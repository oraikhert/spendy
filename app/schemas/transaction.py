"""Transaction schemas"""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class TransactionBase(BaseModel):
    """Base transaction schema"""
    amount: Decimal = Field(..., decimal_places=2)
    currency: str = Field(..., min_length=3, max_length=3)
    transaction_datetime: datetime | None = None
    posting_datetime: datetime | None = None
    description: str
    location: str | None = None
    transaction_kind: str = Field(..., pattern="^(purchase|topup|refund|other)$")
    original_amount: Decimal | None = Field(None, decimal_places=2)
    original_currency: str | None = Field(None, min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(None, decimal_places=6)
    fx_fee: Decimal | None = Field(None, decimal_places=2)


class TransactionCreate(TransactionBase):
    """Schema for creating a transaction"""
    card_id: int


class TransactionUpdate(BaseModel):
    """Schema for updating a transaction"""
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


class TransactionResponse(TransactionBase):
    """Schema for transaction response"""
    id: int
    card_id: int
    merchant_norm: str | None = None
    fingerprint: str | None = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    """Schema for paginated transaction list"""
    items: list[TransactionResponse]
    limit: int
    offset: int
    total: int
