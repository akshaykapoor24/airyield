"""The Airline Master grid's grouping.

The screen is a live view of the platform airline master with the tenant's own ids
hung under each airline, so this checks the three things that view has to get right:
an airline with no ids still appears (that is the blank-ID row the user fills in), an
airline with several ids keeps all of them, and a renamed master is flagged rather
than silently papered over.

No DB, no network — build_catalog is pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.tenant_airline_catalog import build_catalog  # noqa: E402


class FakeAirline:
    """The platform master row."""

    def __init__(self, id, name, iata_code, iata_numeric_code=None,
                 icao_code=None, contract_year=None, is_active=True):
        self.id = id
        self.name = name
        self.iata_code = iata_code
        self.iata_numeric_code = iata_numeric_code
        self.icao_code = icao_code
        self.contract_year = contract_year
        self.is_active = is_active


class FakeTenantAirline:
    """One id the tenant holds. `airline_name` is the snapshot taken at add time."""

    def __init__(self, id, airline_id, ref_id, airline_name=None, is_active=True):
        self.id = id
        self.airline_id = airline_id
        self.ref_id = ref_id
        self.airline_name = airline_name
        self.is_active = is_active


INDIGO = FakeAirline(1, "INDIGO", "6E", iata_numeric_code="312")
AIR_INDIA = FakeAirline(2, "AIR INDIA", "AI", iata_numeric_code="098", contract_year="FY")
AKASA = FakeAirline(3, "AKASA AIR", "QP")


class BuildCatalogTests(unittest.TestCase):

    def test_airline_with_no_ids_still_appears(self):
        """The whole point of the 'All airlines' tab: an airline the tenant has not
        claimed yet must be listed, with an empty id column to fill in."""
        [entry] = build_catalog([AKASA], [])
        self.assertEqual(entry["airline_id"], 3)
        self.assertEqual(entry["name"], "AKASA AIR")
        self.assertEqual(entry["ids"], [])
        self.assertEqual(entry["id_count"], 0)
        self.assertEqual(entry["active_id_count"], 0)

    def test_many_ids_group_under_one_airline(self):
        """Five Indigo logins is the ordinary case, not an edge case."""
        rows = [
            FakeTenantAirline(10 + n, 1, ref, airline_name="INDIGO")
            for n, ref in enumerate(["6E-MAA-44510", "6E-DEL-88213", "6E-BOM-11902"])
        ]
        [entry] = build_catalog([INDIGO], rows)
        self.assertEqual(entry["id_count"], 3)
        # Sorted the way the user reads them, not by insertion order.
        self.assertEqual(
            [i["ref_id"] for i in entry["ids"]],
            ["6E-BOM-11902", "6E-DEL-88213", "6E-MAA-44510"],
        )

    def test_ids_land_on_their_own_airline(self):
        rows = [
            FakeTenantAirline(1, 1, "6E-DEL-88213", airline_name="INDIGO"),
            FakeTenantAirline(2, 2, "ktgh65", airline_name="AIR INDIA"),
            FakeTenantAirline(3, 1, "6E-BOM-11902", airline_name="INDIGO"),
        ]
        entries = {e["name"]: e for e in build_catalog([INDIGO, AIR_INDIA, AKASA], rows)}
        self.assertEqual(entries["INDIGO"]["id_count"], 2)
        self.assertEqual(entries["AIR INDIA"]["id_count"], 1)
        self.assertEqual(entries["AKASA AIR"]["id_count"], 0)

    def test_airline_order_is_preserved(self):
        """The query orders by name; grouping must not reshuffle the page."""
        names = [e["name"] for e in build_catalog([AIR_INDIA, AKASA, INDIGO], [])]
        self.assertEqual(names, ["AIR INDIA", "AKASA AIR", "INDIGO"])

    def test_active_count_excludes_inactive_ids(self):
        rows = [
            FakeTenantAirline(1, 1, "a-live", airline_name="INDIGO", is_active=True),
            FakeTenantAirline(2, 1, "b-dead", airline_name="INDIGO", is_active=False),
        ]
        [entry] = build_catalog([INDIGO], rows)
        self.assertEqual(entry["id_count"], 2)
        self.assertEqual(entry["active_id_count"], 1)

    def test_usage_counts_attach_to_the_right_id(self):
        """in_use_count is what lets the UI warn before DELETE returns a 409."""
        rows = [
            FakeTenantAirline(7, 1, "used", airline_name="INDIGO"),
            FakeTenantAirline(8, 1, "unused", airline_name="INDIGO"),
        ]
        [entry] = build_catalog([INDIGO], rows, {7: 4})
        by_ref = {i["ref_id"]: i for i in entry["ids"]}
        self.assertEqual(by_ref["used"]["in_use_count"], 4)
        self.assertEqual(by_ref["unused"]["in_use_count"], 0)

    def test_drift_flagged_when_master_renamed_since_the_id_was_added(self):
        """The snapshot is what the statements were stamped with and is never
        rewritten, so a rename has to be surfaced, not hidden."""
        rows = [FakeTenantAirline(1, 1, "6E-DEL", airline_name="INDIGO AIRLINES")]
        [entry] = build_catalog([INDIGO], rows)
        self.assertTrue(entry["ids"][0]["snapshot_name_drifted"])

    def test_no_drift_when_snapshot_matches_or_is_missing(self):
        rows = [
            FakeTenantAirline(1, 1, "same", airline_name="INDIGO"),
            FakeTenantAirline(2, 1, "blank", airline_name=None),
        ]
        [entry] = build_catalog([INDIGO], rows)
        self.assertFalse(any(i["snapshot_name_drifted"] for i in entry["ids"]))

    def test_numeric_code_falls_back_to_icao(self):
        """Older master rows only ever got icao_code — /airlines/export makes the
        same fallback, and the two screens must not disagree."""
        legacy = FakeAirline(9, "OLD AIR", "OA", iata_numeric_code=None, icao_code="777")
        [entry] = build_catalog([legacy], [])
        self.assertEqual(entry["iata_numeric_code"], "777")

    def test_null_is_active_is_not_treated_as_inactive(self):
        """`Airline.is_active` has no server default, so a row written outside the
        ORM can be NULL. NULL means unknown, not inactive."""
        [entry] = build_catalog([FakeAirline(9, "OLD AIR", "OA", is_active=None)], [])
        self.assertTrue(entry["master_is_active"])
        [entry] = build_catalog([FakeAirline(9, "OLD AIR", "OA", is_active=False)], [])
        self.assertFalse(entry["master_is_active"])


if __name__ == "__main__":
    unittest.main()
