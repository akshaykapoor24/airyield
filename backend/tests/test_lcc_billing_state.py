"""Where an LCC row stands on its way into billing.

`billing_state` is the one place that decides what the worklist's Billing column says,
and its answers drive real money: a row it calls `sent` will not be re-sent, and a row it
calls `invoiced` will never be touched again. The two cases worth guarding are the ones
SQL and Python disagree about — a NULL `bill_kind`, and a NULL corporate id on both sides
of the party comparison.

No DB, no network — billing_state is pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.lcc_billing_projection import (  # noqa: E402
    BILLING_STATES, SENDABLE_STATES, billing_state,
)


class FakeRow:
    """The five LccDetailed columns billing_state reads."""

    def __init__(self, **kw):
        self.__dict__.update({
            "bill_kind": "sale",
            "bill_status": "resolved",
            "bill_customer_type": "direct",
            "bill_customer_id": 1,
            "bill_corporate_id": None,
            **kw,
        })


class FakeTicket:
    """The four UploadedTicket columns billing_state reads. Defaults agree with FakeRow."""

    def __init__(self, **kw):
        self.__dict__.update({
            "billing_id": None,
            "customer_type": "direct",
            "customer_id": 1,
            "corporate_id": None,
            **kw,
        })


class BillingStateTests(unittest.TestCase):

    # ── not yet in billing ───────────────────────────────────────────────────
    def test_billable_row_with_no_ticket_is_ready(self):
        self.assertEqual(billing_state(FakeRow(), None), "ready")

    def test_a_human_override_is_also_ready(self):
        self.assertEqual(billing_state(FakeRow(bill_status="overridden"), None), "ready")

    def test_unmatched_row_with_no_ticket_needs_a_party(self):
        self.assertEqual(billing_state(FakeRow(bill_status="unresolved"), None), "no_party")

    def test_ambiguous_counts_as_no_party(self):
        # "Several customers share this name" is not a party, however close it looks.
        self.assertEqual(billing_state(FakeRow(bill_status="ambiguous"), None), "no_party")

    def test_payment_movement_is_never_billable(self):
        self.assertEqual(billing_state(FakeRow(bill_kind="payment"), None), "not_billable")

    # ── in billing ───────────────────────────────────────────────────────────
    def test_projected_row_whose_party_still_agrees_is_sent(self):
        self.assertEqual(billing_state(FakeRow(), FakeTicket()), "sent")

    def test_corporate_party_matches_on_the_whole_triple(self):
        row = FakeRow(bill_customer_type="corporate", bill_corporate_id=9)
        ticket = FakeTicket(customer_type="corporate", corporate_id=9)
        self.assertEqual(billing_state(row, ticket), "sent")

    def test_party_changed_after_sending_is_stale(self):
        self.assertEqual(billing_state(FakeRow(), FakeTicket(customer_id=2)), "stale")

    def test_type_change_alone_is_stale(self):
        # Same customer_id, different type — billing would bill the wrong entity.
        row = FakeRow(bill_customer_type="corporate", bill_corporate_id=9)
        self.assertEqual(billing_state(row, FakeTicket()), "stale")

    def test_party_cleared_after_sending_is_withdrawn(self):
        self.assertEqual(
            billing_state(FakeRow(bill_status="unresolved"), FakeTicket()), "withdrawn"
        )

    # ── frozen ───────────────────────────────────────────────────────────────
    def test_invoiced_row_is_invoiced(self):
        self.assertEqual(billing_state(FakeRow(), FakeTicket(billing_id=7)), "invoiced")

    def test_invoiced_beats_every_other_state(self):
        # Once a ticket is on an invoice nothing the row now says can move it, so the
        # column must not offer a state that implies otherwise.
        for row in (FakeRow(bill_status="unresolved"),      # would be withdrawn
                    FakeRow(bill_customer_id=2),            # would be stale
                    FakeRow(bill_kind="payment")):          # would be not_billable
            self.assertEqual(billing_state(row, FakeTicket(billing_id=7)), "invoiced")

    # ── the NULL traps ───────────────────────────────────────────────────────
    def test_null_bill_kind_is_not_a_payment(self):
        # An imported-but-never-resolved row has bill_kind NULL. In SQL
        # `NULL != 'payment'` is NULL, which drops the row silently; Python must agree
        # with the NULL-safe predicate, not with the naive one.
        self.assertEqual(billing_state(FakeRow(bill_kind=None), None), "ready")
        self.assertEqual(
            billing_state(FakeRow(bill_kind=None, bill_status="unresolved"), None),
            "no_party",
        )

    def test_two_null_corporate_ids_are_a_match_not_a_difference(self):
        # `NULL = NULL` is NULL in SQL, which would report every direct-billed row as
        # stale. Both sides null here, and the row must read `sent`.
        row = FakeRow(bill_corporate_id=None)
        self.assertEqual(billing_state(row, FakeTicket(corporate_id=None)), "sent")

    # ── the FK that went away ────────────────────────────────────────────────
    def test_nulled_projection_falls_back_rather_than_claiming_billing(self):
        # projected_ticket_id is ON DELETE SET NULL, so the ticket can vanish underneath
        # the row. It must not keep reporting itself as in billing.
        self.assertEqual(billing_state(FakeRow(), None), "ready")

    # ── the vocabulary itself ────────────────────────────────────────────────
    def test_every_declared_state_is_reachable(self):
        produced = {
            billing_state(FakeRow(), FakeTicket(billing_id=7)),
            billing_state(FakeRow(bill_kind="payment"), None),
            billing_state(FakeRow(bill_status="unresolved"), None),
            billing_state(FakeRow(), None),
            billing_state(FakeRow(bill_status="unresolved"), FakeTicket()),
            billing_state(FakeRow(), FakeTicket(customer_id=2)),
            billing_state(FakeRow(), FakeTicket()),
        }
        self.assertEqual(produced, set(BILLING_STATES))

    def test_sendable_is_exactly_the_states_a_send_would_act_on(self):
        self.assertEqual(set(SENDABLE_STATES), {"ready", "sent", "stale"})
        for state in SENDABLE_STATES:
            self.assertIn(state, BILLING_STATES)


if __name__ == "__main__":
    unittest.main()
