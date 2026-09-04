"""Transaction schemas"""
from datetime import datetime
from decimal import Decimal
import re
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Amount = Annotated[Decimal, Field(max_digits=15, decimal_places=2, allow_inf_nan=False)]
MAX_RECORD_ID = 2**31 - 1  # PostgreSQL Integer, also safely bindable on SQLite.
ExchangeRate = Annotated[
    Decimal, Field(max_digits=15, decimal_places=6, allow_inf_nan=False, gt=0)
]


def normalize_currency(value: str) -> str:
    """Normalize user input without changing stored legacy values on reads."""
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z]{3}", value):
        raise ValueError("Use three Latin letters for the currency")
    return value.upper()


def validate_original_values(
    original_amount: Decimal | None,
    original_currency: str | None,
    fx_rate: Decimal | None,
) -> None:
    """Validate a complete new or changed original-currency group."""
    if original_amount is None and original_currency is not None:
        raise ValueError("original_amount: Enter the original amount and currency together")
    if original_amount is not None and original_currency is None:
        raise ValueError("original_currency: Enter the original amount and currency together")
    if fx_rate is not None and original_amount is None:
        raise ValueError("fx_rate: An exchange rate requires an original amount and currency")


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


class TransactionInput(BaseModel):
    """Shared normalization for direct CRUD; response models remain separate."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("currency", "original_currency", mode="before", check_fields=False)
    @classmethod
    def normalize_input_currency(cls, value):
        if value is None or not isinstance(value, str):
            return value
        return normalize_currency(value)

    @field_validator("description", mode="before", check_fields=False)
    @classmethod
    def trim_description(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Enter a description")
        return value

    @field_validator("location", mode="before", check_fields=False)
    @classmethod
    def trim_location(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class TransactionCreate(TransactionInput):
    """Validated values for a new transaction, with no ingestion side effects."""

    card_id: int = Field(..., gt=0, le=MAX_RECORD_ID)
    amount: Amount
    currency: str
    transaction_datetime: datetime | None = None
    posting_datetime: datetime | None = None
    description: str
    location: str | None = Field(None, max_length=200)
    transaction_kind: str = Field(..., pattern="^(purchase|topup|refund|other)$")
    original_amount: Amount | None = None
    original_currency: str | None = None
    fx_rate: ExchangeRate | None = None
    fx_fee: Amount | None = None

    @model_validator(mode="after")
    def consistent_original_values(self) -> Self:
        validate_original_values(self.original_amount, self.original_currency, self.fx_rate)
        return self


class TransactionUpdate(TransactionInput):
    """Schema for updating a transaction"""
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

    @field_validator("amount", "currency", "description", "transaction_kind")
    @classmethod
    def required_fields_cannot_be_cleared(cls, value):
        if value is None:
            raise ValueError("This field is required and cannot be cleared")
        return value


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
