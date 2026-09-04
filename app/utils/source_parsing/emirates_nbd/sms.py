"""Parse Emirates NBD credit-card SMS notifications."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.utils.source_parsing.contracts import (
    ParsedObservation,
    ParseStatus,
    SourceParseResult,
    SourceParserInput,
)


def _metadata_datetime(source: SourceParserInput, key: str) -> datetime | None:
    value = source.ingestion_metadata.get(key)
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _amount(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _merchant_and_location(text: str) -> tuple[str | None, str | None]:
    merchant: str | None = None
    location: str | None = None
    at_match = re.search(
        r"\s+at\s+(.+?)(?:\.\s*Avl|\s+on\s+your\s+Credit\s+Card|\s*$)",
        text,
        re.IGNORECASE,
    )
    if at_match:
        merchant_raw = at_match.group(1).strip().rstrip(".")
        parts = merchant_raw.rsplit(",", 1)
        if len(parts) == 2:
            potential_location = parts[1].strip().rstrip(".")
            known_locations = {
                "dubai", "abu dhabi", "sharjah", "dxb", "uae", "new york",
                "san francisco", "ae",
            }
            if potential_location and (
                potential_location[0].isupper()
                or potential_location.isupper()
                or potential_location.lower() in known_locations
            ):
                merchant = parts[0].strip()
                location = potential_location
            else:
                merchant = merchant_raw
        else:
            merchant = merchant_raw

    if merchant is None:
        to_match = re.search(
            r"\s+to\s+([^\.]+?)\s+with\s+Credit\s+Card",
            text,
            re.IGNORECASE,
        )
        if to_match:
            merchant = to_match.group(1).strip()

    if merchant is not None:
        merchant = re.sub(r"\s+", " ", merchant).strip()
    return merchant, location


def parse_emirates_nbd_sms(source: SourceParserInput) -> SourceParseResult:
    """Return one normalized observation for a supported SMS message."""
    text = (source.raw_text or "").strip()
    if not text:
        return SourceParseResult(ParseStatus.FAILED, error="The SMS is empty")

    lowered = text.lower()
    if "mini stmt" in lowered or "statement date" in lowered:
        return SourceParseResult(
            ParseStatus.IGNORED,
            error="Non-transaction message (statement)",
        )
    if "this is to remind you" in lowered or "upcoming payment" in lowered:
        return SourceParseResult(
            ParseStatus.IGNORED,
            error="Non-transaction message (reminder)",
        )
    if "beneficiary" in lowered:
        return SourceParseResult(
            ParseStatus.IGNORED,
            error="Non-transaction message (beneficiary)",
        )

    amount: Decimal | None = None
    currency: str | None = None
    description: str | None = None
    location: str | None = None
    transaction_kind = "other"

    refund_match = re.search(
        r"Purchase\s+amount\s+of\s+([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)\s+at\s+"
        r"(.+?)\s+on\s+your\s+Credit\s+Card.*?has\s+been\s+refunded",
        text,
        re.IGNORECASE,
    )
    if refund_match:
        currency = refund_match.group(1).upper()
        parsed_amount = _amount(refund_match.group(2))
        amount = abs(parsed_amount) if parsed_amount is not None else None
        description = refund_match.group(3).strip()
        transaction_kind = "refund"

    if amount is None:
        credit_match = re.search(
            r"Amount\s+of\s+([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)\s+from\s+"
            r"(.+?)\s+has\s+been\s+credited\s+to\s+your\s+card",
            text,
            re.IGNORECASE,
        )
        if credit_match:
            currency = credit_match.group(1).upper()
            parsed_amount = _amount(credit_match.group(2))
            amount = abs(parsed_amount) if parsed_amount is not None else None
            description = credit_match.group(3).strip()
            transaction_kind = "refund"

    if amount is None:
        bill_payment_match = re.search(
            r"([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)\s+has\s+been\s+deducted\s+"
            r"from\s+your\s+account.*?towards\s+payment\s+of\s+your\s+Credit\s+Card",
            text,
            re.IGNORECASE,
        )
        if bill_payment_match:
            currency = bill_payment_match.group(1).upper()
            parsed_amount = _amount(bill_payment_match.group(2))
            amount = abs(parsed_amount) if parsed_amount is not None else None
            description = "Credit Card Bill Payment"
            transaction_kind = "topup"

    if amount is None:
        transaction_match = re.search(
            r"(Purchase|Payment)\s+of\s+([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)",
            text,
            re.IGNORECASE,
        )
        if transaction_match:
            currency = transaction_match.group(2).upper()
            parsed_amount = _amount(transaction_match.group(3))
            amount = -abs(parsed_amount) if parsed_amount is not None else None
            transaction_kind = "purchase"

    if amount is None:
        fallback = re.search(r"([A-Z]{3})\s+([\d,]+(?:\.\d{2})?)", text)
        if fallback:
            currency = fallback.group(1).upper()
            parsed_amount = _amount(fallback.group(2))
            amount = -abs(parsed_amount) if parsed_amount is not None else None

    if amount is None or currency is None:
        return SourceParseResult(
            ParseStatus.FAILED,
            error="No financial transaction could be extracted from the SMS",
        )

    if description is None:
        description, location = _merchant_and_location(text)
    description = description or text
    card_match = re.search(
        r"(?:Credit\s+)?card\s+ending\s+(?:with\s+)?(\d{4})",
        text,
        re.IGNORECASE,
    )
    card_last_four = card_match.group(1) if card_match else None

    return SourceParseResult(
        ParseStatus.PROCESSED,
        observations=(
            ParsedObservation(
                source_item_key="0",
                amount=amount,
                currency=currency,
                transaction_datetime=_metadata_datetime(source, "transaction_datetime"),
                description=description,
                transaction_kind=transaction_kind,
                location=location,
                account_id=source.ingestion_metadata.get("account_id"),
                card_id=source.ingestion_metadata.get("card_id"),
                card_last_four=card_last_four,
                raw_fragment=source.raw_text,
            ),
        ),
    )
