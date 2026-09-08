"""Minimal server-rendered onboarding, creation and signed-session selection."""
from dataclasses import replace
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_current_user_from_cookie_required
from app.core.workspace_deps import WorkspaceRoute
from app.core.web_session import browser_origin
from app.database import get_db
from app.models import User
from app.schemas.workspace import WorkspaceCreate
from app.services import workspace_service
from app.web.transaction_helpers import csrf_token, valid_csrf

router = APIRouter(prefix="/workspaces", route_class=WorkspaceRoute)
templates = Jinja2Templates(directory="app/templates")
DB = Annotated[AsyncSession, Depends(get_db)]
ActiveUser = Annotated[User, Depends(get_current_user_from_cookie_required)]


async def page(request, db, user, *, name="", error=None, status=200):
    # Stable bounded pages, including archived memberships.
    try:
        offset = max(0, min(int(request.query_params.get("offset", "0")), 2147483647))
    except ValueError:
        offset = 0
    workspaces = await workspace_service.list_workspaces(db, user, limit=101, offset=offset)
    return templates.TemplateResponse(request=request, name="workspaces.html", context={
        "user": user, "workspaces": workspaces[:100], "name": name, "error": error,
        "csrf_token": csrf_token(request), "next_offset": offset + 100 if len(workspaces) > 100 else None,
    }, status_code=status)


@router.get("")
@router.get("/onboarding")
async def workspace_page(request: Request, db: DB, user: ActiveUser):
    return await page(request, db, user)


async def form(request):
    posted = await request.form()
    origin = request.headers.get("origin")
    if (origin and origin != browser_origin(request)) or not valid_csrf(request, posted.get("csrf_token")):
        raise HTTPException(403, "Invalid form token")
    return posted


def select_session(request, workspace_id):
    request.state.web_session = replace(request.state.web_session, workspace_id=workspace_id)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("")
async def create_workspace(request: Request, db: DB, user: ActiveUser):
    posted = await form(request)
    name = str(posted.get("name", ""))
    try:
        data = WorkspaceCreate(name=name)
    except ValidationError:
        return await page(request, db, user, name=name, error="Enter a workspace name of 1–100 characters.", status=422)
    workspace = await workspace_service.create_workspace(db, user, data)
    return select_session(request, workspace.id)


@router.post("/{workspace_id}/select")
async def select_workspace(workspace_id: int, request: Request, db: DB, user: ActiveUser):
    await form(request)
    context = await workspace_service.resolve_workspace(db, user, workspace_id)
    return select_session(request, context.workspace_id)
