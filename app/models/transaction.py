"""Transaction model"""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, DateTime, ForeignKey, Integer, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.card import Card
    from app.models.transaction_source_link import TransactionSourceLink


class Transaction(Base):
    """Transaction model - canonical 'truth' record"""
    
    __tablename__ = "transactions"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    card_id: Mapped[int] = mapped_column(Integer, ForeignKey("cards.id"), nullable=False)
    
    # Canonical fields
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posting_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    
    # Kind
    transaction_kind: Mapped[str] = mapped_column(String(50), nullable=False)  # purchase | topup | refund | other
    
    # Multi-currency optional
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    original_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(15, 6), nullable=True)
    fx_fee: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    
    # Dedupe/matching technical
    merchant_norm: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    card: Mapped["Card"] = relationship("Card", back_populates="transactions")
    source_links: Mapped[list["TransactionSourceLink"]] = relationship(
        "TransactionSourceLink",
        back_populates="transaction",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("ix_transactions_card_posting", "card_id", "posting_datetime"),
        Index("ix_transactions_card_transaction", "card_id", "transaction_datetime"),
        Index("ix_transactions_card_amount_currency", "card_id", "amount", "currency"),
    )
    
    def __repr__(self) -> str:
        return f"<Transaction(id={self.id}, amount={self.amount} {self.currency}, description={self.description[:30]})>"
