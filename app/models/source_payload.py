"""Immutable source payload and source processing vocabulary."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.bank_statement_detail import BankStatementDetail
    from app.models.transaction_observation import TransactionObservation


class SourceKind(StrEnum):
    SMS = "sms"
    BANK_STATEMENT = "bank_statement"
    BANK_APP = "bank_app"
    OTHER = "other"


class IngestionMethod(StrEnum):
    PHONE_API = "phone_api"
    MANUAL_UPLOAD = "manual_upload"
    TELEGRAM_API = "telegram_api"
    EMAIL = "email"
    MIGRATION = "migration"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class SourcePayload(Base):
    """An immutable text or file exactly as it entered the system."""

    __tablename__ = "source_payloads"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    ingestion_method: Mapped[str] = mapped_column(String(50), nullable=False)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    processing_status: Mapped[str] = mapped_column(
        String(50), default=ProcessingStatus.PENDING.value, nullable=False
    )
    parser_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingestion_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON), default=dict, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    observations: Mapped[list["TransactionObservation"]] = relationship(
        "TransactionObservation",
        back_populates="payload",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TransactionObservation.source_item_key",
    )
    bank_statement_details: Mapped["BankStatementDetail | None"] = relationship(
        "BankStatementDetail",
        back_populates="payload",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "ingestion_method", "idempotency_key", name="uq_payload_ingestion_idempotency"
        ),
        Index("ix_source_payloads_content_hash", "content_hash"),
        Index(
            "ix_source_payloads_kind_status_received",
            "source_kind",
            "processing_status",
            "received_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SourcePayload(id={self.id}, source_kind={self.source_kind}, "
            f"processing_status={self.processing_status})>"
        )

    @property
    def has_file(self) -> bool:
        """Expose file presence without exposing the private storage path."""
        return self.file_path is not None
