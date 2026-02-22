"""Web routes for Transactions UI (HTMX + Jinja2)"""
import math
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_from_cookie_required
from app.database import get_db
from app.models.user import User
from app.schemas.transaction import TransactionUpdate
from app.services import account_service, card_service, source_event_service, transaction_service

router = APIRouter(prefix="/transactions", tags=["web-transactions"])
templates = Jinja2Templates(directory="app/templates")

DEFAULT_PER_PAGE = 50


def _parse_date(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_decimal(value: str | None) -> Decimal | None:
    if not value or not value.strip():
        return None
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        return None


def _is_htmx(request: Request) -> bool:
    return bool(request.headers.get("HX-Request"))


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def list_transactions(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    direction: str | None = Query(None),
    min_amount: str | None = Query(None),
    max_amount: str | None = Query(None),
    currency: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(DEFAULT_PER_PAGE, ge=1, le=200),
):
    offset = (page - 1) * per_page

    transactions, total, total_out, total_in = await transaction_service.get_transactions_for_web(
        db=db,
        account_id=account_id,
        card_id=card_id,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
        q=q,
        kind=kind,
        direction=direction,
        min_amount=_parse_decimal(min_amount),
        max_amount=_parse_decimal(max_amount),
        currency=currency,
        limit=per_page,
        offset=offset,
    )

    total_pages = max(1, math.ceil(total / per_page))
    accounts = await account_service.get_accounts(db)
    cards = await card_service.get_all_cards(db)

    filters = {
        "account_id": account_id,
        "card_id": card_id,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "q": q or "",
        "kind": kind or "",
        "direction": direction or "all",
        "min_amount": min_amount or "",
        "max_amount": max_amount or "",
        "currency": currency or "",
    }

    ctx = {
        "request": request,
        "user": user,
        "transactions": transactions,
        "total": total,
        "total_out": total_out,
        "total_in": total_in,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "accounts": accounts,
        "cards": cards,
        "filters": filters,
    }

    if _is_htmx(request):
        return templates.TemplateResponse(
            "transactions/partials/_transactions_results.html", ctx
        )
    return templates.TemplateResponse("transactions/list.html", ctx)


@router.get("/cards-for-account", response_class=HTMLResponse)
async def cards_for_account(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    account_id: int | None = Query(None),
):
    """Return <option> elements for the card dropdown (HTMX cascade)."""
    cards = await card_service.get_cards_by_account(db, account_id) if account_id else []
    return templates.TemplateResponse(
        "transactions/partials/_card_options.html",
        {"request": request, "cards": cards},
    )


# ---------------------------------------------------------------------------
# Details
# ---------------------------------------------------------------------------

@router.get("/{transaction_id}", response_class=HTMLResponse)
async def transaction_details(
    request: Request,
    transaction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
):
    transaction = await transaction_service.get_transaction_with_relations(db, transaction_id)
    if not transaction:
        return templates.TemplateResponse(
            "transactions/partials/_not_found.html",
            {"request": request, "user": user},
            status_code=404,
        )

    cards = await card_service.get_all_cards(db)
    sources = transaction.source_links

    return templates.TemplateResponse(
        "transactions/details.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "sources": sources,
            "cards": cards,
            "save_success": request.query_params.get("saved") == "1",
            "save_error": None,
        },
    )


# ---------------------------------------------------------------------------
# Edit (canonical form)
# ---------------------------------------------------------------------------

@router.patch("/{transaction_id}", response_class=HTMLResponse)
async def update_transaction_web(
    request: Request,
    transaction_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    card_id: int = Form(...),
    amount: str = Form(...),
    currency: str = Form(...),
    transaction_kind: str = Form(...),
    description: str = Form(...),
    transaction_datetime: str | None = Form(None),
    posting_datetime: str | None = Form(None),
    location: str | None = Form(None),
    original_amount: str | None = Form(None),
    original_currency: str | None = Form(None),
    fx_rate: str | None = Form(None),
    fx_fee: str | None = Form(None),
):
    error: str | None = None
    try:
        update_data = TransactionUpdate(
            card_id=card_id,
            amount=Decimal(amount),
            currency=currency.strip().upper(),
            transaction_kind=transaction_kind,
            description=description,
            transaction_datetime=_parse_date(transaction_datetime),
            posting_datetime=_parse_date(posting_datetime),
            location=location if location and location.strip() else None,
            original_amount=_parse_decimal(original_amount),
            original_currency=original_currency.strip().upper() if original_currency and original_currency.strip() else None,
            fx_rate=_parse_decimal(fx_rate),
            fx_fee=_parse_decimal(fx_fee),
        )
        result = await transaction_service.update_transaction(db, transaction_id, update_data)
        if not result:
            error = "Transaction not found."
    except Exception as exc:
        error = str(exc)

    if error:
        transaction = await transaction_service.get_transaction_with_relations(db, transaction_id)
        cards = await card_service.get_all_cards(db)
        return templates.TemplateResponse(
            "transactions/partials/_canonical_form.html",
            {
                "request": request,
                "user": user,
                "transaction": transaction,
                "cards": cards,
                "sources": transaction.source_links if transaction else [],
                "save_error": error,
                "save_success": False,
            },
            status_code=422,
        )

    response = HTMLResponse("")
    response.headers["HX-Redirect"] = f"/transactions/{transaction_id}?saved=1"
    return response


# ---------------------------------------------------------------------------
# Source actions
# ---------------------------------------------------------------------------

@router.post("/{transaction_id}/sources/{source_event_id}/set-primary", response_class=HTMLResponse)
async def set_primary_source_web(
    request: Request,
    transaction_id: int,
    source_event_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
):
    await transaction_service.set_primary_source(db, transaction_id, source_event_id)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = f"/transactions/{transaction_id}"
    return response


@router.post("/{transaction_id}/sources/{source_event_id}/reprocess", response_class=HTMLResponse)
async def reprocess_source_web(
    request: Request,
    transaction_id: int,
    source_event_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
):
    try:
        await source_event_service.reprocess_source_event(db, source_event_id)
    except Exception:
        pass
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = f"/transactions/{transaction_id}"
    return response
