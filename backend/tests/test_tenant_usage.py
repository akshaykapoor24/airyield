"""The usage registry must account for every tenant-scoped table.

The point of this file is not to re-assert today's list — it is to fail the day
someone adds a tenant-scoped table and forgets that the platform-admin console
exists. A silently missed table makes a workspace look less used than it is,
which is precisely the judgement that console is there to support.

No DB, no network. Reflects the SQLAlchemy metadata only.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import importlib
import os
import pkgutil
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402
from app.database import Base  # noqa: E402

# Import every module under app/models/ rather than trusting app.models.__init__,
# which today omits three of them (entities, iata_commissions, login_ids) and so
# registers 64 of 67 tables. Relying on it would let exactly the kind of table
# this file exists to catch stay invisible to the check.
for _mod in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_mod.name}")
from app.services.tenant_usage import (  # noqa: E402
    EXCLUDED_TABLES,
    SOURCE_LABELS,
    USAGE_SOURCES,
    to_breakdown,
)

# Global master data — shared across every workspace, so not workspace usage.
GLOBAL_TABLES = frozenset({
    "airlines", "airports", "routes", "airline_class_masters", "suppliers",
})

# Dead pre-tenant tables. Each carries a "legacy/unused" comment in its model and
# has no tenant_id; uploaded_tickets / income_summaries superseded them.
LEGACY_TABLES = frozenset({"tickets", "income_records", "documents"})

COUNTED_TABLES = frozenset(s.model.__tablename__ for s in USAGE_SOURCES)


class TestRegistryCoverage(unittest.TestCase):
    def test_every_table_is_classified(self):
        """No table may be neither counted nor explicitly excluded.

        If this fails, decide which the new table is and add it to USAGE_SOURCES
        or to EXCLUDED_TABLES — do not delete the assertion.
        """
        known = COUNTED_TABLES | EXCLUDED_TABLES | GLOBAL_TABLES | LEGACY_TABLES
        unclassified = sorted(set(Base.metadata.tables) - known)
        self.assertEqual(
            unclassified, [],
            "These tables are neither counted nor excluded by "
            "app/services/tenant_usage.py:\n  " + "\n  ".join(unclassified),
        )

    def test_no_table_is_both_counted_and_excluded(self):
        self.assertEqual(sorted(COUNTED_TABLES & EXCLUDED_TABLES), [])

    def test_every_counted_table_is_tenant_scoped(self):
        """A table with no tenant_id cannot be attributed to a workspace, so
        counting it would add the same number to every row."""
        for src in USAGE_SOURCES:
            with self.subTest(table=src.model.__tablename__):
                self.assertIn("tenant_id", Base.metadata.tables[src.model.__tablename__].c)

    def test_excluded_names_are_real_tables(self):
        """Guards against a typo quietly disabling the coverage check — a
        misspelled exclusion would let its real table go unnoticed."""
        stale = sorted(EXCLUDED_TABLES - set(Base.metadata.tables))
        self.assertEqual(stale, [], f"EXCLUDED_TABLES names non-existent tables: {stale}")


class TestRegistryShape(unittest.TestCase):
    def test_keys_and_labels_are_unique(self):
        keys = [s.key for s in USAGE_SOURCES]
        labels = [s.label for s in USAGE_SOURCES]
        self.assertEqual(len(keys), len(set(keys)), "duplicate source key")
        self.assertEqual(len(labels), len(set(labels)), "duplicate label")

    def test_the_two_original_columns_are_still_counted(self):
        """Records replaced Deals and Tickets; it must not have lost them."""
        self.assertEqual(SOURCE_LABELS["deals"], "Deals")
        self.assertEqual(SOURCE_LABELS["tickets"], "Tickets")
        by_table = {s.model.__tablename__ for s in USAGE_SOURCES}
        self.assertIn("deals", by_table)
        self.assertIn("uploaded_tickets", by_table)

    def test_every_feature_the_console_promises_is_present(self):
        """The tables the platform admin expects to see behind the total."""
        by_table = {s.model.__tablename__ for s in USAGE_SOURCES}
        for table in (
            "bsp_statement_rows", "bsp_summary_rows",
            "airline_adm", "airline_acm", "airline_ra",
            "tgq_hmpr", "ndc", "lcc_detailed",
            "lcc_di", "lcc_divided_pnr", "lcc_flown_report", "lcc_cta_bta",
            "third_party_gds", "third_party_lcc",
        ):
            with self.subTest(table=table):
                self.assertIn(table, by_table)

    def test_third_party_labels_are_disambiguated(self):
        """STATEMENT_SPECS labels them bare "GDS" and "LCC", which say nothing
        outside their nav category."""
        self.assertEqual(SOURCE_LABELS["stmt_tp-gds"], "Third Party GDS")
        self.assertEqual(SOURCE_LABELS["stmt_tp-lcc"], "Third Party LCC")

    def test_no_upload_parent_is_counted_alongside_its_rows(self):
        """Counting a file AND its rows reports 1001 for a 1000-row upload."""
        by_table = {s.model.__tablename__ for s in USAGE_SOURCES}
        for parent in ("bsp_statements", "bsp_summary_statements",
                       "deal_statements", "deal_batches", "lcc_detailed_batch"):
            with self.subTest(parent=parent):
                self.assertNotIn(parent, by_table)


class TestBreakdown(unittest.TestCase):
    def test_maps_keys_to_labels_and_drops_zeros(self):
        out = to_breakdown({"deals": 316, "tickets": 12, "bsp": 0, "billings": 4})
        self.assertEqual(out, {"Deals": 316, "Tickets": 12, "Billings": 4})

    def test_order_follows_the_registry_not_the_input(self):
        out = to_breakdown({"billings": 1, "deals": 2, "tickets": 3})
        self.assertEqual(list(out), ["Deals", "Tickets", "Billings"])

    def test_empty(self):
        self.assertEqual(to_breakdown({}), {})

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(to_breakdown({"not_a_source": 9}), {})

    def test_total_equals_the_sum_of_the_breakdown(self):
        counts = {"deals": 316, "tickets": 12, "bsp": 842, "stmt_ndc": 0}
        self.assertEqual(sum(to_breakdown(counts).values()), sum(counts.values()))


if __name__ == "__main__":
    unittest.main()
