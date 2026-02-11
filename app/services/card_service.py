"""Card service"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.card import Card
from app.schemas.card import CardCreate, CardUpdate


async def create_card(
    db: AsyncSession,
    account_id: int,
    card_data: CardCreate
) -> Card:
    """Create a new card"""
    card = Card(account_id=account_id, **card_data.model_dump())
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


async def get_card(db: AsyncSession, card_id: int) -> Card | None:
    """Get card by ID"""
    result = await db.execute(
        select(Card).where(Card.id == card_id)
    )
    return result.scalar_one_or_none()


async def get_cards_by_account(db: AsyncSession, account_id: int) -> list[Card]:
    """Get all cards for an account"""
    result = await db.execute(
        select(Card).where(Card.account_id == account_id)
    )
    return list(result.scalars().all())


async def update_card(
    db: AsyncSession,
    card_id: int,
    card_data: CardUpdate
) -> Card | None:
    """Update card"""
    card = await get_card(db, card_id)
    if not card:
        return None
    
    update_data = card_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(card, field, value)
    
    await db.commit()
    await db.refresh(card)
    return card


async def delete_card(db: AsyncSession, card_id: int) -> bool:
    """Delete card (hard delete)"""
    card = await get_card(db, card_id)
    if not card:
        return False
    
    await db.delete(card)
    await db.commit()
    return True
