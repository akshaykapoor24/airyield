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
    BILLING_STATES, SENDABLE_STATES, billing_state, file_pax, row_pax,
)


class FakeRow:
    """The LccDetailed columns billing_state reads. Has money to bill unless told otherwise —
    a row with none is a payment movement (`total=0`)."""

    def __init__(self, **kw):
        self.__dict__.update({
            "bill_kind": "sale",
            "total": 100.0,
            "payment_amount": None,
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
        self.assertEqual(billing_state(FakeRow(total=0), None), "not_billable")
        self.assertEqual(billing_state(FakeRow(total=None), None), "not_billable")

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
                    FakeRow(total=0)):                      # would be not_billable
            self.assertEqual(billing_state(row, FakeTicket(billing_id=7)), "invoiced")

    # ── the NULL traps ───────────────────────────────────────────────────────
    def test_null_bill_kind_is_not_a_payment(self):
        # Billing reads the money, never bill_kind, so a row whose kind was never set is
        # still billable when it has an amount — in SQL `NULL != 'payment'` would have
        # dropped it silently.
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
            billing_state(FakeRow(total=0), None),
            billing_state(FakeRow(bill_status="unresolved"), None),
            billing_state(FakeRow(), None),
            billing_state(FakeRow(bill_status="unresolved"), FakeTicket()),
            billing_state(FakeRow(), FakeTicket(customer_id=2)),
            billing_state(FakeRow(), FakeTicket()),
        }
        self.assertEqual(produced, set(BILLING_STATES))

    def test_sendable_is_exactly_the_states_a_send_would_act_on(self):
        self.assertEqual(set(SENDABLE_STATES), {"ready", "stale"})
        for state in SENDABLE_STATES:
            self.assertIn(state, BILLING_STATES)

    def test_a_row_already_in_billing_cannot_be_sent_again(self):
        """`sent` is not sendable, and that is the whole rule.

        Re-sending it was a no-op that still reported "1 updated", so the screen
        let a user send the same row for ever and told them something had
        happened each time. Once a row is in billing the ticket is what exists,
        and its party is changed from Billing (Sold Tickets) instead.
        """
        self.assertNotIn("sent", SENDABLE_STATES)

    def test_stale_stays_sendable_so_a_divergence_can_be_reconciled(self):
        """`stale` is NOT "already sent" — it is billing and the row disagreeing
        about the party, and sending is the only thing that reconciles them."""
        self.assertIn("stale", SENDABLE_STATES)


class PaxTests(unittest.TestCase):
    """A fixed markup is charged per passenger, so the pax is a price input."""

    def test_the_statement_figure_is_used(self):
        self.assertEqual(file_pax(FakeRow(pax_count=3)), 3)
        self.assertEqual(row_pax(FakeRow(pax_count=3, bill_pax_count=None)), 3)

    def test_a_blank_zero_or_absurd_pax_is_one_passenger(self):
        """Never 0 — it would zero the fixed markup with nothing on screen to say why."""
        for raw in (None, 0, -1, 150):
            with self.subTest(raw=raw):
                self.assertEqual(row_pax(FakeRow(pax_count=raw, bill_pax_count=None)), 1)

    def test_a_correction_beats_the_statement(self):
        self.assertEqual(row_pax(FakeRow(pax_count=9, bill_pax_count=2)), 2)

    def test_a_row_with_no_pax_attributes_is_one_passenger(self):
        self.assertEqual(row_pax(FakeRow()), 1)

    def test_a_ticket_sent_with_a_different_pax_is_stale(self):
        row = FakeRow(pax_count=3, bill_pax_count=None)
        self.assertEqual(billing_state(row, FakeTicket(pax_count=1)), "stale")
        self.assertEqual(billing_state(row, FakeTicket(pax_count=3)), "sent")

    def test_correcting_the_pax_of_a_sent_row_makes_it_stale(self):
        row = FakeRow(pax_count=3, bill_pax_count=2)
        self.assertEqual(billing_state(row, FakeTicket(pax_count=3)), "stale")

    def test_every_state_still_has_a_sql_twin(self):
        from sqlalchemy.orm import aliased
        from app.models.uploaded_ticket import UploadedTicket
        from app.services.lcc_billing_projection import billing_state_cond
        T = aliased(UploadedTicket)
        for state in (*BILLING_STATES, "sendable"):
            with self.subTest(state=state):
                self.assertIsNotNone(billing_state_cond(state, T))


class AgOnlyTests(unittest.TestCase):
    """Only a row paid from the agency account — PaymentMethodCode AG — is billed."""

    def test_ag_is_billed_however_the_file_spells_it(self):
        from app.services.lcc_billing_projection import is_ag
        for code in ("AG", "ag", " AG ", "Ag"):
            with self.subTest(code=code):
                self.assertTrue(is_ag(FakeRow(payment_method_code=code)))

    def test_any_other_or_blank_code_is_not(self):
        # EI / EM / EV / PT are the codes a real IndiGo statement carries besides AG; a
        # blank one is a row with no payment on it at all (PaymentAmount 0).
        from app.services.lcc_billing_projection import is_ag
        for code in ("PT", "EI", "EM", "EV", "AGX", "", "   ", None):
            with self.subTest(code=code):
                self.assertFalse(is_ag(FakeRow(payment_method_code=code)))

    def test_a_row_with_no_payment_method_attribute_is_not_ag(self):
        from app.services.lcc_billing_projection import is_ag
        self.assertFalse(is_ag(FakeRow()))

    def test_the_sql_twin_is_null_safe(self):
        """Without the COALESCE a NULL code makes the predicate NULL, and `NOT (NULL)` is
        NULL too — so a blank-code row would vanish from BOTH sides of the split, and the
        "N rows left out" count would miss it."""
        from sqlalchemy.dialects import postgresql
        from app.services.lcc_billing_projection import ag_cond
        sql = str(ag_cond().compile(dialect=postgresql.dialect(),
                                    compile_kwargs={"literal_binds": True})).lower()
        self.assertIn("coalesce(lcc_detailed.payment_method_code", sql)
        self.assertIn("'ag'", sql)

    def test_the_rule_is_the_merge_rule(self):
        # One definition: the two-file import drops non-AG rows with the same constant.
        from app.services.lcc_merge import AG_PAYMENT_METHOD
        self.assertEqual(AG_PAYMENT_METHOD, "AG")


class BillAmountTests(unittest.TestCase):
    """An AG line bills what was paid on it — PaymentAmount, else Total.

    The shapes below are taken from a real 203-row IndiGo statement, where 51 of the 160
    AG lines have Total 0 and their money in PaymentAmount.
    """

    def test_an_ag_payment_line_bills_its_payment(self):
        from app.services.lcc_billing_projection import bill_amount, billing_kind
        row = FakeRow(bill_kind="payment", total=0, payment_amount=10670)
        self.assertEqual(bill_amount(row), 10670)
        self.assertEqual(billing_kind(row), "sale")
        self.assertEqual(billing_state(row, None), "ready")

    def test_a_negative_payment_is_a_refund(self):
        from app.services.lcc_billing_projection import billing_kind
        self.assertEqual(billing_kind(FakeRow(total=0, payment_amount=-998)), "refund")

    def test_a_refund_paid_in_two_parts_bills_each_part_once(self):
        # HEDZ4K: a -6389 refund repaid as -5097 on its fare line plus -1292 on a line of
        # its own. Billing Total on the first would count the -1292 twice.
        from app.services.lcc_billing_projection import bill_amount
        lines = [FakeRow(total=-6389, payment_amount=-5097), FakeRow(total=0, payment_amount=-1292)]
        self.assertEqual(sum(bill_amount(r) for r in lines), -6389)

    def test_ordinary_line_where_both_agree(self):
        from app.services.lcc_billing_projection import bill_amount
        self.assertEqual(bill_amount(FakeRow(total=5529, payment_amount=5529)), 5529)

    def test_no_payment_amount_falls_back_to_total(self):
        # The two-file merge (Air India Express) puts the money in Total and leaves
        # PaymentAmount unmapped.
        from app.services.lcc_billing_projection import bill_amount
        self.assertEqual(bill_amount(FakeRow(total=-5516, payment_amount=None)), -5516)
        self.assertEqual(bill_amount(FakeRow(total=-5516, payment_amount=0)), -5516)

    def test_no_money_at_all_is_a_payment_movement(self):
        from app.services.lcc_billing_projection import billing_kind, is_payment_row
        for total, paid in ((0, 0), (None, None), (0, None)):
            with self.subTest(total=total, paid=paid):
                row = FakeRow(total=total, payment_amount=paid)
                self.assertEqual(billing_kind(row), "payment")
                self.assertTrue(is_payment_row(row))

    def test_the_sql_twins_compile_null_safe(self):
        from sqlalchemy.dialects import postgresql
        from app.services.lcc_billing_projection import billing_kind_cond, not_payment_cond
        sql = str(not_payment_cond().compile(dialect=postgresql.dialect())).lower()
        self.assertIn("coalesce", sql)
        self.assertIn("payment_amount", sql)
        for kind in ("sale", "refund", "payment"):
            self.assertIsNotNone(billing_kind_cond(kind))
        self.assertIsNone(billing_kind_cond("nonsense"))


class BuildTicketTests(unittest.TestCase):
    """What a billed ticket carries. `total_amt` is the price billing marks up."""

    @staticmethod
    def _ticket(**kw):
        from datetime import datetime
        from types import SimpleNamespace
        from app.services.lcc_billing_projection import _build_ticket
        row = FakeRow(**{
            "id": 1, "batch_id": "b", "tenant_id": 1, "created_by_id": 1, "name1": "SUJOYTA GHOSH",
            "base_fare": 0, "taxes_total": None, "other_fee_total": 0, "other_ssr_total": 0,
            "taxes": [{"code": "UDF", "amount": 923}], "segments": None, "record_locator": "UIF9SE",
            "gds_record_locator": None, "parent_pnr": None, "airline_name": "6E INDIGO",
            "airline_code": "6E", "product_class": "F", "international": False,
            "transaction_date": None, "departure_date": None, "pax_count": 2,
            "bill_pax_count": None, "bill_match_reason": None, **kw,
        })
        batch = SimpleNamespace(billing_batch_id="bb", source_file="indigolccStat.csv")
        return _build_ticket(row, batch, now=datetime(2026, 10, 1))

    def test_an_ag_payment_line_bills_the_payment_without_a_fare_it_does_not_have(self):
        t = self._ticket(total=0, payment_amount=10670)
        self.assertEqual(t["total_amt"], 10670)
        self.assertEqual(t["transaction_type"], "SALE")
        # Its zero fare would read as "the fare was nothing" beside ₹10,670.
        self.assertIsNone(t["sell_fare"])
        self.assertIsNone(t["tax_breakup"])

    def test_a_refund_payment_projects_as_a_refund(self):
        self.assertEqual(self._ticket(total=0, payment_amount=-998)["transaction_type"], "REFUND")

    def test_an_ordinary_line_keeps_its_breakdown(self):
        t = self._ticket(total=5529, payment_amount=5529, base_fare=3573)
        self.assertEqual(t["total_amt"], 5529)
        self.assertEqual(t["sell_fare"], 3573)
        self.assertEqual(t["tax_breakup"], {"UDF": 923})


if __name__ == "__main__":
    unittest.main()
