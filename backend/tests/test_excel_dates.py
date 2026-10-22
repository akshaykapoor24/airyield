"""Excel-stored dates put in the order the sheet is written in — no DB.

The rule (services/excel_dates.py): in the declared date columns of a day-and-month format,
a file whose stored Booked Dates fall in the statement period more often swapped than as
stored was entered the other way round from its Excel, and each row is put back — or left —
as a whole, on its Booked Date's word: swapped Booked Date (or one left as text) → the row
was typed and every stored date on it is put back; Booked Date stored right → the row was
pasted and its dates stay. Pinned here on the shape of the real TRIUMPHH 01–07 Aug statement,
on correctly dated weeks, and on the router's use of it.

Run:  python -m unittest discover backend/tests
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd  # noqa: E402

from app.services import excel_dates  # noqa: E402
from app.services import flat_statement as flat  # noqa: E402

WEEK1 = (date(2026, 8, 1), date(2026, 8, 7))
WEEK2 = (date(2026, 8, 8), date(2026, 8, 15))
COLUMNS = {"booking_date": "Booked Date", "travel_date": "Date of Travel"}
DAY_FIRST = flat.date_orders({"booking_date": "DMY", "travel_date": "DMY"})

REAL_WEEK1 = os.environ.get(
    "TP_GDS_WEEK1_SAMPLE",
    r"C:\Users\manve\OneDrive\Desktop\FareQube Docs\TriumphTravel"
    r"\TRIUMPHH BSP STATMENT 01-07TH AUG 26 (5).xlsx",
)


def stored(iso: str) -> str:
    """A real Excel date as services/spreadsheet.py hands it over."""
    return f"{iso} 00:00:00"


def frame(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["Booked Date", "Date of Travel"])


def read(df, period=WEEK1, orders=DAY_FIRST, columns=COLUMNS):
    return excel_dates.read_stored_dates(df, period, columns, orders)


class TypedAndPastedRowsTests(unittest.TestCase):
    """The 01–07 Aug statement: typed rows stored swapped, pasted rows stored right."""

    def setUp(self):
        self.df = frame([
            (stored("2026-01-08"), stored("2026-07-08")),   # 0 typed 01-08 / 07-08 → 1 Aug, 7 Aug
            (stored("2026-07-08"), "13/08/2026"),           # 1 7 Aug; travel left as text by Excel
            (stored("2026-03-08"), stored("2026-02-11")),   # 2 3 Aug; travel 02-11 → 2 Nov
            (stored("2026-08-07"), stored("2026-08-04")),   # 3 a pasted cancellation, stored right
            (stored("2026-06-08"), stored("2026-10-08")),   # 4 6 Aug; travel 10 Aug
            (stored("2026-08-15"), stored("2025-09-11")),   # 5 pasted: past the 12th, never swapped
            ("13/08/2026", stored("2026-09-08")),           # 6 Booked Date typed as text → row typed
            (stored("2026-08-08"), stored("2026-08-11")),   # 7 Booked Date reads alike → date by date
        ])
        self.fix = read(self.df)

    def test_a_typed_row_has_every_stored_date_put_back(self):
        self.assertEqual(self.df.iloc[0].tolist(), [stored("2026-08-01"), stored("2026-08-07")])
        self.assertEqual(self.df.iloc[2].tolist(), [stored("2026-08-03"), stored("2026-11-02")])
        self.assertEqual(self.df.iloc[4].tolist(), [stored("2026-08-06"), stored("2026-08-10")])

    def test_a_pasted_row_is_left_as_excel_holds_it(self):
        self.assertEqual(self.df.iloc[3].tolist(), [stored("2026-08-07"), stored("2026-08-04")])
        # Its travel date is far from the period, but the row says it was pasted: kept.
        self.assertEqual(self.df.iloc[5].tolist(), [stored("2026-08-15"), stored("2025-09-11")])

    def test_text_is_never_moved_and_marks_its_row_as_typed(self):
        self.assertEqual(self.df.iloc[1, 1], "13/08/2026")
        self.assertEqual(self.df.iloc[6].tolist(), ["13/08/2026", stored("2026-08-09")])

    def test_a_row_its_booked_date_does_not_settle_is_read_date_by_date(self):
        self.assertEqual(self.df.iloc[7].tolist(), [stored("2026-08-08"), stored("2026-08-11")])

    def test_every_change_is_reported_by_row_and_column(self):
        d = self.fix.as_dict()
        self.assertEqual(d["count"], 8)
        self.assertEqual(d["columns"], [{"column": "Booked Date", "cells": 4},
                                        {"column": "Date of Travel", "cells": 4}])
        self.assertEqual(d["cells"][0], {"index": 0, "column": "Booked Date",
                                         "stored": "2026-01-08", "read": "2026-08-01"})
        self.assertEqual(d["period_label"], "01–07 Aug 2026")
        # Only the rows the wizard shows are listed cell by cell; the count covers them all.
        self.assertEqual({c["index"] for c in self.fix.as_dict(rows_shown=1)["cells"]}, {0})


class WhatIsNeverMovedTests(unittest.TestCase):
    def test_a_correctly_dated_week_is_untouched(self):
        rows = [(stored("2026-08-08"), stored("2026-08-10")), (stored("2026-08-09"), stored("2026-09-05")),
                (stored("2026-08-12"), stored("2026-09-11")), (stored("2026-08-15"), stored("2026-08-15"))]
        df = frame(rows)
        self.assertIsNone(read(df, WEEK2))
        self.assertEqual([tuple(r) for r in df.itertuples(index=False)], rows)

    def test_a_far_travel_date_on_a_right_sheet_is_not_swapped(self):
        df = frame([(stored("2026-08-03"), stored("2026-12-10"))])
        self.assertIsNone(read(df))
        self.assertEqual(df.iloc[0, 1], stored("2026-12-10"))

    def test_a_year_first_column_is_read_as_excel_holds_it(self):
        df = frame([(stored("2026-01-08"), stored("2026-07-08"))])
        orders = flat.date_orders({"booking_date": "YMD", "travel_date": "YMD"})
        self.assertIsNone(read(df, orders=orders))
        self.assertEqual(df.iloc[0, 0], stored("2026-01-08"))

    def test_only_the_declared_date_columns_move(self):
        df = pd.DataFrame([(stored("2026-01-08"), stored("2026-02-08"))], columns=["Booked Date", "Invoice Date"])
        read(df, columns={"booking_date": "Booked Date"})
        self.assertEqual(df.iloc[0].tolist(), [stored("2026-08-01"), stored("2026-02-08")])

    def test_text_and_iso_text_are_never_read_as_stored(self):
        df = frame([("01-08-2026", "2026-01-08")])
        self.assertIsNone(read(df))
        self.assertEqual(df.iloc[0].tolist(), ["01-08-2026", "2026-01-08"])

    def test_no_period_no_change(self):
        df = frame([(stored("2026-01-08"), None)])
        self.assertIsNone(read(df, period=None))
        self.assertEqual(df.iloc[0, 0], stored("2026-01-08"))

    def test_without_declared_formats_every_given_column_may_move(self):
        # How /detect-date-formats reads the file, before the format is known.
        df = frame([(stored("2026-01-08"), stored("2026-07-08"))])
        self.assertEqual(read(df, orders=None).as_dict()["count"], 2)


class RouterTests(unittest.TestCase):
    def setUp(self):
        import app.models  # noqa: F401
        from app.api.v1 import statements as router
        self.router = router

    def test_only_third_party_gds_excel_files_are_put_in_order(self):
        import io
        df = frame([(stored("2026-01-08"), None)])
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        xlsx = buf.getvalue()
        formats = {"booking_date": "DMY", "travel_date": "DMY"}
        colmap = {"booking_date": "Booked Date", "travel_date": "Date of Travel", "pnr": "PNR"}
        read_ = self.router._read_stored_dates
        self.assertIsNone(read_("tp-lcc", xlsx, "a.xlsx", df.copy(), WEEK1, colmap, formats))
        self.assertIsNone(read_("tp-gds", b"Booked Date\n2026-01-08 00:00:00\n", "a.csv", df.copy(),
                                WEEK1, colmap, formats))
        self.assertIsNone(read_("tp-gds", xlsx, "a.xlsx", df.copy(), None, colmap, formats))
        fix = read_("tp-gds", xlsx, "a.xlsx", df, WEEK1, colmap, formats)
        self.assertEqual((fix.as_dict()["count"], df.iloc[0, 0]), (1, stored("2026-08-01")))

    def test_the_review_grid_shows_a_stored_date_as_its_day(self):
        self.assertEqual(self.router._sample_cell(stored("2026-08-01")), "2026-08-01")
        self.assertEqual(self.router._sample_cell("2026-08-01 10:30:00"), "2026-08-01 10:30:00")
        self.assertEqual(self.router._sample_cell("13/08/2026"), "13/08/2026")


class RealFileTests(unittest.TestCase):
    def test_typed_booked_dates_land_in_the_week_and_pasted_ones_stay(self):
        try:
            with open(REAL_WEEK1, "rb") as fh:
                content = fh.read()
        except OSError:
            self.skipTest(f"sample not available: {REAL_WEEK1}")
        import app.models  # noqa: F401
        from app.api.v1 import statements as router
        builder = router._mapping_capable("tp-gds")
        # Read as the upload reads it — header row detected, not assumed: the sample has
        # been saved both with its header on row 1 and with a blank row above it.
        df, cols, _hr = router._read_for_mapping(content, os.path.basename(REAL_WEEK1), builder, None)
        before = df["Booked Date"].tolist()
        fix = read(df, columns=builder.suggest_mapping(cols))
        self.assertIsNotNone(fix)
        for was, now in zip(before, df["Booked Date"].tolist()):
            was_d = flat.to_iso_date(was, "YMD")
            if was_d is None:
                continue                                  # a balance line: no Booked Date
            if was_d < "2026-08-01":                      # typed: stored 8 Jan … 8 Jul
                self.assertTrue("2026-08-01" <= flat.to_iso_date(now, "YMD") <= "2026-08-07", (was, now))
            else:                                         # pasted: stored right, kept
                self.assertEqual(now, was)


if __name__ == "__main__":
    unittest.main()
