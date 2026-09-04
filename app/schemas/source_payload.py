"""Schemas for immutable source payload registration and processing."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.source_payload import IngestionMethod, ProcessingStatus, SourceKind
from app.schemas.transaction import MAX_RECORD_ID


class SourcePayloadCreateText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKind = SourceKind.SMS
    text: str = Field(min_length=1)
    transaction_datetime: datetime | None = None
    account_id: int | None = Field(None, gt=0, le=MAX_RECORD_ID)
    card_id: int | None = Field(None, gt=0, le=MAX_RECORD_ID)
    sender: str | None = Field(None, max_length=200)
    recipients: str | None = Field(None, max_length=500)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class SourcePayloadSummary(BaseModel):
    id: int
    source_kind: SourceKind
    media_type: str
    ingestion_method: IngestionMethod
    original_filename: str | None = None
    has_file: bool
    content_hash: str
    received_at: datetime
    processing_status: ProcessingStatus
    parser_name: str | None = None
    parser_version: str | None = None
    processing_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BankStatementDetailResponse(BaseModel):
    source_payload_id: int
    account_id: int | None = None
    card_id: int | None = None
    bank: str | None = None
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    statement_currency: str | None = None
    card_type: str | None = None
    card_last_four: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PayloadObservationSummary(BaseModel):
    id: int
    source_payload_id: int
    source_item_key: str
    amount: Decimal | None = None
    currency: str | None = None
    original_amount: Decimal | None = None
    original_currency: str | None = None
    transaction_datetime: datetime | None = None
    posting_datetime: datetime | None = None
    description: str | None = None
    transaction_kind: str | None = None
    location: str | None = None
    account_id: int | None = None
    card_id: int | None = None
    card_last_four: str | None = None
    raw_fragment: str | None = None
    extraction_confidence: Decimal | None = None
    extraction_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SourcePayloadDetail(SourcePayloadSummary):
    raw_text: str | None = None
    ingestion_metadata: dict[str, Any]
    observations: list[PayloadObservationSummary]
    bank_statement_details: BankStatementDetailResponse | None = None


class SourcePayloadListResponse(BaseModel):
    items: list[SourcePayloadSummary]
    limit: int
    offset: int
    total: int
