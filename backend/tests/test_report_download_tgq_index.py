"""TGQ HMPR enrichment index — the report-mode extension, and proof the default path is unchanged.

The Workspace report download reuses ``bsp_tgq_enrichment.load_tgq_index`` with
``report_mode=True`` to put passenger, PNR, flight and fare basis on BSP rows. The commission
engine calls the same function with defaults, and a change in what IT sees would silently move
commission. So the cases below pin, in order of consequence:

* default mode: the SQL is the original statement, ``lookup`` answers exactly as the original
  algorithm did, and tickets carry no report fields;
* report mode: newest-first streaming, a cap that never splits an upload, excluded uploads,
  and the counters the Read Me discloses;
* ``_fold_legs`` report fields for split, pre-split and unparsed rows;
* ``match`` methods and codeless ambiguity (a serial two airlines share never joins).

No DB, no network: the database is a fake that records the statement and replays rows.

Run:  ..\\venv\\Scripts\\python.exe -m unittest test_report_download_tgq_index -v   (from backend/tests)
"""

import asyncio
import os
import sys
import unittest
from collections import namedtuple
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.statement_row import TgqHmpr  # noqa: E402
from app.services import bsp_tgq_enrichment as enr  # noqa: E402
from app.services import sector_split  # noqa: E402
from app.services.bsp_reconciliation import norm_tn  # noqa: E402

# Column order of the index query: 0-12 shared, 13-17 report mode only.
_BASE_FIELDS = ("batch_id", "uploaded_at", "id", "row_seq", "sector_index", "sector_count",
                "split_status", "airline_code", "ticket_no", "sectors", "cls", "traveldt",
                "ticket_date")
Row13 = namedtuple("Row13", _BASE_FIELDS)
Row18 = namedtuple("Row18", _BASE_FIELDS + ("pax_name", "air_pnr", "gal_pnr", "flightno", "fare_basis"))

T_OLD = datetime(2026, 7, 1, 9, 0)
T_NEW = datetime(2026, 8, 1, 9, 0)


def leg(id_, *, batch="B1", at=T_OLD, seq=1, idx=1, count=1, status="single", code="098",
        tkt="5805708071", sectors="BOM/DEL", cls="L", travel="14MAY", tdate="23APR26",
        pax="DOE/JOHN MR", air_pnr="ABC123", gal_pnr="GAL999", flight="AI-101", fare="LOWIN",
        report=True):
    base = (batch, at, id_, seq, idx, count, status, code, tkt, sectors, cls, travel, tdate)
    return Row18(*base, pax, air_pnr, gal_pnr, flight, fare) if report else Row13(*base)


def run(coro):
    return asyncio.run(coro)


def compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ── fakes ────────────────────────────────────────────────────────────────────

class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeExecuteDB:
    """No `stream` attribute: default mode, and report mode's keyset-paged fallback."""

    def __init__(self, pages):
        self.pages = [list(p) for p in pages]
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self.pages.pop(0) if self.pages else [])


class _StreamResult:
    def __init__(self, rows, chunk):
        self._rows = list(rows)
        self._chunk = chunk
        self.closed = False
        self.fetches = 0

    async def fetchmany(self, size=None):
        self.fetches += 1
        out, self._rows = self._rows[:self._chunk], self._rows[self._chunk:]
        return out

    async def close(self):
        self.closed = True


class FakeStreamDB:
    """Replays rows, already in the query's ORDER BY, in chunks of `chunk`."""

    def __init__(self, rows, chunk=2):
        self.rows = rows
        self.chunk = chunk
        self.statements = []
        self.result = None

    async def stream(self, stmt):
        self.statements.append(stmt)
        self.result = _StreamResult(self.rows, self.chunk)
        return self.result

    async def execute(self, stmt):  # pragma: no cover - must never be used when stream exists
        raise AssertionError("report mode must stream when the connection can")


# ── default mode is the commission engine's index, unchanged ─────────────────

def _original_query():
    """The pre-report-mode statement, verbatim from bsp_tgq_enrichment.load_tgq_index."""
    return (
        select(
            TgqHmpr.batch_id, TgqHmpr.uploaded_at, TgqHmpr.id,
            TgqHmpr.row_seq, TgqHmpr.sector_index, TgqHmpr.sector_count, TgqHmpr.split_status,
            TgqHmpr.data["airline_code"].astext,
            TgqHmpr.data["ticket_no"].astext,
            TgqHmpr.data["sectors"].astext,
            TgqHmpr.data["class"].astext,
            TgqHmpr.data["traveldt"].astext,
            TgqHmpr.data["ticket_date"].astext,
        )
        .where(
            TgqHmpr.tenant_id == 5,
            TgqHmpr.created_by_id == 9,
            TgqHmpr.is_total.is_(False),
        )
        .limit(enr.MAX_TGQ_ROWS + 1)
    )


def _original_lookup(exact, norm, accounting_code, document_number, alt_documents=None):
    """The pre-report-mode TgqIndex.lookup body, verbatim."""
    code = (accounting_code or "").strip().upper()
    if code.isdigit():
        code = code.zfill(3)
    if not code:
        return None
    for doc in [document_number, *(alt_documents or [])]:
        key = (doc or "").strip()
        if key and (hit := exact.get((code, key))) is not None:
            return hit
    key = norm_tn(document_number or "")
    return norm.get((code, key)) if key else None


class TestDefaultModeUnchanged(unittest.TestCase):

    def test_query_is_the_original_statement(self):
        db = FakeExecuteDB([[]])
        run(enr.load_tgq_index(db, 5, 9))
        self.assertEqual(len(db.statements), 1)
        self.assertEqual(compiled(db.statements[0]), compiled(_original_query()))

    def test_no_report_fields_and_no_codeless_map(self):
        rows = [leg(1, report=False, sectors="BOM/DEL", cls="L")]
        index = run(enr.load_tgq_index(FakeExecuteDB([rows]), 5, 9))
        t = index.lookup("098", "5805708071")
        self.assertIsNotNone(t)
        self.assertEqual((t.pax_name, t.air_pnr, t.gal_pnr, t.flight_numbers, t.fare_basis),
                         (None, None, None, None, None))
        self.assertEqual(index.match(None, "5805708071", allow_codeless=True), (None, None))
        self.assertFalse(index.truncated)
        self.assertEqual((index.rows_loaded, index.batches_used), (1, 1))

    def test_unparsed_row_without_class_or_travel_is_still_dropped(self):
        rows = [leg(1, report=False, status=sector_split.UNPARSED, sectors="X/SIN", cls="L L",
                    travel="")]
        index = run(enr.load_tgq_index(FakeExecuteDB([rows]), 5, 9))
        self.assertEqual(len(index), 0)

    def test_truncates_at_the_cap(self):
        rows = [leg(i, report=False, tkt=f"58057080{i:02d}") for i in range(1, 6)]
        with self.assertLogs(enr.logger, "WARNING"):
            index = run(enr.load_tgq_index(FakeExecuteDB([rows]), 5, 9, max_rows=3))
        self.assertTrue(index.truncated)
        self.assertEqual(index.rows_loaded, 3)
        self.assertEqual(len(index), 3)

    def test_lookup_answers_exactly_as_the_original_algorithm(self):
        a = enr.TgqTicket("BOM/DEL", "L", "14MAY", "23APR26", 1, "B1")
        b = enr.TgqTicket("DEL/BOM", "U", "15MAY", "23APR26", 1, "B1")
        exact = {("098", "5805708071"): a, ("098", "5800920932"): b, ("098", "5800920933"): b,
                 ("618", "0005708071"): a}
        norm = {("098", "5805708071"): a, ("098", "5800920932"): b, ("098", "5800920933"): b,
                ("618", "5708071"): None}
        index = enr.TgqIndex(exact, norm)
        codes = [None, "", " 98 ", "098", "618", "ai", "999"]
        docs = [None, "", " 5805708071 ", "05805708071", "058-05708071", "5800920933",
                "0005708071", "5708071", "9999999999"]
        alts = [None, [], ["5800920933"], ["", None, "5805708071"], ["nope"]]
        for code in codes:
            for doc in docs:
                for alt in alts:
                    with self.subTest(code=code, doc=doc, alt=alt):
                        self.assertIs(index.lookup(code, doc, alt),
                                      _original_lookup(exact, norm, code, doc, alt))

    def test_existing_positional_construction_still_works(self):
        t = enr.TgqTicket("BOM/DEL", "L", "14MAY", "23APR26", 2, "B1")
        self.assertEqual(t.leg_count, 2)
        self.assertIsNone(t.flight_numbers)
        index = enr.TgqIndex({}, {})
        self.assertEqual((index.truncated, index.rows_loaded, index.batches_used), (False, 0, 0))


# ── report mode: query, streaming, cap ───────────────────────────────────────

def _two_batches():
    """Newest batch B2 (3 legs, 2 tickets) then older B1 (3 legs) — the query's order."""
    return [
        leg(11, batch="B2", at=T_NEW, seq=1, idx=1, count=2, status="split", sectors="BOM/DEL",
            flight="AI-1", pax="NEW/PAX"),
        leg(12, batch="B2", at=T_NEW, seq=1, idx=2, count=2, status="split", sectors="DEL/BOM",
            flight="AI-2", pax="NEW/PAX"),
        leg(13, batch="B2", at=T_NEW, seq=2, tkt="5805708072", pax="OTHER/PAX"),
        leg(1, batch="B1", at=T_OLD, seq=1, pax="OLD/PAX", flight="AI-9"),
        leg(2, batch="B1", at=T_OLD, seq=2, tkt="5805708073"),
        leg(3, batch="B1", at=T_OLD, seq=3, tkt="5805708074"),
    ]


class TestReportModeLoad(unittest.TestCase):

    def test_statement_orders_excludes_and_adds_detail_columns(self):
        db = FakeStreamDB([])
        run(enr.load_tgq_index(db, 5, 9, report_mode=True,
                               exclude_batch_ids=frozenset({"BX", "BA"})))
        stmt = db.statements[0]
        sql = compiled(stmt)
        self.assertIn("ORDER BY tgq_hmpr.uploaded_at DESC, tgq_hmpr.batch_id ASC, tgq_hmpr.id ASC", sql)
        self.assertIn("tgq_hmpr.batch_id NOT IN ('BA', 'BX')", sql)
        self.assertIn("tgq_hmpr.is_total IS false", sql)
        self.assertNotIn("LIMIT", sql)
        self.assertEqual(len(stmt.selected_columns), 18)
        for field in ("pax_name", "air_pnr", "gal_pnr", "flightno", "fare_basis"):
            self.assertIn(f"tgq_hmpr.data ->> '{field}' AS {field}", sql)
        self.assertEqual(stmt.get_execution_options().get("yield_per"), enr.REPORT_FETCH_SIZE)
        self.assertTrue(db.result.closed)

    def test_exclusion_applies_only_when_given(self):
        db = FakeStreamDB([])
        run(enr.load_tgq_index(db, 5, 9, report_mode=True))
        self.assertNotIn("NOT IN", compiled(db.statements[0]))

    def test_newest_batch_wins_and_counters_are_set(self):
        db = FakeStreamDB(_two_batches())
        index = run(enr.load_tgq_index(db, 5, 9, report_mode=True))
        self.assertFalse(index.truncated)
        self.assertEqual((index.rows_loaded, index.batches_used), (6, 2))
        t = index.lookup("098", "5805708071")
        self.assertEqual((t.batch_id, t.pax_name, t.flight_numbers, t.sector, t.leg_count),
                         ("B2", "NEW/PAX", "AI-1/AI-2", "BOM/DEL/BOM", 2))
        self.assertEqual(index.lookup("098", "5805708074").pax_name, "DOE/JOHN MR")
        self.assertTrue(db.result.closed)

    def test_cap_stops_at_a_batch_boundary_never_inside_an_upload(self):
        # Chunks of 2 put the B2/B1 boundary mid-chunk and B2's last leg in a later chunk.
        for cap in (1, 2, 3):
            with self.subTest(cap=cap):
                db = FakeStreamDB(_two_batches(), chunk=2)
                with self.assertLogs(enr.logger, "WARNING"):
                    index = run(enr.load_tgq_index(db, 5, 9, report_mode=True, max_rows=cap))
                self.assertTrue(index.truncated)
                self.assertEqual((index.rows_loaded, index.batches_used), (3, 1))
                self.assertIsNone(index.lookup("098", "5805708073"))
                self.assertTrue(db.result.closed)

    def test_cap_equal_to_everything_is_not_truncation(self):
        db = FakeStreamDB(_two_batches(), chunk=4)
        index = run(enr.load_tgq_index(db, 5, 9, report_mode=True, max_rows=6))
        self.assertFalse(index.truncated)
        self.assertEqual(index.rows_loaded, 6)

    def test_keyset_fallback_pages_in_order_and_honours_the_cap(self):
        rows = _two_batches()
        with mock.patch.object(enr, "REPORT_FETCH_SIZE", 2):
            db = FakeExecuteDB([rows[0:2], rows[2:4], rows[4:6], []])
            index = run(enr.load_tgq_index(db, 5, 9, report_mode=True))
            self.assertEqual((index.rows_loaded, index.batches_used, index.truncated), (6, 2, False))
            self.assertEqual(len(db.statements), 4)
            first, second = compiled(db.statements[0]), compiled(db.statements[1])
            self.assertIn("LIMIT 2", first)
            self.assertNotIn("tgq_hmpr.uploaded_at <", first)
            # Resumes strictly after the last row of the previous page, in the same total order.
            self.assertIn("tgq_hmpr.uploaded_at < '2026-08-01 09:00:00'", second)
            self.assertIn("tgq_hmpr.batch_id > 'B2'", second)
            self.assertIn("tgq_hmpr.id > 12", second)

            db = FakeExecuteDB([rows[0:2], rows[2:4], rows[4:6], []])
            with self.assertLogs(enr.logger, "WARNING"):
                index = run(enr.load_tgq_index(db, 5, 9, report_mode=True, max_rows=2))
            self.assertEqual((index.rows_loaded, index.truncated), (3, True))
            self.assertEqual(len(db.statements), 2)

    def test_take_until_cap(self):
        rows = []
        chunk = [leg(1, batch="A"), leg(2, batch="A"), leg(3, batch="B")]
        self.assertTrue(enr._take_until_cap(rows, chunk, 1))
        self.assertEqual([r.id for r in rows], [1, 2])
        rows = []
        self.assertFalse(enr._take_until_cap(rows, chunk, 3))
        self.assertEqual(len(rows), 3)


# ── _fold_legs report fields ─────────────────────────────────────────────────

class TestFoldLegsReportFields(unittest.TestCase):

    def _split_legs(self):
        return [
            leg(1, seq=1, idx=1, count=3, status="split", sectors="BOM/DEL", cls="L",
                travel="28APR", flight="AI-2928", fare="LOWIN", pax="DOE/JOHN MR"),
            leg(2, seq=1, idx=2, count=3, status="split_partial", sectors="DEL/MNL", cls="L",
                travel="28APR", flight=None, fare="LOWIN", pax="IGNORED/LATER LEG",
                air_pnr="IGNORED"),
            leg(3, seq=1, idx=3, count=3, status="split", sectors="MNL/DEL", cls="U",
                travel="14MAY", flight=" AI-2361 ", fare="UOWIN"),
        ]

    def test_split_legs(self):
        t = enr._fold_legs(self._split_legs(), "B1", report_mode=True)
        self.assertEqual(t.pax_name, "DOE/JOHN MR")
        self.assertEqual((t.air_pnr, t.gal_pnr), ("ABC123", "GAL999"))
        self.assertEqual(t.flight_numbers, "AI-2928/AI-2361")   # blank leg skipped, order kept
        self.assertEqual(t.fare_basis, "LOWIN/UOWIN")
        self.assertEqual((t.sector, t.booking_class, t.travel_raw, t.leg_count),
                         ("BOM/DEL/MNL/DEL", "L/U", "28APR", 3))

    def test_default_mode_fold_is_identical_apart_from_report_fields(self):
        legs = self._split_legs()
        report = enr._fold_legs(legs, "B1", report_mode=True)
        default = enr._fold_legs([Row13(*r[:13]) for r in legs], "B1")
        self.assertEqual(default, enr.TgqTicket(report.sector, report.booking_class,
                                                report.travel_raw, report.ticket_date_raw,
                                                report.leg_count, report.batch_id))

    def test_repeated_fare_basis_and_flight_are_kept_in_order(self):
        legs = [leg(1, idx=1, count=2, status="split", sectors="BOM/DEL", flight="AI-1", fare="Y"),
                leg(2, idx=2, count=2, status="split", sectors="DEL/LHR", flight="AI-1", fare="Y")]
        t = enr._fold_legs(legs, "B1", report_mode=True)
        self.assertEqual((t.flight_numbers, t.fare_basis), ("AI-1/AI-1", "Y"))

    def test_pre_split_row_tokenises_flights_like_split_row_would(self):
        row = leg(1, count=None, status=None, sectors="BOM/DEL DEL/BOM", cls="L U",
                  travel="28APR 14MAY", flight="AI-1 AI-2", fare="LOWIN")
        t = enr._fold_legs([row], "B1", report_mode=True)
        self.assertEqual((t.sector, t.leg_count, t.flight_numbers, t.fare_basis),
                         ("BOM/DEL/BOM", 2, "AI-1/AI-2", "LOWIN"))

    def test_pre_split_single_leg_keeps_the_flight_cell_whole(self):
        row = leg(1, count=None, status=None, sectors="BOM/DEL", flight="AI 101")
        self.assertEqual(enr._fold_legs([row], "B1", report_mode=True).flight_numbers, "AI 101")

    def test_unparsed_row_with_pax_is_kept_identity_only(self):
        row = leg(1, count=1, status=sector_split.UNPARSED, sectors="X/SIN", cls="L L",
                  travel="", flight="AI-1 AI-2", pax="DOE/JANE MS", air_pnr=None, gal_pnr=None)
        t = enr._fold_legs([row], "B1", report_mode=True)
        self.assertEqual((t.sector, t.booking_class, t.travel_raw, t.leg_count),
                         (None, None, None, 1))
        self.assertEqual((t.pax_name, t.flight_numbers), ("DOE/JANE MS", "AI-1 AI-2"))
        self.assertIsNone(enr._fold_legs([Row13(*row[:13])], "B1"))

    def test_pre_split_unparsed_row_with_only_a_gds_pnr_is_kept(self):
        row = leg(1, count=None, status=None, sectors="X/SIN junk", cls="", travel="",
                  pax=None, air_pnr="", gal_pnr="GAL1")
        t = enr._fold_legs([row], "B1", report_mode=True)
        self.assertEqual(t.gal_pnr, "GAL1")
        self.assertIsNone(t.air_pnr)

    def test_unparsed_row_without_identity_is_dropped_in_report_mode_too(self):
        row = leg(1, count=1, status=sector_split.UNPARSED, sectors="X/SIN", cls="", travel="",
                  pax="  ", air_pnr=None, gal_pnr="", flight="AI-1")
        self.assertIsNone(enr._fold_legs([row], "B1", report_mode=True))


# ── match methods ────────────────────────────────────────────────────────────

class TestMatch(unittest.TestCase):

    def setUp(self):
        rows = [
            leg(1, batch="B1", code="098", tkt="5805708071", pax="A"),
            leg(2, batch="B1", code="098", tkt="5800920932-933", seq=2, pax="CONJ"),
            leg(3, batch="B1", code="098", tkt="5801111111", seq=3, pax="SHARED-098"),
            leg(4, batch="B1", code="618", tkt="5801111111", seq=4, pax="SHARED-618"),
            leg(5, batch="B1", code="618", tkt="5802222222", seq=5, pax="ONLY-618"),
        ]
        self.index = run(enr.load_tgq_index(FakeStreamDB(rows), 5, 9, report_mode=True))

    def names(self, result):
        ticket, method = result
        return (ticket.pax_name if ticket else None, method)

    def test_document(self):
        self.assertEqual(self.names(self.index.match(" 98", "5805708071")), ("A", "document"))

    def test_conjunction_via_alternate_document(self):
        self.assertEqual(self.names(self.index.match("098", "9999999999", ["5800920933"])),
                         ("CONJ", "conjunction"))
        # the expanded serial is also a direct document hit
        self.assertEqual(self.names(self.index.match("098", "5800920933")), ("CONJ", "document"))

    def test_rtdn_via_extra_documents(self):
        self.assertEqual(
            self.names(self.index.match("098", "0000000001", [], extra_documents=["5805708071"])),
            ("A", "rtdn"))

    def test_normalised(self):
        self.assertEqual(self.names(self.index.match("098", "058-05708071")), ("A", "normalised"))

    def test_precedence_document_then_alternate_then_rtdn(self):
        m = self.index.match("098", "5805708071", ["5800920932"], extra_documents=["5801111111"])
        self.assertEqual(self.names(m), ("A", "document"))
        m = self.index.match("098", "x", ["5800920932"], extra_documents=["5805708071"])
        self.assertEqual(self.names(m), ("CONJ", "conjunction"))

    def test_miss(self):
        self.assertEqual(self.index.match("098", "1234567890"), (None, None))
        self.assertEqual(self.index.match("098", None), (None, None))

    def test_codeless_requires_opt_in(self):
        self.assertEqual(self.index.match(None, "5805708071"), (None, None))
        self.assertEqual(self.names(self.index.match("", "5805708071", allow_codeless=True)),
                         ("A", "codeless"))

    def test_codeless_serial_held_by_two_codes_is_a_miss(self):
        self.assertEqual(self.index.match(None, "5801111111", allow_codeless=True), (None, None))
        # ... and does not fall through to a unique alternate: the row cannot be placed.
        self.assertEqual(
            self.index.match(None, "5801111111", ["5802222222"], allow_codeless=True),
            (None, None))
        self.assertIsNone(self.index._by_serial["5801111111"])

    def test_codeless_probes_alternates_and_extras(self):
        self.assertEqual(
            self.names(self.index.match(None, "nope", None, extra_documents=["5802222222"],
                                        allow_codeless=True)),
            ("ONLY-618", "codeless"))

    def test_a_code_that_misses_never_falls_back_to_codeless(self):
        self.assertEqual(self.index.match("217", "5802222222", allow_codeless=True), (None, None))

    def test_serial_map_ambiguity_is_sticky(self):
        a, b, c = (enr.TgqTicket(None, None, None, None, 1, x) for x in "ABC")
        out = enr._serial_map({("098", "1"): a, ("618", "1"): b, ("217", "1"): c, ("098", "2"): a})
        self.assertEqual(out, {"1": None, "2": a})


if __name__ == "__main__":
    unittest.main()
