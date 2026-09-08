"""Unit tests for the configurable GST rules — no DB, no network.

The whole point of `gst_configurations` is that the three business rules are DATA
rather than code, so what needs pinning is that the data actually reproduces the
rules. Each test below states the arithmetic the business asked for and checks the
generic engine lands on it:

    Abatement / Domestic       CGST = Basic ×  5% × 9%
    Abatement / International  CGST = Basic × 10% × 9%
    Normal / Agency            CGST = ServiceCharge × 9%
    Normal / Reseller          CGST = (Fare + Taxes + ServiceCharge) × 9%

The load-bearing case is EXCLUSIVITY. CGST + SGST and IGST are alternatives — a
supply is intra-state or inter-state, never both — but all three rates sit on one
row, so the obvious wrong implementation reads the three columns and adds them,
taxing every rupee twice. `compute_gst` takes the place-of-supply decision and
zeroes the pair that does not apply; that is pinned in both directions.

Second: `resolve_config` must return None rather than guessing when a caller asks
for "abatement" without saying which sector. Silently defaulting to domestic
would under-tax every international ticket by exactly half.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.gst_calc import (  # noqa: E402
    basis_amount,
    compute_gst,
    formula_text,
    resolve_config,
)


def rule(**kw):
    """A GstConfiguration stand-in. A plain namespace on purpose: gst_calc reads
    attributes and never queries, so the tests need no session or model."""
    base = dict(
        id=1, code="X", category="normal", sub_category="agency",
        basis="service_charge", taxable_value_pct=100,
        cgst_pct=9, sgst_pct=9, igst_pct=18,
        is_active=True, valid_from=None, valid_to=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# The four seeded rules, exactly as gst_config_01/02 create them.
ABD = rule(id=1, code="ABD", category="abatement", sub_category="domestic",
           basis="basic_fare", taxable_value_pct=5)
ABI = rule(id=5, code="ABI", category="abatement", sub_category="international",
           basis="basic_fare", taxable_value_pct=10)
NA = rule(id=2, code="NA", category="normal", sub_category="agency",
          basis="service_charge", taxable_value_pct=100)
NR = rule(id=3, code="NR", category="normal", sub_category="reseller",
          basis="total_cost", taxable_value_pct=100)

# One sale, used throughout so the four rules can be compared against each other.
SALE = dict(basic_fare=10000, taxes=2000, service_charge=500)


class TestBasisAmount(unittest.TestCase):
    def test_each_basis_reads_the_right_money(self):
        self.assertEqual(basis_amount("basic_fare", **SALE), 10000)
        self.assertEqual(basis_amount("service_charge", **SALE), 500)
        # total_cost is fare + taxes + service charge — NOT the ticket's
        # total_amt, which already has commission and TDS folded in.
        self.assertEqual(basis_amount("total_cost", **SALE), 12500)

    def test_unknown_basis_raises(self):
        with self.assertRaises(ValueError):
            basis_amount("moon_dust", **SALE)


class TestTheFourRules(unittest.TestCase):
    """Each rule against the figures the business stated."""

    def test_abatement_domestic(self):
        got = compute_gst(ABD, interstate=False, **SALE)
        self.assertEqual(got["basis_amount"], 10000.0)
        self.assertEqual(got["taxable_value"], 500.0)      # 10000 × 5%
        self.assertEqual((got["cgst"], got["sgst"]), (45.0, 45.0))

    def test_abatement_international_is_double_domestic(self):
        dom = compute_gst(ABD, interstate=False, **SALE)
        intl = compute_gst(ABI, interstate=False, **SALE)
        self.assertEqual(intl["taxable_value"], 1000.0)    # 10000 × 10%
        self.assertEqual((intl["cgst"], intl["sgst"]), (90.0, 90.0))
        # The only difference between the two rules is the deemed slice, so the
        # tax must land at exactly 2×. A regression that made both 5% or both
        # 10% would still pass the two tests above on their own.
        self.assertEqual(intl["total_gst"], dom["total_gst"] * 2)

    def test_normal_agency_taxes_only_the_service_charge(self):
        got = compute_gst(NA, interstate=False, **SALE)
        self.assertEqual(got["taxable_value"], 500.0)
        self.assertEqual((got["cgst"], got["sgst"]), (45.0, 45.0))

    def test_normal_reseller_taxes_the_whole_sale(self):
        got = compute_gst(NR, interstate=False, **SALE)
        self.assertEqual(got["taxable_value"], 12500.0)
        self.assertEqual((got["cgst"], got["sgst"]), (1125.0, 1125.0))


class TestMarkupBasis(unittest.TestCase):
    """The agency rule the business actually described.

    The seeded NA rule taxes `service_charge`, and that column is populated only
    by B2B consolidator statements — NULL on every LCC row and every hand-punched
    ticket, i.e. on 155 of 210 live rows. A rule taxing it alone bills zero tax on
    a real sale. The business's rule is "the service charge added into the markup,
    otherwise the markup", which is what BASIS_MARKUP computes.
    """

    NA_MARKUP = rule(id=2, code="NA", category="normal", sub_category="agency",
                     basis="markup", taxable_value_pct=100)

    def test_markup_alone_when_no_service_charge(self):
        # The live case: AC SERVICES, fixed markup 300, no service charge.
        got = compute_gst(self.NA_MARKUP, interstate=False, markup=300, service_charge=0)
        self.assertEqual(got["taxable_value"], 300.0)
        self.assertEqual((got["cgst"], got["sgst"]), (27.0, 27.0))
        # Same total as the 18% single figure it replaces — only the split is new.
        self.assertEqual(got["total_gst"], 54.0)

    def test_a_service_charge_is_added_into_the_markup(self):
        got = compute_gst(self.NA_MARKUP, interstate=False, markup=300, service_charge=200)
        self.assertEqual(got["taxable_value"], 500.0)
        self.assertEqual(got["total_gst"], 90.0)

    def test_the_fare_is_never_taxed_under_this_basis(self):
        got = compute_gst(self.NA_MARKUP, interstate=False,
                          basic_fare=10000, taxes=2000, markup=300)
        self.assertEqual(got["basis_amount"], 300.0)


class TestDiscountAndClamp(unittest.TestCase):
    """Matches billing_calc.compute_gst: discount first, then clamp at zero."""

    NR = rule(id=3, code="NR", category="normal", sub_category="reseller",
              basis="total_cost", taxable_value_pct=100)

    def test_discount_reduces_the_taxable_value_before_the_rate(self):
        got = compute_gst(self.NR, interstate=False, basic_fare=1000, discount=200)
        self.assertEqual(got["taxable_value"], 800.0)
        self.assertEqual(got["total_gst"], 144.0)   # 800 x 18%

    def test_a_refund_never_produces_negative_tax(self):
        """Live billing 20 carries base_amount -745.00. Without the clamp this
        would credit tax that was never collected."""
        got = compute_gst(self.NR, interstate=False, basic_fare=-745)
        self.assertEqual(got["taxable_value"], 0.0)
        self.assertEqual((got["cgst"], got["sgst"], got["igst"]), (0.0, 0.0, 0.0))

    def test_a_discount_larger_than_the_base_clamps_to_zero(self):
        got = compute_gst(self.NR, interstate=False, basic_fare=100, discount=500)
        self.assertEqual(got["total_gst"], 0.0)


class TestInterstateIsRequired(unittest.TestCase):
    def test_it_cannot_be_omitted(self):
        """No default. A default of False would silently bill CGST+SGST on an
        inter-state supply the day one of nine call sites forgot the argument."""
        with self.assertRaises(TypeError):
            compute_gst(rule(), basic_fare=100)   # type: ignore[call-arg]


class TestExclusivity(unittest.TestCase):
    """CGST+SGST and IGST are alternatives, never a sum."""

    def test_intrastate_bills_the_pair_and_no_igst(self):
        for cfg in (ABD, ABI, NA, NR):
            with self.subTest(rule=cfg.code):
                got = compute_gst(cfg, interstate=False, **SALE)
                self.assertEqual(got["igst"], 0.0)
                self.assertGreater(got["cgst"], 0.0)
                self.assertEqual(got["cgst"], got["sgst"])
                self.assertEqual(got["applied"], "cgst_sgst")

    def test_interstate_bills_igst_and_neither_half(self):
        for cfg in (ABD, ABI, NA, NR):
            with self.subTest(rule=cfg.code):
                got = compute_gst(cfg, interstate=True, **SALE)
                self.assertEqual((got["cgst"], got["sgst"]), (0.0, 0.0))
                self.assertGreater(got["igst"], 0.0)
                self.assertEqual(got["applied"], "igst")

    def test_the_total_is_the_same_either_way(self):
        """Where the customer sits changes the SPLIT, never the amount. If this
        ever fails, the same ticket is taxed differently by address alone."""
        for cfg in (ABD, ABI, NA, NR):
            with self.subTest(rule=cfg.code):
                intra = compute_gst(cfg, interstate=False, **SALE)
                inter = compute_gst(cfg, interstate=True, **SALE)
                self.assertEqual(intra["total_gst"], inter["total_gst"])

    def test_summing_all_three_columns_would_double_the_tax(self):
        """Pins the bug this design exists to prevent."""
        got = compute_gst(NR, interstate=False, **SALE)
        naive = got["cgst"] + got["sgst"] + got["igst"] + compute_gst(
            NR, interstate=True, **SALE)["igst"]
        self.assertEqual(got["total_gst"], 2250.0)
        self.assertEqual(naive, 4500.0)   # exactly what NOT to compute


class TestResolveConfig(unittest.TestCase):
    ALL = (ABD, ABI, NA, NR)

    def test_each_pair_finds_its_rule(self):
        for category, sub, expected in (
            ("abatement", "domestic", "ABD"),
            ("abatement", "international", "ABI"),
            ("normal", "agency", "NA"),
            ("normal", "reseller", "NR"),
        ):
            with self.subTest(category=category, sub=sub):
                got = resolve_config(self.ALL, category=category, sub_category=sub)
                self.assertIsNotNone(got)
                self.assertEqual(got.code, expected)

    def test_a_category_without_a_sub_category_resolves_to_nothing(self):
        """"Abatement" alone is not a billable rule. Returning ABD here would
        under-tax every international ticket by half."""
        self.assertIsNone(resolve_config(self.ALL, category="abatement"))
        self.assertIsNone(resolve_config(self.ALL, category="normal"))

    def test_inactive_rules_are_skipped(self):
        off = rule(id=9, code="OFF", category="normal", sub_category="agency", is_active=False)
        self.assertIsNone(resolve_config([off], category="normal", sub_category="agency"))

    def test_effective_dating_picks_the_latest_started_rule(self):
        old = rule(id=10, code="OLD", valid_from=date(2020, 1, 1), cgst_pct=6)
        new = rule(id=11, code="NEW", valid_from=date(2026, 1, 1), cgst_pct=9)
        pick = lambda when: resolve_config(  # noqa: E731
            [old, new], category="normal", sub_category="agency", on_date=when).code
        self.assertEqual(pick(date(2025, 6, 1)), "OLD")   # NEW has not started
        self.assertEqual(pick(date(2026, 6, 1)), "NEW")

    def test_an_expired_rule_is_not_picked(self):
        expired = rule(id=12, code="GONE", valid_to=date(2020, 12, 31))
        self.assertIsNone(resolve_config(
            [expired], category="normal", sub_category="agency", on_date=date(2026, 1, 1)))


class TestFormulaText(unittest.TestCase):
    def test_a_full_slice_prints_no_redundant_multiplier(self):
        # "Service Charge × 100% × 9%" is noise; the 100% is the identity.
        text = formula_text(NA)
        self.assertNotIn("100%", text)
        self.assertIn("Service Charge × 9%", text)

    def test_an_abated_slice_prints_the_deemed_percentage(self):
        self.assertIn("Basic Fare × 5% × 9%", formula_text(ABD))
        self.assertIn("Basic Fare × 10% × 9%", formula_text(ABI))

    def test_all_three_taxes_are_named(self):
        text = formula_text(NR)
        for tax in ("CGST", "SGST", "IGST"):
            self.assertIn(tax, text)


if __name__ == "__main__":
    unittest.main()
