"""Web transactions routes for Jinja2 + HTMX screens."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from pathlib import Path
import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user_from_cookie_required
from app.database import get_db
from app.models.card import Card
from app.models.user import User
from app.schemas.transaction import TransactionUpdate
from app.services import account_service, card_service, transaction_service

router = APIRouter(tags=["web-transactions"])
templates = Jinja2Templates(directory="app/templates")

TRANSACTION_KINDS = ["purchase", "topup", "refund", "other"]
DIRECTIONS = ["all", "out", "in"]
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _parse_status_badge(parse_status: str | None) -> tuple[str, str]:
    status_value = (parse_status or "new").lower()
    if status_value == "parsed":
        return "Parsed", "badge-success"
    if status_value == "failed":
        return "Failed", "badge-error"
    return status_value.capitalize(), "badge-warning"


def _primary_date_info(transaction) -> tuple[datetime, str, str]:
    if transaction.posting_datetime:
        return transaction.posting_datetime, "P", "Posting"
    if transaction.transaction_datetime:
        return transaction.transaction_datetime, "T", "Transaction"
    return transaction.created_at, "C", "Created"


def _fmt_datetime(value: datetime | None, with_time: bool = True) -> str:
    if not value:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


def _fmt_datetime_local_input(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%Y-%m-%dT%H:%M")


def _fmt_amount(value: Decimal | None) -> str:
    amount = Decimal(value or 0)
    sign = "+" if amount > 0 else ""
    return f"{sign}{amount:,.2f}"


def _to_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def _to_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _resolve_period(
    preset: str,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date | None, date | None]:
    today = date.today()
    if preset == "today":
        return today, today
    if preset == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end
    if preset == "month":
        start = today.replace(day=1)
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(days=1)
        return start, end
    return date_from, date_to


def _dates_to_bounds(date_from: date | None, date_to: date | None) -> tuple[datetime | None, datetime | None]:
    from_dt = datetime.combine(date_from, time.min) if date_from else None
    to_dt = datetime.combine(date_to, time.max) if date_to else None
    return from_dt, to_dt


def _build_transaction_query_url(filters: dict, offset: int) -> str:
    params: dict[str, str] = {
        "preset": filters["preset"],
        "limit": str(filters["limit"]),
        "offset": str(offset),
    }
    if filters.get("account_id"):
        params["account_id"] = str(filters["account_id"])
    if filters.get("card_id"):
        params["card_id"] = str(filters["card_id"])
    if filters.get("date_from"):
        params["date_from"] = str(filters["date_from"])
    if filters.get("date_to"):
        params["date_to"] = str(filters["date_to"])
    if filters.get("q"):
        params["q"] = str(filters["q"])
    if filters.get("kind"):
        params["kind"] = str(filters["kind"])
    if filters.get("direction") and filters["direction"] != "all":
        params["direction"] = str(filters["direction"])
    if filters.get("min_amount") is not None:
        params["min_amount"] = str(filters["min_amount"])
    if filters.get("max_amount") is not None:
        params["max_amount"] = str(filters["max_amount"])
    if filters.get("currency"):
        params["currency"] = str(filters["currency"])
    return f"/transactions?{urlencode(params)}"


def _build_pagination(total: int, limit: int, offset: int, filters: dict) -> dict:
    if total <= 0:
        return {
            "total": 0,
            "limit": limit,
            "offset": offset,
            "show": False,
            "pages": [],
            "prev_url": None,
            "next_url": None,
        }

    total_pages = max(1, ceil(total / limit))
    current_page = (offset // limit) + 1
    start = max(1, current_page - 2)
    end = min(total_pages, current_page + 2)

    pages = []
    for page in range(start, end + 1):
        page_offset = (page - 1) * limit
        pages.append(
            {
                "page": page,
                "active": page == current_page,
                "url": _build_transaction_query_url(filters, page_offset),
            }
        )

    prev_url = _build_transaction_query_url(filters, max(0, offset - limit)) if current_page > 1 else None
    next_url = _build_transaction_query_url(filters, offset + limit) if current_page < total_pages else None

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "show": total > limit,
        "pages": pages,
        "prev_url": prev_url,
        "next_url": next_url,
    }


def _build_transaction_item_view(transaction, source_meta: dict[str, int | str | None]) -> dict:
    primary_date, date_badge, date_badge_title = _primary_date_info(transaction)
    parse_status_label, parse_status_class = _parse_status_badge(source_meta.get("primary_parse_status"))
    amount_value = Decimal(transaction.amount)

    card_label = f"Card #{transaction.card_id}"
    if transaction.card:
        card_label = f"{transaction.card.name} - {transaction.card.card_masked_number}"

    return {
        "id": transaction.id,
        "primary_date": _fmt_datetime(primary_date, with_time=False),
        "primary_date_title": _fmt_datetime(primary_date, with_time=True),
        "date_badge": date_badge,
        "date_badge_title": date_badge_title,
        "description": transaction.description,
        "location": transaction.location,
        "card_label": card_label,
        "kind": transaction.transaction_kind,
        "amount": _fmt_amount(amount_value),
        "amount_class": "text-error" if amount_value < 0 else "text-success",
        "currency": transaction.currency,
        "source_count": int(source_meta.get("source_count") or 0),
        "parse_status_label": parse_status_label,
        "parse_status_class": parse_status_class,
        "details_url": f"/transactions/{transaction.id}",
    }


async def _load_filter_reference_data(db: AsyncSession, account_id: int | None) -> tuple[list, list, list[str]]:
    accounts = await account_service.get_accounts(db)
    cards = await card_service.get_cards_by_account(db, account_id) if account_id else []

    txn_currencies = await transaction_service.get_transaction_currencies(db)
    account_currencies = sorted({account.account_currency.upper() for account in accounts if account.account_currency})
    currencies = sorted(set(account_currencies + txn_currencies))
    return accounts, cards, currencies


async def _load_cards_for_details(db: AsyncSession) -> list[Card]:
    query = select(Card).options(selectinload(Card.account)).order_by(Card.name.asc(), Card.id.asc())
    result = await db.execute(query)
    return list(result.scalars().all())


def _build_canonical_form_values(transaction) -> dict[str, str]:
    return {
        "card_id": str(transaction.card_id),
        "transaction_kind": transaction.transaction_kind,
        "amount": f"{Decimal(transaction.amount):.2f}",
        "currency": transaction.currency,
        "transaction_datetime": _fmt_datetime_local_input(transaction.transaction_datetime),
        "posting_datetime": _fmt_datetime_local_input(transaction.posting_datetime),
        "description": transaction.description,
        "location": transaction.location or "",
        "original_amount": f"{Decimal(transaction.original_amount):.2f}" if transaction.original_amount is not None else "",
        "original_currency": transaction.original_currency or "",
        "fx_rate": str(transaction.fx_rate) if transaction.fx_rate is not None else "",
        "fx_fee": f"{Decimal(transaction.fx_fee):.2f}" if transaction.fx_fee is not None else "",
    }


def _build_card_options(cards: list[Card]) -> list[dict[str, str]]:
    options = []
    for card in cards:
        account_label = ""
        if card.account:
            account_label = f" ({card.account.institution} - {card.account.name})"
        options.append(
            {
                "id": str(card.id),
                "label": f"{card.name} - {card.card_masked_number}{account_label}",
            }
        )
    return options


def _normalize_currency(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    return normalized


def _build_source_view(link) -> dict:
    source = link.source_event
    parse_status_label, parse_status_class = _parse_status_badge(source.parse_status if source else None)
    preview = ""
    if source:
        if source.raw_text:
            preview = source.raw_text[:160] + ("..." if len(source.raw_text) > 160 else "")
        elif source.file_path:
            preview = Path(source.file_path).name

    parsed_items = []
    if source:
        parsed_items = [
            ("Amount", str(source.parsed_amount) if source.parsed_amount is not None else "-"),
            ("Currency", source.parsed_currency or "-"),
            ("Transaction datetime", _fmt_datetime(source.parsed_transaction_datetime)),
            ("Posting datetime", _fmt_datetime(source.parsed_posting_datetime)),
            ("Description", source.parsed_description or "-"),
            ("Card last 4", source.parsed_card_number or "-"),
            ("Kind", source.parsed_transaction_kind or "-"),
            ("Location", source.parsed_location or "-"),
            ("Sender", source.sender or "-"),
            ("Recipients", source.recipients or "-"),
        ]

    return {
        "source_event_id": link.source_event_id,
        "source_type": source.source_type if source else "unknown",
        "created_at": _fmt_datetime(source.created_at if source else None),
        "is_primary": bool(link.is_primary),
        "confidence": f"{float(link.match_confidence):.2f}" if link.match_confidence is not None else "-",
        "parse_status_label": parse_status_label,
        "parse_status_class": parse_status_class,
        "parse_error": source.parse_error if source else None,
        "preview": preview,
        "raw_text": source.raw_text if source else None,
        "file_name": Path(source.file_path).name if source and source.file_path else None,
        "file_download_url": f"/api/v1/source-events/{source.id}/download" if source and source.file_path else None,
        "parsed_items": parsed_items,
    }


@router.get("/transactions", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    user: User = Depends(get_current_user_from_cookie_required),
    db: AsyncSession = Depends(get_db),
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    preset: str = Query("month"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    direction: str = Query("all"),
    min_amount: Decimal | None = Query(None),
    max_amount: Decimal | None = Query(None),
    currency: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    fragment: str | None = Query(None),
    scope: str = Query("desktop"),
):
    preset = preset.lower() if preset else "month"
    if preset not in {"today", "week", "month", "custom"}:
        preset = "month"

    direction = direction.lower() if direction else "all"
    if direction not in DIRECTIONS:
        direction = "all"

    kind = kind if kind in TRANSACTION_KINDS else None
    currency = _normalize_currency(currency)

    resolved_date_from, resolved_date_to = _resolve_period(preset, date_from, date_to)
    from_dt, to_dt = _dates_to_bounds(resolved_date_from, resolved_date_to)

    filters = {
        "account_id": account_id,
        "card_id": card_id,
        "preset": preset,
        "date_from": resolved_date_from.isoformat() if resolved_date_from else "",
        "date_to": resolved_date_to.isoformat() if resolved_date_to else "",
        "q": q or "",
        "kind": kind or "",
        "direction": direction,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "currency": currency or "",
        "limit": limit,
        "offset": offset,
    }

    accounts, cards, currencies = await _load_filter_reference_data(db, account_id)
    if account_id and card_id and not any(card.id == card_id for card in cards):
        card_id = None
        filters["card_id"] = None

    scope_value = scope if scope in {"desktop", "mobile"} else "desktop"
    panel_id = f"{scope_value}-filters-panel"
    form_id = f"{scope_value}-filters-form"

    if fragment == "filters":
        return templates.TemplateResponse(
            "transactions/partials/_filters.html",
            {
                "request": request,
                "filters": filters,
                "accounts": accounts,
                "cards": cards,
                "currencies": currencies,
                "kinds": TRANSACTION_KINDS,
                "panel_id": panel_id,
                "form_id": form_id,
                "scope": scope_value,
            },
        )

    validation_error = None
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        validation_error = "Minimum amount cannot exceed maximum amount."

    items = []
    total = 0
    outflow_sum = Decimal("0")
    inflow_sum = Decimal("0")

    if not validation_error:
        try:
            transactions, total, outflow_sum, inflow_sum, source_meta = await transaction_service.get_transactions_for_ui(
                db=db,
                account_id=account_id,
                card_id=card_id,
                date_from=from_dt,
                date_to=to_dt,
                q=q,
                kind=kind,
                direction=direction,
                min_amount=min_amount,
                max_amount=max_amount,
                currency=currency,
                limit=limit,
                offset=offset,
            )
            items = [
                _build_transaction_item_view(
                    transaction,
                    source_meta.get(transaction.id, {"source_count": 0, "primary_parse_status": None}),
                )
                for transaction in transactions
            ]
        except Exception:
            validation_error = "Unable to load transactions. Please try again."

    summary = {
        "count": total,
        "outflow": _fmt_amount(outflow_sum),
        "inflow": _fmt_amount(inflow_sum),
        "currency": currency or "",
    }
    pagination = _build_pagination(total, limit, offset, filters)

    results_context = {
        "request": request,
        "items": items,
        "summary": summary,
        "pagination": pagination,
        "filters": filters,
        "error_message": validation_error,
    }

    if _is_htmx(request):
        return templates.TemplateResponse("transactions/partials/_results.html", results_context)

    return templates.TemplateResponse(
        "transactions/list.html",
        {
            "request": request,
            "user": user,
            "filters": filters,
            "accounts": accounts,
            "cards": cards,
            "currencies": currencies,
            "kinds": TRANSACTION_KINDS,
            "items": items,
            "summary": summary,
            "pagination": pagination,
            "error_message": validation_error,
        },
    )


@router.get("/transactions/{transaction_id}", response_class=HTMLResponse)
async def transaction_details(
    transaction_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie_required),
    db: AsyncSession = Depends(get_db),
):
    transaction = await transaction_service.get_transaction_with_relations(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    cards = await _load_cards_for_details(db)
    currencies = sorted(
        set(
            [currency.upper() for currency in await transaction_service.get_transaction_currencies(db)]
            + [transaction.currency.upper()]
            + ([transaction.original_currency.upper()] if transaction.original_currency else [])
        )
    )

    source_meta = await transaction_service.get_transaction_source_metadata(db, [transaction.id])
    source_info = source_meta.get(transaction.id, {"source_count": 0, "primary_parse_status": None})
    parse_status_label, parse_status_class = _parse_status_badge(source_info.get("primary_parse_status"))

    amount_value = Decimal(transaction.amount)
    card_label = f"Card #{transaction.card_id}"
    account_label = "-"
    if transaction.card:
        card_label = f"{transaction.card.name} - {transaction.card.card_masked_number}"
        if transaction.card.account:
            account_label = f"{transaction.card.account.institution} - {transaction.card.account.name}"

    return templates.TemplateResponse(
        "transactions/details.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "transaction_summary": {
                "amount": _fmt_amount(amount_value),
                "amount_class": "text-error" if amount_value < 0 else "text-success",
                "currency": transaction.currency,
                "kind": transaction.transaction_kind,
                "card": card_label,
                "account": account_label,
                "description": transaction.description,
                "transaction_datetime": _fmt_datetime(transaction.transaction_datetime),
                "posting_datetime": _fmt_datetime(transaction.posting_datetime),
                "source_count": int(source_info.get("source_count") or 0),
                "parse_status_label": parse_status_label,
                "parse_status_class": parse_status_class,
            },
            "form_values": _build_canonical_form_values(transaction),
            "card_options": _build_card_options(cards),
            "currency_options": currencies,
            "kinds": TRANSACTION_KINDS,
            "form_errors": [],
            "form_success": None,
        },
    )


@router.patch("/transactions/{transaction_id}", response_class=HTMLResponse)
async def transaction_update(
    transaction_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie_required),
    db: AsyncSession = Depends(get_db),
):
    transaction = await transaction_service.get_transaction_with_relations(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    cards = await _load_cards_for_details(db)
    card_options = _build_card_options(cards)
    currencies = sorted(
        set(
            [currency.upper() for currency in await transaction_service.get_transaction_currencies(db)]
            + [transaction.currency.upper()]
            + [card.account.account_currency.upper() for card in cards if card.account and card.account.account_currency]
        )
    )

    form = await request.form()
    raw_values = {k: (str(v).strip() if v is not None else "") for k, v in form.items()}

    form_values = {
        "card_id": raw_values.get("card_id", ""),
        "transaction_kind": raw_values.get("transaction_kind", ""),
        "amount": raw_values.get("amount", ""),
        "currency": raw_values.get("currency", ""),
        "transaction_datetime": raw_values.get("transaction_datetime", ""),
        "posting_datetime": raw_values.get("posting_datetime", ""),
        "description": raw_values.get("description", ""),
        "location": raw_values.get("location", ""),
        "original_amount": raw_values.get("original_amount", ""),
        "original_currency": raw_values.get("original_currency", ""),
        "fx_rate": raw_values.get("fx_rate", ""),
        "fx_fee": raw_values.get("fx_fee", ""),
    }

    form_errors: list[str] = []

    card_id = _to_int(form_values["card_id"])
    if card_id is None:
        form_errors.append("Card is required.")

    transaction_kind = form_values["transaction_kind"]
    if transaction_kind not in TRANSACTION_KINDS:
        form_errors.append("Transaction kind is required.")

    amount = _to_decimal(form_values["amount"])
    if amount is None:
        form_errors.append("Amount is required and must be a valid number.")
    elif amount == 0:
        form_errors.append("Amount cannot be zero.")

    currency_value = _normalize_currency(form_values["currency"])
    form_values["currency"] = currency_value or ""
    if not currency_value or not CURRENCY_RE.match(currency_value):
        form_errors.append("Currency must be a 3-letter uppercase code.")

    description = form_values["description"].strip()
    if not description:
        form_errors.append("Description is required.")
    form_values["description"] = description

    location = form_values["location"].strip() or None

    transaction_datetime = _to_datetime(form_values["transaction_datetime"])
    if form_values["transaction_datetime"] and transaction_datetime is None:
        form_errors.append("Transaction datetime must be valid.")

    posting_datetime = _to_datetime(form_values["posting_datetime"])
    if form_values["posting_datetime"] and posting_datetime is None:
        form_errors.append("Posting datetime must be valid.")

    if transaction_datetime and posting_datetime and posting_datetime < transaction_datetime:
        form_errors.append("Posting datetime must be greater than or equal to transaction datetime.")

    original_amount = _to_decimal(form_values["original_amount"])
    original_currency = _normalize_currency(form_values["original_currency"])
    form_values["original_currency"] = original_currency or ""

    if (original_amount is None) != (original_currency is None):
        form_errors.append("Original amount and original currency must be provided together.")
    if original_currency and not CURRENCY_RE.match(original_currency):
        form_errors.append("Original currency must be a 3-letter uppercase code.")

    fx_rate = _to_decimal(form_values["fx_rate"])
    if form_values["fx_rate"] and fx_rate is None:
        form_errors.append("FX rate must be a valid number.")

    fx_fee = _to_decimal(form_values["fx_fee"])
    if form_values["fx_fee"] and fx_fee is None:
        form_errors.append("FX fee must be a valid number.")

    if form_errors:
        return templates.TemplateResponse(
            "transactions/partials/_canonical_form.html",
            {
                "request": request,
                "transaction": transaction,
                "form_values": form_values,
                "card_options": card_options,
                "currency_options": currencies,
                "kinds": TRANSACTION_KINDS,
                "form_errors": form_errors,
                "form_success": None,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    update_payload = TransactionUpdate(
        card_id=card_id,
        amount=amount,
        currency=currency_value,
        transaction_datetime=transaction_datetime,
        posting_datetime=posting_datetime,
        description=description,
        location=location,
        transaction_kind=transaction_kind,
        original_amount=original_amount,
        original_currency=original_currency,
        fx_rate=fx_rate,
        fx_fee=fx_fee,
    )

    updated = await transaction_service.update_transaction(db, transaction_id, update_payload)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    updated_transaction = await transaction_service.get_transaction_with_relations(db, transaction_id)
    if not updated_transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    return templates.TemplateResponse(
        "transactions/partials/_canonical_form.html",
        {
            "request": request,
            "transaction": updated_transaction,
            "form_values": _build_canonical_form_values(updated_transaction),
            "card_options": card_options,
            "currency_options": currencies,
            "kinds": TRANSACTION_KINDS,
            "form_errors": [],
            "form_success": "Transaction updated successfully.",
        },
    )


@router.get("/transactions/{transaction_id}/sources", response_class=HTMLResponse)
async def transaction_sources(
    transaction_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie_required),
    db: AsyncSession = Depends(get_db),
):
    transaction = await transaction_service.get_transaction_with_relations(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")

    links = await transaction_service.get_transaction_sources(db, transaction_id)
    source_items = [_build_source_view(link) for link in links]

    return templates.TemplateResponse(
        "transactions/partials/_sources_list.html",
        {
            "request": request,
            "transaction": transaction,
            "source_items": source_items,
        },
    )
