"""Reading a bank statement export, and guessing who paid.

The fixture is the ICICI "Detailed Statement" layout line for line: sixteen rows of account
details, the header on row 17, amounts in the Indian grouping, a legend under the table.
The fourteen transactions are the ones on the first page of a real export.

No DB, no network — services/bank_statement is pure.

Run:  python -m unittest tests.test_bank_statement      (from backend/)
"""

import io
import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openpyxl import Workbook  # noqa: E402

from app.services import bank_statement as bs  # noqa: E402

HEADER = ["S.N.", "Tran. Id", "Value Date", "Transaction Date", "Transaction Posted Date",
          "Cheque. No./Ref. No.", "Transaction Remarks", "Withdrawal Amt (INR)",
          "Deposit Amt (INR)", "Balance (INR)"]

LINES = [
    ("M3149778", "01/Sep/2026", "01/09/26 11:21:55 AM", "TRF/NA/054859/ICI/31.08.2026", "", "2,72,119.00", "22,27,727.17"),
    ("S67242945", "01/Sep/2026", "01/09/26 05:03:54 PM", "NEFT-HDFCH01229825964-ADITI DHAR-0001F", "", "17,920.00", "22,45,647.17"),
    ("S68355106", "01/Sep/2026", "01/09/26 06:23:38 PM", "BIL/ONL/001242784076/AIR IQ PRI/MONEYYAT", "14,017.70", "", "22,31,629.47"),
    ("S78984896", "02/Sep/2026", "02/09/26 03:35:25 PM", "INF/INFT/045724293821/UNICORN", "63,000.00", "", "21,68,629.47"),
    ("S79565846", "02/Sep/2026", "02/09/26 04:29:26 PM", "MMT/IMPS/624516076528/ACMETRAVELS/AKASH", "20,000.00", "", "21,48,629.47"),
    ("S81134634", "02/Sep/2026", "02/09/26 06:28:00 PM", "BIL/BPAY/FI25046935/ICICI BANK CRED//41020", "3,00,000.00", "", "18,48,629.47"),
    ("S81153910", "02/Sep/2026", "02/09/26 06:29:34 PM", "RTGS/ICICR42026090200569477/INDB0000018", "2,00,000.00", "", "16,48,629.47"),
    ("S81298133", "02/Sep/2026", "02/09/26 06:39:15 PM", "NEFT-SBIN226245450523-VISION PLUS SECU", "", "52,981.00", "17,01,610.47"),
    ("S81530940", "02/Sep/2026", "02/09/26 07:03:14 PM", "INF/NEFT/IN42624557542923/SCBL0036085/M", "50,000.00", "", "16,51,610.47"),
    ("S87014732", "03/Sep/2026", "03/09/26 08:37:30 AM", "ATD/Auto Debit CC1xx7183", "1,13,042.00", "", "15,38,568.47"),
    ("S90122557", "03/Sep/2026", "03/09/26 01:31:41 PM", "NEFT-AXSK262460003484-HILFEN PHARMACE", "", "42,646.00", "15,81,214.47"),
    ("S93985969", "03/Sep/2026", "03/09/26 07:01:38 PM", "RTGS-KKBKR22026090324637579-ORIX CORP", "", "11,73,797.40", "27,55,011.87"),
    ("S111294", "04/Sep/2026", "04/09/26 11:39:08 AM", "INF/INFT/045748550501/MEHAK", "90,000.00", "", "26,65,011.87"),
    ("S122087", "04/Sep/2026", "04/09/26 11:40:36 AM", "INF/INFT/045748561671/MEHAK", "90,000.00", "", "25,75,011.87"),
]


def icici_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append([])
    ws.append(["Detailed Statement"])
    ws.append(["Name:", "ACME TRAVELS", "", "", "", "Account Currency:", "INR"])
    ws.append(["Address:", "C-1/120,JANAKPURI,NEAR ALLAHABAD BANK,NEW DELHI,110058,DELHI,INDIA", "", "", "", "A/C Branch:", "NEW DELHI - JANAKPURI"])
    ws.append(["A/C No:", "008705006910", "", "", "", "Branch Address:", "MAHATTA TOWERS, 54, B-BLOCK"])
    ws.append(["A/C Type:", "CAA", "", "", "", "Cust Id:", "525294042"])
    ws.append(["Jt. Holder:", "", "", "", "", "Branch Code:", "0087"])
    ws.append(["Transaction Date from:", "01/09/2026", "", "", "", "IFSC Code:", "ICIC0000087"])
    ws.append(["Transaction Period", "From 01/09/2026 To 22/09/2026"])
    ws.append(["Statement Request/Download Date:", "22/09/2026"])
    ws.append(["Advanced Search"])
    ws.append(["Amount from:", "NA", "To", "NA"])
    ws.append(["Cheque number from:", "NA", "To", "NA"])
    ws.append(["Transaction remarks:"])
    ws.append(["Transaction type:", "CR"])
    ws.append([])
    ws.append(HEADER)
    for i, (tid, d, posted, remarks, wd, dep, bal) in enumerate(LINES, start=1):
        ws.append([str(i), tid, d, d, posted, "", remarks, wd, dep, bal])
    ws.append([])
    ws.append(["Legends Used in Account Statement"])
    ws.append(["INF - Internet Fund Transfer"])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


class ParseStatementTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.st = bs.parse_statement(icici_xlsx(), "OpTransactionHistory.xlsx")

    def test_account_details_come_from_the_header_block(self):
        self.assertEqual(self.st.account_name, "ACME TRAVELS")
        self.assertEqual(self.st.account_no, "008705006910")
        self.assertEqual(self.st.ifsc, "ICIC0000087")
        self.assertEqual(self.st.bank_name, "ICICI Bank")
        self.assertEqual(self.st.currency, "INR")
        self.assertEqual((self.st.period_from, self.st.period_to), (date(2026, 9, 1), date(2026, 9, 22)))

    def test_every_transaction_and_nothing_else(self):
        self.assertEqual(len(self.st.rows), 14)
        self.assertEqual(self.st.ignored_lines, 2)          # the two legend lines

    def test_indian_grouped_amounts_add_up(self):
        self.assertEqual(sum(r.deposit for r in self.st.rows), Decimal("1559463.40"))
        self.assertEqual(sum(r.withdrawal for r in self.st.rows), Decimal("940059.70"))
        self.assertEqual(self.st.rows[11].deposit, Decimal("1173797.40"))
        self.assertEqual(self.st.rows[0].balance, Decimal("2227727.17"))

    def test_dates_and_direction(self):
        r = self.st.rows[1]
        self.assertEqual(r.txn_date, date(2026, 9, 1))
        self.assertEqual(r.posted_at, datetime(2026, 9, 1, 17, 3, 54))
        self.assertEqual(r.direction, "in")
        self.assertEqual(self.st.rows[2].direction, "out")
        self.assertEqual(r.line_no, 2)
        self.assertEqual(r.tran_id, "S67242945")


class RemarksTests(unittest.TestCase):

    def test_counterparty_from_each_remark_shape(self):
        cases = {
            "NEFT-HDFCH01229825964-ADITI DHAR-0001F": "ADITI DHAR",
            "RTGS-KKBKR22026090324637579-ORIX CORP": "ORIX CORP",
            "NEFT-AXSK262460003484-HILFEN PHARMACE": "HILFEN PHARMACE",
            "BIL/ONL/001242784076/AIR IQ PRI/MONEYYAT": "AIR IQ PRI",
            "INF/INFT/045724293821/UNICORN": "UNICORN",
            "BIL/BPAY/FI25046935/ICICI BANK CRED//41020": "ICICI BANK CRED",
            # The sender of an outgoing IMPS is the account holder — skipped.
            "MMT/IMPS/624516076528/ACMETRAVELS/AKASH": "AKASH",
            # No name at all: a transfer code, a reference and a date.
            "TRF/NA/054859/ICI/31.08.2026": None,
            "RTGS/ICICR42026090200569477/INDB0000018": None,
        }
        for remark, want in cases.items():
            with self.subTest(remark=remark):
                self.assertEqual(bs.counterparty(remark, "ACME TRAVELS"), want)

    def test_categories(self):
        self.assertEqual(bs.guess_category("NEFT-HDFC-ADITI DHAR", "in"), "receipt")
        self.assertEqual(bs.guess_category("BIL/BPAY/FI25046935/ICICI BANK CRED//41020", "out"), "credit_card")
        self.assertEqual(bs.guess_category("ATD/Auto Debit CC1xx7183", "out"), "credit_card")
        self.assertEqual(bs.guess_category("BIL/ONL/001242784076/AIR IQ PRI/MONEYYAT", "out"), "vendor_payment")
        self.assertEqual(bs.guess_category("INF/INFT/045748550501/MEHAK", "out"), "other")

    def test_payment_mode_and_reference(self):
        self.assertEqual(bs._mode("NEFT-HDFCH01229825964-ADITI DHAR"), "neft")
        self.assertEqual(bs._mode("RTGS-KKBKR22026090324637579-ORIX CORP"), "rtgs")
        self.assertEqual(bs._mode("MMT/IMPS/624516076528/ACMETRAVELS/AKASH"), "imps")
        self.assertEqual(bs._mode("INF/INFT/045724293821/UNICORN"), "transfer")
        self.assertEqual(bs.reference("NEFT-HDFCH01229825964-ADITI DHAR-0001F"), "HDFCH01229825964")


class MatchingTests(unittest.TestCase):

    def test_truncated_bank_names_still_match(self):
        self.assertGreaterEqual(bs.name_score("HILFEN PHARMACE", "Hilfen Pharmaceuticals Pvt Ltd"), 0.85)
        self.assertGreaterEqual(bs.name_score("VISION PLUS SECU", "Vision Plus Securities Pvt. Ltd."), 0.85)
        self.assertEqual(bs.name_score("ORIX CORP", "ORIX Corporation India Ltd"), 1.0)
        self.assertEqual(bs.name_score("ADITI DHAR", "Aditi Dhar"), 1.0)
        # Cut in the middle of "Private".
        self.assertEqual(bs.name_score("AIR IQ PRI", "Air IQ Private Limited"), 1.0)

    def test_a_different_person_does_not_match(self):
        self.assertLess(bs.name_score("ADITI DHAR", "Aditi Sharma"), 0.6)
        self.assertEqual(bs.name_score("AKA", "Akash Travels"), 0.0)     # too short to trust

    def test_suggest_picks_the_best_and_refuses_a_tie(self):
        cands = [
            bs.Candidate("corporate", 1, "Hilfen Pharmaceuticals Pvt Ltd"),
            bs.Candidate("customer", 7, "Aditi Dhar"),
            bs.Candidate("corporate", 2, "Orix Corporation India Ltd"),
        ]
        best, score = bs.suggest("ADITI DHAR", cands)
        self.assertEqual((best.party_type, best.party_id), ("customer", 7))
        self.assertIsNone(bs.suggest("NOBODY KNOWN", cands))
        twins = cands + [bs.Candidate("customer", 8, "Aditi Dhar")]
        self.assertIsNone(bs.suggest("ADITI DHAR", twins))

    def test_dedupe_key_is_stable_and_distinguishes_lines(self):
        st = bs.parse_statement(icici_xlsx())
        keys = [bs.dedupe_key(st.account_no, r) for r in st.rows]
        self.assertEqual(len(set(keys)), len(keys))
        again = bs.parse_statement(icici_xlsx())
        self.assertEqual(keys, [bs.dedupe_key(again.account_no, r) for r in again.rows])


class BadFileTests(unittest.TestCase):

    def test_a_sheet_without_a_transactions_table_is_refused(self):
        wb = Workbook()
        wb.active.append(["Name", "Amount"])
        wb.active.append(["x", "1"])
        bio = io.BytesIO()
        wb.save(bio)
        with self.assertRaises(bs.StatementError):
            bs.parse_statement(bio.getvalue(), "x.xlsx")


if __name__ == "__main__":
    unittest.main()
