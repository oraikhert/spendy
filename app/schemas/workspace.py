"""Workspace input and public membership-aware representations."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.models.workspace import WorkspaceRole


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    status: Literal["active", "archived"]
    role: WorkspaceRole
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class WorkspaceMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    workspace_id: int
    role: WorkspaceRole
    joined_at: datetime
    created_at: datetime
    updated_at: datetime
