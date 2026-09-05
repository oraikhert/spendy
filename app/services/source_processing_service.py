"""Registration, parsing, matching, and linking for source payloads."""

import hashlib
import os
import re
import tempfile
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.models.account import Account
from app.models.bank_statement_detail import BankStatementDetail
from app.models.card import Card
from app.models.source_payload import (
    IngestionMethod,
    ProcessingStatus,
    SourceKind,
    SourcePayload,
)
from app.models.transaction import Transaction
from app.models.transaction_observation import TransactionObservation
from app.models.transaction_source_link import MatchMethod, TransactionSourceLink
from app.schemas.source_payload import SourcePayloadCreateText
from app.schemas.transaction_observation import TransactionCreateFromObservation
from app.services.exchange_rate_service import exchange_rate_service
from app.services.source_parsers import (
    ObservationInput,
    get_parsers,
    run_registered_parser,
)
from app.utils.source_parsing.contracts import (
    InvalidSourceInputError,
    ParseStatus,
    SourceParseResult,
    UnsupportedSourceError,
)
from app.utils.business_time import (
    DEFAULT_TIMEZONE,
    business_date,
    effective_card_timezone,
    normalize_timezone_name,
)
from app.utils.canonicalization import canonicalize_transaction
from app.utils.matching import (
    find_card_by_last_four,
    find_cards_by_last_four,
    find_matching_transactions,
    generate_fingerprint,
    normalize_merchant,
    select_statement_match,
)


MATCHER_NAME = "same_day_amount_merchant"
MATCHER_VERSION = "4"
STATEMENT_MATCHER_NAME = "statement_same_day_amount_score"
STATEMENT_MATCHER_VERSION = "3"
UPLOAD_CHUNK_SIZE = 1024 * 1024


class SourceProcessingError(ValueError):
    """Base class for expected source-domain failures."""


class SourceConflictError(SourceProcessingError):
    pass


class SourceNotFoundError(SourceProcessingError):
    pass


class SourceValidationError(SourceProcessingError):
    pass


class SourceUploadTooLargeError(SourceValidationError):
    pass


def _compact_metadata(**values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        result[key] = value.isoformat() if isinstance(value, datetime) else value
    return result


async def _validate_context(
    db: AsyncSession, account_id: int | None, card_id: int | None
) -> None:
    account = await db.get(Account, account_id) if account_id is not None else None
    if account_id is not None and account is None:
        raise SourceValidationError("account_id: Account not found")
    card = await db.get(Card, card_id) if card_id is not None else None
    if card_id is not None and card is None:
        raise SourceValidationError("card_id: Card not found")
    if card is not None and account_id is not None and card.account_id != account_id:
        raise SourceValidationError("card_id: Choose a card belonging to the selected account")


async def _card_business_timezone(
    db: AsyncSession, card_id: int | None
) -> str:
    if card_id is None:
        return DEFAULT_TIMEZONE
    card = await db.scalar(
        select(Card).where(Card.id == card_id).options(selectinload(Card.account))
    )
    if card is None:
        raise SourceValidationError("card_id: Card not found")
    return effective_card_timezone(card)


async def _resolve_upload_timezone(
    db: AsyncSession,
    *,
    requested: str | None,
    account_id: int | None,
    card_id: int | None,
) -> str:
    if requested is not None:
        try:
            return normalize_timezone_name(requested)
        except ValueError as exc:
            raise SourceValidationError(f"source_timezone: {exc}") from exc
    if card_id is not None:
        return await _card_business_timezone(db, card_id)
    if account_id is not None:
        account = await db.get(Account, account_id)
        if account is None:
            raise SourceValidationError("account_id: Account not found")
        return normalize_timezone_name(account.timezone)
    return DEFAULT_TIMEZONE


def _payload_timezone(payload: SourcePayload, fallback: str) -> str:
    value = payload.ingestion_metadata.get("source_timezone")
    return normalize_timezone_name(str(value)) if value is not None else fallback


def _comparison_timezone(
    incoming: TransactionObservation,
    existing: TransactionObservation,
    fallback: str,
) -> str:
    for value in (incoming, existing):
        if value.payload.source_kind == SourceKind.BANK_STATEMENT.value:
            return _payload_timezone(value.payload, fallback)
    return _payload_timezone(incoming.payload, fallback)


def _card_last_four(card: Card) -> str | None:
    digits = re.sub(r"\D", "", card.card_masked_number or "")
    return digits[-4:] if len(digits) >= 4 else None


async def _resolve_statement_context(
    db: AsyncSession,
    payload: SourcePayload,
    result: SourceParseResult,
) -> tuple[int | None, int | None]:
    statement = result.bank_statement
    if statement is None:
        return None, None

    details = payload.bank_statement_details
    if details is None:
        details = BankStatementDetail()
        payload.bank_statement_details = details
    details.bank = statement.bank
    details.statement_period_start = statement.statement_period_start
    details.statement_period_end = statement.statement_period_end
    details.statement_currency = statement.statement_currency
    details.card_type = statement.card_type
    details.card_last_four = statement.card_last_four

    if result.status != ParseStatus.PROCESSED:
        return details.account_id, details.card_id
    if statement.card_last_four is None or statement.statement_currency is None:
        raise SourceValidationError("The statement card or currency could not be resolved")

    requested_account_id = payload.ingestion_metadata.get("account_id")
    requested_card_id = payload.ingestion_metadata.get("card_id")
    card: Card | None
    if requested_card_id is not None:
        card = await db.scalar(
            select(Card)
            .where(Card.id == requested_card_id)
            .options(selectinload(Card.account))
        )
        if card is None:
            raise SourceValidationError("card_id: Card not found")
        if requested_account_id is not None and card.account_id != requested_account_id:
            raise SourceValidationError(
                "card_id: Choose a card belonging to the selected account"
            )
        if _card_last_four(card) != statement.card_last_four:
            raise SourceValidationError(
                "The uploaded statement belongs to a different card"
            )
    else:
        matches = await find_cards_by_last_four(
            db,
            statement.card_last_four,
            requested_account_id,
        )
        if not matches:
            raise SourceValidationError(
                "No card matches the statement's last four digits"
            )
        if len(matches) > 1:
            raise SourceValidationError(
                "Multiple cards match the statement's last four digits; provide card_id"
            )
        card = await db.scalar(
            select(Card)
            .where(Card.id == matches[0].id)
            .options(selectinload(Card.account))
        )
        if card is None:
            raise SourceValidationError("card_id: Card not found")

    if card.account.account_currency.upper() != statement.statement_currency.upper():
        raise SourceValidationError(
            "The statement currency does not match the card account currency"
        )
    details.account_id = card.account_id
    details.card_id = card.id
    return card.account_id, card.id


def _same_creation_request(
    payload: SourcePayload,
    *,
    content_hash: str,
    source_kind: str,
    media_type: str,
    original_filename: str | None,
    ingestion_metadata: dict[str, Any],
) -> bool:
    return (
        payload.content_hash == content_hash
        and payload.source_kind == source_kind
        and payload.media_type == media_type
        and payload.original_filename == original_filename
        and payload.ingestion_metadata == ingestion_metadata
    )


async def _idempotent_payload(
    db: AsyncSession,
    *,
    ingestion_method: str,
    idempotency_key: str | None,
    content_hash: str,
    source_kind: str,
    media_type: str,
    original_filename: str | None,
    ingestion_metadata: dict[str, Any],
) -> SourcePayload | None:
    if idempotency_key is None:
        return None
    existing = await db.scalar(
        select(SourcePayload).where(
            SourcePayload.ingestion_method == ingestion_method,
            SourcePayload.idempotency_key == idempotency_key,
        )
    )
    if existing is None:
        return None
    if not _same_creation_request(
        existing,
        content_hash=content_hash,
        source_kind=source_kind,
        media_type=media_type,
        original_filename=original_filename,
        ingestion_metadata=ingestion_metadata,
    ):
        raise SourceConflictError("Idempotency-Key was already used for a different payload")
    return await get_source_payload(db, existing.id)


async def _possible_duplicate_payload_ids(
    db: AsyncSession, payload: SourcePayload
) -> list[int]:
    if (
        payload.source_kind != SourceKind.SMS.value
        or payload.media_type != "text/plain"
    ):
        return []
    rows = await db.execute(
        select(SourcePayload.id, SourcePayload.idempotency_key)
        .where(
            SourcePayload.id != payload.id,
            SourcePayload.ingestion_method == payload.ingestion_method,
            SourcePayload.source_kind == payload.source_kind,
            SourcePayload.media_type == payload.media_type,
            SourcePayload.content_hash == payload.content_hash,
        )
        .order_by(SourcePayload.id)
    )
    peers = list(rows.all())
    if not peers:
        return []
    if payload.idempotency_key is None:
        return [payload_id for payload_id, _key in peers]
    if any(
        peer_key is not None and peer_key != payload.idempotency_key
        for _payload_id, peer_key in peers
    ):
        return []
    return [payload_id for payload_id, _key in peers]


async def get_source_payload(db: AsyncSession, payload_id: int) -> SourcePayload | None:
    result = await db.execute(
        select(SourcePayload)
        .where(SourcePayload.id == payload_id)
        .options(
            selectinload(SourcePayload.observations),
            selectinload(SourcePayload.bank_statement_details),
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def list_source_payloads(
    db: AsyncSession,
    *,
    source_kind: str | None = None,
    media_type: str | None = None,
    ingestion_method: str | None = None,
    processing_status: str | None = None,
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    has_observations: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[SourcePayload], int]:
    filters = []
    if source_kind is not None:
        filters.append(SourcePayload.source_kind == source_kind)
    if media_type is not None:
        filters.append(SourcePayload.media_type == media_type.lower())
    if ingestion_method is not None:
        filters.append(SourcePayload.ingestion_method == ingestion_method)
    if processing_status is not None:
        filters.append(SourcePayload.processing_status == processing_status)
    if received_from is not None:
        filters.append(SourcePayload.received_at >= received_from)
    if received_to is not None:
        filters.append(SourcePayload.received_at <= received_to)
    observation_exists = exists().where(
        TransactionObservation.source_payload_id == SourcePayload.id
    )
    if has_observations is True:
        filters.append(observation_exists)
    elif has_observations is False:
        filters.append(~observation_exists)

    total = await db.scalar(select(func.count(SourcePayload.id)).where(*filters))
    result = await db.execute(
        select(SourcePayload)
        .where(*filters)
        .order_by(SourcePayload.received_at.desc(), SourcePayload.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total or 0


async def get_transaction_observation(
    db: AsyncSession, observation_id: int
) -> TransactionObservation | None:
    result = await db.execute(
        select(TransactionObservation)
        .where(TransactionObservation.id == observation_id)
        .options(
            selectinload(TransactionObservation.payload),
            selectinload(TransactionObservation.transaction_link),
        )
    )
    return result.scalar_one_or_none()


async def list_transaction_observations(
    db: AsyncSession,
    *,
    source_payload_id: int | None = None,
    account_id: int | None = None,
    card_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    has_transaction: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[TransactionObservation], int]:
    filters = []
    if source_payload_id is not None:
        filters.append(TransactionObservation.source_payload_id == source_payload_id)
    if account_id is not None:
        filters.append(TransactionObservation.account_id == account_id)
    if card_id is not None:
        filters.append(TransactionObservation.card_id == card_id)
    observed_date = func.coalesce(
        TransactionObservation.posting_datetime,
        TransactionObservation.transaction_datetime,
    )
    if date_from is not None:
        filters.append(observed_date >= date_from)
    if date_to is not None:
        filters.append(observed_date <= date_to)
    link_exists = exists().where(
        TransactionSourceLink.observation_id == TransactionObservation.id
    )
    if has_transaction is True:
        filters.append(link_exists)
    elif has_transaction is False:
        filters.append(~link_exists)

    total = await db.scalar(select(func.count(TransactionObservation.id)).where(*filters))
    result = await db.execute(
        select(TransactionObservation)
        .where(*filters)
        .options(
            selectinload(TransactionObservation.payload),
            selectinload(TransactionObservation.transaction_link),
        )
        .order_by(observed_date.desc().nullslast(), TransactionObservation.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total or 0


async def _resolve_observation_card(
    db: AsyncSession, observation: TransactionObservation
) -> None:
    if observation.card_id is not None:
        return
    if observation.card_last_four:
        card = await find_card_by_last_four(
            db, observation.card_last_four, observation.account_id
        )
        if card is not None:
            observation.card_id = card.id
            observation.account_id = card.account_id


async def _resolved_money(
    db: AsyncSession,
    card_id: int,
    amount: Decimal,
    currency: str,
) -> tuple[Decimal, str, Decimal | None, str | None, Decimal | None]:
    card = await db.scalar(
        select(Card).where(Card.id == card_id).options(selectinload(Card.account))
    )
    if card is None:
        raise SourceValidationError("card_id: Card not found")
    account_currency = card.account.account_currency
    if currency.upper() == account_currency.upper():
        return amount, currency.upper(), None, None, None
    rate = await exchange_rate_service.get_rate(currency, account_currency)
    return (
        (amount * rate).quantize(Decimal("0.01")),
        account_currency,
        amount,
        currency.upper(),
        rate,
    )


def _observation_business_date(
    observation: TransactionObservation,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> date | None:
    value = observation.transaction_datetime or observation.posting_datetime
    return business_date(value, timezone_name) if value is not None else None


async def _date_consistency_conflicts(
    db: AsyncSession,
    observation: TransactionObservation,
    transaction_ids: set[int],
) -> dict[int, list[int]]:
    if not transaction_ids:
        return {}
    fallback_timezone = await _card_business_timezone(db, observation.card_id)
    rows = await db.execute(
        select(TransactionSourceLink.transaction_id, TransactionObservation)
        .join(
            TransactionSourceLink,
            TransactionSourceLink.observation_id == TransactionObservation.id,
        )
        .where(TransactionSourceLink.transaction_id.in_(transaction_ids))
        .options(selectinload(TransactionObservation.payload))
    )
    conflicts: dict[int, list[int]] = {}
    for transaction_id, existing in rows:
        if existing.id == observation.id:
            continue
        timezone_name = _comparison_timezone(
            observation, existing, fallback_timezone
        )
        incoming_date = _observation_business_date(observation, timezone_name)
        existing_date = _observation_business_date(existing, timezone_name)
        if (
            incoming_date is not None
            and existing_date is not None
            and existing_date != incoming_date
        ):
            conflicts.setdefault(transaction_id, []).append(existing.id)
    return conflicts


async def _require_date_consistency(
    db: AsyncSession,
    observation: TransactionObservation,
    transaction_id: int,
) -> None:
    conflicts = await _date_consistency_conflicts(db, observation, {transaction_id})
    if transaction_id in conflicts:
        conflicting_ids = ", ".join(str(value) for value in conflicts[transaction_id])
        raise SourceValidationError(
            "Observation transaction date conflicts with linked observations "
            f"{conflicting_ids} in transaction {transaction_id}"
        )


async def _transactions_with_sms_from_other_payload(
    db: AsyncSession,
    observation: TransactionObservation,
    transaction_ids: set[int],
) -> set[int]:
    if not transaction_ids:
        return set()
    result = await db.scalars(
        select(TransactionSourceLink.transaction_id)
        .join(
            TransactionObservation,
            TransactionObservation.id == TransactionSourceLink.observation_id,
        )
        .join(SourcePayload, SourcePayload.id == TransactionObservation.source_payload_id)
        .where(
            TransactionSourceLink.transaction_id.in_(transaction_ids),
            SourcePayload.source_kind == SourceKind.SMS.value,
            TransactionObservation.source_payload_id != observation.source_payload_id,
        )
        .distinct()
    )
    return set(result.all())


async def _link_automatically(
    db: AsyncSession,
    observation: TransactionObservation,
    claimed_transaction_ids: set[int] | None = None,
) -> int | None:
    if observation.amount is None or observation.currency is None or observation.card_id is None:
        return None
    amount, currency, original_amount, original_currency, fx_rate = await _resolved_money(
        db, observation.card_id, observation.amount, observation.currency
    )
    if observation.original_amount is not None and observation.original_currency is not None:
        original_amount = observation.original_amount
        original_currency = observation.original_currency
        fx_rate = None
        if original_amount != 0 and currency.upper() != original_currency.upper():
            fx_rate = (amount / original_amount).copy_abs().quantize(
                Decimal("0.000001"),
                rounding=ROUND_HALF_UP,
            )

    is_statement = observation.payload.source_kind == SourceKind.BANK_STATEMENT.value
    card_timezone = await _card_business_timezone(db, observation.card_id)
    business_timezone = _payload_timezone(observation.payload, card_timezone)
    merchant_norm = normalize_merchant(observation.description or "")
    matches = await find_matching_transactions(
        db=db,
        card_id=observation.card_id,
        amount=amount,
        currency=currency,
        posting_datetime=observation.posting_datetime,
        transaction_datetime=observation.transaction_datetime,
        created_at=observation.payload.received_at,
        merchant_norm=None if is_statement else merchant_norm,
        orig_amount=original_amount,
        orig_currency=original_currency,
        match_both_source_dates=is_statement,
        exclude_transaction_ids=claimed_transaction_ids if is_statement else None,
        business_timezone=business_timezone,
    )
    date_conflicts = await _date_consistency_conflicts(
        db, observation, {transaction.id for transaction in matches}
    )
    if date_conflicts:
        observation.extraction_metadata["date_conflict_candidate_count"] = len(
            date_conflicts
        )
        matches = [
            transaction
            for transaction in matches
            if transaction.id not in date_conflicts
        ]
    if observation.payload.source_kind == SourceKind.SMS.value:
        same_source_candidates = await _transactions_with_sms_from_other_payload(
            db, observation, {transaction.id for transaction in matches}
        )
        if same_source_candidates:
            observation.extraction_metadata["same_source_candidate_count"] = len(
                same_source_candidates
            )
            matches = [
                transaction
                for transaction in matches
                if transaction.id not in same_source_candidates
            ]

    confidence = Decimal("1.0000")
    if is_statement:
        if observation.transaction_datetime is None:
            raise RuntimeError("A statement observation must have a transaction date")
        transaction, confidence = select_statement_match(
            matches,
            amount=amount,
            currency=currency,
            transaction_datetime=observation.transaction_datetime,
            posting_datetime=observation.posting_datetime,
            description=observation.description or "",
            original_amount=original_amount,
            original_currency=original_currency,
            business_timezone=business_timezone,
        )
        if matches and transaction is None:
            observation.extraction_metadata["matching_status"] = "ambiguous"
            observation.extraction_metadata["candidate_count"] = len(matches)
            return None
    elif len(matches) > 1:
        observation.extraction_metadata["matching_status"] = "ambiguous"
        observation.extraction_metadata["candidate_count"] = len(matches)
        return None
    else:
        transaction = matches[0] if matches else None

    if transaction is None:
        confidence = Decimal("1.0000")
        transaction = Transaction(
            card_id=observation.card_id,
            amount=amount,
            currency=currency,
            original_amount=original_amount,
            original_currency=original_currency,
            fx_rate=fx_rate,
            fx_fee=None,
            transaction_datetime=observation.transaction_datetime,
            posting_datetime=observation.posting_datetime,
            description=observation.description or observation.raw_fragment or "No description",
            location=observation.location,
            transaction_kind=observation.transaction_kind or "other",
            merchant_norm=merchant_norm,
            fingerprint=generate_fingerprint(
                card_id=observation.card_id,
                amount=amount,
                currency=currency,
                posting_datetime=observation.posting_datetime,
                transaction_datetime=observation.transaction_datetime,
                merchant_norm=merchant_norm,
                orig_amount=original_amount,
                orig_currency=original_currency,
                business_timezone=business_timezone,
            ),
        )
        db.add(transaction)
        await db.flush()

    db.add(
        TransactionSourceLink(
            observation_id=observation.id,
            transaction_id=transaction.id,
            match_confidence=confidence,
            match_method=MatchMethod.AUTOMATIC.value,
            matcher_name=STATEMENT_MATCHER_NAME if is_statement else MATCHER_NAME,
            matcher_version=(
                STATEMENT_MATCHER_VERSION if is_statement else MATCHER_VERSION
            ),
        )
    )
    await db.flush()
    await canonicalize_transaction(db, transaction)
    return transaction.id


async def _recalculate_transactions(db: AsyncSession, transaction_ids: set[int]) -> None:
    for transaction_id in sorted(transaction_ids):
        transaction = await db.get(Transaction, transaction_id)
        if transaction is not None:
            await canonicalize_transaction(db, transaction)


def _observation_from_input(
    payload_id: int,
    value: ObservationInput,
    *,
    default_account_id: int | None = None,
    default_card_id: int | None = None,
) -> TransactionObservation:
    fields = asdict(value)
    fields["account_id"] = fields["account_id"] or default_account_id
    fields["card_id"] = fields["card_id"] or default_card_id
    return TransactionObservation(source_payload_id=payload_id, **fields)


async def _run_payload_parser(
    payload: SourcePayload,
    *,
    file_content: bytes | None,
    password: str | None,
):
    if file_content is None and payload.file_path is not None:
        try:
            file_content = await run_in_threadpool(Path(payload.file_path).read_bytes)
        except OSError as exc:
            raise SourceValidationError("The stored source file could not be read") from exc

    try:
        if file_content is not None:
            return await run_in_threadpool(
                run_registered_parser,
                payload,
                file_content=file_content,
                password=password,
            )
        return run_registered_parser(payload, password=password)
    except (InvalidSourceInputError, UnsupportedSourceError) as exc:
        raise SourceValidationError(str(exc)) from exc


async def _process_payload(
    db: AsyncSession,
    payload: SourcePayload,
    *,
    replace_existing: bool,
    file_content: bytes | None = None,
    password: str | None = None,
) -> None:
    if not get_parsers(payload.source_kind, payload.media_type):
        if replace_existing:
            raise SourceConflictError("No parser is registered for this source kind and media type")
        payload.processing_status = ProcessingStatus.PENDING.value
        return

    parser, result = await _run_payload_parser(
        payload,
        file_content=file_content,
        password=password,
    )
    keys = [value.source_item_key for value in result.observations]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Parser returned duplicate source_item_key values")

    default_account_id, default_card_id = await _resolve_statement_context(
        db, payload, result
    )

    affected_transactions: set[int] = set()
    if replace_existing:
        affected_transactions.update(
            await db.scalars(
                select(TransactionSourceLink.transaction_id)
                .join(
                    TransactionObservation,
                    TransactionObservation.id == TransactionSourceLink.observation_id,
                )
                .where(TransactionObservation.source_payload_id == payload.id)
            )
        )
        observation_ids = select(TransactionObservation.id).where(
            TransactionObservation.source_payload_id == payload.id
        )
        await db.execute(
            delete(TransactionSourceLink).where(
                TransactionSourceLink.observation_id.in_(observation_ids)
            )
        )
        await db.execute(
            delete(TransactionObservation).where(
                TransactionObservation.source_payload_id == payload.id
            )
        )
        await db.flush()

    payload.processing_status = ProcessingStatus.PROCESSING.value
    payload.parser_name = parser.name
    payload.parser_version = parser.version
    payload.processing_error = result.error

    observations = [
        _observation_from_input(
            payload.id,
            value,
            default_account_id=default_account_id,
            default_card_id=default_card_id,
        )
        for value in result.observations
    ]
    db.add_all(observations)
    await db.flush()
    possible_duplicate_ids = await _possible_duplicate_payload_ids(db, payload)
    claimed_transaction_ids: set[int] = set()
    for observation in observations:
        observation.payload = payload
        await _resolve_observation_card(db, observation)
        if possible_duplicate_ids:
            observation.extraction_metadata["matching_status"] = "possible_duplicate"
            observation.extraction_metadata["duplicate_payload_id"] = possible_duplicate_ids[0]
            observation.extraction_metadata["duplicate_payload_count"] = len(
                possible_duplicate_ids
            )
            continue
        try:
            transaction_id = await _link_automatically(
                db,
                observation,
                claimed_transaction_ids,
            )
            if transaction_id is not None:
                affected_transactions.add(transaction_id)
                if payload.source_kind == SourceKind.BANK_STATEMENT.value:
                    claimed_transaction_ids.add(transaction_id)
        except HTTPException as exc:
            payload.processing_status = ProcessingStatus.FAILED.value
            payload.processing_error = f"Matching failed: {exc.detail}"
            observation.extraction_metadata["matching_error"] = "exchange_rate_unavailable"

    if payload.processing_status != ProcessingStatus.FAILED.value:
        payload.processing_status = result.status.value
    await _recalculate_transactions(db, affected_transactions)


async def create_text_payload(
    db: AsyncSession,
    source_data: SourcePayloadCreateText,
    idempotency_key: str | None,
) -> tuple[SourcePayload, bool]:
    await _validate_context(db, source_data.account_id, source_data.card_id)
    metadata = _compact_metadata(
        transaction_datetime=source_data.transaction_datetime,
        account_id=source_data.account_id,
        card_id=source_data.card_id,
        sender=source_data.sender,
        recipients=source_data.recipients,
    )
    content_hash = hashlib.sha256(source_data.text.encode("utf-8")).hexdigest()
    source_kind = source_data.source_kind.value
    existing = await _idempotent_payload(
        db,
        ingestion_method=IngestionMethod.PHONE_API.value,
        idempotency_key=idempotency_key,
        content_hash=content_hash,
        source_kind=source_kind,
        media_type="text/plain",
        original_filename=None,
        ingestion_metadata=metadata,
    )
    if existing is not None:
        return existing, True

    payload = SourcePayload(
        source_kind=source_kind,
        media_type="text/plain",
        ingestion_method=IngestionMethod.PHONE_API.value,
        raw_text=source_data.text,
        content_hash=content_hash,
        idempotency_key=idempotency_key,
        ingestion_metadata=metadata,
    )
    db.add(payload)
    try:
        await db.flush()
        await _process_payload(db, payload, replace_existing=False)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await _idempotent_payload(
            db,
            ingestion_method=IngestionMethod.PHONE_API.value,
            idempotency_key=idempotency_key,
            content_hash=content_hash,
            source_kind=source_kind,
            media_type="text/plain",
            original_filename=None,
            ingestion_metadata=metadata,
        )
        if existing is not None:
            return existing, True
        raise SourceConflictError("The source payload conflicts with existing data") from exc
    except Exception:
        await db.rollback()
        raise
    return await get_source_payload(db, payload.id), False


async def _write_upload(
    file: UploadFile,
    upload_dir: Path,
    max_size: int,
) -> tuple[Path, str, int]:
    await run_in_threadpool(upload_dir.mkdir, parents=True, exist_ok=True)
    descriptor, temporary_name = await run_in_threadpool(
        tempfile.mkstemp, ".part", ".upload-", upload_dir
    )
    temporary_path = Path(temporary_name)
    digest = hashlib.sha256()
    size = 0
    handle = os.fdopen(descriptor, "wb")
    try:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            size += len(chunk)
            if size > max_size:
                raise SourceUploadTooLargeError(
                    f"file: The uploaded file exceeds the {max_size}-byte limit"
                )
            digest.update(chunk)
            await run_in_threadpool(handle.write, chunk)
    except Exception:
        await run_in_threadpool(handle.close)
        await run_in_threadpool(temporary_path.unlink, missing_ok=True)
        raise
    await run_in_threadpool(handle.close)
    return temporary_path, digest.hexdigest(), size


async def create_upload_payload(
    db: AsyncSession,
    *,
    file: UploadFile,
    source_kind: SourceKind,
    account_id: int | None,
    card_id: int | None,
    source_timezone: str | None,
    idempotency_key: str | None,
    password: str | None = None,
) -> tuple[SourcePayload, bool]:
    await _validate_context(db, account_id, card_id)
    source_timezone = await _resolve_upload_timezone(
        db,
        requested=source_timezone,
        account_id=account_id,
        card_id=card_id,
    )
    original_filename = Path((file.filename or "unnamed").replace("\\", "/")).name[:255]
    media_type = (file.content_type or "application/octet-stream").split(";", 1)[0].lower()[:255]
    metadata = _compact_metadata(
        account_id=account_id,
        card_id=card_id,
        source_timezone=source_timezone,
    )
    upload_dir = Path(settings.UPLOAD_DIR).resolve()
    temporary_path, content_hash, size = await _write_upload(
        file,
        upload_dir,
        settings.MAX_UPLOAD_SIZE_BYTES,
    )
    if size == 0:
        await run_in_threadpool(temporary_path.unlink, missing_ok=True)
        raise SourceValidationError("file: The uploaded file is empty")

    file_content: bytes | None = None
    if source_kind is SourceKind.BANK_STATEMENT:
        try:
            file_content = await run_in_threadpool(temporary_path.read_bytes)
        except OSError as exc:
            await run_in_threadpool(temporary_path.unlink, missing_ok=True)
            raise SourceValidationError("file: The uploaded file could not be read") from exc
        if not file_content.startswith(b"%PDF-"):
            await run_in_threadpool(temporary_path.unlink, missing_ok=True)
            raise SourceValidationError("file: The uploaded bank statement is not a PDF")
        media_type = "application/pdf"

    try:
        existing = await _idempotent_payload(
            db,
            ingestion_method=IngestionMethod.MANUAL_UPLOAD.value,
            idempotency_key=idempotency_key,
            content_hash=content_hash,
            source_kind=source_kind.value,
            media_type=media_type,
            original_filename=original_filename,
            ingestion_metadata=metadata,
        )
    except Exception:
        await run_in_threadpool(temporary_path.unlink, missing_ok=True)
        raise
    if existing is not None:
        await run_in_threadpool(temporary_path.unlink, missing_ok=True)
        return existing, True

    stored_path = upload_dir / f"{uuid4().hex}.payload"
    try:
        await run_in_threadpool(os.replace, temporary_path, stored_path)
    except Exception:
        await run_in_threadpool(temporary_path.unlink, missing_ok=True)
        raise
    try:
        payload = SourcePayload(
            source_kind=source_kind.value,
            media_type=media_type,
            ingestion_method=IngestionMethod.MANUAL_UPLOAD.value,
            file_path=str(stored_path),
            original_filename=original_filename,
            content_hash=content_hash,
            idempotency_key=idempotency_key,
            ingestion_metadata=metadata,
            processing_status=ProcessingStatus.PENDING.value,
        )
        db.add(payload)
        if source_kind is SourceKind.BANK_STATEMENT:
            payload.bank_statement_details = BankStatementDetail(
                account_id=account_id, card_id=card_id
            )
        await db.flush()
        await _process_payload(
            db,
            payload,
            replace_existing=False,
            file_content=file_content,
            password=password,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        await run_in_threadpool(stored_path.unlink, missing_ok=True)
        existing = await _idempotent_payload(
            db,
            ingestion_method=IngestionMethod.MANUAL_UPLOAD.value,
            idempotency_key=idempotency_key,
            content_hash=content_hash,
            source_kind=source_kind.value,
            media_type=media_type,
            original_filename=original_filename,
            ingestion_metadata=metadata,
        )
        if existing is not None:
            return existing, True
        raise SourceConflictError("The source payload conflicts with existing data") from exc
    except Exception:
        await db.rollback()
        await run_in_threadpool(stored_path.unlink, missing_ok=True)
        raise
    return await get_source_payload(db, payload.id), False


async def reprocess_source_payload(
    db: AsyncSession,
    payload_id: int,
    password: str | None = None,
    force_manual_links: bool = False,
) -> SourcePayload:
    payload = await get_source_payload(db, payload_id)
    if payload is None:
        raise SourceNotFoundError("Source payload not found")
    manual_link_count = await db.scalar(
        select(func.count())
        .select_from(TransactionSourceLink)
        .join(
            TransactionObservation,
            TransactionObservation.id == TransactionSourceLink.observation_id,
        )
        .where(
            TransactionObservation.source_payload_id == payload_id,
            TransactionSourceLink.match_method == MatchMethod.MANUAL.value,
        )
    )
    if manual_link_count and not force_manual_links:
        raise SourceConflictError(
            "Source payload has manually linked observations; set "
            "force_manual_links=true to replace them"
        )
    try:
        await _process_payload(
            db,
            payload,
            replace_existing=True,
            password=password,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_source_payload(db, payload_id)


async def link_observation_to_transaction(
    db: AsyncSession, observation_id: int, transaction_id: int
) -> TransactionSourceLink:
    observation = await get_transaction_observation(db, observation_id)
    if observation is None:
        raise SourceNotFoundError("Transaction observation not found")
    if observation.transaction_link is not None:
        raise SourceConflictError("Transaction observation is already linked")
    transaction = await db.get(Transaction, transaction_id)
    if transaction is None:
        raise SourceNotFoundError("Transaction not found")
    await _require_date_consistency(db, observation, transaction_id)
    link = TransactionSourceLink(
        observation_id=observation_id,
        transaction_id=transaction_id,
        match_method=MatchMethod.MANUAL.value,
    )
    db.add(link)
    try:
        await db.flush()
        await canonicalize_transaction(db, transaction)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise SourceConflictError("Transaction observation is already linked") from exc
    except Exception:
        await db.rollback()
        raise
    return await get_transaction_link(db, observation_id)


async def move_observation_to_transaction(
    db: AsyncSession,
    observation_id: int,
    transaction_id: int,
    *,
    expected_transaction_id: int | None = None,
) -> TransactionSourceLink:
    observation = await get_transaction_observation(db, observation_id)
    if observation is None:
        raise SourceNotFoundError("Transaction observation not found")
    link = observation.transaction_link
    if link is None:
        raise SourceConflictError("Transaction observation is not linked")
    if expected_transaction_id is not None and link.transaction_id != expected_transaction_id:
        raise SourceConflictError("Transaction observation is no longer linked to this transaction")
    if link.transaction_id == transaction_id:
        raise SourceConflictError("Transaction observation is already linked to this transaction")
    target = await db.get(Transaction, transaction_id)
    if target is None:
        raise SourceNotFoundError("Transaction not found")
    await _require_date_consistency(db, observation, transaction_id)

    old_transaction = await db.get(Transaction, link.transaction_id)
    link.transaction_id = transaction_id
    link.match_method = MatchMethod.MANUAL.value
    link.match_confidence = None
    link.matched_at = datetime.now(UTC)
    link.matcher_name = None
    link.matcher_version = None
    try:
        await db.flush()
        if old_transaction is not None:
            await canonicalize_transaction(db, old_transaction)
        await canonicalize_transaction(db, target)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise SourceConflictError("Transaction observation could not be moved") from exc
    except Exception:
        await db.rollback()
        raise
    return await get_transaction_link(db, observation_id)


async def create_transaction_from_observation(
    db: AsyncSession,
    observation_id: int,
    data: TransactionCreateFromObservation,
) -> Transaction:
    observation = await get_transaction_observation(db, observation_id)
    if observation is None:
        raise SourceNotFoundError("Transaction observation not found")
    if observation.transaction_link is not None:
        raise SourceConflictError("Transaction observation is already linked")

    card_id = observation.card_id or data.card_id
    amount = observation.amount if observation.amount is not None else data.amount
    currency = observation.currency or data.currency
    if card_id is None:
        raise SourceValidationError("card_id is required")
    if amount is None:
        raise SourceValidationError("amount is required")
    if currency is None:
        raise SourceValidationError("currency is required")
    await _validate_context(db, None, card_id)
    canonical_amount, canonical_currency, original_amount, original_currency, fx_rate = (
        await _resolved_money(db, card_id, amount, currency)
    )
    if observation.original_amount is not None and observation.original_currency is not None:
        original_amount = observation.original_amount
        original_currency = observation.original_currency
        fx_rate = (
            (canonical_amount / original_amount).copy_abs() if original_amount != 0 else None
        )
    elif data.original_amount is not None and data.original_currency is not None:
        original_amount = data.original_amount
        original_currency = data.original_currency
        fx_rate = data.fx_rate

    description = observation.description or data.description or observation.raw_fragment or "No description"
    card_timezone = await _card_business_timezone(db, card_id)
    business_timezone = _payload_timezone(observation.payload, card_timezone)
    transaction = Transaction(
        card_id=card_id,
        amount=canonical_amount,
        currency=canonical_currency,
        transaction_datetime=observation.transaction_datetime or data.transaction_datetime,
        posting_datetime=observation.posting_datetime or data.posting_datetime,
        description=description,
        location=observation.location or data.location,
        transaction_kind=observation.transaction_kind or data.transaction_kind or "other",
        original_amount=original_amount,
        original_currency=original_currency,
        fx_rate=fx_rate,
        fx_fee=data.fx_fee,
        merchant_norm=normalize_merchant(description),
    )
    transaction.fingerprint = generate_fingerprint(
        card_id=transaction.card_id,
        amount=transaction.amount,
        currency=transaction.currency,
        posting_datetime=transaction.posting_datetime,
        transaction_datetime=transaction.transaction_datetime,
        merchant_norm=transaction.merchant_norm,
        orig_amount=transaction.original_amount,
        orig_currency=transaction.original_currency,
        business_timezone=business_timezone,
    )
    db.add(transaction)
    try:
        await db.flush()
        db.add(
            TransactionSourceLink(
                observation_id=observation_id,
                transaction_id=transaction.id,
                match_method=MatchMethod.MANUAL.value,
            )
        )
        await db.flush()
        await canonicalize_transaction(db, transaction)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise SourceConflictError("Transaction observation is already linked") from exc
    except Exception:
        await db.rollback()
        raise
    return transaction


async def unlink_observation(
    db: AsyncSession,
    observation_id: int,
    transaction_id: int | None = None,
) -> bool:
    """Unlink an observation, optionally only from the expected transaction."""
    link = await db.get(TransactionSourceLink, observation_id)
    if link is None or (
        transaction_id is not None and link.transaction_id != transaction_id
    ):
        return False
    try:
        transaction = await db.get(Transaction, link.transaction_id)
        await db.delete(link)
        await db.flush()
        if transaction is not None:
            await canonicalize_transaction(db, transaction)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return True


async def get_transaction_link(
    db: AsyncSession, observation_id: int
) -> TransactionSourceLink | None:
    result = await db.execute(
        select(TransactionSourceLink)
        .where(TransactionSourceLink.observation_id == observation_id)
        .options(
            selectinload(TransactionSourceLink.observation).selectinload(
                TransactionObservation.payload
            )
        )
    )
    return result.scalar_one_or_none()
