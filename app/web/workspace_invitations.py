"""Public invitation landing and authenticated acceptance/registration flows."""
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_from_cookie, get_current_user_from_cookie_required
from app.core.web_session import set_auth_cookie
from app.core.workspace_context import WorkspaceAccessError
from app.core.workspace_deps import WorkspaceRoute
from app.database import get_db
from app.models import User
from app.schemas.workspace import WorkspaceInvitationRegister
from app.services import auth_service, workspace_service
from app.web.security import csrf_token, protected_form

router = APIRouter(
    prefix="/workspace-invitations",
    tags=["web-workspace-invitations"],
    route_class=WorkspaceRoute,
)
templates = Jinja2Templates(directory="app/templates")
DB = Annotated[AsyncSession, Depends(get_db)]


def unavailable_response(request: Request, error: WorkspaceAccessError):
    return templates.TemplateResponse(
        request=request,
        name="workspace_invitation_unavailable.html",
        context={"error": error.detail},
        status_code=error.status_code,
    )


async def landing_response(request, db, token, user=None, *, error=None, status=200, values=None):
    invitation = await workspace_service.inspect_invitation(db, token)
    return templates.TemplateResponse(request=request, name="workspace_invitation.html", context={
        "user": user, "invitation": invitation, "token": token, "csrf_token": csrf_token(request),
        "error": error, "values": values or {},
    }, status_code=status)


@router.get("/{token}")
async def invitation_landing(request: Request, token: str, db: DB, user: Annotated[User | None, Depends(get_current_user_from_cookie)]):
    try:
        return await landing_response(request, db, token, user)
    except WorkspaceAccessError as exc:
        return unavailable_response(request, exc)


@router.post("/{token}/accept")
async def invitation_accept(request: Request, token: str, db: DB, user: Annotated[User, Depends(get_current_user_from_cookie_required)]):
    await protected_form(request)
    try:
        member = await workspace_service.accept_invitation(db, user, token)
    except WorkspaceAccessError as exc:
        return unavailable_response(request, exc)
    request.state.web_session = replace(request.state.web_session, workspace_id=member.workspace_id)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/{token}/register")
async def invitation_register_page(request: Request, token: str, db: DB, user: Annotated[User | None, Depends(get_current_user_from_cookie)]):
    if user is not None:
        return RedirectResponse(f"/workspace-invitations/{token}", status_code=303)
    try:
        return await landing_response(request, db, token)
    except WorkspaceAccessError as exc:
        return unavailable_response(request, exc)


@router.post("/{token}/register")
async def invitation_register(request: Request, token: str, db: DB):
    posted = await protected_form(request)
    values = {key: str(posted.get(key, "")) for key in ("username", "full_name")}
    if posted.get("password") != posted.get("password_confirm"):
        return await landing_response(request, db, token, error="Passwords do not match.", status=422, values=values)
    try:
        data = WorkspaceInvitationRegister(
            username=posted.get("username", ""), password=posted.get("password", ""),
            full_name=posted.get("full_name") or None,
        )
        user = await workspace_service.register_from_invitation(db, token, data)
    except WorkspaceAccessError as exc:
        return unavailable_response(request, exc)
    except (ValidationError, ValueError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "Review the registration fields."
        return await landing_response(request, db, token, error=message, status=422, values=values)
    token_response = await auth_service.create_user_access_token(user)
    response = RedirectResponse("/dashboard", status_code=303)
    set_auth_cookie(response, token_response.access_token, request)
    # The middleware cannot renew a session that was created after dependencies ran;
    # set the selected workspace in a second signed token immediately.
    from app.core.security import decode_access_token, create_access_token
    claims = decode_access_token(token_response.access_token) or {}
    selected = await workspace_service.resolve_workspace(db, user, None)
    selected_token = create_access_token({
        "sub": str(user.id), "username": user.username, "sid": claims.get("sid"),
        "workspace_id": selected.workspace_id,
    })
    set_auth_cookie(response, selected_token, request)
    return response
