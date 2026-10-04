"""Payment Module steps 2, 3 and 5: is a loaded statement complete, and is it the vendor's?

Each check is a sentence a person acts on, so the tests pin both the verdict and the reason:

  * rows      — file lines = rows saved = rows present; a deletion after upload is caught;
  * amount    — opening + Σ net = closing, the statement's own arithmetic (±₹1);
  * continuity— this opening = the previous statement's closing, same vendor;
  * controls  — the expected record count / amount the uploader declared;
  * vendor    — the file's Customer ID is the vendor's confirmed account, not another's.

Plus the ingest side: the OLD line is read off the preamble, the BALANCE line is stamped.

No DB, no network.  Run:  ..\\venv\\Scripts\\python.exe -m pytest test_statement_checks.py
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import statement_balance  # noqa: E402
from app.services.statement_checks import (  # noqa: E402
    FAIL, NA, PASS, WARN, BatchFacts, check_amount, check_continuity, check_controls,
    check_rows, check_vendor, copy_of, evaluate, normalize_account, previous_of,
    same_statement, verdict,
)

D = Decimal

REAL_STATEMENT = os.environ.get(
    "TP_GDS_SAMPLE",
    r"C:\Users\manve\OneDrive\Desktop\FareQube Docs\TriumphTravel"
    r"\TRIUMPHH BSP STATEMENT 16-22ND AUG 26.xlsx",
)


def facts(**over) -> BatchFacts:
    """The real 16-22 Aug statement's figures: 37 tickets + BALANCE, opening 627,257."""
    base = dict(slug="tp-gds", batch_id="b2", source_file="16-22.xlsx",
                uploaded_at=datetime(2026, 9, 29, 9, 46), supplier_id=751,
                supplier_name="Globe Air Travels", rows_now=38, ticket_rows=37,
                ticket_net=D("333171.4262"), period_from="2026-08-16", period_to="2026-08-22",
                opening=D("627257"), opening_source="file", closing=D("960428.4259999999"),
                file_rows=38, loaded_rows=38,
                accounts={"2102611": ("TRIUMPHH TRAVEL N MORE PRIVATE", 37)})
    base.update(over)
    return BatchFacts(**base)


class TestRows(unittest.TestCase):

    def test_everything_saved_and_present_passes(self):
        c = check_rows(facts())
        self.assertEqual(c["status"], PASS)
        self.assertIn("37 tickets + 1 balance line", c["detail"])

    def test_rows_deleted_after_upload_fail(self):
        c = check_rows(facts(rows_now=36))
        self.assertEqual(c["status"], FAIL)
        self.assertIn("38 rows were saved", c["detail"])

    def test_lines_the_file_had_but_did_not_load_warn(self):
        self.assertEqual(check_rows(facts(file_rows=40))["status"], WARN)

    def test_an_upload_from_before_controls_is_not_judged(self):
        self.assertEqual(check_rows(facts(file_rows=None, loaded_rows=None))["status"], NA)


class TestAmount(unittest.TestCase):

    def test_the_real_statement_closes_exactly(self):
        c = check_amount(facts())
        self.assertEqual(c["status"], PASS, c["detail"])

    def test_a_missing_ticket_breaks_the_identity(self):
        c = check_amount(facts(ticket_net=D("333171.4262") - D("64305")))
        self.assertEqual(c["status"], FAIL)
        self.assertIn("missing or extra", c["detail"])

    def test_a_rupee_of_rounding_is_tolerated(self):
        self.assertEqual(check_amount(facts(closing=D("960429.40")))["status"], PASS)

    def test_no_opening_asks_for_one(self):
        c = check_amount(facts(opening=None))
        self.assertEqual(c["status"], NA)
        self.assertTrue(c.get("needs_opening"))

    def test_no_balance_line_cannot_be_judged(self):
        self.assertEqual(check_amount(facts(closing=None))["status"], NA)


class TestContinuity(unittest.TestCase):

    def test_opening_equals_the_previous_closing(self):
        # The real chain: 08-15 closed at 627,257.41; 16-22 opens at 627,257.
        prev = facts(batch_id="b1", source_file="08-15.xlsx", closing=D("627257.41"),
                     period_to="2026-08-15")
        self.assertEqual(check_continuity(facts(), prev)["status"], PASS)

    def test_a_gap_says_a_statement_may_be_missing(self):
        prev = facts(batch_id="b0", source_file="01-07.xlsx", closing=D("100000"),
                     period_to="2026-08-07")
        c = check_continuity(facts(), prev)
        self.assertEqual(c["status"], FAIL)
        self.assertIn("may not be loaded", c["detail"])

    def test_the_first_statement_has_nothing_to_chain_to(self):
        self.assertEqual(check_continuity(facts(), None)["status"], NA)

    def test_previous_is_the_same_vendors_latest_earlier_statement(self):
        f = facts()
        # Distinct closings: identical figures throughout would make them copies of `f`.
        a = facts(batch_id="a", period_to="2026-08-07", closing=D("100000"))
        b = facts(batch_id="b", period_to="2026-08-15", closing=D("627257.41"))
        other_vendor = facts(batch_id="c", period_to="2026-08-20", supplier_id=999)
        later = facts(batch_id="d", period_to="2026-08-31")
        self.assertEqual(previous_of(f, [a, b, other_vendor, later, f]).batch_id, "b")


class TestSameStatementTwice(unittest.TestCase):
    """The 16-22 statement uploaded a second time is a copy, not a statement in a chain."""

    ORIGINAL = dict(batch_id="b1", uploaded_at=datetime(2026, 9, 29, 9, 0))
    AUG_08_15 = dict(batch_id="a", source_file="08-15.xlsx", period_from="2026-08-08",
                     period_to="2026-08-15", ticket_rows=34, ticket_net=D("120000"),
                     closing=D("627257.41"), uploaded_at=datetime(2026, 9, 28))

    def test_a_second_upload_of_the_same_statement_is_its_copy(self):
        original, again = facts(**self.ORIGINAL), facts()
        self.assertEqual(copy_of(again, [original, again]).batch_id, "b1")
        self.assertIsNone(copy_of(original, [original, again]), "the first upload is the original")

    def test_a_copy_warns_instead_of_reporting_a_missing_statement(self):
        original, again = facts(**self.ORIGINAL), facts()
        c = check_continuity(again, None, copy=original)
        self.assertEqual(c["status"], WARN)
        self.assertIn("loaded twice", c["detail"])
        self.assertIn("duplicates", c["detail"], "a vendor copy is flagged in Reconciliation")
        mo = check_continuity(facts(slug="mo-gds"), None, copy=original)
        self.assertNotIn("duplicates", mo["detail"])

    def test_a_copy_is_not_the_predecessor_the_statement_before_is(self):
        before, original, again = facts(**self.AUG_08_15), facts(**self.ORIGINAL), facts()
        prev = previous_of(again, [before, original, again])
        self.assertEqual(prev.batch_id, "a")
        self.assertEqual(check_continuity(again, prev)["status"], PASS)

    def test_consecutive_statements_are_not_copies_even_when_their_dates_overlap(self):
        # A refund in 16-22 carries its 10 Aug issue date, so the periods overlap.
        self.assertFalse(same_statement(facts(**self.AUG_08_15), facts(period_from="2026-08-10")))

    def test_without_balances_the_same_tickets_over_the_same_days_are_a_copy(self):
        a, b = facts(closing=None, batch_id="x"), facts(closing=None)
        self.assertTrue(same_statement(a, b))
        self.assertFalse(same_statement(a, facts(closing=None, period_to="2026-08-23")))

    def test_evaluate_reports_the_copy(self):
        out = evaluate(facts(), None, {751: {"2102611"}}, {}, copy=facts(**self.ORIGINAL))
        self.assertEqual(out["verdict"], "attention")


class TestControls(unittest.TestCase):

    def test_none_entered(self):
        self.assertEqual(check_controls(facts())["status"], NA)

    def test_matching_controls_pass(self):
        c = check_controls(facts(expected_count=37, expected_amount=D("333171.43")))
        self.assertEqual(c["status"], PASS)

    def test_a_short_count_fails(self):
        c = check_controls(facts(expected_count=40))
        self.assertEqual(c["status"], FAIL)
        self.assertIn("expected 40 records, loaded 37", c["detail"].lower())


class TestVendor(unittest.TestCase):

    def test_confirmed_account_passes(self):
        c = check_vendor(facts(), {751: {"2102611"}}, {})
        self.assertEqual(c["status"], PASS)

    def test_first_statement_asks_to_confirm(self):
        c = check_vendor(facts(), {}, {})
        self.assertEqual(c["status"], WARN)
        self.assertTrue(c["confirmable"])

    def test_another_vendors_confirmed_account_is_the_wrong_vendor(self):
        c = check_vendor(facts(), {12: {"2102611"}}, {})
        self.assertEqual(c["status"], FAIL)
        self.assertIn("wrong vendor", c["detail"])

    def test_an_account_seen_on_another_vendors_statements_fails(self):
        c = check_vendor(facts(), {}, {"2102611": {"Riya Travels"}})
        self.assertEqual(c["status"], FAIL)
        self.assertIn("Riya Travels", c["detail"])

    def test_a_different_account_from_the_confirmed_one_fails(self):
        c = check_vendor(facts(), {751: {"9999"}}, {})
        self.assertEqual(c["status"], FAIL)

    def test_a_file_mixing_accounts_fails(self):
        c = check_vendor(facts(accounts={"1": ("A", 3), "2": ("B", 4)}), {}, {})
        self.assertEqual(c["status"], FAIL)

    def test_no_customer_id_cannot_be_verified(self):
        self.assertEqual(check_vendor(facts(accounts={}), {}, {})["status"], NA)

    def test_account_normalisation(self):
        self.assertEqual(normalize_account(" 2102611.0 "), "2102611")
        self.assertEqual(normalize_account("ab12"), "AB12")
        self.assertIsNone(normalize_account("  "))


class TestVerdict(unittest.TestCase):

    def test_order_of_severity(self):
        self.assertEqual(verdict([{"status": PASS}, {"status": FAIL}]), "incomplete")
        self.assertEqual(verdict([{"status": PASS}, {"status": WARN}]), "attention")
        self.assertEqual(verdict([{"status": PASS}, {"status": NA}]), "complete")
        self.assertEqual(verdict([{"status": NA}]), "unverified")

    def test_mo_statements_get_no_vendor_check(self):
        out = evaluate(facts(slug="mo-gds"), None, {}, {})
        self.assertNotIn("vendor", [c["key"] for c in out["checks"]])
        self.assertEqual(out["verdict"], "complete")


class TestBalanceStamp(unittest.TestCase):

    def test_the_balance_line_is_stamped_and_a_booking_is_not(self):
        closing = {"cancellation_markup": "BALANCE", "net_amount": "960428.43"}
        statement_balance.tag(closing)
        self.assertEqual(closing["row_kind"], "closing")
        booking = {"ticket_number": "5808758786", "remarks": "BALANCE", "net_amount": "1"}
        statement_balance.tag(booking)
        self.assertNotIn("row_kind", booking)

    def test_restamping_is_idempotent_and_unstamps(self):
        d = {"cancellation_markup": "BALANCE", "net_amount": "5"}
        statement_balance.tag(d)
        statement_balance.tag(d)
        self.assertEqual(d["row_kind"], "closing")
        d["ticket_number"] = "1"
        statement_balance.tag(d)
        self.assertNotIn("row_kind", d)


@unittest.skipUnless(os.path.exists(REAL_STATEMENT), "real TRIUMPHH sample not on this machine")
class TestRealFileIngest(unittest.TestCase):
    """The upload path itself, on the real export: preamble OLD line and BALANCE stamp."""

    def test_opening_is_read_off_the_preamble(self):
        from app.api.v1.statements import _preamble_opening
        content = open(REAL_STATEMENT, "rb").read()
        self.assertEqual(_preamble_opening(content, REAL_STATEMENT, 1), D("627257"))
        self.assertIsNone(_preamble_opening(content, REAL_STATEMENT, 0))

    def test_the_builder_stamps_exactly_one_closing_line(self):
        from app.api.v1.statements import _detect_df
        from app.services import flat_statement
        content = open(REAL_STATEMENT, "rb").read()
        b = flat_statement.get("tp-gds")
        df = _detect_df(content, REAL_STATEMENT, lambda cols: len(b.build_col_map(cols)))
        self.assertEqual(df.attrs.get("header_row"), 1)
        cols = [str(c) for c in df.columns]
        kinds = [b.build_row(r, cols)["data"].get("row_kind") for _, r in df.iterrows()]
        self.assertEqual([k for k in kinds if k], ["closing"])
        self.assertEqual(sum(1 for k in kinds if not k), 37)


if __name__ == "__main__":
    unittest.main()
