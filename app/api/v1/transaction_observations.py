"""Transaction observation query and final-link API."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.transaction import MAX_RECORD_ID, TransactionResponse
from app.schemas.transaction_observation import (
    TransactionCreateFromObservation,
    TransactionLinkCreate,
    TransactionObservationDetail,
    TransactionObservationListResponse,
    TransactionSourceLinkResponse,
)
from app.services import source_processing_service
from app.services.source_processing_service import (
    SourceConflictError,
    SourceNotFoundError,
    SourceValidationError,
)


router = APIRouter(prefix="/transaction-observations", tags=["transaction-observations"])


def _raise_source_error(exc: Exception) -> None:
    if isinstance(exc, SourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, SourceConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, SourceValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    raise exc


@router.get("", response_model=TransactionObservationListResponse)
async def list_transaction_observations(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    source_payload_id: int | None = Query(None, gt=0, le=MAX_RECORD_ID),
    account_id: int | None = Query(None, gt=0, le=MAX_RECORD_ID),
    card_id: int | None = Query(None, gt=0, le=MAX_RECORD_ID),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    has_transaction: bool | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    observations, total = await source_processing_service.list_transaction_observations(
        db,
        source_payload_id=source_payload_id,
        account_id=account_id,
        card_id=card_id,
        date_from=date_from,
        date_to=date_to,
        has_transaction=has_transaction,
        limit=limit,
        offset=offset,
    )
    return TransactionObservationListResponse(
        items=observations, limit=limit, offset=offset, total=total
    )


@router.get("/{observation_id}", response_model=TransactionObservationDetail)
async def get_transaction_observation(
    observation_id: Annotated[int, Path(gt=0, le=MAX_RECORD_ID)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    observation = await source_processing_service.get_transaction_observation(db, observation_id)
    if observation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction observation not found",
        )
    return observation


@router.post(
    "/{observation_id}/link",
    response_model=TransactionSourceLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def link_observation(
    observation_id: Annotated[int, Path(gt=0, le=MAX_RECORD_ID)],
    link_data: TransactionLinkCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    try:
        return await source_processing_service.link_observation_to_transaction(
            db, observation_id, link_data.transaction_id
        )
    except (SourceConflictError, SourceNotFoundError, SourceValidationError) as exc:
        _raise_source_error(exc)


@router.post(
    "/{observation_id}/move",
    response_model=TransactionSourceLinkResponse,
)
async def move_observation(
    observation_id: Annotated[int, Path(gt=0, le=MAX_RECORD_ID)],
    link_data: TransactionLinkCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    try:
        return await source_processing_service.move_observation_to_transaction(
            db, observation_id, link_data.transaction_id
        )
    except (SourceConflictError, SourceNotFoundError, SourceValidationError) as exc:
        _raise_source_error(exc)


@router.post(
    "/{observation_id}/transaction",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_transaction_from_observation(
    observation_id: Annotated[int, Path(gt=0, le=MAX_RECORD_ID)],
    transaction_data: TransactionCreateFromObservation,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    try:
        return await source_processing_service.create_transaction_from_observation(
            db, observation_id, transaction_data
        )
    except (SourceConflictError, SourceNotFoundError, SourceValidationError) as exc:
        _raise_source_error(exc)


@router.delete("/{observation_id}/link", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_observation(
    observation_id: Annotated[int, Path(gt=0, le=MAX_RECORD_ID)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    if not await source_processing_service.unlink_observation(db, observation_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    return None
