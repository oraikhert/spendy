"""Drop parsed_original_amount and parsed_original_currency from source_events

Revision ID: drop_orig_001
Revises: parsed_card_001
Create Date: 2026-02-11

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'drop_orig_001'
down_revision: Union[str, None] = 'parsed_card_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('source_events', 'parsed_original_currency')
    op.drop_column('source_events', 'parsed_original_amount')


def downgrade() -> None:
    op.add_column('source_events', sa.Column('parsed_original_amount', sa.Numeric(15, 2), nullable=True))
    op.add_column('source_events', sa.Column('parsed_original_currency', sa.String(3), nullable=True))