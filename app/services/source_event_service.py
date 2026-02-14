"""SourceEvent service"""
import hashlib
from datetime import datetime
from pathlib import Path
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from app.models.card import Card
from app.models.source_event import SourceEvent
from app.models.transaction import Transaction
from app.models.transaction_source_link import TransactionSourceLink
from app.services.exchange_rate_service import exchange_rate_service
from app.schemas.source_event import SourceEventCreateText, TransactionCreateAndLink
from app.utils.parsing import parse_text
from app.utils.matching import find_matching_transactions, normalize_merchant, generate_fingerprint, find_card_by_last_four


def _enrich_found_transaction_with_source(transaction: Transaction, source_event: SourceEvent) -> None:
    """Update found transaction with parsed data from source_event when transaction has missing/inferior data."""
    if transaction.location is None and source_event.parsed_location is not None:
        transaction.location = source_event.parsed_location
    if (not transaction.description or not transaction.description.strip()) and source_event.parsed_description:
        transaction.description = source_event.parsed_description
    if transaction.transaction_datetime is None and source_event.parsed_transaction_datetime is not None:
        transaction.transaction_datetime = source_event.parsed_transaction_datetime
    if transaction.posting_datetime is None and source_event.parsed_posting_datetime is not None:
        transaction.posting_datetime = source_event.parsed_posting_datetime
    if (
        transaction.transaction_kind == "other"
        and source_event.parsed_transaction_kind is not None
        and source_event.parsed_transaction_kind != "other"
    ):
        transaction.transaction_kind = source_event.parsed_transaction_kind


async def _resolve_amount_currency_fx(
    db: AsyncSession,
    card_id: int,
    source_amount: Decimal,
    source_currency: str,
    use_auto_fx: bool = True,
) -> tuple[Decimal, str, Decimal | None, str | None, Decimal | None]:
    """
    If source_currency != account.currency and use_auto_fx: convert and return
    (amount, currency, original_amount, original_currency, fx_rate).
    Else: (source_amount, source_currency, None, None, None).
    """
    if not source_currency or not use_auto_fx:
        return (source_amount, source_currency, None, None, None)
    card_result = await db.execute(
        select(Card).options(selectinload(Card.account)).where(Card.id == card_id)
    )
    card = card_result.scalar_one_or_none()
    if not card or not card.account:
        return (source_amount, source_currency, None, None, None)
    account_currency = card.account.account_currency
    if not account_currency or source_currency.upper() == account_currency.upper():
        return (source_amount, source_currency, None, None, None)
    fx_rate = await exchange_rate_service.get_rate(source_currency, account_currency)
    amount = (source_amount * fx_rate).quantize(Decimal("0.01"))
    return (amount, account_currency, source_amount, source_currency, fx_rate)


async def create_source_event_from_text(
    db: AsyncSession,
    source_data: SourceEventCreateText
) -> SourceEvent:
    """
    Create source event from text and attempt matching.
    
    This includes:
    1. Create SourceEvent
    2. Parse text (stub)
    3. Find matching transaction or create new one
    4. Link source to transaction
    """
    # Generate hash for idempotency
    raw_hash = hashlib.sha256(source_data.raw_text.encode()).hexdigest()
    
    # Check if already exists
    existing = await db.execute(
        select(SourceEvent).where(SourceEvent.raw_hash == raw_hash)
    )
    if existing.scalar_one_or_none():
        raise ValueError("Source event with this content already exists")
    
    # Parse text (stub)
    parsed = parse_text(source_data.raw_text)
    
    # Resolve effective card_id: from request or from parsed last-four digits
    effective_card_id = source_data.card_id
    if not effective_card_id and parsed.get("parsed_card_number"):
        card = await find_card_by_last_four(
            db, parsed["parsed_card_number"], source_data.account_id
        )
        if card:
            effective_card_id = card.id

    # Resolve effective transaction datetime: parsed first, else manual param
    effective_transaction_datetime = parsed.get("parsed_transaction_datetime") or source_data.transaction_datetime

    # Create source event
    source_event = SourceEvent(
        source_type=source_data.source_type,
        received_at=effective_transaction_datetime,
        raw_text=source_data.raw_text,
        raw_hash=raw_hash,
        account_id=source_data.account_id,
        card_id=effective_card_id,
        **parsed
    )
    db.add(source_event)
    await db.flush()  # Get ID without committing
    
    # Attempt matching if we have parsed amount and currency and a card
    if parsed["parsed_amount"] and parsed["parsed_currency"] and effective_card_id:
        merchant_norm = normalize_merchant(parsed["parsed_description"] or "")
        amount, currency, orig_amount, orig_currency, fx_rate = await _resolve_amount_currency_fx(
            db, effective_card_id, parsed["parsed_amount"], parsed["parsed_currency"]
        )
        matching_transactions = await find_matching_transactions(
            db=db,
            card_id=effective_card_id,
            amount=amount,
            currency=currency,
            posting_datetime=parsed["parsed_posting_datetime"],
            transaction_datetime=effective_transaction_datetime,
            created_at=source_event.created_at,
            merchant_norm=merchant_norm,
            orig_amount=orig_amount,
            orig_currency=orig_currency,
        )
        
        if len(matching_transactions) == 1:
            # Single match - link to it and enrich transaction with parsed data when missing
            found_transaction = matching_transactions[0]
            link = TransactionSourceLink(
                transaction_id=found_transaction.id,
                source_event_id=source_event.id,
                match_confidence=1.0,
                is_primary=False
            )
            db.add(link)
            _enrich_found_transaction_with_source(found_transaction, source_event)
        elif len(matching_transactions) == 0:
            # No match - create new transaction (amount, currency, orig_* already resolved above)
            fingerprint = generate_fingerprint(
                card_id=effective_card_id,
                amount=amount,
                currency=currency,
                posting_datetime=parsed["parsed_posting_datetime"],
                transaction_datetime=effective_transaction_datetime,
                merchant_norm=merchant_norm,
                orig_amount=orig_amount,
                orig_currency=orig_currency,
            )
            transaction = Transaction(
                card_id=effective_card_id,
                amount=amount,
                currency=currency,
                transaction_datetime=effective_transaction_datetime,
                posting_datetime=parsed["parsed_posting_datetime"],
                description=parsed["parsed_description"] or source_data.raw_text,
                location=parsed.get("parsed_location"),
                transaction_kind=parsed.get("parsed_transaction_kind") or "other",
                original_amount=orig_amount,
                original_currency=orig_currency,
                fx_rate=fx_rate,
                fx_fee=None,
                merchant_norm=merchant_norm,
                fingerprint=fingerprint
            )
            db.add(transaction)
            await db.flush()
            
            # Link to new transaction
            link = TransactionSourceLink(
                transaction_id=transaction.id,
                source_event_id=source_event.id,
                match_confidence=1.0,
                is_primary=True
            )
            db.add(link)
        else:
            # Multiple matches - log but don't link automatically
            # In production, this could be logged or flagged for manual review
            pass
    
    await db.commit()
    await db.refresh(source_event)
    return source_event


async def create_source_event_from_file(
    db: AsyncSession,
    source_type: str,
    file_content: bytes,
    filename: str,
    account_id: int | None = None,
    card_id: int | None = None
) -> SourceEvent:
    """
    Create source event from uploaded file.
    
    Args:
        db: Database session
        source_type: Type of source
        file_content: File content as bytes
        filename: Original filename
        account_id: Optional account ID
        card_id: Optional card ID
        
    Returns:
        Created source event
    """
    # Generate hash for idempotency
    raw_hash = hashlib.sha256(file_content).hexdigest()
    
    # Check if already exists
    existing = await db.execute(
        select(SourceEvent).where(SourceEvent.raw_hash == raw_hash)
    )
    if existing.scalar_one_or_none():
        raise ValueError("Source event with this file already exists")
    
    # Save file
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Create unique filename with hash prefix
    file_path = upload_dir / f"{raw_hash[:16]}_{filename}"
    file_path.write_bytes(file_content)
    
    # Create source event
    source_event = SourceEvent(
        source_type=source_type,
        file_path=str(file_path),
        raw_hash=raw_hash,
        account_id=account_id,
        card_id=card_id,
        parse_status="new",  # File parsing not implemented yet
    )
    db.add(source_event)
    await db.commit()
    await db.refresh(source_event)
    return source_event


async def get_source_event(db: AsyncSession, source_event_id: int) -> SourceEvent | None:
    """Get source event by ID"""
    result = await db.execute(
        select(SourceEvent).where(SourceEvent.id == source_event_id)
    )
    return result.scalar_one_or_none()


async def get_source_events(
    db: AsyncSession,
    source_type: str | None = None,
    parse_status: str | None = None,
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    has_transaction: bool | None = None,
    limit: int = 100,
    offset: int = 0
) -> tuple[list[SourceEvent], int]:
    """
    Get source events with filters.
    
    Returns:
        Tuple of (source events list, total count)
    """
    # Base query
    query = select(SourceEvent)
    count_query = select(func.count(SourceEvent.id))
    
    # Apply filters
    filters = []
    
    if source_type:
        filters.append(SourceEvent.source_type == source_type)
    
    if parse_status:
        filters.append(SourceEvent.parse_status == parse_status)
    
    if received_from:
        filters.append(SourceEvent.received_at >= received_from)
    
    if received_to:
        filters.append(SourceEvent.received_at <= received_to)
    
    if has_transaction is not None:
        # Need to check if there are any links
        if has_transaction:
            query = query.join(
                TransactionSourceLink,
                SourceEvent.id == TransactionSourceLink.source_event_id
            )
            count_query = count_query.join(
                TransactionSourceLink,
                SourceEvent.id == TransactionSourceLink.source_event_id
            )
        else:
            query = query.outerjoin(
                TransactionSourceLink,
                SourceEvent.id == TransactionSourceLink.source_event_id
            )
            count_query = count_query.outerjoin(
                TransactionSourceLink,
                SourceEvent.id == TransactionSourceLink.source_event_id
            )
            filters.append(TransactionSourceLink.source_event_id.is_(None))
    
    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply pagination and ordering
    query = query.order_by(SourceEvent.received_at.desc())
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    source_events = list(result.scalars().all())
    
    return source_events, total


async def link_source_to_transaction(
    db: AsyncSession,
    source_event_id: int,
    transaction_id: int
) -> TransactionSourceLink:
    """Link a source event to a transaction"""
    # Check if link already exists
    existing = await db.execute(
        select(TransactionSourceLink).where(
            and_(
                TransactionSourceLink.source_event_id == source_event_id,
                TransactionSourceLink.transaction_id == transaction_id
            )
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Link already exists")
    
    link = TransactionSourceLink(
        transaction_id=transaction_id,
        source_event_id=source_event_id,
        is_primary=False
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def create_transaction_and_link(
    db: AsyncSession,
    source_event_id: int,
    transaction_data: TransactionCreateAndLink
) -> tuple[Transaction, TransactionSourceLink]:
    """
    Create a new transaction from source event and link them.
    Uses parsed data from source event with optional overrides.
    """
    # Get source event
    source_event = await get_source_event(db, source_event_id)
    if not source_event:
        raise ValueError("Source event not found")
    
    # Build transaction data from source event + overrides
    card_id = transaction_data.card_id or source_event.card_id
    if not card_id:
        raise ValueError("card_id is required")
    
    amount = transaction_data.amount or source_event.parsed_amount
    if amount is None:
        raise ValueError("amount is required")
    
    currency = transaction_data.currency or source_event.parsed_currency
    if not currency:
        raise ValueError("currency is required")
    
    description = (
        transaction_data.description
        or source_event.parsed_description
        or source_event.raw_text
        or "No description"
    )
    
    transaction_datetime = (
        transaction_data.transaction_datetime
        or source_event.parsed_transaction_datetime
    )
    
    posting_datetime = (
        transaction_data.posting_datetime
        or source_event.parsed_posting_datetime
    )
    
    location = (
        transaction_data.location
        or source_event.parsed_location
    )
    
    transaction_kind = (
        transaction_data.transaction_kind
        or source_event.parsed_transaction_kind
        or "other"
    )
    
    # Auto-FX when source currency != account currency (skip if user provided manual FX)
    use_auto_fx = (
        transaction_data.original_amount is None
        and transaction_data.fx_rate is None
    )
    if use_auto_fx:
        amount, currency, orig_amount, orig_currency, fx_rate = await _resolve_amount_currency_fx(
            db, card_id, amount, currency
        )
        fx_fee = None
    else:
        orig_amount = transaction_data.original_amount
        orig_currency = transaction_data.original_currency
        fx_rate = transaction_data.fx_rate
        fx_fee = transaction_data.fx_fee
    
    # Generate merchant_norm and fingerprint
    merchant_norm = normalize_merchant(description)
    fingerprint = generate_fingerprint(
        card_id=card_id,
        amount=amount,
        currency=currency,
        posting_datetime=posting_datetime,
        transaction_datetime=transaction_datetime,
        merchant_norm=merchant_norm,
        orig_amount=orig_amount,
        orig_currency=orig_currency,
    )
    
    # Create transaction
    transaction = Transaction(
        card_id=card_id,
        amount=amount,
        currency=currency,
        transaction_datetime=transaction_datetime,
        posting_datetime=posting_datetime,
        description=description,
        location=location,
        transaction_kind=transaction_kind,
        original_amount=orig_amount,
        original_currency=orig_currency,
        fx_rate=fx_rate,
        fx_fee=fx_fee,
        merchant_norm=merchant_norm,
        fingerprint=fingerprint
    )
    db.add(transaction)
    await db.flush()
    
    # Create link
    link = TransactionSourceLink(
        transaction_id=transaction.id,
        source_event_id=source_event_id,
        is_primary=True
    )
    db.add(link)
    
    await db.commit()
    await db.refresh(transaction)
    await db.refresh(link)
    
    return transaction, link


async def unlink_source_from_transaction(
    db: AsyncSession,
    source_event_id: int,
    transaction_id: int
) -> bool:
    """Unlink a source event from a transaction"""
    link = await db.execute(
        select(TransactionSourceLink).where(
            and_(
                TransactionSourceLink.source_event_id == source_event_id,
                TransactionSourceLink.transaction_id == transaction_id
            )
        )
    )
    link_obj = link.scalar_one_or_none()
    if not link_obj:
        return False
    
    await db.delete(link_obj)
    await db.commit()
    return True


async def reprocess_source_event(
    db: AsyncSession,
    source_event_id: int
) -> SourceEvent:
    """
    Reprocess a source event.
    Re-runs parsing and matching logic.
    """
    source_event = await get_source_event(db, source_event_id)
    if not source_event:
        raise ValueError("Source event not found")
    
    # Re-parse if text source
    if source_event.raw_text:
        parsed = parse_text(source_event.raw_text)
        for field, value in parsed.items():
            setattr(source_event, field, value)
    
    # Attempt matching if we have necessary data
    if (source_event.parsed_amount and
        source_event.parsed_currency and
        source_event.card_id):
        
        merchant_norm = normalize_merchant(
            source_event.parsed_description or ""
        )
        amount, currency, orig_amount, orig_currency, fx_rate = await _resolve_amount_currency_fx(
            db, source_event.card_id, source_event.parsed_amount, source_event.parsed_currency
        )
        matching_transactions = await find_matching_transactions(
            db=db,
            card_id=source_event.card_id,
            amount=amount,
            currency=currency,
            posting_datetime=source_event.parsed_posting_datetime,
            transaction_datetime=source_event.parsed_transaction_datetime,
            created_at=source_event.created_at,
            merchant_norm=merchant_norm,
            orig_amount=orig_amount,
            orig_currency=orig_currency,
        )
        
        # Remove existing links
        existing_links = await db.execute(
            select(TransactionSourceLink)
            .where(TransactionSourceLink.source_event_id == source_event_id)
        )
        for link in existing_links.scalars().all():
            await db.delete(link)
        
        if len(matching_transactions) == 1:
            # Single match - link to it and enrich transaction with parsed data when missing
            found_transaction = matching_transactions[0]
            link = TransactionSourceLink(
                transaction_id=found_transaction.id,
                source_event_id=source_event.id,
                match_confidence=1.0,
                is_primary=False
            )
            db.add(link)
            _enrich_found_transaction_with_source(found_transaction, source_event)
    
    await db.commit()
    await db.refresh(source_event)
    return source_event
