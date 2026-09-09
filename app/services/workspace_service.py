"""Workspace ownership, collaboration, invitation and selection services."""
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.workspace_context import WorkspaceAccessError, WorkspaceContext
from app.models import User, Workspace, WorkspaceInvitation, WorkspaceMember, WorkspaceRole
from app.schemas.user import UserCreate
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceInvitationCreate,
    WorkspaceInvitationPublic,
    WorkspaceInvitationRegister,
    WorkspaceInvitationResponse,
    WorkspaceMemberResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services import user_service
from app.services.invitation_delivery import send_workspace_invitation


class InvitationDeliveryError(Exception):
    def __init__(self, invitation: WorkspaceInvitationResponse):
        self.invitation = invitation
        super().__init__("Invitation saved, but email delivery failed")


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


async def rename_workspace(db: AsyncSession, user: User, workspace_id: int, data: WorkspaceUpdate) -> WorkspaceResponse:
    try:
        workspace = await _lock_active_workspace(db, workspace_id)
        member = await _require_locked_owner(db, workspace_id, user.id)
        workspace.name = data.name
        await db.commit()
        return _response(workspace, member.role)
    except Exception:
        await db.rollback()
        raise


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


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _normalize_email(value: str) -> str:
    return value.strip().casefold()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _member_response(member: WorkspaceMember, user: User) -> WorkspaceMemberResponse:
    return WorkspaceMemberResponse(
        user_id=user.id,
        workspace_id=member.workspace_id,
        role=member.role,
        joined_at=member.joined_at,
        created_at=member.created_at,
        updated_at=member.updated_at,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
    )


async def _lock_active_workspace(db: AsyncSession, workspace_id: int) -> Workspace:
    # The harmless write serializes competing owner/invitation changes on SQLite;
    # PostgreSQL also takes a row lock. It deliberately bypasses ORM onupdate.
    result = await db.execute(
        text("UPDATE workspaces SET id = id WHERE id = :workspace_id AND status = 'active'"),
        {"workspace_id": workspace_id},
    )
    if result.rowcount != 1:
        workspace = await db.get(Workspace, workspace_id)
        if workspace is None:
            raise WorkspaceAccessError(404, "Not Found")
        raise WorkspaceAccessError(409, "Workspace archived")
    workspace = await db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    assert workspace is not None
    return workspace


async def _locked_membership(db: AsyncSession, workspace_id: int, user_id: int) -> WorkspaceMember:
    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        ).with_for_update()
    )
    if member is None:
        raise WorkspaceAccessError(404, "Not Found")
    return member


async def _require_locked_owner(db: AsyncSession, workspace_id: int, user_id: int) -> WorkspaceMember:
    member = await _locked_membership(db, workspace_id, user_id)
    if member.role != WorkspaceRole.OWNER:
        raise WorkspaceAccessError(403, "Forbidden")
    return member


async def list_members(db: AsyncSession, user: User, workspace_id: int, *, limit=100, offset=0):
    await read_workspace(db, user, workspace_id)
    rows = await db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(User.username, User.id).limit(limit).offset(offset)
    )
    return [_member_response(member, member_user) for member, member_user in rows]


async def change_member_role(
    db: AsyncSession, user: User, workspace_id: int, target_user_id: int, role: WorkspaceRole
) -> WorkspaceMemberResponse:
    try:
        await _lock_active_workspace(db, workspace_id)
        await _require_locked_owner(db, workspace_id, user.id)
        target = await _locked_membership(db, workspace_id, target_user_id)
        if target.role == WorkspaceRole.OWNER and role != WorkspaceRole.OWNER:
            owners = await db.scalar(select(func.count()).select_from(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            ))
            if owners == 1:
                raise WorkspaceAccessError(409, "The final owner cannot be demoted")
        target.role = role
        await db.commit()
        target_user = await db.get(User, target.user_id)
        assert target_user is not None
        return _member_response(target, target_user)
    except Exception:
        await db.rollback()
        raise


async def remove_member(db: AsyncSession, user: User, workspace_id: int, target_user_id: int) -> None:
    try:
        await _lock_active_workspace(db, workspace_id)
        await _require_locked_owner(db, workspace_id, user.id)
        target = await _locked_membership(db, workspace_id, target_user_id)
        if target.role == WorkspaceRole.OWNER:
            owners = await db.scalar(select(func.count()).select_from(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            ))
            if owners == 1:
                raise WorkspaceAccessError(409, "The final owner cannot be removed")
        await db.delete(target)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def leave_workspace(db: AsyncSession, user: User, workspace_id: int) -> None:
    try:
        await _lock_active_workspace(db, workspace_id)
        member = await _locked_membership(db, workspace_id, user.id)
        if member.role == WorkspaceRole.OWNER:
            owners = await db.scalar(select(func.count()).select_from(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            ))
            if owners == 1:
                raise WorkspaceAccessError(409, "The final owner cannot leave")
        await db.delete(member)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def _owner_for_invitations(db: AsyncSession, user: User, workspace_id: int, *, lock=False) -> Workspace:
    if lock:
        workspace = await _lock_active_workspace(db, workspace_id)
        await _require_locked_owner(db, workspace_id, user.id)
        return workspace
    workspace = await db.get(Workspace, workspace_id)
    if workspace is None:
        raise WorkspaceAccessError(404, "Not Found")
    if workspace.status != "active":
        raise WorkspaceAccessError(409, "Workspace archived")
    member = await db.scalar(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id))
    if member is None:
        raise WorkspaceAccessError(404, "Not Found")
    if member.role != WorkspaceRole.OWNER:
        raise WorkspaceAccessError(403, "Forbidden")
    return workspace


async def list_invitations(db: AsyncSession, user: User, workspace_id: int, *, limit=100, offset=0):
    await _owner_for_invitations(db, user, workspace_id)
    rows = await db.scalars(select(WorkspaceInvitation).where(
        WorkspaceInvitation.workspace_id == workspace_id
    ).order_by(WorkspaceInvitation.id.desc()).limit(limit).offset(offset))
    return [WorkspaceInvitationResponse.model_validate(row) for row in rows]


async def _record_delivery(
    db: AsyncSession, invitation_id: int, expected_hash: str, *, recipient: str,
    workspace_name: str, role: str, token: str,
) -> WorkspaceInvitationResponse:
    try:
        await send_workspace_invitation(recipient, workspace_name, role, token)
        state = "sent"
    except Exception:
        state = "failed"
    await db.execute(update(WorkspaceInvitation).where(
        WorkspaceInvitation.id == invitation_id,
        WorkspaceInvitation.token_hash == expected_hash,
        WorkspaceInvitation.accepted_at.is_(None),
        WorkspaceInvitation.revoked_at.is_(None),
    ).values(delivery_state=state, updated_at=_now()))
    await db.commit()
    invitation = await db.get(WorkspaceInvitation, invitation_id)
    assert invitation is not None
    response = WorkspaceInvitationResponse.model_validate(invitation)
    if state == "failed":
        raise InvitationDeliveryError(response)
    return response


async def create_invitation(
    db: AsyncSession, user: User, workspace_id: int, data: WorkspaceInvitationCreate
) -> WorkspaceInvitationResponse:
    token = secrets.token_urlsafe(32)
    digest = _token_hash(token)
    now = _now()
    email = _normalize_email(str(data.recipient_email))
    try:
        workspace = await _owner_for_invitations(db, user, workspace_id, lock=True)
        existing_user_id = await db.scalar(select(User.id).where(func.lower(User.email) == email))
        if existing_user_id is not None and await db.scalar(select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == existing_user_id,
        )) is not None:
            raise WorkspaceAccessError(409, "This user is already a member")
        await db.execute(update(WorkspaceInvitation).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.recipient_email == email,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
            WorkspaceInvitation.expires_at <= now,
        ).values(revoked_at=now, updated_at=now))
        existing = await db.scalar(select(WorkspaceInvitation.id).where(
            WorkspaceInvitation.workspace_id == workspace_id,
            WorkspaceInvitation.recipient_email == email,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.revoked_at.is_(None),
        ))
        if existing is not None:
            raise WorkspaceAccessError(409, "An invitation is already pending for this email")
        invitation = WorkspaceInvitation(
            workspace_id=workspace_id,
            recipient_email=email,
            role=data.role,
            token_hash=digest,
            expires_at=now + timedelta(days=settings.WORKSPACE_INVITATION_LIFETIME_DAYS),
            inviter_user_id=user.id,
            delivery_state="pending",
        )
        db.add(invitation)
        await db.commit()
        invitation_id = invitation.id
        workspace_name = workspace.name
    except IntegrityError as exc:
        await db.rollback()
        raise WorkspaceAccessError(409, "An invitation is already pending for this email") from exc
    except Exception:
        await db.rollback()
        raise
    return await _record_delivery(
        db, invitation_id, digest, recipient=email, workspace_name=workspace_name,
        role=str(data.role), token=token,
    )


async def resend_invitation(
    db: AsyncSession, user: User, workspace_id: int, invitation_id: int
) -> WorkspaceInvitationResponse:
    token = secrets.token_urlsafe(32)
    digest = _token_hash(token)
    now = _now()
    try:
        workspace = await _owner_for_invitations(db, user, workspace_id, lock=True)
        invitation = await db.scalar(select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_id,
        ).with_for_update())
        if invitation is None:
            raise WorkspaceAccessError(404, "Not Found")
        if invitation.accepted_at is not None or invitation.revoked_at is not None:
            raise WorkspaceAccessError(409, "Invitation is no longer actionable")
        invitation.token_hash = digest
        invitation.expires_at = now + timedelta(days=settings.WORKSPACE_INVITATION_LIFETIME_DAYS)
        invitation.delivery_state = "pending"
        await db.commit()
        recipient, role, workspace_name = invitation.recipient_email, invitation.role, workspace.name
    except Exception:
        await db.rollback()
        raise
    return await _record_delivery(
        db, invitation_id, digest, recipient=recipient, workspace_name=workspace_name,
        role=role, token=token,
    )


async def revoke_invitation(db: AsyncSession, user: User, workspace_id: int, invitation_id: int) -> None:
    try:
        await _owner_for_invitations(db, user, workspace_id, lock=True)
        invitation = await db.scalar(select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id,
            WorkspaceInvitation.workspace_id == workspace_id,
        ).with_for_update())
        if invitation is None:
            raise WorkspaceAccessError(404, "Not Found")
        if invitation.accepted_at is not None or invitation.revoked_at is not None:
            raise WorkspaceAccessError(409, "Invitation is no longer actionable")
        invitation.revoked_at = _now()
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def _invitation_from_token(db: AsyncSession, token: str) -> WorkspaceInvitation:
    if not token or len(token) > 256 or not token.isascii():
        raise WorkspaceAccessError(404, "Invitation not found")
    digest = _token_hash(token)
    invitation = await db.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == digest))
    if invitation is None or not hmac.compare_digest(invitation.token_hash, digest):
        raise WorkspaceAccessError(404, "Invitation not found")
    return invitation


def _validate_invitation(invitation: WorkspaceInvitation, workspace: Workspace) -> None:
    if workspace.status != "active":
        raise WorkspaceAccessError(409, "Workspace archived")
    if invitation.revoked_at is not None:
        raise WorkspaceAccessError(409, "Invitation revoked")
    if invitation.accepted_at is not None:
        raise WorkspaceAccessError(409, "Invitation already accepted")
    if _aware(invitation.expires_at) <= _now():
        raise WorkspaceAccessError(410, "Invitation expired")


def _masked_email(email: str) -> str:
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


async def inspect_invitation(db: AsyncSession, token: str) -> WorkspaceInvitationPublic:
    invitation = await _invitation_from_token(db, token)
    workspace = await db.get(Workspace, invitation.workspace_id)
    if workspace is None:
        raise WorkspaceAccessError(404, "Invitation not found")
    _validate_invitation(invitation, workspace)
    return WorkspaceInvitationPublic(
        workspace_name=workspace.name,
        role=invitation.role,
        masked_recipient_email=_masked_email(invitation.recipient_email),
        expires_at=invitation.expires_at,
    )


async def _lock_token_invitation(db: AsyncSession, token: str) -> tuple[WorkspaceInvitation, Workspace]:
    initial = await _invitation_from_token(db, token)
    workspace = await _lock_active_workspace(db, initial.workspace_id)
    invitation = await db.scalar(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.id == initial.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if invitation is None or not hmac.compare_digest(invitation.token_hash, _token_hash(token)):
        raise WorkspaceAccessError(404, "Invitation not found")
    _validate_invitation(invitation, workspace)
    return invitation, workspace


async def accept_invitation(db: AsyncSession, user: User, token: str) -> WorkspaceMemberResponse:
    try:
        invitation, _workspace = await _lock_token_invitation(db, token)
        if _normalize_email(user.email) != invitation.recipient_email:
            raise WorkspaceAccessError(403, "Invitation email does not match the signed-in user")
        if await db.scalar(select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == invitation.workspace_id,
            WorkspaceMember.user_id == user.id,
        )) is not None:
            raise WorkspaceAccessError(409, "User is already a member")
        member = WorkspaceMember(
            workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role)
        db.add(member)
        invitation.accepted_at = _now()
        await db.commit()
        await db.refresh(member)
        return _member_response(member, user)
    except Exception:
        await db.rollback()
        raise


async def register_from_invitation(
    db: AsyncSession, token: str, data: WorkspaceInvitationRegister
) -> User:
    try:
        invitation, _workspace = await _lock_token_invitation(db, token)
        user = await user_service.prepare_user(UserCreate(
            email=invitation.recipient_email,
            username=data.username,
            password=data.password,
            full_name=data.full_name,
        ), db)
        db.add(WorkspaceMember(
            workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role))
        invitation.accepted_at = _now()
        await db.commit()
        await db.refresh(user)
        return user
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError("Email or username already registered") from exc
    except Exception:
        await db.rollback()
        raise
