"""Web routes for Transactions UI (Jinja2 + HTMX)"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated

from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_from_cookie_required
from app.database import get_db
from app.models.user import User
from app.schemas.transaction import TransactionUpdate
from app.services import (
    account_service,
    card_service,
    transaction_service,
    source_event_service,
)

router = APIRouter(tags=["web-transactions"])
templates = Jinja2Templates(directory="app/templates")

TRANSACTION_KINDS = [
    {"value": "purchase", "label": "Purchase"},
    {"value": "topup", "label": "Top-up"},
    {"value": "refund", "label": "Refund"},
    {"value": "other", "label": "Other"},
]

CURRENCIES = ["AED", "USD", "EUR", "GBP"]


def _parse_datetime(val: str | None) -> datetime | None:
    if not val or not val.strip():
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(val.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_decimal(val: str | None) -> Decimal | None:
    if val is None or val == "" or not str(val).strip():
        return None
    try:
        return Decimal(str(val).strip())
    except Exception:
        return None


def _period_dates(period: str | None) -> tuple[datetime | None, datetime | None]:
    """Return (date_from, date_to) for period preset."""
    now = datetime.utcnow()
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if period == "week":
        start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if period == "month":
        start = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    return None, None


def _primary_date(tx) -> tuple[datetime | None, str]:
    """Return (primary_date, badge) per spec: P=posting, T=transaction, C=created."""
    if tx.posting_datetime:
        return tx.posting_datetime, "P"
    if tx.transaction_datetime:
        return tx.transaction_datetime, "T"
    return tx.created_at, "C"


@router.get("/transactions", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    period: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    direction: str | None = Query(None),
    min_amount: str | None = Query(None),
    max_amount: str | None = Query(None),
    currency: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=100),
):
    """Transactions list page or HTMX results partial."""
    df, dt = _period_dates(period) if period else (date_from, date_to)
    min_a = _parse_decimal(min_amount) if min_amount else None
    max_a = _parse_decimal(max_amount) if max_amount else None
    direction_val = direction if direction and direction != "all" else None

    accounts = await account_service.get_accounts(db)
    cards = []
    if account_id:
        cards = await card_service.get_cards_by_account(db, account_id)

    offset = (page - 1) * per_page
    transactions, total = await transaction_service.get_transactions(
        db=db,
        account_id=account_id,
        card_id=card_id,
        date_from=df,
        date_to=dt,
        q=q,
        kind=kind,
        direction=direction_val,
        currency=currency,
        min_amount=min_a,
        max_amount=max_a,
        limit=per_page,
        offset=offset,
        load_source_count=True,
    )
    out_total, in_total = await transaction_service.get_transactions_summary(
        db=db,
        account_id=account_id,
        card_id=card_id,
        date_from=df,
        date_to=dt,
        q=q,
        kind=kind,
        direction=direction_val,
        currency=currency,
        min_amount=min_a,
        max_amount=max_a,
    )

    _params = {
        k: v
        for k, v in [
            ("account_id", account_id),
            ("card_id", card_id),
            ("period", period),
            ("date_from", df.strftime("%Y-%m-%d") if df else None),
            ("date_to", dt.strftime("%Y-%m-%d") if dt else None),
            ("q", q),
            ("kind", kind),
            ("direction", direction or "all"),
            ("min_amount", min_amount),
            ("max_amount", max_amount),
            ("currency", currency),
        ]
        if v is not None and v != ""
    }
    pagination_params = ("&" + urlencode(_params)) if _params else ""

    ctx = {
        "request": request,
        "user": user,
        "accounts": accounts,
        "cards": cards,
        "transactions": transactions,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pagination_params": pagination_params,
        "out_total": out_total,
        "in_total": in_total,
        "filters": {
            "account_id": account_id,
            "card_id": card_id,
            "period": period,
            "date_from": df,
            "date_to": dt,
            "q": q,
            "kind": kind,
            "direction": direction or "all",
            "min_amount": min_amount,
            "max_amount": max_amount,
            "currency": currency,
        },
        "kinds": TRANSACTION_KINDS,
        "currencies": CURRENCIES,
        "primary_date": _primary_date,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "transactions/partials/_results_table.html", ctx
        )
    return templates.TemplateResponse("transactions/list.html", ctx)


@router.get("/transactions/card-options", response_class=HTMLResponse)
async def card_options(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    account_id: int = Query(...),
    selected_id: int | None = Query(None),
):
    """HTMX: Card select options for given account."""
    cards = await card_service.get_cards_by_account(db, account_id)
    return templates.TemplateResponse(
        "transactions/partials/_card_options.html",
        {
            "request": request,
            "cards": cards,
            "selected_id": selected_id,
        },
    )


@router.get("/transactions/{transaction_id}", response_class=HTMLResponse)
async def transaction_details(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Transaction details page."""
    transaction = await transaction_service.get_transaction(
        db, transaction_id, load_relations=True
    )
    if not transaction:
        return templates.TemplateResponse(
            "transactions/partials/_error.html",
            {"request": request, "message": "Transaction not found"},
            status_code=404,
        )

    accounts = await account_service.get_accounts(db)
    cards = await card_service.get_cards_by_account(db, transaction.card.account_id)

    ctx = {
        "request": request,
        "user": user,
        "transaction": transaction,
        "accounts": accounts,
        "cards": cards,
        "kinds": TRANSACTION_KINDS,
        "currencies": CURRENCIES,
    }
    return templates.TemplateResponse("transactions/details.html", ctx)


@router.patch("/transactions/{transaction_id}", response_class=HTMLResponse)
async def transaction_update(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    card_id: int = Form(...),
    amount: str = Form(...),
    currency: str = Form(...),
    transaction_datetime: str | None = Form(None),
    posting_datetime: str | None = Form(None),
    description: str = Form(...),
    location: str | None = Form(None),
    transaction_kind: str = Form("purchase"),
    original_amount: str | None = Form(None),
    original_currency: str | None = Form(None),
    fx_rate: str | None = Form(None),
    fx_fee: str | None = Form(None),
):
    """Update transaction (HTMX form submit)."""
    transaction = await transaction_service.get_transaction(
        db, transaction_id, load_relations=True
    )
    if not transaction:
        return templates.TemplateResponse(
            "transactions/partials/_error.html",
            {"request": request, "message": "Transaction not found"},
            status_code=404,
        )

    try:
        update_data = TransactionUpdate(
            card_id=card_id,
            amount=Decimal(amount),
            currency=currency.strip().upper()[:3],
            transaction_datetime=_parse_datetime(transaction_datetime),
            posting_datetime=_parse_datetime(posting_datetime),
            description=description.strip(),
            location=location.strip() if location else None,
            transaction_kind=transaction_kind,
            original_amount=_parse_decimal(original_amount),
            original_currency=original_currency.strip().upper()[:3] if original_currency else None,
            fx_rate=_parse_decimal(fx_rate),
            fx_fee=_parse_decimal(fx_fee),
        )
    except Exception as e:
        return templates.TemplateResponse(
            "transactions/partials/_error.html",
            {"request": request, "message": str(e)},
            status_code=400,
        )

    updated = await transaction_service.update_transaction(
        db, transaction_id, update_data
    )
    if not updated:
        return templates.TemplateResponse(
            "transactions/partials/_error.html",
            {"request": request, "message": "Update failed"},
            status_code=404,
        )

    await db.refresh(updated)
    transaction = await transaction_service.get_transaction(
        db, transaction_id, load_relations=True
    )
    accounts = await account_service.get_accounts(db)
    cards = await card_service.get_cards_by_account(db, transaction.card.account_id)

    ctx = {
        "request": request,
        "user": user,
        "transaction": transaction,
        "accounts": accounts,
        "cards": cards,
        "kinds": TRANSACTION_KINDS,
        "currencies": CURRENCIES,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "transactions/partials/_details_canonical.html", ctx
        )
    return RedirectResponse(
        url=f"/transactions/{transaction_id}", status_code=303
    )


@router.get("/transactions/{transaction_id}/sources", response_class=HTMLResponse)
async def transaction_sources_partial(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """HTMX: Sources list partial."""
    transaction = await transaction_service.get_transaction(
        db, transaction_id, load_relations=True
    )
    if not transaction:
        return templates.TemplateResponse(
            "transactions/partials/_error.html",
            {"request": request, "message": "Transaction not found"},
            status_code=404,
        )
    return templates.TemplateResponse(
        "transactions/partials/_details_sources.html",
        {
            "request": request,
            "transaction": transaction,
        },
    )


@router.post(
    "/transactions/{transaction_id}/sources/{source_event_id}/reprocess",
    response_class=HTMLResponse,
)
async def reprocess_source(
    request: Request,
    transaction_id: int,
    source_event_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """HTMX: Reprocess source, return sources partial."""
    try:
        await source_event_service.reprocess_source_event(db, source_event_id)
    except ValueError:
        return templates.TemplateResponse(
            "transactions/partials/_error.html",
            {"request": request, "message": "Source not found or reprocess failed"},
            status_code=404,
        )
    transaction = await transaction_service.get_transaction(
        db, transaction_id, load_relations=True
    )
    return templates.TemplateResponse(
        "transactions/partials/_details_sources.html",
        {"request": request, "transaction": transaction},
    )


@router.post(
    "/transactions/{transaction_id}/sources/{source_event_id}/set-primary",
    response_class=HTMLResponse,
)
async def set_primary_source(
    request: Request,
    transaction_id: int,
    source_event_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """HTMX: Set source as primary, return sources partial."""
    link = await transaction_service.set_primary_source(
        db, transaction_id, source_event_id
    )
    if not link:
        return templates.TemplateResponse(
            "transactions/partials/_error.html",
            {"request": request, "message": "Source not found"},
            status_code=404,
        )
    transaction = await transaction_service.get_transaction(
        db, transaction_id, load_relations=True
    )
    return templates.TemplateResponse(
        "transactions/partials/_details_sources.html",
        {"request": request, "transaction": transaction},
    )
