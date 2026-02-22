"""Web routes for Transactions UI (Jinja2 + HTMX)."""
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.deps import get_current_user_from_cookie_required
from app.models.user import User
from app.services import transaction_service, account_service, card_service
from app.services import source_event_service
from app.schemas.transaction import TransactionUpdate

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PER_PAGE_DEFAULT = 50
PER_PAGE_MAX = 200


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _resolve_period(period: str | None, date_from: str | None, date_to: str | None):
    """Convert period shortcut to (date_from, date_to) datetimes."""
    today = date.today()
    if period == "today":
        start = datetime.combine(today, datetime.min.time())
        end = datetime.combine(today, datetime.max.time())
        return start, end
    elif period == "week":
        start = datetime.combine(today - timedelta(days=6), datetime.min.time())
        end = datetime.combine(today, datetime.max.time())
        return start, end
    elif period == "month":
        start = datetime.combine(today.replace(day=1), datetime.min.time())
        end = datetime.combine(today, datetime.max.time())
        return start, end
    return _parse_date(date_from), _parse_date(date_to)


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _collect_filter_params(request: Request) -> dict:
    """Extract all filter query params into a dict for service calls."""
    params = request.query_params
    period = params.get("period")
    df, dt = _resolve_period(period, params.get("date_from"), params.get("date_to"))
    direction = params.get("direction")
    if direction not in ("out", "in"):
        direction = None

    return dict(
        account_id=_safe_int(params.get("account_id")),
        card_id=_safe_int(params.get("card_id")),
        date_from=df,
        date_to=dt,
        q=params.get("q") or None,
        kind=params.get("kind") or None,
        direction=direction,
        currency=params.get("currency") or None,
        min_amount=_safe_decimal(params.get("min_amount")),
        max_amount=_safe_decimal(params.get("max_amount")),
    )


def _pagination(request: Request) -> tuple[int, int, int]:
    """Return (page, per_page, offset)."""
    params = request.query_params
    page = max(_safe_int(params.get("page")) or 1, 1)
    per_page = min(max(_safe_int(params.get("per_page")) or PER_PAGE_DEFAULT, 1), PER_PAGE_MAX)
    return page, per_page, (page - 1) * per_page


# ---------- List page ----------

@router.get("", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    fp = _collect_filter_params(request)
    page, per_page, offset = _pagination(request)

    transactions, total = await transaction_service.get_transactions(
        db, **fp, limit=per_page, offset=offset, load_relations=True,
    )
    summary = await transaction_service.get_transactions_summary(db, **fp)
    total_pages = max((total + per_page - 1) // per_page, 1)

    ctx = {
        "request": request,
        "user": user,
        "transactions": transactions,
        "summary": summary,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "filters": fp,
        "period": request.query_params.get("period", ""),
    }

    if _is_htmx(request):
        return templates.TemplateResponse("transactions/partials/_results.html", ctx)

    accounts = await account_service.get_accounts(db)
    cards = []
    if fp["account_id"]:
        cards = await card_service.get_cards_by_account(db, fp["account_id"])

    ctx.update({"accounts": accounts, "cards": cards})
    return templates.TemplateResponse("transactions/list.html", ctx)


# ---------- Filter helpers (HTMX partials) ----------

@router.get("/filter-cards", response_class=HTMLResponse)
async def filter_cards(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    account_id: int | None = Query(None),
):
    cards = []
    if account_id:
        cards = await card_service.get_cards_by_account(db, account_id)
    html = '<option value="">All cards</option>'
    for c in cards:
        html += f'<option value="{c.id}">{c.name} &bull; ****{c.card_masked_number[-4:]}</option>'
    return HTMLResponse(html)


# ---------- Details page ----------

@router.get("/{transaction_id:int}", response_class=HTMLResponse)
async def transaction_detail(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tx = await transaction_service.get_transaction(db, transaction_id, load_relations=True)
    if not tx:
        return templates.TemplateResponse(
            "transactions/details.html",
            {"request": request, "user": user, "tx": None, "error": "Transaction not found"},
            status_code=404,
        )

    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    accounts = await account_service.get_accounts(db)
    cards = await card_service.get_cards_by_account(db, tx.card.account_id)

    return templates.TemplateResponse("transactions/details.html", {
        "request": request,
        "user": user,
        "tx": tx,
        "sources": sources,
        "accounts": accounts,
        "cards": cards,
        "error": None,
    })


# ---------- Update canonical fields (HTMX PATCH) ----------

@router.patch("/{transaction_id:int}", response_class=HTMLResponse)
async def update_transaction(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    form = await request.form()
    update_fields: dict = {}

    for field in (
        "amount", "currency", "description", "location",
        "transaction_kind", "transaction_datetime", "posting_datetime",
        "original_amount", "original_currency", "fx_rate", "fx_fee",
    ):
        val = form.get(field)
        if val is None:
            continue
        val = val.strip() if isinstance(val, str) else val
        if field in ("amount", "original_amount", "fx_rate", "fx_fee"):
            update_fields[field] = Decimal(val) if val else None
        elif field in ("transaction_datetime", "posting_datetime"):
            update_fields[field] = datetime.fromisoformat(val) if val else None
        else:
            update_fields[field] = val if val else None

    card_id_raw = form.get("card_id")
    if card_id_raw:
        update_fields["card_id"] = int(card_id_raw)

    update_data = TransactionUpdate(**{k: v for k, v in update_fields.items() if k != "card_id"})
    tx = await transaction_service.update_transaction(db, transaction_id, update_data)

    if not tx:
        return HTMLResponse('<div class="alert alert-error">Transaction not found</div>', status_code=404)

    tx = await transaction_service.get_transaction(db, transaction_id, load_relations=True)
    cards = await card_service.get_cards_by_account(db, tx.card.account_id)

    return templates.TemplateResponse("transactions/partials/_canonical_form.html", {
        "request": request,
        "tx": tx,
        "cards": cards,
        "save_success": True,
    })


# ---------- Sources partial (HTMX) ----------

@router.get("/{transaction_id:int}/sources", response_class=HTMLResponse)
async def transaction_sources(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    return templates.TemplateResponse("transactions/partials/_sources_list.html", {
        "request": request,
        "sources": sources,
        "transaction_id": transaction_id,
    })


# ---------- Set primary source (HTMX) ----------

@router.patch("/{transaction_id:int}/sources/{source_event_id:int}/primary", response_class=HTMLResponse)
async def set_primary_source(
    request: Request,
    transaction_id: int,
    source_event_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models.transaction_source_link import TransactionSourceLink as TSL
    from sqlalchemy import select, update

    await db.execute(
        update(TSL)
        .where(TSL.transaction_id == transaction_id)
        .values(is_primary=False)
    )
    await db.execute(
        update(TSL)
        .where(TSL.transaction_id == transaction_id, TSL.source_event_id == source_event_id)
        .values(is_primary=True)
    )
    await db.commit()

    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    return templates.TemplateResponse("transactions/partials/_sources_list.html", {
        "request": request,
        "sources": sources,
        "transaction_id": transaction_id,
    })


# ---------- Reprocess source (HTMX) ----------

@router.post("/{transaction_id:int}/sources/{source_event_id:int}/reprocess", response_class=HTMLResponse)
async def reprocess_source(
    request: Request,
    transaction_id: int,
    source_event_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        await source_event_service.reprocess_source_event(db, source_event_id)
    except ValueError as e:
        return HTMLResponse(f'<div class="alert alert-error">{e}</div>')

    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    return templates.TemplateResponse("transactions/partials/_sources_list.html", {
        "request": request,
        "sources": sources,
        "transaction_id": transaction_id,
    })
