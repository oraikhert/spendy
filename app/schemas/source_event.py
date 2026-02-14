"""SourceEvent schemas"""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class SourceEventBase(BaseModel):
    """Base source event schema"""
    source_type: str = Field(..., pattern="^(telegram_text|sms_text|sms_screenshot|bank_screenshot|pdf_statement|manual)$")


class SourceEventCreateText(SourceEventBase):
    """Schema for creating a text source event"""
    raw_text: str
    account_id: int | None = None
    card_id: int | None = None
    transaction_datetime: datetime | None = None


class SourceEventResponse(SourceEventBase):
    """Schema for source event response"""
    id: int
    received_at: datetime
    raw_text: str | None = None
    file_path: str | None = None
    raw_hash: str
    parsed_amount: Decimal | None = None
    parsed_currency: str | None = None
    parsed_transaction_datetime: datetime | None = None
    parsed_posting_datetime: datetime | None = None
    parsed_description: str | None = None
    parsed_card_number: str | None = None
    parsed_transaction_kind: str | None = None
    parsed_location: str | None = None
    account_id: int | None = None
    card_id: int | None = None
    parse_status: str
    parse_error: str | None = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class SourceEventListResponse(BaseModel):
    """Schema for paginated source event list"""
    items: list[SourceEventResponse]
    limit: int
    offset: int
    total: int


class SourceEventWithTransaction(SourceEventResponse):
    """Schema for source event with transaction info"""
    has_transaction: bool
    transaction_ids: list[int]


class TransactionLinkCreate(BaseModel):
    """Schema for linking source event to transaction"""
    transaction_id: int


class TransactionCreateAndLink(BaseModel):
    """Schema for creating transaction and linking to source event"""
    card_id: int | None = None
    amount: Decimal | None = Field(None, decimal_places=2)
    currency: str | None = Field(None, min_length=3, max_length=3)
    transaction_datetime: datetime | None = None
    posting_datetime: datetime | None = None
    description: str | None = None
    location: str | None = None
    transaction_kind: str | None = Field(None, pattern="^(purchase|topup|refund|other)$")
    original_amount: Decimal | None = Field(None, decimal_places=2)
    original_currency: str | None = Field(None, min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(None, decimal_places=6)
    fx_fee: Decimal | None = Field(None, decimal_places=2)


class TransactionSourceLinkResponse(BaseModel):
    """Schema for transaction-source link"""
    transaction_id: int
    source_event_id: int
    match_confidence: float | None = None
    is_primary: bool
    source_event: SourceEventResponse
    
    model_config = {"from_attributes": True}


class TransactionSourceLinkUpdate(BaseModel):
    """Schema for updating transaction-source link"""
    match_confidence: float | None = None
    is_primary: bool | None = None
