"""SourceEvents API endpoints"""
from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from app.database import get_db
from app.core.deps import get_current_active_user
from app.models.user import User
from app.schemas.source_event import (
    SourceEventCreateText,
    SourceEventResponse,
    SourceEventListResponse,
    TransactionLinkCreate,
    TransactionCreateAndLink,
    TransactionSourceLinkResponse
)
from app.schemas.transaction import TransactionResponse
from app.services import source_event_service


router = APIRouter(prefix="/source-events", tags=["source-events"])


@router.post("/text", response_model=SourceEventResponse, status_code=status.HTTP_201_CREATED)
async def create_source_event_text(
    source_data: SourceEventCreateText,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Create source event from text and attempt automatic matching"""
    try:
        source_event = await source_event_service.create_source_event_from_text(
            db, source_data
        )
        return source_event
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/upload", response_model=SourceEventResponse, status_code=status.HTTP_201_CREATED)
async def upload_source_event_file(
    file: Annotated[UploadFile, File()],
    source_type: Annotated[str, Form(pattern="^(sms_screenshot|bank_screenshot|pdf_statement)$")],
    account_id: Annotated[int | None, Form()] = None,
    card_id: Annotated[int | None, Form()] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """Upload file (PDF/image) as source event"""
    # Read file content
    file_content = await file.read()
    
    try:
        source_event = await source_event_service.create_source_event_from_file(
            db=db,
            source_type=source_type,
            file_content=file_content,
            filename=file.filename or "unnamed",
            account_id=account_id,
            card_id=card_id
        )
        return source_event
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("", response_model=SourceEventListResponse)
async def get_source_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    source_type: str | None = Query(None, pattern="^(telegram_text|sms_text|sms_screenshot|bank_screenshot|pdf_statement|manual)$"),
    parse_status: str | None = Query(None, pattern="^(new|parsed|failed)$"),
    received_from: datetime | None = Query(None),
    received_to: datetime | None = Query(None),
    has_transaction: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get source events (inbox) with filters"""
    source_events, total = await source_event_service.get_source_events(
        db=db,
        source_type=source_type,
        parse_status=parse_status,
        date_from=received_from,
        date_to=received_to,
        has_transaction=has_transaction,
        limit=limit,
        offset=offset
    )
    
    return SourceEventListResponse(
        items=source_events,
        limit=limit,
        offset=offset,
        total=total
    )


@router.get("/{source_event_id}", response_model=SourceEventResponse)
async def get_source_event(
    source_event_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Get source event details"""
    source_event = await source_event_service.get_source_event(db, source_event_id)
    if not source_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source event not found"
        )
    return source_event


@router.post("/{source_event_id}/link", response_model=TransactionSourceLinkResponse, status_code=status.HTTP_201_CREATED)
async def link_source_to_transaction(
    source_event_id: int,
    link_data: TransactionLinkCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Manually link source event to existing transaction"""
    try:
        link = await source_event_service.link_source_to_transaction(
            db, source_event_id, link_data.transaction_id
        )
        return link
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{source_event_id}/create-transaction-and-link", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction_and_link(
    source_event_id: int,
    transaction_data: TransactionCreateAndLink,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Create new transaction from source event and link them"""
    try:
        transaction, link = await source_event_service.create_transaction_and_link(
            db, source_event_id, transaction_data
        )
        return transaction
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/{source_event_id}/link/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_source_from_transaction(
    source_event_id: int,
    transaction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Unlink source event from transaction"""
    success = await source_event_service.unlink_source_from_transaction(
        db, source_event_id, transaction_id
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link not found"
        )
    return None


@router.post("/{source_event_id}/reprocess", response_model=SourceEventResponse)
async def reprocess_source_event(
    source_event_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Reprocess source event (re-run parsing and matching)"""
    try:
        source_event = await source_event_service.reprocess_source_event(
            db, source_event_id
        )
        return source_event
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.get("/{source_event_id}/download")
async def download_source_event_file(
    source_event_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    """Download source event file"""
    source_event = await source_event_service.get_source_event(db, source_event_id)
    if not source_event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source event not found"
        )
    
    if not source_event.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No file associated with this source event"
        )
    
    file_path = Path(source_event.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on server"
        )
    
    return FileResponse(
        path=file_path,
        filename=file_path.name
    )
