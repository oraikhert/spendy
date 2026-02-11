"""Account schemas"""
from datetime import datetime
from pydantic import BaseModel, Field


class AccountBase(BaseModel):
    """Base account schema"""
    institution: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    account_currency: str = Field(..., min_length=3, max_length=3)


class AccountCreate(AccountBase):
    """Schema for creating an account"""
    pass


class AccountUpdate(BaseModel):
    """Schema for updating an account"""
    institution: str | None = Field(None, max_length=255)
    name: str | None = Field(None, max_length=255)
    account_currency: str | None = Field(None, min_length=3, max_length=3)


class AccountResponse(AccountBase):
    """Schema for account response"""
    id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}
