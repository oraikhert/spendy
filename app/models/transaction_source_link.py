"""Final link between one observation and one canonical transaction."""
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.transaction_observation import TransactionObservation


class MatchMethod(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    MIGRATION = "migration"


class TransactionSourceLink(Base):
    """A final 0..1 observation-to-transaction match."""

    __tablename__ = "transaction_source_links"

    observation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("transaction_observations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    match_method: Mapped[str] = mapped_column(String(50), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    matcher_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    matcher_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="source_links")
    observation: Mapped["TransactionObservation"] = relationship(
        "TransactionObservation", back_populates="transaction_link"
    )

    __table_args__ = (Index("ix_transaction_source_links_transaction_id", "transaction_id"),)

    def __repr__(self) -> str:
        return (
            f"<TransactionSourceLink(transaction_id={self.transaction_id}, "
            f"observation_id={self.observation_id})>"
        )
