"""Add transaction kind and location fields

Revision ID: kind_location_001
Revises: drop_orig_001
Create Date: 2026-02-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'kind_location_001'
down_revision: Union[str, None] = 'drop_orig_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add parsed_transaction_kind to source_events
    op.add_column('source_events', sa.Column('parsed_transaction_kind', sa.String(length=50), nullable=True))
    
    # Add parsed_location to source_events
    op.add_column('source_events', sa.Column('parsed_location', sa.String(length=200), nullable=True))
    
    # Add location to transactions
    op.add_column('transactions', sa.Column('location', sa.String(length=200), nullable=True))


def downgrade() -> None:
    # Remove location from transactions
    op.drop_column('transactions', 'location')
    
    # Remove parsed_location from source_events
    op.drop_column('source_events', 'parsed_location')
    
    # Remove parsed_transaction_kind from source_events
    op.drop_column('source_events', 'parsed_transaction_kind')
