"""Matching and deduplication utilities"""
import re
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.card import Card
from app.models.transaction import Transaction
from app.utils.business_time import (
    DEFAULT_TIMEZONE,
    business_date,
    business_day_utc_bounds,
)


MERCHANT_SIMILARITY_THRESHOLD = Decimal("0.8000")
MERCHANT_PREFIX_SIMILARITY_THRESHOLD = Decimal("0.5000")


async def find_card_by_last_four(
    db: AsyncSession,
    last_four: str,
    account_id: int | None = None
) -> Card | None:
    """
    Find a card by last 4 digits of the masked number.

    Normalizes card_masked_number to digits only, takes last 4, and compares
    to last_four. Optionally restricts to account_id.

    Args:
        db: Database session
        last_four: Exactly 4 digits (e.g. from parsed "Credit Card ending 3278")
        account_id: If set, only consider cards for this account

    Returns:
        First matching Card or None
    """
    if not last_four or len(last_four) != 4 or not last_four.isdigit():
        return None

    cards = await find_cards_by_last_four(db, last_four, account_id)
    return cards[0] if cards else None


async def find_cards_by_last_four(
    db: AsyncSession,
    last_four: str,
    account_id: int | None = None,
) -> list[Card]:
    """Return all cards with the requested normalized suffix."""
    if not last_four or len(last_four) != 4 or not last_four.isdigit():
        return []

    query = select(Card).order_by(Card.id)
    if account_id is not None:
        query = query.where(Card.account_id == account_id)
    result = await db.execute(query)
    matches = []
    for card in result.scalars().all():
        digits_only = re.sub(r"\D", "", card.card_masked_number or "")
        if len(digits_only) >= 4 and digits_only[-4:] == last_four:
            matches.append(card)
    return matches


def normalize_merchant(description: str) -> str:
    """
    Normalize merchant name from description.
    
    Args:
        description: Raw transaction description
        
    Returns:
        Normalized merchant name
    """
    if not description:
        return ""
    
    # Lower case
    normalized = description.lower().strip()
    
    # Remove special characters (keep alphanumeric and spaces)
    normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)
    
    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Remove common noise tokens (minimal set)
    noise_tokens = {'the', 'a', 'an', 'and', 'or', 'at', 'in', 'on'}
    words = normalized.split()
    words = [w for w in words if w not in noise_tokens]
    
    return ' '.join(words)


def generate_fingerprint(
    card_id: int,
    amount: Decimal,
    currency: str,
    posting_datetime: datetime | None,
    transaction_datetime: datetime | None,
    merchant_norm: str | None,
    orig_amount: Decimal | None = None,
    orig_currency: str | None = None,
    business_timezone: str = DEFAULT_TIMEZONE,
) -> str:
    """
    Generate fingerprint for transaction deduplication.
    Uses original_amount and original_currency when both are not null (e.g. after FX);
    otherwise uses amount and currency.
    """
    if posting_datetime:
        date_str = business_date(posting_datetime, business_timezone).isoformat()
    elif transaction_datetime:
        date_str = business_date(transaction_datetime, business_timezone).isoformat()
    else:
        date_str = "unknown"

    merchant_str = merchant_norm or ""

    if orig_amount is not None and orig_currency is not None:
        amt, curr = orig_amount, orig_currency
    else:
        amt, curr = amount, currency

    fingerprint = f"{card_id}|{date_str}|{amt}|{curr}|{merchant_str}"
    return fingerprint


async def find_matching_transactions(
    db: AsyncSession,
    card_id: int,
    amount: Decimal,
    currency: str,
    posting_datetime: datetime | None,
    transaction_datetime: datetime | None,
    created_at: datetime,
    merchant_norm: str | None = None,
    orig_amount: Decimal | None = None,
    orig_currency: str | None = None,
    match_both_source_dates: bool = False,
    exclude_transaction_ids: set[int] | None = None,
    business_timezone: str = DEFAULT_TIMEZONE,
) -> list[Transaction]:
    """
    Find matching transactions based on card_id, amount, currency, and date.
    Date matching is restricted to the same calendar day.
    Matches on (amount, currency) or (orig_amount, orig_currency) when provided.
    
    Args:
        db: Database session
        card_id: Card ID
        amount: Transaction amount (canonical, after FX conversion)
        currency: Transaction currency
        posting_datetime: Posting datetime
        transaction_datetime: Transaction datetime
        merchant_norm: Normalized merchant name (optional)
        orig_amount: Original amount before FX (optional)
        orig_currency: Original currency before FX (optional)
        
    Returns:
        List of matching transactions
    """
    if match_both_source_dates:
        match_dates = {
            business_date(value, business_timezone)
            for value in (posting_datetime, transaction_datetime)
            if value is not None
        }
        has_explicit_date = bool(match_dates)
        if not match_dates:
            match_dates = {business_date(created_at, business_timezone)}
    else:
        if posting_datetime:
            match_dates = {business_date(posting_datetime, business_timezone)}
        elif transaction_datetime:
            match_dates = {business_date(transaction_datetime, business_timezone)}
        else:
            match_dates = {business_date(created_at, business_timezone)}
        has_explicit_date = posting_datetime is not None or transaction_datetime is not None

    amount_currency_match = and_(
        Transaction.amount == amount,
        Transaction.currency == currency,
    )
    if orig_amount is not None and orig_currency is not None:
        orig_match = and_(
            Transaction.original_amount == orig_amount,
            Transaction.original_currency == orig_currency,
        )
        amount_condition = or_(amount_currency_match, orig_match)
    else:
        amount_condition = amount_currency_match

    # Build query
    query = select(Transaction).where(
        and_(
            Transaction.card_id == card_id,
            amount_condition,
        )
    )
    
    date_conditions = []
    for match_date in sorted(match_dates):
        match_start, match_end = business_day_utc_bounds(
            match_date, business_timezone
        )
        date_conditions.extend(
            [
                and_(
                    Transaction.posting_datetime.isnot(None),
                    Transaction.posting_datetime >= match_start,
                    Transaction.posting_datetime < match_end,
                ),
                and_(
                    Transaction.transaction_datetime.isnot(None),
                    Transaction.transaction_datetime >= match_start,
                    Transaction.transaction_datetime < match_end,
                ),
            ]
        )
        if not match_both_source_dates or not has_explicit_date:
            date_conditions.append(
                and_(
                    Transaction.created_at >= match_start,
                    Transaction.created_at < match_end,
                )
            )
    query = query.where(or_(*date_conditions))

    if exclude_transaction_ids:
        query = query.where(Transaction.id.not_in(exclude_transaction_ids))
    
    result = await db.execute(query.order_by(Transaction.id))
    transactions = list(result.scalars().all())
    if merchant_norm:
        transactions = [
            transaction
            for transaction in transactions
            if merchant_names_match(
                merchant_norm,
                transaction.merchant_norm or transaction.description,
            )
        ]
    return transactions


def merchant_similarity(left: str | None, right: str | None) -> Decimal:
    """Return a conservative similarity score for two descriptions."""
    left_norm = normalize_merchant(left or "")
    right_norm = normalize_merchant(right or "")
    if not left_norm or not right_norm:
        return Decimal("0")
    if left_norm == right_norm:
        return Decimal("1")
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    return Decimal(str(max(token_score, sequence_score)))


def merchant_names_match(left: str | None, right: str | None) -> bool:
    """Conservatively match merchant variants after money/card/date filtering."""
    left_norm = normalize_merchant(left or "")
    right_norm = normalize_merchant(right or "")
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True

    score = merchant_similarity(left_norm, right_norm)
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    shared_tokens = left_tokens & right_tokens
    is_prefix_variant = (
        left_norm.startswith(right_norm + " ")
        or right_norm.startswith(left_norm + " ")
    )
    if (
        is_prefix_variant
        and min(len(left_tokens), len(right_tokens)) >= 2
        and score >= MERCHANT_PREFIX_SIMILARITY_THRESHOLD
    ):
        return True
    return len(shared_tokens) >= 2 and score >= MERCHANT_SIMILARITY_THRESHOLD


def select_statement_match(
    candidates: list[Transaction],
    *,
    amount: Decimal,
    currency: str,
    transaction_datetime: datetime,
    posting_datetime: datetime | None,
    description: str,
    original_amount: Decimal | None = None,
    original_currency: str | None = None,
    business_timezone: str = DEFAULT_TIMEZONE,
) -> tuple[Transaction | None, Decimal | None]:
    """Select a decisive statement candidate, leaving ties unlinked."""
    if not candidates:
        return None, None
    if len(candidates) == 1:
        return candidates[0], Decimal("0.9500")

    source_transaction_date = business_date(
        transaction_datetime, business_timezone
    )
    source_posting_date = (
        business_date(posting_datetime, business_timezone)
        if posting_datetime
        else None
    )
    ranked: list[tuple[Decimal, Decimal, Decimal, Decimal, Transaction]] = []
    for candidate in candidates:
        money_score = Decimal("0")
        if candidate.amount == amount and candidate.currency == currency:
            money_score += Decimal("3")
        if (
            original_amount is not None
            and original_currency is not None
            and candidate.original_amount == original_amount
            and candidate.original_currency == original_currency
        ):
            money_score += Decimal("4")

        candidate_transaction_date = (
            business_date(candidate.transaction_datetime, business_timezone)
            if candidate.transaction_datetime is not None
            else None
        )
        candidate_posting_date = (
            business_date(candidate.posting_datetime, business_timezone)
            if candidate.posting_datetime is not None
            else None
        )
        date_score = Decimal("0")
        if candidate_transaction_date == source_transaction_date:
            date_score += Decimal("3")
        if source_posting_date is not None and candidate_posting_date == source_posting_date:
            date_score += Decimal("3")
        if source_posting_date is not None and candidate_transaction_date == source_posting_date:
            date_score += Decimal("1")
        if candidate_posting_date == source_transaction_date:
            date_score += Decimal("1")

        description_score = merchant_similarity(
            candidate.merchant_norm or candidate.description,
            description,
        )
        total = money_score + date_score + (description_score * Decimal("2"))
        ranked.append((total, money_score, date_score, description_score, candidate))

    ranked.sort(key=lambda item: (-item[0], item[4].id))
    best, second = ranked[0], ranked[1]
    decisive_description = (
        best[3] >= Decimal("0.25") and best[3] - second[3] >= Decimal("0.15")
    )
    decisive_dates = best[2] - second[2] >= Decimal("2")
    decisive_money = best[1] - second[1] >= Decimal("3")
    if best[0] - second[0] >= Decimal("1") and (
        decisive_description or decisive_dates or decisive_money
    ):
        confidence = min(
            Decimal("0.9900"),
            Decimal("0.75") + min(best[0], Decimal("12")) / Decimal("50"),
        ).quantize(Decimal("0.0001"))
        return best[4], confidence
    return None, None
