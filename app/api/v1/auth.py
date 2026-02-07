"""Authentication routes"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, User as UserSchema, Token
from app.core.deps import get_current_active_user
from app.services import user_service, auth_service


router = APIRouter()


@router.post("/register", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """
    Register a new user.
    
    Args:
        user_in: User registration data
        db: Database session
        
    Returns:
        User: Created user
        
    Raises:
        HTTPException: If email or username already exists
    """
    try:
        user = await user_service.create_user(user_in, db)
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> Token:
    """
    Login user and return access token.
    
    Args:
        form_data: OAuth2 form with username and password
        db: Database session
        
    Returns:
        Token: Access token
        
    Raises:
        HTTPException: If credentials are incorrect
    """
    try:
        user = await auth_service.authenticate_user(
            form_data.username, form_data.password, db
        )
        token = await auth_service.create_user_access_token(user)
        return token
    except ValueError as e:
        # Map service exceptions to appropriate HTTP status codes
        if "Inactive" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )


@router.get("/me", response_model=UserSchema)
async def get_me(
    current_user: Annotated[User, Depends(get_current_active_user)]
) -> User:
    """
    Get current user information.
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        User: Current user data
    """
    return current_user
