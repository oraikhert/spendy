"""Workspace ownership and collaboration records."""
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, declared_attr

from app.database import Base


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    creator = relationship("User", foreign_keys=[created_by_user_id])
    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    invitations: Mapped[list["WorkspaceInvitation"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    accounts = relationship("Account", back_populates="workspace")
    cards = relationship("Card", back_populates="workspace")
    transactions = relationship("Transaction", back_populates="workspace")
    source_payloads = relationship("SourcePayload", back_populates="workspace")
    transaction_observations = relationship("TransactionObservation", back_populates="workspace")
    bank_statement_details = relationship("BankStatementDetail", back_populates="workspace")
    transaction_source_links = relationship("TransactionSourceLink", back_populates="workspace")
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_workspace_status"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 100", name="ck_workspace_name"),
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user = relationship("User", back_populates="workspace_memberships")
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_workspace_member_role"),
    )


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inviter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    workspace: Mapped[Workspace] = relationship(back_populates="invitations")
    inviter = relationship("User", foreign_keys=[inviter_user_id], back_populates="workspace_invitations_sent")
    __table_args__ = (
        CheckConstraint("role IN ('editor', 'viewer')", name="ck_workspace_invitation_role"),
        CheckConstraint("delivery_state IN ('pending', 'sent', 'failed')", name="ck_workspace_invitation_delivery"),
        Index(
            "uq_workspace_invitation_actionable_recipient",
            "workspace_id", "recipient_email", unique=True,
            sqlite_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )


class WorkspaceOwned:
    """Ownership is mandatory; services supply it from their explicit context."""
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)

    @declared_attr
    def workspace(cls):
        return relationship("Workspace", foreign_keys=[cls.workspace_id], back_populates=cls.__tablename__)
