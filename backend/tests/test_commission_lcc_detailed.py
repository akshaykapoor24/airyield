"""Unit tests for LCC Detailed commission semantics — no DB, no network.

The load-bearing decision here is that `product_class` is NEVER used as a booking class.
It is a fare family ("Value", "Flexi"), and `_resolve_cabin_groups` defaults an unknown
code to Economy — so feeding it through would pay Economy rates on Business tickets and
make Business-only deals unmatchable, silently, on every row.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.commission.calc_row import KIND_ISSUE, KIND_REFUND, KIND_SKIP  # noqa: E402
from app.services.commission.lcc_detailed import (  # noqa: E402
    STATEMENT_TYPE, _sector, _tax, build_calc_row,
)
from app.services.deal_matching import SKIP_CLASS  # noqa: E402


class FakeRow:
    """Only the columns the adapter reads."""

    def __init__(self, **kw):
        defaults = dict(
            id=1, record_locator="ABC123", gds_record_locator=None, name="MR A PASSENGER",
            name1=None, bill_kind="sale", payment_status="PAID",
            airline_name="INDIGO", airline_id=7,
            booking_date=datetime(2026, 8, 8, 10, 30), transaction_date=None,
            departure_date=date(2026, 8, 20), international=False,
            product_class="Value", base_fare=5000, other_ssr_total=None,
            taxes=[{"code": "YQ", "amount": "300"}, {"code": "K3", "amount": "250"}],
            segments=[{"leg": 1, "route": "DEL/BOM", "flight_no": "6E123"}],
        )
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


class TestTaxExtraction(unittest.TestCase):
    def test_a_named_tax_is_found(self):
        self.assertEqual(_tax(FakeRow(), "YQ"), 300.0)

    def test_an_absent_tax_is_none_not_zero(self):
        """Zero would tell the engine the carrier charged nothing, which is a claim; None
        says we do not know, which is the truth."""
        self.assertIsNone(_tax(FakeRow(), "YR"))

    def test_code_matching_ignores_case_and_padding(self):
        r = FakeRow(taxes=[{"code": " yq ", "amount": "42"}])
        self.assertEqual(_tax(r, "YQ"), 42.0)

    def test_an_unparseable_amount_is_none(self):
        r = FakeRow(taxes=[{"code": "YQ", "amount": "n/a"}])
        self.assertIsNone(_tax(r, "YQ"))

    def test_no_taxes_at_all(self):
        self.assertIsNone(_tax(FakeRow(taxes=None), "YQ"))


class TestSector(unittest.TestCase):
    def test_one_leg(self):
        self.assertEqual(_sector(FakeRow()), "DEL/BOM")

    def test_legs_join_into_a_journey(self):
        r = FakeRow(segments=[{"route": "DEL/BOM"}, {"route": "BOM/MAA"}])
        self.assertEqual(_sector(r), "DEL/BOM/MAA")

    def test_a_repeated_airport_is_collapsed_once(self):
        """DEL/BOM then BOM/MAA is a three-airport journey, not four."""
        r = FakeRow(segments=[{"route": "DEL-BOM"}, {"route": "BOM-MAA"}, {"route": "MAA-DEL"}])
        self.assertEqual(_sector(r), "DEL/BOM/MAA/DEL")

    def test_no_segments_is_none(self):
        self.assertIsNone(_sector(FakeRow(segments=None)))
        self.assertIsNone(_sector(FakeRow(segments=[{"leg": 1}])))


class TestCalcRow(unittest.TestCase):
    def test_it_prices_against_airline_deals_not_b2b(self):
        """The carrier is the counterparty on its own statement."""
        ctx = build_calc_row(FakeRow(), "IndiGo")
        self.assertEqual(ctx.statement_type, STATEMENT_TYPE)
        self.assertEqual(ctx.statement_type, "AIRLINE")
        self.assertIsNone(ctx.supplier_agency)
        self.assertIsNone(ctx.supplier_agency_id)

    def test_the_fare_family_is_never_used_as_a_booking_class(self):
        ctx = build_calc_row(FakeRow(product_class="Business Flexi"), "IndiGo")
        self.assertIsNone(ctx.booking_class)
        self.assertIn(SKIP_CLASS, ctx.skip_criteria)
        self.assertIn("class", ctx.skip_rule_fields)

    def test_the_fare_family_is_still_reported_on_the_row(self):
        """Skipping it silently would leave the user with no idea why a class-restricted
        deal did not pay."""
        ctx = build_calc_row(FakeRow(product_class="Flexi"), "IndiGo")
        self.assertTrue(any("Flexi" in n for n in ctx.notes))

    def test_the_batch_carrier_wins_over_the_row(self):
        """An LCC export names no carrier — the uploader declares it, and that is the
        spelling the deal was written against."""
        ctx = build_calc_row(FakeRow(airline_name="6E"), "IndiGo")
        self.assertEqual(ctx.airline_name, "IndiGo")

    def test_the_row_carrier_is_the_fallback(self):
        ctx = build_calc_row(FakeRow(airline_name="IndiGo"), None)
        self.assertEqual(ctx.airline_name, "IndiGo")

    def test_segment_type_comes_from_the_international_flag(self):
        self.assertEqual(build_calc_row(FakeRow(international=False), "X").segment_type, "Domestic")
        self.assertEqual(build_calc_row(FakeRow(international=True), "X").segment_type, "International")

    def test_an_unknown_international_flag_is_not_guessed(self):
        """None means 'cannot determine', which _flight_type_matches lets through — a
        fabricated Domestic would silently exclude every International deal."""
        self.assertIsNone(build_calc_row(FakeRow(international=None), "X").segment_type)

    def test_travel_date_and_sector_are_real(self):
        ctx = build_calc_row(FakeRow(), "IndiGo")
        self.assertEqual(ctx.travel_date, date(2026, 8, 20))
        self.assertEqual(ctx.sector, "DEL/BOM")
        self.assertNotIn("travel_date", ctx.skipped_labels)
        self.assertNotIn("sector", ctx.skipped_labels)

    def test_issue_date_prefers_the_booking_date(self):
        ctx = build_calc_row(FakeRow(), "IndiGo")
        self.assertEqual(ctx.issue_date, date(2026, 8, 8))

    def test_issue_date_falls_back_to_the_transaction_date(self):
        ctx = build_calc_row(FakeRow(booking_date=None,
                                     transaction_date=datetime(2026, 7, 1, 9, 0)), "IndiGo")
        self.assertEqual(ctx.issue_date, date(2026, 7, 1))

    def test_yq_and_yr_come_off_the_folded_taxes(self):
        ctx = build_calc_row(FakeRow(taxes=[{"code": "YQ", "amount": "300"},
                                            {"code": "YR", "amount": "150"}]), "IndiGo")
        self.assertEqual(ctx.yq, 300.0)
        self.assertEqual(ctx.yr, 150.0)

    def test_a_combined_ssr_total_is_shown_but_never_claimed(self):
        ctx = build_calc_row(FakeRow(other_ssr_total=900), "IndiGo")
        self.assertEqual(ctx.ancillary_amount, 900.0)
        self.assertIsNone(ctx.seat_selection)
        self.assertIsNone(ctx.excess_baggage)
        self.assertIsNone(ctx.meals)

    def test_no_declared_amounts_to_compare_against(self):
        """A carrier's own statement does not print what it paid you — only third-party
        statements do, so there is nothing to build a variance from."""
        self.assertIsNone(build_calc_row(FakeRow(), "IndiGo").declared)


class TestTransactionKind(unittest.TestCase):
    def test_a_sale_earns(self):
        self.assertEqual(build_calc_row(FakeRow(bill_kind="sale"), "X").kind, KIND_ISSUE)

    def test_a_refund_reverses(self):
        self.assertEqual(build_calc_row(FakeRow(bill_kind="refund"), "X").kind, KIND_REFUND)

    def test_a_payment_line_is_not_a_sale(self):
        ctx = build_calc_row(FakeRow(bill_kind="payment"), "X")
        self.assertEqual(ctx.kind, KIND_SKIP)
        self.assertTrue(ctx.kind_reason)

    def test_an_unclassified_row_behaves_like_a_sale(self):
        self.assertEqual(build_calc_row(FakeRow(bill_kind=None), "X").kind, KIND_ISSUE)


if __name__ == "__main__":
    unittest.main()
