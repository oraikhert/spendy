"""Card model"""
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.transaction import Transaction


class Card(Base):
    """Card model - ties transactions to a specific card"""
    
    __tablename__ = "cards"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    card_masked_number: Mapped[str] = mapped_column(String(255), nullable=False)
    card_type: Mapped[str] = mapped_column(String(50), nullable=False)  # debit | credit
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    account: Mapped["Account"] = relationship("Account", back_populates="cards")
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction",
        back_populates="card",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        UniqueConstraint("account_id", "card_masked_number", name="uq_account_card_number"),
    )
    
    def __repr__(self) -> str:
        return f"<Card(id={self.id}, name={self.name}, masked_number={self.card_masked_number})>"
