"""Add workspace invitations.

Revision ID: workspace_collaboration_002
Revises: workspace_ownership_001
"""
from alembic import op
import sqlalchemy as sa

revision = "workspace_collaboration_002"
down_revision = "workspace_ownership_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inviter_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delivery_state", sa.String(20), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('editor', 'viewer')", name="ck_workspace_invitation_role"),
        sa.CheckConstraint("delivery_state IN ('pending', 'sent', 'failed')", name="ck_workspace_invitation_delivery"),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitations_token_hash"),
    )
    op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"])
    op.create_index(
        "uq_workspace_invitation_actionable_recipient",
        "workspace_invitations", ["workspace_id", "recipient_email"], unique=True,
        sqlite_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade():
    op.drop_table("workspace_invitations")
