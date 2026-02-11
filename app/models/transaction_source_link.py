"""TransactionSourceLink model"""
from sqlalchemy import ForeignKey, Integer, Numeric, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.source_event import SourceEvent


class TransactionSourceLink(Base):
    """TransactionSourceLink model - link multiple sources to one transaction"""
    
    __tablename__ = "transaction_source_links"
    
    transaction_id: Mapped[int] = mapped_column(Integer, ForeignKey("transactions.id"), primary_key=True)
    source_event_id: Mapped[int] = mapped_column(Integer, ForeignKey("source_events.id"), primary_key=True)
    match_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Relationships
    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="source_links")
    source_event: Mapped["SourceEvent"] = relationship("SourceEvent", back_populates="transaction_links")
    
    __table_args__ = (
        UniqueConstraint("transaction_id", "source_event_id", name="uq_transaction_source"),
    )
    
    def __repr__(self) -> str:
        return f"<TransactionSourceLink(transaction_id={self.transaction_id}, source_event_id={self.source_event_id})>"
