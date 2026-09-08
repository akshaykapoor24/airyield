"""Unit tests for third-party commission semantics — no DB, no network.

Two things here decide whether a number on screen is right or merely plausible:

  * the Net Amount self-check, which is what stops a variance being computed against a
    vendor's arithmetic that does not close; and
  * the gross-vs-gross variance, which is what stops a phantom 2% shortfall appearing on
    every commission-bearing row.

Both are pinned against the real export's own figures.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.commission.calc_row import (  # noqa: E402
    KIND_ISSUE, KIND_REFUND, KIND_SKIP, CalcRow,
)
from app.services.commission.runner import _variance  # noqa: E402
from app.services.commission.third_party import (  # noqa: E402
    build_calc_row, build_declared, classify, net_from_components,
)
from app.services.deal_matching import SKIP_CLASS  # noqa: E402


# The two verified rows, as `data` would look after ingest normalisation.
TURKISH = {
    "week": "08-15TH AUG 26", "booking_date": "2026-08-08", "issue_date": "2026-08-08",
    "issue_date_source": "booked_date", "travel_date": "2026-08-08",
    "airline_name": "TURKISH AIRLINES", "airline_master_name": "TURKISH AIRLINES",
    "airline_code": "TK", "airline_id": "1", "segment_type": "INTERNATIONAL",
    "ticket_prefix": "235", "ticket_number": "4848358656", "ticket_status": "CONFIRMED",
    "passenger_name": "MR AJAY", "sector": "DEL/IST/MAD/MLA/IST/DEL",
    "base_fare": "66250", "yq": "0", "other_taxes": "23069",
    "commission_amount": "0", "tds": "0", "service_fee": "100", "gst_on_sf": "18",
    "net_amount": "89437",
}
ETIHAD = {
    "booking_date": "2026-08-13", "issue_date": "2026-08-13",
    "issue_date_source": "booked_date", "travel_date": "2026-08-24",
    "airline_master_name": "ETIHAD AIRWAYS", "airline_code": "EY", "airline_id": "4",
    "segment_type": "INTERNATIONAL", "ticket_prefix": "607",
    "ticket_number": "5808675862", "ticket_status": "CONFIRMED",
    "passenger_name": "MR ASHOK KUMAR", "sector": "JAI/JMK",
    "base_fare": "31670", "yq": "0", "other_taxes": "21544",
    "commission_amount": "285.72", "tds": "5.7144", "service_charge": "0",
    "net_amount": "52933.9944",
}


class FakeRow:
    def __init__(self, data, row_id=1):
        self.id = row_id
        self.data = data


class TestNetIdentity(unittest.TestCase):
    def test_turkish_closes(self):
        self.assertAlmostEqual(net_from_components(TURKISH), 89437.0, places=4)

    def test_etihad_closes(self):
        self.assertAlmostEqual(net_from_components(ETIHAD), 52933.9944, places=4)

    def test_commission_is_subtracted_and_tds_added_back(self):
        """The direction of both is what the Etihad row proves. Flip either and the
        identity misses by twice its value."""
        d = dict(ETIHAD)
        d["commission_amount"] = "0"
        d["tds"] = "0"
        self.assertAlmostEqual(net_from_components(d), 53214.0, places=4)


class TestDeclaredSelfCheck(unittest.TestCase):
    def test_a_closing_row_is_verified(self):
        self.assertIs(build_declared(TURKISH).net_ok, True)
        self.assertIs(build_declared(ETIHAD).net_ok, True)

    def test_declared_figures_are_carried_gross(self):
        d = build_declared(ETIHAD)
        self.assertAlmostEqual(d.commission, 285.72, places=4)
        self.assertAlmostEqual(d.tds, 5.7144, places=4)
        self.assertAlmostEqual(d.tds, d.commission * 0.02, places=4)

    def test_a_row_that_does_not_add_up_is_marked_false(self):
        d = dict(TURKISH, net_amount="99999")
        self.assertIs(build_declared(d).net_ok, False)

    def test_an_unverified_sign_makes_it_none_not_false(self):
        """agent_penalty / reschedule / cancellation columns are blank in every real row we
        have, so their sign in the identity is unproven. Calling the vendor wrong on that
        basis would raise false alarms across a whole file."""
        d = dict(TURKISH, net_amount="99999", agent_penalty="500")
        self.assertIsNone(build_declared(d).net_ok)

    def test_no_net_column_is_none(self):
        d = {k: v for k, v in TURKISH.items() if k != "net_amount"}
        self.assertIsNone(build_declared(d).net_ok)

    def test_rounding_slack_is_paise_not_rupees(self):
        self.assertIs(build_declared(dict(TURKISH, net_amount="89437.04")).net_ok, True)
        self.assertIs(build_declared(dict(TURKISH, net_amount="89438")).net_ok, False)


class TestStatusPolicy(unittest.TestCase):
    def test_confirmed_is_a_sale(self):
        self.assertEqual(classify({"ticket_status": "CONFIRMED"})[0], KIND_ISSUE)

    def test_refunded_reverses(self):
        for s in ("REFUNDED", "refunded", "RFND", "Refund"):
            self.assertEqual(classify({"ticket_status": s})[0], KIND_REFUND, s)

    def test_cancelled_and_void_earn_nothing(self):
        for s in ("CANCELLED", "VOID", "PENDING", "FAILED"):
            kind, reason = classify({"ticket_status": s})
            self.assertEqual(kind, KIND_SKIP, s)
            self.assertTrue(reason)

    def test_an_unknown_status_is_treated_as_a_sale_and_flagged(self):
        """A whitelist-only issue rule would silently zero a whole file the first time a
        consolidator wrote something we had not seen."""
        kind, reason = classify({"ticket_status": "TKTD-OK"})
        self.assertEqual(kind, KIND_ISSUE)
        self.assertIn("Unrecognised status", reason)

    def test_a_blank_status_is_a_sale_without_a_warning(self):
        self.assertEqual(classify({}), (KIND_ISSUE, None))


class TestCalcRowConstruction(unittest.TestCase):
    def test_the_master_spelling_is_what_the_matcher_sees(self):
        """`deals.airline_name` holds the master's spelling and the compare is an
        equality, so the file's own string must not be used."""
        ctx = build_calc_row(FakeRow(dict(TURKISH, airline_name="TURKISH AIRLINES CO",
                                          airline_master_name="Turkish Airlines")), None, None)
        self.assertEqual(ctx.airline_name, "Turkish Airlines")

    def test_third_party_rows_search_b2b_deals(self):
        ctx = build_calc_row(FakeRow(TURKISH), "3A Travels", 40)
        self.assertEqual(ctx.statement_type, "B2B")
        self.assertEqual(ctx.supplier_agency, "3A Travels")
        self.assertEqual(ctx.supplier_agency_id, 40)

    def test_a_blank_class_skips_the_class_filter(self):
        ctx = build_calc_row(FakeRow(TURKISH), None, None)
        self.assertIn(SKIP_CLASS, ctx.skip_criteria)
        self.assertIn("class", ctx.skip_rule_fields)
        self.assertIn("class", ctx.skipped_labels)

    def test_a_present_class_does_not_skip(self):
        """Per row, never per statement: skipping class on a row whose class we know would
        let an Economy-only deal match a Business ticket."""
        ctx = build_calc_row(FakeRow(dict(TURKISH, booking_class="J")), None, None)
        self.assertNotIn(SKIP_CLASS, ctx.skip_criteria)
        self.assertEqual(ctx.booking_class, "J")

    def test_travel_date_and_sector_are_not_skipped(self):
        """The export prints both, so travel windows and route rules are genuinely
        evaluable — better evidence than an unenriched BSP row."""
        ctx = build_calc_row(FakeRow(TURKISH), None, None)
        self.assertIsNotNone(ctx.travel_date)
        self.assertIsNotNone(ctx.sector)
        self.assertNotIn("travel_date", ctx.skipped_labels)
        self.assertNotIn("sector", ctx.skipped_labels)

    def test_yr_is_none_not_a_share_of_other_taxes(self):
        ctx = build_calc_row(FakeRow(TURKISH), None, None)
        self.assertIsNone(ctx.yr)
        self.assertEqual(ctx.fare_amount, 66250.0)
        self.assertEqual(ctx.yq, 0.0)

    def test_ssr_is_stored_but_never_fed_to_the_ancillary_engine(self):
        """A deal pays Ancillary per sub-type; one combined figure cannot be split."""
        ctx = build_calc_row(FakeRow(dict(TURKISH, ssr_amount="285.72")), None, None)
        self.assertEqual(ctx.ancillary_amount, 285.72)
        self.assertIsNone(ctx.seat_selection)
        self.assertIsNone(ctx.excess_baggage)
        self.assertIsNone(ctx.meals)

    def test_the_issue_date_assumption_is_stated_on_the_row(self):
        ctx = build_calc_row(FakeRow(TURKISH), None, None)
        self.assertTrue(any("Booked Date" in n for n in ctx.notes))

    def test_an_airline_conflict_is_carried_through(self):
        ctx = build_calc_row(FakeRow(dict(TURKISH, airline_conflict="prefix says X, name says Y")),
                             None, None)
        self.assertIn("prefix says X, name says Y", ctx.notes)

    def test_dates_come_through_as_dates(self):
        ctx = build_calc_row(FakeRow(ETIHAD), None, None)
        self.assertEqual(ctx.issue_date.isoformat(), "2026-08-13")
        self.assertEqual(ctx.travel_date.isoformat(), "2026-08-24")


class TestVariance(unittest.TestCase):
    """Positive = under-recovery: the consolidator owes you."""

    def test_a_deal_paying_more_than_the_vendor_did_is_positive(self):
        ctx = build_calc_row(FakeRow(TURKISH), None, None)
        v = _variance(ctx, computed_incentive=1987.50, computed_iata=1325.00)
        self.assertAlmostEqual(v["variance_commission"], 1325.00, places=2)
        self.assertAlmostEqual(v["variance_incentive"], 1987.50, places=2)
        self.assertAlmostEqual(v["variance_total"], 3312.50, places=2)

    def test_the_comparison_is_gross_to_gross(self):
        """Netting the declared TDS off first would print +353.39 instead of +347.68 — a
        phantom 2% shortfall on every commission-bearing row."""
        ctx = build_calc_row(FakeRow(ETIHAD), None, None)
        v = _variance(ctx, computed_incentive=0.0, computed_iata=633.40)
        self.assertAlmostEqual(v["variance_commission"], 347.68, places=2)
        self.assertNotAlmostEqual(v["variance_commission"], 353.39, places=2)

    def test_over_payment_is_negative(self):
        ctx = build_calc_row(FakeRow(ETIHAD), None, None)
        v = _variance(ctx, computed_incentive=0.0, computed_iata=100.0)
        self.assertLess(v["variance_total"], 0)

    def test_a_row_whose_arithmetic_does_not_close_gets_no_variance(self):
        """A variance against figures that do not add up is meaningless — better to show
        nothing and say why."""
        ctx = build_calc_row(FakeRow(dict(TURKISH, net_amount="99999")), None, None)
        self.assertIs(ctx.declared.net_ok, False)
        self.assertEqual(_variance(ctx, 1000.0, 500.0), {})

    def test_an_unverifiable_row_still_gets_a_variance(self):
        """net_ok None means 'we could not judge the vendor's arithmetic', not 'it is
        wrong' — the figure is still worth showing, flagged."""
        ctx = build_calc_row(FakeRow(dict(TURKISH, net_amount="99999", agent_penalty="500")),
                             None, None)
        self.assertIsNone(ctx.declared.net_ok)
        self.assertNotEqual(_variance(ctx, 1000.0, 500.0), {})

    def test_a_source_with_no_declared_figures_gets_none(self):
        """BSP and LCC Detailed print nothing to compare against."""
        ctx = CalcRow(source_row_id=1)
        self.assertEqual(_variance(ctx, 1000.0, 500.0), {})


if __name__ == "__main__":
    unittest.main()
