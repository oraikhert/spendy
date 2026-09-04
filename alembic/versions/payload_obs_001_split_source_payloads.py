"""Split source payloads from transaction observations.

Revision ID: payload_obs_001
Revises: recipients_sender_001
Create Date: 2026-09-04

The downgrade is structurally reversible but necessarily lossy: old source events
cannot represent multiple observations and old links discarded during strict cleanup
cannot be reconstructed.
"""

from collections import defaultdict
from datetime import datetime
import hashlib
import logging
import mimetypes
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "payload_obs_001"
down_revision: Union[str, None] = "recipients_sender_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def _media_type(source_type: str, file_path: str | None) -> str:
    if source_type in {"sms_text", "telegram_text", "manual"} and not file_path:
        return "text/plain"
    if source_type == "pdf_statement":
        return "application/pdf"
    guessed = mimetypes.guess_type(file_path or "")[0]
    if guessed:
        return guessed
    if source_type in {"sms_screenshot", "bank_screenshot"}:
        return "image/png"
    return "application/octet-stream"


def _source_dimensions(source_type: str, file_path: str | None) -> tuple[str, str, str]:
    media_type = _media_type(source_type, file_path)
    mapping = {
        "sms_text": ("sms", media_type, "phone_api"),
        "telegram_text": ("sms", media_type, "telegram_api"),
        "sms_screenshot": ("sms", media_type, "manual_upload"),
        "bank_screenshot": ("bank_app", media_type, "manual_upload"),
        "pdf_statement": ("bank_statement", media_type, "manual_upload"),
        "manual": ("other", media_type, "migration"),
    }
    return mapping.get(source_type, ("other", media_type, "migration"))


def _json_value(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _compact(**values):
    return {key: _json_value(value) for key, value in values.items() if value is not None}


def _restore_datetime(value):
    if not isinstance(value, str):
        return value
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _reset_postgresql_sequence(bind, table_name: str) -> None:
    if bind.dialect.name != "postgresql":
        return
    bind.execute(
        sa.text(
            f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), "
            f"EXISTS(SELECT 1 FROM {table_name}))"
        )
    )


def upgrade() -> None:
    op.create_table(
        "source_payloads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=50), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("ingestion_method", sa.String(length=50), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_status", sa.String(length=50), nullable=False),
        sa.Column("parser_name", sa.String(length=100), nullable=True),
        sa.Column("parser_version", sa.String(length=50), nullable=True),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("ingestion_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ingestion_method", "idempotency_key", name="uq_payload_ingestion_idempotency"
        ),
    )
    op.create_index("ix_source_payloads_id", "source_payloads", ["id"], unique=False)
    op.create_index(
        "ix_source_payloads_content_hash", "source_payloads", ["content_hash"], unique=False
    )
    op.create_index(
        "ix_source_payloads_kind_status_received",
        "source_payloads",
        ["source_kind", "processing_status", "received_at"],
        unique=False,
    )

    op.create_table(
        "bank_statement_details",
        sa.Column("source_payload_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("card_id", sa.Integer(), nullable=True),
        sa.Column("bank", sa.String(length=255), nullable=True),
        sa.Column("statement_period_start", sa.Date(), nullable=True),
        sa.Column("statement_period_end", sa.Date(), nullable=True),
        sa.Column("statement_currency", sa.String(length=3), nullable=True),
        sa.Column("card_type", sa.String(length=50), nullable=True),
        sa.Column("card_last_four", sa.String(length=4), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"]),
        sa.ForeignKeyConstraint(["source_payload_id"], ["source_payloads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_payload_id"),
    )

    op.create_table(
        "transaction_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_payload_id", sa.Integer(), nullable=False),
        sa.Column("source_item_key", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("original_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("original_currency", sa.String(length=3), nullable=True),
        sa.Column("transaction_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posting_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("transaction_kind", sa.String(length=50), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("card_id", sa.Integer(), nullable=True),
        sa.Column("card_last_four", sa.String(length=4), nullable=True),
        sa.Column("raw_fragment", sa.Text(), nullable=True),
        sa.Column("extraction_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("extraction_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"]),
        sa.ForeignKeyConstraint(["source_payload_id"], ["source_payloads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_payload_id", "source_item_key", name="uq_observation_payload_item"
        ),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_transaction_observations_id", "transaction_observations", ["id"])
    op.create_index(
        "ix_observations_card_transaction",
        "transaction_observations",
        ["card_id", "transaction_datetime"],
    )
    op.create_index(
        "ix_observations_card_posting",
        "transaction_observations",
        ["card_id", "posting_datetime"],
    )
    op.create_index(
        "ix_observations_amount_currency",
        "transaction_observations",
        ["amount", "currency"],
    )

    op.create_table(
        "transaction_source_links_v2",
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("match_method", sa.String(length=50), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matcher_name", sa.String(length=100), nullable=True),
        sa.Column("matcher_version", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["transaction_observations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("observation_id"),
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    legacy_sources = sa.Table("source_events", metadata, autoload_with=bind)
    legacy_links = sa.Table("transaction_source_links", metadata, autoload_with=bind)
    source_rows = list(bind.execute(sa.select(legacy_sources)).mappings())
    link_rows = list(bind.execute(sa.select(legacy_links)).mappings())

    payload_table = sa.table(
        "source_payloads",
        sa.column("id", sa.Integer()),
        sa.column("source_kind", sa.String()),
        sa.column("media_type", sa.String()),
        sa.column("ingestion_method", sa.String()),
        sa.column("raw_text", sa.Text()),
        sa.column("file_path", sa.String()),
        sa.column("original_filename", sa.String()),
        sa.column("content_hash", sa.String()),
        sa.column("idempotency_key", sa.String()),
        sa.column("received_at", sa.DateTime(timezone=True)),
        sa.column("processing_status", sa.String()),
        sa.column("parser_name", sa.String()),
        sa.column("parser_version", sa.String()),
        sa.column("processing_error", sa.Text()),
        sa.column("ingestion_metadata", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    observation_table = sa.table(
        "transaction_observations",
        *[
            sa.column(name, type_)
            for name, type_ in (
                ("id", sa.Integer()),
                ("source_payload_id", sa.Integer()),
                ("source_item_key", sa.String()),
                ("amount", sa.Numeric(15, 2)),
                ("currency", sa.String()),
                ("original_amount", sa.Numeric(15, 2)),
                ("original_currency", sa.String()),
                ("transaction_datetime", sa.DateTime(timezone=True)),
                ("posting_datetime", sa.DateTime(timezone=True)),
                ("description", sa.Text()),
                ("transaction_kind", sa.String()),
                ("location", sa.String()),
                ("account_id", sa.Integer()),
                ("card_id", sa.Integer()),
                ("card_last_four", sa.String()),
                ("raw_fragment", sa.Text()),
                ("extraction_confidence", sa.Numeric(5, 4)),
                ("extraction_metadata", sa.JSON()),
                ("created_at", sa.DateTime(timezone=True)),
                ("updated_at", sa.DateTime(timezone=True)),
            )
        ],
    )
    detail_table = sa.table(
        "bank_statement_details",
        sa.column("source_payload_id", sa.Integer()),
        sa.column("account_id", sa.Integer()),
        sa.column("card_id", sa.Integer()),
        sa.column("bank", sa.String()),
        sa.column("statement_period_start", sa.Date()),
        sa.column("statement_period_end", sa.Date()),
        sa.column("statement_currency", sa.String()),
        sa.column("card_type", sa.String()),
        sa.column("card_last_four", sa.String()),
    )
    new_link_table = sa.table(
        "transaction_source_links_v2",
        sa.column("observation_id", sa.Integer()),
        sa.column("transaction_id", sa.Integer()),
        sa.column("match_confidence", sa.Numeric(5, 4)),
        sa.column("match_method", sa.String()),
        sa.column("matched_at", sa.DateTime(timezone=True)),
        sa.column("matcher_name", sa.String()),
        sa.column("matcher_version", sa.String()),
    )

    payload_rows = []
    observation_rows = []
    detail_rows = []
    observation_ids: set[int] = set()
    received_by_id = {}
    for row in source_rows:
        source_kind, media_type, ingestion_method = _source_dimensions(
            row["source_type"], row["file_path"]
        )
        received_at = row["created_at"]
        received_by_id[row["id"]] = received_at
        old_status = row["parse_status"]
        if old_status == "parsed":
            processing_status = "processed"
        elif old_status == "skipped":
            processing_status = "ignored"
        elif old_status == "failed":
            processing_status = "failed"
        else:
            processing_status = "pending"
        payload_rows.append(
            {
                "id": row["id"],
                "source_kind": source_kind,
                "media_type": media_type,
                "ingestion_method": ingestion_method,
                "raw_text": row["raw_text"],
                "file_path": row["file_path"],
                # The legacy schema retained only an internal path, not the original
                # client filename. Do not relabel or expose its basename as user data.
                "original_filename": None,
                "content_hash": row["raw_hash"],
                "idempotency_key": None,
                "received_at": received_at,
                "processing_status": processing_status,
                "parser_name": "legacy_sms_parser" if media_type == "text/plain" else None,
                "parser_version": "legacy" if media_type == "text/plain" else None,
                "processing_error": row["parse_error"],
                "ingestion_metadata": _compact(
                    legacy_source_type=row["source_type"],
                    account_id=row["account_id"],
                    card_id=row["card_id"],
                    transaction_datetime=row["transaction_datetime"],
                    sender=row["sender"],
                    recipients=row["recipients"],
                ),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
        if source_kind == "bank_statement":
            detail_rows.append(
                {
                    "source_payload_id": row["id"],
                    "account_id": row["account_id"],
                    "card_id": row["card_id"],
                    "bank": row.get("bank"),
                    "statement_period_start": row.get("statement_period_start"),
                    "statement_period_end": row.get("statement_period_end"),
                    "statement_currency": row.get("statement_currency"),
                    "card_type": row.get("card_type"),
                    "card_last_four": row.get("parsed_card_number"),
                }
            )
        if row["parsed_amount"] is None or row["parsed_currency"] is None:
            continue
        observation_ids.add(row["id"])
        observation_rows.append(
            {
                "id": row["id"],
                "source_payload_id": row["id"],
                "source_item_key": "0",
                "amount": row["parsed_amount"],
                "currency": row["parsed_currency"],
                "original_amount": None,
                "original_currency": None,
                "transaction_datetime": row["parsed_transaction_datetime"] or row["transaction_datetime"],
                "posting_datetime": row["parsed_posting_datetime"],
                "description": row["parsed_description"],
                "transaction_kind": row["parsed_transaction_kind"],
                "location": row["parsed_location"],
                "account_id": row["account_id"],
                "card_id": row["card_id"],
                "card_last_four": row["parsed_card_number"],
                "raw_fragment": row["raw_text"],
                "extraction_confidence": None,
                "extraction_metadata": {"legacy_source_event_id": row["id"]},
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    if payload_rows:
        op.bulk_insert(payload_table, payload_rows)
    if observation_rows:
        op.bulk_insert(observation_table, observation_rows)
    if detail_rows:
        op.bulk_insert(detail_table, detail_rows)

    links_by_source = defaultdict(list)
    for row in link_rows:
        if row["source_event_id"] in observation_ids:
            links_by_source[row["source_event_id"]].append(row)
    migrated_links = []
    dropped_conflicts = 0
    for source_event_id, rows in links_by_source.items():
        chosen = min(
            rows,
            key=lambda row: (0 if row["is_primary"] else 1, row["transaction_id"]),
        )
        dropped_conflicts += len(rows) - 1
        migrated_links.append(
            {
                "observation_id": source_event_id,
                "transaction_id": chosen["transaction_id"],
                "match_confidence": chosen["match_confidence"],
                "match_method": "migration",
                "matched_at": received_by_id[source_event_id],
                "matcher_name": "legacy",
                "matcher_version": "legacy",
            }
        )
    if migrated_links:
        op.bulk_insert(new_link_table, migrated_links)

    dropped_without_observation = sum(
        1 for row in link_rows if row["source_event_id"] not in observation_ids
    )
    logger.info(
        "Source split migrated %d payloads, %d observations and %d links; "
        "discarded %d links without observations and %d conflicting links",
        len(payload_rows),
        len(observation_rows),
        len(migrated_links),
        dropped_without_observation,
        dropped_conflicts,
    )

    op.drop_table("transaction_source_links")
    op.drop_index("ix_source_events_type_transaction_datetime", table_name="source_events")
    op.drop_index("ix_source_events_id", table_name="source_events")
    op.drop_table("source_events")
    op.rename_table("transaction_source_links_v2", "transaction_source_links")
    op.create_index(
        "ix_transaction_source_links_transaction_id",
        "transaction_source_links",
        ["transaction_id"],
    )
    _reset_postgresql_sequence(bind, "source_payloads")
    _reset_postgresql_sequence(bind, "transaction_observations")


def _legacy_source_type(payload) -> str:
    original = (payload["ingestion_metadata"] or {}).get("legacy_source_type")
    if original in {
        "sms_text", "telegram_text", "sms_screenshot", "bank_screenshot", "pdf_statement", "manual"
    }:
        return original
    if payload["source_kind"] == "bank_statement":
        return "pdf_statement"
    if payload["source_kind"] == "bank_app":
        return "bank_screenshot"
    if payload["source_kind"] == "sms":
        return "sms_text" if payload["media_type"] == "text/plain" else "sms_screenshot"
    return "manual"


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    payloads = sa.Table("source_payloads", metadata, autoload_with=bind)
    observations = sa.Table("transaction_observations", metadata, autoload_with=bind)
    new_links = sa.Table("transaction_source_links", metadata, autoload_with=bind)

    payload_rows = list(bind.execute(sa.select(payloads)).mappings())
    observation_rows = list(
        bind.execute(
            sa.select(observations).order_by(
                observations.c.source_payload_id, observations.c.source_item_key, observations.c.id
            )
        ).mappings()
    )
    link_rows = list(bind.execute(sa.select(new_links)).mappings())

    op.create_table(
        "source_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("transaction_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_text", sa.String(), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=True),
        sa.Column("raw_hash", sa.String(length=64), nullable=False),
        sa.Column("parsed_amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("parsed_currency", sa.String(length=3), nullable=True),
        sa.Column("parsed_transaction_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_posting_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_description", sa.String(), nullable=True),
        sa.Column("parsed_card_number", sa.String(length=4), nullable=True),
        sa.Column("parsed_transaction_kind", sa.String(length=50), nullable=True),
        sa.Column("parsed_location", sa.String(length=200), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("card_id", sa.Integer(), nullable=True),
        sa.Column("parse_status", sa.String(length=50), nullable=False),
        sa.Column("parse_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipients", sa.String(length=500), nullable=True),
        sa.Column("sender", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["card_id"], ["cards.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_hash"),
    )
    op.create_index("ix_source_events_id", "source_events", ["id"])
    op.create_index(
        "ix_source_events_type_transaction_datetime",
        "source_events",
        ["source_type", "transaction_datetime"],
    )
    op.create_table(
        "transaction_source_links_legacy",
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=False),
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["source_event_id"], ["source_events.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("transaction_id", "source_event_id"),
        sa.UniqueConstraint("transaction_id", "source_event_id", name="uq_transaction_source"),
    )

    first_observation = {}
    discarded_observations = 0
    for row in observation_rows:
        if row["source_payload_id"] in first_observation:
            discarded_observations += 1
        else:
            first_observation[row["source_payload_id"]] = row
    observation_payload = {
        row["id"]: row["source_payload_id"] for row in first_observation.values()
    }

    old_source_table = sa.Table("source_events", sa.MetaData(), autoload_with=bind)
    used_hashes = set()
    old_rows = []
    for payload in payload_rows:
        observation = first_observation.get(payload["id"])
        metadata_value = payload["ingestion_metadata"] or {}
        raw_hash = payload["content_hash"]
        if raw_hash in used_hashes:
            raw_hash = hashlib.sha256(f"{raw_hash}:{payload['id']}".encode()).hexdigest()
        used_hashes.add(raw_hash)
        status_map = {
            "processed": "parsed",
            "ignored": "skipped",
            "failed": "failed",
            "processing": "new",
            "pending": "new",
        }
        old_rows.append(
            {
                "id": payload["id"],
                "source_type": _legacy_source_type(payload),
                "transaction_datetime": (
                    observation["transaction_datetime"] if observation else None
                ) or _restore_datetime(metadata_value.get("transaction_datetime")) or payload["received_at"],
                "raw_text": payload["raw_text"],
                "file_path": payload["file_path"],
                "raw_hash": raw_hash,
                "parsed_amount": observation["amount"] if observation else None,
                "parsed_currency": observation["currency"] if observation else None,
                "parsed_transaction_datetime": observation["transaction_datetime"] if observation else None,
                "parsed_posting_datetime": observation["posting_datetime"] if observation else None,
                "parsed_description": observation["description"] if observation else None,
                "parsed_card_number": observation["card_last_four"] if observation else None,
                "parsed_transaction_kind": observation["transaction_kind"] if observation else None,
                "parsed_location": observation["location"] if observation else None,
                "account_id": (observation["account_id"] if observation else None) or metadata_value.get("account_id"),
                "card_id": (observation["card_id"] if observation else None) or metadata_value.get("card_id"),
                "parse_status": status_map.get(payload["processing_status"], "new"),
                "parse_error": payload["processing_error"],
                "created_at": payload["created_at"],
                "updated_at": payload["updated_at"],
                "recipients": metadata_value.get("recipients"),
                "sender": metadata_value.get("sender"),
            }
        )
    if old_rows:
        bind.execute(old_source_table.insert(), old_rows)

    old_link_table = sa.Table("transaction_source_links_legacy", sa.MetaData(), autoload_with=bind)
    old_links = []
    for link in link_rows:
        payload_id = observation_payload.get(link["observation_id"])
        if payload_id is None:
            continue
        old_links.append(
            {
                "transaction_id": link["transaction_id"],
                "source_event_id": payload_id,
                "match_confidence": link["match_confidence"],
                "is_primary": False,
            }
        )
    if old_links:
        bind.execute(old_link_table.insert(), old_links)

    logger.warning(
        "Lossy source split downgrade discarded %d additional observations",
        discarded_observations,
    )
    op.drop_index(
        "ix_transaction_source_links_transaction_id", table_name="transaction_source_links"
    )
    op.drop_table("transaction_source_links")
    op.drop_index("ix_observations_amount_currency", table_name="transaction_observations")
    op.drop_index("ix_observations_card_posting", table_name="transaction_observations")
    op.drop_index("ix_observations_card_transaction", table_name="transaction_observations")
    op.drop_index("ix_transaction_observations_id", table_name="transaction_observations")
    op.drop_table("transaction_observations")
    op.drop_table("bank_statement_details")
    op.drop_index("ix_source_payloads_kind_status_received", table_name="source_payloads")
    op.drop_index("ix_source_payloads_content_hash", table_name="source_payloads")
    op.drop_index("ix_source_payloads_id", table_name="source_payloads")
    op.drop_table("source_payloads")
    op.rename_table("transaction_source_links_legacy", "transaction_source_links")
    _reset_postgresql_sequence(bind, "source_events")
