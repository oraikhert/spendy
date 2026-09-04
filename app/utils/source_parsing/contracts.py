"""Shared, persistence-agnostic contracts for source parsers."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping


class ParseStatus(StrEnum):
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class SourceParserError(ValueError):
    """Base class for safe parser errors."""


class InvalidSourceInputError(SourceParserError):
    """The supplied bytes or credentials cannot be processed."""


class UnsupportedSourceError(SourceParserError):
    """A parser does not recognize this source document."""


@dataclass(frozen=True, slots=True)
class SourceParserInput:
    raw_text: str | None = None
    file_content: bytes | None = None
    password: str | None = None
    ingestion_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedObservation:
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


@dataclass(frozen=True, slots=True)
class ParsedBankStatement:
    bank: str
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    statement_currency: str | None = None
    card_type: str | None = None
    card_last_four: str | None = None
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class SourceParseResult:
    status: ParseStatus
    observations: tuple[ParsedObservation, ...] = ()
    error: str | None = None
    bank_statement: ParsedBankStatement | None = None
