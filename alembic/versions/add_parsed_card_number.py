"""Add parsed_card_number to source_events

Revision ID: parsed_card_001
Revises: trans001
Create Date: 2026-02-10 12:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'parsed_card_001'
down_revision: Union[str, None] = 'trans001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('source_events', sa.Column('parsed_card_number', sa.String(length=4), nullable=True))

def downgrade() -> None:
    op.drop_column('source_events', 'parsed_card_number')
