"""Card service"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.workspace_context import WorkspaceContext, WorkspaceAccessError, workspace_get
from app.models.card import Card
from app.models.account import Account
from app.schemas.card import CardCreate, CardUpdate


async def create_card(
    context: WorkspaceContext,
    db: AsyncSession,
    account_id: int,
    card_data: CardCreate
) -> Card:
    """Create a new card"""
    context.require_write()
    if await workspace_get(db, Account, account_id, context=context) is None:
        raise WorkspaceAccessError(404, "Not Found")
    card = Card(workspace_id=context.workspace_id, account_id=account_id, **card_data.model_dump())
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


async def get_card(context: WorkspaceContext, db: AsyncSession, card_id: int) -> Card | None:
    """Get card by ID"""
    result = await db.execute(
        select(Card).where(Card.workspace_id == context.workspace_id).where(Card.id == card_id)
    )
    return result.scalar_one_or_none()


async def get_cards_by_account(context: WorkspaceContext, db: AsyncSession, account_id: int) -> list[Card]:
    """Get all cards for an account"""
    if await workspace_get(db, Account, account_id, context=context) is None:
        raise WorkspaceAccessError(404, "Not Found")
    result = await db.execute(
        select(Card).where(Card.workspace_id == context.workspace_id).where(Card.account_id == account_id).order_by(Card.id)
    )
    return list(result.scalars().all())


async def update_card(
    context: WorkspaceContext,
    db: AsyncSession,
    card_id: int,
    card_data: CardUpdate
) -> Card | None:
    """Update card"""
    context.require_write()
    card = await get_card(context, db, card_id)
    if not card:
        return None
    
    update_data = card_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(card, field, value)
    if "timezone" in update_data:
        from app.services.transaction_service import refresh_card_transaction_fingerprints

        await refresh_card_transaction_fingerprints(context, db, card_id)
    
    await db.commit()
    await db.refresh(card)
    return card


async def delete_card(context: WorkspaceContext, db: AsyncSession, card_id: int) -> bool:
    """Delete card (hard delete)"""
    context.require_write()
    card = await get_card(context, db, card_id)
    if not card:
        return False
    
    await db.delete(card)
    await db.commit()
    return True
