"""Explicit immutable service authorization; no ambient workspace or session state."""
from dataclasses import dataclass

from sqlalchemy import inspect, select

from app.models.workspace import WorkspaceRole


class WorkspaceAccessError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class WorkspaceContext:
    user_id: int
    workspace_id: int
    role: WorkspaceRole
    workspace_name: str = ""

    def require_write(self) -> None:
        if self.role not in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
            raise WorkspaceAccessError(403, "Forbidden")

    def require_record(self, record) -> None:
        if record.workspace_id != self.workspace_id:
            raise WorkspaceAccessError(404, "Not Found")


async def workspace_get(db, model, record_id, *, context: WorkspaceContext):
    """Always query ownership, even when a foreign object is in the identity map."""
    key = inspect(model).primary_key[0]
    return await db.scalar(select(model).where(key == record_id, model.workspace_id == context.workspace_id))
