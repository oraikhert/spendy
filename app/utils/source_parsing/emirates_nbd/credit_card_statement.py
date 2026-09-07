"""Parse Emirates NBD credit-card statement PDFs."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import DependencyError, PdfReadError

from app.utils.business_time import (
    DEFAULT_TIMEZONE,
    local_midnight_utc,
    normalize_timezone_name,
)
from app.utils.source_parsing.contracts import (
    InvalidSourceInputError,
    ParsedBankStatement,
    ParsedObservation,
    ParseStatus,
    SourceParseResult,
    SourceParserInput,
    UnsupportedSourceError,
)


MAX_STATEMENT_PAGES = 100
_DATE = r"\d{2}/\d{2}/\d{4}"
_ROW_RE = re.compile(
    rf"^\s*(?P<transaction_date>{_DATE})"
    rf"(?:\s+(?P<posting_date>{_DATE}))?"
    r"\s+(?P<description>.+?)"
    r"\s+(?P<amount>[+-]?\d[\d,]*\.\d{2})\s*(?P<credit>CR)?\s*$",
    re.IGNORECASE,
)
_FX_RE = re.compile(
    r"^\s*\(\s*1\s+(?P<base>[A-Z]{3})\s*=\s*"
    r"(?P<quote>[A-Z]{3})\s+(?P<rate>\d+(?:\.\d+)?)\s*\)\s*$"
)
_ORIGINAL_RE = re.compile(
    r"^(?P<description>.+?)\s+"
    r"(?P<amount>\d[\d,]*\.\d{2})\s+(?P<currency>[A-Z]{3})\s*$"
)
_INSTALLMENT_RE = re.compile(
    r"^INSTALLMENT\s+PLAN\s+EMI\s*\(\s*(?P<number>\d{1,2})\s*/\s*"
    r"(?P<count>\d{1,2})\s*\)$",
    re.IGNORECASE,
)
_INSTALLMENT_PLAN_RE = re.compile(
    r"^(?P<plan_id>LOC-[A-Z0-9-]+)\s+(?P<principal>\d[\d,]*\.\d{2})$",
    re.IGNORECASE,
)
_REMAINING_PRINCIPAL_RE = re.compile(
    r"^Remaining\s+Principle\s+Balance\s+"
    r"(?P<remaining>\d[\d,]*\.\d{2})$",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r"Statement\s+Period\s*:\s*(?P<start>\d{2}-[A-Za-z]{3}-\d{2})"
    r"\s+to\s+(?P<end>\d{2}-[A-Za-z]{3}-\d{2})",
    re.IGNORECASE,
)
_PERIOD_VALUE_RE = re.compile(
    r"(?P<start>\d{2}-[A-Za-z]{3}-\d{2})"
    r"\s+to\s+(?P<end>\d{2}-[A-Za-z]{3}-\d{2})",
    re.IGNORECASE,
)
_MASKED_CARD_RE = re.compile(
    r"\b\d{4}\s+(?:[X*]{4}\s+){2}(?P<last_four>\d{4})\b",
    re.IGNORECASE,
)
_CARD_SECTION_RE = re.compile(
    r"\b(?:Primary|Supplementary)\s+Card\s+Number\b", re.IGNORECASE
)
_MONEY_RE = re.compile(r"\d[\d,]*\.\d{2}")
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


class _StatementExtractionError(ValueError):
    """A recognized statement cannot be extracted completely."""


def _decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise _StatementExtractionError(f"Invalid {field}") from exc


def _short_date(value: str) -> date:
    day_text, month_text, year_text = value.split("-")
    try:
        return date(2000 + int(year_text), _MONTHS[month_text.lower()], int(day_text))
    except (KeyError, ValueError) as exc:
        raise _StatementExtractionError("Invalid statement period") from exc


def _statement_metadata(full_text: str, page_count: int) -> ParsedBankStatement:
    card_last_four = None
    card_type = None
    lines = [" ".join(line.split()) for line in full_text.splitlines()]
    for line in lines:
        if card_last_four is None and "Card Number:" in line:
            digits = re.findall(r"\d", line.split("Card Number:", 1)[1])
            if len(digits) >= 4:
                card_last_four = "".join(digits[-4:])
        if card_type is None and "Card Type:" in line:
            value = line.split("Card Type:", 1)[1].strip()
            card_type = " ".join(value.split()) or None

    # Some original bank PDFs expose header labels first and their three values
    # later as a masked card, card type, and statement period block.
    for index, line in enumerate(lines):
        masked_card = _MASKED_CARD_RE.search(line)
        if masked_card is None:
            continue
        if card_last_four is None:
            card_last_four = masked_card.group("last_four")
        if (
            card_type is None
            and index + 2 < len(lines)
            and _PERIOD_VALUE_RE.fullmatch(lines[index + 2]) is not None
        ):
            card_type = lines[index + 1] or None
        if card_last_four is not None and card_type is not None:
            break

    if card_last_four is None:
        raise _StatementExtractionError("Card number was not found in the statement")

    period_match = _PERIOD_RE.search(full_text) or _PERIOD_VALUE_RE.search(full_text)
    if period_match is None:
        raise _StatementExtractionError("Statement period was not found")
    period_start = _short_date(period_match.group("start"))
    period_end = _short_date(period_match.group("end"))
    if period_start > period_end:
        raise _StatementExtractionError("Statement period start is after its end")

    currency_match = re.search(
        r"(?:Available Credit Limit|Current Balance|Total Payment Due|"
        r"Purchase / Cash Advance)\s*\(([A-Z]{3})\)",
        full_text,
        re.IGNORECASE,
    )
    if currency_match is None:
        currency_match = re.search(r"\(\s*1\s+([A-Z]{3})\s*=", full_text)
    if currency_match is None:
        raise _StatementExtractionError("Statement currency was not found")

    return ParsedBankStatement(
        bank="Emirates NBD",
        statement_period_start=period_start,
        statement_period_end=period_end,
        statement_currency=currency_match.group(1).upper(),
        card_type=card_type,
        card_last_four=card_last_four,
        page_count=page_count,
    )


def _transaction_kind(description: str, is_credit: bool) -> str:
    normalized = " ".join(description.upper().split())
    if is_credit and "PAYMENT RECEIVED" in normalized:
        return "topup"
    if is_credit:
        return "refund"
    return "purchase"


def _add_months_clamped(value: date, months: int) -> date:
    """Shift a date by whole months while clamping short month ends."""
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _statement_summary_totals(full_text: str) -> tuple[Decimal, Decimal]:
    marker = full_text.find("STATEMENT SUMMARY")
    if marker < 0:
        raise _StatementExtractionError("Statement summary was not found")
    values = _MONEY_RE.findall(full_text[marker : marker + 3500])
    if len(values) < 6:
        raise _StatementExtractionError("Statement summary totals were not found")
    purchases = _decimal(values[1], "purchase summary total")
    charges = _decimal(values[2], "charge summary total")
    credits = _decimal(values[3], "credit summary total")
    return purchases + charges, credits


def _parse_observations(
    pages: list[str], statement: ParsedBankStatement, source_timezone: str
) -> tuple[ParsedObservation, ...]:
    rows: list[dict[str, object]] = []
    currency = statement.statement_currency
    active_card_last_four = statement.card_last_four
    if currency is None:
        raise _StatementExtractionError("Statement currency was not found")

    for page_number, page_text in enumerate(pages, start=1):
        table_active = False
        current_row: dict[str, object] | None = None
        page_lines = page_text.splitlines()
        for line_index, line in enumerate(page_lines):
            stripped = line.strip()
            normalized = " ".join(stripped.split())
            if "STATEMENT SUMMARY" in normalized or "Emirates NBD Bank" in normalized:
                table_active = False
                current_row = None
                continue
            if (
                "Transaction Date" in normalized
                and "Posting Date" in normalized
                and "Description" in normalized
                and "Amount" in normalized
            ):
                table_active = True
                current_row = None
                continue

            if _CARD_SECTION_RE.search(normalized):
                for candidate in page_lines[line_index : line_index + 3]:
                    masked_card = _MASKED_CARD_RE.search(candidate)
                    if masked_card is not None:
                        active_card_last_four = masked_card.group("last_four")
                        break
                current_row = None
                continue

            row_match = _ROW_RE.match(line)
            if row_match is not None:
                # Elixir-generated PDFs omit the table header from layout-mode
                # extraction, while preserving each date-prefixed transaction row.
                table_active = True
                value = _decimal(row_match.group("amount"), "statement amount")
                is_credit = bool(row_match.group("credit"))
                signed_amount = abs(value) if is_credit else -abs(value)
                description = " ".join(row_match.group("description").split())
                installment_match = _INSTALLMENT_RE.fullmatch(description)
                current_row = {
                    "item_index": len(rows) + 1,
                    "page_number": page_number,
                    "transaction_date": datetime.strptime(
                        row_match.group("transaction_date"), "%d/%m/%Y"
                    ).date(),
                    "posting_date": (
                        datetime.strptime(row_match.group("posting_date"), "%d/%m/%Y").date()
                        if row_match.group("posting_date")
                        else None
                    ),
                    "description": description,
                    "amount": signed_amount,
                    "card_last_four": active_card_last_four,
                    "transaction_kind": _transaction_kind(description, is_credit),
                    "printed_transaction_date": None,
                    "installment_number": None,
                    "installment_count": None,
                    "installment_plan_id": None,
                    "installment_principal": None,
                    "remaining_principal": None,
                    "excluded_from_statement_totals": False,
                    "original_amount": None,
                    "original_currency": None,
                    "fx_rate": None,
                    "raw_lines": [stripped],
                }
                if installment_match is not None:
                    current_row["printed_transaction_date"] = current_row[
                        "transaction_date"
                    ]
                    current_row["installment_number"] = int(
                        installment_match.group("number")
                    )
                    current_row["installment_count"] = int(
                        installment_match.group("count")
                    )
                rows.append(current_row)
                continue

            if not table_active:
                continue

            fx_match = _FX_RE.match(stripped)
            if fx_match is not None and current_row is not None:
                original_match = _ORIGINAL_RE.match(str(current_row["description"]))
                if original_match is None:
                    raise _StatementExtractionError("FX details have no original amount")
                original_currency = original_match.group("currency").upper()
                if (
                    fx_match.group("base").upper() != currency
                    or fx_match.group("quote").upper() != original_currency
                ):
                    raise _StatementExtractionError("Inconsistent FX currencies")
                original_value = _decimal(original_match.group("amount"), "original amount")
                if original_value == 0:
                    raise _StatementExtractionError("Original FX amount cannot be zero")
                sign = Decimal("1") if Decimal(current_row["amount"]) >= 0 else Decimal("-1")
                original_amount = abs(original_value) * sign
                current_row["description"] = " ".join(
                    original_match.group("description").split()
                )
                current_row["original_amount"] = original_amount
                current_row["original_currency"] = original_currency
                current_row["fx_rate"] = (
                    abs(Decimal(current_row["amount"]) / original_amount)
                    .quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                )
                current_row["raw_lines"].append(stripped)
                continue

            if current_row is not None and (
                normalized.startswith("LOC-")
                or normalized.startswith("Remaining Principle Balance")
            ):
                plan_match = _INSTALLMENT_PLAN_RE.fullmatch(normalized)
                remaining_match = _REMAINING_PRINCIPAL_RE.fullmatch(normalized)
                if current_row["installment_number"] is not None:
                    if plan_match is not None:
                        current_row["installment_plan_id"] = plan_match.group(
                            "plan_id"
                        ).upper()
                        current_row["installment_principal"] = _decimal(
                            plan_match.group("principal"), "installment principal"
                        )
                    elif remaining_match is not None:
                        current_row["remaining_principal"] = _decimal(
                            remaining_match.group("remaining"),
                            "remaining installment principal",
                        )
                current_row["description"] = f"{current_row['description']} {normalized}"
                current_row["raw_lines"].append(stripped)

    if not rows:
        raise _StatementExtractionError("No statement transactions were found")

    installment_plans: dict[str, dict[str, object]] = {}
    for row in rows:
        installment_number = row["installment_number"]
        if installment_number is None:
            continue
        installment_count = int(row["installment_count"])
        if not 1 <= int(installment_number) <= installment_count:
            raise _StatementExtractionError("Invalid installment sequence")
        plan_id = row["installment_plan_id"]
        principal = row["installment_principal"]
        remaining = row["remaining_principal"]
        if plan_id is None or principal is None or remaining is None:
            raise _StatementExtractionError("Incomplete installment details")
        printed_date = row["printed_transaction_date"]
        effective_date = _add_months_clamped(
            printed_date, int(installment_number) - 1
        )
        date_source = "installment_sequence"
        if not (
            statement.statement_period_start
            <= effective_date
            <= statement.statement_period_end
        ):
            effective_date = statement.statement_period_end
            date_source = "statement_period_end"
        row["transaction_date"] = effective_date
        installment_plans[str(plan_id)] = row
        row["installment_date_source"] = date_source

    for row in rows:
        plan = installment_plans.get(str(row["description"]).upper())
        if plan is None:
            continue
        if (
            abs(Decimal(row["amount"])) == Decimal(plan["installment_principal"])
            and row["transaction_date"] == plan["printed_transaction_date"]
        ):
            row["transaction_kind"] = "other"
            row["excluded_from_statement_totals"] = True

    observations = []
    for row in rows:
        transaction_date = row["transaction_date"]
        posting_date = row["posting_date"]
        fx_rate = row["fx_rate"]
        metadata: dict[str, object] = {
            "page_number": row["page_number"],
            "row_number": row["item_index"],
            "local_transaction_date": transaction_date.isoformat(),
        }
        if row["installment_number"] is not None:
            metadata.update(
                {
                    "statement_entry_type": "installment_payment",
                    "installment_plan_id": row["installment_plan_id"],
                    "installment_number": row["installment_number"],
                    "installment_count": row["installment_count"],
                    "installment_principal": str(row["installment_principal"]),
                    "remaining_principal": str(row["remaining_principal"]),
                    "printed_plan_date": row["printed_transaction_date"].isoformat(),
                    "installment_date_source": row["installment_date_source"],
                }
            )
        if row["excluded_from_statement_totals"]:
            metadata.update(
                {
                    "statement_entry_type": "loan_principal",
                    "installment_plan_id": row["description"],
                    "excluded_from_statement_totals": True,
                    "excluded_from_summary": True,
                }
            )
        if posting_date is not None:
            metadata["local_posting_date"] = posting_date.isoformat()
        if fx_rate is not None:
            metadata["statement_fx_rate"] = str(fx_rate)
        observations.append(
            ParsedObservation(
                source_item_key=str(row["item_index"]),
                amount=Decimal(row["amount"]),
                currency=currency,
                original_amount=(
                    Decimal(row["original_amount"])
                    if row["original_amount"] is not None
                    else None
                ),
                original_currency=(
                    str(row["original_currency"])
                    if row["original_currency"] is not None
                    else None
                ),
                transaction_datetime=local_midnight_utc(
                    transaction_date, source_timezone
                ),
                posting_datetime=(
                    local_midnight_utc(posting_date, source_timezone)
                    if posting_date
                    else None
                ),
                description=str(row["description"]),
                transaction_kind=str(row["transaction_kind"]),
                card_last_four=(
                    str(row["card_last_four"])
                    if row["card_last_four"] is not None
                    else None
                ),
                raw_fragment="\n".join(row["raw_lines"]),
                extraction_confidence=Decimal("1.0000"),
                extraction_metadata=metadata,
            )
        )
    return tuple(observations)


def parse_emirates_nbd_statement_text(
    layout_pages: list[str],
    *,
    document_pages: list[str] | None = None,
    source_timezone: str = DEFAULT_TIMEZONE,
) -> SourceParseResult:
    """Parse row layout plus normal document text from a statement."""
    source_timezone = normalize_timezone_name(source_timezone)
    if document_pages is None:
        document_pages = layout_pages
    document_text = "\n".join(document_pages)
    if not re.search(r"Credit\s+Card\s+Statement", document_text, re.IGNORECASE):
        raise UnsupportedSourceError("The PDF is not a supported credit-card statement")
    if not re.search(r"Emirates\s+NBD", document_text, re.IGNORECASE):
        raise UnsupportedSourceError("The PDF is not an Emirates NBD statement")

    statement = ParsedBankStatement(bank="Emirates NBD", page_count=len(layout_pages))
    try:
        statement = _statement_metadata(document_text, len(layout_pages))
        observations = _parse_observations(
            layout_pages, statement, source_timezone
        )
        expected_debits, expected_credits = _statement_summary_totals(document_text)
        parsed_debits = -sum(
            (
                value.amount
                for value in observations
                if value.amount
                and value.amount < 0
                and not value.extraction_metadata.get(
                    "excluded_from_statement_totals", False
                )
            ),
            Decimal("0"),
        )
        parsed_credits = sum(
            (value.amount for value in observations if value.amount and value.amount > 0),
            Decimal("0"),
        )
        if parsed_debits != expected_debits or parsed_credits != expected_credits:
            raise _StatementExtractionError(
                "Statement transaction totals do not match the statement summary"
            )
    except _StatementExtractionError as exc:
        return SourceParseResult(
            ParseStatus.FAILED,
            error=str(exc),
            bank_statement=statement,
        )

    return SourceParseResult(
        ParseStatus.PROCESSED,
        observations=observations,
        bank_statement=statement,
    )


def parse_emirates_nbd_credit_card_statement(
    source: SourceParserInput,
) -> SourceParseResult:
    """Decrypt, extract, and parse an Emirates NBD statement PDF."""
    file_content = source.file_content
    if not file_content or not file_content.startswith(b"%PDF-"):
        raise InvalidSourceInputError("The uploaded bank statement is not a PDF")

    try:
        reader = PdfReader(BytesIO(file_content), strict=False)
        if reader.is_encrypted and not reader.decrypt(source.password or ""):
            raise InvalidSourceInputError("The PDF password is missing or incorrect")
        if len(reader.pages) > MAX_STATEMENT_PAGES:
            raise InvalidSourceInputError(
                f"The statement exceeds the {MAX_STATEMENT_PAGES}-page limit"
            )
        document_pages = [page.extract_text() or "" for page in reader.pages]
        layout_pages = [
            page.extract_text(extraction_mode="layout") or "" for page in reader.pages
        ]
    except InvalidSourceInputError:
        raise
    except (DependencyError, PdfReadError, OSError, TypeError, ValueError) as exc:
        raise InvalidSourceInputError("The PDF could not be read") from exc

    try:
        source_timezone = normalize_timezone_name(
            str(source.ingestion_metadata.get("source_timezone", DEFAULT_TIMEZONE))
        )
    except ValueError as exc:
        raise InvalidSourceInputError(str(exc)) from exc

    return parse_emirates_nbd_statement_text(
        layout_pages,
        document_pages=document_pages,
        source_timezone=source_timezone,
    )
