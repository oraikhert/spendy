"""JSON and signed-cookie workspace selection dependencies."""
from dataclasses import replace
from typing import Annotated
from fastapi import Depends, Header, HTTPException, Request
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_current_active_user, get_current_user_from_cookie_required
from app.core.workspace_context import WorkspaceAccessError, WorkspaceContext
from app.database import get_db
from app.models import User
from app.services.workspace_service import list_workspaces, resolve_workspace


class WorkspaceRoute(APIRoute):
    """Map domain authorization errors even in apps mounting individual routers."""
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handle(request):
            try:
                return await original(request)
            except WorkspaceAccessError as exc:
                raise HTTPException(exc.status_code, exc.detail) from exc
        return handle


async def get_api_workspace(
    user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    selection: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
) -> WorkspaceContext:
    try:
        return await resolve_workspace(db, user, selection)
    except WorkspaceAccessError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


async def get_api_workspace_write(
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)],
) -> WorkspaceContext:
    context.require_write()
    return context


async def get_web_workspace(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceContext:
    selection = request.state.web_session.workspace_id
    if request.state.web_session.workspace_invalidated:
        destination = "/workspaces"
        headers = {"Location": destination}
        if request.headers.get("HX-Request") == "true":
            headers["HX-Redirect"] = destination
        raise HTTPException(303, "Select a workspace", headers=headers)
    try:
        context = await resolve_workspace(db, user, selection)
    except WorkspaceAccessError as exc:
        if selection is not None:
            request.state.web_session = replace(
                request.state.web_session,
                workspace_id=None,
                workspace_invalidated=True,
            )
        destination = "/workspaces/onboarding" if exc.detail == "Workspace required" else "/workspaces"
        headers = {"Location": destination}
        if request.headers.get("HX-Request") == "true":
            headers["HX-Redirect"] = destination
        raise HTTPException(303, "Select a workspace", headers=headers) from exc
    request.state.workspace_context = context
    request.state.active_workspaces = [
        workspace for workspace in await list_workspaces(db, user, limit=100)
        if workspace.status == "active"
    ]
    return context


async def get_web_workspace_write(
    context: Annotated[WorkspaceContext, Depends(get_web_workspace)],
) -> WorkspaceContext:
    context.require_write()
    return context
