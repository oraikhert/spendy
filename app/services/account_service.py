"""Account service"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.card import Card
from app.schemas.account import AccountCreate, AccountUpdate


async def create_account(db: AsyncSession, account_data: AccountCreate) -> Account:
    """Create a new account"""
    account = Account(**account_data.model_dump())
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def get_account(db: AsyncSession, account_id: int) -> Account | None:
    """Get account by ID"""
    result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    return result.scalar_one_or_none()


async def get_accounts(db: AsyncSession) -> list[Account]:
    """Get all accounts"""
    result = await db.execute(
        select(Account)
        .options(selectinload(Account.cards))
        .order_by(Account.institution, Account.name)
    )
    return list(result.scalars().all())


async def get_account_cards(db: AsyncSession, account_id: int) -> list[Card]:
    """Get all cards for an account"""
    result = await db.execute(
        select(Card)
        .where(Card.account_id == account_id)
        .order_by(Card.name)
    )
    return list(result.scalars().all())


async def update_account(
    db: AsyncSession,
    account_id: int,
    account_data: AccountUpdate
) -> Account | None:
    """Update account"""
    account = await get_account(db, account_id)
    if not account:
        return None
    
    update_data = account_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(account, field, value)
    
    await db.commit()
    await db.refresh(account)
    return account


async def delete_account(db: AsyncSession, account_id: int) -> bool:
    """Delete account (hard delete)"""
    account = await get_account(db, account_id)
    if not account:
        return False
    
    await db.delete(account)
    await db.commit()
    return True
