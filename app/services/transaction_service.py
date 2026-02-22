"""Transaction service"""
from decimal import Decimal
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, case
from sqlalchemy.orm import selectinload, joinedload

from app.models.transaction import Transaction
from app.models.card import Card
from app.models.account import Account
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


async def get_transaction(
    db: AsyncSession,
    transaction_id: int,
    load_relations: bool = False,
) -> Transaction | None:
    """Get transaction by ID, optionally eager-loading card/account/source_links."""
    query = select(Transaction).where(Transaction.id == transaction_id)
    if load_relations:
        query = query.options(
            joinedload(Transaction.card).joinedload(Card.account),
            selectinload(Transaction.source_links),
        )
    result = await db.execute(query)
    return result.unique().scalar_one_or_none()


def _build_filters(
    account_id: int | None = None,
    card_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    kind: str | None = None,
    direction: str | None = None,
    currency: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
):
    """Build common filter clauses. Returns (filters list, needs_card_join bool)."""
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

    if currency:
        filters.append(Transaction.currency == currency)

    if min_amount is not None:
        filters.append(func.abs(Transaction.amount) >= min_amount)

    if max_amount is not None:
        filters.append(func.abs(Transaction.amount) <= max_amount)

    return filters, needs_card_join


async def get_transactions(
    db: AsyncSession,
    account_id: int | None = None,
    card_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    kind: str | None = None,
    direction: str | None = None,
    currency: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    limit: int = 100,
    offset: int = 0,
    load_relations: bool = False,
) -> tuple[list[Transaction], int]:
    """Get transactions with filters. Returns (transactions, total_count)."""
    query = select(Transaction)
    count_query = select(func.count(Transaction.id))

    filters, needs_card_join = _build_filters(
        account_id=account_id, card_id=card_id, date_from=date_from,
        date_to=date_to, q=q, kind=kind, direction=direction,
        currency=currency, min_amount=min_amount, max_amount=max_amount,
    )

    if needs_card_join:
        query = query.join(Card, Transaction.card_id == Card.id)
        count_query = count_query.join(Card, Transaction.card_id == Card.id)

    if load_relations:
        query = query.options(
            joinedload(Transaction.card).joinedload(Card.account),
            selectinload(Transaction.source_links),
        )

    if filters:
        query = query.where(and_(*filters))
        count_query = count_query.where(and_(*filters))

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    query = query.order_by(
        Transaction.posting_datetime.desc().nullslast(),
        Transaction.transaction_datetime.desc().nullslast(),
    )
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    transactions = list(result.unique().scalars().all())

    return transactions, total


async def get_transactions_summary(
    db: AsyncSession,
    account_id: int | None = None,
    card_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
    kind: str | None = None,
    direction: str | None = None,
    currency: str | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
) -> dict:
    """Aggregate summary (count, total_out, total_in) for filtered transactions."""
    query = select(
        func.count(Transaction.id).label("count"),
        func.coalesce(
            func.sum(case((Transaction.amount < 0, Transaction.amount), else_=Decimal("0"))),
            Decimal("0"),
        ).label("total_out"),
        func.coalesce(
            func.sum(case((Transaction.amount > 0, Transaction.amount), else_=Decimal("0"))),
            Decimal("0"),
        ).label("total_in"),
    )

    filters, needs_card_join = _build_filters(
        account_id=account_id, card_id=card_id, date_from=date_from,
        date_to=date_to, q=q, kind=kind, direction=direction,
        currency=currency, min_amount=min_amount, max_amount=max_amount,
    )

    if needs_card_join:
        query = query.join(Card, Transaction.card_id == Card.id)

    if filters:
        query = query.where(and_(*filters))

    row = (await db.execute(query)).one()
    return {"count": row.count, "total_out": row.total_out, "total_in": row.total_in}


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
