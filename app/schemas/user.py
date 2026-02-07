"""User schemas for request/response validation"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class UserBase(BaseModel):
    """Base user schema with common attributes"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    full_name: str | None = None
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for user creation"""
    password: str = Field(..., min_length=8, max_length=72)


class UserUpdate(BaseModel):
    """Schema for user update"""
    email: EmailStr | None = None
    username: str | None = Field(None, min_length=3, max_length=100)
    full_name: str | None = None
    password: str | None = Field(None, min_length=8, max_length=72)
    is_active: bool | None = None


class UserInDB(UserBase):
    """Schema for user in database (includes hashed password)"""
    id: int
    hashed_password: str
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class User(UserBase):
    """Schema for user response (public data)"""
    id: int
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    """Schema for JWT token response"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Schema for token payload data"""
    user_id: int | None = None
    username: str | None = None
