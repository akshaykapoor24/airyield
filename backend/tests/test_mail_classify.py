"""What is this attachment? — statement recognition (services/mail/classify.py).

Files are synthesised from each spec's own headers, so the tests follow the specs instead of
depending on sample files on someone's desktop.

Run:  python -m unittest tests.test_mail_classify      (from backend/)
"""

import csv
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import lcc_detailed_spec, statement_spec as spec  # noqa: E402
from app.services.mail import classify  # noqa: E402


def _csv(headers: list[str], rows: int = 3) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(headers)
    for i in range(rows):
        w.writerow([f"v{i}{j}" for j in range(len(headers))])
    return out.getvalue().encode()


def _spec_headers(slug: str) -> list[str]:
    return [c["header"] for c in spec.columns(slug)] or spec.headers(slug)


class PdfTests(unittest.TestCase):

    def test_bsplink_file_names(self):
        c = classify.classify(b"%PDF-1.4 x", "IN_FCAGBILLDETALT_1436390_20260701.PDF", "application/pdf")
        self.assertEqual((c.kind, c.doc_type, c.family), ("statement", "bsp", "bsp"))
        c = classify.classify(b"%PDF-1.4 x", "IN_FCAGBILLSUMNG_1430023_260701.PDF", "application/pdf")
        self.assertEqual(c.doc_type, "bsp-summary")

    def test_a_deal_sheet_pdf_is_a_deal_not_a_statement(self):
        import fitz
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Deal Sheet Effective 03Oct26 - PLB 3% on basic, incentive 1%")
        c = classify.classify(doc.tobytes(), "Mirror PCC.pdf", "application/pdf")
        self.assertEqual((c.kind, c.doc_type), ("deal", "deal-sheet"))

    def test_a_pdf_with_no_markers_is_other(self):
        import fitz
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Minutes of the review meeting")
        self.assertEqual(classify.classify(doc.tobytes(), "minutes.pdf", "application/pdf").kind, "other")

    def test_bsp_report_code_inside_a_renamed_pdf(self):
        import fitz
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "FCAGBILLDETALT  AGENT BILLING DETAILS")
        c = classify.classify(doc.tobytes(), "statement-july.pdf", "application/pdf")
        self.assertEqual(c.doc_type, "bsp")


class SheetTests(unittest.TestCase):

    def test_lcc_detailed_export(self):
        c = classify.classify(_csv(lcc_detailed_spec.LCC_STANDARD_HEADERS[:60]), "indigolccStat.csv", "text/csv")
        self.assertEqual((c.doc_type, c.family), ("lcc-detailed", "lcc"))

    def test_third_party_api(self):
        c = classify.classify(_csv(_spec_headers("tp-api")), "MiscD.csv", "text/csv")
        self.assertEqual((c.doc_type, c.family), ("tp-api", "third_party"))

    def test_third_party_gds_vs_lcc_comes_from_the_file_name(self):
        headers = _spec_headers("tp-gds")
        self.assertEqual(classify.classify(_csv(headers), "TRIUMPHH BSP STATEMENT 08-15TH AUG 26.csv", "").doc_type, "tp-gds")
        self.assertEqual(classify.classify(_csv(headers), "ACME LCC STATEMENT SEP.csv", "").doc_type, "tp-lcc")
        mo = classify.classify(_csv(headers), "weekly.csv", "", sender_hint="internal")
        self.assertEqual(mo.doc_type, "mo-gds")

    def test_ndc_export(self):
        c = classify.classify(_csv(_spec_headers("ndc")), "AirIndiaStatement.csv", "")
        self.assertEqual(c.doc_type, "ndc")

    def test_divided_pnr_by_file_name(self):
        headers = ["BookingDate", "ParentPNR", "DividedDate", "ChildPNR", "PaymentAmount"]
        c = classify.classify(_csv(headers), "DividePNR_All_08Sep2026_20Sep2026_x.csv", "")
        self.assertEqual(c.doc_type, "lcc-divided-pnr")

    def test_unknown_consolidator_format_is_flagged_not_guessed(self):
        globe = ["Doc Date", "DocNo", "Ticket No.", "PNR No.", "Narration", "Pax Name", "AL",
                 "Basic Fare", "YQ Tax", "K3 Tax", "Discount", "GST", "TDS", "BillAmount"]
        c = classify.classify(_csv(globe), "GLOBE 16 22 AUG 26.csv", "")
        self.assertEqual((c.kind, c.doc_type), ("statement", "unknown"))

    def test_deal_sheet_by_its_columns(self):
        c = classify.classify(_csv(["Airline", "Code", "Economy", "Business", "Validity", "Remarks"]), "Oct.xlsx", "")
        self.assertEqual(c.kind, "deal")

    def test_subject_marks_an_ambiguous_sheet_as_a_deal(self):
        headers = ["Carrier name", "Sector", "Rate", "Valid"]
        self.assertEqual(classify.classify(_csv(headers), "Vendor 23-30SEP.xlsx", "").kind, "other")
        c = classify.classify(_csv(headers), "Vendor 23-30SEP.xlsx", "", context="Fwd: Vendor deal sheet — PLB revised")
        self.assertEqual(c.kind, "deal")

    def test_an_internal_plb_workbook_is_not_a_deal(self):
        self.assertEqual(classify.classify(_csv(["Month", "Revenue", "Target"]), "plb analysis.xlsx", "").kind, "other")

    def test_a_master_file_is_not_a_statement(self):
        c = classify.classify(_csv(["Airline Name", "IATA Code", "ICAO", "Country"]), "airline_master.csv", "")
        self.assertEqual(c.kind, "other")

    def test_unreadable_and_non_statement_types(self):
        self.assertEqual(classify.classify(b"\x89PNG\r\n\x1a\n", "logo.png", "image/png").kind, "other")
        self.assertEqual(classify.classify(b"not a workbook", "broken.xlsx", "").kind, "other")


if __name__ == "__main__":
    unittest.main()
