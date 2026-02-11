"""SourceEvent model"""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, DateTime, ForeignKey, Integer, Numeric, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING

from app.database import Base

if TYPE_CHECKING:
    from app.models.transaction_source_link import TransactionSourceLink


class SourceEvent(Base):
    """SourceEvent model - store any incoming fact (SMS, screenshot, PDF, manual)"""
    
    __tablename__ = "source_events"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # telegram_text | sms_text | sms_screenshot | bank_screenshot | pdf_statement | manual
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    
    # Raw payload
    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    
    # Parsed fields (stub for now)
    parsed_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    parsed_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    parsed_transaction_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parsed_posting_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parsed_description: Mapped[str | None] = mapped_column(String, nullable=True)
    parsed_card_number: Mapped[str | None] = mapped_column(String(4), nullable=True)
    parsed_original_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    parsed_original_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    
    # Context (optional)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=True)
    card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cards.id"), nullable=True)
    
    # Parsing status
    parse_status: Mapped[str] = mapped_column(String(50), nullable=False, default="new")  # new | parsed | failed
    parse_error: Mapped[str | None] = mapped_column(String, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    # Relationships
    transaction_links: Mapped[list["TransactionSourceLink"]] = relationship(
        "TransactionSourceLink",
        back_populates="source_event",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("ix_source_events_type_received", "source_type", "received_at"),
    )
    
    def __repr__(self) -> str:
        return f"<SourceEvent(id={self.id}, source_type={self.source_type}, parse_status={self.parse_status})>"
