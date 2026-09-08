"""Explicit workspace onboarding and membership-scoped reads."""
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_current_active_user
from app.core.workspace_deps import WorkspaceRoute
from app.database import get_db
from app.models import User
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"], route_class=WorkspaceRoute)
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
