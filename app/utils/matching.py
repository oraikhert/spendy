"""Matching and deduplication utilities"""
import re
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.card import Card
from app.models.transaction import Transaction


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

    query = select(Card)
    if account_id is not None:
        query = query.where(Card.account_id == account_id)
    result = await db.execute(query)
    cards = result.scalars().all()

    for card in cards:
        digits_only = re.sub(r"\D", "", card.card_masked_number or "")
        if len(digits_only) >= 4 and digits_only[-4:] == last_four:
            return card
    return None


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
    merchant_norm: str | None
) -> str:
    """
    Generate fingerprint for transaction deduplication.
    
    Args:
        card_id: Card ID
        amount: Transaction amount
        currency: Transaction currency
        posting_datetime: Posting datetime
        transaction_datetime: Transaction datetime
        merchant_norm: Normalized merchant name
        
    Returns:
        Fingerprint string
    """
    # Use posting_date if available, otherwise transaction_date
    if posting_datetime:
        date_str = posting_datetime.date().isoformat()
    elif transaction_datetime:
        date_str = transaction_datetime.date().isoformat()
    else:
        date_str = "unknown"
    
    merchant_str = merchant_norm or ""
    
    # Format: card_id|date|amount|currency|merchant_norm
    fingerprint = f"{card_id}|{date_str}|{amount}|{currency}|{merchant_str}"
    
    return fingerprint


async def find_matching_transactions(
    db: AsyncSession,
    card_id: int,
    amount: Decimal,
    currency: str,
    posting_datetime: datetime | None,
    transaction_datetime: datetime | None,
    merchant_norm: str | None = None
) -> list[Transaction]:
    """
    Find matching transactions based on card_id, amount, currency, and date.
    
    Args:
        db: Database session
        card_id: Card ID
        amount: Transaction amount
        currency: Transaction currency
        posting_datetime: Posting datetime
        transaction_datetime: Transaction datetime
        merchant_norm: Normalized merchant name (optional)
        
    Returns:
        List of matching transactions
    """
    # Determine the date to match on
    if posting_datetime:
        match_date = posting_datetime.date()
        date_field = Transaction.posting_datetime
    elif transaction_datetime:
        match_date = transaction_datetime.date()
        date_field = Transaction.transaction_datetime
    else:
        # No date to match on
        return []
    
    # Build query
    query = select(Transaction).where(
        and_(
            Transaction.card_id == card_id,
            Transaction.amount == amount,
            Transaction.currency == currency,
        )
    )
    
    # Add date filter
    # Match on the same date (not exact datetime)
    query = query.where(
        or_(
            and_(
                Transaction.posting_datetime.isnot(None),
                Transaction.posting_datetime >= datetime.combine(match_date, datetime.min.time()),
                Transaction.posting_datetime < datetime.combine(match_date, datetime.max.time())
            ),
            and_(
                Transaction.transaction_datetime.isnot(None),
                Transaction.transaction_datetime >= datetime.combine(match_date, datetime.min.time()),
                Transaction.transaction_datetime < datetime.combine(match_date, datetime.max.time())
            )
        )
    )
    
    # Optional: filter by merchant_norm if provided
    if merchant_norm:
        query = query.where(Transaction.merchant_norm == merchant_norm)
    
    result = await db.execute(query)
    transactions = result.scalars().all()
    
    return list(transactions)
