"""Focused parser checks for Emirates NBD source formats."""

from io import BytesIO
from pathlib import Path
import sys
import unittest
from datetime import UTC, datetime

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from pypdf import PdfWriter

from app.utils.source_parsing import InvalidSourceInputError, SourceParserInput
from app.utils.source_parsing.emirates_nbd.credit_card_statement import (
    parse_emirates_nbd_credit_card_statement,
    parse_emirates_nbd_statement_text,
)


SYNTHETIC_STATEMENT = """
Emirates NBD
Credit Card Statement
Card Number: 9999 XXXX XXXX 1111
Card Type: Synthetic Rewards
Statement Period: 01-Jan-26 to 31-Jan-26
Available Credit Limit (AED)
Transaction Date Posting Date Description Amount
01/01/2026 02/01/2026 SYNTHETIC FOREIGN SHOP USA 10.00 USD 36.73
(1 AED = USD 0.27226)
03/01/2026 03/01/2026 SYNTHETIC REFUND 5.00CR
04/01/2026 04/01/2026 TRANSFER PAYMENT RECEIVED THANK YOU 20.00CR
05/01/2026 INSTALLMENT PLAN EMI (2/3) 100.00
LOC-SYNTHETIC-1 300.00
Remaining Principle Balance 100.00
STATEMENT SUMMARY
Previous Statement Purchase / Cash Advance Interest/Other Charges Payments/Credits Total Payment Due Current Balance
0.00 136.73 0.00 25.00 111.73 111.73
"""

SPLIT_DOCUMENT_TEXT = """
Emirates NBD Bank
Credit Card Statement
Available Credit Limit (AED)
Card Number:
Card Type:
Statement Period:
9999 XXXX XXXX 1111
Synthetic Rewards
01-Jan-26 to 31-Jan-26
STATEMENT SUMMARY
Previous Statement Purchase / Cash Advance Interest/Other Charges Payments/Credits Total Payment Due Current Balance
0.00 136.73 0.00 25.00 111.73 111.73
"""

HEADERLESS_LAYOUT_TEXT = """
01/01/2026 02/01/2026 SYNTHETIC FOREIGN SHOP USA 10.00 USD 36.73
(1 AED = USD 0.27226)
03/01/2026 03/01/2026 SYNTHETIC REFUND 5.00CR
04/01/2026 04/01/2026 TRANSFER PAYMENT RECEIVED THANK YOU 20.00CR
05/01/2026 INSTALLMENT PLAN EMI (2/3) 100.00
LOC-SYNTHETIC-1 300.00
Remaining Principle Balance 100.00
"""

INITIAL_INSTALLMENT_STATEMENT = """
Emirates NBD
Credit Card Statement
Card Number: 9999 XXXX XXXX 1111
Card Type: Synthetic Rewards
Statement Period: 26-Jan-25 to 25-Feb-25
Available Credit Limit (AED)
Transaction Date Posting Date Description Amount
18/02/2025 18/02/2025 LOAN ON CARD PROCESSING FEE 130.00
18/02/2025 18/02/2025 VAT ON PROCESSING FEE 6.50
18/02/2025 18/02/2025 LOC-SYNTHETIC-1 300.00
18/02/2025 INSTALLMENT PLAN EMI (01/03) 100.00
LOC-SYNTHETIC-1 300.00
Remaining Principle Balance 200.00
STATEMENT SUMMARY
Previous Statement Purchase / Cash Advance Interest/Other Charges Payments/Credits Total Payment Due Current Balance
0.00 100.00 136.50 0.00 236.50 436.50
"""

SECOND_INSTALLMENT_STATEMENT = """
Emirates NBD
Credit Card Statement
Card Number: 9999 XXXX XXXX 1111
Card Type: Synthetic Rewards
Statement Period: 26-Feb-25 to 25-Mar-25
Available Credit Limit (AED)
Transaction Date Posting Date Description Amount
18/02/2025 INSTALLMENT PLAN EMI (02/03) 100.00
LOC-SYNTHETIC-1 300.00
Remaining Principle Balance 100.00
STATEMENT SUMMARY
Previous Statement Purchase / Cash Advance Interest/Other Charges Payments/Credits Total Payment Due Current Balance
236.50 100.00 0.00 0.00 336.50 436.50
"""

MULTI_CARD_PAGE_ONE = """
Emirates NBD
Credit Card Statement
Card Number: 9999 XXXX XXXX 1111
Card Type: Synthetic Rewards
Statement Period: 01-Jan-26 to 31-Jan-26
Available Credit Limit (AED)
Transaction Date Posting Date Description Amount
Primary Card Number
SYNTHETIC HOLDER: 9999 XXXX XXXX 1111
01/01/2026 02/01/2026 PRIMARY CARD PURCHASE 10.00
Primary Card Number
SYNTHETIC HOLDER: 8888 XXXX XXXX 2222
03/01/2026 04/01/2026 REPLACED CARD PURCHASE 20.00
"""

MULTI_CARD_PAGE_TWO = """
Card Number: 9999 XXXX XXXX 1111
Transaction Date Posting Date Description Amount
05/01/2026 06/01/2026 REPLACED CARD CONTINUATION 30.00
STATEMENT SUMMARY
Previous Statement Purchase / Cash Advance Interest/Other Charges Payments/Credits Total Payment Due Current Balance
0.00 60.00 0.00 0.00 60.00 60.00
"""


class StatementParserTests(unittest.TestCase):
    def test_metadata_rows_fx_signs_and_summary(self):
        result = parse_emirates_nbd_statement_text([SYNTHETIC_STATEMENT])

        self.assertEqual(result.status.value, "processed")
        self.assertEqual(result.bank_statement.card_last_four, "1111")
        self.assertEqual(result.bank_statement.statement_currency, "AED")
        self.assertEqual(len(result.observations), 4)
        foreign, refund, payment, installment = result.observations
        self.assertEqual(str(foreign.amount), "-36.73")
        self.assertEqual(str(foreign.original_amount), "-10.00")
        self.assertEqual(foreign.original_currency, "USD")
        self.assertEqual(refund.transaction_kind, "refund")
        self.assertEqual(payment.transaction_kind, "topup")
        self.assertIsNone(installment.posting_datetime)
        self.assertIn("LOC-SYNTHETIC-1", installment.description)

    def test_split_metadata_and_headerless_layout(self):
        result = parse_emirates_nbd_statement_text(
            [HEADERLESS_LAYOUT_TEXT],
            document_pages=[SPLIT_DOCUMENT_TEXT],
        )

        self.assertEqual(result.status.value, "processed")
        self.assertEqual(result.bank_statement.card_last_four, "1111")
        self.assertEqual(result.bank_statement.card_type, "Synthetic Rewards")
        self.assertEqual(len(result.observations), 4)

    def test_card_section_applies_to_following_rows_across_pages(self):
        result = parse_emirates_nbd_statement_text(
            [MULTI_CARD_PAGE_ONE, MULTI_CARD_PAGE_TWO]
        )

        self.assertEqual(result.status.value, "processed")
        self.assertEqual(result.bank_statement.card_last_four, "1111")
        self.assertEqual(
            [value.card_last_four for value in result.observations],
            ["1111", "2222", "2222"],
        )

    def test_statement_dates_use_source_timezone_and_preserve_local_dates(self):
        result = parse_emirates_nbd_statement_text(
            [SYNTHETIC_STATEMENT],
            source_timezone="Asia/Dubai",
        )

        foreign = result.observations[0]
        self.assertEqual(
            foreign.transaction_datetime,
            datetime(2025, 12, 31, 20, tzinfo=UTC),
        )
        self.assertEqual(
            foreign.posting_datetime,
            datetime(2026, 1, 1, 20, tzinfo=UTC),
        )
        self.assertEqual(
            foreign.extraction_metadata["local_transaction_date"],
            "2026-01-01",
        )
        self.assertEqual(
            foreign.extraction_metadata["local_posting_date"],
            "2026-01-02",
        )

    def test_installment_principal_is_excluded_and_payments_use_sequence_dates(self):
        first = parse_emirates_nbd_statement_text(
            [INITIAL_INSTALLMENT_STATEMENT], source_timezone="Asia/Dubai"
        )
        second = parse_emirates_nbd_statement_text(
            [SECOND_INSTALLMENT_STATEMENT], source_timezone="Asia/Dubai"
        )

        self.assertEqual(first.status.value, "processed")
        principal = next(
            value
            for value in first.observations
            if value.extraction_metadata.get("statement_entry_type") == "loan_principal"
        )
        first_payment = first.observations[-1]
        second_payment = second.observations[-1]
        self.assertEqual(principal.transaction_kind, "other")
        self.assertTrue(principal.extraction_metadata["excluded_from_summary"])
        self.assertEqual(
            first_payment.extraction_metadata["local_transaction_date"], "2025-02-18"
        )
        self.assertEqual(
            second_payment.extraction_metadata["local_transaction_date"], "2025-03-18"
        )
        self.assertEqual(
            second_payment.extraction_metadata["installment_plan_id"],
            "LOC-SYNTHETIC-1",
        )
        self.assertEqual(second_payment.extraction_metadata["installment_number"], 2)

    def test_wrong_pdf_password_is_rejected(self):
        stream = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("correct-password")
        writer.write(stream)

        with self.assertRaisesRegex(InvalidSourceInputError, "password"):
            parse_emirates_nbd_credit_card_statement(
                SourceParserInput(
                    file_content=stream.getvalue(),
                    password="wrong-password",
                )
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
