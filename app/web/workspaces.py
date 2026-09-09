"""Server-rendered workspace selection and collaboration."""
from dataclasses import replace
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_current_user_from_cookie_required
from app.core.workspace_context import WorkspaceAccessError
from app.core.workspace_deps import WorkspaceRoute
from app.database import get_db
from app.models import User
from app.models.workspace import WorkspaceRole
from app.schemas.workspace import WorkspaceCreate, WorkspaceDelete, WorkspaceInvitationCreate, WorkspaceUpdate
from app.services import workspace_service
from app.web.security import csrf_token, protected_form
from app.web.transaction_helpers import display_date

router = APIRouter(prefix="/workspaces", tags=["web-workspaces"], route_class=WorkspaceRoute)
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(display_date=display_date)
DB = Annotated[AsyncSession, Depends(get_db)]
ActiveUser = Annotated[User, Depends(get_current_user_from_cookie_required)]


async def page(request, db, user, *, name="", error=None, message=None, status=200):
    # Stable bounded pages, including archived memberships.
    try:
        offset = max(0, min(int(request.query_params.get("offset", "0")), 2147483647))
    except ValueError:
        offset = 0
    workspaces = await workspace_service.list_workspaces(db, user, limit=101, offset=offset)
    request.state.active_workspaces = [workspace for workspace in workspaces if workspace.status == "active"]
    return templates.TemplateResponse(request=request, name="workspaces.html", context={
        "user": user, "workspaces": workspaces[:100], "name": name, "error": error,
        "message": message,
        "csrf_token": csrf_token(request), "next_offset": offset + 100 if len(workspaces) > 100 else None,
    }, status_code=status)


@router.get("")
@router.get("/onboarding")
async def workspace_page(request: Request, db: DB, user: ActiveUser):
    messages = {"archived": "Workspace archived.", "deleted": "Workspace permanently deleted."}
    return await page(
        request, db, user,
        message=messages.get(request.query_params.get("message", "")),
    )


def select_session(request, workspace_id, destination="/dashboard"):
    request.state.web_session = replace(
        request.state.web_session,
        workspace_id=workspace_id,
        workspace_invalidated=False,
    )
    return RedirectResponse(destination, status_code=303)


def lifecycle_redirect(request: Request, destination: str):
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=200, headers={"HX-Redirect": destination})
    return RedirectResponse(destination, status_code=303)


@router.post("")
async def create_workspace(request: Request, db: DB, user: ActiveUser):
    posted = await protected_form(request)
    name = str(posted.get("name", ""))
    try:
        data = WorkspaceCreate(name=name)
    except ValidationError:
        return await page(request, db, user, name=name, error="Enter a workspace name of 1–100 characters.", status=422)
    workspace = await workspace_service.create_workspace(db, user, data)
    return select_session(request, workspace.id)


@router.post("/{workspace_id}/select")
async def select_workspace(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    await protected_form(request)
    context = await workspace_service.resolve_workspace(db, user, workspace_id)
    return select_session(request, context.workspace_id)


@router.post("/select")
async def select_workspace_form(request: Request, db: DB, user: ActiveUser):
    posted = await protected_form(request)
    raw = str(posted.get("workspace_id", ""))
    context = await workspace_service.resolve_workspace(db, user, raw)
    destination = str(posted.get("return_url", "/dashboard"))
    if not destination.startswith("/") or destination.startswith("//"):
        destination = "/dashboard"
    return select_session(request, context.workspace_id, destination)


async def collaboration_page(
    request, db, user, workspace_id, *, error=None, message=None, status=200,
    invite_email="", invite_role="viewer", invite_error=None, confirmation_name="",
    rename_name=None, rename_error=None,
):
    # Workspace mutation services roll back before surfacing business-rule
    # conflicts. SQLAlchemy expires loaded ORM objects on rollback, so refresh
    # the request user explicitly before re-rendering an error response.
    if inspect(user).expired:
        await db.refresh(user)
    workspace = await workspace_service.read_workspace(db, user, workspace_id)
    request.state.active_workspaces = [item for item in await workspace_service.list_workspaces(db, user) if item.status == "active"]
    is_owner = workspace.role is WorkspaceRole.OWNER
    if workspace.status == "active":
        context = await workspace_service.resolve_workspace(db, user, workspace_id)
        request.state.workspace_context = context
        members = await workspace_service.list_members(db, user, workspace_id)
        invitations = await workspace_service.list_invitations(db, user, workspace_id) if is_owner else []
    else:
        members = []
        invitations = []
    return templates.TemplateResponse(request=request, name="workspace_detail.html", context={
        "user": user, "workspace": workspace, "members": members, "invitations": invitations,
        "is_owner": is_owner, "is_archived": workspace.status == "archived",
        "csrf_token": csrf_token(request), "error": error, "message": message,
        "invite_email": invite_email, "invite_role": invite_role,
        "invite_error": invite_error, "confirmation_name": confirmation_name,
        "rename_name": rename_name, "rename_error": rename_error,
    }, status_code=status)


@router.get("/{workspace_id}")
async def workspace_detail(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    messages = {"renamed": "Workspace renamed.", "restored": "Workspace restored.", "role": "Member role updated.", "removed": "Member removed.", "invited": "Invitation sent.", "added": "User added to the workspace.", "resent": "Email resent.", "revoked": "Invitation revoked."}
    return await collaboration_page(request, db, user, workspace_id, message=messages.get(request.query_params.get("message", "")))


@router.post("/{workspace_id}/archive")
async def archive_form(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    await protected_form(request)
    try:
        await workspace_service.archive_workspace(db, user, workspace_id)
    except WorkspaceAccessError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=exc.detail, status=exc.status_code)
    if str(request.state.web_session.workspace_id) == str(workspace_id):
        request.state.web_session = replace(
            request.state.web_session,
            workspace_id=None,
            workspace_invalidated=True,
        )
    return lifecycle_redirect(request, "/workspaces?message=archived")


@router.post("/{workspace_id}/restore")
async def restore_form(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    await protected_form(request)
    try:
        await workspace_service.restore_workspace(db, user, workspace_id)
    except WorkspaceAccessError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=exc.detail, status=exc.status_code)
    return lifecycle_redirect(request, f"/workspaces/{workspace_id}?message=restored")


@router.post("/{workspace_id}/delete")
async def delete_form(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    posted = await protected_form(request)
    confirmation_name = str(posted.get("confirmation_name", ""))
    try:
        data = WorkspaceDelete(confirmation_name=confirmation_name)
    except ValidationError:
        return await collaboration_page(
            request, db, user, workspace_id,
            error="Enter the exact workspace name.", status=422,
            confirmation_name=confirmation_name,
        )
    try:
        await workspace_service.delete_workspace(db, user, workspace_id, data)
    except WorkspaceAccessError as exc:
        return await collaboration_page(
            request, db, user, workspace_id, error=exc.detail,
            status=exc.status_code, confirmation_name=confirmation_name,
        )
    if str(request.state.web_session.workspace_id) == str(workspace_id):
        request.state.web_session = replace(
            request.state.web_session,
            workspace_id=None,
            workspace_invalidated=True,
        )
    return lifecycle_redirect(request, "/workspaces?message=deleted")


@router.post("/{workspace_id}/members/{target_user_id}/role")
async def role_form(workspace_id: int, target_user_id: int, request: Request, db: DB, user: ActiveUser):
    posted = await protected_form(request)
    try:
        role = WorkspaceRole(str(posted.get("role", "")))
    except ValueError:
        return await collaboration_page(request, db, user, workspace_id, error="Choose a valid role.", status=422)
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    try:
        await workspace_service.change_member_role(db, user, workspace_id, target_user_id, role)
    except WorkspaceAccessError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=exc.detail, status=exc.status_code)
    return RedirectResponse(f"/workspaces/{workspace_id}?message=role", status_code=303)


@router.post("/{workspace_id}/rename")
async def rename_form(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    posted = await protected_form(request)
    name = str(posted.get("name", ""))
    try:
        data = WorkspaceUpdate(name=name)
    except ValidationError:
        return await collaboration_page(
            request, db, user, workspace_id, status=422, rename_name=name,
            rename_error="Enter a workspace name of 1–100 characters.",
        )
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    await workspace_service.rename_workspace(db, user, workspace_id, data)
    return RedirectResponse(f"/workspaces/{workspace_id}?message=renamed", status_code=303)


@router.post("/{workspace_id}/members/{target_user_id}/remove")
async def remove_form(workspace_id: int, target_user_id: int, request: Request, db: DB, user: ActiveUser):
    await protected_form(request)
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    try:
        await workspace_service.remove_member(db, user, workspace_id, target_user_id)
    except WorkspaceAccessError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=exc.detail, status=exc.status_code)
    return RedirectResponse(f"/workspaces/{workspace_id}?message=removed", status_code=303)


@router.post("/{workspace_id}/leave")
async def leave_form(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    await protected_form(request)
    await workspace_service.resolve_workspace(db, user, workspace_id)
    try:
        await workspace_service.leave_workspace(db, user, workspace_id)
    except WorkspaceAccessError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=exc.detail, status=exc.status_code)
    return select_session(request, None, "/workspaces")


@router.post("/{workspace_id}/invitations")
async def invite_form(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    posted = await protected_form(request)
    email, role = str(posted.get("recipient_email", "")), str(posted.get("role", "viewer"))
    try:
        data = WorkspaceInvitationCreate(recipient_email=email, role=role)
    except ValidationError:
        return await collaboration_page(
            request, db, user, workspace_id, status=422, invite_email=email,
            invite_role=role, invite_error="Enter a valid email and choose editor or viewer.",
        )
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    try:
        invitation = await workspace_service.create_invitation(db, user, workspace_id, data)
        message = "added" if invitation.accepted_at is not None else "invited"
        return RedirectResponse(f"/workspaces/{workspace_id}?message={message}", status_code=303)
    except workspace_service.InvitationDeliveryError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=f"{exc}. You can retry it.", status=502, invite_email=email, invite_role=role)
    except WorkspaceAccessError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=exc.detail, status=exc.status_code, invite_email=email, invite_role=role)


@router.post("/{workspace_id}/invitations/{invitation_id}/resend")
async def resend_form(workspace_id: int, invitation_id: int, request: Request, db: DB, user: ActiveUser):
    await protected_form(request)
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    try:
        await workspace_service.resend_invitation(db, user, workspace_id, invitation_id)
        return RedirectResponse(f"/workspaces/{workspace_id}?message=resent", status_code=303)
    except workspace_service.InvitationDeliveryError:
        return await collaboration_page(request, db, user, workspace_id, error="The new link was saved, but email delivery failed. You can retry it.", status=502)
    except WorkspaceAccessError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=exc.detail, status=exc.status_code)


@router.post("/{workspace_id}/invitations/{invitation_id}/revoke")
async def revoke_form(workspace_id: int, invitation_id: int, request: Request, db: DB, user: ActiveUser):
    await protected_form(request)
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    try:
        await workspace_service.revoke_invitation(db, user, workspace_id, invitation_id)
    except WorkspaceAccessError as exc:
        return await collaboration_page(request, db, user, workspace_id, error=exc.detail, status=exc.status_code)
    return RedirectResponse(f"/workspaces/{workspace_id}?message=revoked", status_code=303)
