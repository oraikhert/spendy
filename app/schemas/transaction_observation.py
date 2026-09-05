"""Schemas for extracted transaction observations and their final links."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.transaction_source_link import MatchMethod
from app.schemas.transaction import Amount, ExchangeRate, MAX_RECORD_ID, normalize_currency
from app.schemas.source_payload import SourcePayloadSummary


Confidence = Annotated[Decimal, Field(ge=0, le=1, max_digits=5, decimal_places=4)]


class TransactionObservationSummary(BaseModel):
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
    extraction_confidence: Confidence | None = None
    extraction_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransactionLinkSummary(BaseModel):
    observation_id: int
    transaction_id: int
    match_confidence: Confidence | None = None
    match_method: MatchMethod
    matched_at: datetime
    matcher_name: str | None = None
    matcher_version: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionObservationWithPayload(TransactionObservationSummary):
    payload: SourcePayloadSummary


class TransactionObservationDetail(TransactionObservationWithPayload):
    transaction_link: TransactionLinkSummary | None = None


class TransactionObservationListResponse(BaseModel):
    items: list[TransactionObservationDetail]
    limit: int
    offset: int
    total: int


class TransactionLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: int = Field(gt=0, le=MAX_RECORD_ID)


class TransactionMoveCreate(TransactionLinkCreate):
    allow_date_mismatch: bool = False


class TransactionCreateFromObservation(BaseModel):
    """Optional overrides used only where the observation has no canonical value."""

    model_config = ConfigDict(extra="forbid")

    card_id: int | None = Field(None, gt=0, le=MAX_RECORD_ID)
    amount: Amount | None = None
    currency: str | None = None
    transaction_datetime: datetime | None = None
    posting_datetime: datetime | None = None
    description: str | None = None
    location: str | None = Field(None, max_length=200)
    transaction_kind: str | None = Field(None, pattern="^(purchase|topup|refund|other)$")
    original_amount: Amount | None = None
    original_currency: str | None = None
    fx_rate: ExchangeRate | None = None
    fx_fee: Amount | None = None

    @field_validator("currency", "original_currency", mode="before")
    @classmethod
    def normalize_input_currency(cls, value):
        return normalize_currency(value) if isinstance(value, str) else value

    @field_validator("description", "location", mode="before")
    @classmethod
    def trim_optional_text(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_override_pair(self) -> Self:
        if (self.original_amount is None) != (self.original_currency is None):
            raise ValueError("original_amount and original_currency must be supplied together")
        if self.fx_rate is not None and self.original_amount is None:
            raise ValueError("fx_rate requires original_amount and original_currency")
        return self


class TransactionSourceLinkResponse(TransactionLinkSummary):
    observation: TransactionObservationWithPayload
