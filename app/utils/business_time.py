"""Business-calendar helpers for UTC persistence and source-local dates."""

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from app.models.card import Card


DEFAULT_TIMEZONE = "UTC"


def normalize_timezone_name(value: str) -> str:
    """Validate and normalize an IANA timezone name."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("timezone must not be blank")
    try:
        zone = ZoneInfo(normalized)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone name") from exc
    return zone.key


def aware_utc(value: datetime) -> datetime:
    """Return a UTC-aware instant; persisted naive values are treated as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def business_date(value: datetime, timezone_name: str = DEFAULT_TIMEZONE) -> date:
    """Return the calendar date of an instant in the requested business timezone."""
    timezone_name = normalize_timezone_name(timezone_name)
    return aware_utc(value).astimezone(ZoneInfo(timezone_name)).date()


def local_midnight_utc(
    value: date, timezone_name: str = DEFAULT_TIMEZONE
) -> datetime:
    """Represent local midnight for a date as a UTC-aware persisted instant."""
    timezone_name = normalize_timezone_name(timezone_name)
    local_value = datetime.combine(value, time.min, tzinfo=ZoneInfo(timezone_name))
    return local_value.astimezone(UTC)


def business_day_utc_bounds(
    value: date, timezone_name: str = DEFAULT_TIMEZONE
) -> tuple[datetime, datetime]:
    """Return UTC instants bounding one local calendar day, including DST days."""
    timezone_name = normalize_timezone_name(timezone_name)
    zone = ZoneInfo(timezone_name)
    start = datetime.combine(value, time.min, tzinfo=zone)
    end = datetime.combine(value + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def effective_card_timezone(card: "Card") -> str:
    """Resolve a card override, then its account timezone, then UTC."""
    value = card.timezone or getattr(card.account, "timezone", None) or DEFAULT_TIMEZONE
    return normalize_timezone_name(value)
