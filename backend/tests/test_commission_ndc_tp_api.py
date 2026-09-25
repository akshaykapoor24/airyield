"""The two newest commission sources, on the decisions that are theirs alone — no DB.

Shaped like test_commission_third_party.py: `build_calc_row` is a pure function over a
statement row's `data`, so the whole normalisation can be tested without a session.

What is worth pinning here is not the field copying — that fails loudly — but the four
judgements a future reader might "simplify" away, because every one of them fails SILENTLY
as a wrong money figure:

  1. An NDC ancillary line must contribute NO fare components. It repeats the ticket's
     `Basic Fare`, so reading them off it pays the flight's incentive once per add-on.
  2. An NDC ancillary must land in the sub-type a deal actually pays on, and an
     unrecognised product must land in none of them rather than the nearest one.
  3. Neither source may let a flight-type-restricted deal through unverified. NDC prints
     no dom/intl column at all, and the engine's default for a NULL segment is "allow".
  4. A Third Party API file's hotel, train, bus and car rows must SKIP rather than vanish,
     and their reasons must group.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.commission import ndc as N  # noqa: E402
from app.services.commission import tp_api as T  # noqa: E402
from app.services.commission.calc_row import (  # noqa: E402
    KIND_ISSUE, KIND_REFUND, KIND_SKIP,
)
from app.services.deal_matching import SKIP_CLASS, SKIP_SEGMENT  # noqa: E402
from app.services.tp_airline_resolution import TpAirlineMatch  # noqa: E402

AI = TpAirlineMatch(airline_id=7, iata_code="AI", name="Air India", source="numeric_code")
SIXE = TpAirlineMatch(airline_id=9, iata_code="6E", name="IndiGo", source="name")


def ndc_row(rid: int = 1, **data):
    base = {"airline": "AI", "airline_iata_code": "098", "date_of_issue": "2025-04-11"}
    return SimpleNamespace(id=rid, data={**base, **data})


def api_row(rid: int = 1, **data):
    base = {"booking_status": "Confirmed", "booking_date": "2025-06-02"}
    return SimpleNamespace(id=rid, data={**base, **data})


class TestNdcFlightLine(unittest.TestCase):
    """The flight line is the best evidence on the router and must be treated as such."""

    def setUp(self):
        self.ctx = N.build_calc_row(ndc_row(
            document_no="0984848358656", txn_type="PAID_BOOKING", product="FLIGHT",
            departure_date="2025-05-02", sectors="DEL-BOM-DEL",
            class_of_booking="Y", basic_fare="12000.00", yq_tax="1500.00",
            yr_tax="300.00", payment_amount="14400.00", airline_pnr="ABC123",
        ), AI)

    def test_it_is_a_sale_with_its_own_fare_components(self):
        self.assertEqual(self.ctx.kind, KIND_ISSUE)
        self.assertEqual(self.ctx.fare_amount, 12000.0)
        self.assertEqual(self.ctx.yq, 1500.0)
        self.assertEqual(self.ctx.yr, 300.0)

    def test_the_class_is_real_so_class_rules_are_not_bypassed(self):
        # The one thing that separates NDC from BSP and LCC Detailed. Adding SKIP_CLASS
        # here "for consistency" would let an Economy-only deal pay a Business ticket.
        self.assertEqual(self.ctx.booking_class, "Y")
        self.assertNotIn(SKIP_CLASS, self.ctx.skip_criteria)

    def test_the_sector_is_normalised_the_way_every_other_source_writes_it(self):
        self.assertEqual(self.ctx.sector, "DEL/BOM/DEL")

    def test_the_carrier_is_the_masters_spelling_not_the_files_code(self):
        # `deals.airline_name` holds the master's spelling and the match is a lowercase
        # equality, so "AI" would never match anything.
        self.assertEqual(self.ctx.airline_name, "Air India")
        self.assertEqual(self.ctx.airline_id, 7)


class TestNdcAncillaryLines(unittest.TestCase):
    """An add-on is priced as an ancillary, and contributes nothing else."""

    def _anc(self, **over):
        return N.build_calc_row(ndc_row(
            # The repeated ticket columns are the trap: a latched line carries them.
            basic_fare="12000.00", total_fare="14400.00", yq_tax="1500.00",
            payment_amount="650.00", **over,
        ), AI)

    def test_a_paid_seat_pays_the_seat_base_and_no_fare(self):
        c = self._anc(txn_type="PAID_SEAT", product="SEAT")
        self.assertEqual(c.seat_selection, 650.0)
        self.assertEqual(c.ancillary_amount, 650.0)
        # THE POINT OF THE TEST. The row repeats Basic Fare 12000 and YQ 1500; reading
        # either would pay the flight's incentive a second time.
        self.assertIsNone(c.fare_amount)
        self.assertIsNone(c.yq)
        self.assertIsNone(c.yr)

    def test_baggage_and_meals_reach_their_own_bases(self):
        bag = self._anc(txn_type="PAID_BOOKING", product="EXCESS BAGGAGE")
        self.assertEqual(bag.excess_baggage, 650.0)
        self.assertIsNone(bag.seat_selection)

        meal = self._anc(txn_type="PAID_BOOKING", product="MEAL")
        self.assertEqual(meal.meals, 650.0)
        self.assertIsNone(meal.excess_baggage)

    def test_an_unrecognised_add_on_claims_nothing_and_says_so(self):
        # "Skipping is not passing", applied to ancillaries: a deal pays Ancillary as
        # baggage / meals / seat, and lounge access is none of them. Dropping it into the
        # nearest base would invent an incentive nobody contracted.
        c = self._anc(txn_type="PAID_BOOKING", product="LOUNGE ACCESS")
        self.assertIsNone(c.seat_selection)
        self.assertIsNone(c.excess_baggage)
        self.assertIsNone(c.meals)
        # Shown, so the money is not invisible.
        self.assertEqual(c.ancillary_amount, 650.0)
        self.assertTrue(any("nothing was claimed" in n for n in c.notes), c.notes)

    def test_a_flight_line_is_never_treated_as_an_add_on(self):
        c = self._anc(txn_type="PAID_BOOKING", product="FLIGHT")
        self.assertEqual(c.fare_amount, 12000.0)
        self.assertIsNone(c.ancillary_amount)


class TestNdcTransactionPolicy(unittest.TestCase):

    def test_a_refund_is_read_off_txn_type_not_off_the_sign(self):
        # A portal that writes a positive Payment Amount on a REFUND line must still
        # reverse — reading the sign would issue a credit note as an invoice.
        for pay in ("-9200.00", "9200.00"):
            c = N.build_calc_row(ndc_row(txn_type="REFUND", product="FLIGHT",
                                         document_no="0984848358656",
                                         payment_amount=pay), AI)
            self.assertEqual(c.kind, KIND_REFUND, pay)

    def test_the_refund_key_is_the_document_number(self):
        # The runner reverses by ticket number, so a refund and its issue must agree.
        c = N.build_calc_row(ndc_row(txn_type="REFUND", document_no="0984848358656"), AI)
        self.assertEqual(c.ticket_number, "0984848358656")

    def test_a_line_where_no_money_moved_is_not_a_sale(self):
        c = N.build_calc_row(ndc_row(txn_type="TICKETING", payment_amount="0",
                                     total_fare="0"), AI)
        self.assertEqual(c.kind, KIND_SKIP)


class TestFlightTypeIsNeverAssumed(unittest.TestCase):
    """The engine's default for a NULL segment is ALLOW, which is wrong for these two."""

    def test_ndc_always_declares_the_segment_skip(self):
        # An NDC export prints no domestic/international column at all. Without
        # SKIP_SEGMENT a Domestic-only deal pays every International ticket in the file.
        c = N.build_calc_row(ndc_row(txn_type="PAID_BOOKING", product="FLIGHT",
                                     class_of_booking="Y", basic_fare="100"), AI)
        self.assertIn(SKIP_SEGMENT, c.skip_criteria)
        self.assertIn("segment_type", c.skipped_labels)

    def test_tp_api_declares_it_only_when_the_cell_cannot_be_read(self):
        known = T.build_calc_row(api_row(
            product_type="Flight", intl_dom="Domestic", booking_class="Y",
            base_fare="4200", net_amount="5000"), "TBO", 44, SIXE)
        self.assertEqual(known.segment_type, "Domestic")
        self.assertNotIn(SKIP_SEGMENT, known.skip_criteria)

        # READABILITY, not presence: a spelling the engine's vocabulary does not know is
        # a fact we do not have, not a mismatch. Left as a mismatch it drops every
        # flight-type-restricted config and reports the row unmatched instead.
        odd = T.build_calc_row(api_row(
            product_type="Flight", intl_dom="DOM-INTL MIX", booking_class="Y",
            base_fare="4200", net_amount="5000"), "TBO", 44, SIXE)
        self.assertIn(SKIP_SEGMENT, odd.skip_criteria)

    def test_a_restrictive_flight_type_is_unconfirmed_rather_than_passed(self):
        from app.services.deal_matching import _flight_type_is_restrictive
        for ft in ("Domestic", "International", "domestic"):
            self.assertTrue(_flight_type_is_restrictive(ft), ft)
        for ft in ("Both", "All", "", None):
            self.assertFalse(_flight_type_is_restrictive(ft), ft)

    def test_a_slab_paying_different_dom_and_intl_rates_also_withholds(self):
        # The half that is easy to miss. `flight_type` is not the only segment
        # dependency: slab cells are keyed domEconomy / intlBusiness and
        # `_slab_seg_key` resolves an unknown segment to 'dom'. A slab paying 3%
        # domestic and 6% international, written for flight_type "Both", would pay the
        # 3% cell on every international ticket of a statement with no segment column.
        from app.services.deal_matching import _slab_is_segment_sensitive

        def config(cells):
            values = [SimpleNamespace(value_key=k, value=v) for k, v in cells.items()]
            return SimpleNamespace(slabs=[SimpleNamespace(values=values)])

        self.assertTrue(_slab_is_segment_sensitive(
            config({"domEconomy": 3.0, "intlEconomy": 6.0})))
        # Agreeing cells cost nothing, so flagging them would withhold on almost every
        # deal for no gain.
        self.assertFalse(_slab_is_segment_sensitive(
            config({"domEconomy": 3.0, "intlEconomy": 3.0})))
        # Only one side present: the other cell reads None and pays nothing, which is a
        # silent zero rather than an overpay -- not this predicate's job.
        self.assertFalse(_slab_is_segment_sensitive(config({"domEconomy": 3.0})))
        self.assertFalse(_slab_is_segment_sensitive(SimpleNamespace(slabs=[])))
        # Per class: Business may differ while Economy agrees.
        self.assertTrue(_slab_is_segment_sensitive(
            config({"domEconomy": 3.0, "intlEconomy": 3.0,
                    "domBusiness": 4.0, "intlBusiness": 9.0})))


class TestTpApiIsMultiProduct(unittest.TestCase):
    """Only flight rows price, and the rest must be visible rather than filtered out."""

    def _row(self, product, **over):
        return T.build_calc_row(
            api_row(product_type=product, net_amount="5000.00", **over),
            "TBO Travel", 44, SIXE if product == "Flight" else None)

    def test_a_flight_row_prices_against_a_b2b_deal(self):
        c = self._row("Flight", booking_class="Y", base_fare="4200.00",
                      origin_code="DEL", destination_code="BLR", intl_dom="Domestic",
                      pnr="PQ7RT2")
        self.assertEqual(c.kind, KIND_ISSUE)
        self.assertEqual(c.statement_type, "B2B")
        self.assertEqual(c.supplier_agency, "TBO Travel")
        self.assertEqual(c.supplier_agency_id, 44)
        self.assertEqual(c.sector, "DEL/BLR")
        self.assertEqual(c.airline_name, "IndiGo")

    def test_every_other_product_skips_with_a_reason_naming_it(self):
        for product in ("Hotel", "Train", "Bus", "Car"):
            c = self._row(product)
            self.assertEqual(c.kind, KIND_SKIP, product)
            self.assertIn(product, c.kind_reason or "", product)

    def test_the_skip_reasons_group_by_product_not_by_row(self):
        # The gaps tab groups by (status, reason) and caps at 50 groups. One sentence per
        # PRODUCT keeps four hundred hotel nights in one bucket; naming the booking would
        # give each its own and push every other reason off the screen.
        reasons = {T.build_calc_row(
            api_row(product_type="Hotel", booking_id=f"NH{i}", net_amount=f"{i}000"),
            "TBO", 44, None).kind_reason for i in range(25)}
        self.assertEqual(len(reasons), 1, reasons)

    def test_a_product_with_no_billing_category_still_says_what_it_was(self):
        c = self._row("Visa")
        self.assertEqual(c.kind, KIND_SKIP)
        self.assertIn("Visa", c.kind_reason or "")

    def test_a_blank_product_is_out_too_and_does_not_guess(self):
        c = T.build_calc_row(api_row(net_amount="5000"), "TBO", 44, None)
        self.assertEqual(c.kind, KIND_SKIP)
        self.assertIn("does not say which product", c.kind_reason or "")


class TestTpApiDeclaresNothing(unittest.TestCase):
    """An aggregator prints no commission it paid us, so there is no variance to report."""

    def test_the_adapter_says_it_has_no_declared_amounts(self):
        # `Agent Markup` is OUR markup to our own customer. Treating it as a declared
        # commission would invent a variance out of our own pricing.
        self.assertFalse(T.TpApiAdapter.has_declared_amounts)
        self.assertFalse(N.NdcAdapter.has_declared_amounts)

    def test_no_row_carries_declared_figures(self):
        c = T.build_calc_row(api_row(product_type="Flight", net_amount="5000",
                                     agent_markup="250", base_fare="4200",
                                     booking_class="Y", intl_dom="Domestic"),
                             "TBO", 44, SIXE)
        self.assertIsNone(c.declared)

    def test_the_pax_suffix_is_stripped_before_it_reaches_a_name(self):
        # TBO writes the pax count onto the name; "lovekush singh X 1" splits into
        # first="lovekush singh X", last="1" downstream.
        c = T.build_calc_row(api_row(product_type="Flight", net_amount="5000",
                                     passenger_name="lovekush singh X 1"),
                             "TBO", 44, SIXE)
        self.assertEqual(c.passenger_name, "lovekush singh")


class TestSupplierRequirements(unittest.TestCase):

    def test_only_the_aggregator_needs_a_consolidator_named(self):
        # An NDC export comes from the carrier; there is no consolidator to name, and
        # demanding one would block every upload from ever being priced.
        self.assertTrue(T.TpApiAdapter.requires_supplier)
        self.assertFalse(N.NdcAdapter.requires_supplier)

    def test_the_deal_pools_are_opposite(self):
        self.assertEqual(N.NdcAdapter.statement_type, "AIRLINE")
        self.assertEqual(T.TpApiAdapter.statement_type, "B2B")


if __name__ == "__main__":
    unittest.main()
