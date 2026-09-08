"""Introduce workspace ownership and backfill retained data.

Revision ID: workspace_ownership_001
Revises: txn_summary_excl_001
"""
from datetime import UTC, datetime
from alembic import op
import sqlalchemy as sa

revision = "workspace_ownership_001"
down_revision = "txn_summary_excl_001"
branch_labels = None
depends_on = None

TABLES = {
    "accounts": ("id", []),
    "cards": ("id", [("account_id", "accounts", None)]),
    "transactions": ("id", [("card_id", "cards", None)]),
    "source_payloads": ("id", []),
    "transaction_observations": ("id", [("source_payload_id", "source_payloads", "CASCADE"), ("account_id", "accounts", None), ("card_id", "cards", None)]),
    "bank_statement_details": ("source_payload_id", [("source_payload_id", "source_payloads", "CASCADE"), ("account_id", "accounts", None), ("card_id", "cards", None)]),
    "transaction_source_links": ("observation_id", [("observation_id", "transaction_observations", "CASCADE"), ("transaction_id", "transactions", "CASCADE")]),
}


def _observation_sequence(bind):
    if bind.dialect.name == "sqlite":
        return bind.scalar(sa.text("SELECT seq FROM sqlite_sequence WHERE name='transaction_observations'"))
    return None


def _restore_observation_sequence(bind, sequence):
    if sequence is not None:
        bind.execute(sa.text("UPDATE sqlite_sequence SET seq = max(seq, :sequence) WHERE name='transaction_observations'"), {"sequence": sequence})


def upgrade():
    observation_sequence = _observation_sequence(op.get_bind())
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_workspace_status"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 100", name="ck_workspace_name"),
    )
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_workspace_member_role"),
    )
    for column in ("workspace_id", "user_id"):
        op.create_index(f"ix_workspace_members_{column}", "workspace_members", [column])
    bind = op.get_bind()
    users = list(bind.execute(sa.text("SELECT id FROM users ORDER BY id")).scalars())
    retained = any(bind.scalar(sa.text(f"SELECT count(*) FROM {table}")) for table in TABLES)
    legacy_id = None
    if users or retained:
        now = datetime.now(UTC)
        workspace = sa.table("workspaces", sa.column("id", sa.Integer()), sa.column("name"), sa.column("status"), sa.column("created_by_user_id"), sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)))
        legacy_id = bind.execute(workspace.insert().values(name="Legacy Workspace", status="active", created_by_user_id=users[0] if users else None, created_at=now, updated_at=now).returning(workspace.c.id)).scalar_one()
        members = sa.table("workspace_members", sa.column("workspace_id"), sa.column("user_id"), sa.column("role"), sa.column("joined_at", sa.DateTime(timezone=True)), sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)))
        if users:
            bind.execute(members.insert(), [dict(workspace_id=legacy_id, user_id=user_id, role="owner" if index == 0 else "editor", joined_at=now, created_at=now, updated_at=now) for index, user_id in enumerate(users)])
    # Every table is populated before any new ownership constraint is installed.
    for table in TABLES:
        op.add_column(table, sa.Column("workspace_id", sa.Integer(), nullable=True))
        if legacy_id is not None:
            bind.execute(sa.text(f"UPDATE {table} SET workspace_id = :workspace"), {"workspace": legacy_id})
    for table, (key, references) in TABLES.items():
        with op.batch_alter_table(table, table_kwargs={"sqlite_autoincrement": True} if table == "transaction_observations" else {}) as batch:
            batch.alter_column("workspace_id", existing_type=sa.Integer(), nullable=False)
            batch.create_foreign_key(f"fk_{table}_workspace", "workspaces", ["workspace_id"], ["id"])
            batch.create_unique_constraint(f"uq_{table}_id_workspace", [key, "workspace_id"])
            batch.create_index(f"ix_{table}_workspace_id", ["workspace_id"])
            for column, target, ondelete in references:
                batch.create_foreign_key(f"fk_{table}_{column}_workspace", target, [column, "workspace_id"], ["id", "workspace_id"], ondelete=ondelete)
            if table == "source_payloads":
                batch.drop_constraint("uq_payload_ingestion_idempotency", type_="unique")
                batch.create_unique_constraint("uq_payload_ingestion_idempotency", ["workspace_id", "ingestion_method", "idempotency_key"])
    _restore_observation_sequence(bind, observation_sequence)
    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_superuser")


def downgrade():
    bind = op.get_bind()
    observation_sequence = _observation_sequence(bind)
    # Collapse would remove access boundaries even if scopes currently contain no money.
    # Refuse before changing any schema or membership data.
    if bind.scalar(sa.text("SELECT count(*) FROM workspaces")) > 1:
        raise RuntimeError("Unsafe workspace downgrade: multiple workspace scopes cannot be collapsed")
    for table, (key, references) in reversed(list(TABLES.items())):
        with op.batch_alter_table(table, table_kwargs={"sqlite_autoincrement": True} if table == "transaction_observations" else {}) as batch:
            for column, target, ondelete in references:
                batch.drop_constraint(f"fk_{table}_{column}_workspace", type_="foreignkey")
            batch.drop_constraint(f"fk_{table}_workspace", type_="foreignkey")
            batch.drop_constraint(f"uq_{table}_id_workspace", type_="unique")
            batch.drop_index(f"ix_{table}_workspace_id")
            if table == "source_payloads":
                batch.drop_constraint("uq_payload_ingestion_idempotency", type_="unique")
                batch.create_unique_constraint("uq_payload_ingestion_idempotency", ["ingestion_method", "idempotency_key"])
            batch.drop_column("workspace_id")
    _restore_observation_sequence(bind, observation_sequence)
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()))
