"""Add account timezone and optional card timezone override.

Revision ID: account_card_timezone_001
Revises: payload_obs_001
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "account_card_timezone_001"
down_revision: Union[str, None] = "payload_obs_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "timezone",
                sa.String(length=64),
                nullable=False,
                server_default="UTC",
            )
        )
    with op.batch_alter_table("cards") as batch_op:
        batch_op.add_column(sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cards") as batch_op:
        batch_op.drop_column("timezone")
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("timezone")
