"""Web transaction routes (Jinja2 + HTMX)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_from_cookie_required
from app.database import get_db
from app.models.source_event import SourceEvent
from app.models.transaction_source_link import TransactionSourceLink
from app.models.user import User
from app.schemas.transaction import TransactionUpdate
from app.services import account_service, card_service, source_event_service, transaction_service

router = APIRouter(tags=["web-transactions"])
templates = Jinja2Templates(directory="app/templates")


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _parse_int(value: str | None) -> int | None:
    value = _empty_to_none(value)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    value = _empty_to_none(value)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _normalize_datetime_local(value: str | None) -> datetime | None:
    value = _empty_to_none(value)
    if not value:
        return None
    return datetime.fromisoformat(value)


def _compute_period_dates(
    period: str | None,
    custom_from: date | None,
    custom_to: date | None,
) -> tuple[date | None, date | None]:
    today = date.today()
    if period == "today":
        return today, today
    if period == "week":
        week_start = today - timedelta(days=today.weekday())
        return week_start, today
    if period == "month":
        month_start = today.replace(day=1)
        return month_start, today
    if period == "custom":
        return custom_from, custom_to
    return custom_from, custom_to


def _date_to_datetime_range(
    date_from: date | None,
    date_to: date | None,
) -> tuple[datetime | None, datetime | None]:
    dt_from = datetime.combine(date_from, time.min) if date_from else None
    dt_to = datetime.combine(date_to, time.max) if date_to else None
    return dt_from, dt_to


async def _load_source_meta(
    db: AsyncSession,
    transaction_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not transaction_ids:
        return {}

    counts_result = await db.execute(
        select(
            TransactionSourceLink.transaction_id,
            func.count(TransactionSourceLink.source_event_id),
        )
        .where(TransactionSourceLink.transaction_id.in_(transaction_ids))
        .group_by(TransactionSourceLink.transaction_id)
    )
    count_map = {
        tx_id: int(count)
        for tx_id, count in counts_result.all()
    }

    status_result = await db.execute(
        select(
            TransactionSourceLink.transaction_id,
            TransactionSourceLink.is_primary,
            SourceEvent.parse_status,
            SourceEvent.created_at,
        )
        .join(
            SourceEvent,
            SourceEvent.id == TransactionSourceLink.source_event_id
        )
        .where(TransactionSourceLink.transaction_id.in_(transaction_ids))
    )
    status_rows = list(status_result.all())

    status_map: dict[int, str | None] = {}
    for tx_id in transaction_ids:
        rows = [row for row in status_rows if row[0] == tx_id]
        rows.sort(key=lambda row: (row[1], row[3]), reverse=True)
        status_map[tx_id] = rows[0][2] if rows else None

    return {
        tx_id: {
            "source_count": count_map.get(tx_id, 0),
            "parse_status": status_map.get(tx_id),
        }
        for tx_id in transaction_ids
    }


async def _build_list_context(
    request: Request,
    db: AsyncSession,
    user: User,
    account_id: int | None,
    card_id: int | None,
    period: str | None,
    date_from: date | None,
    date_to: date | None,
    q: str | None,
    kind: str | None,
    direction: str,
    min_amount: Decimal | None,
    max_amount: Decimal | None,
    currency: str | None,
    limit: int,
    offset: int,
    error_message: str | None = None,
) -> dict[str, Any]:
    applied_date_from, applied_date_to = _compute_period_dates(period, date_from, date_to)
    if applied_date_from and applied_date_to and applied_date_from > applied_date_to:
        error_message = "Date range is invalid. Start date must be before end date."
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        error_message = "Amount range is invalid. Minimum amount must be less than or equal to maximum."

    dir_min = min_amount
    dir_max = max_amount
    if direction == "out":
        cap = Decimal("-0.01")
        dir_max = cap if dir_max is None else min(dir_max, cap)
    elif direction == "in":
        floor = Decimal("0.01")
        dir_min = floor if dir_min is None else max(dir_min, floor)

    if dir_min is not None and dir_max is not None and dir_min > dir_max:
        error_message = "No values match the selected direction and amount range."

    dt_from, dt_to = _date_to_datetime_range(applied_date_from, applied_date_to)

    transactions: list[Any] = []
    total = 0
    if error_message is None:
        transactions, total = await transaction_service.get_transactions(
            db=db,
            account_id=account_id,
            card_id=card_id,
            date_from=dt_from,
            date_to=dt_to,
            q=q,
            kind=kind,
            currency=(currency.upper() if currency else None),
            min_amount=dir_min,
            max_amount=dir_max,
            limit=limit,
            offset=offset,
        )

    all_accounts = await account_service.get_accounts(db)
    all_cards: list[Any] = []
    for account in all_accounts:
        all_cards.extend(await card_service.get_cards_by_account(db, account.id))

    filtered_cards = [
        card for card in all_cards
        if account_id is None or card.account_id == account_id
    ]

    card_map = {card.id: card for card in all_cards}
    account_map = {account.id: account for account in all_accounts}

    tx_ids = [tx.id for tx in transactions]
    source_meta = await _load_source_meta(db, tx_ids)

    inflow_total = sum(
        tx.amount for tx in transactions if tx.amount > 0
    ) if transactions else Decimal("0")
    outflow_total = sum(
        tx.amount for tx in transactions if tx.amount < 0
    ) if transactions else Decimal("0")

    page = (offset // limit) + 1 if limit else 1
    has_prev = offset > 0
    has_next = offset + limit < total

    return {
        "request": request,
        "user": user,
        "transactions": transactions,
        "total": total,
        "limit": limit,
        "offset": offset,
        "page": page,
        "has_prev": has_prev,
        "has_next": has_next,
        "prev_offset": max(offset - limit, 0),
        "next_offset": offset + limit,
        "accounts": all_accounts,
        "cards": filtered_cards,
        "card_map": card_map,
        "account_map": account_map,
        "source_meta": source_meta,
        "summary": {
            "count": total,
            "inflow_total": inflow_total,
            "outflow_total": outflow_total,
        },
        "filters": {
            "account_id": account_id,
            "card_id": card_id,
            "period": period or "month",
            "date_from": applied_date_from.isoformat() if applied_date_from else "",
            "date_to": applied_date_to.isoformat() if applied_date_to else "",
            "q": q or "",
            "kind": kind or "",
            "direction": direction,
            "min_amount": str(min_amount) if min_amount is not None else "",
            "max_amount": str(max_amount) if max_amount is not None else "",
            "currency": (currency or "").upper(),
        },
        "error_message": error_message,
    }


async def _render_sources_list(
    request: Request,
    db: AsyncSession,
    user: User,
    transaction_id: int,
    message_kind: str | None = None,
    message_text: str | None = None,
) -> HTMLResponse:
    transaction = await transaction_service.get_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    source_links = await transaction_service.get_transaction_sources(db, transaction_id)
    source_links.sort(
        key=lambda link: (
            link.is_primary,
            link.source_event.created_at if link.source_event else datetime.min
        ),
        reverse=True,
    )
    return templates.TemplateResponse(
        "transactions/_sources_list.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "source_links": source_links,
            "message_kind": message_kind,
            "message_text": message_text,
        },
    )


@router.get("/transactions", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    account_id: str | None = Query(None),
    card_id: str | None = Query(None),
    period: str | None = Query("month", pattern="^(today|week|month|custom)$"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    direction: str = Query("all", pattern="^(all|out|in)$"),
    min_amount: str | None = Query(None),
    max_amount: str | None = Query(None),
    currency: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    parsed_account_id = _parse_int(account_id)
    parsed_card_id = _parse_int(card_id)
    parsed_date_from = _parse_date(date_from)
    parsed_date_to = _parse_date(date_to)
    parsed_min_amount = _parse_decimal(min_amount)
    parsed_max_amount = _parse_decimal(max_amount)
    normalized_kind = _empty_to_none(kind)
    if normalized_kind not in {None, "purchase", "topup", "refund", "other"}:
        normalized_kind = None

    context = await _build_list_context(
        request=request,
        db=db,
        user=user,
        account_id=parsed_account_id,
        card_id=parsed_card_id,
        period=period,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
        q=q,
        kind=normalized_kind,
        direction=direction,
        min_amount=parsed_min_amount,
        max_amount=parsed_max_amount,
        currency=currency,
        limit=limit,
        offset=offset,
    )
    if _is_htmx(request):
        return templates.TemplateResponse("transactions/_results.html", context)
    return templates.TemplateResponse("transactions/list.html", context)


@router.get("/transactions/cards-options", response_class=HTMLResponse)
async def transaction_cards_options(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    account_id: str | None = Query(None),
    selected_card_id: str | None = Query(None),
):
    parsed_account_id = _parse_int(account_id)
    parsed_selected_card_id = _parse_int(selected_card_id)
    cards: list[Any] = []
    if parsed_account_id:
        cards = await card_service.get_cards_by_account(db, parsed_account_id)
    return templates.TemplateResponse(
        "transactions/_card_options.html",
        {
            "request": request,
            "user": user,
            "cards": cards,
            "selected_card_id": parsed_selected_card_id,
        },
    )


@router.get("/transactions/{transaction_id}", response_class=HTMLResponse)
async def transaction_details(
    transaction_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
):
    transaction = await transaction_service.get_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    accounts = await account_service.get_accounts(db)
    cards: list[Any] = []
    for account in accounts:
        cards.extend(await card_service.get_cards_by_account(db, account.id))
    card_map = {card.id: card for card in cards}
    account_map = {account.id: account for account in accounts}

    source_links = await transaction_service.get_transaction_sources(db, transaction_id)
    source_links.sort(
        key=lambda link: (
            link.is_primary,
            link.source_event.created_at if link.source_event else datetime.min
        ),
        reverse=True,
    )

    context = {
        "request": request,
        "user": user,
        "transaction": transaction,
        "cards": cards,
        "card_map": card_map,
        "account_map": account_map,
        "source_links": source_links,
        "message_kind": None,
        "message_text": None,
    }
    return templates.TemplateResponse("transactions/details.html", context)


@router.patch("/transactions/{transaction_id}", response_class=HTMLResponse)
async def transaction_details_patch(
    transaction_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    card_id: int | None = Form(None),
    amount: str | None = Form(None),
    currency: str | None = Form(None),
    transaction_datetime: str | None = Form(None),
    posting_datetime: str | None = Form(None),
    description: str | None = Form(None),
    location: str | None = Form(None),
    transaction_kind: str | None = Form(None),
    original_amount: str | None = Form(None),
    original_currency: str | None = Form(None),
    fx_rate: str | None = Form(None),
    fx_fee: str | None = Form(None),
):
    transaction = await transaction_service.get_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    accounts = await account_service.get_accounts(db)
    cards: list[Any] = []
    for account in accounts:
        cards.extend(await card_service.get_cards_by_account(db, account.id))

    parsed_amount = _parse_decimal(amount)
    parsed_original_amount = _parse_decimal(original_amount)
    parsed_fx_rate = _parse_decimal(fx_rate)
    parsed_fx_fee = _parse_decimal(fx_fee)
    parsed_currency = (_empty_to_none(currency) or "").upper() or None
    parsed_original_currency = (_empty_to_none(original_currency) or "").upper() or None
    parsed_description = _empty_to_none(description)
    parsed_location = _empty_to_none(location)
    parsed_transaction_kind = _empty_to_none(transaction_kind)

    try:
        parsed_txn_dt = _normalize_datetime_local(transaction_datetime)
        parsed_post_dt = _normalize_datetime_local(posting_datetime)
    except ValueError:
        return templates.TemplateResponse(
            "transactions/_details_form.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "cards": cards,
                "message_kind": "error",
                "message_text": "Invalid datetime format.",
            },
        )

    if parsed_amount is None or parsed_amount == Decimal("0"):
        return templates.TemplateResponse(
            "transactions/_details_form.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "cards": cards,
                "message_kind": "error",
                "message_text": "Amount is required and must be non-zero.",
            },
        )

    if not parsed_currency or len(parsed_currency) != 3:
        return templates.TemplateResponse(
            "transactions/_details_form.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "cards": cards,
                "message_kind": "error",
                "message_text": "Currency must be a 3-letter code.",
            },
        )

    if (parsed_original_amount is None) != (parsed_original_currency is None):
        return templates.TemplateResponse(
            "transactions/_details_form.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "cards": cards,
                "message_kind": "error",
                "message_text": "Original amount and original currency must be set together.",
            },
        )

    if parsed_txn_dt and parsed_post_dt and parsed_post_dt < parsed_txn_dt:
        return templates.TemplateResponse(
            "transactions/_details_form.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "cards": cards,
                "message_kind": "error",
                "message_text": "Posting datetime must be later than or equal to transaction datetime.",
            },
        )

    payload = {
        "card_id": card_id,
        "amount": parsed_amount,
        "currency": parsed_currency,
        "transaction_datetime": parsed_txn_dt,
        "posting_datetime": parsed_post_dt,
        "description": parsed_description,
        "location": parsed_location,
        "transaction_kind": parsed_transaction_kind,
        "original_amount": parsed_original_amount,
        "original_currency": parsed_original_currency,
        "fx_rate": parsed_fx_rate,
        "fx_fee": parsed_fx_fee,
    }
    try:
        update_model = TransactionUpdate(**payload)
    except Exception:
        return templates.TemplateResponse(
            "transactions/_details_form.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "cards": cards,
                "message_kind": "error",
                "message_text": "Validation failed. Please verify required fields.",
            },
        )

    updated_transaction = await transaction_service.update_transaction(
        db, transaction_id, update_model
    )
    if not updated_transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    return templates.TemplateResponse(
        "transactions/_details_form.html",
        {
            "request": request,
            "user": user,
            "transaction": updated_transaction,
            "cards": cards,
            "message_kind": "success",
            "message_text": "Transaction updated.",
        },
    )


@router.get("/transactions/{transaction_id}/sources", response_class=HTMLResponse)
async def transaction_sources_partial(
    transaction_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
):
    return await _render_sources_list(
        request=request,
        db=db,
        user=user,
        transaction_id=transaction_id,
    )


@router.post("/transactions/{transaction_id}/sources/{source_event_id}/set-primary", response_class=HTMLResponse)
async def transaction_set_primary_source(
    transaction_id: int,
    source_event_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
):
    updated = await transaction_service.set_primary_source_link(
        db, transaction_id, source_event_id
    )
    if not updated:
        return await _render_sources_list(
            request=request,
            db=db,
            user=user,
            transaction_id=transaction_id,
            message_kind="error",
            message_text="Unable to set primary source.",
        )

    return await _render_sources_list(
        request=request,
        db=db,
        user=user,
        transaction_id=transaction_id,
        message_kind="success",
        message_text="Primary source updated.",
    )


@router.post("/transactions/{transaction_id}/sources/{source_event_id}/reprocess", response_class=HTMLResponse)
async def transaction_reprocess_source(
    transaction_id: int,
    source_event_id: int,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
):
    source_event = await transaction_service.get_source_event_for_transaction(
        db, transaction_id, source_event_id
    )
    if not source_event:
        return await _render_sources_list(
            request=request,
            db=db,
            user=user,
            transaction_id=transaction_id,
            message_kind="error",
            message_text="Source not linked to this transaction.",
        )

    await source_event_service.reprocess_source_event(db, source_event.id)
    return await _render_sources_list(
        request=request,
        db=db,
        user=user,
        transaction_id=transaction_id,
        message_kind="info",
        message_text="Source reprocessed.",
    )
