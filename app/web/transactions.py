"""Cookie-authenticated transaction pages. Business operations live in services."""
from pathlib import Path
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.routing import APIRoute
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.deps import get_current_user_from_cookie_required
from app.database import get_db
from app.models.user import User
from app.schemas.transaction import TransactionCreate, TransactionUpdate
from app.services import transaction_service, source_event_service
from app.web.transaction_helpers import (
    KINDS, ListFilters, account_label, card_label, csrf_token, detail_url,
    display_date, money, parse_filters, safe_return_url, valid_csrf, validation_errors,
)

class TransactionRoute(APIRoute):
    """Provide recovery even when a lookup or reference query fails before a form."""
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                return await original(request)
            except SQLAlchemyError:
                # get_db closes/rolls back the failed session; never replay a POST.
                return error_page(
                    request, getattr(request.state, "transaction_user", None),
                    "This page could not be loaded. Please retry." if request.method == "GET" else
                    "The change could not be confirmed. Refresh and check the record before trying again.",
                    503, retry_url=current_path(request) if request.method == "GET" else None,
                )
        return handle


router = APIRouter(prefix="/transactions", tags=["web-transactions"], route_class=TransactionRoute)
templates = Jinja2Templates(directory="app/templates")
templates.env.globals.update(money=money, display_date=display_date, kind_label=lambda value: KINDS.get(value, "Other"),
                             account_label=account_label, card_label=card_label, detail_url=detail_url)
DB = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True)
class WebUser:
    """Keep navigation renderable even when a rollback expires ORM objects."""
    username: str


async def web_user(request: Request, user: Annotated[User, Depends(get_current_user_from_cookie_required)]) -> WebUser:
    request.state.transaction_user = WebUser(username=user.username)
    return request.state.transaction_user


ActiveUser = Annotated[WebUser, Depends(web_user)]
UPLOAD_DIR = Path("data/uploads")
FORM_FIELDS = ("card_id", "amount", "currency", "transaction_kind", "description", "transaction_datetime",
               "posting_datetime", "location", "original_amount", "original_currency", "fx_rate")
OPTIONAL_FIELDS = {"transaction_datetime", "posting_datetime", "location", "original_amount", "original_currency", "fx_rate"}


def is_htmx(request):
    return request.headers.get("HX-Request") == "true" and request.headers.get("HX-History-Restore-Request") != "true"


def current_path(request):
    return request.url.path + ("?" + request.url.query if request.url.query else "")


def render(request, user, name, context=None, status=200):
    return templates.TemplateResponse(request=request, name=f"transactions/{name}.html",
                                      context={"user": user, "csrf_token": csrf_token(request), **(context or {})}, status_code=status)


def navigate(request, url):
    if is_htmx(request):
        return Response(headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


def error_page(request, user, message, status=404, back_url="/transactions", retry_url=None):
    return render(request, user, "error", {"title": "Transaction unavailable" if status == 404 else "Unable to continue",
                  "message": message, "back_url": back_url, "retry_url": retry_url}, status)


def file_path_for(source):
    """Resolve symlinks as well as .. before allowing an attachment download."""
    if not source.file_path:
        return None
    try:
        root = UPLOAD_DIR.resolve(strict=True)
        path = Path(source.file_path).resolve(strict=True)
        if path.is_relative_to(root) and path.is_file():
            return path
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def page_number(raw):
    try:
        page = int(raw or "1")
        return max(1, min(page, 1000000000))
    except (ValueError, TypeError):
        return 1


def record_id(raw):
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 10:
        return None
    value = int(raw)
    return value if 0 < value <= 2147483647 else None


@router.get("", response_class=HTMLResponse)
async def transaction_list(request: Request, db: DB, user: ActiveUser):
    values = ListFilters().values()
    values.update(dict(request.query_params))
    errors = {}
    parsed = None
    records, total, counts = [], 0, {}
    try:
        refs = await transaction_service.get_transaction_references(db)
        try:
            parsed = parse_filters(request.query_params.multi_items())
            values = parsed.values()
            records, total = await transaction_service.get_transactions(db, **parsed.service_args(), limit=50, offset=(parsed.page - 1) * 50)
            last_page = max(1, (total + 49) // 50)
            if parsed.page > last_page:
                parsed.page = last_page
                records, total = await transaction_service.get_transactions(db, **parsed.service_args(), limit=50, offset=(parsed.page - 1) * 50)
                if not is_htmx(request):
                    return navigate(request, parsed.url())
            counts = await transaction_service.get_source_counts(db, [record.id for record in records])
            if request.query_params.get("period") == "month" and not is_htmx(request):
                return navigate(request, parsed.url())
        except (ValidationError, ValueError) as exc:
            errors = validation_errors(exc)
        current_page = parsed.page if parsed else 1
        return_url = parsed.url() if parsed and not errors else "/transactions"
        create_params = {"return_url": return_url}
        if parsed and parsed.card_id and not errors:
            create_params["card_id"] = parsed.card_id
        advanced = sum(bool(values.get(key)) for key in ("card_id", "kind", "direction", "currency")) + bool(values.get("min_abs_amount") or values.get("max_abs_amount"))
        context = {**refs, "filters": values, "transactions": records, "total": total, "source_counts": counts,
                   "page": current_page, "pages": max(1, (total + 49) // 50), "start": (current_page - 1) * 50 + 1 if total else 0,
                   "end": min(current_page * 50, total), "previous_url": parsed.url(current_page - 1) if parsed and current_page > 1 else None,
                   "next_url": parsed.url(current_page + 1) if parsed and current_page * 50 < total else None,
                   "errors": errors, "advanced_count": advanced, "has_filters": any(values.get(k) for k in values if k not in {"page", "period"}) or values.get("period") != "all",
                   "can_create": bool(refs["cards"]), "return_url": return_url, "create_url": "/transactions/new?" + urlencode(create_params)}
        response = render(request, user, "_browser" if is_htmx(request) else "list", context, 422 if errors else 200)
        if is_htmx(request) and not errors:
            response.headers["HX-Push-Url"] = return_url
        return response
    except SQLAlchemyError:
        await db.rollback()
        return error_page(request, user, "Transactions could not be loaded. Please retry.", 503, retry_url=current_path(request))


def form_values(transaction=None):
    values = {key: "" for key in FORM_FIELDS}
    values["transaction_kind"] = "purchase"
    if transaction is not None:
        for key in FORM_FIELDS:
            value = getattr(transaction, key)
            values[key] = value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else ""
    return values


async def form_response(request, db, user, transaction=None, values=None, errors=None, status=200, return_url=None):
    refs = await transaction_service.get_transaction_references(db)
    return_url = safe_return_url(return_url or request.query_params.get("return_url"))
    if values is None:
        values = form_values(transaction)
        if transaction is None:
            selected = request.query_params.get("card_id")
            if not selected:
                selected = dict(parse_qsl(urlsplit(return_url).query)).get("card_id")
            chosen = next((card for card in refs["cards"] if str(card["id"]) == selected), None)
            if chosen is None and len(refs["cards"]) == 1:
                chosen = refs["cards"][0]
            if chosen:
                values.update(card_id=str(chosen["id"]), currency=chosen["currency"])
    title = "Edit transaction" if transaction else "Add transaction"
    context = {**refs, "values": values, "errors": errors or {}, "transaction": transaction, "return_url": return_url,
               "cancel_url": detail_url(transaction.id, return_url) if transaction else return_url,
               "form_action": f"/transactions/{transaction.id}/edit" if transaction else "/transactions/new",
               "submit_label": "Save changes" if transaction else "Create transaction", "can_create": bool(refs["cards"]), "title": title,
               "blocked": status in {403, 503},
               "currency_manually_edited": getattr(request.state, "currency_manually_edited", False),
               "more_details": bool(any(values.get(key) for key in ("posting_datetime", "location", "original_amount", "original_currency", "fx_rate")) or errors)}
    return render(request, user, "_form" if is_htmx(request) and request.method == "POST" else "form", context, status)


@router.get("/new", response_class=HTMLResponse)
async def new_page(request: Request, db: DB, user: ActiveUser):
    return await form_response(request, db, user)


async def save_form(request, db, user, transaction=None):
    posted = await request.form()
    request.state.currency_manually_edited = posted.get("currency_manually_edited") == "yes"
    values = {key: str(posted.get(key, "")) for key in FORM_FIELDS}
    return_url = safe_return_url(posted.get("return_url"))
    transaction_id = transaction.id if transaction is not None else None
    if not valid_csrf(request, posted.get("csrf_token")):
        return await form_response(request, db, user, transaction, values, {"form": "Security token is invalid. Refresh the page before saving again."}, 403, return_url)
    payload = {}
    previous = form_values(transaction)
    for key in FORM_FIELDS:
        # A missing control is omitted on update; optional empty controls explicitly clear.
        if key not in posted and transaction is not None:
            continue
        if transaction is not None and values[key] == previous[key]:
            continue
        if key == "card_id" and transaction is not None and key not in posted:
            continue
        payload[key] = None if key in OPTIONAL_FIELDS and not values[key].strip() else values[key]
    if transaction is not None and {"original_amount", "original_currency"} <= posted.keys():
        if not values["original_amount"].strip() and not values["original_currency"].strip() and any(
            previous[key] for key in ("original_amount", "original_currency")
        ):
            payload.update(original_amount=None, original_currency=None, fx_rate=None)
    # Web fee editing is outside this feature. Never accept hidden changes to it.
    if "fx_fee" in posted:
        return await form_response(request, db, user, transaction, values, {"form": "Recorded FX fee cannot be edited here."}, 422, return_url)
    try:
        if transaction:
            result = await transaction_service.update_transaction(db, transaction.id, TransactionUpdate.model_validate(payload))
            if result is None:
                return error_page(request, user, "This transaction no longer exists.", back_url=return_url)
        else:
            result = await transaction_service.create_transaction(db, TransactionCreate.model_validate(payload))
    except (ValidationError, ValueError) as exc:
        return await form_response(request, db, user, transaction, values, validation_errors(exc), 422, return_url)
    except SQLAlchemyError:
        await db.rollback()
        if transaction_id is not None:
            transaction = await transaction_service.get_transaction(db, transaction_id)
        return await form_response(request, db, user, transaction, values,
                                   {"form": "The save could not be confirmed. Refresh and check the transaction before trying again."}, 503, return_url)
    return navigate(request, detail_url(result.id, return_url) + "&saved=1")


@router.post("/new", response_class=HTMLResponse)
async def create_page(request: Request, db: DB, user: ActiveUser):
    return await save_form(request, db, user)


async def lookup(db, transaction_id):
    identifier = record_id(transaction_id)
    if identifier is None:
        return None
    return await transaction_service.get_transaction(db, identifier)


async def sources_context(request, db, transaction, return_url, page=None, message=None):
    page = page or page_number(request.query_params.get("source_page"))
    links, total = await transaction_service.get_transaction_sources_page(db, transaction.id, limit=20, offset=(page - 1) * 20)
    pages = max(1, (total + 19) // 20)
    if page > pages:
        page = pages
        links, total = await transaction_service.get_transaction_sources_page(db, transaction.id, limit=20, offset=(page - 1) * 20)
    refs = await transaction_service.get_transaction_references(db)
    accounts = {value["id"]: value["label"] for value in refs["accounts"]}
    cards = {value["id"]: value["label"] for value in refs["cards"]}
    available = await run_in_threadpool(lambda: {link.source_event_id: file_path_for(link.source_event) is not None for link in links})
    source_types = {"telegram_text": "Telegram message", "sms_text": "SMS", "sms_screenshot": "SMS screenshot",
                    "bank_screenshot": "Bank screenshot", "pdf_statement": "PDF statement", "manual": "Manual entry"}
    states = {"new": "Not processed", "parsed": "Parsed", "failed": "Could not parse", "skipped": "Not a transaction"}
    sources = []
    for link in links:
        event = link.source_event
        extracted = []
        for name, label in (("parsed_amount", "Extracted amount"), ("parsed_currency", "Extracted currency"),
                            ("parsed_transaction_datetime", "Transaction date"), ("parsed_posting_datetime", "Posting date"),
                            ("parsed_description", "Description"), ("parsed_card_number", "Card last four digits"),
                            ("parsed_transaction_kind", "Type"), ("parsed_location", "Location")):
            value = getattr(event, name)
            if value is not None and value != "":
                if name.endswith("datetime"):
                    value = display_date(value)
                elif name == "parsed_amount":
                    value = money(value, event.parsed_currency)
                elif name == "parsed_transaction_kind":
                    value = KINDS.get(value, "Other")
                extracted.append((label, value))
        context = [(label, value) for label, value in (
            ("Account", accounts.get(event.account_id)), ("Card", cards.get(event.card_id)), ("Sender", event.sender),
            ("Recipients", event.recipients), ("Transaction date", display_date(event.transaction_datetime) if event.transaction_datetime else None)) if value]
        state = states.get(event.parse_status, "Unknown status")
        if event.parse_status == "new" and event.file_path and not event.raw_text:
            state = "Stored file"
        sources.append({"event": event, "type_label": source_types.get(event.source_type, "Unknown source"), "status_label": state,
                        "file_available": available[event.id], "download_url": f"/transactions/sources/{event.id}/download",
                        "extracted": extracted, "context": context})
    def source_url(target):
        return f"/transactions/{transaction.id}/sources?" + urlencode({"source_page": target, "return_url": return_url}) + "#sources"
    return {"sources": sources, "source_page": page, "source_pages": pages, "source_total": total,
            "source_start": (page - 1) * 20 + 1 if total else 0, "source_end": min(page * 20, total),
            "source_previous_url": source_url(page - 1) if page > 1 else None,
            "source_next_url": source_url(page + 1) if page < pages else None, "source_message": message}


async def detail_response(request, db, user, transaction, return_url=None, page=None, message=None):
    return_url = safe_return_url(return_url or request.query_params.get("return_url"))
    if not message and request.query_params.get("unlinked"):
        message = "Source unlinked. The source and file were preserved." if request.query_params.get("unlinked") == "1" else "This link no longer exists. Sources have been refreshed."
    context = await sources_context(request, db, transaction, return_url, page, message)
    context.update(transaction=transaction, return_url=return_url, back_url=return_url,
                   edit_url=f"/transactions/{transaction.id}/edit?" + urlencode({"return_url": return_url}),
                   message="Transaction saved." if request.query_params.get("saved") == "1" else None)
    return render(request, user, "_sources" if is_htmx(request) else "detail", context)


@router.get("/{transaction_id}/edit", response_class=HTMLResponse)
async def edit_page(request: Request, transaction_id: str, db: DB, user: ActiveUser):
    transaction = await lookup(db, transaction_id)
    if transaction is None:
        return error_page(request, user, "This transaction no longer exists.", back_url=safe_return_url(request.query_params.get("return_url")))
    return await form_response(request, db, user, transaction)


@router.post("/{transaction_id}/edit", response_class=HTMLResponse)
async def update_page(request: Request, transaction_id: str, db: DB, user: ActiveUser):
    transaction = await lookup(db, transaction_id)
    if transaction is None:
        return error_page(request, user, "This transaction no longer exists.")
    return await save_form(request, db, user, transaction)


@router.get("/{transaction_id}/sources", response_class=HTMLResponse)
@router.get("/{transaction_id}", response_class=HTMLResponse)
async def transaction_detail(request: Request, transaction_id: str, db: DB, user: ActiveUser):
    try:
        transaction = await lookup(db, transaction_id)
        if transaction is None:
            return error_page(request, user, "This transaction no longer exists.", back_url=safe_return_url(request.query_params.get("return_url")))
        return await detail_response(request, db, user, transaction)
    except SQLAlchemyError:
        await db.rollback()
        return error_page(request, user, "This transaction could not be loaded. Please retry.", 503, retry_url=current_path(request))


async def confirm_mutation(request, user, posted, transaction, source_id=None):
    return_url = safe_return_url(posted.get("return_url"))
    if not valid_csrf(request, posted.get("csrf_token")):
        return error_page(request, user, "Security token is invalid. Refresh the page before trying again.", 403, return_url)
    if posted.get("confirmed") == "yes":
        return None
    unlink = source_id is not None
    return render(request, user, "confirmation", {
        "title": "Unlink source?" if unlink else "Delete transaction?",
        "message": "Only this link will be removed. The source, file, other links and transaction values will remain." if unlink else
            f"Permanently delete {transaction.description or 'No description'} ({money(transaction.amount, transaction.currency)})? Sources, files, accounts, cards and other links will remain.",
        "form_action": request.url.path, "cancel_url": detail_url(transaction.id, return_url, "sources" if unlink else ""),
        "submit_label": "Unlink source" if unlink else "Delete transaction",
        "fields": {"csrf_token": csrf_token(request), "confirmed": "yes", "return_url": return_url, "source_page": str(page_number(posted.get("source_page")))},
    })


@router.post("/{transaction_id}/delete", response_class=HTMLResponse)
async def delete_page(request: Request, transaction_id: str, db: DB, user: ActiveUser):
    posted = await request.form()
    return_url = safe_return_url(posted.get("return_url"))
    transaction = await lookup(db, transaction_id)
    if transaction is None:
        return error_page(request, user, "This transaction no longer exists.", back_url=return_url)
    confirmation = await confirm_mutation(request, user, posted, transaction)
    if confirmation is not None:
        return confirmation
    try:
        await transaction_service.delete_transaction(db, transaction.id)
    except SQLAlchemyError:
        await db.rollback()
        return error_page(request, user, "Deletion could not be confirmed. Refresh the list before trying again.", 503, return_url)
    return navigate(request, return_url)


@router.post("/{transaction_id}/sources/{source_id}/unlink", response_class=HTMLResponse)
async def unlink_page(request: Request, transaction_id: str, source_id: str, db: DB, user: ActiveUser):
    posted = await request.form()
    return_url = safe_return_url(posted.get("return_url"))
    transaction = await lookup(db, transaction_id)
    if transaction is None:
        return error_page(request, user, "This transaction no longer exists.", back_url=return_url)
    confirmation = await confirm_mutation(request, user, posted, transaction, source_id)
    if confirmation is not None:
        return confirmation
    try:
        identifier = record_id(source_id)
        changed = await source_event_service.unlink_source_from_transaction(db, identifier, transaction.id) if identifier is not None else False
        page = page_number(posted.get("source_page"))
        message = "Source unlinked. The source and file were preserved." if changed else "This link no longer exists. Sources have been refreshed."
        if is_htmx(request):
            return await detail_response(request, db, user, transaction, return_url, page, message)
        # A GET renders the refreshed count and clamps the source page after ordinary POST.
        return navigate(request, detail_url(transaction.id, return_url) + "&" + urlencode({"source_page": page, "unlinked": "1" if changed else "missing"}) + "#sources")
    except SQLAlchemyError:
        await db.rollback()
        return error_page(request, user, "Unlinking could not be confirmed. Refresh Sources before trying again.", 503, detail_url(transaction_id, return_url, "sources"))
