"""Unit tests for the declared date format of a Third Party GDS upload — no DB, no network.

A consolidator writes its sheet however it likes: "05/08/2026" is 5 Aug from one and 8 May
from the next, and nothing in the cell says which. The upload step asks the uploader for
the order Booked Date and Date of Travel are written in, and those columns' text dates are
read that way and no other (flat_statement.to_iso_date). The cases that matter are the
ambiguous day (both readings valid, the declaration decides), the contradiction (a cell
that cannot be in the declared order is left unread, not quietly read the other way), and
the Excel-stored date (already a date — the declaration never moves it).

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace

import pandas as pd
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1 import statements as router  # noqa: E402
from app.services import date_format_detect as dfd  # noqa: E402
from app.services import flat_statement as fs  # noqa: E402
from app.services import statement_spec as spec  # noqa: E402


class InOrderTests(unittest.TestCase):
    def test_the_declaration_decides_an_ambiguous_day(self):
        self.assertEqual(fs.to_iso_date("05/08/2026", "DMY"), "2026-08-05")
        self.assertEqual(fs.to_iso_date("05/08/2026", "MDY"), "2026-05-08")
        self.assertEqual(fs.to_iso_date("2026/08/05", "YMD"), "2026-08-05")

    def test_separators_two_digit_years_and_times(self):
        for s in ("05-08-2026", "05.08.2026", "05 08 2026", "05-08-26", "5/8/26",
                  "05/08/2026 10:30", "05/08/2026 10:30:15", "05/08/2026 10:30 AM"):
            with self.subTest(s=s):
                self.assertEqual(fs.to_iso_date(s, "DMY"), "2026-08-05")
        self.assertEqual(fs.to_iso_date("26-08-05", "YMD"), "2026-08-05")

    def test_a_cell_that_cannot_be_in_the_declared_order_is_not_read(self):
        # Read the other way round it would be a date — which is exactly the guess the
        # declaration exists to stop.
        self.assertIsNone(fs.to_iso_date("13/08/2026", "MDY"))
        self.assertIsNone(fs.to_iso_date("08/13/2026", "DMY"))
        self.assertIsNone(fs.to_iso_date("31-08-2026", "YMD"))
        self.assertIsNone(fs.to_iso_date("31/02/2026", "DMY"))

    def test_a_stored_excel_date_is_never_moved(self):
        # The reader hands an Excel date over as ISO; Excel already decided its day and month.
        for order in fs.DATE_ORDERS:
            with self.subTest(order=order):
                self.assertEqual(fs.to_iso_date("2026-01-08 00:00:00", order), "2026-01-08")
                self.assertEqual(fs.to_iso_date("2026-08-31", order), "2026-08-31")

    def test_a_named_month_says_which_part_is_the_month(self):
        self.assertEqual(fs.to_iso_date("05-Aug-2026", "DMY"), "2026-08-05")
        self.assertEqual(fs.to_iso_date("05-Aug-2026", "MDY"), "2026-08-05")
        self.assertEqual(fs.to_iso_date("Aug 5, 2026", "MDY"), "2026-08-05")
        self.assertIsNone(fs.to_iso_date("Aug", "DMY"))       # not "today in August"

    def test_compact_dates(self):
        self.assertEqual(fs.to_iso_date("05082026", "DMY"), "2026-08-05")
        self.assertEqual(fs.to_iso_date("08052026", "MDY"), "2026-08-05")
        self.assertEqual(fs.to_iso_date("20260805", "YMD"), "2026-08-05")

    def test_blank_and_junk(self):
        for v in (None, "", "  ", "nan", "LESS PAYMENT", "12/2026"):
            with self.subTest(v=v):
                self.assertIsNone(fs.to_iso_date(v, "DMY"))

    def test_no_declaration_reads_as_before(self):
        self.assertEqual(fs.to_iso_date("05/08/2026"), "2026-08-05")
        self.assertEqual(fs.to_iso_date("08/13/2026"), "2026-08-13")   # dateutil's fallback


class DateOrdersTests(unittest.TestCase):
    def test_issue_and_transaction_date_follow_the_booked_date(self):
        self.assertEqual(fs.date_orders({"booking_date": "MDY", "travel_date": "DMY"}), {
            "booking_date": "MDY", "travel_date": "DMY",
            "issue_date": "MDY", "transaction_date": "MDY",
        })

    def test_a_field_declared_itself_keeps_its_own(self):
        out = fs.date_orders({"issue_date": "YMD", "booking_date": "MDY"})
        self.assertEqual(out["issue_date"], "YMD")
        self.assertEqual(out["transaction_date"], "MDY")

    def test_unknown_orders_and_nothing_declared(self):
        self.assertEqual(fs.date_orders({"booking_date": "DDMM"}), {})
        self.assertEqual(fs.date_orders(None), {})


HEADERS = ["Booked Date", "Date of Travel", "Ticket No", "Net Amount"]
MAPPING = {"booking_date": "Booked Date", "travel_date": "Date of Travel",
           "ticket_number": "Ticket No", "net_amount": "Net Amount"}


def build(values, date_formats=None, overrides=None):
    return fs.get("tp-gds").build_row_mapped(dict(zip(HEADERS, values)), HEADERS, MAPPING,
                                             overrides, date_formats=date_formats)["data"]


class BuilderTests(unittest.TestCase):
    def test_each_column_is_read_in_its_own_declared_order(self):
        data = build(["05/08/2026", "09/08/2026", "2355809056126", "100"],
                     {"booking_date": "MDY", "travel_date": "DMY"})
        self.assertEqual(data["booking_date"], "2026-05-08")
        self.assertEqual(data["travel_date"], "2026-08-09")
        # No Issue Date column: the Booked Date stands in, as read.
        self.assertEqual(data["issue_date"], "2026-05-08")

    def test_a_correction_is_read_in_its_columns_order(self):
        data = build(["05/08/2026", "09/08/2026", "1", "1"], {"booking_date": "MDY", "travel_date": "MDY"},
                     overrides={"booking_date": "08/07/2026"})
        self.assertEqual(data["booking_date"], "2026-08-07")

    def test_an_unreadable_date_is_kept_and_flagged(self):
        data = build(["13/08/2026", "09/08/2026", "1", "1"], {"booking_date": "MDY", "travel_date": "MDY"})
        self.assertEqual(data["booking_date"], "13/08/2026")
        self.assertEqual(data["date_parse_failed"], "booking_date")

    def test_build_row_takes_them_too(self):
        data = fs.get("tp-gds").build_row(dict(zip(HEADERS, ["05/08/2026", "05/08/2026", "1", "1"])),
                                          HEADERS, date_formats={"booking_date": "MDY", "travel_date": "MDY"})["data"]
        self.assertEqual((data["booking_date"], data["travel_date"]), ("2026-05-08", "2026-05-08"))


class FormTests(unittest.TestCase):
    def test_third_party_gds_asks_for_booked_and_travel_date(self):
        self.assertEqual([f["field"] for f in spec.date_format_fields("tp-gds")],
                         ["booking_date", "travel_date"])
        self.assertEqual(spec.date_format_fields("tp-lcc"), [])
        self.assertEqual(spec.date_format_fields("ndc"), [])

    def test_read_and_checked(self):
        self.assertEqual(
            router._date_formats_form("tp-gds", '{"booking_date": "DMY", "travel_date": "MDY"}', required=True),
            {"booking_date": "DMY", "travel_date": "MDY"})

    def test_required_where_the_wizard_always_sends_it(self):
        with self.assertRaises(HTTPException) as e:
            router._date_formats_form("tp-gds", None, required=True)
        self.assertIn("Booked / Issue Date and Travel Date", e.exception.detail)
        self.assertIsNone(router._date_formats_form("tp-gds", None, required=False))

    def test_a_missing_or_unknown_format_is_refused(self):
        for raw in ('{"booking_date": "DMY"}', '{"booking_date": "DMY", "travel_date": "DDMM"}',
                    '["DMY"]', "not json"):
            with self.subTest(raw=raw), self.assertRaises(HTTPException):
                router._date_formats_form("tp-gds", raw, required=True)

    def test_ignored_for_a_type_that_asks_nothing(self):
        self.assertIsNone(router._date_formats_form("tp-lcc", '{"booking_date": "DDMM"}', required=True))


class DatesReadTests(unittest.TestCase):
    """`/save-preview`'s per-column report — what the review step shows about the dates."""

    def report(self, lines_data, df_rows, edits=None):
        df = pd.DataFrame(df_rows, columns=HEADERS)
        req = router._MappingRequest(MAPPING, edits or {}, b"", df, HEADERS, 0,
                                     {"booking_date": "MDY", "travel_date": "DMY"})
        lines = router._MappedLines([SimpleNamespace(data=d) for d in lines_data], 0, 0, 0, None,
                                    indexes=list(range(len(lines_data))))
        return {r["field"]: r for r in router._dates_read("tp-gds", req, lines)}

    def test_span_and_unreadable_cells(self):
        out = self.report(
            [
                {"booking_date": "2026-08-01", "travel_date": "2026-08-09"},
                {"booking_date": "2026-08-07", "travel_date": "2026-09-01"},
                # A typed line: the date did not fit, so no value and the field is named.
                {"travel_date": "2026-08-10", "unparsed_fields": "booking_date,issue_date"},
                # A JSONB line keeps the cell as it was.
                {"booking_date": "2026-08-03", "travel_date": "31/31/2026"},
                {"row_kind": "balance", "net_amount": "100"},
            ],
            [["08/01/2026", "09/08/2026", "1", "1"], ["08/07/2026", "01/09/2026", "2", "1"],
             ["13/08/2026", "10/08/2026", "3", "1"], ["08/03/2026", "31/31/2026", "4", "1"],
             [None, None, None, "100"]],
        )
        b, t = out["booking_date"], out["travel_date"]
        self.assertEqual((b["read"], b["first"], b["last"], b["unreadable"]), (3, "2026-08-01", "2026-08-07", 1))
        self.assertEqual(b["cells"], [{"index": 2, "value": "13/08/2026"}])
        self.assertEqual((b["format"], b["header"], b["mapped"]), ("MDY", "Booked / Issue Date", True))
        self.assertEqual((t["read"], t["unreadable"]), (3, 1))
        self.assertEqual(t["cells"], [{"index": 3, "value": "31/31/2026"}])

    def test_an_unreadable_correction_shows_what_was_typed(self):
        out = self.report([{"unparsed_fields": "booking_date"}],
                          [["08/01/2026", "09/08/2026", "1", "1"]],
                          edits={0: {"booking_date": "32/01/2026"}})
        self.assertEqual(out["booking_date"]["cells"], [{"index": 0, "value": "32/01/2026"}])


class RowMarksTests(unittest.TestCase):
    def test_balance_lines_and_unread_values_by_file_row(self):
        lines = router._MappedLines(
            [SimpleNamespace(data=d) for d in (
                {"ticket_number": "1"},
                {"row_kind": "balance", "net_amount": "100"},
                {"ticket_number": "2", "unparsed_fields": "booking_date,issue_date"},
                {"ticket_number": "3", "date_parse_failed": "travel_date"},
            )], 0, 0, 0, None, indexes=[0, 4, 5, 7])
        self.assertEqual(router._row_marks(lines), {
            "balance_rows": [4],
            "unparsed_rows": [{"index": 5, "fields": ["booking_date", "issue_date"]},
                              {"index": 7, "fields": ["travel_date"]}],
        })


AUG_1_7 = (date(2026, 8, 1), date(2026, 8, 7))


class DetectTests(unittest.TestCase):
    """services/date_format_detect.py — the upload step's Date format, read off the file."""

    def test_the_period_settles_dates_valid_both_ways(self):
        # A week of Booked Dates, one a day early and one a day late: day-first puts all of
        # them in or beside 01–07 Aug; month-first scatters them from January to July.
        cells = ["01/08/2026", "03/08/2026", "05/08/2026", "07/08/2026", "31/07/2026", "08/08/2026"]
        d = dfd.detect_column("booking_date", "Booked", cells, AUG_1_7)
        self.assertEqual(d.order, "DMY")
        self.assertEqual(d.votes, {"DMY": 5, "MDY": 0, "YMD": 0})   # 08/08 reads alike: no vote
        self.assertEqual(d.example, {"value": "31/07/2026", "read": "2026-07-31"})  # only day-first

    def test_a_month_first_sheet(self):
        d = dfd.detect_column("booking_date", "Booked", ["08/01/2026", "08/05/2026", "08/07/2026"], AUG_1_7)
        self.assertEqual(d.order, "MDY")

    def test_without_a_period_only_one_way_dates_count(self):
        d = dfd.detect_column("travel_date", "Travel", ["05/08/2026", "13/08/2026"], None)
        self.assertEqual((d.order, d.votes["DMY"], d.text_dates), ("DMY", 1, 2))

    def test_stored_dates_say_nothing_unless_put_right(self):
        stored = ["2026-08-01 00:00:00", "2026-08-05 00:00:00"]
        d = dfd.detect_column("booking_date", "Booked", stored, AUG_1_7)
        self.assertEqual((d.order, d.text_dates), (None, 0))
        # The same column, read day-first by excel_dates: a sheet typed day-first.
        d = dfd.detect_column("booking_date", "Booked", stored, AUG_1_7, swapped=64)
        self.assertEqual((d.order, d.example), ("DMY", None))

    def test_mixed_evidence_is_not_settled(self):
        d = dfd.detect_column("booking_date", "Booked",
                              ["01/08/2026", "02/08/2026", "08/03/2026", "08/04/2026"], AUG_1_7)
        self.assertEqual(d.votes, {"DMY": 2, "MDY": 2, "YMD": 0})
        self.assertIsNone(d.order)

    def test_detect_reads_the_mapped_columns(self):
        df = pd.DataFrame([["13/08/2026", "x"], ["2026-01-08 00:00:00", "y"]], columns=["Booked", "Other"])
        fix = SimpleNamespace(cells=[(1, "Booked", "2026-01-08", "2026-08-01")])
        out = dfd.detect(df, {"booking_date": "Booked", "travel_date": None}, AUG_1_7, fix)
        self.assertEqual([(d.field, d.column, d.order, d.swapped) for d in out],
                         [("booking_date", "Booked", "DMY", 1), ("travel_date", None, None, 0)])


if __name__ == "__main__":
    unittest.main()
