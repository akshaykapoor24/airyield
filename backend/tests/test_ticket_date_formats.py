"""Internal Statement's declared date format — no DB.

An uploaded sales statement declares how its Ticket Date and Travel Date are written
(services/ticket_extraction.py DATE_FORMAT_FIELDS): text dates are read in that order and no
other, Excel-stored ones are put in it row by row against the statement period
(services/excel_dates.py, anchored on the Ticket Date), and Doc Date follows the Ticket Date.
Customer data and manual entry declare nothing and keep reading day-first.

Run:  python -m unittest discover backend/tests
"""
import asyncio
import io
import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import app.models  # noqa: E402,F401
from app.services import ticket_extraction as tx  # noqa: E402

WEEK1 = (date(2026, 8, 1), date(2026, 8, 7))
DAY_FIRST = {"ticket_date": "DMY", "departure_datetime": "DMY"}


def xlsx(rows: list[list]) -> bytes:
    """A workbook whose datetime cells are stored by Excel as dates, the rest as text."""
    buf = io.BytesIO()
    pd.DataFrame(rows, columns=["Ticket Number", "Pax Name", "Ticket Date", "Travel Date", "Total"]).to_excel(
        buf, index=False)
    return buf.getvalue()


def extract(content: bytes, formats=None, period=WEEK1, mapping=None) -> dict:
    return asyncio.run(tx.TicketExtractionService.extract(
        content, "sales.xlsx", column_mapping=mapping, split_legs=False,
        date_formats=formats, valid_period=period))


class RowTests(unittest.TestCase):
    def test_doc_date_follows_the_ticket_date(self):
        self.assertEqual(tx.date_orders({"ticket_date": "MDY", "departure_datetime": "DMY"}),
                         {"ticket_date": "MDY", "departure_datetime": "DMY", "doc_date": "MDY"})

    def test_each_date_is_read_in_its_declared_order(self):
        row = tx.derive_ticket_row({"ticket_date": "05/08/2026", "doc_date": "06/08/2026",
                                    "departure_datetime": "09/08/2026 10:30"}, False,
                                   {"ticket_date": "MDY", "departure_datetime": "DMY"})
        self.assertEqual((row["ticket_date"], row["doc_date"], row["departure_datetime"]),
                         ("2026-05-08", "2026-06-08", "2026-08-09"))

    def test_a_date_that_does_not_fit_is_left_for_the_reviewer(self):
        row = tx.derive_ticket_row({"ticket_date": "13/08/2026"}, False, {"ticket_date": "MDY",
                                                                          "departure_datetime": "MDY"})
        self.assertEqual(row["ticket_date"], "13/08/2026")

    def test_nothing_declared_reads_day_first_as_before(self):
        self.assertEqual(tx.derive_ticket_row({"ticket_date": "05/08/2026"}, False)["ticket_date"], "2026-08-05")

    def test_a_multi_sector_tickets_first_leg_date_is_read_in_the_travel_order(self):
        rows = tx._keep_multi_sector_whole([{"sector": "DEL/BOM BOM/DEL", "travel_dt": "08/05/2026 08/09/2026"}], "MDY")
        self.assertEqual(rows[0]["departure_datetime"], "2026-08-05")


class ExtractTests(unittest.TestCase):
    """The read that makes the rows — what the preview shows and Save stores."""

    def setUp(self):
        self.content = xlsx([
            ["5808583279", "SHARMA/AMIT", datetime(2026, 1, 8), datetime(2026, 7, 8), 1000],  # typed: 1 Aug, 7 Aug
            ["5808583280", "VERMA/RAVI", datetime(2026, 8, 7), datetime(2026, 8, 4), 2000],   # pasted: stored right
            ["5808583281", "KHAN/SARA", datetime(2026, 3, 8), "13/08/2026", 3000],            # typed; travel as text
        ])

    def test_excel_dates_are_put_in_the_declared_order_row_by_row(self):
        out = extract(self.content, DAY_FIRST)
        got = [(r["ticket_date"], r["departure_datetime"]) for r in out["rows"]]
        self.assertEqual(got, [("2026-08-01", "2026-08-07"), ("2026-08-07", "2026-08-04"),
                               ("2026-08-03", "2026-08-13")])
        self.assertEqual(out["date_fix"]["count"], 3)

    def test_a_text_date_that_does_not_fit_the_travel_format_is_not_read(self):
        out = extract(self.content, {"ticket_date": "DMY", "departure_datetime": "MDY"})
        self.assertEqual(out["rows"][2]["departure_datetime"], "13/08/2026")

    def test_without_a_format_the_file_reads_as_before(self):
        out = extract(self.content, None)
        self.assertEqual(out["rows"][0]["ticket_date"], "2026-01-08")
        self.assertIsNone(out["date_fix"])

    def test_detection_reads_the_format_off_the_file(self):
        found = {d["field"]: d for d in tx.detect_date_formats(self.content, "sales.xlsx", valid_period=WEEK1)}
        self.assertEqual(found["ticket_date"]["order"], "DMY")          # 2 typed Ticket Dates fit only day-first
        self.assertEqual(found["departure_datetime"]["order"], "DMY")   # "13/08/2026" can only be day-first
        self.assertEqual(found["departure_datetime"]["example"], {"value": "13/08/2026", "read": "2026-08-13"})


class RouterTests(unittest.TestCase):
    def setUp(self):
        from app.api.v1 import internal_tickets, tickets
        self.tickets, self.internal = tickets, internal_tickets

    def test_required_on_internal_statement_only(self):
        self.assertFalse(self.tickets.DATE_FORMATS_REQUIRED)
        self.assertTrue(self.internal._impl.DATE_FORMATS_REQUIRED)

    def test_checked(self):
        check = self.tickets._checked_date_formats
        self.assertEqual(check({"ticket_date": "DMY", "departure_datetime": "MDY"}, required=True),
                         {"ticket_date": "DMY", "departure_datetime": "MDY"})
        self.assertIsNone(check(None, required=False))
        for bad in (None, {"ticket_date": "DMY"}, {"ticket_date": "DMY", "departure_datetime": "DDMM"}):
            with self.subTest(bad=bad), self.assertRaises(HTTPException):
                check(bad, required=True)

    def test_a_period_still_being_typed_is_no_period(self):
        p = self.tickets._period_or_none
        self.assertEqual(p("2026-08-01", "2026-08-07"), WEEK1)
        self.assertIsNone(p("2026-08-07", "2026-08-01"))
        self.assertIsNone(p("", "2026-08-07"))


if __name__ == "__main__":
    unittest.main()
