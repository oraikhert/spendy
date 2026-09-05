"""Source payload registration and processing API."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Path, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.source_payload import IngestionMethod, ProcessingStatus, SourceKind
from app.models.user import User
from app.schemas.source_payload import (
    SourcePayloadCreateText,
    SourcePayloadDetail,
    SourcePayloadListResponse,
)
from app.schemas.transaction import MAX_RECORD_ID
from app.services import source_processing_service
from app.services.source_processing_service import (
    SourceConflictError,
    SourceNotFoundError,
    SourceUploadTooLargeError,
    SourceValidationError,
)


router = APIRouter(prefix="/source-payloads", tags=["source-payloads"])


def _raise_source_error(exc: Exception) -> None:
    if isinstance(exc, SourceNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, SourceConflictError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if isinstance(exc, SourceUploadTooLargeError):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    if isinstance(exc, SourceValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    raise exc


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise SourceValidationError("Idempotency-Key must not be blank")
    return normalized


@router.post("/text", response_model=SourcePayloadDetail, status_code=status.HTTP_201_CREATED)
async def create_text_payload(
    source_data: SourcePayloadCreateText,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
):
    try:
        payload, replayed = await source_processing_service.create_text_payload(
            db, source_data, _normalize_idempotency_key(idempotency_key)
        )
    except (SourceConflictError, SourceNotFoundError, SourceValidationError) as exc:
        _raise_source_error(exc)
    if replayed:
        response.status_code = status.HTTP_200_OK
    return payload


@router.post("/upload", response_model=SourcePayloadDetail, status_code=status.HTTP_201_CREATED)
async def create_upload_payload(
    response: Response,
    file: Annotated[UploadFile, File()],
    source_kind: Annotated[SourceKind, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    account_id: Annotated[int | None, Form(gt=0, le=MAX_RECORD_ID)] = None,
    card_id: Annotated[int | None, Form(gt=0, le=MAX_RECORD_ID)] = None,
    password: Annotated[str | None, Form(max_length=255)] = None,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=255)
    ] = None,
):
    try:
        payload, replayed = await source_processing_service.create_upload_payload(
            db,
            file=file,
            source_kind=source_kind,
            account_id=account_id,
            card_id=card_id,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            password=password,
        )
    except (SourceConflictError, SourceNotFoundError, SourceValidationError) as exc:
        _raise_source_error(exc)
    if replayed:
        response.status_code = status.HTTP_200_OK
    return payload


@router.get("", response_model=SourcePayloadListResponse)
async def list_source_payloads(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    source_kind: SourceKind | None = None,
    media_type: str | None = Query(None, min_length=1, max_length=255),
    ingestion_method: IngestionMethod | None = None,
    processing_status: ProcessingStatus | None = None,
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    has_observations: bool | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    payloads, total = await source_processing_service.list_source_payloads(
        db,
        source_kind=source_kind.value if source_kind else None,
        media_type=media_type,
        ingestion_method=ingestion_method.value if ingestion_method else None,
        processing_status=processing_status.value if processing_status else None,
        received_from=received_from,
        received_to=received_to,
        has_observations=has_observations,
        limit=limit,
        offset=offset,
    )
    return SourcePayloadListResponse(items=payloads, limit=limit, offset=offset, total=total)


@router.get("/{payload_id}", response_model=SourcePayloadDetail)
async def get_source_payload(
    payload_id: Annotated[int, Path(gt=0, le=MAX_RECORD_ID)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    payload = await source_processing_service.get_source_payload(db, payload_id)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source payload not found")
    return payload


@router.post("/{payload_id}/reprocess", response_model=SourcePayloadDetail)
async def reprocess_source_payload(
    payload_id: Annotated[int, Path(gt=0, le=MAX_RECORD_ID)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    force_manual_links: bool = Query(
        False,
        description="Explicitly allow replacement of manually linked observations",
    ),
    password: Annotated[str | None, Form(max_length=255)] = None,
):
    try:
        return await source_processing_service.reprocess_source_payload(
            db,
            payload_id,
            password=password,
            force_manual_links=force_manual_links,
        )
    except (SourceConflictError, SourceNotFoundError, SourceValidationError) as exc:
        _raise_source_error(exc)
