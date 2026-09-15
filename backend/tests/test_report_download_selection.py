"""Report download — owner-verified selection, size estimate and the picker's duplicate hint.

Pinned:

* ``mark_possible_duplicates``: an older upload of the same type with the same row count and
  date range points at the NEWER one and is left unticked; a same-name-only match (case-
  insensitive) is noted but stays ticked; uploads with different references (airline /
  supplier) never match; the newest never points anywhere; different types never match;
  undated shapes (no date range) do not count as the same file.
* ``estimate``: every included row, doubled with detail sheets, 62 cells per row.
* ``OwnedSelection.for_source`` is newest first (the de-duplication order).
* ``resolve_selection`` refuses unknown types, ids that are not the caller's and
  not-completed BSP / LCC Detailed uploads, and its per-source statements compile for
  PostgreSQL with the owner filter present — all on a fake connection, no DB.

Run:  ..\\venv\\Scripts\\python.exe -m unittest test_report_download_selection -v   (from backend/tests)
"""
import asyncio
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.services.report_download import selection as S  # noqa: E402
from app.services.report_download.queries import mark_possible_duplicates  # noqa: E402
from app.services.report_download.registry import get_source  # noqa: E402
from app.services.report_download.types import ReportOptions  # noqa: E402


def upload(uid, *, source="tp-gds", name="stmt.xlsx", at=datetime(2026, 7, 1), total=10,
           dmin="2026-07-01", dmax="2026-07-15", reference=None):
    return {"source_type": source, "upload_id": uid, "file_name": name, "uploaded_at": at,
            "total_rows": total, "date_min": dmin, "date_max": dmax, "reference": reference,
            "possible_duplicate_of": None, "default_selected": True}


class MarkPossibleDuplicates(unittest.TestCase):
    def test_same_file_name_only_is_noted_but_stays_ticked(self):
        old = upload("u-old", name="Riya JULY.xlsx", at=datetime(2026, 7, 2), total=5)
        new = upload("u-new", name="riya july.XLSX ", at=datetime(2026, 7, 9), total=7, dmin="2026-07-02")
        items = [old, new]
        mark_possible_duplicates(items)
        self.assertEqual(old["possible_duplicate_of"], {"upload_id": "u-new", "file_name": "riya july.XLSX "})
        self.assertTrue(old["default_selected"])
        self.assertIsNone(new["possible_duplicate_of"])
        self.assertTrue(new["default_selected"])

    def test_same_shape_points_older_at_newer_and_unticks_it(self):
        old = upload("a", name="first.xlsx", at=datetime(2026, 7, 1))
        new = upload("b", name="second.xlsx", at=datetime(2026, 7, 5))
        mark_possible_duplicates([new, old])
        self.assertEqual(old["possible_duplicate_of"]["upload_id"], "b")
        self.assertFalse(old["default_selected"])
        self.assertIsNone(new["possible_duplicate_of"])

    def test_different_airline_with_same_name_is_unrelated(self):
        # Two LCC DI files named alike but for different airlines — never a duplicate.
        indigo = upload("a", source="lcc-di", name="Statement.xlsx", at=datetime(2026, 7, 1),
                        total=40, reference="IndiGo")
        spice = upload("b", source="lcc-di", name="statement.xlsx", at=datetime(2026, 7, 5),
                       total=12, dmin="2026-07-03", reference="SpiceJet")
        mark_possible_duplicates([indigo, spice])
        self.assertIsNone(indigo["possible_duplicate_of"])
        self.assertTrue(indigo["default_selected"])

    def test_same_shape_but_different_reference_is_unrelated(self):
        a = upload("a", at=datetime(2026, 7, 1), reference="Supplier A")
        b = upload("b", at=datetime(2026, 7, 5), reference="Supplier B")
        mark_possible_duplicates([a, b])
        self.assertIsNone(a["possible_duplicate_of"])
        self.assertTrue(a["default_selected"])

    def test_different_shape_or_type_is_not_a_duplicate(self):
        a = upload("a", name="one.xlsx", at=datetime(2026, 7, 1), total=10)
        b = upload("b", name="two.xlsx", at=datetime(2026, 7, 5), total=11)
        c = upload("c", source="tp-lcc", name="one.xlsx", at=datetime(2026, 7, 9), total=10)
        mark_possible_duplicates([a, b, c])
        self.assertTrue(all(u["possible_duplicate_of"] is None for u in (a, b, c)))

    def test_undated_shape_needs_a_name_match(self):
        a = upload("a", name="one.xlsx", at=datetime(2026, 7, 1), dmin=None, dmax=None)
        b = upload("b", name="two.xlsx", at=datetime(2026, 7, 5), dmin=None, dmax=None)
        mark_possible_duplicates([a, b])
        self.assertIsNone(a["possible_duplicate_of"])

    def test_three_copies_point_at_the_newest(self):
        a = upload("a", at=datetime(2026, 7, 1))
        b = upload("b", at=datetime(2026, 7, 2))
        c = upload("c", at=datetime(2026, 7, 3))
        mark_possible_duplicates([a, b, c])
        self.assertEqual(a["possible_duplicate_of"]["upload_id"], "c")
        self.assertEqual(b["possible_duplicate_of"]["upload_id"], "c")
        self.assertIsNone(c["possible_duplicate_of"])


def owned(source, uid, *, total, at=datetime(2026, 7, 1), status=None):
    return S.OwnedUpload(source_key=source, upload_id=uid, file_name=f"{uid}.xlsx", uploaded_at=at,
                         status=status, total_rows=total)


class EstimateAndOrdering(unittest.TestCase):
    def setUp(self):
        self.sel = S.OwnedSelection(tenant_id=1, user_id=2, uploads=(
            owned("bsp", "s-old", total=1000, at=datetime(2026, 7, 1), status="completed"),
            owned("bsp", "s-new", total=500, at=datetime(2026, 7, 9), status="completed"),
            owned("tgq-hmpr", "t1", total=250),
        ))

    def test_estimate_doubles_with_detail_sheets(self):
        self.assertEqual(S.estimate(self.sel, ReportOptions(include_detail_sheets=True)), (3500, 3500 * 62))
        self.assertEqual(S.estimate(self.sel, ReportOptions(include_detail_sheets=False)), (1750, 1750 * 62))

    def test_for_source_is_newest_first(self):
        self.assertEqual(self.sel.ids("bsp"), ["s-new", "s-old"])
        self.assertEqual(self.sel.for_source("ndc"), [])


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeConn:
    """Answers each owned-upload statement with the rows registered for its FROM table and
    keeps the compiled SQL for inspection."""

    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table
        self.sql = []

    async def execute(self, stmt, *args, **kwargs):
        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))
        tables = [getattr(f, "name", None) for f in stmt.get_final_froms()]
        for name in tables:
            if name in self.rows_by_table:
                return FakeResult(self.rows_by_table[name])
        return FakeResult([])


def run(coro):
    return asyncio.run(coro)


class ResolveSelection(unittest.TestCase):
    def test_unknown_source_type(self):
        with self.assertRaisesRegex(S.SelectionError, "Unknown source type 'nope'"):
            run(S.resolve_selection(FakeConn({}), 1, 2, [("nope", "x")]))

    def test_missing_or_foreign_id(self):
        conn = FakeConn({"tgq_hmpr": [("t1", "a.xlsx", datetime(2026, 7, 1), None, 12, None)]})
        with self.assertRaisesRegex(S.SelectionError, "TGQ HMPR upload t2 was not found"):
            run(S.resolve_selection(conn, 1, 2, [("tgq-hmpr", "t1"), ("tgq-hmpr", "t2")]))

    def test_not_completed_bsp_is_refused(self):
        conn = FakeConn({"bsp_statements": [("s1", "bsp.pdf", datetime(2026, 7, 1), "processing", 10, "BSP")]})
        with self.assertRaisesRegex(S.SelectionError, "is processing, not completed"):
            run(S.resolve_selection(conn, 1, 2, [("bsp", "s1")]))

    def test_owned_selection_and_unticked(self):
        conn = FakeConn({
            "bsp_statements": [("s1", "bsp.pdf", datetime(2026, 7, 1), "completed", 15204, "BSP JUL")],
            "tgq_hmpr": [("t1", "a.xlsx", datetime(2026, 7, 2), None, 12, None),
                         ("t9", "old.xlsx", datetime(2026, 6, 2), None, 3, None)],
        })
        sel = run(S.resolve_selection(conn, 7, 8, [("bsp", "s1"), ("tgq-hmpr", "t1")],
                                      [("tgq-hmpr", "t9"), ("tgq-hmpr", "gone")]))
        self.assertEqual([(u.source_key, u.upload_id, u.total_rows) for u in sel.uploads],
                         [("bsp", "s1", 15204), ("tgq-hmpr", "t1", 12)])
        self.assertEqual(sel.uploads[0].reference, "BSP JUL")
        # a vanished unticked id is dropped, not an error
        self.assertEqual([u.upload_id for u in sel.unticked], ["t9"])
        self.assertEqual(sel.unticked_ids("tgq-hmpr"), ["t9"])
        for sql in conn.sql:
            self.assertIn("tenant_id = %(tenant_id_1)s", sql)
            self.assertIn("created_by_id = %(created_by_id_1)s", sql)

    def test_included_and_unticked_at_once(self):
        with self.assertRaisesRegex(S.SelectionError, "both included and unticked"):
            run(S.resolve_selection(FakeConn({}), 1, 2, [("ndc", "n1")], [("ndc", "n1")]))

    def test_every_source_statement_compiles(self):
        for key in ("bsp", "bsp-summary", "adm", "ra", "tgq-hmpr", "ndc", "lcc-detailed", "lcc-di", "tp-api"):
            stmt = S._owned_statement(get_source(key), 1, 2, ["a", "b"])
            sql = str(stmt.compile(dialect=postgresql.dialect()))
            self.assertIn("= ANY (", sql, key)
            self.assertIn("created_by_id", sql, key)


if __name__ == "__main__":
    unittest.main()
