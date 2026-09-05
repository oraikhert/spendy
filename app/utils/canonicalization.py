"""Deterministic canonical transaction values from linked observations."""
from datetime import UTC
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.card import Card
from app.models.transaction import Transaction
from app.models.transaction_source_link import TransactionSourceLink
from app.models.transaction_observation import TransactionObservation
from app.utils.business_time import (
    DEFAULT_TIMEZONE,
    effective_card_timezone,
    normalize_timezone_name,
)
from app.utils.matching import generate_fingerprint, normalize_merchant


FINANCIAL_PRIORITY = {"bank_statement": 0, "bank_app": 1, "sms": 2, "other": 3}
IMMEDIATE_PRIORITY = {"sms": 0, "bank_app": 1, "bank_statement": 2, "other": 3}


def _received_timestamp(observation: TransactionObservation) -> float:
    value = observation.payload.received_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _priority_key(observation: TransactionObservation, priority):
    confidence = (
        observation.extraction_confidence
        if observation.extraction_confidence is not None
        else Decimal("-1")
    )
    return (
        priority.get(observation.payload.source_kind, len(priority)),
        -confidence,
        -_received_timestamp(observation),
        -observation.id,
    )


def _winner(observations, field, priority):
    candidates = [value for value in observations if getattr(value, field) is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda value: _priority_key(value, priority))


def _money_winner(observations):
    candidates = [
        value
        for value in observations
        if value.amount is not None and value.currency is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda value: _priority_key(value, FINANCIAL_PRIORITY))


def transaction_business_timezone(
    card: Card | None,
    observations: list[TransactionObservation],
) -> str:
    fallback = effective_card_timezone(card) if card is not None else DEFAULT_TIMEZONE
    date_source = _winner(observations, "posting_datetime", FINANCIAL_PRIORITY)
    if date_source is None:
        date_source = _winner(observations, "transaction_datetime", IMMEDIATE_PRIORITY)
    if date_source is None:
        return fallback
    value = date_source.payload.ingestion_metadata.get("source_timezone")
    return normalize_timezone_name(str(value)) if value is not None else fallback


async def _canonical_business_timezone(
    db: AsyncSession,
    transaction: Transaction,
    observations: list[TransactionObservation],
) -> str:
    card = await db.scalar(
        select(Card)
        .where(Card.id == transaction.card_id)
        .options(selectinload(Card.account))
    )
    return transaction_business_timezone(card, observations)


async def _canonical_money(db: AsyncSession, transaction: Transaction, observation):
    # Import lazily so standalone parser imports do not recurse through the eager
    # app.services package exports back into source processing.
    from app.services.exchange_rate_service import exchange_rate_service

    amount = observation.amount
    currency = observation.currency
    if amount is None or currency is None:
        return None
    if observation.original_amount is not None and observation.original_currency is not None:
        fx_rate = None
        if observation.original_amount != 0 and currency != observation.original_currency:
            fx_rate = (amount / observation.original_amount).copy_abs()
        return amount, currency, observation.original_amount, observation.original_currency, fx_rate

    card = await db.scalar(
        select(Card).where(Card.id == transaction.card_id).options(selectinload(Card.account))
    )
    if card is None or not card.account or currency.upper() == card.account.account_currency.upper():
        return amount, currency, None, None, None
    rate = await exchange_rate_service.get_rate(currency, card.account.account_currency)
    canonical_amount = (amount * rate).quantize(Decimal("0.01"))
    return canonical_amount, card.account.account_currency, amount, currency, rate


async def canonicalize_transaction(
    db: AsyncSession,
    transaction: Transaction
) -> Transaction:
    """Recalculate every source-backed canonical field without committing."""
    query = (
        select(TransactionSourceLink)
        .where(TransactionSourceLink.transaction_id == transaction.id)
        .options(
            selectinload(TransactionSourceLink.observation).selectinload(
                TransactionObservation.payload
            )
        )
    )
    result = await db.execute(query)
    links = result.scalars().all()
    if not links:
        return transaction

    observations = [link.observation for link in links]
    business_timezone = await _canonical_business_timezone(
        db, transaction, observations
    )
    money_source = _money_winner(observations)
    if money_source is not None:
        money = await _canonical_money(db, transaction, money_source)
        if money is not None:
            (
                transaction.amount,
                transaction.currency,
                transaction.original_amount,
                transaction.original_currency,
                transaction.fx_rate,
            ) = money

    for field in ("posting_datetime", "description"):
        source = _winner(observations, field, FINANCIAL_PRIORITY)
        if source is not None:
            setattr(transaction, field, getattr(source, field))
    for field in ("transaction_datetime", "transaction_kind", "location"):
        source = _winner(observations, field, IMMEDIATE_PRIORITY)
        if source is not None:
            setattr(transaction, field, getattr(source, field))

    transaction.merchant_norm = normalize_merchant(transaction.description)
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
    return transaction
