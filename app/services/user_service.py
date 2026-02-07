"""User service for user-related business logic"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate
from app.core.security import get_password_hash


async def get_user_by_id(user_id: int, db: AsyncSession) -> User | None:
    """
    Get user by ID.
    
    Args:
        user_id: User ID
        db: Database session
        
    Returns:
        User | None: User object or None if not found
    """
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(email: str, db: AsyncSession) -> User | None:
    """
    Get user by email.
    
    Args:
        email: User email
        db: Database session
        
    Returns:
        User | None: User object or None if not found
    """
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_username(username: str, db: AsyncSession) -> User | None:
    """
    Get user by username.
    
    Args:
        username: Username
        db: Database session
        
    Returns:
        User | None: User object or None if not found
    """
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_username_or_email(identifier: str, db: AsyncSession) -> User | None:
    """
    Get user by username or email.
    
    Args:
        identifier: Username or email
        db: Database session
        
    Returns:
        User | None: User object or None if not found
    """
    result = await db.execute(
        select(User).where(
            (User.username == identifier) | (User.email == identifier)
        )
    )
    return result.scalar_one_or_none()


async def create_user(user_in: UserCreate, db: AsyncSession) -> User:
    """
    Create a new user.
    
    Args:
        user_in: User creation data
        db: Database session
        
    Returns:
        User: Created user object
        
    Raises:
        ValueError: If email or username already exists
    """
    # Check if email already exists
    existing_user = await get_user_by_email(user_in.email, db)
    if existing_user:
        raise ValueError("Email already registered")
    
    # Check if username already exists
    existing_user = await get_user_by_username(user_in.username, db)
    if existing_user:
        raise ValueError("Username already taken")
    
    # Create new user
    db_user = User(
        email=user_in.email,
        username=user_in.username,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        is_active=user_in.is_active,
    )
    
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    
    return db_user


async def update_user(user_id: int, user_update: UserUpdate, db: AsyncSession) -> User:
    """
    Update an existing user.
    
    Args:
        user_id: User ID to update
        user_update: User update data
        db: Database session
        
    Returns:
        User: Updated user object
        
    Raises:
        ValueError: If user not found or validation fails
    """
    # Get existing user
    user = await get_user_by_id(user_id, db)
    if not user:
        raise ValueError("User not found")
    
    # Update fields if provided
    update_data = user_update.model_dump(exclude_unset=True)
    
    # Check email uniqueness if being updated
    if "email" in update_data and update_data["email"] != user.email:
        existing_user = await get_user_by_email(update_data["email"], db)
        if existing_user:
            raise ValueError("Email already registered")
    
    # Check username uniqueness if being updated
    if "username" in update_data and update_data["username"] != user.username:
        existing_user = await get_user_by_username(update_data["username"], db)
        if existing_user:
            raise ValueError("Username already taken")
    
    # Hash password if being updated
    if "password" in update_data:
        update_data["hashed_password"] = get_password_hash(update_data.pop("password"))
    
    # Apply updates
    for field, value in update_data.items():
        setattr(user, field, value)
    
    await db.commit()
    await db.refresh(user)
    
    return user
