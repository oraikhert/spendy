"""Direct transaction CRUD and bounded, deterministic read queries.

Writes commit here. They never ingest sources, match records, or retrieve FX rates.
"""
from datetime import datetime
from decimal import Decimal

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, func, select, union
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.card import Card
from app.models.source_payload import SourcePayload
from app.models.transaction import Transaction
from app.models.transaction_observation import TransactionObservation
from app.models.transaction_source_link import TransactionSourceLink
from app.schemas.transaction import (
    Amount, ExchangeRate, MAX_RECORD_ID, TransactionCreate, TransactionUpdate,
    normalize_currency, validate_original_values,
)
from app.utils.canonicalization import transaction_business_timezone
from app.utils.matching import generate_fingerprint, normalize_merchant


REFERENCE_BATCH_SIZE = 500
_amount_adapter = TypeAdapter(Amount)
_rate_adapter = TypeAdapter(ExchangeRate)


def _validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= 1000:
        raise ValueError("limit: Choose between 1 and 1000 records per page")
    if offset < 0:
        raise ValueError("offset: The page offset cannot be negative")


def _validated_amount(value: Decimal | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return _amount_adapter.validate_python(value)
    except ValidationError as exc:
        raise ValueError(f"{field}: Use a finite amount with up to 13 integer and 2 fractional digits") from exc


async def _validate_references(
    db: AsyncSession, account_id: int | None, card_id: int | None
) -> None:
    if account_id is not None:
        if not 0 < account_id <= MAX_RECORD_ID or await db.get(Account, account_id) is None:
            raise ValueError("account_id: Account not found")
    if card_id is not None:
        card = await db.get(Card, card_id) if 0 < card_id <= MAX_RECORD_ID else None
        if card is None:
            raise ValueError("card_id: Card not found")
        if account_id is not None and card.account_id != account_id:
            raise ValueError("card_id: Choose a card belonging to the selected account")


def _set_fingerprint(transaction: Transaction, business_timezone: str) -> None:
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


async def _refresh_fingerprint(db: AsyncSession, transaction: Transaction) -> None:
    with db.no_autoflush:
        card = await db.scalar(
            select(Card)
            .where(Card.id == transaction.card_id)
            .options(selectinload(Card.account))
        )
        observations = []
        if transaction.id is not None:
            observations = list(
                await db.scalars(
                    select(TransactionObservation)
                    .join(
                        TransactionSourceLink,
                        TransactionSourceLink.observation_id
                        == TransactionObservation.id,
                    )
                    .where(
                        TransactionSourceLink.transaction_id == transaction.id
                    )
                    .options(selectinload(TransactionObservation.payload))
                )
            )
    if card is None:
        raise ValueError("card_id: Card not found")
    _set_fingerprint(
        transaction,
        transaction_business_timezone(card, observations),
    )


async def refresh_account_transaction_fingerprints(
    db: AsyncSession, account_id: int
) -> None:
    result = await db.execute(
        select(Transaction)
        .join(Card)
        .where(Card.account_id == account_id, Card.timezone.is_(None))
        .options(
            selectinload(Transaction.card).selectinload(Card.account),
            selectinload(Transaction.source_links)
            .selectinload(TransactionSourceLink.observation)
            .selectinload(TransactionObservation.payload),
        )
    )
    for transaction in result.scalars().all():
        observations = [link.observation for link in transaction.source_links]
        _set_fingerprint(
            transaction,
            transaction_business_timezone(transaction.card, observations),
        )


async def refresh_card_transaction_fingerprints(
    db: AsyncSession, card_id: int
) -> None:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.card_id == card_id)
        .options(
            selectinload(Transaction.card).selectinload(Card.account),
            selectinload(Transaction.source_links)
            .selectinload(TransactionSourceLink.observation)
            .selectinload(TransactionObservation.payload),
        )
    )
    for transaction in result.scalars().all():
        observations = [link.observation for link in transaction.source_links]
        _set_fingerprint(
            transaction,
            transaction_business_timezone(transaction.card, observations),
        )


async def create_transaction(
    db: AsyncSession, transaction_data: TransactionCreate
) -> Transaction:
    """Create and commit a record; the selected card must exist."""
    await _validate_references(db, None, transaction_data.card_id)
    transaction = Transaction(**transaction_data.model_dump())
    await _refresh_fingerprint(db, transaction)
    db.add(transaction)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ValueError("card_id: The transaction could not be saved; refresh the available cards") from exc
    return await get_transaction(db, transaction.id)


async def get_transaction(db: AsyncSession, transaction_id: int) -> Transaction | None:
    """Get a record with the card and account required by the HTML views."""
    if not 0 < transaction_id <= MAX_RECORD_ID:
        return None
    result = await db.execute(
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .options(selectinload(Transaction.card).selectinload(Card.account))
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
    offset: int = 0,
    *,
    currency: str | None = None,
    direction: str | None = None,
    min_abs_amount: Decimal | None = None,
    max_abs_amount: Decimal | None = None,
) -> tuple[list[Transaction], int]:
    """Filter before counting/paging; existing amount bounds remain signed.

    Date bounds are inclusive. Callers supplying calendar dates must expand them
    to full days. Records without either saved date never acquire a date fallback.
    """
    _validate_page(limit, offset)
    await _validate_references(db, account_id, card_id)
    if kind is not None and kind not in {"purchase", "topup", "refund", "other"}:
        raise ValueError("kind: Choose a valid transaction type")
    if direction is not None and direction not in {"out", "in"}:
        raise ValueError("direction: Choose money out or money in")
    if currency is not None:
        try:
            currency = normalize_currency(currency)
        except ValueError as exc:
            raise ValueError(f"currency: {exc}") from exc
    if date_from is not None and date_to is not None:
        try:
            reversed_dates = date_from > date_to
        except TypeError as exc:
            raise ValueError("date_to: Use consistent timezone information for both date bounds") from exc
        if reversed_dates:
            raise ValueError("date_to: The end date must be on or after the start date")
    min_amount = _validated_amount(min_amount, "min_amount")
    max_amount = _validated_amount(max_amount, "max_amount")
    min_abs_amount = _validated_amount(min_abs_amount, "min_abs_amount")
    max_abs_amount = _validated_amount(max_abs_amount, "max_abs_amount")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise ValueError("max_amount: The maximum amount must be at least the minimum")
    if min_abs_amount is not None or max_abs_amount is not None:
        if currency is None:
            raise ValueError("currency: Choose a currency before filtering by absolute amount")
        if min_abs_amount is not None and min_abs_amount < 0:
            raise ValueError("min_abs_amount: Enter a nonnegative amount")
        if max_abs_amount is not None and max_abs_amount < 0:
            raise ValueError("max_abs_amount: Enter a nonnegative amount")
        if min_abs_amount is not None and max_abs_amount is not None and min_abs_amount > max_abs_amount:
            raise ValueError("max_abs_amount: The maximum amount must be at least the minimum")

    effective_date = func.coalesce(Transaction.transaction_datetime, Transaction.posting_datetime)
    filters = []
    if card_id is not None:
        filters.append(Transaction.card_id == card_id)
    if account_id is not None:
        filters.append(Transaction.card_id.in_(select(Card.id).where(Card.account_id == account_id)))
    if date_from is not None:
        filters.append(effective_date >= date_from)
    if date_to is not None:
        filters.append(effective_date <= date_to)
    if q is not None and q.strip():
        # Escape the escape character first: % and _ are literal description text.
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Transaction.description.ilike(f"%{term}%", escape="\\"))
    if kind is not None:
        filters.append(Transaction.transaction_kind == kind)
    if currency is not None:
        filters.append(Transaction.currency == currency)
    if direction == "out":
        filters.append(Transaction.amount < 0)
    elif direction == "in":
        filters.append(Transaction.amount > 0)
    if min_amount is not None:
        filters.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        filters.append(Transaction.amount <= max_amount)
    if min_abs_amount is not None:
        filters.append(func.abs(Transaction.amount) >= min_abs_amount)
    if max_abs_amount is not None:
        filters.append(func.abs(Transaction.amount) <= max_abs_amount)

    total = await db.scalar(select(func.count(Transaction.id)).where(*filters))
    result = await db.execute(
        select(Transaction)
        .where(*filters)
        .options(selectinload(Transaction.card).selectinload(Card.account))
        .order_by(effective_date.desc().nullslast(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def update_transaction(
    db: AsyncSession, transaction_id: int, transaction_data: TransactionUpdate
) -> Transaction | None:
    """Commit explicit changes, preserving omitted fields and unchanged legacy FX."""
    transaction = await get_transaction(db, transaction_id)
    if transaction is None:
        return None
    update_data = transaction_data.model_dump(exclude_unset=True)
    clearing_original_pair = (
        "original_amount" in update_data and "original_currency" in update_data
        and update_data["original_amount"] is None
        and update_data["original_currency"] is None
    )
    if clearing_original_pair:
        update_data["fx_rate"] = None
    # Resubmitting identical values does not ask to repair an incomplete legacy group.
    changed_fields = {field for field, value in update_data.items() if getattr(transaction, field) != value}
    if changed_fields & {"amount", "currency", "original_amount", "original_currency", "fx_rate"}:
        original_amount = update_data.get("original_amount", transaction.original_amount)
        original_currency = update_data.get("original_currency", transaction.original_currency)
        fx_rate = update_data.get("fx_rate", transaction.fx_rate)
        try:
            normalize_currency(update_data.get("currency", transaction.currency))
        except ValueError as exc:
            raise ValueError(f"currency: {exc}") from exc
        _validated_amount(update_data.get("amount", transaction.amount), "amount")
        validate_original_values(original_amount, original_currency, fx_rate)
        # Stored values in a changed group must also meet current input rules.
        _validated_amount(original_amount, "original_amount")
        if original_currency is not None:
            try:
                normalized = normalize_currency(original_currency)
            except ValueError as exc:
                raise ValueError(f"original_currency: {exc}") from exc
            if normalized != original_currency:
                update_data["original_currency"] = normalized
        if fx_rate is not None:
            try:
                _rate_adapter.validate_python(fx_rate)
            except ValidationError as exc:
                raise ValueError("fx_rate: Enter a positive rate with up to 9 integer and 6 fractional digits") from exc

    for field, value in update_data.items():
        setattr(transaction, field, value)
    if update_data:
        await _refresh_fingerprint(db, transaction)
        await db.commit()
    return await get_transaction(db, transaction_id)


async def delete_transaction(db: AsyncSession, transaction_id: int) -> bool:
    """Atomically remove the record and only its links, keeping all sources/files."""
    transaction = await get_transaction(db, transaction_id)
    if transaction is None:
        return False
    await db.execute(
        delete(TransactionSourceLink).where(TransactionSourceLink.transaction_id == transaction_id)
    )
    # Bulk deletion avoids loading every link through the ORM cascade.
    await db.execute(delete(Transaction).where(Transaction.id == transaction_id))
    await db.commit()
    return True


async def get_source_counts(db: AsyncSession, transaction_ids: list[int]) -> dict[int, int]:
    """Count links in batches, including zero for records without a source."""
    identifiers = list(dict.fromkeys(transaction_ids))
    counts = dict.fromkeys(identifiers, 0)
    for start in range(0, len(identifiers), REFERENCE_BATCH_SIZE):
        rows = await db.execute(
            select(TransactionSourceLink.transaction_id, func.count())
            .where(TransactionSourceLink.transaction_id.in_(identifiers[start:start + REFERENCE_BATCH_SIZE]))
            .group_by(TransactionSourceLink.transaction_id)
        )
        counts.update({transaction_id: count for transaction_id, count in rows})
    return counts


async def get_transaction_observations_page(
    db: AsyncSession, transaction_id: int, limit: int = 20, offset: int = 0
) -> tuple[list[TransactionSourceLink], int]:
    """Return bounded observation links and their total."""
    _validate_page(limit, offset)
    total = await db.scalar(
        select(func.count()).select_from(TransactionSourceLink)
        .where(TransactionSourceLink.transaction_id == transaction_id)
    )
    links = await get_transaction_observations(db, transaction_id, limit=limit, offset=offset)
    return links, total


async def get_transaction_observations(
    db: AsyncSession, transaction_id: int, limit: int = 100, offset: int = 0
) -> list[TransactionSourceLink]:
    """Retrieve links with the observation and safe payload summary eagerly loaded."""
    _validate_page(limit, offset)
    result = await db.execute(
        select(TransactionSourceLink)
        .join(
            TransactionObservation,
            TransactionObservation.id == TransactionSourceLink.observation_id,
        )
        .join(SourcePayload, SourcePayload.id == TransactionObservation.source_payload_id)
        .where(TransactionSourceLink.transaction_id == transaction_id)
        .options(
            selectinload(TransactionSourceLink.observation).selectinload(
                TransactionObservation.payload
            )
        )
        .order_by(
            SourcePayload.received_at.desc(),
            TransactionObservation.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_transaction_references(db: AsyncSession) -> dict:
    """Read every selector option in bounded, stable batches without lazy I/O."""
    accounts = []
    cards = []
    last_id = 0
    while True:
        rows = (await db.execute(
            select(Account.id, Account.institution, Account.name)
            .where(Account.id > last_id).order_by(Account.id).limit(REFERENCE_BATCH_SIZE)
        )).all()
        accounts.extend({"id": row.id, "label": f"{row.institution} · {row.name}"} for row in rows)
        if len(rows) < REFERENCE_BATCH_SIZE:
            break
        last_id = rows[-1].id
    last_id = 0
    while True:
        rows = (await db.execute(
            select(Card.id, Card.account_id, Card.name, Card.card_masked_number, Account.account_currency)
            .join(Account, Account.id == Card.account_id)
            .where(Card.id > last_id).order_by(Card.id).limit(REFERENCE_BATCH_SIZE)
        )).all()
        cards.extend({
            "id": row.id, "account_id": row.account_id, "currency": row.account_currency,
            "label": f"{row.name} · {row.card_masked_number}",
        } for row in rows)
        if len(rows) < REFERENCE_BATCH_SIZE:
            break
        last_id = rows[-1].id
    saved_codes = union(
        select(Transaction.currency.label("code")),
        select(Transaction.original_currency.label("code")),
        select(Account.account_currency.label("code")),
    ).subquery()
    currencies = set()
    offset = 0
    while True:
        codes = list((await db.scalars(
            select(saved_codes.c.code).where(saved_codes.c.code.isnot(None))
            .order_by(saved_codes.c.code).limit(REFERENCE_BATCH_SIZE).offset(offset)
        )).all())
        for code in codes:
            try:
                currencies.add(normalize_currency(code))
            except ValueError:
                continue
        if len(codes) < REFERENCE_BATCH_SIZE:
            break
        offset += REFERENCE_BATCH_SIZE
    return {"accounts": accounts, "cards": cards, "currencies": sorted(currencies)}
