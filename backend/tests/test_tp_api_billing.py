"""Billing for Third Party API statements — the classifier, the base, and the state machine.

This is the only billable statement type whose file carries more than one PRODUCT, and every
product bills under its own markup category. That makes three things worth pinning that
neither the LCC nor the NDC suite has to:

* WHAT a row bills as: a category, and a sale or a CREDIT — which on TBO is decided by the
  invoice series, because its file carries no sign.
* WHY a row is out, not just that it is. `bill_kind` has several not-billable values, each
  driving a different sentence and a different group in the gaps view, and the ORDER they are
  tested in decides which sentence a row gets.
* That an excluded row KEEPS ITS AMOUNT. A count with no money attached is how ₹3,280
  disappears behind the word "1", which is the failure this whole design is arranged to
  prevent — so it is asserted directly.

Everything here is pure: no DB, no network. The projection's `project_batch` needs a session
and is covered by the end-to-end run instead.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import customer_resolver as cres  # noqa: E402
from app.services import statement_spec as spec  # noqa: E402
from app.services import tp_api_billing_projection as proj  # noqa: E402
from app.services import tp_api_spec as tp  # noqa: E402

SLUG = "tp-api"


# Real rows, as `data` holds them after tp_api_spec.normalize.
TBO_TRAIN = {
    "product_type": "Train", "booking_status": None, "invoice_number": "SM/2627/566301",
    "passenger_name": "lovekush singh X 1", "net_amount": "3280", "base_fare": "3260.4",
    "booking_class": "3A", "transaction_date": "2026-08-01", "vendor": "TBO",
    "quota": "General", "reference_no": "8151629905",
    "narration": ("Train Name-NZM RAJDHANI Train number- 22221 TravelDate-Aug  2 2026  "
                  "From-C SHIVAJI MAH T (CSMT) To-H NIZAMUDDIN (NZM)"),
}
# SM/2627/701490 sold this berth for ₹390; MZ/2627/143655 cancels it — NET is the refund.
TBO_TRAIN_CANCELLATION = {
    "product_type": "Train", "invoice_number": "MZ/2627/143655", "vendor": "TBO",
    "passenger_name": "RAKESH KR SINGH X 1", "net_amount": "145", "base_fare": "145",
    "cancellation_fee": "190", "reference_no": "6708865985",
}
# SM/2627/578753 sold ₹850 on this reference; the refund memo returns all but ₹17.
TBO_REFUND_MEMO = {
    "product_type": "Train", "invoice_number": "RM/2627/30789", "vendor": "TBO",
    "passenger_name": "GUUDI X 1", "net_amount": "833", "base_fare": "830.4",
    "reference_no": "TBOB9214471937388143",
}
TBO_HOTEL = {
    "product_type": "Hotel", "invoice_number": "SM/2627/614284", "vendor": "TBO",
    "passenger_name": "Ramesha Ramesha X 1", "net_amount": "39098", "base_fare": "37756.77",
    "airline_property_name": "Trident Chennai", "destination": "Chennai",
    "start_date": "2026-09-23", "end_date": "2026-09-27", "no_of_nights": "4",
    "intl_dom": "Domestic", "transaction_date": "2026-08-11",
}
TBO_BUS = {
    "product_type": "Bus", "invoice_number": "MW/2627/108385", "vendor": "TBO",
    "passenger_name": "SANDEEP  GARG X 1", "net_amount": "2154", "discount": "90",
    "narration": "TicketNo- 9BS3V6YG SeatName-3L Source-Delhi Destination-Indore DateOfJourney-Aug 23 2026",
}
MMT_HOTEL_FULLY_REFUNDED = {
    "product_type": "Hotel", "booking_status": "Cancelled", "booking_id": "NH28165511775508",
    "passenger_name": "Kishore Chakraborty", "total_paid_amount": "15508",
    "refund_amount": "15507.5", "vendor": "MakeMyTrip",
}
MMT_FLIGHT_REFUND_ONLY = {
    "product_type": "Flight", "booking_status": "Cancelled", "booking_id": "MN2GIZ1TYPFUDV7X3454",
    "passenger_name": "ARCHANA HANDA", "refund_amount": "54762", "vendor": "MakeMyTrip",
}
MMT_HOTEL_TRAVELLED = {
    "product_type": "Hotel", "booking_status": "Travelled", "booking_id": "NH24229512007220",
    "passenger_name": "ANKUR SHUKLA", "total_paid_amount": "1545", "vendor": "MakeMyTrip",
    "airline_property_name": "Hotel Deviram Palace", "origin": "AGRA",
    "start_date": "2026-08-26", "end_date": "2026-08-27",
}
MMT_HOTEL_CANCELLED = {
    "product_type": "Hotel", "booking_status": "Cancelled", "booking_id": "NH23065512619254",
    "passenger_name": "RAJEEV JETLY", "total_paid_amount": "0", "refund_amount": "0",
    "start_date": "2026-09-20", "vendor": "MakeMyTrip",
}
MMT_FLIGHT_SALE = {
    "product_type": "Flight", "booking_status": "Travelled", "booking_id": "MF28EAIWUGXFCJAE7195",
    "pnr": "12MGDG", "passenger_name": "GURUNADH ALIGI", "total_paid_amount": "5508",
    "airline_property_name": "Air India", "flight_number": "AI-560",
    "origin": "HYD", "destination": "DEL", "vendor": "MakeMyTrip",
}


class _Row:
    """The handful of attributes `billing_state` and `is_projectable` actually read."""

    def __init__(self, *, bill_kind=None, bill_status=cres.UNRESOLVED,
                 customer_type=None, customer_id=None, corporate_id=None,
                 projected=False):
        self.bill_kind = bill_kind
        self.bill_status = bill_status
        self.bill_customer_type = customer_type
        self.bill_customer_id = customer_id
        self.bill_corporate_id = corporate_id
        self.projected_ticket_id = 1 if projected else None
        self.bill_pax_count = None
        self.data = {}


class _Ticket:
    def __init__(self, *, customer_type=None, customer_id=None, corporate_id=None,
                 billing_id=None, pax_count=1):
        self.id = 1
        self.customer_type = customer_type
        self.customer_id = customer_id
        self.corporate_id = corporate_id
        self.billing_id = billing_id
        self.pax_count = pax_count


class TestBillingBase(unittest.TestCase):
    """`net_amount` (TBO's NET) or `total_paid_amount` (MMT's tender total) — never both,
    because the two are different facts and each is absent on the other vendor's file."""

    def test_tbos_net_is_used(self):
        self.assertEqual(proj.bill_base(TBO_TRAIN), Decimal("3280"))

    def test_mmt_falls_through_to_the_tender_total(self):
        self.assertEqual(proj.bill_base(MMT_FLIGHT_SALE), Decimal("5508"))

    def test_net_wins_when_both_are_present_and_non_zero(self):
        self.assertEqual(
            proj.bill_base({"net_amount": "3280", "total_paid_amount": "999"}),
            Decimal("3280"))

    def test_an_explicit_zero_does_not_stop_the_search(self):
        """FIRST NON-ZERO, not a plain coalesce. A coalesce would stop at "0.00" and never
        look at the other vendor's column, zeroing a real figure on a mixed file."""
        self.assertEqual(
            proj.bill_base({"net_amount": "0", "total_paid_amount": "5000"}),
            Decimal("5000"))

    def test_a_genuine_nil_is_zero_not_none(self):
        """0 is "the vendor says nothing is payable"; None is "no cell here would parse".
        Different reasons, different copy — collapsing them would hide a mis-mapped column."""
        self.assertEqual(proj.bill_base({"net_amount": "0"}), Decimal("0"))

    def test_nothing_readable_is_none(self):
        self.assertIsNone(proj.bill_base({}))
        self.assertIsNone(proj.bill_base({"net_amount": "", "total_paid_amount": "  "}))
        self.assertIsNone(proj.bill_base({"net_amount": "see invoice"}))

    def test_a_negative_settled_figure_survives(self):
        self.assertEqual(proj.bill_base({"net_amount": "-9200"}), Decimal("-9200"))


class TestClassifier(unittest.TestCase):
    """`bill_kind`, and the ORDER its tests run in."""

    # ── every category bills ────────────────────────────────────────────────
    def test_the_real_tbo_train_row_bills_and_keeps_its_money(self):
        kind, amount = proj.classify(TBO_TRAIN)
        self.assertEqual(kind, proj.SALE)
        self.assertEqual(amount, Decimal("3280"))
        self.assertEqual(proj.row_category(TBO_TRAIN), "train")

    def test_hotels_and_buses_bill_under_their_own_category(self):
        for data, category, amount in ((TBO_HOTEL, "hotel", "39098"),
                                       (TBO_BUS, "bus", "2154"),
                                       (MMT_HOTEL_TRAVELLED, "hotel", "1545")):
            with self.subTest(category=category):
                self.assertEqual(proj.classify(data), (proj.SALE, Decimal(amount)))
                self.assertEqual(proj.row_category(data), category)

    def test_flight_is_the_air_category(self):
        """"Flight" is the statement's display word; 'air' is the markup slug."""
        self.assertEqual(proj.row_category(MMT_FLIGHT_SALE), "air")

    def test_the_real_mmt_flight_row_bills(self):
        kind, amount = proj.classify(MMT_FLIGHT_SALE)
        self.assertEqual(kind, proj.SALE)
        self.assertEqual(amount, Decimal("5508"))

    # ── what is still out ───────────────────────────────────────────────────
    def test_a_product_with_no_category_is_out_and_keeps_its_money(self):
        """THE assertion the gaps view exists for: a count with no amount is how ₹3,000 of
        visa fees hides behind the word "1"."""
        kind, amount = proj.classify({"product_type": "Visa", "net_amount": "3000"})
        self.assertEqual(kind, proj.NO_CATEGORY)
        self.assertEqual(amount, Decimal("3000"))
        self.assertIn("Visa", proj.reason_for(kind, "Visa"))

    def test_a_blank_product_has_no_category(self):
        """Not defaulted to a category: that would be a guess about which markup to charge."""
        kind, _ = proj.classify({"net_amount": "100"})
        self.assertEqual(kind, proj.NO_CATEGORY)
        self.assertIn("does not say which product", proj.reason_for(kind, None))

    def test_category_is_tested_before_status(self):
        kind, _ = proj.classify({"product_type": "Visa", "booking_status": "Pending"})
        self.assertEqual(kind, proj.NO_CATEGORY)

    def test_the_real_cancelled_mmt_hotel_has_nothing_to_bill(self):
        kind, _ = proj.classify(MMT_HOTEL_CANCELLED)
        self.assertEqual(kind, proj.CANCELLED)

    def test_pending_beats_a_perfectly_good_amount(self):
        kind, amount = proj.classify({
            "product_type": "Hotel", "booking_status": "Pending", "net_amount": "4791.95"})
        self.assertEqual(kind, proj.PENDING)
        self.assertEqual(amount, Decimal("4791.95"))

    def test_a_dead_cancellation_is_named_precisely(self):
        """`cancelled` is a strict subset of `no_amount` — it exists only to say so. A dead
        cancellation and an unreadable cell are the same verdict for very different reasons,
        and the user can only act on one of them."""
        kind, _ = proj.classify({
            "product_type": "Flight", "booking_status": "Cancelled",
            "refund_amount": "0", "cancellation_fee": "0", "base_fare": "0"})
        self.assertEqual(kind, proj.CANCELLED)

    def test_a_cancelled_flight_that_kept_a_fee_is_still_billable(self):
        """Money moved, so there is something to invoice — a cancellation fee is a charge."""
        kind, amount = proj.classify({
            "product_type": "Flight", "booking_status": "Cancelled",
            "cancellation_fee": "500", "net_amount": "500"})
        self.assertEqual(kind, proj.SALE)
        self.assertEqual(amount, Decimal("500"))

    def test_an_unreadable_amount_on_a_live_booking_is_no_amount(self):
        kind, amount = proj.classify({"product_type": "Flight", "booking_status": "Travelled"})
        self.assertEqual(kind, proj.NO_AMOUNT)
        self.assertIsNone(amount)

    def test_an_unparseable_component_is_not_treated_as_zero(self):
        """`_is_zero` must not write a row off as a dead cancellation because one of its
        cells was unreadable — unknown is not nil."""
        kind, _ = proj.classify({
            "product_type": "Flight", "booking_status": "Cancelled",
            "refund_amount": "N/A", "cancellation_fee": "0", "base_fare": "0"})
        self.assertEqual(kind, proj.NO_AMOUNT)

    # ── credits ─────────────────────────────────────────────────────────────
    def test_the_sign_comes_from_the_file_not_the_status(self):
        """No status-driven negation. Inventing a credit from a status while the number
        stays positive is how a sale becomes a credit note on an invoice."""
        self.assertEqual(proj.classify({"product_type": "Flight", "net_amount": "-9200"})[0],
                         proj.REFUND)
        self.assertEqual(proj.classify({"product_type": "Flight", "net_amount": "9200",
                                        "booking_status": "Refunded"})[0], proj.SALE)

    def test_a_tbo_cancellation_line_is_a_credit(self):
        """MZ/: NET is the refund. Billed as a sale it would charge ₹145 for a berth that was
        given back."""
        self.assertEqual(proj.classify(TBO_TRAIN_CANCELLATION), (proj.REFUND, Decimal("-145")))

    def test_a_tbo_refund_memo_is_a_credit(self):
        self.assertEqual(proj.classify(TBO_REFUND_MEMO), (proj.REFUND, Decimal("-833")))

    def test_a_tbo_sale_series_stays_a_sale(self):
        for series in ("SM", "MW", "ZZ"):
            with self.subTest(series=series):
                data = {**TBO_TRAIN, "invoice_number": f"{series}/2627/1"}
                self.assertEqual(proj.classify(data)[0], proj.SALE)

    def test_the_credit_series_is_tbo_only(self):
        """Another vendor numbering its invoices MZ/… says nothing about TBO's series."""
        data = {**TBO_TRAIN_CANCELLATION, "vendor": "MakeMyTrip"}
        self.assertEqual(proj.classify(data), (proj.SALE, Decimal("145")))

    def test_the_invoice_series_is_the_prefix(self):
        self.assertEqual(proj.invoice_series({"invoice_number": " mz/2627/143655"}), "MZ")
        self.assertIsNone(proj.invoice_series({"invoice_number": "143655"}))
        self.assertIsNone(proj.invoice_series({}))

    # ── MakeMyTrip cancellations: what the vendor kept ──────────────────────
    def test_a_fully_refunded_mmt_cancellation_has_nothing_to_bill(self):
        """₹15,508 paid, ₹15,507.50 refunded. Billing the paid figure would invoice a stay
        that never happened; billing the residue would raise a 50-paise invoice."""
        self.assertEqual(proj.classify(MMT_HOTEL_FULLY_REFUNDED), (proj.CANCELLED, Decimal("0")))

    def test_a_refund_a_few_paise_over_the_payment_is_still_nil(self):
        data = {**MMT_HOTEL_FULLY_REFUNDED, "total_paid_amount": "10770",
                "refund_amount": "10770.98"}
        self.assertEqual(proj.classify(data)[0], proj.CANCELLED)

    def test_a_retained_cancellation_charge_bills(self):
        data = {**MMT_HOTEL_FULLY_REFUNDED, "total_paid_amount": "5000", "refund_amount": "4000"}
        self.assertEqual(proj.classify(data), (proj.SALE, Decimal("1000")))

    def test_a_refund_with_no_payment_on_the_statement_needs_review(self):
        """The sale it reverses is on another statement — nothing here says which bill the
        credit belongs on. The amount is kept, as a credit, so the gaps view shows it."""
        self.assertEqual(proj.classify(MMT_FLIGHT_REFUND_ONLY),
                         (proj.NEEDS_REVIEW, Decimal("-54762")))

    def test_a_net_figure_is_never_netted_again(self):
        """TBO's NET is already after every refund; subtracting one would count it twice."""
        data = {"product_type": "Train", "booking_status": "Cancelled",
                "net_amount": "500", "refund_amount": "400", "total_paid_amount": "900"}
        self.assertEqual(proj.classify(data), (proj.SALE, Decimal("500")))

    def test_every_classifiable_kind_is_reachable(self):
        seen = {
            proj.classify(TBO_TRAIN)[0],
            proj.classify(TBO_TRAIN_CANCELLATION)[0],
            proj.classify({"product_type": "Visa"})[0],
            proj.classify({"product_type": "Flight", "booking_status": "Pending"})[0],
            proj.classify(MMT_HOTEL_FULLY_REFUNDED)[0],
            proj.classify(MMT_FLIGHT_REFUND_ONLY)[0],
            proj.classify({"product_type": "Flight"})[0],
        }
        self.assertEqual(seen, set(proj.BILL_KINDS) - set(proj.LEGACY_KINDS))


class TestLegacyVerdict(unittest.TestCase):
    """Rows classified before every category billed are stored as `not_flight`."""

    def test_it_stays_not_billable_until_rematched(self):
        """Nothing silently re-classifies them — a Re-match is a write the user asks for."""
        self.assertIn(proj.NOT_FLIGHT, proj.NOT_BILLABLE_KINDS)
        row = _Row(bill_kind=proj.NOT_FLIGHT, bill_status=cres.OVERRIDDEN, customer_id=1)
        self.assertEqual(proj.billing_state(row, None), "not_billable")
        self.assertFalse(proj.is_projectable(row))

    def test_its_reason_says_to_rematch(self):
        self.assertIn("Re-match", proj.reason_for(proj.NOT_FLIGHT, "Hotel"))

    def test_classify_never_produces_it(self):
        for data in (TBO_TRAIN, TBO_HOTEL, TBO_BUS, MMT_HOTEL_CANCELLED, {"net_amount": "1"}):
            self.assertNotEqual(proj.classify(data)[0], proj.NOT_FLIGHT)


class TestReasons(unittest.TestCase):
    """The strings the gaps view GROUPs on — identical per gap type, per product."""

    def test_every_not_billable_kind_has_a_reason(self):
        for kind in proj.NOT_BILLABLE_KINDS:
            with self.subTest(kind=kind):
                self.assertTrue(proj.reason_for(kind, "Visa"))

    def test_a_billable_kind_has_none(self):
        for kind in proj.BILLABLE_KINDS:
            self.assertIsNone(proj.reason_for(kind, "Flight"))

    def test_the_product_is_named_so_the_gaps_view_can_group_on_it(self):
        self.assertIn("Visa", proj.reason_for(proj.NO_CATEGORY, "Visa"))
        self.assertIn("Forex", proj.reason_for(proj.NO_CATEGORY, "Forex"))

    def test_two_rows_of_the_same_product_share_one_string(self):
        # Otherwise forty visa rows become forty groups of one and tell the user nothing.
        self.assertEqual(proj.reason_for(proj.NO_CATEGORY, "Visa"),
                         proj.reason_for(proj.NO_CATEGORY, "Visa"))

    def test_every_kind_fits_the_column(self):
        """`third_party_api.bill_kind` is String(12)."""
        for kind in proj.BILL_KINDS:
            self.assertLessEqual(len(kind), 12, kind)


class TestPax(unittest.TestCase):
    """The pax count is a price input — a fixed markup is multiplied by it."""

    def test_the_file_figure_is_read(self):
        self.assertEqual(proj.parse_pax({"pax_count": "6"}), (6, proj.PAX_FILE))
        self.assertEqual(proj.parse_pax({"pax_count": "2.0"}), (2, proj.PAX_FILE))

    def test_anything_unusable_is_one_passenger_and_says_so(self):
        """Never 0: it would zero the fixed markup with nothing on screen to say why."""
        for raw in (None, "", "0", "-1", "abc", "1.5", "150"):
            with self.subTest(raw=raw):
                self.assertEqual(proj.parse_pax({"pax_count": raw}), (1, proj.PAX_DEFAULT))

    def test_tbos_name_suffix_becomes_the_pax(self):
        data = {"passenger_name": "GARIMA GUPTA X 6"}
        tp.normalize(data)
        self.assertEqual(proj.parse_pax(data), (6, proj.PAX_FILE))

    def test_a_stamped_pax_beats_the_file(self):
        row = _Row(bill_kind=proj.SALE)
        row.data = {"pax_count": "6"}
        row.bill_pax_count = None
        self.assertEqual(proj.row_pax(row), 6)
        row.bill_pax_count = 3                      # typed on the worklist
        self.assertEqual(proj.row_pax(row), 3)

    def test_a_ticket_sent_with_a_different_pax_is_stale(self):
        row = _Row(bill_kind=proj.SALE, bill_status=cres.OVERRIDDEN, customer_id=1, projected=True)
        row.bill_pax_count = 3
        ticket = _Ticket(customer_id=1)
        ticket.pax_count = 6
        self.assertEqual(proj.billing_state(row, ticket), "stale")
        ticket.pax_count = 3
        self.assertEqual(proj.billing_state(row, ticket), "sent")

    def test_an_unstamped_row_matches_a_one_pax_ticket(self):
        """Rows resolved before pax was tracked; the SQL twin coalesces to 1 the same way."""
        row = _Row(bill_kind=proj.SALE, bill_status=cres.RESOLVED, customer_id=1, projected=True)
        row.bill_pax_count = None
        ticket = _Ticket(customer_id=1)
        ticket.pax_count = 1
        self.assertEqual(proj.billing_state(row, ticket), "sent")


class TestCategoryFilterValues(unittest.TestCase):
    def test_every_spelling_of_a_category_is_matched(self):
        self.assertIn("flight", proj.category_product_values("air"))
        self.assertIn("air", proj.category_product_values("air"))
        self.assertIn("hotel", proj.category_product_values("hotel"))
        self.assertNotIn("hotel", proj.category_product_values("air"))


class TestBillingState(unittest.TestCase):
    """The seven states, and the NULL trap."""

    def test_every_declared_state_is_reachable(self):
        seen = {
            proj.billing_state(_Row(bill_kind=proj.SALE, bill_status=cres.RESOLVED, projected=True),
                               _Ticket(billing_id=7)),
            proj.billing_state(_Row(bill_kind=proj.NOT_FLIGHT), None),
            proj.billing_state(_Row(bill_kind=proj.SALE), None),
            proj.billing_state(_Row(bill_kind=proj.SALE, bill_status=cres.RESOLVED), None),
            proj.billing_state(_Row(bill_kind=proj.SALE, projected=True), _Ticket()),
            proj.billing_state(_Row(bill_kind=proj.SALE, bill_status=cres.RESOLVED,
                                    customer_id=1, projected=True), _Ticket(customer_id=2)),
            proj.billing_state(_Row(bill_kind=proj.SALE, bill_status=cres.RESOLVED,
                                    customer_id=1, projected=True), _Ticket(customer_id=1)),
        }
        self.assertEqual(seen, set(proj.BILLING_STATES))

    def test_a_not_billable_row_is_never_sendable(self):
        for kind in proj.NOT_BILLABLE_KINDS:
            with self.subTest(kind=kind):
                row = _Row(bill_kind=kind, bill_status=cres.OVERRIDDEN, customer_id=1)
                self.assertEqual(proj.billing_state(row, None), "not_billable")
                self.assertNotIn(proj.billing_state(row, None), proj.SENDABLE_STATES)
                self.assertFalse(proj.is_projectable(row))

    def test_a_null_bill_kind_is_not_not_billable(self):
        """THE NULL TRAP. A row imported but never resolved has bill_kind NULL. In Python
        `None in NOT_BILLABLE_KINDS` is False, which is right; the SQL twin has to agree, or
        every unresolved row drops out of every result set."""
        self.assertFalse(proj._is_not_billable(None))
        row = _Row(bill_kind=None, bill_status=cres.RESOLVED)
        self.assertEqual(proj.billing_state(row, None), "ready")

    def test_invoiced_beats_everything(self):
        row = _Row(bill_kind=proj.NOT_FLIGHT, bill_status=cres.UNRESOLVED, projected=True)
        self.assertEqual(proj.billing_state(row, _Ticket(billing_id=9)), "invoiced")

    def test_two_null_corporates_are_a_match_not_a_difference(self):
        row = _Row(bill_kind=proj.SALE, bill_status=cres.RESOLVED,
                   customer_type="direct", customer_id=5, projected=True)
        ticket = _Ticket(customer_type="direct", customer_id=5)
        self.assertEqual(proj.billing_state(row, ticket), "sent")

    def test_a_vanished_ticket_falls_back_rather_than_claiming_to_be_in_billing(self):
        """`projected_ticket_id` is ON DELETE SET NULL, so the row can outlive its ticket."""
        row = _Row(bill_kind=proj.SALE, bill_status=cres.RESOLVED, projected=True)
        self.assertEqual(proj.billing_state(row, None), "ready")

    def test_sendable_is_exactly_ready_and_stale(self):
        self.assertEqual(set(proj.SENDABLE_STATES), {"ready", "stale"})

    def test_every_state_has_a_sql_twin(self):
        """One definition written twice; a state with no SQL condition would silently be an
        un-filterable option in the worklist's dropdown."""
        from sqlalchemy.orm import aliased
        from app.models.uploaded_ticket import UploadedTicket
        T = aliased(UploadedTicket)
        for state in (*proj.BILLING_STATES, "sendable"):
            with self.subTest(state=state):
                self.assertIsNotNone(proj.billing_state_cond(state, T))
        self.assertIsNone(proj.billing_state_cond("nonsense", T))

    def test_only_a_billable_kind_with_a_party_projects(self):
        self.assertTrue(proj.is_projectable(
            _Row(bill_kind=proj.SALE, bill_status=cres.RESOLVED)))
        self.assertTrue(proj.is_projectable(
            _Row(bill_kind=proj.REFUND, bill_status=cres.DEFAULTED)))
        self.assertFalse(proj.is_projectable(
            _Row(bill_kind=proj.SALE, bill_status=cres.AMBIGUOUS)))


class TestTicketFieldMap(unittest.TestCase):
    """What lands on `uploaded_tickets` for a billable row of any category."""

    def _ticket(self, data, *, amount, **kw):
        row = _Row(bill_kind=proj.SALE if amount >= 0 else proj.REFUND,
                   bill_status=cres.RESOLVED, **kw)
        row.id = 11
        row.batch_id = "b1"
        row.tenant_id = 4
        row.created_by_id = 16
        row.source_format = "mmt-bookings-v1"
        row.data = data
        row.bill_amount = amount
        row.bill_match_reason = None
        from datetime import datetime
        return proj._build_ticket(row, now=datetime(2026, 9, 13), billing_batch_id="bb1",
                                  source_file="MMT.xlsx", vendor="MakeMyTrip")

    def test_the_billing_base_is_total_amt(self):
        t = self._ticket(MMT_FLIGHT_SALE, amount=Decimal("5508"))
        self.assertEqual(t["total_amt"], Decimal("5508"))
        self.assertEqual(t["net_amt"], Decimal("5508"))

    def test_no_ticket_number_is_synthesised(self):
        """`_find_original_ticket` and BSP reconciliation both key on it; an invented one
        would collide with a real airline document."""
        self.assertIsNone(self._ticket(MMT_FLIGHT_SALE, amount=Decimal("1"))["ticket_number"])

    def test_no_airline_code_is_guessed(self):
        """Deriving one from the flight number would make an AIRLINE DEAL match an
        aggregator booking. The name is carried; the code is not invented."""
        t = self._ticket(MMT_FLIGHT_SALE, amount=Decimal("1"))
        self.assertIsNone(t["airlines_code"])
        self.assertEqual(t["airline_name"], "Air India")

    def test_invoice_type_stays_none(self):
        """tickets.py::_CANCELLED_INVOICE_TYPES drives an unrelated cancellation path off
        "refund"/"credit note" — setting it would zero these tickets' commission."""
        self.assertIsNone(self._ticket(MMT_FLIGHT_SALE, amount=Decimal("-1"))["invoice_type"])

    def test_a_refund_is_carried_by_the_sign(self):
        t = self._ticket({**MMT_FLIGHT_SALE, "base_fare": "5000"}, amount=Decimal("-5508"))
        self.assertEqual(t["transaction_type"], "REFUND")
        self.assertEqual(t["total_amt"], Decimal("-5508"))
        self.assertEqual(t["sell_fare"], Decimal("-5000"))

    def test_the_pax_suffix_is_stripped_and_the_original_kept(self):
        t = self._ticket({**MMT_FLIGHT_SALE, "passenger_name": "lovekush singh X 1"},
                         amount=Decimal("1"))
        self.assertEqual(t["pax_name"], "lovekush singh")
        self.assertEqual(t["first_name"], "lovekush")
        self.assertEqual(t["last_name"], "singh")
        self.assertEqual(t["raw_data"]["passenger_name_raw"], "lovekush singh X 1")

    def test_the_vendor_gst_goes_to_tax_breakup_not_to_the_sell_columns(self):
        """`cgst_sell`/`sgst_sell`/`igst_sell` are what the AGENCY charges its customer, and
        api/v1/customers.py computes those from scratch at billing time."""
        t = self._ticket({**MMT_FLIGHT_SALE, "igst_amount": "18", "total_gst": "18"},
                         amount=Decimal("1"))
        self.assertNotIn("cgst_sell", t)
        self.assertNotIn("igst_sell", t)
        self.assertEqual(t["tax_breakup"]["IGST"], "18")

    def test_fees_are_recorded_but_not_added_to_the_base(self):
        t = self._ticket({**MMT_FLIGHT_SALE, "cancellation_fee": "-300",
                          "refund_amount": "-100"}, amount=Decimal("5508"))
        self.assertEqual(t["can_charge"], Decimal("300"))            # abs, recorded
        self.assertEqual(t["total_refund_amount"], Decimal("100"))
        self.assertEqual(t["total_amt"], Decimal("5508"))            # unchanged

    def test_provenance_names_the_type_and_the_aggregator(self):
        t = self._ticket(MMT_FLIGHT_SALE, amount=Decimal("1"))
        self.assertEqual(t["statement_type"], "TP-API")
        self.assertEqual(t["document_type"], "TP-API")
        self.assertEqual(t["booking_agency_name"], "MakeMyTrip")
        self.assertEqual(t["raw_data"]["tp_api_row_id"], 11)
        self.assertEqual(t["raw_data"]["product_type"], "Flight")

    def test_the_sector_is_built_from_the_role_named_columns(self):
        self.assertEqual(self._ticket(MMT_FLIGHT_SALE, amount=Decimal("1"))["sector"],
                         "HYD/DEL")

    def test_every_key_is_a_real_column(self):
        for data in (MMT_FLIGHT_SALE, TBO_HOTEL, TBO_TRAIN, TBO_BUS):
            with self.subTest(product=data["product_type"]):
                t = self._ticket(data, amount=Decimal("1"))
                unknown = set(t) - proj._TICKET_COLUMNS
                self.assertEqual(unknown, set(), f"not columns on uploaded_tickets: {unknown}")

    # ── every category ──────────────────────────────────────────────────────
    def test_a_flight_is_an_air_line_with_no_service_details(self):
        t = self._ticket(MMT_FLIGHT_SALE, amount=Decimal("5508"))
        self.assertEqual(t["product_category"], "air")
        self.assertIsNone(t["service_details"])
        self.assertEqual(t["air_pnr"], "12MGDG")

    def test_a_hotel_line_carries_its_category_and_its_stay(self):
        """`product_category` is what `party_markup.category_of` reads to pick the hotel
        markup; `service_details` is what the billing screens and the invoice print."""
        t = self._ticket(TBO_HOTEL, amount=Decimal("39098"))
        self.assertEqual(t["product_category"], "hotel")
        self.assertEqual(t["total_amt"], Decimal("39098"))
        self.assertEqual(t["booking_ref"], "SM/2627/614284")
        d = t["service_details"]
        self.assertEqual((d["category"], d["property"], d["check_in"], d["nights"]),
                         ("hotel", "Trident Chennai", "2026-09-23", "4"))
        self.assertIn("Trident Chennai", d["summary"])
        self.assertEqual(t["travel_dt"], "2026-09-23")

    def test_a_non_air_line_leaves_the_airline_columns_empty(self):
        """A hotel's name in `airline_name` is one income-by-airline report away from
        listing "Trident Chennai" as a carrier."""
        for data in (TBO_HOTEL, TBO_TRAIN, TBO_BUS):
            with self.subTest(product=data["product_type"]):
                t = self._ticket({**data, "airline_property_name": "Somebody", "pnr": "X1",
                                  "origin": "A", "destination": "B"}, amount=Decimal("1"))
                for col in ("airline_name", "airlines_code", "sector", "flight_no",
                            "air_pnr", "segments", "segment_type", "departure_datetime"):
                    self.assertIsNone(t[col], col)

    def test_a_train_line_takes_its_journey_from_the_narration(self):
        t = self._ticket(TBO_TRAIN, amount=Decimal("3280"))
        self.assertEqual(t["product_category"], "train")
        self.assertEqual(t["booking_class"], "3A")
        self.assertEqual(t["travel_dt"], "2026-08-02")
        d = t["service_details"]
        self.assertEqual((d["train_number"], d["from_code"], d["to_code"], d["pnr"]),
                         ("22221", "CSMT", "NZM", "8151629905"))

    def test_the_pax_rides_onto_the_ticket(self):
        """TBO's "GARIMA GUPTA X 6" — normalize reads the suffix into pax_count."""
        t = self._ticket({**TBO_TRAIN, "pax_count": "6"}, amount=Decimal("7860"))
        self.assertEqual(t["pax_count"], 6)
        self.assertEqual(self._ticket(MMT_FLIGHT_SALE, amount=Decimal("1"))["pax_count"], 1)

    def test_a_tbo_credit_projects_as_a_negative_line(self):
        t = self._ticket(TBO_TRAIN_CANCELLATION, amount=Decimal("-145"))
        self.assertEqual(t["transaction_type"], "REFUND")
        self.assertEqual(t["total_amt"], Decimal("-145"))
        self.assertEqual(t["sell_fare"], Decimal("-145"))
        self.assertEqual(t["can_charge"], Decimal("190"))       # recorded, not summed
        self.assertEqual(t["raw_data"]["invoice_series"], "MZ")


class TestMixinAndRegistry(unittest.TestCase):
    """The model split, and the flag that gates every billing endpoint."""

    _BILLING = {"bill_kind", "bill_status", "bill_customer_type", "bill_customer_id",
                "bill_corporate_id", "bill_match_reason", "bill_amount",
                "projected_ticket_id", "resolved_at", "resolved_by_id"}
    _ROLLUP = {"bill_group_key", "bill_is_anchor", "bill_latch_status"}

    def test_third_party_api_has_the_billing_columns_and_not_the_roll_up_ones(self):
        from app.models.statement_row import ThirdPartyApi
        cols = set(ThirdPartyApi.__table__.c.keys())
        self.assertTrue(self._BILLING <= cols)
        self.assertEqual(self._ROLLUP & cols, set(),
                         "an aggregator booking is one row and one ticket — nothing to latch")

    def test_ndc_kept_all_thirteen(self):
        from app.models.statement_row import Ndc
        cols = set(Ndc.__table__.c.keys())
        self.assertTrue((self._BILLING | self._ROLLUP) <= cols)

    def test_the_shared_mixin_gives_each_table_its_own_column_object(self):
        """The mixin's old docstring claimed a second adopter needed `@declared_attr` for
        every ForeignKey. It does not, for STRING targets: SQLAlchemy copies the column per
        mapper (orm/decl_base.py, `obj._copy()`). This is that claim, pinned."""
        from app.models.statement_row import Ndc, ThirdPartyApi
        a = Ndc.__table__.c.bill_customer_id
        b = ThirdPartyApi.__table__.c.bill_customer_id
        self.assertIsNot(a, b)
        for col in (a, b):
            self.assertEqual([str(fk.target_fullname) for fk in col.foreign_keys],
                             ["customers.id"])

    def test_third_party_api_has_no_split_columns(self):
        """A straight copy of ndc_billing's queries would `AttributeError` on these."""
        from app.models.statement_row import ThirdPartyApi
        for absent in ("row_seq", "is_total", "sector_index"):
            self.assertNotIn(absent, ThirdPartyApi.__table__.c.keys())

    def test_the_spec_declares_billing(self):
        self.assertTrue(spec.supports_billing(SLUG))

    def test_it_is_the_second_billable_type_and_there_is_no_third(self):
        billable = {s for s in spec.STATEMENT_SPECS if spec.supports_billing(s)}
        self.assertEqual(billable, {"ndc", SLUG})


class TestPaxSuffix(unittest.TestCase):
    """TBO writes the pax count onto the name. Stripping it is not cosmetic."""

    def test_the_suffix_goes(self):
        self.assertEqual(tp.strip_pax_suffix("lovekush singh X 1"), "lovekush singh")
        self.assertEqual(tp.strip_pax_suffix("NASER AHMED X 1"), "NASER AHMED")

    def test_a_multi_pax_suffix_goes_too(self):
        self.assertEqual(tp.strip_pax_suffix("guddi X 12"), "guddi")

    def test_a_name_without_one_is_untouched(self):
        self.assertEqual(tp.strip_pax_suffix("RAJEEV JETLY"), "RAJEEV JETLY")

    def test_blanks_are_none(self):
        self.assertIsNone(tp.strip_pax_suffix("  "))
        self.assertIsNone(tp.strip_pax_suffix(None))

    def test_it_removes_the_phantom_initial_that_breaks_matching(self):
        """The real reason this exists. `person_match_key` reads the "X" as a dropped
        initial, and a non-empty initials set ENABLES the resolver's strict-subset fallback —
        so a clean row can come back INITIALS_ONLY against a longer master name."""
        _, initials = cres.person_match_key("lovekush singh X 1")
        self.assertEqual(initials, frozenset({"X"}))
        _, after = cres.person_match_key(tp.strip_pax_suffix("lovekush singh X 1"))
        self.assertEqual(after, frozenset())

    def test_it_fixes_the_first_last_split(self):
        """`split_person_name` has no protection at all — it would put "1" on the ticket."""
        self.assertEqual(cres.split_person_name("lovekush singh X 1"),
                         ("lovekush singh X", "1"))
        self.assertEqual(cres.split_person_name(tp.strip_pax_suffix("lovekush singh X 1")),
                         ("lovekush", "singh"))

    def test_the_pax_count_is_still_read_from_the_suffix(self):
        """Regression: `normalize` and `strip_pax_suffix` share the same regex."""
        data = {"passenger_name": "lovekush singh X 3"}
        tp.normalize(data)
        self.assertEqual(data["pax_count"], "3")


if __name__ == "__main__":
    unittest.main()
