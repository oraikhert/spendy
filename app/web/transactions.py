"""Cookie-authenticated transaction pages. Business operations live in services."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.routing import APIRoute
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_current_user_from_cookie_required
from app.database import get_db
from app.models.user import User
from app.schemas.transaction import TransactionCreate, TransactionUpdate
from app.services import source_processing_service, transaction_service
from app.services.source_processing_service import (
    SourceConflictError,
    SourceNotFoundError,
    SourceValidationError,
)
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


@dataclass(frozen=True)
class SourcePayloadView:
    """Safe payload presentation without private storage or technical hashes."""

    id: int
    kind_label: str
    media_type: str
    ingestion_label: str
    original_filename: str | None
    has_file: bool
    received_at: datetime
    status_label: str
    status_is_error: bool
    parser: str | None
    processing_error: str | None
    raw_text: str | None
    context: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TransactionObservationView:
    """One linked observation and the safe evidence shown with it."""

    id: int
    payload: SourcePayloadView
    extracted: tuple[tuple[str, str | datetime], ...]
    match: tuple[tuple[str, str | datetime], ...]
    raw_fragment: str | None


@dataclass(frozen=True)
class TransactionMoveTargetView:
    """A bounded, safe transaction selector entry for moving an observation."""

    id: int
    label: str


async def web_user(request: Request, user: Annotated[User, Depends(get_current_user_from_cookie_required)]) -> WebUser:
    request.state.transaction_user = WebUser(username=user.username)
    return request.state.transaction_user


ActiveUser = Annotated[WebUser, Depends(web_user)]
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


SOURCE_KINDS = {
    "sms": "SMS",
    "bank_statement": "Bank statement",
    "bank_app": "Bank app",
    "other": "Other",
}
INGESTION_METHODS = {
    "phone_api": "Phone API",
    "manual_upload": "Manual upload",
    "telegram_api": "Telegram API",
    "email": "Email",
    "migration": "Migration",
}
PROCESSING_STATES = {
    "pending": "Pending",
    "processing": "Processing",
    "processed": "Processed",
    "ignored": "Ignored",
    "failed": "Failed",
}
MATCH_METHODS = {
    "automatic": "Automatic",
    "manual": "Manual",
    "migration": "Migration",
}


def confidence(value):
    return f"{Decimal(value) * 100:.2f}%" if value is not None else None


def source_view(link, accounts, cards):
    observation = link.observation
    payload = observation.payload
    extracted = []
    if observation.amount is not None:
        extracted.append((
            "Extracted amount",
            money(observation.amount, observation.currency),
        ))
    elif observation.currency:
        extracted.append(("Extracted currency", observation.currency))
    if observation.original_amount is not None:
        extracted.append((
            "Extracted original amount",
            money(observation.original_amount, observation.original_currency),
        ))
    elif observation.original_currency:
        extracted.append(("Extracted original currency", observation.original_currency))
    for label, value in (
        ("Transaction date", observation.transaction_datetime),
        ("Posting date", observation.posting_datetime),
        ("Description", observation.description),
        ("Type", KINDS.get(observation.transaction_kind, "Other") if observation.transaction_kind else None),
        ("Location", observation.location),
        ("Card last four digits", observation.card_last_four),
        ("Extraction confidence", confidence(observation.extraction_confidence)),
    ):
        if value is not None and value != "":
            extracted.append((label, value if isinstance(value, datetime) else str(value)))

    match = [
        ("Match method", MATCH_METHODS.get(link.match_method, "Unknown method")),
        ("Matched", link.matched_at),
    ]
    if link.match_confidence is not None:
        match.append(("Match confidence", confidence(link.match_confidence)))
    if link.matcher_name:
        matcher = link.matcher_name
        if link.matcher_version:
            matcher += f" · version {link.matcher_version}"
        match.append(("Matcher", matcher))
    elif link.matcher_version:
        match.append(("Matcher version", link.matcher_version))

    metadata = payload.ingestion_metadata or {}
    context = []
    for label, value in (
        ("Observation account", accounts.get(observation.account_id)),
        ("Observation card", cards.get(observation.card_id)),
        ("Requested account", accounts.get(metadata.get("account_id"))),
        ("Requested card", cards.get(metadata.get("card_id"))),
        ("Sender", metadata.get("sender")),
        ("Recipients", metadata.get("recipients")),
    ):
        if value is not None and value != "":
            context.append((label, str(value)))

    parser = payload.parser_name
    if parser and payload.parser_version:
        parser += f" · version {payload.parser_version}"
    elif payload.parser_version:
        parser = f"Version {payload.parser_version}"
    return TransactionObservationView(
        id=observation.id,
        payload=SourcePayloadView(
            id=payload.id,
            kind_label=SOURCE_KINDS.get(payload.source_kind, "Unknown source"),
            media_type=payload.media_type,
            ingestion_label=INGESTION_METHODS.get(payload.ingestion_method, "Unknown ingestion method"),
            original_filename=payload.original_filename,
            has_file=payload.has_file,
            received_at=payload.received_at,
            status_label=PROCESSING_STATES.get(payload.processing_status, "Unknown status"),
            status_is_error=payload.processing_status == "failed",
            parser=parser,
            processing_error=payload.processing_error,
            raw_text=payload.raw_text if payload.source_kind == "sms" else None,
            context=tuple(context),
        ),
        extracted=tuple(extracted),
        match=tuple(match),
        raw_fragment=observation.raw_fragment,
    )


async def sources_context(request, db, transaction, return_url, page=None, message=None, move_state=None):
    page = page or page_number(request.query_params.get("source_page"))
    links, total = await transaction_service.get_transaction_observations_page(
        db, transaction.id, limit=20, offset=(page - 1) * 20
    )
    pages = max(1, (total + 19) // 20)
    if page > pages:
        page = pages
        links, total = await transaction_service.get_transaction_observations_page(
            db, transaction.id, limit=20, offset=(page - 1) * 20
        )
    refs = await transaction_service.get_transaction_references(db)
    candidates, candidate_total = await transaction_service.get_transactions(db, limit=1000)
    accounts = {value["id"]: value["label"] for value in refs["accounts"]}
    cards = {value["id"]: value["label"] for value in refs["cards"]}
    sources = [source_view(link, accounts, cards) for link in links]
    move_state = move_state or {}
    move_targets = tuple(
        TransactionMoveTargetView(
            id=candidate.id,
            label=(
                f"#{candidate.id} · {candidate.description or 'No description'} "
                f"· {money(candidate.amount, candidate.currency)}"
            ),
        )
        for candidate in candidates
        if candidate.id != transaction.id
    )
    def source_url(target):
        return f"/transactions/{transaction.id}/sources?" + urlencode({"source_page": target, "return_url": return_url}) + "#sources"
    return {"sources": sources, "source_page": page, "source_pages": pages, "source_total": total,
            "source_start": (page - 1) * 20 + 1 if total else 0, "source_end": min(page * 20, total),
            "source_previous_url": source_url(page - 1) if page > 1 else None,
            "source_next_url": source_url(page + 1) if page < pages else None, "source_message": message,
            "move_targets": move_targets, "move_targets_truncated": candidate_total > 1000,
            "move_observation_id": move_state.get("observation_id"),
            "move_transaction_id": move_state.get("transaction_id", ""),
            "move_error": move_state.get("error")}


async def detail_response(
    request, db, user, transaction, return_url=None, page=None, message=None,
    sources_only=False, move_state=None,
):
    return_url = safe_return_url(return_url or request.query_params.get("return_url"))
    if not message and request.query_params.get("unlinked"):
        message = (
            "Observation unlinked. The payload, observation, private file and transaction were preserved."
            if request.query_params.get("unlinked") == "1"
            else "This link no longer exists. Sources have been refreshed."
        )
    if not message and (moved_to := record_id(request.query_params.get("moved_to", ""))):
        message = (
            f"Observation moved to transaction #{moved_to}. "
            "Both transactions were recanonicalized."
        )
    context = await sources_context(request, db, transaction, return_url, page, message, move_state)
    context.update(transaction=transaction, return_url=return_url, back_url=return_url,
                   edit_url=f"/transactions/{transaction.id}/edit?" + urlencode({"return_url": return_url}),
                   message="Transaction saved." if request.query_params.get("saved") == "1" else None)
    if is_htmx(request):
        return render(request, user, "_sources" if sources_only else "_detail", context)
    return render(request, user, "detail", context)


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
        return await detail_response(
            request,
            db,
            user,
            transaction,
            sources_only=request.url.path.endswith("/sources"),
        )
    except SQLAlchemyError:
        await db.rollback()
        return error_page(request, user, "This transaction could not be loaded. Please retry.", 503, retry_url=current_path(request))


async def confirm_mutation(request, user, posted, transaction, observation_id=None):
    return_url = safe_return_url(posted.get("return_url"))
    if not valid_csrf(request, posted.get("csrf_token")):
        return error_page(request, user, "Security token is invalid. Refresh the page before trying again.", 403, return_url)
    if posted.get("confirmed") == "yes":
        return None
    unlink = observation_id is not None
    return render(request, user, "confirmation", {
        "title": "Unlink source?" if unlink else "Delete transaction?",
        "message": "Only this link will be removed. The payload, observation, private file and transaction will remain. Other links will remain, but canonical transaction values may change." if unlink else
            f"Permanently delete {transaction.description or 'No description'} ({money(transaction.amount, transaction.currency)})? Sources, files, accounts, cards and other links will remain.",
        "form_action": request.url.path, "cancel_url": detail_url(transaction.id, return_url, "sources" if unlink else ""),
        "submit_label": "Unlink source" if unlink else "Delete transaction",
        "fields": {"csrf_token": csrf_token(request), "confirmed": "yes", "return_url": return_url, "source_page": str(page_number(posted.get("source_page")))},
    })


async def move_context(db, transaction, observation_id):
    """Confirm that the observation still belongs to this page's transaction."""
    observation = await source_processing_service.get_transaction_observation(db, observation_id)
    if (
        observation is None
        or observation.transaction_link is None
        or observation.transaction_link.transaction_id != transaction.id
    ):
        return None
    return observation


async def move_error_response(
    request, db, user, transaction, return_url, page, observation_id, transaction_id, message, status
):
    response = await detail_response(
        request,
        db,
        user,
        transaction,
        return_url,
        page,
        message,
        move_state={
            "observation_id": observation_id,
            "transaction_id": transaction_id,
            "error": message,
        },
    )
    response.status_code = status
    return response


@router.post("/{transaction_id}/sources/move", response_class=HTMLResponse)
async def move_observation_page(
    request: Request, transaction_id: str, db: DB, user: ActiveUser
):
    posted = await request.form()
    values = {
        "return_url": str(posted.get("return_url", "")),
        "source_page": str(posted.get("source_page", "")),
        "observation_id": str(posted.get("observation_id", "")),
        "transaction_id": str(posted.get("transaction_id", "")),
    }
    return_url = safe_return_url(values["return_url"])
    page = page_number(values["source_page"])
    transaction = await lookup(db, transaction_id)
    if transaction is None:
        return error_page(request, user, "This transaction or observation no longer exists.", back_url=return_url)
    if not valid_csrf(request, posted.get("csrf_token")):
        return error_page(
            request,
            user,
            "Security token is invalid. Refresh the page before moving the observation.",
            403,
            detail_url(transaction.id, return_url, "sources"),
        )
    identifier = record_id(values["observation_id"])
    if identifier is None:
        return error_page(request, user, "This transaction or observation no longer exists.", back_url=return_url)
    if await move_context(db, transaction, identifier) is None:
        return error_page(
            request,
            user,
            "This observation is no longer linked to this transaction.",
            back_url=detail_url(transaction.id, return_url, "sources"),
        )
    target_id = record_id(values["transaction_id"])
    if target_id is None:
        return await move_error_response(
            request, db, user, transaction, return_url, page, identifier,
            values["transaction_id"], "Choose a destination transaction.", 422,
        )
    if target_id == transaction.id:
        return await move_error_response(
            request, db, user, transaction, return_url, page, identifier,
            values["transaction_id"], "Choose a different destination transaction.", 422,
        )
    if await transaction_service.get_transaction(db, target_id) is None:
        return await move_error_response(
            request, db, user, transaction, return_url, page, identifier,
            values["transaction_id"], "Destination transaction not found.", 422,
        )
    try:
        await source_processing_service.move_observation_to_transaction(
            db,
            identifier,
            target_id,
            expected_transaction_id=transaction.id,
        )
    except (SourceConflictError, SourceNotFoundError, SourceValidationError) as exc:
        return await move_error_response(
            request, db, user, transaction, return_url, page, identifier,
            values["transaction_id"], str(exc), 422,
        )
    except SQLAlchemyError:
        await db.rollback()
        return await move_error_response(
            request, db, user, transaction, return_url, page, identifier,
            values["transaction_id"],
            "The move could not be confirmed. Refresh and check both transactions.", 503,
        )
    message = f"Observation moved to transaction #{target_id}. Both transactions were recanonicalized."
    if is_htmx(request):
        return await detail_response(request, db, user, transaction, return_url, page, message)
    return navigate(
        request,
        detail_url(transaction.id, return_url)
        + "&"
        + urlencode({"source_page": page, "moved_to": target_id})
        + "#sources",
    )


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


@router.post("/{transaction_id}/sources/{observation_id}/unlink", response_class=HTMLResponse)
async def unlink_page(request: Request, transaction_id: str, observation_id: str, db: DB, user: ActiveUser):
    posted = await request.form()
    return_url = safe_return_url(posted.get("return_url"))
    transaction = await lookup(db, transaction_id)
    if transaction is None:
        return error_page(request, user, "This transaction no longer exists.", back_url=return_url)
    confirmation = await confirm_mutation(request, user, posted, transaction, observation_id)
    if confirmation is not None:
        return confirmation
    try:
        identifier = record_id(observation_id)
        changed = await source_processing_service.unlink_observation(
            db, identifier, transaction.id
        ) if identifier is not None else False
        page = page_number(posted.get("source_page"))
        message = (
            "Observation unlinked. The payload, observation, private file and transaction were preserved. Canonical transaction values may have changed."
            if changed else "This link no longer exists. Sources have been refreshed."
        )
        if changed:
            await db.refresh(transaction)
        if is_htmx(request):
            return await detail_response(request, db, user, transaction, return_url, page, message)
        # A GET renders the refreshed count and clamps the source page after ordinary POST.
        return navigate(request, detail_url(transaction.id, return_url) + "&" + urlencode({"source_page": page, "unlinked": "1" if changed else "missing"}) + "#sources")
    except SQLAlchemyError:
        await db.rollback()
        return error_page(request, user, "Unlinking could not be confirmed. Refresh Sources before trying again.", 503, detail_url(transaction_id, return_url, "sources"))
