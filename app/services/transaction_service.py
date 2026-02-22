"""Transaction service"""
from decimal import Decimal
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from app.models.transaction import Transaction
from app.models.transaction_source_link import TransactionSourceLink
from app.schemas.transaction import TransactionCreate, TransactionUpdate
from app.utils.matching import normalize_merchant, generate_fingerprint


async def get_transaction_with_relations(
    db: AsyncSession, transaction_id: int
) -> Transaction | None:
    """Get transaction with card, account, and source links eager-loaded."""
    from app.models.card import Card
    result = await db.execute(
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .options(
            selectinload(Transaction.card).selectinload(Card.account),
            selectinload(Transaction.source_links).selectinload(
                TransactionSourceLink.source_event
            ),
        )
    )
    return result.scalar_one_or_none()


async def get_transactions_for_web(
    db: AsyncSession,
    account_id: int | None = None,
    card_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    kind: str | None = None,
    direction: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    currency: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Transaction], int, Decimal, Decimal]:
    """
    Get transactions with card/source_links loaded and inflow/outflow sums.
    Returns (transactions, total_count, total_out, total_in).
    """
    from app.models.card import Card

    query = select(Transaction).options(
        selectinload(Transaction.card).selectinload(Card.account),
        selectinload(Transaction.source_links),
    )
    count_query = select(func.count(Transaction.id))
    sum_out_query = select(func.sum(Transaction.amount)).where(Transaction.amount < 0)
    sum_in_query = select(func.sum(Transaction.amount)).where(Transaction.amount > 0)

    filters = []
    needs_card_join = False

    if card_id:
        filters.append(Transaction.card_id == card_id)

    if account_id:
        needs_card_join = True
        filters.append(Card.account_id == account_id)

    if date_from:
        filters.append(
            or_(
                and_(Transaction.posting_datetime.isnot(None), Transaction.posting_datetime >= date_from),
                and_(Transaction.posting_datetime.is_(None), Transaction.transaction_datetime >= date_from),
            )
        )

    if date_to:
        filters.append(
            or_(
                and_(Transaction.posting_datetime.isnot(None), Transaction.posting_datetime <= date_to),
                and_(Transaction.posting_datetime.is_(None), Transaction.transaction_datetime <= date_to),
            )
        )

    if q:
        filters.append(Transaction.description.ilike(f"%{q}%"))

    if kind:
        filters.append(Transaction.transaction_kind == kind)

    if direction == "out":
        filters.append(Transaction.amount < 0)
    elif direction == "in":
        filters.append(Transaction.amount > 0)

    if min_amount is not None:
        filters.append(Transaction.amount >= min_amount)

    if max_amount is not None:
        filters.append(Transaction.amount <= max_amount)

    if currency:
        filters.append(Transaction.currency == currency.strip().upper())

    if needs_card_join:
        query = query.join(Card, Transaction.card_id == Card.id)
        count_query = count_query.join(Card, Transaction.card_id == Card.id)
        sum_out_query = sum_out_query.join(Card, Transaction.card_id == Card.id)
        sum_in_query = sum_in_query.join(Card, Transaction.card_id == Card.id)

    if filters:
        cond = and_(*filters)
        query = query.where(cond)
        count_query = count_query.where(cond)
        sum_out_query = sum_out_query.where(cond)
        sum_in_query = sum_in_query.where(cond)

    total = (await db.execute(count_query)).scalar_one()
    total_out = (await db.execute(sum_out_query)).scalar_one() or Decimal("0")
    total_in = (await db.execute(sum_in_query)).scalar_one() or Decimal("0")

    query = query.order_by(
        Transaction.posting_datetime.desc().nullslast(),
        Transaction.transaction_datetime.desc().nullslast(),
        Transaction.created_at.desc(),
    )
    query = query.limit(limit).offset(offset)
    transactions = list((await db.execute(query)).scalars().all())

    return transactions, total, total_out, total_in


async def set_primary_source(
    db: AsyncSession, transaction_id: int, source_event_id: int
) -> bool:
    """Set one source as primary, clearing all others for this transaction."""
    result = await db.execute(
        select(TransactionSourceLink).where(
            TransactionSourceLink.transaction_id == transaction_id
        )
    )
    links = list(result.scalars().all())
    target = None
    for link in links:
        if link.source_event_id == source_event_id:
            target = link
        link.is_primary = False
    if not target:
        return False
    target.is_primary = True
    await db.commit()
    return True


async def create_transaction(
    db: AsyncSession,
    transaction_data: TransactionCreate
) -> Transaction:
    """Create a new transaction"""
    # Normalize merchant and generate fingerprint
    merchant_norm = normalize_merchant(transaction_data.description)
    fingerprint = generate_fingerprint(
        card_id=transaction_data.card_id,
        amount=transaction_data.amount,
        currency=transaction_data.currency,
        posting_datetime=transaction_data.posting_datetime,
        transaction_datetime=transaction_data.transaction_datetime,
        merchant_norm=merchant_norm,
        orig_amount=transaction_data.original_amount,
        orig_currency=transaction_data.original_currency,
    )
    
    transaction = Transaction(
        **transaction_data.model_dump(),
        merchant_norm=merchant_norm,
        fingerprint=fingerprint
    )
    db.add(transaction)
    await db.commit()
    await db.refresh(transaction)
    return transaction


async def get_transaction(db: AsyncSession, transaction_id: int) -> Transaction | None:
    """Get transaction by ID"""
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    return result.scalar_one_or_none()


async def get_transactions(
    db: AsyncSession,
    account_id: int | None = None,
    card_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    kind: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    limit: int = 100,
    offset: int = 0
) -> tuple[list[Transaction], int]:
    """
    Get transactions with filters.
    
    Returns:
        Tuple of (transactions list, total count)
    """
    # Base query
    query = select(Transaction)
    count_query = select(func.count(Transaction.id))
    
    # Apply filters
    filters = []
    
    if card_id:
        filters.append(Transaction.card_id == card_id)
    
    if account_id:
        # Need to join with Card to filter by account_id
        from app.models.card import Card
        query = query.join(Card, Transaction.card_id == Card.id)
        count_query = count_query.join(Card, Transaction.card_id == Card.id)
        filters.append(Card.account_id == account_id)
    
    if date_from:
        # Filter by posting_datetime if exists, else transaction_datetime
        filters.append(
            or_(
                and_(
                    Transaction.posting_datetime.isnot(None),
                    Transaction.posting_datetime >= date_from
                ),
                and_(
                    Transaction.posting_datetime.is_(None),
                    Transaction.transaction_datetime >= date_from
                )
            )
        )
    
    if date_to:
        filters.append(
            or_(
                and_(
                    Transaction.posting_datetime.isnot(None),
                    Transaction.posting_datetime <= date_to
                ),
                and_(
                    Transaction.posting_datetime.is_(None),
                    Transaction.transaction_datetime <= date_to
                )
            )
        )
    
    if q:
        # Search in description
        filters.append(Transaction.description.ilike(f"%{q}%"))
    
    if kind:
        filters.append(Transaction.transaction_kind == kind)
    
    if min_amount is not None:
        filters.append(Transaction.amount >= min_amount)
    
    if max_amount is not None:
        filters.append(Transaction.amount <= max_amount)
    
    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()
    
    # Apply pagination and ordering
    query = query.order_by(Transaction.posting_datetime.desc().nullslast(), Transaction.transaction_datetime.desc().nullslast())
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    transactions = list(result.scalars().all())
    
    return transactions, total


async def update_transaction(
    db: AsyncSession,
    transaction_id: int,
    transaction_data: TransactionUpdate
) -> Transaction | None:
    """Update transaction"""
    transaction = await get_transaction(db, transaction_id)
    if not transaction:
        return None
    
    update_data = transaction_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(transaction, field, value)
    
    # Recalculate merchant_norm and fingerprint if description changed
    if "description" in update_data:
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
    )
    
    await db.commit()
    await db.refresh(transaction)
    return transaction


async def delete_transaction(db: AsyncSession, transaction_id: int) -> bool:
    """Delete transaction (hard delete)"""
    transaction = await get_transaction(db, transaction_id)
    if not transaction:
        return False
    
    await db.delete(transaction)
    await db.commit()
    return True


async def get_transaction_sources(
    db: AsyncSession,
    transaction_id: int
) -> list[TransactionSourceLink]:
    """Get all source events linked to a transaction"""
    query = (
        select(TransactionSourceLink)
        .where(TransactionSourceLink.transaction_id == transaction_id)
        .options(selectinload(TransactionSourceLink.source_event))
    )
    result = await db.execute(query)
    return list(result.scalars().all())
