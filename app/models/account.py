"""Account model"""
from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.card import Card
    from app.models.balance_snapshot import BalanceSnapshot


class Account(Base):
    """Account model - container for account currency and grouping cards/balances"""
    
    __tablename__ = "accounts"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    cards: Mapped[list["Card"]] = relationship(
        "Card",
        back_populates="account",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Account(id={self.id}, name={self.name}, institution={self.institution})>"
