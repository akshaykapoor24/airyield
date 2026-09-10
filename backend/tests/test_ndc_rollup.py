"""The NDC billing roll-up — which statement rows become which ticket.

An NDC export is a transaction ledger. A seat sold with a ticket is its OWN line, with no
document number, tied to the flight only by PNR and passenger. `build_groups` is what
latches those onto the right ticket, and it is the one piece of this feature that can put
money on the wrong invoice without anything failing.

Everything here is pure — `build_groups` takes plain objects with `.id`, `.row_seq` and
`.data`, so no session and no database are involved. That seam is deliberate: it is the
same one `customer_resolver.CustomerIndex.from_rows` uses, and it is what makes the risky
half of the projection testable at all.

Note `is_total` is NOT exercised here: excluding the declared grand-total line is done by
the row query in `project_batch`, not by `build_groups`.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import ndc_billing_projection as proj  # noqa: E402

PNR = "9FTDB8"
PAX = "NITIN/CHAUHAN"
DOC = "0982185569174"
DOC2 = "0982185569175"


class Row:
    """The shape `build_groups` reads — an `Ndc` ORM row's public surface, minus the ORM."""

    def __init__(self, id, data, seq=None, **billing):
        self.id = id
        self.row_seq = seq
        self.data = data
        self.bill_latch_status = billing.get("latch")
        self.bill_status = billing.get("status")
        self.bill_kind = billing.get("kind")


def flight(id, *, doc=DOC, pnr=PNR, pax=PAX, txn="PAID_BOOKING", fare="7747.00",
           basic="5642.00", tax="2105.00", paid=None, seq=None, **extra):
    """A ticketed flight line. `paid` defaults to `fare` — a sale settles at its fare."""
    data = {
        "document_no": doc, "airline_pnr": pnr, "passenger_name": pax,
        "txn_type": txn, "product": "Flight", "airline": "AI",
        "total_fare": fare, "basic_fare": basic, "total_tax": tax,
        "payment_amount": fare if paid is None else paid,
        "date_of_issue": "15-Aug-2026", "departure_date": "15-Aug-2026",
        "sectors": "HSR-DEL", "flight_no": "AI2538", "currency": "INR",
        "k3_tax": "311.00", "yq_tax": "399.00", "yr_tax": "170.00", "other_taxes": "1225.00",
    }
    data.update(extra)
    return Row(id, {k: v for k, v in data.items() if v is not None}, seq=seq)


def seat(id, *, pnr=PNR, pax=PAX, txn="PAID_SEAT", amount="975.00", product="Seat", seq=None):
    """An ancillary line: no document number, identified only by PNR + passenger."""
    data = {
        "airline_pnr": pnr, "passenger_name": pax, "txn_type": txn, "product": product,
        "airline": "AI", "total_fare": amount, "payment_amount": amount,
    }
    return Row(id, {k: v for k, v in data.items() if v is not None}, seq=seq)


class TestOneTicket(unittest.TestCase):
    def test_a_flight_alone_is_one_group(self):
        (group,) = proj.build_groups([flight(1)])
        self.assertEqual(group.key, f"D:{DOC}")
        self.assertEqual(group.anchor.id, 1)
        self.assertEqual(group.latched, [])
        self.assertEqual(group.anchor.latch_status, proj.ANCHOR)

    def test_a_seat_latches_onto_its_flight(self):
        """The case the whole feature exists for: one billed ticket, the seat inside it."""
        (group,) = proj.build_groups([flight(1), seat(2)])
        self.assertEqual([ln.id for ln in group.latched], [2])
        self.assertEqual(group.latched[0].latch_status, proj.LATCHED)
        self.assertEqual(group.total, Decimal("8722.00"))       # 7747 + 975

    def test_the_seats_money_lands_in_its_own_column_and_in_the_total(self):
        """`total_amt` IS the billing base (api/v1/customers.py reads it first), so the
        ancillary has to be in it — and in `seat_selection`, so the invoice can say what
        the money was for."""
        (group,) = proj.build_groups([flight(1), seat(2)])
        values = proj.ticket_fields(group)
        self.assertEqual(values["total_amt"], Decimal("8722.00"))
        self.assertEqual(values["net_amt"], Decimal("8722.00"))
        self.assertEqual(values["seat_selection"], Decimal("975.00"))
        # The flight document's own figures are untouched by the ancillary.
        self.assertEqual(values["sell_fare"], Decimal("5642.00"))
        self.assertEqual(values["sell_tax"], Decimal("2105.00"))
        self.assertEqual(values["ticket_number"], DOC)
        self.assertEqual(values["air_pnr"], PNR)
        self.assertEqual(values["ticket_date"], "2026-08-15")

    def test_the_named_taxes_map_one_to_one(self):
        values = proj.ticket_fields(proj.build_groups([flight(1)])[0])
        self.assertEqual(values["sale_k3"], Decimal("311.00"))
        self.assertEqual(values["sell_tax_yq"], Decimal("399.00"))
        self.assertEqual(values["sale_yr"], Decimal("170.00"))
        self.assertEqual(values["other_tax"], Decimal("1225.00"))

    def test_ancillaries_go_to_the_column_their_product_names(self):
        rows = [flight(1),
                seat(2, product="Seat"),
                seat(3, product="Baggage", txn="PAID_BOOKING", amount="500.00"),
                seat(4, product="Meal", txn="PAID_BOOKING", amount="250.00")]
        values = proj.ticket_fields(proj.build_groups(rows)[0])
        self.assertEqual(values["seat_selection"], Decimal("975.00"))
        self.assertEqual(values["excess_baggage"], Decimal("500.00"))
        self.assertEqual(values["meals"], Decimal("250.00"))

    def test_an_unrecognised_product_is_recorded_not_treated_as_a_seat(self):
        """`seat_selection` is an incentive base. An unknown product landing there would
        silently inflate an incentive, so it goes to the recorded column instead.

        It still LATCHES: the discriminator is "is this the flight", not "is this one of
        the four add-ons we thought of", so a product nobody listed is an add-on on the
        passenger's ticket rather than a ticket of its own."""
        (group,) = proj.build_groups(
            [flight(1), seat(2, product="Lounge Access", txn="PAID_BOOKING", amount="300.00")])
        self.assertEqual(group.latched[0].bucket, proj.DEFAULT_ANCILLARY_BUCKET)
        values = proj.ticket_fields(group)
        self.assertEqual(values["booking_fee_sell"], Decimal("300.00"))
        self.assertIsNone(values["seat_selection"])

    def test_a_blank_product_is_read_as_the_flight(self):
        """A line we cannot classify bills on its own, which is visible. Latching it onto
        someone's ticket would move money silently."""
        rows = [flight(1, doc=DOC, product=None), flight(2, doc=DOC2, product=None)]
        self.assertEqual(len(proj.build_groups(rows)), 2)


class TestPassengerMatching(unittest.TestCase):
    """The latch key is `customer_resolver.person_match_key` — the same key the party
    resolver uses, so a seat cannot latch onto a ticket that resolves to someone else."""

    def test_spelling_variants_are_one_passenger(self):
        for spelling in ("NITIN/CHAUHAN", "MR NITIN CHAUHAN", "CHAUHAN NITIN",
                         "nitin chauhan", "NITIN  CHAUHAN"):
            with self.subTest(spelling=spelling):
                (group,) = proj.build_groups([flight(1), seat(2, pax=spelling)])
                self.assertEqual([ln.id for ln in group.latched], [2],
                                 f"{spelling!r} did not latch")

    def test_an_initial_does_not_latch(self):
        """"N CHAUHAN" could be any Chauhan. `person_match_key` drops single letters and
        never expands them — the same refusal documented at customer_resolver's foot, here
        where it decides whose invoice the money lands on. The row becomes an orphan, which
        is visible, rather than a guess, which is not."""
        groups = proj.build_groups([flight(1), seat(2, pax="N CHAUHAN")])
        self.assertEqual(len(groups), 2)
        orphan = next(g for g in groups if g.key == "O:2")
        self.assertEqual(orphan.anchor.latch_status, proj.ORPHAN)


class TestAmbiguity(unittest.TestCase):
    def test_two_tickets_for_one_passenger_leave_the_seat_unlatched(self):
        """A conjunction ticket (two documents, one journey) and a reissue both look like
        this. Neither is merged — the rule is one billed ticket per document number — and
        "latch to the first / the biggest" is a guess that ends on an invoice."""
        groups = proj.build_groups([flight(1, doc=DOC), flight(2, doc=DOC2), seat(3)])
        self.assertEqual(len(groups), 3)
        seat_group = next(g for g in groups if g.key == "O:3")
        self.assertEqual(seat_group.anchor.latch_status, proj.AMBIGUOUS)
        # And no money moved onto either ticket.
        for key in (f"D:{DOC}", f"D:{DOC2}"):
            group = next(g for g in groups if g.key == key)
            self.assertEqual(group.latched, [])

    def test_a_seat_naming_an_unknown_pnr_is_an_orphan(self):
        groups = proj.build_groups([flight(1), seat(2, pnr="ZZZZZZ")])
        self.assertEqual(next(g for g in groups if g.key == "O:2").anchor.latch_status,
                         proj.ORPHAN)

    def test_a_seat_with_nothing_to_latch_by_is_unidentified(self):
        for missing in ({"pnr": " "}, {"pax": " "}, {"pnr": " ", "pax": " "}):
            with self.subTest(**missing):
                groups = proj.build_groups([flight(1), seat(2, **missing)])
                self.assertEqual(next(g for g in groups if g.key == "O:2").anchor.latch_status,
                                 proj.UNIDENTIFIED)

    def test_an_orphan_is_not_projected_until_a_human_names_a_party(self):
        """Real money — an orphaned REFUND_SEAT is a seat refunded on a kept flight — so it
        is never silently dropped. It is inert until someone points it at a party."""
        row = Row(2, {}, latch=proj.ORPHAN, status="unresolved")
        self.assertFalse(proj.is_projectable(row))
        row.bill_status = "overridden"
        self.assertTrue(proj.is_projectable(row))
        # A latched row is never projected, whoever says what: its money is on the anchor.
        self.assertFalse(proj.is_projectable(Row(3, {}, latch=proj.LATCHED, status="overridden")))


class TestRefunds(unittest.TestCase):
    def test_the_sign_comes_from_the_txn_type_not_the_amount(self):
        """A REFUND whose portal wrote a positive Payment Amount must not project as a
        charge. `-abs()` is idempotent, so a portal that already writes negatives works
        through the same path with no branch."""
        for paid in ("9200.00", "-9200.00"):
            with self.subTest(paid=paid):
                row = flight(1, txn="REFUND", fare="9480.00", paid=paid)
                self.assertEqual(proj.bill_kind(row.data), "refund")
                self.assertEqual(proj.signed_total(row.data), Decimal("-9200.00"))

    def test_a_refund_projects_every_component_negative(self):
        """The export writes Basic Fare and the taxes as positive MAGNITUDES on a REFUND
        line; only Payment Amount is signed. Left as-is, an invoice would show a credit
        with positive tax."""
        (group,) = proj.build_groups(
            [flight(1, txn="REFUND", fare="9480.00", basic="7189.00", tax="2291.00",
                    paid="-9200.00", penalty_amount="280.00")])
        values = proj.ticket_fields(group)
        self.assertEqual(values["total_amt"], Decimal("-9200.00"))
        for column in ("sell_fare", "sell_tax", "sale_k3", "sell_tax_yq",
                       "sale_yr", "other_tax"):
            self.assertLess(values[column], 0, column)
        self.assertEqual(values["transaction_type"], "REFUND")
        # Recorded, not subtracted: the penalty is already netted inside Payment Amount.
        self.assertEqual(values["can_charge"], Decimal("280.00"))

    def test_a_sale_and_a_refund_for_one_passenger_take_their_own_seats(self):
        """The `sign` component of the latch key. One PNR, one passenger, a sale and a
        refund — the PAID_SEAT belongs to the sale and the REFUND_SEAT to the refund, and
        neither is a guess."""
        rows = [flight(1, doc=DOC, txn="PAID_BOOKING"),
                flight(2, doc=DOC2, txn="REFUND", paid="-9200.00"),
                seat(3, txn="PAID_SEAT", amount="975.00"),
                seat(4, txn="REFUND_SEAT", amount="975.00")]
        groups = {g.key: g for g in proj.build_groups(rows)}
        self.assertEqual([ln.id for ln in groups[f"D:{DOC}"].latched], [3])
        self.assertEqual([ln.id for ln in groups[f"C:{DOC2}"].latched], [4])
        self.assertGreater(groups[f"D:{DOC}"].total, 0)
        self.assertLess(groups[f"C:{DOC2}"].total, 0)

    def test_a_ticket_and_its_own_refund_stay_two_lines(self):
        """FOUND IN A REAL AIR INDIA EXPORT, where ten of its groups were this shape.

        A ticket and its reversal carry the SAME document number — TICKETING then REFUND on
        one 13-digit number. Keyed on the number alone they became one group whose total was
        exactly zero, so the customer was neither charged nor credited: the sale disappeared
        and so did the credit note. A sale and its reversal are two transactions on one
        document, and they have to stay two billed lines.
        """
        rows = [flight(1, doc=DOC, txn="TICKETING", fare="9508.00"),
                flight(2, doc=DOC, txn="REFUND", fare="9508.00")]
        groups = {g.key: g for g in proj.build_groups(rows)}
        self.assertEqual(set(groups), {f"D:{DOC}", f"C:{DOC}"})
        self.assertEqual(groups[f"D:{DOC}"].total, Decimal("9508.00"))
        self.assertEqual(groups[f"C:{DOC}"].total, Decimal("-9508.00"))
        # And each keeps the document number, so both reconcile against the airline.
        for key, expected in ((f"D:{DOC}", "SALE"), (f"C:{DOC}", "REFUND")):
            values = proj.ticket_fields(groups[key])
            self.assertEqual(values["ticket_number"], DOC)
            self.assertEqual(values["transaction_type"], expected)

    def test_a_paid_seat_with_its_own_emd_still_latches(self):
        """ALSO FROM THE REAL EXPORT: Air India issues an EMD for a paid seat, so a
        PAID_SEAT line carries its own 13-digit document number. Latching on "has no
        document number" made the roll-up dead code on the very file it was written for —
        the discriminator is `Product`, which is the airline's own word for what was sold.
        The EMD number is kept in the ticket's `raw_data`, so nothing is lost."""
        rows = [flight(1, doc=DOC, txn="TICKETING"),
                Row(2, {**seat(9, txn="PAID_SEAT", amount="975.00").data,
                        "document_no": "0984218616596"})]
        (group,) = proj.build_groups(rows)
        self.assertEqual(group.anchor.id, 1)
        self.assertEqual([ln.id for ln in group.latched], [2])
        self.assertEqual(proj.ticket_fields(group)["seat_selection"], Decimal("975.00"))

    def test_a_refunded_emd_seat_credits_the_refunded_ticket(self):
        """The same file's other half: TICKETING + PAID_SEAT and REFUND + REFUND_SEAT, all
        four on two document numbers. Two lines out, and the seat money on the right one."""
        rows = [flight(1, doc=DOC, txn="TICKETING", fare="9508.00"),
                Row(2, {**seat(9, txn="PAID_SEAT", amount="975.00").data,
                        "document_no": "0984218616596"}),
                flight(3, doc=DOC, txn="REFUND", fare="9508.00"),
                Row(4, {**seat(9, txn="REFUND_SEAT", amount="975.00").data,
                        "document_no": "0984218616596"})]
        groups = {g.key: g for g in proj.build_groups(rows)}
        self.assertEqual(groups[f"D:{DOC}"].total, Decimal("10483.00"))    # 9508 + 975
        self.assertEqual(groups[f"C:{DOC}"].total, Decimal("-10483.00"))

    def test_a_refund_seat_with_no_refund_is_an_orphan(self):
        """It cannot latch onto the sale: that would credit a seat against a charge."""
        groups = proj.build_groups([flight(1, txn="PAID_BOOKING"),
                                    seat(2, txn="REFUND_SEAT", amount="975.00")])
        self.assertEqual(next(g for g in groups if g.key == "O:2").anchor.latch_status,
                         proj.ORPHAN)


class TestAnchorSelection(unittest.TestCase):
    def test_the_anchor_is_the_ticket_line_not_the_ancillary(self):
        rows = [Row(1, {**seat(9).data, "document_no": DOC}, seq=1),
                flight(2, doc=DOC, seq=2)]
        (group,) = proj.build_groups(rows)
        self.assertEqual(group.anchor.id, 2)
        self.assertEqual([ln.id for ln in group.latched], [1])

    def test_the_anchor_does_not_move_when_the_input_order_does(self):
        """Load-bearing, not cosmetic: idempotency is keyed on the anchor's
        `projected_ticket_id`, so an anchor that moved between two runs would orphan one
        ticket and create a second."""
        rows = [flight(1, doc=DOC, fare="1000.00", seq=1),
                flight(2, doc=DOC, fare="7747.00", seq=2),
                flight(3, doc=DOC, fare="500.00", seq=3)]
        forward = proj.build_groups(rows)[0].anchor.id
        backward = proj.build_groups(list(reversed(rows)))[0].anchor.id
        self.assertEqual(forward, backward)
        self.assertEqual(forward, 2)          # the largest amount wins

    def test_a_document_number_is_matched_on_its_digits(self):
        """One export can pad or hyphenate the same number differently on a later coupon
        line. Two spellings would become two tickets and two invoice lines."""
        (group,) = proj.build_groups([flight(1, doc="0982185569174"),
                                      flight(2, doc="098-2185569174 ")])
        self.assertEqual(len(group.lines), 2)


class TestAmounts(unittest.TestCase):
    def test_payment_amount_wins_over_total_fare(self):
        row = flight(1, fare="7747.00", paid="7000.00")
        self.assertEqual(proj.signed_total(row.data), Decimal("7000.00"))

    def test_total_fare_is_the_fallback_for_older_batches(self):
        """`Payment Amount` was not always a column, and NDC has no reprocess path."""
        row = flight(1, fare="7747.00")
        del row.data["payment_amount"]
        self.assertEqual(proj.signed_total(row.data), Decimal("7747.00"))

    def test_an_unreadable_cell_is_none_not_zero(self):
        """A total silently short by one row is the failure this module exists to avoid."""
        row = flight(1, paid="N/A", fare="N/A")
        self.assertIsNone(proj.signed_total(row.data))

    def test_a_zero_settled_figure_is_not_billable(self):
        self.assertEqual(proj.bill_kind(flight(1, fare="0.00", paid="0.00").data), "payment")

    def test_an_unrecognised_txn_type_still_bills(self):
        """Mirrors the ingest filter's drop-list stance — a carrier's type we have never
        seen must not vanish."""
        self.assertEqual(proj.bill_kind(flight(1, txn="VOID").data), "sale")

    def test_the_ticket_total_is_the_sum_of_its_rows(self):
        """The invariant that catches a dropped bucket. If an ancillary stops reaching a
        column, `total_amt` and the sum of the rows behind it come apart — and the invoice
        is wrong in a way no other assertion here would notice."""
        rows = [flight(1), seat(2, amount="975.00"),
                seat(3, product="Baggage", txn="PAID_BOOKING", amount="500.00"),
                seat(4, product="Lounge", txn="PAID_BOOKING", amount="300.00")]
        (group,) = proj.build_groups(rows)
        values = proj.ticket_fields(group)
        self.assertEqual(values["total_amt"], sum(ln.amount for ln in group.lines))
        # And the ancillaries are fully accounted for across the buckets.
        self.assertEqual(sum(group.ancillary_totals().values()), Decimal("1775.00"))

    def test_an_unreadable_ancillary_does_not_void_the_ticket(self):
        (group,) = proj.build_groups([flight(1), seat(2, amount="—")])
        self.assertEqual(group.total, Decimal("7747.00"))
        self.assertIsNone(group.latched[0].amount)


class TestBillingState(unittest.TestCase):
    """`billing_state` in Python and `billing_state_cond` in SQL are one definition written
    twice; these cover the Python half and the two states LCC has no equivalent of."""

    class Ticket:
        def __init__(self, billing_id=None, party=(None, None, None)):
            self.billing_id = billing_id
            self.customer_type, self.customer_id, self.corporate_id = party

    def row(self, **kw):
        r = Row(1, {}, **kw)
        r.bill_customer_type = kw.get("ct")
        r.bill_customer_id = kw.get("cid")
        r.bill_corporate_id = kw.get("corp")
        return r

    def test_a_latched_row_reports_latched_and_is_never_sendable(self):
        state = proj.billing_state(self.row(latch=proj.LATCHED, status="resolved"), None)
        self.assertEqual(state, "latched")
        self.assertNotIn(state, proj.SENDABLE_STATES)

    def test_an_unlatched_ancillary_reports_unlatched_until_it_has_a_party(self):
        self.assertEqual(
            proj.billing_state(self.row(latch=proj.ORPHAN, status="unresolved"), None),
            "unlatched")
        self.assertEqual(
            proj.billing_state(self.row(latch=proj.ORPHAN, status="overridden"), None),
            "ready")

    def test_invoiced_beats_latched(self):
        """Every row in a group shares one ticket, so a latched row is frozen the moment
        its anchor's ticket is invoiced — and has to say so."""
        row = self.row(latch=proj.LATCHED, status="resolved")
        self.assertEqual(proj.billing_state(row, self.Ticket(billing_id=7)), "invoiced")

    def test_a_payment_row_is_not_billable(self):
        self.assertEqual(
            proj.billing_state(self.row(latch=proj.ANCHOR, status="resolved", kind="payment"), None),
            "not_billable")

    def test_a_vanished_ticket_falls_back_rather_than_claiming_to_be_in_billing(self):
        """`projected_ticket_id` is ON DELETE SET NULL, so the ticket can go underneath."""
        self.assertEqual(
            proj.billing_state(self.row(latch=proj.ANCHOR, status="resolved"), None), "ready")

    def test_only_ready_and_stale_are_sendable(self):
        """`sent` is absent on purpose: a row already in billing has nothing left to send,
        and ticking it produced a no-op update reported as "1 updated"."""
        self.assertEqual(proj.SENDABLE_STATES, ("ready", "stale"))
        for state in ("invoiced", "not_billable", "latched", "unlatched", "no_party",
                      "withdrawn", "sent"):
            self.assertNotIn(state, proj.SENDABLE_STATES)

    def test_every_state_has_a_sql_twin(self):
        """A state with no condition cannot be filtered on, and the worklist's dropdown
        would silently return the unfiltered set."""
        from sqlalchemy.orm import aliased
        from app.models.uploaded_ticket import UploadedTicket

        T = aliased(UploadedTicket)
        for state in (*proj.BILLING_STATES, "sendable"):
            self.assertIsNotNone(proj.billing_state_cond(state, T), state)
        self.assertIsNone(proj.billing_state_cond("not_a_state", T))


if __name__ == "__main__":
    unittest.main()
