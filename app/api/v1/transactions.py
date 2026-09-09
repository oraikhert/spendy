"""Transactions API endpoints"""
from typing import Annotated
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workspace_context import WorkspaceContext
from app.core.workspace_deps import get_api_workspace, get_api_workspace_write, WorkspaceRoute
from app.database import get_db
from app.schemas.transaction import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionListResponse
)
from app.schemas.transaction_observation import TransactionSourceLinkResponse
from app.services import transaction_service


router = APIRouter(route_class=WorkspaceRoute, prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionListResponse)
async def get_transactions(
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)],
    account_id: int | None = Query(None, gt=0),
    card_id: int | None = Query(None, gt=0),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None, pattern="^(purchase|topup|refund|other)$"),
    min_amount: Decimal | None = Query(None),
    max_amount: Decimal | None = Query(None),
    currency: str | None = Query(None),
    direction: str | None = Query(None, pattern="^(out|in)$"),
    min_abs_amount: Decimal | None = Query(None),
    max_abs_amount: Decimal | None = Query(None),
    excluded_from_summary: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get transactions with filters"""
    try:
        transactions, total = await transaction_service.get_transactions(
            context,
            db=db,
            account_id=account_id,
            card_id=card_id,
            date_from=date_from,
            date_to=date_to,
            q=q,
            kind=kind,
            min_amount=min_amount,
            max_amount=max_amount,
            currency=currency,
            direction=direction,
            min_abs_amount=min_abs_amount,
            max_abs_amount=max_abs_amount,
            excluded_from_summary=excluded_from_summary,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    
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
    context: Annotated[WorkspaceContext, Depends(get_api_workspace_write)]
):
    """Create a new transaction"""
    try:
        transaction = await transaction_service.create_transaction(context, db, transaction_data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return transaction


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)]
):
    """Get transaction by ID"""
    transaction = await transaction_service.get_transaction(context, db, transaction_id)
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
    context: Annotated[WorkspaceContext, Depends(get_api_workspace_write)]
):
    """Update transaction"""
    try:
        transaction = await transaction_service.update_transaction(
            context,
            db, transaction_id, transaction_data
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
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
    context: Annotated[WorkspaceContext, Depends(get_api_workspace_write)]
):
    """Delete transaction"""
    success = await transaction_service.delete_transaction(context, db, transaction_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    return None


@router.get("/{transaction_id}/observations", response_model=list[TransactionSourceLinkResponse])
async def get_transaction_observations(
    transaction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    context: Annotated[WorkspaceContext, Depends(get_api_workspace)],
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Get the transaction's ordered source-observation links."""
    if await transaction_service.get_transaction(context, db, transaction_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    links = await transaction_service.get_transaction_observations(
        context,
        db, transaction_id, limit, offset
    )
    return links
