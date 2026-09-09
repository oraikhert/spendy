"""Workspace input and public membership-aware representations."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.models.workspace import WorkspaceRole


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class WorkspaceUpdate(WorkspaceCreate):
    pass


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
    username: str
    email: EmailStr
    full_name: str | None = None


class WorkspaceMemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: WorkspaceRole


class WorkspaceInvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_email: EmailStr = Field(max_length=320)
    role: Literal[WorkspaceRole.EDITOR, WorkspaceRole.VIEWER]

    @field_validator("recipient_email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().casefold()


class WorkspaceInvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workspace_id: int
    recipient_email: EmailStr
    role: Literal[WorkspaceRole.EDITOR, WorkspaceRole.VIEWER]
    expires_at: datetime
    inviter_user_id: int
    delivery_state: Literal["pending", "sent", "failed"]
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkspaceInvitationPublic(BaseModel):
    workspace_name: str
    role: Literal[WorkspaceRole.EDITOR, WorkspaceRole.VIEWER]
    masked_recipient_email: str
    expires_at: datetime


class WorkspaceInvitationRegister(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = Field(default=None, max_length=255)
