"""Rename source_events.received_at to transaction_datetime

Revision ID: rename_received_001
Revises: kind_location_001
Create Date: 2026-02-21

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'rename_received_001'
down_revision: Union[str, None] = 'kind_location_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_source_events_type_received', table_name='source_events')
    op.alter_column(
        'source_events',
        'received_at',
        new_column_name='transaction_datetime',
    )
    op.create_index(
        'ix_source_events_type_transaction_datetime',
        'source_events',
        ['source_type', 'transaction_datetime'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_source_events_type_transaction_datetime', table_name='source_events')
    op.alter_column(
        'source_events',
        'transaction_datetime',
        new_column_name='received_at',
    )
    op.create_index(
        'ix_source_events_type_received',
        'source_events',
        ['source_type', 'received_at'],
        unique=False,
    )
