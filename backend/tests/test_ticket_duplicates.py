"""Internal Statement: a ticket already loaded is a duplicate — no DB.

The rule (services/ticket_duplicates.py): an upload of any period, at any time, leaves out
every line whose Booked Date, Ticket No, Pax Name, Amount and Travel Date match a ticket
already loaded — or a line above it in the same file — and a file of nothing but duplicates
is refused. Pinned here: what makes two lines the same, the split, the lookup, the switch
that confines all this to Internal Statement, and the migration's frozen copy of the key.

Run:  python -m unittest discover backend/tests
"""
import asyncio
import importlib.util
import os
import sys
import unittest
from collections import namedtuple
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: E402,F401
from fastapi import HTTPException  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api.v1 import internal_tickets  # noqa: E402
from app.api.v1 import tickets as customer_tickets  # noqa: E402
from app.models.internal_ticket import InternalTicketStatement, InternalUploadedTicket  # noqa: E402
from app.schemas.uploaded_ticket import ConfirmTicketUploadPayload, TicketRow  # noqa: E402
from app.services import ticket_duplicates as td  # noqa: E402

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION = VERSIONS / "internal_dupes_01_ticket_duplicate_keys.py"

USER = SimpleNamespace(id=14, tenant_id=3)
GLOBE = customer_tickets.CustomerParty("agency", agency_id=28, name="Globe Air Travels", label="B2B")

# Shaped like the real GLOBE ticket statement: a sale and, in another voucher, its refund.
SALE = {"doc_no": "IS26/   1094", "doc_date": "2026-08-16", "ticket_number": "5808758776",
        "ticket_prefix": "157", "gds_pnr": "HQSTH5", "pax_name": "NAGPAL/RAVINDER SINGH",
        "departure_datetime": "2026-09-02", "sector": "ATH/DOH DOH/DEL", "sell_fare": 69305.0,
        "total_amt": 94621.0}
REFUND = {**SALE, "doc_no": "IR26/    387", "doc_date": "2026-08-22", "sell_fare": -69305.0,
          "total_amt": -94389.0}

WEEK1 = td.Loaded("B1", "B2B - Globe Air Travels - 2026-08-01", "GLOBE OUR 01 07 AUG 26.xls",
                  date(2026, 8, 1), date(2026, 8, 7), datetime(2026, 10, 17, 9, 0))
MONTH = td.Loaded("B2", "B2B - Globe Air Travels - 2026-08-01", "GLOBE OUR AUG 26.xls",
                  date(2026, 8, 1), date(2026, 8, 31), datetime(2026, 10, 20, 11, 30))


def line(n: int, **over) -> dict:
    return {"doc_no": f"IS26/   {1000 + n}", "doc_date": "2026-08-10", "ticket_number": f"58087580{n:02d}",
            "pax_name": f"PAX/{n}", "departure_datetime": "2026-08-20", "total_amt": float(1100 + n), **over}


def split(rows, loaded_rows=(), where=WEEK1):
    return td.partition(rows, [td.ticket_key(r) for r in rows], {td.ticket_key(r): where for r in loaded_rows})


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


Found = namedtuple("Found", ("id", "dedup_key", *td.KEY_COLUMNS, "batch_id", "statement_name", "file_name",
                             "valid_from", "valid_to", "created_at"))


def found(row: dict, where: td.Loaded = WEEK1, key="stamped", n: int = 1) -> Found:
    """A loaded ticket as the lookup selects it: its id, stored key, key columns and statement.
    `key`: "stamped" — stored as the rule keys it; None — never stored; any other string — a
    key stored under an older rule."""
    stored = td.ticket_key(row) if key == "stamped" else key
    return Found(n, stored, *[row.get(c) for c in td.KEY_COLUMNS], where.batch_id, where.statement_name,
                 where.file_name, where.valid_from, where.valid_to, where.created_at)


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeDB:
    """Hands out the given results in order; records each statement and anything added."""

    def __init__(self, *results):
        self.results = [_Rows(r) for r in results]
        self.statements, self.added = [], []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return self.results.pop(0) if self.results else _Rows([])

    def add(self, obj):
        self.added.append(obj)


# ── what makes two lines the same ────────────────────────────────────────────
class KeyTests(unittest.TestCase):
    def test_each_of_the_five_makes_a_different_ticket(self):
        for change in ({"doc_date": "2026-08-17"}, {"ticket_number": "5808758777"},
                       {"pax_name": "NAGPAL/RAVINDER"}, {"total_amt": 94680.0},
                       {"departure_datetime": "2026-09-03"}):
            with self.subTest(change=change):
                self.assertNotEqual(td.ticket_key(SALE), td.ticket_key({**SALE, **change}))

    def test_nothing_else_counts(self):
        """Another Doc No, PNR, sector or fare — the same five are the same ticket."""
        other = {**SALE, "doc_no": "IS26/2001", "gds_pnr": "ZZZZZZ", "sector": "DEL/BOM",
                 "sell_fare": 1.0, "ticket_prefix": None}
        self.assertEqual(td.ticket_key(SALE), td.ticket_key(other))

    def test_booked_date_is_the_ticket_date_else_the_doc_date(self):
        self.assertEqual(td.booked_date(SALE), "2026-08-16")
        with_ticket_date = {**SALE, "ticket_date": "2026-08-15"}
        self.assertEqual(td.booked_date(with_ticket_date), "2026-08-15")
        self.assertEqual(td.ticket_key(with_ticket_date),
                         td.ticket_key({**with_ticket_date, "doc_date": "2026-08-30"}))

    def test_case_spacing_float_noise_and_a_time_do_not_matter(self):
        a = {**SALE, "total_amt": 94620.99999999, "pax_name": "nagpal/ravinder  singh",
             "departure_datetime": "2026-09-02T06:40:00", "ticket_number": "157 5808758776"}
        self.assertEqual(td.ticket_key(a), td.ticket_key(SALE))

    def test_a_sale_and_its_refund_are_never_the_same(self):
        self.assertEqual((td.kind(SALE), td.kind(REFUND)), ("S", "R"))
        # Even when the refund is printed with the sale's own date and positive amount.
        positive = {**SALE, "doc_no": None, "invoice_type": "Refund"}
        self.assertNotEqual(td.ticket_key({**SALE, "doc_no": None}), td.ticket_key(positive))

    def test_the_passenger_from_its_name_parts(self):
        parts = {**SALE, "pax_name": None, "last_name": "NAGPAL/RAVINDER", "first_name": "SINGH"}
        self.assertEqual(td.ticket_key(parts), td.ticket_key(SALE))

    def test_a_line_nothing_names_has_no_key(self):
        self.assertIsNone(td.ticket_key({"doc_date": "2026-08-10", "total_amt": 500.0}))
        self.assertIsNotNone(td.ticket_key({"pax_name": "PAX/1", "total_amt": 500.0}))
        self.assertIsNotNone(td.ticket_key({"ticket_number": "5808758776"}))

    def test_a_saved_ticket_keys_as_its_uploaded_line(self):
        """A stored ticket (Numeric amount, string dates) keys as the line it came from."""
        saved = SimpleNamespace(**{**SALE, "total_amt": Decimal("94621.00"), "ticket_date": None,
                                   "last_name": None, "first_name": None, "invoice_type": None})
        self.assertEqual(td.ticket_key(saved), td.ticket_key(SALE))


# ── the split ────────────────────────────────────────────────────────────────
class PartitionTests(unittest.TestCase):
    def test_nothing_loaded_saves_everything(self):
        out = split([line(1), line(2), SALE])
        self.assertEqual((out.kept, out.count, out.new, out.refusal()), ([0, 1, 2], 0, 3, None))

    def test_a_ticket_loaded_under_any_period_is_left_out(self):
        """The week is loaded; the month is uploaded: only the week's tickets are duplicates."""
        week = [line(1), line(2)]
        out = split(week + [line(3), SALE], loaded_rows=week)
        self.assertEqual((out.kept, out.count, out.new), ([2, 3], 2, 2))
        self.assertEqual([(d["index"], d["batch_id"]) for d in out.lines], [(0, "B1"), (1, "B1")])
        self.assertEqual(out.duplicate_of, "B1")
        self.assertEqual(out.summary()["statements"], [{**WEEK1.as_dict(), "matched": 2}])
        self.assertEqual(out.summary()["statements"][0]["period_label"], "01–07 Aug 2026")

    def test_the_file_is_not_checked_against_itself(self):
        """A line the file holds twice is saved twice — only what is already loaded counts."""
        out = split([line(1), line(2), line(1), dict(line(1))])
        self.assertEqual((out.kept, out.count, out.refusal()), ([0, 1, 2, 3], 0, None))

    def test_every_repeat_of_a_loaded_ticket_is_a_duplicate(self):
        out = split([line(1), line(1)], loaded_rows=[line(1)])
        self.assertEqual([d["batch_id"] for d in out.lines], ["B1", "B1"])
        self.assertEqual(out.matched["B1"], 2)

    def test_lines_nothing_names_are_always_saved(self):
        blank = {"doc_date": "2026-08-10", "total_amt": 500.0}
        out = split([blank, dict(blank)], loaded_rows=[blank])
        self.assertEqual((out.kept, out.count), ([0, 1], 0))

    def test_a_file_of_nothing_but_duplicates_is_refused(self):
        out = split([line(1), line(2)], loaded_rows=[line(1), line(2)])
        self.assertEqual(out.refusal(),
                         "All 2 tickets of this file are duplicates of tickets already loaded"
                         " — there is nothing new to save.")
        self.assertFalse(out.preview()["can_save"])

    def test_what_the_preview_shows(self):
        out = split([line(1), SALE, line(2)], loaded_rows=[SALE, line(2)])
        p = out.preview()
        self.assertEqual((p["total"], p["duplicates"], p["new"]), (3, 2, 1))
        self.assertNotIn("in_file", p)
        self.assertEqual(p["duplicates_amount"], "95723.00")
        self.assertEqual(p["rows"], [{"index": 1, "batch_id": "B1"}, {"index": 2, "batch_id": "B1"}])
        self.assertEqual({k: p["lines"][0][k] for k in ("ticket_number", "pax_name", "booked_date",
                                                        "travel_date", "total_amt")},
                         {"ticket_number": "5808758776", "pax_name": "NAGPAL/RAVINDER SINGH",
                          "booked_date": "2026-08-16", "travel_date": "2026-09-02", "total_amt": 94621.0})
        self.assertTrue(p["can_save"])
        self.assertIsNone(p["reason"])


# ── the lookup ───────────────────────────────────────────────────────────────
class LookupTests(unittest.TestCase):
    def find(self, db, rows):
        return asyncio.run(td.find(db, USER, rows, statements=InternalTicketStatement,
                                   tickets=InternalUploadedTicket))

    def test_scoped_to_the_user_and_the_files_tickets_any_period(self):
        db = FakeDB([found(SALE, MONTH, n=2), found(SALE, WEEK1, n=1)])
        out = self.find(db, [SALE, line(1)])
        self.assertEqual((out.kept, out.lines[0]["batch_id"]), ([1], "B1"))   # the earliest
        sql = _sql(db.statements[0])
        for part in ("internal_uploaded_tickets.tenant_id = 3", "internal_uploaded_tickets.created_by_id = 14",
                     "internal_uploaded_tickets.dedup_key IN (", "JOIN internal_ticket_statements",
                     "right(regexp_replace(upper(coalesce(internal_uploaded_tickets.ticket_number, '')), "
                     "'[^0-9A-Z]', '', 'g'), 10) IN ('5808758001', '5808758776')"):
            with self.subTest(part=part):
                self.assertIn(part, sql)
        for absent in ("valid_from <=", "customer_agency_id", "Manual Entry"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, sql)

    def test_a_ticket_saved_under_an_older_key_is_found_by_its_columns(self):
        """What the database held before the migration: a stored key from the period check."""
        for stored in (None, "0" * 64):
            with self.subTest(stored=stored):
                out = self.find(FakeDB([found(SALE, WEEK1, key=stored)]), [SALE, line(1)])
                self.assertEqual(([d["batch_id"] for d in out.lines], out.kept), (["B1"], [1]))

    def test_a_ticket_edited_since_is_found_by_the_key_it_was_saved_with(self):
        edited = found({**SALE, "pax_name": "NAGPAL/RAVINDER"}, WEEK1, key=td.ticket_key(SALE))
        out = self.find(FakeDB([edited]), [SALE])
        self.assertEqual(out.count, 1)

    def test_a_same_numbered_ticket_that_differs_is_not_a_duplicate(self):
        """Read as a candidate by its ticket number; the key decides."""
        out = self.find(FakeDB([found({**SALE, "total_amt": 94680.0}, WEEK1)]), [SALE])
        self.assertEqual((out.count, out.kept), (0, [0]))

    def test_a_file_nothing_names_reads_nothing(self):
        db = FakeDB()
        out = asyncio.run(td.find(db, USER, [{"total_amt": 5.0}],
                                  statements=InternalTicketStatement, tickets=InternalUploadedTicket))
        self.assertEqual((out.kept, db.statements), ([0], []))

    def test_the_lock_is_per_user(self):
        self.assertEqual(td.lock_key(USER), td.lock_key(SimpleNamespace(id=14, tenant_id=3)))
        self.assertNotEqual(td.lock_key(USER), td.lock_key(SimpleNamespace(id=15, tenant_id=3)))


# ── the router ───────────────────────────────────────────────────────────────
def _routes(router) -> set:
    return {(m, r.path) for r in router.routes for m in (getattr(r, "methods", None) or set())}


class SwitchTests(unittest.TestCase):
    def test_only_internal_statement_checks(self):
        self.assertFalse(customer_tickets.DUPLICATE_CHECK)
        self.assertTrue(internal_tickets._impl.DUPLICATE_CHECK)

    def test_the_period_checks_are_gone(self):
        self.assertFalse(hasattr(customer_tickets, "REUPLOAD_CHECK"))
        self.assertFalse(hasattr(internal_tickets._impl, "REUPLOAD_CHECK"))
        internal = _routes(internal_tickets.router)
        for ep in (("GET", "/upload/period-uploads"), ("POST", "/upload/save-preview")):
            with self.subTest(endpoint=ep):
                self.assertNotIn(ep, internal)

    def test_the_details_step_keeps_what_fills_it_in(self):
        """Attach → details filled in from the file, date format asked → Next."""
        internal, customer = _routes(internal_tickets.router), _routes(customer_tickets.router)
        for ep in (("POST", "/upload/guess"), ("POST", "/upload/detect-date-formats"),
                   ("GET", "/upload/last-date-formats")):
            with self.subTest(endpoint=ep):
                self.assertIn(ep, internal)
                self.assertNotIn(ep, customer)

    def test_the_last_date_format_is_looked_up_per_customer(self):
        conds = internal_tickets._party_conditions(GLOBE)
        self.assertEqual([str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
                          for c in conds],
                         ["internal_ticket_statements.customer_type = 'agency'",
                          "internal_ticket_statements.customer_agency_id = 28"])
        self.assertIsNone(internal_tickets._party_conditions(customer_tickets.CustomerParty("direct")))

    def test_the_duplicate_check_is_internal_only(self):
        self.assertIn(("POST", "/upload/duplicates"), _routes(internal_tickets.router))
        self.assertNotIn(("POST", "/upload/duplicates"), _routes(customer_tickets.router))

    def test_the_endpoint_answers_through_the_same_code(self):
        payload = internal_tickets._DuplicatesPayload(rows=[TicketRow(**r) for r in (SALE, line(1), line(1))])
        db = FakeDB([found(SALE, WEEK1)])
        out = asyncio.run(internal_tickets.check_duplicates(payload, db=db, current_user=USER))
        # Row 3 repeats row 2 of the same file: both are saved.
        self.assertEqual(out["rows"], [{"index": 0, "batch_id": "B1"}])
        self.assertEqual((out["new"], out["can_save"]), (2, True))


class ConfirmTests(unittest.TestCase):
    def payload(self, rows, **over):
        base = dict(file_name="GLOBE OUR AUG 26.xls", rows=[TicketRow(**r) for r in rows],
                    agency="Globe Air Travels", customer_type="agency", customer_agency_id=28,
                    valid_from=date(2026, 8, 1), valid_to=date(2026, 8, 31),
                    # An Internal Statement upload always declares how its dates are written.
                    date_formats={"ticket_date": "DMY", "departure_datetime": "DMY"})
        base.update(over)
        return ConfirmTicketUploadPayload(**base)

    def run_confirm(self, db, payload):
        impl = internal_tickets._impl

        async def party(*_a, **_k):
            return GLOBE
        real, impl._resolve_customer_party = impl._resolve_customer_party, party
        try:
            return asyncio.run(impl.confirm_ticket_upload(payload, db=db, current_user=USER))
        finally:
            impl._resolve_customer_party = real

    def test_nothing_new_is_refused_and_nothing_written(self):
        db = FakeDB([], [found(SALE), found(REFUND)])
        with self.assertRaises(HTTPException) as cm:
            self.run_confirm(db, self.payload([SALE, REFUND]))
        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("All 2 tickets of this file are duplicates", cm.exception.detail)
        self.assertTrue(cm.exception.detail.endswith("Nothing was saved."))
        self.assertIn("pg_advisory_xact_lock", str(db.statements[0]))
        self.assertEqual(db.added, [])

    def test_every_saved_ticket_keeps_its_key(self):
        rows = [TicketRow(**SALE), TicketRow(**line(1))]
        built = [SimpleNamespace(dedup_key=None), SimpleNamespace(dedup_key=None)]
        internal_tickets._impl._stamp_keys(built, rows)
        self.assertEqual([b.dedup_key for b in built], [td.ticket_key(r.model_dump()) for r in rows])
        self.assertEqual(built[0].dedup_key, td.ticket_key(SALE))

    def test_customer_data_keys_nothing(self):
        built = [SimpleNamespace(dedup_key=None)]
        customer_tickets._stamp_keys(built, [TicketRow(**SALE)])
        self.assertIsNone(built[0].dedup_key)


class MigrationTests(unittest.TestCase):
    src = MIGRATION.read_text(encoding="utf-8")

    def test_chains_onto_the_previous_head_without_forking(self):
        self.assertIn("down_revision: Union[str, None] = 'tp_gds_dupes_02'", self.src)
        siblings = [f.name for f in VERSIONS.glob("*.py") if f != MIGRATION
                    and "down_revision: Union[str, None] = 'tp_gds_dupes_02'" in f.read_text(encoding="utf-8")]
        self.assertEqual(siblings, [], "another migration also revises tp_gds_dupes_02")

    def test_its_frozen_key_is_the_services_key(self):
        spec = importlib.util.spec_from_file_location("internal_dupes_01", MIGRATION)
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        stored = {"total_amt": Decimal("94621.00"), "last_name": None, "first_name": None, "invoice_type": None}
        for row in (SALE, REFUND, line(3), {**SALE, **stored}, {**SALE, "ticket_date": "2026-08-15"},
                    {**SALE, "doc_no": None, "invoice_type": "Credit Note"},
                    {**SALE, "pax_name": None, "last_name": "NAGPAL", "first_name": "RAVINDER"},
                    {"doc_date": "2026-08-10", "total_amt": 5.0}):
            with self.subTest(row=row):
                self.assertEqual(mig.ticket_key(row), td.ticket_key(row))

    def test_the_declared_date_format_is_kept(self):
        self.assertNotIn("drop_column", self.src)
        for model in (InternalTicketStatement, customer_tickets.TicketStatement):
            self.assertIn("date_formats", model.__table__.c)

    def test_the_models_have_the_columns(self):
        self.assertIn("dedup_key", InternalUploadedTicket.__table__.c)
        for col in ("total_entries", "duplicate_entries", "duplicate_of"):
            self.assertIn(col, InternalTicketStatement.__table__.c)


if __name__ == "__main__":
    unittest.main()
