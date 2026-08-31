"""Unit tests for billing math — no DB, no network.

The case that matters here is a REFUND. Customer and Corporate billing were built
when only positively-signed ticket statements existed, so `compute_markup`'s "fixed"
branch returned the flat amount regardless of the base's sign. The moment a negative
row becomes billable — an LCC credit, a refunded B2B ticket — that charges the
customer a markup on a ticket they gave back.

Pinning both signs of both markup types, because the percentage branch is correct by
accident (the base carries the sign) and could be "simplified" into the same bug.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.billing_calc import (  # noqa: E402
    GST_RATE,
    compute_gst,
    compute_markup,
    passenger_name,
    safe_date,
    to_float,
)


class TestToFloat(unittest.TestCase):
    def test_none_is_zero(self):
        self.assertEqual(to_float(None), 0.0)

    def test_garbage_is_zero_not_an_exception(self):
        # Billing must never 500 on a bad cell; a zero line is inspectable.
        self.assertEqual(to_float("not a number"), 0.0)

    def test_numeric_string_and_decimal(self):
        from decimal import Decimal
        self.assertEqual(to_float("1234.56"), 1234.56)
        self.assertEqual(to_float(Decimal("-3728.00")), -3728.0)


class TestComputeMarkupFixed(unittest.TestCase):
    """The regression this file exists for."""

    def test_sale_gets_the_flat_amount(self):
        self.assertEqual(compute_markup(5529.0, "fixed", 300), 300.0)

    def test_refund_gets_the_NEGATIVE_flat_amount(self):
        # Was +300 before the fix: a credit note that billed the customer 300
        # for handing a ticket back.
        self.assertEqual(compute_markup(-3728.0, "fixed", 300), -300.0)

    def test_zero_base_keeps_the_positive_amount(self):
        # No such row is billable (payment movements are excluded upstream),
        # but the branch has to be defined rather than accidental.
        self.assertEqual(compute_markup(0.0, "fixed", 300), 300.0)

    def test_case_insensitive_and_decimal_value(self):
        from decimal import Decimal
        self.assertEqual(compute_markup(-100.0, "FIXED", Decimal("500.00")), -500.0)


class TestComputeMarkupPercentage(unittest.TestCase):
    def test_sale(self):
        self.assertAlmostEqual(compute_markup(5529.0, "percentage", 5), 276.45)

    def test_refund_sign_comes_from_the_base(self):
        # Already correct before the fix — pinned so it stays that way.
        self.assertAlmostEqual(compute_markup(-3728.0, "percentage", 5), -186.4)

    def test_zero_value(self):
        self.assertEqual(compute_markup(5529.0, "percentage", 0), 0.0)


class TestComputeMarkupNone(unittest.TestCase):
    def test_unset_type_is_no_markup(self):
        self.assertEqual(compute_markup(5529.0, None, 300), 0.0)
        self.assertEqual(compute_markup(5529.0, "", 300), 0.0)

    def test_unknown_type_is_no_markup(self):
        self.assertEqual(compute_markup(5529.0, "flat", 300), 0.0)


class TestComputeGst(unittest.TestCase):
    def test_reseller_taxes_base_plus_markup(self):
        self.assertAlmostEqual(compute_gst(1000.0, 100.0, "reseller"), 1100.0 * GST_RATE)

    def test_agency_taxes_only_the_markup(self):
        self.assertAlmostEqual(compute_gst(1000.0, 100.0, "agency"), 100.0 * GST_RATE)

    def test_unset_billing_type_is_no_gst(self):
        self.assertEqual(compute_gst(1000.0, 100.0, None), 0.0)

    def test_discount_reduces_the_taxable_amount(self):
        self.assertAlmostEqual(compute_gst(1000.0, 100.0, "reseller", discount=200.0), 900.0 * GST_RATE)

    def test_refund_reverses_no_gst(self):
        # Documented, deliberate, and NOT changed by the markup fix: the clamp at
        # zero means a credit note carries no GST reversal. Pinned so that if it
        # ever should reverse, this test is the place the decision gets made.
        self.assertEqual(compute_gst(-3728.0, -300.0, "reseller"), 0.0)
        self.assertEqual(compute_gst(-3728.0, -300.0, "agency"), 0.0)

    def test_oversized_discount_cannot_create_negative_tax(self):
        self.assertEqual(compute_gst(100.0, 0.0, "reseller", discount=10_000.0), 0.0)


class TestSafeDate(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(safe_date("2026-08-25").isoformat(), "2026-08-25")

    def test_iso_datetime_is_truncated(self):
        self.assertEqual(safe_date("2026-08-25 18:00:23").isoformat(), "2026-08-25")

    def test_dayfirst(self):
        self.assertEqual(safe_date("25/08/2026").isoformat(), "2026-08-25")

    def test_falls_through_to_the_next_candidate(self):
        # The billing date filter passes several columns; the first parseable wins.
        self.assertEqual(safe_date(None, "", "2026-08-25").isoformat(), "2026-08-25")

    def test_unparseable_is_none_not_an_exception(self):
        self.assertIsNone(safe_date("not a date"))
        self.assertIsNone(safe_date(None))


class _Ticket:
    def __init__(self, **kw):
        self.pax_name = kw.get("pax_name")
        self.first_name = kw.get("first_name")
        self.last_name = kw.get("last_name")


class TestPassengerName(unittest.TestCase):
    def test_pax_name_wins(self):
        t = _Ticket(pax_name="SHIVCHAND YADAV", first_name="Shivchand", last_name="Yadav")
        self.assertEqual(passenger_name(t), "SHIVCHAND YADAV")

    def test_falls_back_to_first_last(self):
        self.assertEqual(passenger_name(_Ticket(first_name="Hemal", last_name="Shah")), "Hemal Shah")

    def test_nothing_at_all_is_a_dash(self):
        self.assertEqual(passenger_name(_Ticket()), "—")


if __name__ == "__main__":
    unittest.main()
