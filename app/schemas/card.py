"""Card schemas"""
from datetime import datetime
from pydantic import BaseModel, Field


class CardBase(BaseModel):
    """Base card schema"""
    card_masked_number: str = Field(..., max_length=255)
    card_type: str = Field(..., pattern="^(debit|credit)$")
    name: str = Field(..., max_length=255)


class CardCreate(CardBase):
    """Schema for creating a card"""
    pass


class CardUpdate(BaseModel):
    """Schema for updating a card"""
    card_masked_number: str | None = Field(None, max_length=255)
    card_type: str | None = Field(None, pattern="^(debit|credit)$")
    name: str | None = Field(None, max_length=255)


class CardResponse(CardBase):
    """Schema for card response"""
    id: int
    account_id: int
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}
