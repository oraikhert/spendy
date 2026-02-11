"""Cards API endpoints"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.deps import get_current_active_user
from app.models.user import User
from app.schemas.card import CardCreate, CardUpdate, CardResponse
from app.services import card_service


router = APIRouter(tags=["cards"])


@router.get("/accounts/{account_id}/cards", response_model=list[CardResponse])
async def get_cards_by_account(
    account_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Get all cards for an account"""
    cards = await card_service.get_cards_by_account(db, account_id)
    return cards


@router.post("/accounts/{account_id}/cards", response_model=CardResponse, status_code=status.HTTP_201_CREATED)
async def create_card(
    account_id: int,
    card_data: CardCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Create a new card for an account"""
    card = await card_service.create_card(db, account_id, card_data)
    return card


@router.get("/cards/{card_id}", response_model=CardResponse)
async def get_card(
    card_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Get card by ID"""
    card = await card_service.get_card(db, card_id)
    if not card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found"
        )
    return card


@router.patch("/cards/{card_id}", response_model=CardResponse)
async def update_card(
    card_id: int,
    card_data: CardUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Update card"""
    card = await card_service.update_card(db, card_id, card_data)
    if not card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found"
        )
    return card


@router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(
    card_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Delete card"""
    success = await card_service.delete_card(db, card_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Card not found"
        )
    return None
