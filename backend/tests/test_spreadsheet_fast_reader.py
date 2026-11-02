"""The `fast` xlsx read gives the same table as the openpyxl read.

Internal Statement's background upload reads a lakh-line sales report with calamine
(services/internal_import.py), because openpyxl takes minutes over it. Every other importer keeps
openpyxl. These tests hold the two to the same answer on the cells that differ between engines —
stored dates and date-times, whole and fractional numbers, ticket numbers with leading zeros,
padded and placeholder text, blank rows — and on the guard that cuts a sheet whose filler runs
to row 1,048,576.

Also: the column-at-a-time cell clean-up the fast read uses (`_cells`) against `cell`, and the
date-format detector reading each distinct value once.

No DB, no network. Workbooks are built in memory with openpyxl.

Run:  python -m unittest tests.test_spreadsheet_fast_reader -v      (from backend/)
"""

import io
import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd  # noqa: E402

from app.services import date_format_detect  # noqa: E402
from app.services import spreadsheet as ss  # noqa: E402
from app.services import ticket_extraction  # noqa: E402

HEADER = ["Booking Date", "Ticket No", "Pax Name", "Travel Date", "Basic", "Tax", "Supplier", "Note"]


def workbook(rows, *, sheets=("Sheet1",), preamble=()) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    for i, name in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet(name)
        ws.title = name
        if i == 0:
            for line in preamble:
                ws.append(line)
            ws.append(HEADER)
            for r in rows:
                ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROWS = [
    [datetime(2026, 10, 1), "0987654321012", "MR ARJUN / SINGH", date(2026, 10, 15), 4500, 1234.5, "JETHI - 6E", "  padded  "],
    [datetime(2026, 10, 2, 13, 45), 5808583279, "SINGH/PRIYA MRS", "13/10/2026", 4500.0, 0, "IATA BSP", "N/A"],
    [None, None, None, None, None, None, None, None],
    ["15 Oct 2026", "607 5808583279", "", "", "", "", "", "nan"],
    [datetime(2026, 10, 3), "AB12CD", "Lee/Kim", datetime(2026, 11, 1, 6, 0), -150.75, 12, "TSC Travel", "—"],
]


class FastReadMatchesOpenpyxl(unittest.TestCase):
    def both(self, content, **kw):
        slow = ss.read_table(content, "f.xlsx", **kw)
        fast = ss.read_table(content, "f.xlsx", fast=True, **kw)
        return slow, fast

    def assertSameTable(self, slow, fast):
        self.assertEqual(slow.columns, fast.columns)
        self.assertEqual(slow.header_row, fast.header_row)
        self.assertEqual(slow.sheet, fast.sheet)
        self.assertEqual(slow.preamble, fast.preamble)
        self.assertEqual(slow.df.astype(object).values.tolist(), fast.df.astype(object).values.tolist())

    def test_typed_cells_read_the_same(self):
        slow, fast = self.both(workbook(ROWS))
        self.assertSameTable(slow, fast)
        # The blank line is dropped by both.
        self.assertEqual(len(fast.df), 4)

    def test_header_below_a_preamble(self):
        content = workbook(ROWS, preamble=[["SALES REPORT"], ["For The Period 1 October 2026 To 15 October 2026"]])
        slow, fast = self.both(content)
        self.assertSameTable(slow, fast)
        self.assertEqual(fast.header_row, 2)

    def test_the_fullest_of_several_sheets(self):
        slow, fast = self.both(workbook(ROWS, sheets=("Sales", "Notes", "Sheet3")))
        self.assertSameTable(slow, fast)
        self.assertEqual(fast.sheet, "Sales")

    def test_ticket_extraction_rows_are_the_same(self):
        import asyncio
        content = workbook(ROWS)
        kw = dict(split_legs=False, keep_raw=False, internal_standard=True,
                  date_formats={"ticket_date": "DMY", "departure_datetime": "DMY"})
        slow = asyncio.run(ticket_extraction.TicketExtractionService.extract(content, "f.xlsx", **kw))
        fast = asyncio.run(ticket_extraction.TicketExtractionService.extract(content, "f.xlsx", fast_read=True, **kw))
        self.assertEqual(slow["rows"], fast["rows"])
        self.assertEqual(slow["suggested_mapping"], fast["suggested_mapping"])


class FillerToTheBottom(unittest.TestCase):
    """A sheet whose one column is filled far below the data (the coloured Yatra copy runs to row
    1,048,576) is cut where the data ends, by both engines."""

    def test_declared_rows_are_read_off_the_dimension(self):
        content = workbook(ROWS)
        book = pd.ExcelFile(io.BytesIO(content), engine="calamine")
        self.assertEqual(ss._declared_rows(book, "Sheet1"), len(ROWS) + 1)
        self.assertIsNone(ss._declared_rows(book, "No such sheet"))

    def test_an_implausible_sheet_is_cut_at_its_data(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(HEADER)
        for r in ROWS:
            ws.append(r)
        n = ss._IMPLAUSIBLE_ROWS + 5
        ws.cell(row=n, column=1, value="filler")   # declares the sheet that tall
        buf = io.BytesIO()
        wb.save(buf)
        content = buf.getvalue()
        book = pd.ExcelFile(io.BytesIO(content), engine="calamine")
        self.assertEqual(ss._declared_rows(book, "Sheet"), n)
        self.assertEqual(ss._data_rows(book, "Sheet"), len(ROWS) + 1)


class CellsColumnWise(unittest.TestCase):
    def test_same_strings_as_cell(self):
        frame = pd.DataFrame({
            "a": [" x ", None, "NaN", "  ", "null", "N/A", "5808583279", "<NA>"],
            "b": ["None", "y", "  z", None, "nat", "0", "", "- "],
        }, dtype=str)
        self.assertEqual(ss._cells(frame).astype(object).values.tolist(),
                         frame.map(ss.cell).astype(object).values.tolist())

    def test_no_columns(self):
        self.assertEqual(ss._cells(pd.DataFrame(index=[0, 1])).shape, (2, 0))


class DetectorReadsEachValueOnce(unittest.TestCase):
    """Votes and examples are the same as reading every cell — the column below is what a
    per-cell loop counted before."""

    def test_votes_count_repeats(self):
        values = ["13/10/2026"] * 5 + ["05/10/2026"] * 3 + ["2026-10-01", "", None, "nan"] + ["14/10/2026"]
        det = date_format_detect.detect_column("ticket_date", "Booking Date", values,
                                               (date(2026, 10, 1), date(2026, 10, 15)))
        self.assertEqual(det.votes["DMY"], 9)          # 5 × 13th, 3 × 5th (in the period), 1 × 14th
        self.assertEqual(det.text_dates, 9)
        self.assertEqual(det.order, "DMY")
        self.assertEqual(det.example["value"], "13/10/2026")


class DateMemo(unittest.TestCase):
    def test_each_extract_starts_with_an_empty_memo(self):
        ticket_extraction._iso_text("05/10/2026", "DMY")
        self.assertGreater(ticket_extraction._iso_text.cache_info().currsize, 0)
        import asyncio
        asyncio.run(ticket_extraction.TicketExtractionService.extract(workbook(ROWS), "f.xlsx", include_rows=False))
        self.assertEqual(ticket_extraction._iso_text.cache_info().currsize, 0)
        self.assertEqual(ticket_extraction._normalize_date("05/10/2026", "DMY"), "2026-10-05")
        self.assertEqual(ticket_extraction._normalize_date("05/10/2026", "MDY"), "2026-05-10")
        self.assertEqual(ticket_extraction._normalize_date("not a date", "DMY"), "not a date")


if __name__ == "__main__":
    unittest.main()
