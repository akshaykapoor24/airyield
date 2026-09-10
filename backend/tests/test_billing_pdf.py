"""What the invoice PDF must say — no DB, no network.

An invoice is the document a tax authority and the recipient's accountant both
read, and this one is modelled on the paper the business already issues. Four
things about it are not cosmetic:

  * it must identify WHO is charging the tax, by GSTIN. Without that the
    recipient cannot claim input credit, which is most of the point of holding
    the invoice at all.
  * it must name WHICH tax. CGST + SGST and IGST go to different governments and
    the totals are identical, so a reader cannot tell them apart from the money.
  * `Amount` and `Taxable Value` are DIFFERENT NUMBERS. The first is what the
    line cost, the second only the slice GST applies to. On a real sale they
    differ by more than an order of magnitude, and swapping them would misstate
    the tax base.
  * WHO is billed follows the billing's own foreign key: a corporate bill is
    addressed to the company, a direct bill to the traveller by name.

Everything is read from the billing's snapshot. A reprint next year has to
produce the same paper, so nothing is recalculated.

Run:  python -m unittest discover backend/tests
"""

import base64
import os
import re
import sys
import unittest
import zlib
from datetime import date, datetime
from types import SimpleNamespace as N

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.billing_pdf import (  # noqa: E402
    SAC_CODE, _bill_to_lines, _invoice_number, _place_of_supply,
    amount_in_words, build_billing_pdf, supplier_block,
)

TENANT = N(
    name="Money Yatra", domain="moneyyatra.com",
    gst_number="07AASFM5646A1Z6", pan_number="AASFM5646A",
    address="C-1/120, JANAKPURI", city="NEW DELHI", state="Delhi", pincode="110058",
    phone="9911194525\n9810316453", logo_path=None,
)
USER = N(full_name="A User", email="mail.moneyyatra@gmail.com")

CORPORATE = N(
    company="ORIX CORPORATION INDIA LIMITED", first_name=None, last_name=None, title=None,
    email=None, phone=None, gst_no="07AAACO2563P1Z3", pan_no=None,
    address="PLOT NO. D-71/2, RAMA ROAD", city="NEW DELHI", state="Delhi",
    pincode="110015", country=None,
)
PERSON = N(
    company="AC SERVICES PVT LTD", first_name="JATIN", last_name="L K WASNIK", title=None,
    email=None, phone=None, gst_no=None, pan_no=None, state="Delhi",
)

# The reference invoice's own numbers: fare 25,57,526 + markup 95,700 = 26,53,226
# before tax, GST on the markup alone at 9 + 9, total 26,70,452.
LINE = {
    "ticket_number": "0581", "passenger": "BATCH-1-17AUG-GOI", "airline_name": "GOAIR",
    "airlines_code": "G8", "sector": "GOI-GOI", "ticket_date": "18-08-2026",
    "base_amount": 2557526.0, "markup_amount": 95700.0, "additional_markup": 0.0,
    "discount": 0.0, "gst_amount": 17226.0, "cgst": 8613.0, "sgst": 8613.0, "igst": 0.0,
    "total": 2670452.0,
}
# The same sale billed across a state line.
LINE_IGST = {**LINE, "cgst": 0.0, "sgst": 0.0, "igst": 17226.0}
# A bill raised before billing_gst_split_01: real tax, no heads, no such keys.
LINE_LEGACY = {k: v for k, v in LINE.items() if k not in ("cgst", "sgst", "igst")}


def _billing(**kw):
    base = dict(
        id=99, created_at=datetime(2026, 8, 18), period_from=date(2026, 8, 1),
        period_to=date(2026, 8, 31), billing_type="agency", billing_name="ORIX AUG",
        total_base=2557526.0, total_markup=95700.0, total_additional_markup=0.0,
        total_gst=17226.0, total_cgst=8613.0, total_sgst=8613.0, total_igst=0.0,
        gst_treatment="cgst_sgst", supplier_state_code="07", place_of_supply_code="07",
        grand_total=2670452.0, line_items=[LINE],
        customer_id=None, corporate_id=7, agency_id=None,
    )
    base.update(kw)
    return N(**base)


def pdf_text(buf) -> str:
    """The visible strings. reportlab writes ASCII85 + Flate, so undo both."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", buf.getvalue(), re.S):
        chunk = m.group(1).strip()
        try:
            chunk = base64.a85decode(chunk, adobe=True)
        except Exception:
            pass
        try:
            chunk = zlib.decompress(chunk)
        except zlib.error:
            pass
        out.append(chunk.decode("latin-1", "ignore"))
    text = " ".join(re.findall(r"\((.*?)\)\s*Tj", "\n".join(out)))
    # PDF escapes parentheses inside strings, and collapses the runs of spaces
    # used for alignment — normalise both so assertions read naturally.
    text = text.replace("\\(", "(").replace("\\)", ")")
    return re.sub(r"\s+", " ", text)


def packed(text: str) -> str:
    """The same text with every space removed.

    reportlab kerns a string into several show operations — "18.00" comes back
    from the extractor as "18.0" then "0" — so a figure has to be matched
    against the run of characters rather than the spacing between them. The
    rendered page is correct either way; this is only about reading it back.
    """
    return text.replace(" ", "")


def render(party=CORPORATE, **kw) -> str:
    return pdf_text(build_billing_pdf(_billing(**kw), party, supplier_block(TENANT, USER)))


class TestAmountInWords(unittest.TestCase):
    """Indian grouping — crore / lakh / thousand, not millions.

    A western grouping would be wrong on every invoice over a lakh, which is
    most of them.
    """

    def test_the_reference_invoice_total(self):
        self.assertEqual(
            amount_in_words(2670452),
            "Twenty Six Lakh Seventy Thousand Four Hundred Fifty Two Only.",
        )

    def test_crore_lakh_thousand(self):
        self.assertEqual(
            amount_in_words(12345678),
            "One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight Only.",
        )

    def test_exact_groups_do_not_trail_empty_words(self):
        self.assertEqual(amount_in_words(1500000), "Fifteen Lakh Only.")
        self.assertEqual(amount_in_words(250000000), "Twenty Five Crore Only.")

    def test_zero_and_paise(self):
        self.assertEqual(amount_in_words(0), "Zero Only.")
        # Paise are dropped, matching how the reference invoice words a total.
        self.assertEqual(amount_in_words(999.87), "Nine Hundred Ninety Nine Only.")

    def test_a_credit_note_is_worded_as_its_magnitude(self):
        self.assertEqual(amount_in_words(-8260), "Eight Thousand Two Hundred Sixty Only.")


class TestSupplierBlock(unittest.TestCase):
    def test_it_carries_the_tax_ids_and_the_letterhead(self):
        """The bug this fixed: the FROM block used to be name + domain + email,
        so the invoice never said who was charging the tax."""
        got = supplier_block(TENANT, USER)
        self.assertEqual(got["gst_number"], "07AASFM5646A1Z6")
        self.assertEqual(got["pan_number"], "AASFM5646A")
        self.assertEqual(got["city"], "NEW DELHI")
        self.assertIn("9911194525", got["phone"])

    def test_a_missing_tenant_does_not_crash(self):
        """A workspace can be deleted out from under a user mid-session."""
        got = supplier_block(None, USER)
        self.assertEqual(got["name"], "A User")
        self.assertIsNone(got["gst_number"])


class TestLetterhead(unittest.TestCase):
    def test_the_supplier_identity_is_printed(self):
        text = render()
        self.assertIn("Money Yatra", text)
        self.assertIn("GST NO. : 07AASFM5646A1Z6", text)
        self.assertIn("C-1/120, JANAKPURI", text)
        self.assertIn("Email : mail.moneyyatra@gmail.com", text)

    def test_both_phone_numbers_are_printed(self):
        text = render()
        self.assertIn("Tel :", text)
        self.assertIn("9911194525", text)
        self.assertIn("9810316453", text)

    def test_it_is_titled_a_tax_invoice(self):
        self.assertIn("TAX INVOICE", render())

    def test_a_workspace_with_no_letterhead_still_renders(self):
        """6 of 8 live workspaces have no address, phone or GSTIN."""
        bare = N(name="Bare Co", domain=None, gst_number=None, pan_number=None,
                 address=None, city=None, state=None, pincode=None, phone=None, logo_path=None)
        text = pdf_text(build_billing_pdf(_billing(), CORPORATE, supplier_block(bare, USER)))
        self.assertIn("Bare Co", text)
        self.assertIn("TAX INVOICE", text)


class TestInvoiceNumber(unittest.TestCase):
    """Prefix / Indian financial year / serial, as the reference invoice reads."""

    def test_the_financial_year_runs_april_to_march(self):
        agency = supplier_block(TENANT, USER)
        self.assertEqual(_invoice_number(_billing(), agency), "MY/26-27/0099")
        # March is still the PREVIOUS financial year.
        march = _billing(created_at=datetime(2026, 3, 31))
        self.assertEqual(_invoice_number(march, agency), "MY/25-26/0099")
        april = _billing(created_at=datetime(2026, 4, 1))
        self.assertEqual(_invoice_number(april, agency), "MY/26-27/0099")

    def test_a_one_word_name_uses_its_first_two_letters(self):
        self.assertTrue(_invoice_number(_billing(), {"name": "gtmvantage"}).startswith("GT/"))

    def test_a_nameless_workspace_still_gets_a_number(self):
        self.assertTrue(_invoice_number(_billing(), {}).startswith("INV/"))


class TestPlaceOfSupply(unittest.TestCase):
    def test_it_reads_code_and_state(self):
        self.assertEqual(_place_of_supply(_billing()), "07-Delhi")
        self.assertEqual(_place_of_supply(_billing(place_of_supply_code="27")), "27-Maharashtra")

    def test_a_pre_split_billing_has_none_to_show(self):
        """Guessing one would put a claim on the invoice that nobody made."""
        self.assertEqual(_place_of_supply(_billing(place_of_supply_code=None)), "—")

    def test_it_is_printed(self):
        self.assertIn("Place of Supply", render())
        self.assertIn("07-Delhi", render())


class TestWhoIsBilled(unittest.TestCase):
    """The business's rule: a corporate is billed as the corporate, a direct
    sale is billed to the traveller by name."""

    def test_a_corporate_bill_is_addressed_to_the_company(self):
        head, lines = _bill_to_lines(_billing(corporate_id=7), CORPORATE)
        self.assertEqual(head, "ORIX CORPORATION INDIA LIMITED")
        self.assertIn("PLOT NO. D-71/2, RAMA ROAD", lines)
        self.assertIn("NEW DELHI, Delhi-110015", lines)

    def test_a_direct_bill_is_addressed_to_the_person(self):
        head, lines = _bill_to_lines(_billing(corporate_id=None, customer_id=21), PERSON)
        self.assertEqual(head, "JATIN L K WASNIK")
        # Their employer is context, not the addressee — they are not billing it.
        self.assertIn("AC SERVICES PVT LTD", lines)

    def test_the_recipient_gstin_is_printed_as_party_gst_no(self):
        self.assertIn("Party GST No. 07AAACO2563P1Z3", render())

    def test_a_recipient_without_a_gstin_simply_omits_it(self):
        text = render(party=PERSON, corporate_id=None, customer_id=21)
        self.assertIn("JATIN L K WASNIK", text)
        self.assertNotIn("Party GST No.", text)

    def test_an_agency_bill_falls_back_to_its_name(self):
        shim = N(company="SKYWAY TRAVELS", first_name=None, last_name=None,
                 gst_no="07AAACA7029A1Z9", pan_no=None, email=None, phone=None)
        head, _ = _bill_to_lines(_billing(corporate_id=None, agency_id=3), shim)
        self.assertEqual(head, "SKYWAY TRAVELS")


class TestTheLineTable(unittest.TestCase):
    def test_amount_and_taxable_value_are_disjoint_and_add_up(self):
        """The heart of it: 26,70,452 was charged, and only 95,700 of it was taxable.

        Amount and Taxable Value are the two halves of the line and do not overlap,
        so a reader can add the row across: 25,57,526 + 95,700 + 17,226 = 26,70,452.
        They used to overlap — Amount carried fare + markup (26,53,226) and Taxable
        restated the markup slice of it — which meant the row only reconciled if you
        knew to ignore one of the two columns.
        """
        text = render()
        self.assertIn("2,557,526.00", text)   # the fare — not taxed, agency rule
        self.assertIn("95,700.00", text)      # the markup alone — what IS taxed
        self.assertIn("2,670,452.00", text)   # the line total, tax included
        self.assertNotIn("2,653,226.00", text)  # the old overlapping Amount

    def test_the_row_reconciles(self):
        self.assertEqual(2557526.00 + 95700.00 + 17226.00, 2670452.00)

    def test_a_reseller_is_taxed_on_the_whole_sale(self):
        """Same line, different billing type: the taxable value becomes the lot, so
        the untaxed Amount left beside it is nothing."""
        text = render(billing_type="reseller")
        self.assertIn("2,653,226.00", text)   # now the TAXABLE value, not the Amount

    def test_the_sac_code_is_printed(self):
        self.assertIn(SAC_CODE, render())

    def test_the_ticket_details_are_printed(self):
        text = render()
        self.assertIn("BATCH-1-17AUG-GOI", text)
        self.assertIn("GOI-GOI", text)
        self.assertIn("18-08-2026", text)

    def test_every_head_column_is_present(self):
        text = render()
        for head in ("CGST", "SGST", "IGST", "Taxable", "Hs/Sac"):
            self.assertIn(head, text)


class TestTaxHeads(unittest.TestCase):
    def test_intra_state_charges_nine_and_nine(self):
        text = render()
        self.assertIn("9.00", packed(text))
        self.assertIn("8,613.00", packed(text))
        # The rate that did NOT apply is printed as zero, not left blank — the
        # column has to be readable as "no IGST on this supply".
        self.assertIn("IGST", text)

    def test_inter_state_charges_eighteen_as_igst(self):
        text = render(
            gst_treatment="igst", total_cgst=0.0, total_sgst=0.0, total_igst=17226.0,
            line_items=[LINE_IGST], place_of_supply_code="27",
        )
        self.assertIn("18.00", packed(text))
        self.assertIn("17,226.00", packed(text))
        self.assertIn("27-Maharashtra", text)
        # And the intra-state pair carried nothing.
        self.assertNotIn("8,613.00", packed(text))

    def test_the_tax_total_closes_the_invoice(self):
        text = render()
        self.assertIn("Add GST Tax", text)
        self.assertIn("17,226.00", text)
        self.assertIn("Nett Bill Amount", text)

    def test_a_pre_split_bill_says_its_tax_is_unsplit(self):
        """Its heads are zero but its tax is real. Leaving the columns at zero
        with no explanation would read as 'no tax charged' while the Total
        plainly includes it."""
        text = render(
            gst_treatment=None, total_cgst=0.0, total_sgst=0.0, total_igst=0.0,
            line_items=[LINE_LEGACY], place_of_supply_code=None,
        )
        self.assertIn("not split", text)
        self.assertIn("17,226.00", text)      # still stated
        self.assertIn("Add GST Tax", text)

    def test_a_split_bill_carries_no_such_note(self):
        self.assertNotIn("not split", render())


class TestTheClosingBlock(unittest.TestCase):
    def test_the_total_is_worded(self):
        self.assertIn("Twenty Six Lakh Seventy Thousand Four Hundred Fifty Two Only.", render())

    def test_the_terms_name_the_supplier(self):
        text = render()
        self.assertIn("in favour of Money Yatra", text)
        self.assertIn("FOR MONEY YATRA", text)
        self.assertIn("Authorised Signatory", text)

    def test_jurisdiction_follows_the_supplier_state(self):
        self.assertIn("subject to Delhi Jurisdiction", render())


class TestItStaysOnePage(unittest.TestCase):
    def test_a_single_line_invoice_is_one_page(self):
        raw = build_billing_pdf(_billing(), CORPORATE, supplier_block(TENANT, USER)).getvalue()
        self.assertEqual(len(re.findall(rb"/Type\s*/Page[^s]", raw)), 1)

    def test_a_long_invoice_paginates_with_its_headers(self):
        """repeatRows=2 carries both header rows onto every page — a continuation
        page whose columns are unlabelled cannot be read."""
        many = _billing(line_items=[LINE] * 40)
        raw = build_billing_pdf(many, CORPORATE, supplier_block(TENANT, USER)).getvalue()
        pages = len(re.findall(rb"/Type\s*/Page[^s]", raw))
        self.assertGreater(pages, 1)
        text = pdf_text(io_wrap(raw))
        self.assertGreaterEqual(text.count("Taxable"), pages)

    def test_an_empty_billing_does_not_crash(self):
        text = pdf_text(build_billing_pdf(
            _billing(line_items=[]), CORPORATE, supplier_block(TENANT, USER),
        ))
        self.assertIn("TAX INVOICE", text)


def io_wrap(raw: bytes):
    import io
    return io.BytesIO(raw)


class TestTheLogo(unittest.TestCase):
    def test_a_broken_logo_does_not_break_the_invoice(self):
        """A row can outlive its file, and a customer's invoice must not depend
        on a decorative image."""
        agency = supplier_block(TENANT, USER)
        agency["logo"] = b"this is not an image"
        text = pdf_text(build_billing_pdf(_billing(), CORPORATE, agency))
        self.assertIn("TAX INVOICE", text)

    def test_a_real_logo_is_placed(self):
        try:
            from PIL import Image as PILImage
        except ImportError:
            self.skipTest("Pillow not installed")
        import io
        buf = io.BytesIO()
        PILImage.new("RGB", (200, 80), "white").save(buf, format="PNG")
        agency = supplier_block(TENANT, USER)
        agency["logo"] = buf.getvalue()
        raw = build_billing_pdf(_billing(), CORPORATE, agency).getvalue()
        # An XObject image is only emitted when one was actually drawn.
        self.assertIn(b"/Image", raw)


if __name__ == "__main__":
    unittest.main()
