"""Deal-sheet PDF parsing: merged cells, the deterministic fast path, bare airline codes.

Two layers:
  * Pure tests (always run) pin each rule on hand-built rows and fake tables.
  * Sample-sheet tests read the real supplier PDFs (Lords, Akbar, Mirror PCC, Vicky)
    and pin what each must parse to. The PDFs are supplier documents and are NOT in
    the repo; point DEAL_SHEET_DIR at a folder holding them, or they are looked for in
    ~/Downloads and ~/OneDrive/Desktop/FareQube Docs/TriumphTravel. Missing → skipped.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.ai_deal_extraction import (  # noqa: E402
    Stats, _simple_cell, deterministic_compact, expand_row,
)
from app.services.airline_resolver import AirlineIndex, bare_designator, RESOLVED  # noqa: E402
from app.services.pdf_table_rows import (  # noqa: E402
    ColumnMap, DocRow, _is_repeat_header, build_colmap, fill_merged_cells, is_noise_row,
)


def row(n, cells, cm, section=None):
    from app.services.pdf_table_rows import _row_expects_deals
    return DocRow(n=n, page=0, cells=tuple(cells), section=section,
                  raw="\t".join(cells), expects_deals=_row_expects_deals(tuple(cells), cm))


# Vicky's column order: rates run BUS, P.ECO, ECO — the reverse of most sheets.
VICKY_HEADER = ("Airline", "BUS/FIRST", "P.ECO", "ECO", "Validity", "Remarks")


class HeaderTest(unittest.TestCase):
    def test_bus_first_is_business(self):
        cm = build_colmap(VICKY_HEADER)
        self.assertEqual((cm.bus, cm.pey, cm.eco, cm.validity), (1, 2, 3, 4))

    def test_partial_header_repeat(self):
        header = ("Airline Name", "Airline Code", "Cabin Type", "Commission")
        self.assertTrue(_is_repeat_header(("Airline Name", "Airline Code", "", "Commission"), header))
        self.assertFalse(_is_repeat_header(("Air India", "AI", "Eco", "1%"), header))

    def test_repeated_banner_is_noise(self):
        cm = build_colmap(VICKY_HEADER)
        self.assertTrue(is_noise_row(("", "DEAL", "DEAL", "DEAL", "", ""), cm))


def fake_table(grid):
    """grid: rows of (text, bbox|None). The first row has every cell (the grid row)."""
    rows = []
    for r in grid:
        boxes = [b for _, b in r]
        present = [b for b in boxes if b is not None]
        y0 = min(b[1] for b in present)
        y1 = max(b[3] for b in present)
        rows.append(SimpleNamespace(cells=boxes, bbox=(0, y0, 100, y1)))
    return SimpleNamespace(rows=rows), [[t for t, _ in r] for r in grid]


class MergeTest(unittest.TestCase):
    # columns at x: 0-10 airline, 10-20 BUS, 20-30 PEY, 30-40 ECO, 40-50 validity
    def test_across_rate_columns_and_down(self):
        table, texts = fake_table([
            [("Airline", (0, 0, 10, 10)), ("BUS", (10, 0, 20, 10)), ("PEY", (20, 0, 30, 10)),
             ("ECO", (30, 0, 40, 10)), ("Validity", (40, 0, 50, 10))],
            # VS: 2.75% spans BUS+PEY, 1.75% under ECO
            [("VS", (0, 10, 10, 20)), ("2.75%", (10, 10, 30, 20)), (None, None),
             ("1.75%", (30, 10, 40, 20)), ("Dec'26", (40, 10, 50, 20))],
            # AZ: name and validity span two rows; each row's rate spans all classes
            [("AZ", (0, 20, 10, 40)), ("2.75%", (10, 20, 40, 30)), (None, None), (None, None),
             ("Dec'26", (40, 20, 50, 40))],
            [(None, None), ("2%", (10, 30, 40, 40)), (None, None), (None, None), (None, None)],
        ])
        fill_merged_cells(table, texts, rate_cols={1, 2, 3})
        self.assertEqual(texts[1][1:4], ["2.75%", "2.75%", "1.75%"])
        self.assertEqual(texts[2][1:4], ["2.75%"] * 3)
        self.assertEqual(texts[3], ["AZ", "2%", "2%", "2%", "Dec'26"])

    def test_banner_never_spreads_across(self):
        table, texts = fake_table([
            [("A", (0, 0, 10, 10)), ("B", (10, 0, 20, 10)), ("C", (20, 0, 30, 10))],
            [("BANNER", (0, 10, 30, 20)), (None, None), (None, None)],
        ])
        fill_merged_cells(table, texts, rate_cols={1, 2})
        self.assertEqual(texts[1], ["BANNER", None, None])


class FastPathTest(unittest.TestCase):
    def test_simple_cells(self):
        self.assertEqual(_simple_cell("2.75%(B+YQ)"), (True, {"p": 2.75, "cc": "B+YQ"}))
        self.assertEqual(_simple_cell("2% B+YR+YQ")[1]["cc"], "B+YQ+YR")
        self.assertEqual(_simple_cell("1.25% Basic")[1], {"p": 1.25, "cc": "B"})
        self.assertEqual(_simple_cell("0.0%")[1]["p"], 0.0)
        self.assertEqual(_simple_cell("NIL"), (True, None))
        for messy in ("CNP+2%", "3+5%", "3% IATA", "NET + SC 50", "1.25%-STD-(B+YQ), 1.5%"):
            self.assertFalse(_simple_cell(messy)[0], messy)

    def test_vicky_row_needs_no_model(self):
        cm = build_colmap(VICKY_HEADER)
        r = row(9, ["MH", "10.5%", "8.5% (B)", "8.5% (B)", "FLOWN TILL 31ST Dec'26", ""], cm)
        compact = deterministic_compact(r, cm)
        self.assertIsNotNone(compact)
        deals = expand_row(compact, r, Stats(), cm)
        got = {d["incentive_data"]["PLB"]["class"]: d["incentive_data"]["PLB"]["incentiveAmtPct"] for d in deals}
        self.assertEqual(got, {"Economy": 8.5, "Premium": 8.5, "Business": 10.5})
        self.assertEqual(deals[0]["contract_valid_to"], "2026-12-31")
        self.assertEqual(deals[0]["airline_code"], "MH")       # the name cell IS the code

    def test_messy_row_goes_to_model(self):
        cm = build_colmap(VICKY_HEADER)
        r = row(4, ["BA", "CNP+2.5% (B+YQ)", "CNP+2.5% (B+YQ)", "CNP+2% (B+YQ)", "Dec'26", ""], cm)
        self.assertIsNone(deterministic_compact(r, cm))

    def test_cabin_format(self):
        cm = build_colmap(("Airline Name", "Airline Code", "Cabin Type", "Commission",
                           "Applicable on", "Travel Validity", "Remarks"))
        r = row(1, ["Air Astana", "KC", "All", "1.18%", "Base Fare + YQ", "31 Dec'2026", ""], cm)
        deals = expand_row(deterministic_compact(r, cm), r, Stats(), cm)
        self.assertEqual(len(deals), 3)
        self.assertEqual(deals[0]["incentive_data"]["PLB"]["payoutCalcCols"], "Basic + YQ")


class BareCodeTest(unittest.TestCase):
    def setUp(self):
        self.idx = AirlineIndex.from_rows([
            (1, "VIRGIN ATLANTIC", "VS"), (2, "AIR FRANCE", "AF"), (3, "KLM ROYAL DUTCH AIRLINES", "KL"),
            (4, "DELTA AIRLINES", "DL"), (5, "MYANMAR AIRWAYS INTERNATIONAL", "8M"),
        ])

    def test_bare_designator(self):
        self.assertEqual(bare_designator("VS"), "VS")
        for not_code in ("Vs", "Virgin Atlantic", "AF/KLM/DL", "123"):
            self.assertIsNone(bare_designator(not_code), not_code)

    def test_code_in_name_cell_resolves(self):
        m = self.idx.resolve("VS", None)
        self.assertEqual((m.status, m.canonical_name), (RESOLVED, "VIRGIN ATLANTIC"))

    def test_multi_carrier_is_not_near_matched(self):
        self.assertNotEqual(self.idx.resolve("AF/KLM/DL", None).canonical_name, "KLM ROYAL DUTCH AIRLINES")
        self.assertEqual(len(self.idx.split_carriers("AF/KLM/DL", None)), 3)


class SpreadsheetTest(unittest.TestCase):
    """A vendor-comparison workbook: %-formatted rates, a Source column, a TYPE column."""

    def workbook(self):
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Week", "A/L", "TYPE", "Code", "Source", "IATA", "PLB(ECO)", "PLB(PRE ECO)",
                   "PLB(BUS)", "Applicable", "Travel Validity", "Remarks"])
        ws.append(["23-30SEP", "AC", None, 14, "AKBAR", 0, 0.0125, 0.0175, 0.02, "B+YQ", "Till 31DEC'26", "x"])
        ws.append(["23-30SEP", "AI", "INTL", 98, "AKBAR", 0, 0.01, 0.015, 0.0275, "B+YQ", "TKTG Till 31DEC'26", ""])
        ws.append(["23-30SEP", "AC", None, 14, "BRIGHTSUN", 0, 0.0325, 0.0325, 0.035, "B+YQ", "Till 31DEC'26", ""])
        for row in ws.iter_rows(min_row=2):
            for c in row[5:9]:
                c.number_format = "0.00%"
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def test_reads_rates_and_keeps_one_supplier(self):
        from app.services.deal_supplier_check import supplier_cell_matches
        from app.services.pdf_table_rows import build_layout_from_sheet
        L = build_layout_from_sheet(
            self.workbook(), "vendor.xlsx",
            lambda cell: supplier_cell_matches(cell, "Akbar Travels of India Private Limited"))
        self.assertEqual(len(L.rows), 2)
        self.assertEqual(L.skipped_suppliers, {"BRIGHTSUN": 1})
        self.assertIsNone(L.colmap.code)                       # "Code" is the numeric stock code
        ac, ai = L.rows
        self.assertEqual(ac.cells[L.colmap.eco], "1.25%")       # 0.0125 with a % format
        self.assertEqual(ai.cells[L.colmap.airline], "AI (INTL)")
        deals = expand_row(deterministic_compact(ai, L.colmap), ai, Stats(), L.colmap)
        self.assertEqual([d["incentive_data"]["PLB"]["incentiveAmtPct"] for d in deals], [1.0, 1.5, 2.75])
        self.assertEqual(deals[0]["incentive_data"]["PLB"]["flightType"], "International")
        self.assertEqual(deals[0]["airline_code"], "AI")

    def test_no_filter_keeps_everyone(self):
        from app.services.pdf_table_rows import build_layout_from_sheet
        self.assertEqual(len(build_layout_from_sheet(self.workbook(), "vendor.xlsx").rows), 3)


# ── the real sheets ──────────────────────────────────────────────────────────

def _find(name):
    home = os.path.expanduser("~")
    for d in (os.environ.get("DEAL_SHEET_DIR"), os.path.join(home, "Downloads"),
              os.path.join(home, "OneDrive", "Desktop", "FareQube Docs", "TriumphTravel")):
        if d and os.path.isfile(os.path.join(d, name)):
            return os.path.join(d, name)
    return None


SHEETS = {
    # name: (rows, deal rows, rows the fast path reads, deals it yields)
    "LORDS DEAL 18 MAR.pdf": (115, 111, 106, 296),
    "AKBAR TRAVELS COSOLIDATOR PLB SHEET EFF 7 March 2026.pdf": (39, 34, 29, 84),
    "Mirror PCC Deal Sheet Effective March 24th.pdf": (80, 79, 79, 191),
    "Deal Sheet Effective 03Oct26.pdf": (60, 60, 58, 174),
}


class SampleSheetTest(unittest.TestCase):
    def _layout(self, name):
        path = _find(name)
        if not path:
            self.skipTest(f"{name} not available")
        from app.services.pdf_table_rows import build_layout
        with open(path, "rb") as f:
            return build_layout(f.read())

    def test_counts(self):
        for name, (rows, expects, local, deals) in SHEETS.items():
            with self.subTest(name):
                path = _find(name)
                if not path:
                    continue
                L = self._layout(name)
                got_local, got_deals = 0, 0
                for r in L.rows:
                    c = deterministic_compact(r, L.colmap)
                    if c is not None:
                        got_local += 1
                        got_deals += len(expand_row(c, r, Stats(), L.colmap))
                self.assertEqual(
                    (len(L.rows), sum(r.expects_deals for r in L.rows), got_local, got_deals),
                    (rows, expects, local, deals),
                )

    def test_vicky_merged_rates(self):
        L = self._layout("Deal Sheet Effective 03Oct26.pdf")
        cm = L.colmap
        by_name = {}
        for r in L.rows:
            by_name.setdefault(r.cells[cm.airline], []).append(r)

        def rates(name, i=0):
            r = by_name[name][i]
            return r.cells[cm.bus], r.cells[cm.pey], r.cells[cm.eco]

        self.assertEqual(rates("VS"), ("2.75%(B+YQ)", "2.75%(B+YQ)", "1.75%(B+YQ)"))
        self.assertEqual(rates("MH"), ("10.5%", "8.5% (B)", "8.5% (B)"))
        self.assertEqual(rates("SK"), ("2% (B+YQ)", "2% (B+YQ)", "0.0%"))
        self.assertEqual(rates("AZ", 1), ("2% (B+YQ+YR)",) * 3)    # the continuation row
        self.assertEqual(by_name["AZ"][1].cells[cm.validity], "FLOWN TILL 31ST Dec'26")


if __name__ == "__main__":
    unittest.main()
