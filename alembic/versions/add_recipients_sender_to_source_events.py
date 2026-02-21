"""Add recipients and sender to source_events

Revision ID: recipients_sender_001
Revises: rename_received_001
Create Date: 2026-02-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'recipients_sender_001'
down_revision: Union[str, None] = 'rename_received_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('source_events', sa.Column('recipients', sa.String(length=500), nullable=True))
    op.add_column('source_events', sa.Column('sender', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('source_events', 'sender')
    op.drop_column('source_events', 'recipients')
