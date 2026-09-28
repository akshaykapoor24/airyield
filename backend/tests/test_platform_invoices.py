"""Platform invoices: numbering, GST, validation, the printed document and the email.

A tax invoice is read by a tax authority, so the failure modes here are not cosmetic: a
number reused or out of its financial year, CGST+SGST charged on an inter-state supply,
GST charged by a supplier with no GSTIN, or a PDF whose figures disagree with the row.

No DB, no network. Numbering's lock needs Postgres and is exercised end to end instead;
the arithmetic it feeds is covered here.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import asyncio
import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402
import fitz  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.schemas.platform_invoice import InvoiceCreate  # noqa: E402
from app.services import email_service  # noqa: E402
from app.services import platform_invoices as pi  # noqa: E402
from app.services.platform_invoice_pdf import (  # noqa: E402
    build_platform_invoice_pdf, inr, pdf_filename, words,
)

# Valid GSTINs (check digits computed by core/india_tax.gstin_check_digit).
HARYANA_GSTIN = "06AAPFU0939F1ZZ"   # PAN AAPFU0939F
DELHI_GSTIN = "07AABCG1234K1ZU"


def _issuer(**kw):
    raw = {"name": "Fareqube Technologies Pvt Ltd", "state": "Haryana", "gstin": HARYANA_GSTIN,
           "pan": "AAPFU0939F", "bank": {"account_number": "5020001", "ifsc": "hdfc0001234"}}
    raw.update(kw)
    return pi.clean_party(raw, "Your company", bank=True)


def _bill(**kw):
    raw = {"name": "GTMVantage", "state": "Delhi"}
    raw.update(kw)
    return pi.clean_party(raw, "Bill to")


def _lines(*prices, qty="1"):
    return pi.clean_lines([{"description": f"Line {i}", "quantity": qty, "unit_price": p}
                           for i, p in enumerate(prices, start=1)])


class TestNumbering(unittest.TestCase):
    def test_financial_year_turns_on_the_first_of_april(self):
        self.assertEqual(pi.financial_year(date(2027, 3, 31)), "26-27")
        self.assertEqual(pi.financial_year(date(2027, 4, 1)), "27-28")
        self.assertEqual(pi.financial_year(date(2026, 9, 28)), "26-27")
        self.assertEqual(pi.financial_year(date(2099, 12, 1)), "99-00")

    def test_number_format_fits_the_gst_sixteen_character_limit(self):
        number = pi.format_number("26-27", 7, prefix="fq")
        self.assertEqual(number, "FQ/26-27/0007")
        self.assertLessEqual(len(pi.format_number("26-27", 9999, prefix="ABCD")), 16)


class TestParties(unittest.TestCase):
    def test_cleaned_and_canonical(self):
        p = pi.clean_party({"name": "  GTM   Vantage ", "state": "delhi", "gstin": " 07aabcg1234k1zu "}, "Bill to")
        self.assertEqual((p["name"], p["state"], p["gstin"]), ("GTM Vantage", "Delhi", DELHI_GSTIN))

    def test_a_name_is_required(self):
        with self.assertRaisesRegex(pi.InvoiceError, "Bill to: a name is required"):
            pi.clean_party({"name": "  "}, "Bill to")

    def test_an_unknown_state_is_refused(self):
        with self.assertRaisesRegex(pi.InvoiceError, "not an Indian state"):
            pi.clean_party({"name": "X", "state": "Atlantis"}, "Bill to")

    def test_gstin_must_agree_with_the_state(self):
        with self.assertRaisesRegex(pi.InvoiceError, "Bill to: GSTIN starts with '07'"):
            pi.clean_party({"name": "X", "state": "Haryana", "gstin": DELHI_GSTIN}, "Bill to")

    def test_gstin_must_carry_the_pan(self):
        with self.assertRaisesRegex(pi.InvoiceError, "PAN"):
            pi.clean_party({"name": "X", "gstin": HARYANA_GSTIN, "pan": "AABCG1234K"}, "Your company")

    def test_bank_details_are_kept_for_the_issuer_only(self):
        self.assertEqual(_issuer()["bank"]["ifsc"], "HDFC0001234")
        self.assertNotIn("bank", _bill())


class TestLines(unittest.TestCase):
    def test_money_is_exact_to_the_paisa(self):
        (line,) = pi.clean_lines([{"description": "x", "quantity": "3", "unit_price": "0.1"}])
        self.assertEqual(line["amount"], "0.30")

    def test_fractional_quantity_is_kept_as_typed(self):
        (line,) = pi.clean_lines([{"description": "1.5 months", "quantity": "1.50", "unit_price": "1000"}])
        self.assertEqual((line["quantity"], line["amount"]), ("1.5", "1500.00"))

    def test_a_discount_line_may_be_negative(self):
        lines = _lines("1000", "-250")
        self.assertEqual([l["amount"] for l in lines], ["1000.00", "-250.00"])

    def test_problems_name_the_line(self):
        with self.assertRaisesRegex(pi.InvoiceError, "Line 2: a description is required"):
            pi.clean_lines([{"description": "a", "unit_price": "1"}, {"description": "", "unit_price": "1"}])
        with self.assertRaisesRegex(pi.InvoiceError, "Line 1: quantity must be more than zero"):
            pi.clean_lines([{"description": "a", "quantity": "0", "unit_price": "1"}])
        with self.assertRaisesRegex(pi.InvoiceError, "rate must be a number"):
            pi.clean_lines([{"description": "a", "unit_price": "ten"}])
        with self.assertRaisesRegex(pi.InvoiceError, "at least one line"):
            pi.clean_lines([])


class TestTax(unittest.TestCase):
    def test_inter_state_is_igst_on_the_subtotal(self):
        t = pi.compute(_lines("15000", "50", "-1000"), 18, _issuer(), _bill())
        self.assertEqual((t.treatment, t.subtotal, t.igst, t.cgst, t.sgst), ("igst", Decimal("14050.00"),
                         Decimal("2529.00"), 0, 0))
        self.assertEqual((t.grand_total, t.place_of_supply_code), (Decimal("16579.00"), "07"))

    def test_intra_state_splits_in_equal_halves_each_rounded(self):
        t = pi.compute(_lines("14049.45"), 18, _issuer(), _bill(state="Haryana"))
        self.assertEqual((t.treatment, t.cgst, t.sgst, t.igst), ("cgst_sgst", Decimal("1264.45"),
                         Decimal("1264.45"), 0))
        self.assertEqual(t.grand_total, Decimal("16578.35"))

    def test_the_gstin_decides_over_a_typed_state(self):
        """A Delhi GSTIN is a Delhi supply even if nobody filled in the state."""
        t = pi.compute(_lines("100"), 18, _issuer(), _bill(state=None, gstin=DELHI_GSTIN))
        self.assertEqual(t.treatment, "igst")

    def test_no_supplier_gstin_means_no_gst_at_all(self):
        t = pi.compute(_lines("1000"), 18, _issuer(gstin=None, pan=None), _bill())
        self.assertEqual((t.treatment, t.total_tax, t.grand_total), ("none", 0, Decimal("1000.00")))

    def test_a_zero_rate_charges_nothing(self):
        self.assertEqual(pi.compute(_lines("1000"), 0, _issuer(), _bill()).total_tax, 0)

    def test_undecidable_place_of_supply_is_refused_not_guessed(self):
        with self.assertRaisesRegex(pi.InvoiceError, "CGST \\+ SGST or IGST"):
            pi.compute(_lines("1000"), 18, _issuer(), _bill(state=None))

    def test_a_non_positive_total_is_refused(self):
        with self.assertRaisesRegex(pi.InvoiceError, "more than zero"):
            pi.compute(_lines("100", "-100"), 18, _issuer(), _bill())

    def test_rate_bounds(self):
        for rate in (-1, 29):
            with self.subTest(rate=rate), self.assertRaises(pi.InvoiceError):
                pi.compute(_lines("100"), rate, _issuer(), _bill())


class TestDraft(unittest.TestCase):
    def test_a_first_invoice_gets_one_unpriced_subscription_line(self):
        (line,) = pi.carry_lines(None, date(2026, 9, 1))
        self.assertIn("September 2026", line["description"])
        self.assertEqual((line["quantity"], line["unit_price"]), ("1", "0.00"))

    def test_last_months_lines_carry_over_with_the_month_renamed(self):
        previous = SimpleNamespace(period_from=date(2026, 8, 1), line_items=[
            {"description": "Subscription — August 2026", "sac": "998314", "quantity": "1", "unit_price": "15000.00"},
            {"description": "Onboarding", "sac": None, "quantity": "2", "unit_price": "500.00"},
        ])
        lines = pi.carry_lines(previous, date(2026, 9, 1))
        self.assertEqual([l["description"] for l in lines], ["Subscription — September 2026", "Onboarding"])
        self.assertEqual(lines[0]["unit_price"], "15000.00")

    def test_month_period(self):
        self.assertEqual(pi.month_period(date(2026, 2, 14)), (date(2026, 2, 1), date(2026, 2, 28)))


class TestCreateSchema(unittest.TestCase):
    def _payload(self, **kw):
        base = {"invoice_date": "2026-09-28", "issuer": {"name": "F"}, "bill_to": {"name": "G"},
                "lines": [{"description": "x", "unit_price": "1"}]}
        base.update(kw)
        return base

    def test_due_date_before_invoice_date(self):
        with self.assertRaisesRegex(ValidationError, "due date"):
            InvoiceCreate(**self._payload(due_date="2026-09-01"))

    def test_period_needs_both_ends_in_order(self):
        with self.assertRaisesRegex(ValidationError, "both a start and an end"):
            InvoiceCreate(**self._payload(period_from="2026-09-01"))
        with self.assertRaisesRegex(ValidationError, "ends before it starts"):
            InvoiceCreate(**self._payload(period_from="2026-09-30", period_to="2026-09-01"))


def _invoice(**kw):
    issuer, bill = _issuer(), _bill()
    t = pi.compute(_lines("15000", "-999.50"), 18, issuer, bill)
    inv = SimpleNamespace(
        invoice_number="FQ/26-27/0042", invoice_date=date(2026, 9, 28), due_date=date(2026, 10, 13),
        period_from=date(2026, 9, 1), period_to=date(2026, 9, 30), issuer=issuer, bill_to=bill,
        gst_treatment=t.treatment, place_of_supply_code=t.place_of_supply_code, gst_rate=Decimal("18.00"),
        currency="INR", line_items=t.lines, subtotal=t.subtotal, cgst=t.cgst, sgst=t.sgst, igst=t.igst,
        total_tax=t.total_tax, grand_total=t.grand_total, notes="Thank you & welcome <aboard>",
        status="issued", paid_at=None, payment_reference=None, cancel_reason=None,
    )
    for k, v in kw.items():
        setattr(inv, k, v)
    return inv


def _pdf_text(inv) -> str:
    doc = fitz.open(stream=build_platform_invoice_pdf(inv).getvalue(), filetype="pdf")
    return " ".join(page.get_text() for page in doc)


class TestPdf(unittest.TestCase):
    def test_every_stored_figure_is_printed(self):
        text = _pdf_text(_invoice())
        for needle in ("TAX INVOICE", "FQ/26-27/0042", "GTMVantage", HARYANA_GSTIN, "07 - Delhi",
                       "IGST @ 18%", "14,000.50", "2,520.09", "16,520.59", "HDFC0001234",
                       "Thank you & welcome <aboard>"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("CGST", text)

    def test_no_gstin_prints_a_plain_invoice(self):
        text = _pdf_text(_invoice(issuer=_issuer(gstin=None, pan=None), gst_treatment="none"))
        self.assertIn("INVOICE", text)
        self.assertNotIn("TAX INVOICE", text)
        self.assertNotIn("REVERSE CHARGE", text)

    def test_cancelled_says_so_and_hides_the_bank(self):
        text = _pdf_text(_invoice(status="cancelled", cancel_reason="Wrong period"))
        self.assertIn("CANCELLED", text)
        self.assertIn("Wrong period", text)
        self.assertNotIn("HDFC0001234", text)

    def test_paid_carries_its_reference(self):
        text = _pdf_text(_invoice(status="paid", paid_at=date(2026, 10, 2), payment_reference="UTR123"))
        self.assertIn("PAID", text)
        self.assertIn("UTR123", text)

    def test_formatting(self):
        self.assertEqual(inr(Decimal("1234567.5")), "12,34,567.50")
        self.assertEqual(inr(-999.5), "-999.50")
        self.assertEqual(words(Decimal("11800.50")),
                         "Indian Rupees Eleven Thousand Eight Hundred and Fifty Paise Only.")
        self.assertEqual(pdf_filename(_invoice()), "FQ-26-27-0042.pdf")


class TestInvoiceEmail(unittest.TestCase):
    def test_the_pdf_goes_as_an_attachment(self):
        sent = []
        smtp = mock.MagicMock()
        smtp.return_value.__enter__.return_value.send_message.side_effect = sent.append
        with mock.patch.object(email_service.smtplib, "SMTP", smtp):
            asyncio.run(email_service.send_invoice_email(
                "owner@example.com", invoice_number="FQ/26-27/0042", issuer_name="Fareqube",
                recipient_name="GTMVantage", amount="INR 16,520.59", due_date="13 Oct 2026",
                message="Hi <team>", pdf=b"%PDF-1.4 test", filename="FQ-26-27-0042.pdf"))
        (msg,) = sent
        self.assertEqual(msg["Subject"], "Invoice FQ/26-27/0042 from Fareqube")
        (attachment,) = list(msg.iter_attachments())
        self.assertEqual(attachment.get_filename(), "FQ-26-27-0042.pdf")
        self.assertEqual(attachment.get_content(), b"%PDF-1.4 test")
        html = msg.get_body(preferencelist=("html",)).get_content()
        self.assertIn("Hi &lt;team&gt;", html)

    def test_a_failure_is_raised_not_swallowed(self):
        """The admin is told the bill did not go, unlike the signup emails."""
        with mock.patch.object(email_service.smtplib, "SMTP", side_effect=OSError("connection refused")):
            with self.assertRaises(OSError):
                asyncio.run(email_service.send_invoice_email(
                    "owner@example.com", invoice_number="X", issuer_name="F", recipient_name="G",
                    amount="INR 1.00", due_date=None, message=None, pdf=b"%PDF", filename="x.pdf"))


if __name__ == "__main__":
    unittest.main()
