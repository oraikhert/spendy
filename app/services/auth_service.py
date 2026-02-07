"""Authentication service for authentication-related business logic"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import Token
from app.core.security import verify_password, create_access_token
from app.services.user_service import get_user_by_username_or_email


async def authenticate_user(username_or_email: str, password: str, db: AsyncSession) -> User:
    """
    Authenticate a user with username/email and password.
    
    Args:
        username_or_email: Username or email
        password: Plain text password
        db: Database session
        
    Returns:
        User: Authenticated user object
        
    Raises:
        ValueError: If authentication fails or user is inactive
    """
    # Try to find user by username or email
    user = await get_user_by_username_or_email(username_or_email, db)
    
    # Check if user exists and password is correct
    if not user or not verify_password(password, user.hashed_password):
        raise ValueError("Incorrect username or password")
    
    # Check if user is active
    if not user.is_active:
        raise ValueError("Inactive user")
    
    return user


async def create_user_access_token(user: User) -> Token:
    """
    Create an access token for a user.
    
    Args:
        user: User object
        
    Returns:
        Token: Token schema with access_token and token_type
    """
    # Create access token (sub must be string for JWT)
    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username}
    )
    
    return Token(access_token=access_token, token_type="bearer")
