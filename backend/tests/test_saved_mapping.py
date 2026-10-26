"""Remembered column mappings (services/saved_mapping.py) — no DB, no network.

The rules that matter are the ones a careless version gets wrong silently: re-adding a
column the user deliberately left unmapped, carrying a mapping onto a different report,
reusing another vendor's mapping on a layout that merely overlaps, and proposing a field
the type no longer has.

Run:  python -m unittest discover backend/tests
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import saved_mapping as sm  # noqa: E402

# TripJack's weekly export (trimmed): names the alias map does not know.
TRIPJACK = ["Posting Date", "MO Document No.", "Type", "Ticket No.", "PNR No.", "PAX Name",
            "Sector", "RBD", "Base Amount", "YQ Tax Amount", "Net To Customer", "UATP"]
SAVED_MAP = {"booking_date": "Posting Date", "ticket_status": "Type", "ticket_number": "Ticket No.",
             "airline_pnr": "PNR No.", "first_name": "PAX Name", "sector": "Sector",
             "booking_class": "RBD", "base_fare": "Base Amount", "yq": "YQ Tax Amount",
             "net_amount": "Net To Customer"}
FIELDS = set(SAVED_MAP) | {"invoice_number", "remarks", "flight_number"}
# What the alias map would say — including one the user rejected (UATP as Remarks).
BY_NAME = {"ticket_status": "Type", "sector": "Sector", "remarks": "UATP"}


def saved(columns=TRIPJACK, column_map=SAVED_MAP, same_vendor=True, **kw):
    return sm.Saved(signature=sm.signature(columns), columns=tuple(columns), column_map=dict(column_map),
                    same_vendor=same_vendor, vendor_name=kw.get("vendor_name", "TRIPJACK"),
                    source_file=kw.get("source_file", "1st Week Oct- TripJack.xlsx"),
                    saved_at=datetime(2026, 10, 25, 10, 0))


def propose(columns, saved_rows, has_vendor=True, by_name=BY_NAME, fields=FIELDS):
    return sm.propose(columns, fields, by_name, saved_rows, has_vendor=has_vendor)


class TestSignature(unittest.TestCase):
    def test_spelling_case_and_order_do_not_make_a_new_layout(self):
        self.assertEqual(sm.signature(["Ticket No.", "PNR No."]), sm.signature([" pnr no ", "TICKET NO"]))

    def test_a_different_column_is_a_different_layout(self):
        self.assertNotEqual(sm.signature(TRIPJACK), sm.signature(TRIPJACK + ["Management Fee"]))


class TestSameVendorSameLayout(unittest.TestCase):
    def test_the_saved_mapping_comes_back_as_saved(self):
        p = propose(TRIPJACK, [saved()])
        self.assertEqual(p.match, sm.VENDOR)
        self.assertEqual(p.mapping, SAVED_MAP)

    def test_a_column_left_unmapped_stays_unmapped(self):
        """UATP was in the file when the user mapped it and they left it out — the alias
        map's "Remarks" must not creep back in."""
        p = propose(TRIPJACK, [saved()])
        self.assertNotIn("remarks", p.mapping)

    def test_the_newest_of_two_saves_wins(self):
        newer = saved(column_map={**SAVED_MAP, "booking_date": "MO Document No."})
        self.assertEqual(propose(TRIPJACK, [newer, saved()]).mapping["booking_date"], "MO Document No.")

    def test_headers_spelt_differently_still_land_on_the_files_own_columns(self):
        respelt = [c.upper() + " " for c in TRIPJACK]
        p = propose(respelt, [saved()])
        self.assertEqual(p.match, sm.VENDOR)
        self.assertEqual(p.mapping["base_fare"], "BASE AMOUNT ")

    def test_a_field_the_type_no_longer_has_is_not_carried(self):
        old = saved(column_map={**SAVED_MAP, "issue_date": "Posting Date"})
        self.assertNotIn("issue_date", propose(TRIPJACK, [old]).mapping)


class TestSameVendorChangedLayout(unittest.TestCase):
    def test_kept_for_the_columns_still_there_and_new_ones_matched_by_name(self):
        changed = [c for c in TRIPJACK if c != "RBD"] + ["Flight No"]
        p = propose(changed, [saved()], by_name={**BY_NAME, "flight_number": "Flight No"})
        self.assertEqual(p.match, sm.VENDOR_CHANGED)
        self.assertNotIn("booking_class", p.mapping)                 # RBD is gone
        self.assertEqual(p.mapping["flight_number"], "Flight No")    # new, so name-matched
        self.assertNotIn("remarks", p.mapping)                       # UATP was seen before
        self.assertEqual(p.new_columns, ["Flight No"])
        self.assertEqual(p.gone_columns, ["RBD"])

    def test_a_different_report_from_the_vendor_is_not_forced_into_the_mapping(self):
        ledger = ["Booking Date", "YT No", "Type", "Product Type", "Amount", "Balance"]
        p = propose(ledger, [saved()], by_name={"ticket_status": "Type"})
        self.assertIsNone(p.match)
        self.assertEqual(p.mapping, {"ticket_status": "Type"})       # by name, as before


class TestOtherVendors(unittest.TestCase):
    def test_another_vendors_mapping_is_reused_on_the_exact_layout(self):
        """GLOBE and Yatra print the same TICKET STATEMENT export."""
        p = propose(TRIPJACK, [saved(same_vendor=False, vendor_name="GLOBE AIR TRAVELS")])
        self.assertEqual(p.match, sm.LAYOUT)
        self.assertEqual(p.mapping, SAVED_MAP)
        self.assertEqual(p.info()["vendor_name"], "GLOBE AIR TRAVELS")

    def test_but_never_on_a_layout_that_only_overlaps(self):
        changed = [c for c in TRIPJACK if c != "RBD"]
        self.assertIsNone(propose(changed, [saved(same_vendor=False)]).match)

    def test_the_vendors_own_mapping_beats_another_vendors_exact_layout(self):
        theirs = saved(same_vendor=False, column_map={**SAVED_MAP, "booking_date": "MO Document No."})
        p = propose(TRIPJACK, [theirs, saved()])
        self.assertEqual((p.match, p.mapping["booking_date"]), (sm.VENDOR, "Posting Date"))


class TestNoVendor(unittest.TestCase):
    def test_a_type_without_a_vendor_reuses_an_exact_layout(self):
        p = propose(TRIPJACK, [saved(same_vendor=False, vendor_name=None)], has_vendor=False)
        self.assertEqual(p.mapping, SAVED_MAP)

    def test_and_only_an_exact_one(self):
        changed = [c for c in TRIPJACK if c != "RBD"]
        self.assertIsNone(propose(changed, [saved(same_vendor=False)], has_vendor=False).match)


class TestNothingSaved(unittest.TestCase):
    def test_falls_back_to_the_name_match(self):
        p = propose(TRIPJACK, [])
        self.assertEqual((p.match, p.mapping, p.info()), (None, BY_NAME, None))


if __name__ == "__main__":
    unittest.main()
