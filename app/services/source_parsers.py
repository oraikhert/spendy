"""Versioned parser registry for immutable source payloads."""

from dataclasses import dataclass
from typing import Callable

from app.models.source_payload import SourceKind, SourcePayload
from app.utils.source_parsing.contracts import (
    ParsedObservation,
    SourceParseResult,
    SourceParserInput,
    UnsupportedSourceError,
)
from app.utils.source_parsing.emirates_nbd.credit_card_statement import (
    parse_emirates_nbd_credit_card_statement,
)
from app.utils.source_parsing.emirates_nbd.sms import parse_emirates_nbd_sms


ObservationInput = ParsedObservation
ParserResult = SourceParseResult


@dataclass(frozen=True)
class RegisteredParser:
    name: str
    version: str
    parse: Callable[[SourceParserInput], SourceParseResult]


PARSER_REGISTRY: dict[tuple[str, str], tuple[RegisteredParser, ...]] = {
    (SourceKind.SMS.value, "text/plain"): (
        RegisteredParser(
            name="emirates_nbd_sms_text",
            version="1",
            parse=parse_emirates_nbd_sms,
        ),
    ),
    (SourceKind.BANK_STATEMENT.value, "application/pdf"): (
        RegisteredParser(
            name="emirates_nbd_credit_card_statement_pdf",
            version="2",
            parse=parse_emirates_nbd_credit_card_statement,
        ),
    ),
}


def get_parsers(source_kind: str, media_type: str) -> tuple[RegisteredParser, ...]:
    """Return every candidate registered for a source/media pair."""
    registered = PARSER_REGISTRY.get((source_kind, media_type.lower()), ())
    # Tests and extensions may temporarily install a single parser.
    if isinstance(registered, RegisteredParser):
        return (registered,)
    return registered


def run_registered_parser(
    payload: SourcePayload,
    *,
    file_content: bytes | None = None,
    password: str | None = None,
) -> tuple[RegisteredParser, SourceParseResult]:
    """Run candidates until one recognizes the source."""
    parsers = get_parsers(payload.source_kind, payload.media_type)
    if not parsers:
        raise UnsupportedSourceError(
            "No parser is registered for this source kind and media type"
        )

    source = SourceParserInput(
        raw_text=payload.raw_text,
        file_content=file_content,
        password=password,
        ingestion_metadata=payload.ingestion_metadata,
    )
    last_error: UnsupportedSourceError | None = None
    for parser in parsers:
        try:
            return parser, parser.parse(source)
        except UnsupportedSourceError as exc:
            last_error = exc
    raise last_error or UnsupportedSourceError("No parser recognized the source")
