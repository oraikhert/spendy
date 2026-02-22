"""Transaction service"""
from decimal import Decimal
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, case
from sqlalchemy.orm import selectinload

from app.models.transaction import Transaction
from app.models.card import Card
from app.models.transaction_source_link import TransactionSourceLink
from app.schemas.transaction import TransactionCreate, TransactionUpdate
from app.utils.matching import normalize_merchant, generate_fingerprint


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


def _primary_datetime_expr():
    """Primary date expression: posting -> transaction -> created."""
    return func.coalesce(
        Transaction.posting_datetime,
        Transaction.transaction_datetime,
        Transaction.created_at
    )


def _build_transactions_ui_filters(
    account_id: int | None = None,
    card_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    kind: str | None = None,
    direction: str = "all",
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    currency: str | None = None,
) -> list:
    """Build filters for transactions UI list queries."""
    filters = []
    primary_datetime = _primary_datetime_expr()

    if account_id:
        filters.append(Card.account_id == account_id)
    if card_id:
        filters.append(Transaction.card_id == card_id)
    if date_from:
        filters.append(primary_datetime >= date_from)
    if date_to:
        filters.append(primary_datetime <= date_to)
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
        filters.append(Transaction.currency == currency)

    return filters


async def get_transaction_source_metadata(
    db: AsyncSession,
    transaction_ids: list[int]
) -> dict[int, dict[str, int | str | None]]:
    """
    Collect source metadata for transactions in one query.

    Returns dict:
      transaction_id -> {"source_count": int, "primary_parse_status": str | None}
    """
    metadata = {
        transaction_id: {"source_count": 0, "primary_parse_status": None}
        for transaction_id in transaction_ids
    }
    if not transaction_ids:
        return metadata

    query = (
        select(TransactionSourceLink)
        .where(TransactionSourceLink.transaction_id.in_(transaction_ids))
        .options(selectinload(TransactionSourceLink.source_event))
    )
    result = await db.execute(query)
    links = list(result.scalars().all())

    first_status_by_tx: dict[int, str] = {}
    for link in links:
        tx_meta = metadata.get(link.transaction_id)
        if tx_meta is None:
            continue
        tx_meta["source_count"] = int(tx_meta["source_count"]) + 1
        source_status = link.source_event.parse_status if link.source_event else None
        if source_status and link.transaction_id not in first_status_by_tx:
            first_status_by_tx[link.transaction_id] = source_status
        if link.is_primary and source_status:
            tx_meta["primary_parse_status"] = source_status

    # Fallback to any source parse status if no primary is marked.
    for transaction_id, status in first_status_by_tx.items():
        tx_meta = metadata[transaction_id]
        if tx_meta["primary_parse_status"] is None:
            tx_meta["primary_parse_status"] = status

    return metadata


async def get_transactions_for_ui(
    db: AsyncSession,
    account_id: int | None = None,
    card_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    kind: str | None = None,
    direction: str = "all",
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    currency: str | None = None,
    limit: int = 50,
    offset: int = 0
) -> tuple[list[Transaction], int, Decimal, Decimal, dict[int, dict[str, int | str | None]]]:
    """
    Query transactions for web UI with canonical date ordering and summary totals.

    Returns:
      (transactions, total_count, outflow_sum, inflow_sum, source_metadata)
    """
    primary_datetime = _primary_datetime_expr()
    filters = _build_transactions_ui_filters(
        account_id=account_id,
        card_id=card_id,
        date_from=date_from,
        date_to=date_to,
        q=q,
        kind=kind,
        direction=direction,
        min_amount=min_amount,
        max_amount=max_amount,
        currency=currency,
    )

    base_query = (
        select(Transaction)
        .join(Card, Transaction.card_id == Card.id)
        .options(selectinload(Transaction.card).selectinload(Card.account))
    )
    count_query = (
        select(func.count(Transaction.id))
        .join(Card, Transaction.card_id == Card.id)
    )
    summary_query = (
        select(
            func.coalesce(
                func.sum(case((Transaction.amount < 0, Transaction.amount), else_=0)),
                0
            ),
            func.coalesce(
                func.sum(case((Transaction.amount > 0, Transaction.amount), else_=0)),
                0
            ),
        )
        .join(Card, Transaction.card_id == Card.id)
    )

    if filters:
        base_query = base_query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))
        summary_query = summary_query.where(and_(*filters))

    count_result = await db.execute(count_query)
    total = int(count_result.scalar_one())

    summary_result = await db.execute(summary_query)
    outflow_sum, inflow_sum = summary_result.one()
    outflow_sum = Decimal(outflow_sum or 0)
    inflow_sum = Decimal(inflow_sum or 0)

    base_query = (
        base_query
        .order_by(primary_datetime.desc().nullslast(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(base_query)
    transactions = list(result.scalars().all())

    source_metadata = await get_transaction_source_metadata(
        db,
        [transaction.id for transaction in transactions]
    )
    return transactions, total, outflow_sum, inflow_sum, source_metadata


async def get_transaction_with_relations(
    db: AsyncSession,
    transaction_id: int
) -> Transaction | None:
    """Get one transaction with card/account relation for web details screen."""
    query = (
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .options(selectinload(Transaction.card).selectinload(Card.account))
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_transaction_currencies(db: AsyncSession) -> list[str]:
    """Get distinct canonical currencies used by transactions."""
    query = select(Transaction.currency).distinct().order_by(Transaction.currency)
    result = await db.execute(query)
    return [row[0] for row in result.all() if row[0]]
