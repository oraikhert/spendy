"""Versioned parser registry for immutable source payloads."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from app.models.source_payload import ProcessingStatus, SourceKind, SourcePayload
from app.utils.parsing import parse_text


@dataclass(frozen=True)
class ObservationInput:
    source_item_key: str
    amount: Decimal | None = None
    currency: str | None = None
    original_amount: Decimal | None = None
    original_currency: str | None = None
    transaction_datetime: datetime | None = None
    posting_datetime: datetime | None = None
    description: str | None = None
    transaction_kind: str | None = None
    location: str | None = None
    account_id: int | None = None
    card_id: int | None = None
    card_last_four: str | None = None
    raw_fragment: str | None = None
    extraction_confidence: Decimal | None = None
    extraction_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParserResult:
    status: ProcessingStatus
    observations: tuple[ObservationInput, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class RegisteredParser:
    name: str
    version: str
    parse: Callable[[SourcePayload], ParserResult]


def _metadata_datetime(payload: SourcePayload, key: str) -> datetime | None:
    value = payload.ingestion_metadata.get(key)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_sms_text(payload: SourcePayload) -> ParserResult:
    parsed = parse_text(payload.raw_text or "")
    if parsed["parse_status"] == "skipped":
        return ParserResult(ProcessingStatus.IGNORED, error=parsed.get("parse_error"))
    if parsed["parse_status"] == "failed":
        return ParserResult(
            ProcessingStatus.FAILED,
            error=parsed.get("parse_error") or "The SMS could not be parsed",
        )
    if parsed.get("parsed_amount") is None or not parsed.get("parsed_currency"):
        return ParserResult(
            ProcessingStatus.FAILED,
            error="No financial transaction could be extracted from the SMS",
        )

    return ParserResult(
        ProcessingStatus.PROCESSED,
        observations=(
            ObservationInput(
                source_item_key="0",
                amount=parsed["parsed_amount"],
                currency=parsed["parsed_currency"],
                transaction_datetime=(
                    parsed.get("parsed_transaction_datetime")
                    or _metadata_datetime(payload, "transaction_datetime")
                ),
                posting_datetime=parsed.get("parsed_posting_datetime"),
                description=parsed.get("parsed_description"),
                transaction_kind=parsed.get("parsed_transaction_kind"),
                location=parsed.get("parsed_location"),
                account_id=payload.ingestion_metadata.get("account_id"),
                card_id=payload.ingestion_metadata.get("card_id"),
                card_last_four=parsed.get("parsed_card_number"),
                raw_fragment=payload.raw_text,
            ),
        ),
    )


PARSER_REGISTRY: dict[tuple[str, str], RegisteredParser] = {
    (SourceKind.SMS.value, "text/plain"): RegisteredParser(
        name="sms_regex",
        version="1",
        parse=parse_sms_text,
    ),
}


def get_parser(source_kind: str, media_type: str) -> RegisteredParser | None:
    """Return the exact parser for a source/media pair."""
    return PARSER_REGISTRY.get((source_kind, media_type.lower()))
