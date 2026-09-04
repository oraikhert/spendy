"""Payload-level metadata for bank statements."""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.source_payload import SourcePayload


class BankStatementDetail(Base):
    __tablename__ = "bank_statement_details"

    source_payload_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("source_payloads.id", ondelete="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True
    )
    card_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cards.id"), nullable=True)
    bank: Mapped[str | None] = mapped_column(String(255), nullable=True)
    statement_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    statement_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    statement_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    card_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    card_last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)

    payload: Mapped["SourcePayload"] = relationship(
        "SourcePayload", back_populates="bank_statement_details"
    )
