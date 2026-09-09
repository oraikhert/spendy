"""Workspace ownership and collaboration JSON endpoints."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_current_active_user
from app.core.workspace_deps import WorkspaceRoute
from app.database import get_db
from app.models import User
from app.schemas.user import User as UserResponse
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceInvitationCreate,
    WorkspaceInvitationPublic,
    WorkspaceInvitationRegister,
    WorkspaceInvitationResponse,
    WorkspaceMemberResponse,
    WorkspaceMemberRoleUpdate,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"], route_class=WorkspaceRoute)
invitation_router = APIRouter(prefix="/workspace-invitations", tags=["workspace-invitations"], route_class=WorkspaceRoute)
DB = Annotated[AsyncSession, Depends(get_db)]
ActiveUser = Annotated[User, Depends(get_current_active_user)]


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(db: DB, user: ActiveUser, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    return await workspace_service.list_workspaces(db, user, limit=limit, offset=offset)


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(data: WorkspaceCreate, db: DB, user: ActiveUser):
    return await workspace_service.create_workspace(db, user, data)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def read_workspace(workspace_id: int, db: DB, user: ActiveUser):
    return await workspace_service.read_workspace(db, user, workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def rename_workspace(workspace_id: int, data: WorkspaceUpdate, db: DB, user: ActiveUser):
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    return await workspace_service.rename_workspace(db, user, workspace_id, data)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
async def list_members(workspace_id: int, db: DB, user: ActiveUser, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    return await workspace_service.list_members(db, user, workspace_id, limit=limit, offset=offset)


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberResponse)
async def change_member_role(workspace_id: int, user_id: int, data: WorkspaceMemberRoleUpdate, db: DB, user: ActiveUser):
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    return await workspace_service.change_member_role(db, user, workspace_id, user_id, data.role)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(workspace_id: int, user_id: int, db: DB, user: ActiveUser):
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    await workspace_service.remove_member(db, user, workspace_id, user_id)


@router.post("/{workspace_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_workspace(workspace_id: int, db: DB, user: ActiveUser):
    await workspace_service.resolve_workspace(db, user, workspace_id)
    await workspace_service.leave_workspace(db, user, workspace_id)


@router.get("/{workspace_id}/invitations", response_model=list[WorkspaceInvitationResponse])
async def list_invitations(workspace_id: int, db: DB, user: ActiveUser, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    return await workspace_service.list_invitations(db, user, workspace_id, limit=limit, offset=offset)


@router.post("/{workspace_id}/invitations", response_model=WorkspaceInvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(workspace_id: int, data: WorkspaceInvitationCreate, db: DB, user: ActiveUser):
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    try:
        return await workspace_service.create_invitation(db, user, workspace_id, data)
    except workspace_service.InvitationDeliveryError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/{workspace_id}/invitations/{invitation_id}/resend", response_model=WorkspaceInvitationResponse)
async def resend_invitation(workspace_id: int, invitation_id: int, db: DB, user: ActiveUser):
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    try:
        return await workspace_service.resend_invitation(db, user, workspace_id, invitation_id)
    except workspace_service.InvitationDeliveryError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.delete("/{workspace_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(workspace_id: int, invitation_id: int, db: DB, user: ActiveUser):
    (await workspace_service.resolve_workspace(db, user, workspace_id)).require_admin()
    await workspace_service.revoke_invitation(db, user, workspace_id, invitation_id)


@invitation_router.get("/{token}", response_model=WorkspaceInvitationPublic)
async def inspect_invitation(token: str, db: DB):
    return await workspace_service.inspect_invitation(db, token)


@invitation_router.post("/{token}/accept", response_model=WorkspaceMemberResponse, status_code=status.HTTP_201_CREATED)
async def accept_invitation(token: str, db: DB, user: ActiveUser):
    return await workspace_service.accept_invitation(db, user, token)


@invitation_router.post("/{token}/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_from_invitation(token: str, data: WorkspaceInvitationRegister, db: DB):
    try:
        return await workspace_service.register_from_invitation(db, token, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
