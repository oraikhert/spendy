"""HTTP-only parsing and presentation for transaction pages."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import hmac
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import settings


KINDS = {"purchase": "Purchase", "topup": "Top-up", "refund": "Refund", "other": "Other"}
FILTER_NAMES = {"q", "period", "date_from", "date_to", "account_id", "card_id", "kind", "direction", "currency", "min_abs_amount", "max_abs_amount", "page"}


class ListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = ""
    period: str = "all"
    date_from: date | None = None
    date_to: date | None = None
    account_id: int | None = Field(None, gt=0, le=2147483647)
    card_id: int | None = Field(None, gt=0, le=2147483647)
    kind: str = ""
    direction: str = ""
    currency: str = ""
    min_abs_amount: Decimal | None = Field(None, ge=0, max_digits=15, decimal_places=2, allow_inf_nan=False)
    max_abs_amount: Decimal | None = Field(None, ge=0, max_digits=15, decimal_places=2, allow_inf_nan=False)
    page: int = Field(1, ge=1, le=1000000000)

    @field_validator("q", "currency", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip()

    @field_validator("currency")
    @classmethod
    def currency_code(cls, value):
        if value and not re.fullmatch("[A-Za-z]{3}", value):
            raise ValueError("Use three Latin letters for currency")
        return value.upper()

    @field_validator("period", "kind", "direction")
    @classmethod
    def choices(cls, value, info):
        choices = {"period": {"all", "month", "custom"}, "kind": {"", *KINDS}, "direction": {"", "out", "in"}}
        if value not in choices[info.field_name]:
            raise ValueError("Choose a valid option")
        return value

    @model_validator(mode="after")
    def ranges(self):
        if self.period == "month":
            today = date.today()
            self.date_from = today.replace(day=1)
            self.date_to = date(today.year + today.month // 12, today.month % 12 + 1, 1) - timedelta(days=1)
            self.period = "custom"
        if self.period == "custom":
            if self.date_from is None or self.date_to is None:
                raise ValueError("date_from: Both dates are required for a custom range")
            if self.date_from > self.date_to:
                raise ValueError("date_to: To must be on or after From")
        elif self.date_from is not None or self.date_to is not None:
            raise ValueError("period: Select Custom range to use dates")
        if (self.min_abs_amount is not None or self.max_abs_amount is not None) and not self.currency:
            raise ValueError("currency: Choose a currency for amount bounds")
        if self.min_abs_amount is not None and self.max_abs_amount is not None and self.min_abs_amount > self.max_abs_amount:
            raise ValueError("max_abs_amount: Amount to must be at least Amount from")
        return self

    def service_args(self):
        result = self.model_dump(exclude={"period", "page"})
        result["date_from"] = datetime.combine(self.date_from, time.min) if self.date_from else None
        result["date_to"] = datetime.combine(self.date_to, time.max) if self.date_to else None
        for field in ("q", "kind", "direction", "currency"):
            result[field] = result[field] or None
        return result

    def values(self):
        return {key: "" if value is None else str(value) for key, value in self.model_dump().items()}

    def url(self, page=None):
        values = self.values()
        values["page"] = str(page or self.page)
        values = {key: value for key, value in values.items() if value and not (key == "page" and value == "1") and not (key == "period" and value == "all")}
        return "/transactions" + ("?" + urlencode(values) if values else "")


def parse_filters(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"{key}: Use each filter only once")
        data[key] = value
    return ListFilters.model_validate({key: value for key, value in data.items() if value != ""})


def safe_return_url(value):
    if not value or len(value) > 8192 or any(ord(c) < 32 for c in value) or "\\" in value:
        return "/transactions"
    try:
        parts = urlsplit(value)
        if parts.scheme or parts.netloc or parts.path != "/transactions" or parts.fragment:
            return "/transactions"
        return parse_filters(parse_qsl(parts.query, keep_blank_values=True, max_num_fields=20)).url()
    except (ValueError, ValidationError):
        return "/transactions"


def detail_url(transaction_id, return_url="/transactions", anchor=""):
    return f"/transactions/{transaction_id}?{urlencode({'return_url': safe_return_url(return_url)})}" + (f"#{anchor}" if anchor else "")


def csrf_token(request):
    return hmac.new(settings.SECRET_KEY.encode(), ("transactions:" + request.cookies.get("access_token", "")).encode(), hashlib.sha256).hexdigest()


def valid_csrf(request, value):
    return isinstance(value, str) and value.isascii() and hmac.compare_digest(csrf_token(request), value)


def money(value, currency=""):
    if value is None:
        return "Not specified"
    amount = Decimal(value)
    sign = "−" if amount < 0 else "+" if amount > 0 else ""
    return f"{sign}{abs(amount):,.2f} {currency or ''}".strip()


def display_date(value, missing="Not specified"):
    if value is None:
        return missing
    result = value.strftime("%d %b %Y, %H:%M")
    if value.second or value.microsecond:
        result += value.strftime(":%S")
        if value.microsecond:
            result += f".{value.microsecond:06d}".rstrip("0")
    offset = value.strftime("%z")
    if offset:
        result += f" UTC{offset[:3]}:{offset[3:]}"
    return result


def account_label(account):
    return f"{account.institution} · {account.name}"


def card_label(card):
    return f"{card.name} · {card.card_masked_number}"


def validation_errors(exc):
    errors = {}
    if isinstance(exc, ValidationError):
        for item in exc.errors():
            key = str(item["loc"][0]) if item["loc"] else "form"
            message = item["msg"].removeprefix("Value error, ")
            if key == "form" and ": " in message:
                key, message = message.split(": ", 1)
            errors.setdefault(key, message)
    else:
        message = str(exc)
        key, message = message.split(": ", 1) if ": " in message else ("form", message)
        errors[key] = message
    return errors
