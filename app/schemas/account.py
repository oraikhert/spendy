"""Account schemas"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from app.utils.business_time import DEFAULT_TIMEZONE, normalize_timezone_name


class AccountBase(BaseModel):
    """Base account schema"""
    institution: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    account_currency: str = Field(..., min_length=3, max_length=3)
    timezone: str = Field(DEFAULT_TIMEZONE, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return normalize_timezone_name(value)


class AccountCreate(AccountBase):
    """Schema for creating an account"""
    pass


class AccountUpdate(BaseModel):
    """Schema for updating an account"""
    institution: str | None = Field(None, max_length=255)
    name: str | None = Field(None, max_length=255)
    account_currency: str | None = Field(None, min_length=3, max_length=3)
    timezone: str | None = Field(None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("timezone cannot be null")
        return normalize_timezone_name(value)


class AccountResponse(AccountBase):
    """Schema for account response"""
    id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}
