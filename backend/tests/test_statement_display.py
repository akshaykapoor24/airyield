"""statement_display — the column list and row flattening shared by /statements and the report.

These two functions used to live inside ``api/v1/statements.py``; the Workspace report download
now renders its TGQ HMPR / NDC / LCC ledger / Third Party detail sheets from them too. The
cases below pin their output so the move — and any later edit — cannot change what either
consumer shows:

* ``display_columns`` per slug is fully characterised by (a) the spec's own columns, in spec
  order, (b) the derived columns and their exact positions, and (c) the money kinds. (b) is
  snapshotted here; (a) and (c) are asserted against the spec so a legitimate spec edit does
  not need a test edit, while a change to the derivation rules does.
* ``flatten_record`` on a plain ``SimpleNamespace`` row (the report passes non-ORM rows).
* The router still exposes both under the names it and ``test_tp_api_spec`` use.

No DB, no network.

Run:  ..\\venv\\Scripts\\python.exe -m unittest test_statement_display -v   (from backend/tests)
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.statement_row import STATEMENT_MODELS  # noqa: E402
from app.services import statement_spec as spec  # noqa: E402
from app.services.statement_display import display_columns, flatten_record  # noqa: E402

# slug → [(index in display_columns, header, field)] for every column the spec does not declare.
# Captured from api/v1/statements._display_columns before it moved (identical output verified).
DERIVED_COLUMNS = {
    "tgq-hmpr": [(0, "Leg", "__leg__"), (6, "Airline_Code", "airline_code"), (65, "Taxes", "__taxes__")],
    "ndc": [],
    "lcc-di": [(7, "Format", "__format__")],
    "lcc-divided-pnr": [(10, "Format", "__format__")],
    "lcc-flown-report": [(31, "Format", "__format__")],
    "lcc-cta-bta": [(28, "Format", "__format__")],
    "tp-gds": [(56, "Format", "__format__")],
    "tp-lcc": [(44, "Format", "__format__")],
    "tp-api": [(93, "Format", "__format__")],
}

# Record keys that describe the row rather than fill a column.
_ROW_META = {"__split__", "__legs__"}


class TestDisplayColumns(unittest.TestCase):

    def test_every_statement_type_has_a_snapshot(self):
        self.assertEqual(set(DERIVED_COLUMNS), set(STATEMENT_MODELS))
        self.assertEqual(set(DERIVED_COLUMNS), set(spec.STATEMENT_SPECS))

    def test_snapshot(self):
        for slug, derived in DERIVED_COLUMNS.items():
            with self.subTest(slug=slug):
                cols = display_columns(slug)
                spec_cols = spec.columns(slug)
                spec_fields = {c["field"] for c in spec_cols}

                got_derived = [(i, c["header"], c["field"]) for i, c in enumerate(cols)
                               if c["field"] not in spec_fields]
                self.assertEqual(got_derived, derived)
                self.assertEqual(len(cols), len(spec_cols) + len(derived))

                # Everything else is the spec's own columns, in spec order, money-kinded.
                money = spec.money_fields(slug)
                expected_rest = [{**c, "kind": "money"} if c["field"] in money else c
                                 for c in spec_cols]
                self.assertEqual([c for c in cols if c["field"] in spec_fields], expected_rest)
                for c in cols:
                    if c["field"] not in spec_fields:
                        self.assertEqual(set(c), {"header", "field"})

    def test_airline_code_sits_immediately_before_ticket_no(self):
        headers = [c["header"] for c in display_columns("tgq-hmpr")]
        self.assertEqual(headers[headers.index("Airline_Code") + 1], "Ticket_No")

    def test_returns_a_fresh_list(self):
        first = display_columns("ndc")
        first.append({"header": "X", "field": "x"})
        self.assertNotIn({"header": "X", "field": "x"}, display_columns("ndc"))


class TestFlattenRecord(unittest.TestCase):

    def test_tgq_hmpr_split_leg(self):
        data = {"ticket_no": "5805708071", "airline_code": "098", "pax_name": "DOE/JOHN MR"}
        row = SimpleNamespace(
            id=41, data=data, sector_index=2, sector_count=3, split_status="split",
            taxes=[{"type": "YQ", "amount": "1200"}, {"type": "K3", "amount": None},
                   {"type": "", "amount": "5"}, {"type": "IN", "amount": "88.5"}],
        )
        self.assertEqual(flatten_record("tgq-hmpr", row), {
            "ticket_no": "5805708071", "airline_code": "098", "pax_name": "DOE/JOHN MR",
            "id": 41, "__leg__": "2/3", "__split__": "split", "__legs__": 3,
            "__taxes__": "YQ 1200 · K3 · IN 88.5",
        })
        self.assertNotIn("id", data)   # the stored JSONB dict is copied, never mutated

    def test_tgq_hmpr_row_never_split(self):
        row = SimpleNamespace(id=1, data=None, taxes=None, sector_index=None, sector_count=None,
                              split_status=None)
        self.assertEqual(flatten_record("tgq-hmpr", row), {
            "id": 1, "__leg__": "", "__split__": None, "__legs__": None, "__taxes__": "",
        })

    def test_ndc_is_data_plus_id(self):
        row = SimpleNamespace(id=7, data={"document_no": "0985805708071", "total_fare": "100"},
                              taxes=[{"type": "YQ", "amount": "1"}], sector_index=1,
                              sector_count=1, split_status="single", source_format="x")
        self.assertEqual(flatten_record("ndc", row),
                         {"document_no": "0985805708071", "total_fare": "100", "id": 7})

    def test_tp_gds_gets_its_format(self):
        row = SimpleNamespace(id=3, data={"ticket_number": "1234567890"}, taxes=None,
                              source_format="tp-gds-v2")
        self.assertEqual(flatten_record("tp-gds", row),
                         {"ticket_number": "1234567890", "id": 3, "__format__": "tp-gds-v2"})
        blank = SimpleNamespace(id=4, data={}, taxes=None, source_format=None)
        self.assertEqual(flatten_record("tp-gds", blank), {"id": 4, "__format__": ""})

    def test_spec_driven_type_without_the_column_reads_blank_format(self):
        """tp-api has no `parser` but declares Format; a row lacking the attribute is ""."""
        row = SimpleNamespace(id=9, data={"booking_id": "B1"}, taxes=None)
        self.assertEqual(flatten_record("tp-api", row),
                         {"booking_id": "B1", "id": 9, "__format__": ""})

    def test_every_declared_derived_column_is_filled_and_nothing_else(self):
        row = SimpleNamespace(id=1, data={}, taxes=[], segments=[], ssr=[], sector_index=1,
                              sector_count=1, split_status="single", source_format="f")
        for slug in STATEMENT_MODELS:
            with self.subTest(slug=slug):
                declared = {c["field"] for c in display_columns(slug) if c["field"].startswith("__")}
                filled = {k for k in flatten_record(slug, row) if k.startswith("__")} - _ROW_META
                self.assertEqual(declared, filled)


class TestRouterUsesTheSharedFunctions(unittest.TestCase):

    def test_router_names(self):
        from app.api.v1 import statements as router
        self.assertIs(router._display_columns, display_columns)
        self.assertIs(router.flatten_record, flatten_record)


if __name__ == "__main__":
    unittest.main()
