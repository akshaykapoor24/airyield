"""Payment Module steps 10–13: what is payable, who decided it, and what stays outstanding.

The rules that decide money leaving the business:

  * a duplicate is excluded automatically (step 6B) — never paid by default;
  * nothing auto-approves before income is calculated, or while income needs data;
  * a clean match auto-approves at the payable after commission;
  * anything else waits for Operations, with the reason spelled out;
  * a person's decision survives re-runs; rule-based amounts follow the figures, a custom
    amount does not; a paid ticket cannot be re-decided.

No DB, no network.  Run:  ..\\venv\\Scripts\\python.exe -m pytest test_payment_ledger.py
"""
from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.payment_ledger import (  # noqa: E402
    DECISION_APPROVED, DECISION_EXCLUDED, DECISION_HELD, DECISION_PENDING, PaymentItem,
)
from app.services.payment_ledger import (  # noqa: E402
    ACTION_AUTO, LedgerError, amount_for, auto_decision, decide, payment_total,
)

D = Decimal


def snap(**over) -> dict:
    """A clean, matched, priced ticket: vendor net 1303, shortfall 45 → payable 1258."""
    base = {"is_duplicate": False, "duplicate_info": None, "commission_ran": True,
            "income_needs_data": False, "match_status": "matched", "not_billed": False,
            "mo_vendor_status": "ok", "mo_vendor_info": None, "net_variance": 0.0,
            "vendor_net": 1303.0, "suggested_payable": 1258.0}
    base.update(over)
    return base


def item(**over) -> PaymentItem:
    base = dict(id=1, tenant_id=9, created_by_id=14, vendor_batch_id="b", ticket_key="k:1",
                ticket_number="5808758786", vendor_net=D("1303"), mo_net=D("1300"),
                suggested_payable=D("1258"), match_status="minor_diff", is_duplicate=False,
                not_billed=False, mo_vendor_status="ok", commission_ran=True,
                income_needs_data=False, decision_status=DECISION_PENDING,
                decision_source="auto", payment_id=None)
    base.update(over)
    return PaymentItem(**base)


class TestAutoDecision(unittest.TestCase):

    def test_a_clean_match_is_approved_at_the_payable_after_commission(self):
        status, action, amount, _ = auto_decision(snap())
        self.assertEqual((status, action, amount), (DECISION_APPROVED, "auto_clean", D("1258.0")))

    def test_a_duplicate_is_excluded_even_when_it_matches(self):
        status, action, amount, reason = auto_decision(snap(
            is_duplicate=True, duplicate_info={"kind": "earlier", "source_file": "08-15.xlsx",
                                               "paid": True}))
        self.assertEqual((status, action, amount), (DECISION_EXCLUDED, "auto_duplicate", None))
        self.assertIn("08-15.xlsx", reason)
        self.assertIn("paid", reason)

    def test_nothing_is_approved_before_income_is_calculated(self):
        status, _a, amount, reason = auto_decision(snap(commission_ran=False))
        self.assertEqual((status, amount), (DECISION_PENDING, None))
        self.assertIn("Calculate income", reason)

    def test_income_that_needs_data_waits(self):
        self.assertEqual(auto_decision(snap(income_needs_data=True))[0], DECISION_PENDING)

    def test_a_net_difference_waits_with_the_amount_in_the_reason(self):
        status, _a, _amt, reason = auto_decision(snap(match_status="mismatch", net_variance=500.0))
        self.assertEqual(status, DECISION_PENDING)
        self.assertIn("₹500.00", reason)

    def test_vendor_only_wrong_vendor_and_not_billed_each_wait(self):
        for over, phrase in (
            ({"match_status": "vendor_only"}, "not in the MO statement"),
            ({"mo_vendor_status": "other_vendor", "mo_vendor_info": {"supplier_name": "Riya"}},
             "Riya"),
            ({"not_billed": True}, "booking ID"),
        ):
            with self.subTest(over=over):
                status, _a, _amt, reason = auto_decision(snap(**over))
                self.assertEqual(status, DECISION_PENDING)
                self.assertIn(phrase, reason)

    def test_a_corrected_mo_vendor_is_clean(self):
        self.assertEqual(auto_decision(snap(mo_vendor_status="corrected"))[0], DECISION_APPROVED)

    def test_no_shortfall_figure_falls_back_to_the_vendor_net(self):
        self.assertEqual(auto_decision(snap(suggested_payable=None))[2], D("1303.0"))


class TestOperationsDecision(unittest.TestCase):

    def test_pay_mo_amount(self):
        i = item()
        decide(i, action="pay_mo", user_id=14, ops_reference="OPS-17")
        self.assertEqual((i.decision_status, i.decision_source, i.approved_amount),
                         (DECISION_APPROVED, "user", D("1300")))
        self.assertEqual(i.ops_reference, "OPS-17")

    def test_custom_amount_needs_an_amount_and_a_remark(self):
        with self.assertRaises(LedgerError):
            decide(item(), action="pay_custom", user_id=14, remarks="agreed")
        with self.assertRaises(LedgerError):
            decide(item(), action="pay_custom", user_id=14, amount=D("1290"))
        i = item()
        decide(i, action="pay_custom", user_id=14, amount=D("1290"), remarks="agreed by ops")
        self.assertEqual(i.approved_amount, D("1290"))

    def test_hold_and_exclude_carry_no_amount_and_need_a_remark(self):
        with self.assertRaises(LedgerError):
            decide(item(), action="hold", user_id=14)
        i = item()
        decide(i, action="hold", user_id=14, remarks="vendor to confirm fare")
        self.assertEqual((i.decision_status, i.approved_amount), (DECISION_HELD, None))
        decide(i, action="exclude", user_id=14, remarks="not ours")
        self.assertEqual(i.decision_status, DECISION_EXCLUDED)

    def test_a_paid_ticket_cannot_be_re_decided(self):
        with self.assertRaises(LedgerError):
            decide(item(payment_id=5), action="hold", user_id=14, remarks="x")

    def test_pay_mo_without_an_mo_side_is_refused(self):
        with self.assertRaises(LedgerError):
            decide(item(mo_net=None), action="pay_mo", user_id=14)

    def test_reverting_to_automatic_reapplies_the_rules(self):
        i = item(match_status="matched", decision_source="user", decision_status=DECISION_HELD)
        decide(i, action=ACTION_AUTO, user_id=14)
        self.assertEqual((i.decision_source, i.decision_status, i.approved_amount),
                         ("auto", DECISION_APPROVED, D("1258")))

    def test_unknown_action_is_refused(self):
        with self.assertRaises(LedgerError):
            decide(item(), action="pay_double", user_id=14)


class TestAmounts(unittest.TestCase):

    def test_rule_based_amounts_follow_the_current_figures(self):
        i = item()
        self.assertEqual(amount_for(i, "pay_suggested"), D("1258"))
        self.assertEqual(amount_for(i, "pay_vendor"), D("1303"))
        i.vendor_net = D("1400")
        self.assertEqual(amount_for(i, "pay_vendor"), D("1400"))

    def test_a_custom_amount_is_kept(self):
        i = item(approved_amount=D("999"))
        self.assertEqual(amount_for(i, "pay_custom"), D("999"))
        self.assertIsNone(amount_for(i, "hold"))


class TestPaymentTotal(unittest.TestCase):
    """Step 12: tickets are paid in full, together, by one vendor — and only for money owed."""

    def approved(self, id_, amount, **over):
        return item(**{"id": id_, "ticket_key": f"k:{id_}", "decision_status": DECISION_APPROVED,
                       "approved_amount": D(amount), "supplier_id": 751, **over})

    def test_approved_tickets_add_up(self):
        self.assertEqual(payment_total([self.approved(1, "1258"), self.approved(2, "-200")], 751),
                         D("1058"))

    def test_refunds_outweighing_sales_are_not_a_payment(self):
        # The 08-15 statement nets to a credit: carried forward, never "paid".
        with self.assertRaises(LedgerError) as e:
            payment_total([self.approved(1, "-268999.01")])
        self.assertIn("nothing to pay", str(e.exception))
        with self.assertRaises(LedgerError):
            payment_total([self.approved(1, "500"), self.approved(2, "-500")])

    def test_held_paid_or_mixed_vendor_tickets_are_refused(self):
        with self.assertRaises(LedgerError):
            payment_total([self.approved(1, "10"), item(id=2, decision_status=DECISION_HELD)])
        with self.assertRaises(LedgerError):
            payment_total([self.approved(1, "10", payment_id=7)])
        with self.assertRaises(LedgerError):
            payment_total([self.approved(1, "10"), self.approved(2, "10", supplier_id=12)])
        with self.assertRaises(LedgerError):
            payment_total([self.approved(1, "10")], supplier_id=12)


if __name__ == "__main__":
    unittest.main()
