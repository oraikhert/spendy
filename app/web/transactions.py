"""Transactions web pages routes"""
from typing import Annotated
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.deps import get_current_user_from_cookie_required
from app.models.user import User
from app.services import transaction_service, account_service

router = APIRouter(prefix="/transactions", tags=["web-transactions"])


@router.get("", response_class=HTMLResponse)
async def transactions_list(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    min_amount: float | None = Query(None),
    max_amount: float | None = Query(None),
    direction: str | None = Query(None, pattern="^(out|in)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Display transactions list page with filters."""
    # Get accounts for filter dropdown
    accounts = await account_service.get_accounts(db)
    
    # Get cards if account selected
    cards = []
    if account_id:
        cards = await account_service.get_cards_by_account(db, account_id)
    
    # Parse date filters
    from datetime import datetime
    date_from_dt = None
    date_to_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to)
        except ValueError:
            pass
    
    # Apply direction filter (outflow = negative, inflow = positive)
    if direction == "out":
        max_amount = -0.01 if max_amount is None else -0.01
    elif direction == "in":
        min_amount = 0.01 if min_amount is None else 0.01
    
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
    
    # Calculate totals for summary
    total_out = sum(t.amount for t in transactions if t.amount < 0)
    total_in = sum(t.amount for t in transactions if t.amount > 0)
    
    # Get source counts for each transaction
    for t in transactions:
        t.source_count = len(t.source_links) if t.source_links else 0
    
    # Calculate pagination
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    current_page = (offset // limit) + 1
    
    return request.app.state.templates.TemplateResponse(
        "transactions/list.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "cards": cards,
            "transactions": transactions,
            "total": total,
            "total_out": total_out,
            "total_in": total_in,
            "filters": {
                "account_id": account_id,
                "card_id": card_id,
                "date_from": date_from,
                "date_to": date_to,
                "q": q,
                "kind": kind,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "direction": direction,
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "total_pages": total_pages,
                "current_page": current_page,
            }
        }
    )


@router.get("/partials/transactions", response_class=HTMLResponse)
async def transactions_partial(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    min_amount: float | None = Query(None),
    max_amount: float | None = Query(None),
    direction: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """HTMX partial for transactions table rows."""
    from datetime import datetime
    
    date_from_dt = None
    date_to_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to)
        except ValueError:
            pass
    
    if direction == "out":
        max_amount = -0.01 if max_amount is None else -0.01
    elif direction == "in":
        min_amount = 0.01 if min_amount is None else 0.01
    
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
    
    for t in transactions:
        t.source_count = len(t.source_links) if t.source_links else 0
    
    return request.app.state.templates.TemplateResponse(
        "transactions/_transaction_rows.html",
        {
            "request": request,
            "transactions": transactions,
        }
    )


@router.get("/partials/pagination", response_class=HTMLResponse)
async def transactions_pagination_partial(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
    account_id: int | None = Query(None),
    card_id: int | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    q: str | None = Query(None),
    kind: str | None = Query(None),
    min_amount: float | None = Query(None),
    max_amount: float | None = Query(None),
    direction: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """HTMX partial for pagination controls."""
    from datetime import datetime
    
    date_from_dt = None
    date_to_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to)
        except ValueError:
            pass
    
    if direction == "out":
        max_amount = -0.01 if max_amount is None else -0.01
    elif direction == "in":
        min_amount = 0.01 if min_amount is None else 0.01
    
    _, total = await transaction_service.get_transactions(
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
    
    total_pages = (total + limit - 1) // limit if total > 0 else 1
    current_page = (offset // limit) + 1
    
    # Build query string for pagination links
    params = []
    if account_id:
        params.append(f"account_id={account_id}")
    if card_id:
        params.append(f"card_id={card_id}")
    if date_from:
        params.append(f"date_from={date_from}")
    if date_to:
        params.append(f"date_to={date_to}")
    if q:
        params.append(f"q={q}")
    if kind:
        params.append(f"kind={kind}")
    if min_amount:
        params.append(f"min_amount={min_amount}")
    if max_amount:
        params.append(f"max_amount={max_amount}")
    if direction:
        params.append(f"direction={direction}")
    params.append(f"limit={limit}")
    
    query_string = "&".join(params)
    
    return request.app.state.templates.TemplateResponse(
        "transactions/_pagination.html",
        {
            "request": request,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "total_pages": total_pages,
                "current_page": current_page,
            },
            "query_string": query_string,
            "filters": {
                "account_id": account_id,
                "card_id": card_id,
                "date_from": date_from,
                "date_to": date_to,
                "q": q,
                "kind": kind,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "direction": direction,
            }
        }
    )


@router.get("/{transaction_id}", response_class=HTMLResponse)
async def transaction_details(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Display transaction details page."""
    # Get transaction
    transaction = await transaction_service.get_transaction(db, transaction_id)
    if not transaction:
        return request.app.state.templates.TemplateResponse(
            "partials/_error.html",
            {"request": request, "error": "Transaction not found"},
            status_code=404
        )
    
    # Get sources
    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    
    # Get accounts for dropdown
    accounts = await account_service.get_accounts(db)
    
    # Get all cards
    all_cards = []
    for account in accounts:
        cards = await account_service.get_cards_by_account(db, account.id)
        all_cards.extend(cards)
    
    # Get source count
    source_count = len(sources)
    
    # Find primary source
    primary_source = None
    for link in sources:
        if link.is_primary:
            primary_source = link.source_event
            break
    
    return request.app.state.templates.TemplateResponse(
        "transactions/details.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "sources": sources,
            "primary_source": primary_source,
            "source_count": source_count,
            "accounts": accounts,
            "cards": all_cards,
        }
    )


@router.patch("/{transaction_id}", response_class=HTMLResponse)
async def update_transaction(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update transaction via HTMX."""
    from fastapi import Form
    from app.schemas.transaction import TransactionUpdate
    from datetime import datetime
    
    # Parse form data
    form_data = await request.form()
    
    # Build update data
    update_data = {}
    
    if form_data.get("card_id"):
        update_data["card_id"] = int(form_data["card_id"])
    
    if form_data.get("amount"):
        update_data["amount"] = float(form_data["amount"])
    
    if form_data.get("currency"):
        update_data["currency"] = form_data["currency"]
    
    if form_data.get("transaction_datetime"):
        try:
            update_data["transaction_datetime"] = datetime.fromisoformat(
                form_data["transaction_datetime"].replace(" ", "T")
            )
        except ValueError:
            pass
    
    if form_data.get("posting_datetime"):
        try:
            update_data["posting_datetime"] = datetime.fromisoformat(
                form_data["posting_datetime"].replace(" ", "T")
            )
        except ValueError:
            pass
    
    if form_data.get("description"):
        update_data["description"] = form_data["description"]
    
    if form_data.get("location"):
        update_data["location"] = form_data["location"]
    
    if form_data.get("transaction_kind"):
        update_data["transaction_kind"] = form_data["transaction_kind"]
    
    # FX fields
    if form_data.get("original_amount"):
        update_data["original_amount"] = float(form_data["original_amount"])
    
    if form_data.get("original_currency"):
        update_data["original_currency"] = form_data["original_currency"]
    
    if form_data.get("fx_rate"):
        update_data["fx_rate"] = float(form_data["fx_rate"])
    
    if form_data.get("fx_fee"):
        update_data["fx_fee"] = float(form_data["fx_fee"])
    
    # Perform update
    transaction_update = TransactionUpdate(**update_data)
    transaction = await transaction_service.update_transaction(
        db, transaction_id, transaction_update
    )
    
    if not transaction:
        return request.app.state.templates.TemplateResponse(
            "partials/_error.html",
            {"request": request, "error": "Transaction not found"},
            status_code=404
        )
    
    # Get updated sources
    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    
    # Get accounts and cards for dropdown
    accounts = await account_service.get_accounts(db)
    all_cards = []
    for account in accounts:
        cards = await account_service.get_cards_by_account(db, account.id)
        all_cards.extend(cards)
    
    # Return updated form
    return request.app.state.templates.TemplateResponse(
        "transactions/_transaction_form.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "sources": sources,
            "source_count": len(sources),
            "accounts": accounts,
            "cards": all_cards,
            "success": True,
        }
    )


@router.get("/{transaction_id}/partials/form", response_class=HTMLResponse)
async def transaction_form_partial(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get transaction form as partial for HTMX."""
    transaction = await transaction_service.get_transaction(db, transaction_id)
    if not transaction:
        return request.app.state.templates.TemplateResponse(
            "partials/_error.html",
            {"request": request, "error": "Transaction not found"},
            status_code=404
        )
    
    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    accounts = await account_service.get_accounts(db)
    all_cards = []
    for account in accounts:
        cards = await account_service.get_cards_by_account(db, account.id)
        all_cards.extend(cards)
    
    return request.app.state.templates.TemplateResponse(
        "transactions/_transaction_form.html",
        {
            "request": request,
            "user": user,
            "transaction": transaction,
            "sources": sources,
            "source_count": len(sources),
            "accounts": accounts,
            "cards": all_cards,
        }
    )


@router.get("/{transaction_id}/sources", response_class=HTMLResponse)
async def transaction_sources_partial(
    request: Request,
    transaction_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get transaction sources as partial for HTMX."""
    transaction = await transaction_service.get_transaction(db, transaction_id)
    if not transaction:
        return request.app.state.templates.TemplateResponse(
            "partials/_error.html",
            {"request": request, "error": "Transaction not found"},
            status_code=404
        )
    
    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    
    return request.app.state.templates.TemplateResponse(
        "transactions/_sources_list.html",
        {
            "request": request,
            "transaction": transaction,
            "sources": sources,
            "source_count": len(sources),
        }
    )


@router.patch("/{transaction_id}/sources/{source_event_id}", response_class=HTMLResponse)
async def update_source_link(
    request: Request,
    transaction_id: int,
    source_event_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie_required)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update source link (set primary, etc.) via HTMX."""
    from app.schemas.source_event import TransactionSourceLinkUpdate
    
    form_data = await request.form()
    is_primary = form_data.get("is_primary") == "true"
    
    link_update = TransactionSourceLinkUpdate(is_primary=is_primary)
    
    # Update the link - this would need to be implemented in the service
    # For now, we'll just reload and render
    
    sources = await transaction_service.get_transaction_sources(db, transaction_id)
    
    return request.app.state.templates.TemplateResponse(
        "transactions/_sources_list.html",
        {
            "request": request,
            "transaction_id": transaction_id,
            "sources": sources,
            "source_count": len(sources),
        }
    )
