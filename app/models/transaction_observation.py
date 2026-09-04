"""Financial observation extracted from one source payload."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.source_payload import SourcePayload
    from app.models.transaction_source_link import TransactionSourceLink


class TransactionObservation(Base):
    """One source assertion about one financial transaction."""

    __tablename__ = "transaction_observations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_payload_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("source_payloads.id", ondelete="CASCADE"), nullable=False
    )
    source_item_key: Mapped[str] = mapped_column(String(255), nullable=False)

    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    original_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    transaction_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posting_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True
    )
    card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cards.id"), nullable=True)
    card_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)

    raw_fragment: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(
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

    payload: Mapped["SourcePayload"] = relationship("SourcePayload", back_populates="observations")
    transaction_link: Mapped["TransactionSourceLink | None"] = relationship(
        "TransactionSourceLink",
        back_populates="observation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "source_payload_id", "source_item_key", name="uq_observation_payload_item"
        ),
        Index("ix_observations_card_transaction", "card_id", "transaction_datetime"),
        Index("ix_observations_card_posting", "card_id", "posting_datetime"),
        Index("ix_observations_amount_currency", "amount", "currency"),
        {"sqlite_autoincrement": True},
    )

    def __repr__(self) -> str:
        return (
            f"<TransactionObservation(id={self.id}, payload={self.source_payload_id}, "
            f"item={self.source_item_key})>"
        )
