"""The third-party statement, line by line (services/commission/statement_lines.py) — no DB.

What the Commission income cards promise: every ticket line counted once, the money cards
adding up (expected − statement = difference), lines no run has reached kept out of the money
but not out of the count, and the statement's own TOTAL line never counted as a ticket.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.commission import statement_lines as sl  # noqa: E402

SLUG = "tp-gds"


def line(i, data, calc=None):
    row = SimpleNamespace(id=i, data=data, source_format="third-party-gds-v2")
    return sl.build_line(SLUG, row, calc)


def calc(status, incentive=0.0, iata=0.0):
    return SimpleNamespace(status=status, incentive=incentive, iata_commission=iata,
                           matched_deal_name=None, matched_deal_no=None)


SALE = {"ticket_number": "1", "ticket_status": "Sales", "base_fare": "1000",
        "commission_amount": "-50", "net_amount": "950", "airline_master_name": "AIR INDIA"}
REFUND = {"ticket_number": "2", "ticket_status": "Credit Note", "base_fare": "-1000",
          "commission_amount": "50", "net_amount": "-950", "airline_master_name": "AIR INDIA"}


class TestOneLine(unittest.TestCase):
    def test_statement_expected_and_difference(self):
        ln = line(1, SALE, calc("calculated", incentive=60.0, iata=5.0))
        self.assertEqual((ln.statement, ln.expected, ln.difference), (50.0, 65.0, 15.0))
        self.assertEqual(ln.bucket, "matched")

    def test_a_refund_gives_the_commission_back_on_both_sides(self):
        ln = line(2, REFUND, calc("reversed", incentive=-60.0))
        self.assertEqual((ln.statement, ln.expected, ln.difference), (-50.0, -60.0, -10.0))

    def test_a_line_no_run_has_reached_has_no_expected_figure(self):
        ln = line(1, SALE)
        self.assertEqual((ln.bucket, ln.statement, ln.expected, ln.difference),
                         ("pending", 50.0, None, None))

    def test_unmatched_expects_nothing(self):
        ln = line(1, SALE, calc("unmatched"))
        self.assertEqual((ln.bucket, ln.expected, ln.difference), ("unmatched", 0.0, -50.0))

    def test_buckets(self):
        self.assertEqual([sl.bucket_of(s) for s in (
            None, "pending", "calculated", "reversed", "unmatched", "needs_data", "excluded", "skipped")],
            ["pending", "pending", "matched", "matched", "unmatched", "unmatched", "other", "other"])


class TestTheCards(unittest.TestCase):
    def setUp(self):
        self.lines = [
            line(1, SALE, calc("calculated", incentive=60.0, iata=5.0)),   # +15
            line(2, REFUND, calc("reversed", incentive=-60.0)),           # −10
            line(3, dict(SALE, ticket_number="3"), calc("unmatched")),    # −50
            line(4, dict(SALE, ticket_number="4"), calc("skipped")),      # −50
            line(5, dict(SALE, ticket_number="5")),                       # not run
        ]

    def test_counts(self):
        t = sl.totals(self.lines)
        self.assertEqual((t["tickets"], t["matched"], t["unmatched"], t["other"], t["pending"]),
                         (5, 2, 1, 1, 1))

    def test_the_money_adds_up(self):
        t = sl.totals(self.lines)
        self.assertEqual(t["statement_commission"], 100.0)       # 50 − 50 + 50 + 50
        self.assertEqual(t["expected_commission"], 5.0)          # 65 − 60
        self.assertEqual(t["difference"], round(t["expected_commission"] - t["statement_commission"], 2))
        self.assertEqual(t["difference"], sum(ln.difference for ln in self.lines if ln.difference is not None))
        self.assertEqual(t["statement_pending"], 50.0)           # reported beside, never mixed in
        self.assertEqual(t["iata_commission"], 5.0)

    def test_iata_is_its_own_card_and_part_of_expected(self):
        t = sl.totals(self.lines)
        self.assertEqual((t["iata_commission"], t["incentive"], t["with_iata"]), (5.0, 0.0, 1))
        self.assertEqual(t["incentive"] + t["iata_commission"], t["expected_commission"])
        self.assertEqual([ln.line_id for ln in self.lines if sl.in_bucket(ln, "iata")], [1])

    def test_card_filters(self):
        pick = lambda b: [ln.line_id for ln in self.lines if sl.in_bucket(ln, b)]  # noqa: E731
        self.assertEqual(pick("matched"), [1, 2])
        self.assertEqual(pick("unmatched"), [3])
        self.assertEqual(pick("pending"), [5])
        self.assertEqual(pick("difference"), [1, 2, 3, 4])
        self.assertEqual(pick("expected"), [1, 2])
        self.assertEqual(pick("all"), [1, 2, 3, 4, 5])

    def test_a_rounding_gap_is_not_a_difference(self):
        ln = line(1, dict(SALE, commission_amount="590.277"), calc("calculated", incentive=590.28))
        self.assertFalse(sl.in_bucket(ln, "difference"))

    def test_filters(self):
        self.assertTrue(sl.matches(self.lines[0], search="1", air="AIR INDIA", txn="Sales"))
        self.assertFalse(sl.matches(self.lines[0], air="EMIRATES"))
        self.assertFalse(sl.matches(self.lines[0], txn="Credit Note"))


class TestWhatIsATicket(unittest.TestCase):
    def test_the_statements_own_total_line_is_not_a_ticket(self):
        total = SimpleNamespace(id=9, data={"ticket_number": "Total", "net_amount": "10570964.23"})
        self.assertFalse(sl.is_ticket(total))
        self.assertTrue(sl.is_ticket(SimpleNamespace(id=1, data=SALE)))

    def test_only_filled_columns_are_shown_and_amounts_are_money(self):
        cols = sl.columns(SLUG, [line(1, SALE)])
        fields = {c["field"]: c["kind"] for c in cols}
        self.assertEqual(fields.get("base_fare"), "money")
        self.assertIn("ticket_number", fields)
        self.assertNotIn("seat_selection", fields)              # blank on every line
        self.assertFalse(any(f.startswith("__") for f in fields))


if __name__ == "__main__":
    unittest.main()
