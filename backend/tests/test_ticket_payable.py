"""Tickets: Payable To — who a ticket was bought from — no DB.

Create Ticket asks, beside Sold To, who the ticket is payable to: an Airline (any carrier in
the platform's airline master) or a B2B consolidator (one of the user's Agency Master rows). Pinned here: the server authorises the pick and stores the
master's name, a row with no pick stores nothing, and the migration adds the columns to
both ticket tables.

Run:  python -m unittest discover backend/tests
"""
import asyncio
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: E402,F401
from fastapi import HTTPException  # noqa: E402

from app.api.v1 import tickets  # noqa: E402
from app.models.internal_ticket import InternalUploadedTicket  # noqa: E402
from app.models.uploaded_ticket import UploadedTicket  # noqa: E402
from app.schemas.uploaded_ticket import TicketRow  # noqa: E402

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "ticket_payable_01_payable_to.py"
COLUMNS = ("payable_type", "payable_airline_id", "payable_agency_id", "payable_to")


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeDB:
    """Hands out the given results in order and records each statement it was given."""

    def __init__(self, *results):
        self.results = [_Rows(r) for r in results]
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return self.results.pop(0) if self.results else _Rows([])


def resolve(rows, db):
    return asyncio.run(tickets._resolve_payables([TicketRow(**r) for r in rows], db, user_id=14))


class ResolveTests(unittest.TestCase):
    def test_a_row_with_no_pick_stores_nothing_and_reads_nothing(self):
        db = FakeDB()
        self.assertEqual(resolve([{}, {"payable_airline_id": 9}], db), [{}, {}])
        self.assertEqual(db.statements, [])

    def test_an_airline_and_an_agency_are_stored_with_the_masters_names(self):
        db = FakeDB([(57, "TURKISH AIRLINES")], [(28, "Globe Air Travels")])
        out = resolve([{"payable_type": "airline", "payable_airline_id": 57, "payable_to": "typed"},
                       {"payable_type": "B2B", "payable_agency_id": 28}], db)
        self.assertEqual(out, [
            {"payable_type": "airline", "payable_airline_id": 57, "payable_agency_id": None,
             "payable_to": "TURKISH AIRLINES"},
            {"payable_type": "b2b", "payable_airline_id": None, "payable_agency_id": 28,
             "payable_to": "Globe Air Travels"},
        ])
        # The airline from the platform's master — not the user's Airline Master ids;
        # the agency from the user's own Agency Master.
        airline_sql, agency_sql = (str(s) for s in db.statements)
        self.assertIn("FROM airlines", airline_sql)
        self.assertNotIn("tenant_airlines", airline_sql)
        self.assertIn("agencies.user_id", agency_sql)

    def test_a_party_that_is_not_the_callers_is_refused(self):
        for row, results, status, says in (
            ({"payable_type": "airline", "payable_airline_id": 57}, ([],), 400, "not in the airline master"),
            ({"payable_type": "b2b", "payable_agency_id": 28}, ([],), 400, "not found in your agencies"),
            ({"payable_type": "airline"}, (), 422, "pick the airline"),
            ({"payable_type": "b2b"}, (), 422, "pick the agency"),
            ({"payable_type": "vendor", "payable_agency_id": 28}, ([],), 422, "Airline or B2B"),
        ):
            with self.subTest(row=row):
                with self.assertRaises(HTTPException) as cm:
                    resolve([row], FakeDB(*results))
                self.assertEqual(cm.exception.status_code, status)
                self.assertIn(says, cm.exception.detail)


class ColumnTests(unittest.TestCase):
    def test_both_ticket_tables_have_the_columns(self):
        for model in (UploadedTicket, InternalUploadedTicket):
            for col in COLUMNS:
                with self.subTest(table=model.__table__.name, col=col):
                    self.assertIn(col, model.__table__.c)
        # Accepted by the row the builder makes, so `**payable` lands as columns.
        t = UploadedTicket(payable_type="b2b", payable_agency_id=28, payable_to="Globe Air Travels")
        self.assertEqual((t.payable_type, t.payable_agency_id), ("b2b", 28))

    def test_the_migration_chains_and_adds_them_to_both_tables(self):
        src = MIGRATION.read_text(encoding="utf-8")
        self.assertIn("down_revision: Union[str, None] = 'internal_reupload_01'", src)
        self.assertIn("('uploaded_tickets', 'internal_uploaded_tickets')", src)
        for col in COLUMNS:
            self.assertRegex(src, rf"add_column\(table, sa\.Column\('{re.escape(col)}'")
            self.assertIn(f"drop_column(table, '{col}')", src)


if __name__ == "__main__":
    unittest.main()
