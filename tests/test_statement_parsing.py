"""Focused parser checks for Emirates NBD source formats."""

from io import BytesIO
from pathlib import Path
import sys
import unittest

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
