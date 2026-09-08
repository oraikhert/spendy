"""Workspace ownership and selection. Creation owns its atomic commit."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workspace_context import WorkspaceAccessError, WorkspaceContext
from app.models import User, Workspace, WorkspaceMember, WorkspaceRole
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse


def _response(workspace, role):
    return WorkspaceResponse(
        id=workspace.id, name=workspace.name, status=workspace.status, role=role,
        created_at=workspace.created_at, updated_at=workspace.updated_at,
        archived_at=workspace.archived_at,
    )


async def list_workspaces(db: AsyncSession, user: User, *, limit=100, offset=0):
    rows = await db.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.id).limit(limit).offset(offset)
    )
    return [_response(workspace, role) for workspace, role in rows]


async def read_workspace(db: AsyncSession, user: User, workspace_id: int):
    if not 0 < workspace_id <= 2147483647:
        raise WorkspaceAccessError(404, "Not Found")
    row = (await db.execute(
        select(Workspace, WorkspaceMember.role).join(WorkspaceMember)
        .where(Workspace.id == workspace_id, WorkspaceMember.user_id == user.id)
    )).one_or_none()
    if row is None:
        raise WorkspaceAccessError(404, "Not Found")
    return _response(*row)


async def create_workspace(db: AsyncSession, user: User, data: WorkspaceCreate):
    if not user.is_active:
        raise WorkspaceAccessError(403, "Forbidden")
    workspace = Workspace(name=data.name, created_by_user_id=user.id)
    try:
        db.add(workspace)
        await db.flush()
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER))
        await db.commit()
        await db.refresh(workspace)
    except Exception:
        await db.rollback()
        raise
    return _response(workspace, WorkspaceRole.OWNER)


async def resolve_workspace(db: AsyncSession, user: User, selection: str | int | None):
    if not user.is_active:
        raise WorkspaceAccessError(403, "Forbidden")
    if selection is not None:
        raw = str(selection)
        if len(raw) > 10 or not raw.isascii() or not raw.isdecimal() or not 0 < int(raw) <= 2147483647:
            raise WorkspaceAccessError(404, "Not Found")
        workspace = await read_workspace(db, user, int(raw))
        if workspace.status != "active":
            raise WorkspaceAccessError(409, "Workspace archived")
        return WorkspaceContext(user.id, workspace.id, WorkspaceRole(workspace.role), workspace.name)
    rows = (await db.execute(
        select(Workspace.id, WorkspaceMember.role, Workspace.name).join(WorkspaceMember)
        .where(WorkspaceMember.user_id == user.id, Workspace.status == "active")
        .order_by(Workspace.id).limit(2)
    )).all()
    if not rows:
        raise WorkspaceAccessError(409, "Workspace required")
    if len(rows) > 1:
        raise WorkspaceAccessError(409, "Workspace selection required")
    return WorkspaceContext(user.id, rows[0].id, WorkspaceRole(rows[0].role), rows[0].name)


async def assign_legacy_owner(db: AsyncSession, workspace_id: int, user_id: int):
    """Operator-only recovery, guarded against replacing an existing owner."""
    # A write lock also serializes concurrent recovery attempts on SQLite.
    from sqlalchemy import update
    await db.execute(update(Workspace).where(Workspace.id == workspace_id).values(id=Workspace.id))
    workspace = await db.get(Workspace, workspace_id)
    user = await db.get(User, user_id)
    if workspace is None or workspace.name != "Legacy Workspace" or workspace.created_by_user_id is not None:
        raise ValueError("Choose an ownerless Legacy Workspace")
    if user is None or not user.is_active:
        raise ValueError("Choose an existing active user")
    owner = await db.scalar(select(WorkspaceMember.id).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner"))
    if owner is not None:
        raise ValueError("The workspace already has an owner")
    member = await db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id))
    if member is None:
        db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role="owner"))
    else:
        member.role = "owner"
    await db.commit()
