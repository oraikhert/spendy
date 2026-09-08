"""Explicit synthetic ownership for pre-existing financial regression fixtures."""
from datetime import UTC, datetime
from sqlalchemy import select
from app.core.workspace_context import WorkspaceContext, WorkspaceAccessError
from app.models import Workspace, WorkspaceMember, WorkspaceRole, User

CONTEXT = WorkspaceContext(user_id=1, workspace_id=1, role=WorkspaceRole.OWNER)


def seed_workspace(connection):
    now = datetime.now(UTC)
    connection.execute(Workspace.__table__.insert().values(
        id=1, name="Synthetic workspace", status="active", created_at=now, updated_at=now))


async def add_fixture_memberships(db):
    """Call only after explicitly creating fixture users; never a registration hook."""
    await db.flush()
    for user_id in await db.scalars(select(User.id)):
        if await db.scalar(select(WorkspaceMember.id).where(WorkspaceMember.user_id == user_id)) is None:
            db.add(WorkspaceMember(workspace_id=1, user_id=user_id, role="owner" if user_id == 1 else "editor"))
    await db.commit()
