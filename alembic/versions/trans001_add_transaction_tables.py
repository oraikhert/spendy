"""Add transaction tracking tables

Revision ID: trans001
Revises: cfc042908370
Create Date: 2026-02-10 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'trans001'
down_revision: Union[str, None] = 'cfc042908370'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('account_currency', sa.String(length=3), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_accounts_id'), 'accounts', ['id'], unique=False)
    
    op.create_table(
        'cards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('card_masked_number', sa.String(length=255), nullable=False),
        sa.Column('card_type', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'card_masked_number', name='uq_account_card_number')
    )
    op.create_index(op.f('ix_cards_id'), 'cards', ['id'], unique=False)
    
    op.create_table(
        'transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('transaction_datetime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('posting_datetime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('transaction_kind', sa.String(length=50), nullable=False),
        sa.Column('original_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('original_currency', sa.String(length=3), nullable=True),
        sa.Column('fx_rate', sa.Numeric(precision=15, scale=6), nullable=True),
        sa.Column('fx_fee', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('merchant_norm', sa.String(length=500), nullable=True),
        sa.Column('fingerprint', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transactions_id'), 'transactions', ['id'], unique=False)
    op.create_index(op.f('ix_transactions_fingerprint'), 'transactions', ['fingerprint'], unique=False)
    op.create_index('ix_transactions_card_posting', 'transactions', ['card_id', 'posting_datetime'], unique=False)
    op.create_index('ix_transactions_card_transaction', 'transactions', ['card_id', 'transaction_datetime'], unique=False)
    op.create_index('ix_transactions_card_amount_currency', 'transactions', ['card_id', 'amount', 'currency'], unique=False)
    
    op.create_table(
        'source_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('raw_text', sa.String(), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('raw_hash', sa.String(length=64), nullable=False),
        sa.Column('parsed_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('parsed_currency', sa.String(length=3), nullable=True),
        sa.Column('parsed_transaction_datetime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('parsed_posting_datetime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('parsed_description', sa.String(), nullable=True),
        sa.Column('parsed_original_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('parsed_original_currency', sa.String(length=3), nullable=True),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('card_id', sa.Integer(), nullable=True),
        sa.Column('parse_status', sa.String(length=50), nullable=False),
        sa.Column('parse_error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('raw_hash')
    )
    op.create_index(op.f('ix_source_events_id'), 'source_events', ['id'], unique=False)
    op.create_index('ix_source_events_type_received', 'source_events', ['source_type', 'received_at'], unique=False)
    
    op.create_table(
        'transaction_source_links',
        sa.Column('transaction_id', sa.Integer(), nullable=False),
        sa.Column('source_event_id', sa.Integer(), nullable=False),
        sa.Column('match_confidence', sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['source_event_id'], ['source_events.id'], ),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ),
        sa.PrimaryKeyConstraint('transaction_id', 'source_event_id'),
        sa.UniqueConstraint('transaction_id', 'source_event_id', name='uq_transaction_source')
    )

def downgrade() -> None:
    op.drop_table('transaction_source_links')
    op.drop_index('ix_source_events_type_received', table_name='source_events')
    op.drop_index(op.f('ix_source_events_id'), table_name='source_events')
    op.drop_table('source_events')
    op.drop_index('ix_transactions_card_amount_currency', table_name='transactions')
    op.drop_index('ix_transactions_card_transaction', table_name='transactions')
    op.drop_index('ix_transactions_card_posting', table_name='transactions')
    op.drop_index(op.f('ix_transactions_fingerprint'), table_name='transactions')
    op.drop_index(op.f('ix_transactions_id'), table_name='transactions')
    op.drop_table('transactions')
    op.drop_index(op.f('ix_cards_id'), table_name='cards')
    op.drop_table('cards')
    op.drop_index(op.f('ix_accounts_id'), table_name='accounts')
    op.drop_table('accounts')
