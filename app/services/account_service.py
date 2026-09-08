"""Account service"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.workspace_context import WorkspaceContext
from app.models.account import Account
from app.schemas.account import AccountCreate, AccountUpdate


async def create_account(context: WorkspaceContext, db: AsyncSession, account_data: AccountCreate) -> Account:
    """Create a new account"""
    context.require_write()
    account = Account(workspace_id=context.workspace_id, **account_data.model_dump())
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def get_account(context: WorkspaceContext, db: AsyncSession, account_id: int) -> Account | None:
    """Get account by ID"""
    result = await db.execute(
        select(Account).where(Account.workspace_id == context.workspace_id).where(Account.id == account_id)
    )
    return result.scalar_one_or_none()


async def get_accounts(context: WorkspaceContext, db: AsyncSession) -> list[Account]:
    """Get all accounts"""
    result = await db.execute(select(Account).where(Account.workspace_id == context.workspace_id).order_by(Account.id))
    return list(result.scalars().all())


async def update_account(
    context: WorkspaceContext,
    db: AsyncSession,
    account_id: int,
    account_data: AccountUpdate
) -> Account | None:
    """Update account"""
    context.require_write()
    account = await get_account(context, db, account_id)
    if not account:
        return None
    
    update_data = account_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(account, field, value)
    if "timezone" in update_data:
        from app.services.transaction_service import (
            refresh_account_transaction_fingerprints,
        )

        await refresh_account_transaction_fingerprints(context, db, account_id)
    
    await db.commit()
    await db.refresh(account)
    return account


async def delete_account(context: WorkspaceContext, db: AsyncSession, account_id: int) -> bool:
    """Delete account (hard delete)"""
    context.require_write()
    account = await get_account(context, db, account_id)
    if not account:
        return False
    
    await db.delete(account)
    await db.commit()
    return True
