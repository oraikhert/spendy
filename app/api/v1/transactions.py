"""Transactions API endpoints"""
from typing import Annotated
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.deps import get_current_active_user
from app.models.user import User
from app.schemas.transaction import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionListResponse
)
from app.schemas.source_event import (
    TransactionSourceLinkResponse,
    TransactionSourceLinkUpdate
)
from app.services import transaction_service


router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionListResponse)
async def get_transactions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None, pattern="^(purchase|topup|refund|other)$"),
    currency: str | None = Query(None, min_length=3, max_length=3),
    min_amount: Decimal | None = Query(None),
    max_amount: Decimal | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get transactions with filters"""
    transactions, total = await transaction_service.get_transactions(
        db=db,
        account_id=account_id,
        card_id=card_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        kind=kind,
        currency=currency,
        min_amount=min_amount,
        max_amount=max_amount,
        limit=limit,
        offset=offset
    )
    
    return TransactionListResponse(
        items=transactions,
        limit=limit,
        offset=offset,
        total=total
    )


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    transaction_data: TransactionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Create a new transaction"""
    transaction = await transaction_service.create_transaction(db, transaction_data)
    return transaction


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Get transaction by ID"""
    transaction = await transaction_service.get_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    return transaction


@router.patch("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: int,
    transaction_data: TransactionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Update transaction"""
    transaction = await transaction_service.update_transaction(
        db, transaction_id, transaction_data
    )
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    return transaction


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Delete transaction"""
    success = await transaction_service.delete_transaction(db, transaction_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    return None


@router.get("/{transaction_id}/sources", response_model=list[TransactionSourceLinkResponse])
async def get_transaction_sources(
    transaction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Get all source events linked to a transaction"""
    links = await transaction_service.get_transaction_sources(db, transaction_id)
    return links


@router.patch(
    "/{transaction_id}/sources/{source_event_id}",
    response_model=TransactionSourceLinkResponse
)
async def update_transaction_source_link(
    transaction_id: int,
    source_event_id: int,
    link_data: TransactionSourceLinkUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Update a transaction-source link (MVP: set primary)."""
    link = await transaction_service.get_source_link(db, transaction_id, source_event_id)
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction-source link not found"
        )

    if link_data.is_primary is True:
        updated_link = await transaction_service.set_primary_source_link(
            db, transaction_id, source_event_id
        )
        if not updated_link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction-source link not found"
            )
        link = await transaction_service.get_source_link(db, transaction_id, source_event_id)
        if not link:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction-source link not found after update"
            )

    return link
