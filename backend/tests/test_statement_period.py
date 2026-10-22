"""A statement's period, read off its file name or an email — no DB, no network.

The Third Party GDS upload pre-fills its Statement period from the file name, and the email
intake reads the same thing from a subject, a covering note or an attachment's name. Pinned
here on every name in the real sample folder: what reads as a period, what reads as nothing
(and so is asked for), the year when the name gives none, and that the migration's frozen
copy reads exactly the same.

Run:  python -m unittest discover backend/tests
"""
import importlib.util
import os
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import statement_period as sp  # noqa: E402
from app.services.mail import body  # noqa: E402

TODAY = date(2026, 10, 17)
MIGRATION = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
             / "tp_gds_period_01_statement_period.py")


def d(s: str) -> date:
    return date.fromisoformat(s)


# Every statement name in the sample folder (FareQube Docs/TriumphTravel), and what it says.
SAMPLES = {
    "TRIUMPHH BSP STATMENT 01-07TH AUG 26 (5).xlsx": ("2026-08-01", "2026-08-07"),
    "TRIUMPHH BSP STATEMENT 08-15TH AUG 26.xlsx": ("2026-08-08", "2026-08-15"),
    "TRIUMPHH BSP STATEMENT 16-22ND AUG 26.xlsx": ("2026-08-16", "2026-08-22"),
    "TRIUMPHH TRAVELS BSP STATEMENT 23-31ST AUG 26.xlsx": ("2026-08-23", "2026-08-31"),
    "GLOBE OUR 08 15 AUG 26.xls": ("2026-08-08", "2026-08-15"),
    "GLOBE 16 22 AUG 26.xls": ("2026-08-16", "2026-08-22"),
    "GLOBE 23 31 AUG 26.xls": ("2026-08-23", "2026-08-31"),
    "GLOBE 01 AUG TO 31 AUG.xls": ("2026-08-01", "2026-08-31"),
    "TRIUMPHH TRAVEL N MORE PVT LTD(62257)01-Jul-26 To 06-Oct-26.xlsx": ("2026-07-01", "2026-10-06"),
    "Vendor 23-30SEP'26.xlsx": ("2026-09-23", "2026-09-30"),
    "DividePNR_All_08Sep2026_20Sep2026_20260921143112.csv": ("2026-09-08", "2026-09-20"),
    "MY202106031225502005_bookingDate_2026-08-01_2026-08-31_BookingSummary.xlsx": ("2026-08-01", "2026-08-31"),
}
# Names that give no period: the user is asked rather than handed a guess.
NOTHING = [
    "test1.xlsx", "test2.xlsx", "test3.xlsx",
    "YATRA STATEMENT 30 SEP 26.xls",                 # one as-of date, not a period
    "IN_FCAGBILLDETALT_1430023_20260601.PDF",
    "MARKUP 01-07 REPORT.xlsx",                       # MARKUP is not March
    "", None,
]


class FileNameTests(unittest.TestCase):
    def test_every_sample_name(self):
        for name, (start, end) in SAMPLES.items():
            with self.subTest(name=name):
                self.assertEqual(sp.from_file_name(name, TODAY), (d(start), d(end)))

    def test_names_with_no_period(self):
        for name in NOTHING:
            with self.subTest(name=name):
                self.assertIsNone(sp.from_file_name(name, TODAY))

    def test_other_shapes(self):
        cases = {
            "STATEMENT 01.08.2026 TO 07.08.2026.xlsx": ("2026-08-01", "2026-08-07"),
            "TRIUMPHH 01-07TH AUGUST.xlsx": ("2026-08-01", "2026-08-07"),
            "TRIUMPHH 01-07 AUG.xlsx": ("2026-08-01", "2026-08-07"),
            "AUG 01-07 2026.xlsx": ("2026-08-01", "2026-08-07"),
            "stmt 08-15thAug26.xlsx": ("2026-08-08", "2026-08-15"),
            "X 28 JUL - 03 AUG 26.xlsx": ("2026-07-28", "2026-08-03"),
            "C:\\Users\\x\\Downloads\\GLOBE 16 22 AUG 26 - Copy (2).xls": ("2026-08-16", "2026-08-22"),
        }
        for name, (start, end) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(sp.from_file_name(name, TODAY), (d(start), d(end)))

    def test_a_copy_suffix_is_not_a_day(self):
        self.assertEqual(sp.from_file_name("TRIUMPHH 01-07TH AUG 26 (5).xlsx", TODAY),
                         sp.from_file_name("TRIUMPHH 01-07TH AUG 26.xlsx", TODAY))

    def test_the_week_column_reads_the_same(self):
        self.assertEqual(sp.find_period("01-07TH AUG 26", TODAY), (d("2026-08-01"), d("2026-08-07")))
        self.assertEqual(sp.find_period("23-30SEP", TODAY), (d("2026-09-23"), d("2026-09-30")))


class YearTests(unittest.TestCase):
    def test_no_year_is_the_latest_period_that_has_ended(self):
        self.assertEqual(sp.from_file_name("X 20-31 DEC.xlsx", TODAY), (d("2025-12-20"), d("2025-12-31")))
        self.assertEqual(sp.from_file_name("X 20-31 DEC.xlsx", date(2027, 1, 5)),
                         (d("2026-12-20"), d("2026-12-31")))

    def test_a_period_still_running_is_this_years(self):
        self.assertEqual(sp.from_file_name("X 01-07 OCT.xlsx", date(2026, 10, 5)),
                         (d("2026-10-01"), d("2026-10-07")))

    def test_across_the_year_end(self):
        self.assertEqual(sp.from_file_name("X 28 DEC - 03 JAN.xlsx", TODAY), (d("2025-12-28"), d("2026-01-03")))
        self.assertEqual(sp.from_file_name("X 28 DEC 26 - 03 JAN 27.xlsx", TODAY),
                         (d("2026-12-28"), d("2027-01-03")))

    def test_a_year_is_two_or_four_digits(self):
        """"245 tickets" is a count, not the year 245 (it used to be, in the email reader)."""
        text = "PFA statement for 08-15th Aug, 245 tickets, net payable ₹12,34,567"
        self.assertEqual(sp.find_period(text, TODAY), (d("2026-08-08"), d("2026-08-15")))

    def test_impossible_or_backwards_dates_are_not_a_period(self):
        for text in ("01-31 SEP 26", "07-01 AUG 26", "29-30 FEB 26"):
            with self.subTest(text=text):
                self.assertIsNone(sp.find_period(text, TODAY))


class HelperTests(unittest.TestCase):
    def test_overlaps_share_a_day(self):
        a = (d("2026-08-01"), d("2026-08-07"))
        self.assertTrue(sp.overlaps(*a, d("2026-08-07"), d("2026-08-15")))
        self.assertTrue(sp.overlaps(*a, d("2026-08-01"), d("2026-08-15")))
        self.assertTrue(sp.overlaps(*a, d("2026-08-03"), d("2026-08-04")))
        self.assertFalse(sp.overlaps(*a, d("2026-08-08"), d("2026-08-15")))
        self.assertFalse(sp.overlaps(d("2026-08-08"), d("2026-08-15"), *a))

    def test_label(self):
        self.assertEqual(sp.label(d("2026-08-01"), d("2026-08-07")), "01–07 Aug 2026")
        self.assertEqual(sp.label(d("2026-07-28"), d("2026-08-03")), "28 Jul – 03 Aug 2026")
        self.assertEqual(sp.label(d("2025-12-28"), d("2026-01-03")), "28 Dec 2025 – 03 Jan 2026")
        self.assertEqual(sp.label(None, None), "—")


class EmailFactsTests(unittest.TestCase):
    """services/mail/body.py reads the period with the same code."""

    def test_the_covering_note(self):
        f = body.facts("Statement", "PFA statement for 08-15th Aug, 245 tickets, net payable 12,34,567",
                       today=TODAY)
        self.assertEqual((f["period_from"], f["period_to"]), ("2026-08-08", "2026-08-15"))
        self.assertEqual(f["expected_count"], 245)

    def test_an_attachment_name(self):
        f = body.facts("Fwd: statement", None, "GLOBE 01 AUG TO 31 AUG.xls", today=TODAY)
        self.assertEqual((f["period_from"], f["period_to"]), ("2026-08-01", "2026-08-31"))

    def test_the_other_facts_still_read(self):
        f = body.facts("Deal w.e.f. 01 Oct 2026 valid till 31 Oct 2026", today=TODAY)
        self.assertEqual((f["effective_from"], f["valid_to"]), ("2026-10-01", "2026-10-31"))
        self.assertNotIn("period_from", f)


class MigrationParityTests(unittest.TestCase):
    """tp_gds_period_01 backfills with a frozen copy of the reader; it must read the same."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("tp_gds_period_01", MIGRATION)
        cls.mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mig)

    def test_frozen_reader_agrees(self):
        names = [*SAMPLES, *[n for n in NOTHING if n], "X 20-31 DEC.xlsx", "X 28 DEC - 03 JAN.xlsx",
                 "STATEMENT 01.08.2026 TO 07.08.2026.xlsx", "AUG 01-07 2026.xlsx"]
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(self.mig.from_file_name(name, TODAY), sp.from_file_name(name, TODAY))
        for week in ("01-07TH AUG 26", "08-15TH AUG 26", "16-22ND AUG 26", "23-31ST AUG 26", "junk"):
            with self.subTest(week=week):
                self.assertEqual(self.mig.find_period(week, TODAY), sp.find_period(week, TODAY))


class SideTests(unittest.TestCase):
    """A line's date against its period — the review step's out-of-period flag."""
    WEEK = (date(2026, 8, 1), date(2026, 8, 7))

    def test_both_ends_are_inside(self):
        for v in ("2026-08-01", "2026-08-07", "2026-08-04 00:00:00"):
            with self.subTest(v=v):
                self.assertIsNone(sp.side(v, self.WEEK))

    def test_before_after_and_not_a_date(self):
        self.assertEqual(sp.side("2026-07-31", self.WEEK), "before")
        self.assertEqual(sp.side("2026-08-08", self.WEEK), "after")
        self.assertEqual(sp.side("N/A", self.WEEK), "unreadable")

    def test_the_report_lists_the_first_lines_and_marks_every_row(self):
        out = sp.OutsidePeriod(self.WEEK, [{"index": i, "outside": {"doc_date": "after"}}
                                           for i in range(sp.OUTSIDE_LISTED + 5)])
        d = out.as_dict()
        self.assertEqual((d["count"], len(d["lines"]), len(d["rows"])),
                         (sp.OUTSIDE_LISTED + 5, sp.OUTSIDE_LISTED, sp.OUTSIDE_LISTED + 5))
        self.assertEqual(d["period_label"], "01–07 Aug 2026")


if __name__ == "__main__":
    unittest.main()
