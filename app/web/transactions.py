"""Web routes for transaction pages (UI)"""
from datetime import datetime, timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from decimal import Decimal

from app.database import get_db
from app.core.deps import get_current_user_from_cookie_required
from app.models.user import User
from app.models.account import Account
from app.models.card import Card
from app.models.transaction import Transaction
from app.models.source_event import SourceEvent
from app.models.transaction_source_link import TransactionSourceLink
from app.services import transaction_service, account_service

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")

# Common currencies for dropdowns
COMMON_CURRENCIES = ["AED", "USD", "EUR", "GBP", "SAR", "INR", "PKR", "PHP"]


def format_number(value):
    """Format number with thousand separators."""
    if value is None:
        return "0"
    return f"{value:,.2f}"


def format_currency(value, currency="AED"):
    """Format currency value."""
    if value is None:
        return f"0.00 {currency}"
    return f"{value:,.2f} {currency}"


# Register template filters
templates.env.filters["format_number"] = format_number
templates.env.filters["format_currency"] = format_currency


async def get_accounts_with_cards(db: AsyncSession, user_id: int) -> list[dict]:
    """Get all accounts with their cards for dropdowns."""
    result = await db.execute(
        select(Account)
        .order_by(Account.institution, Account.name)
    )
    accounts = result.scalars().all()
    
    # Get cards for each account
    accounts_data = []
    for account in accounts:
        cards_result = await db.execute(
            select(Card)
            .where(Card.account_id == account.id)
            .order_by(Card.name)
        )
        cards = cards_result.scalars().all()
        accounts_data.append({
            "account": account,
            "cards": cards
        })
    
    return accounts_data


async def get_all_cards(db: AsyncSession) -> list[Card]:
    """Get all cards with account info."""
    result = await db.execute(
        select(Card)
        .order_by(Card.name)
    )
    cards = result.scalars().all()
    return cards


@router.get("/transactions", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    # Filters
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    period_preset: str | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    direction: str | None = Query(None),
    min_amount: Decimal | None = Query(None),
    max_amount: Decimal | None = Query(None),
    currency: str | None = Query(None),
    # Pagination
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    # Sorting
    sort: str = Query("date"),
    sort_dir: str = Query("desc"),
    # HTMX partials
    partial: str | None = Query(None),
    reset: bool = Query(False),
):
    """
    Render transactions list page.
    
    HTMX partials:
    - partial=table: Return only table rows
    - partial=cards: Return only card layout
    - partial=filters: Return filter form
    """
    # Handle reset
    if reset:
        account_id = card_id = date_from = date_to = None
        q = kind = direction = None
        min_amount = max_amount = currency = None
        period_preset = "month"
    
    # Handle period presets
    today = datetime.now().date()
    if period_preset == "today":
        date_from = today.isoformat()
        date_to = today.isoformat()
    elif period_preset == "week":
        week_start = today - timedelta(days=today.weekday())
        date_from = week_start.isoformat()
        date_to = today.isoformat()
    elif period_preset == "month":
        month_start = today.replace(day=1)
        date_from = month_start.isoformat()
        date_to = today.isoformat()
    
    # Parse dates
    date_from_dt = datetime.fromisoformat(date_from) if date_from else None
    date_to_dt = datetime.fromisoformat(date_to) if date_to else None
    
    # Handle direction filter
    if direction == "out":
        if min_amount is None:
            min_amount = Decimal("-999999999")
        max_amount = Decimal("-0.01") if max_amount is None or max_amount > 0 else max_amount
    elif direction == "in":
        min_amount = Decimal("0.01") if min_amount is None or min_amount < 0 else min_amount
    
    # Get transactions
    transactions, total = await transaction_service.get_transactions(
        db=db,
        account_id=account_id,
        card_id=card_id,
        date_from=date_from_dt,
        date_to=date_to_dt,
        q=q,
        kind=kind,
        min_amount=min_amount,
        max_amount=max_amount,
        limit=limit,
        offset=offset
    )
    
    # Get accounts and cards for filters
    accounts = await account_service.get_accounts(db)
    cards = []
    if account_id:
        cards = await account_service.get_account_cards(db, account_id)
    else:
        cards = await get_all_cards(db)
    
    # Calculate summary
    summary = None
    if transactions:
        outflow = sum(float(tx.amount) for tx in transactions if tx.amount < 0)
        inflow = sum(float(tx.amount) for tx in transactions if tx.amount > 0)
        # Get most common currency
        currencies = [tx.currency for tx in transactions]
        summary = {
            "outflow": abs(outflow),
            "inflow": inflow,
            "currency": max(set(currencies), key=currencies.count) if currencies else "AED"
        }
    
    # Build template context
    context = {
        "request": request,
        "user": user,
        "transactions": transactions,
        "total": total,
        "limit": limit,
        "offset": offset,
        "accounts": accounts,
        "cards": cards,
        "currencies": COMMON_CURRENCIES,
        "filters": {
            "account_id": account_id,
            "card_id": card_id,
            "date_from": date_from,
            "date_to": date_to,
            "q": q,
            "kind": kind,
            "direction": direction,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "currency": currency,
            "sort": sort,
            "sort_dir": sort_dir,
        },
        "period_preset": period_preset or "month",
        "summary": summary,
    }
    
    # Handle HTMX partials
    if partial == "table":
        return templates.TemplateResponse(
            "transactions/partials/_transaction_table.html",
            context
        )
    elif partial == "cards":
        return templates.TemplateResponse(
            "transactions/partials/_transaction_cards.html",
            context
        )
    elif partial == "filters":
        return templates.TemplateResponse(
            "transactions/partials/_filters.html",
            context
        )
    
    # Full page render
    return templates.TemplateResponse(
        "transactions/list.html",
        context
    )


@router.get("/transactions/{transaction_id}", response_class=HTMLResponse)
async def transaction_details(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    partial: str | None = Query(None),
):
    """
    Render transaction details page.
    
    HTMX partials:
    - partial=sources: Return only sources list
    """
    # Get transaction with relationships
    transaction = await transaction_service.get_transaction(db, transaction_id)
    if not transaction:
        # Return 404 page or redirect
        return templates.TemplateResponse(
            "partials/_alert.html",
            {"request": request, "kind": "error", "text": "Transaction not found"},
            status_code=404
        )
    
    # Get source links
    source_links = await transaction_service.get_transaction_sources(db, transaction_id)
    
    # Get all cards for dropdown
    cards = await get_all_cards(db)
    
    context = {
        "request": request,
        "user": user,
        "transaction": transaction,
        "source_links": source_links,
        "cards": cards,
        "currencies": COMMON_CURRENCIES,
    }
    
    # Handle HTMX partials
    if partial == "sources":
        return templates.TemplateResponse(
            "transactions/partials/_source_list.html",
            context
        )
    
    return templates.TemplateResponse(
        "transactions/details.html",
        context
    )


@router.get("/transactions/{transaction_id}/sources", response_class=HTMLResponse)
async def transaction_sources_partial(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get sources list as HTML partial for HTMX updates."""
    source_links = await transaction_service.get_transaction_sources(db, transaction_id)
    transaction = await transaction_service.get_transaction(db, transaction_id)
    
    return templates.TemplateResponse(
        "transactions/partials/_source_list.html",
        {
            "request": request,
            "user": user,
            "source_links": source_links,
            "transaction": transaction,
        }
    )
