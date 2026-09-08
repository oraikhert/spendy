"""Payload-level metadata for bank statements."""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, String, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.workspace import WorkspaceOwned

if TYPE_CHECKING:
    from app.models.source_payload import SourcePayload


class BankStatementDetail(WorkspaceOwned, Base):
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

    payload: Mapped["SourcePayload"] = relationship("SourcePayload", foreign_keys="BankStatementDetail.source_payload_id", back_populates="bank_statement_details"
    )

    __table_args__ = (
        UniqueConstraint("source_payload_id", "workspace_id", name="uq_bank_statement_details_id_workspace"),
        ForeignKeyConstraint(["source_payload_id", "workspace_id"], ["source_payloads.id", "source_payloads.workspace_id"], name="fk_bank_statement_details_source_payload_id_workspace", ondelete="CASCADE"),
        ForeignKeyConstraint(["account_id", "workspace_id"], ["accounts.id", "accounts.workspace_id"], name="fk_bank_statement_details_account_id_workspace"),
        ForeignKeyConstraint(["card_id", "workspace_id"], ["cards.id", "cards.workspace_id"], name="fk_bank_statement_details_card_id_workspace"),
    )
