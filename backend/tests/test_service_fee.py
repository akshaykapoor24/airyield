"""Service charge (as vendor) and service fee (as customer) on an agency.

Two things here are load-bearing out of proportion to the size of the module.

THE FIRST IS THE DIRECTION. One `agencies` row is read as a VENDOR on the Vendors data
screens (we buy from them — their charge is a cost) and as a CUSTOMER on the Customer data
ones (we sell to them — our fee is income). The rate we pay Lords is not the rate we charge
Lords, so the two resolvers must never see each other's columns. A test that only checked
"a rate comes back" would pass with the two wired to the same column, which is the single
mistake this whole design exists to prevent.

THE SECOND IS INCLUSIVE VS EXCLUSIVE. It decides how much of a quoted amount is taxable, so
getting it backwards moves real money on every line — ₹1,000 is ₹1,000 + ₹180 exclusive and
₹847.46 + ₹152.54 inclusive. NULL must read as EXCLUSIVE: every agency onboarded before
these columns existed has NULL, and defaulting those to inclusive would silently divide the
taxable value of each of their lines by 1.18.

The third case is the quiet one: a HALF-SET rate must be stored as nothing at all. A type
with no value bills 0.0 and a value with no type falls through `compute_markup` to 0.0, so a
half-set rate is a line silently priced at zero — exactly the revenue leak
`party_markup.norm_category_markups` drops its own half-set entries to avoid.

NOTHING BILLS FROM THIS MODULE YET (api/v1/agency_billing.py still hardcodes 0.0). These
tests pin the arithmetic and the vocabulary now so the wiring pass has something to wire to.

No DB, no network — every function here is pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.billing_calc import GST_RATE, compute_markup  # noqa: E402
from app.services.service_fee import (  # noqa: E402
    DEFAULT_GST_TREATMENT,
    GST_EXCLUSIVE,
    GST_INCLUSIVE,
    GST_TREATMENTS,
    SERVICE_FEE_TYPES,
    customer_service_fee,
    describe,
    norm_service_fee,
    service_amount,
    service_fee_from_cells,
    taxable_and_gst,
    vendor_service_charge,
)


class FakeAgency:
    """Only the six columns the two resolvers read."""

    def __init__(self, **kw):
        self.vendor_service_charge_type = kw.get("vct")
        self.vendor_service_charge_value = kw.get("vcv")
        self.vendor_service_charge_gst = kw.get("vcg")
        self.customer_service_fee_type = kw.get("cft")
        self.customer_service_fee_value = kw.get("cfv")
        self.customer_service_fee_gst = kw.get("cfg")


def cells(**kw):
    """A `cell(column)` callable over a dict, as the XLS importer passes in."""
    return lambda col: kw.get(col)


# ══════════════════════════════════════════════════════════════════════════════
# The direction — the reason there are two triples rather than one
# ══════════════════════════════════════════════════════════════════════════════

class TestTheTwoDirectionsNeverCross(unittest.TestCase):
    """The vendor rate is a COST and the customer rate is INCOME. They are different
    commercial facts about the same party and must not leak into one another."""

    def setUp(self):
        self.a = FakeAgency(
            vct="percentage", vcv=2, vcg=GST_EXCLUSIVE,
            cft="fixed", cfv=250, cfg=GST_INCLUSIVE,
        )

    def test_each_resolver_reads_only_its_own_columns(self):
        self.assertEqual(vendor_service_charge(self.a), ("percentage", 2.0, GST_EXCLUSIVE))
        self.assertEqual(customer_service_fee(self.a), ("fixed", 250.0, GST_INCLUSIVE))

    def test_one_direction_set_leaves_the_other_empty(self):
        """Buying from someone we never sell to is the ordinary case, not an error."""
        buy_only = FakeAgency(vct="fixed", vcv=150, vcg=GST_EXCLUSIVE)
        self.assertEqual(vendor_service_charge(buy_only), ("fixed", 150.0, GST_EXCLUSIVE))
        self.assertEqual(customer_service_fee(buy_only), (None, None, DEFAULT_GST_TREATMENT))

    def test_clearing_one_direction_does_not_disturb_the_other(self):
        self.a.vendor_service_charge_type = None
        self.assertEqual(vendor_service_charge(self.a), (None, None, DEFAULT_GST_TREATMENT))
        self.assertEqual(customer_service_fee(self.a), ("fixed", 250.0, GST_INCLUSIVE))

    def test_an_agency_missing_the_columns_entirely_still_resolves(self):
        """A plain object — or a row read before the migration ran — must not explode
        inside a billing loop. The same defence party_markup.markup_for keeps."""
        self.assertEqual(vendor_service_charge(object()), (None, None, DEFAULT_GST_TREATMENT))
        self.assertEqual(customer_service_fee(object()), (None, None, DEFAULT_GST_TREATMENT))


# ══════════════════════════════════════════════════════════════════════════════
# Inclusive vs exclusive — the arithmetic that moves money
# ══════════════════════════════════════════════════════════════════════════════

class TestTaxableAndGst(unittest.TestCase):

    def test_exclusive_adds_tax_on_top(self):
        out = taxable_and_gst(1000, GST_EXCLUSIVE)
        self.assertEqual(out["taxable"], 1000.0)
        self.assertEqual(out["gst"], 180.0)
        self.assertEqual(out["gross"], 1180.0)

    def test_inclusive_backs_tax_out_of_the_amount(self):
        out = taxable_and_gst(1000, GST_INCLUSIVE)
        self.assertEqual(out["taxable"], 847.46)
        self.assertEqual(out["gst"], 152.54)
        self.assertEqual(out["gross"], 1000.0)

    def test_the_two_treatments_really_do_differ(self):
        """The whole reason the flag is stored rather than inferred."""
        excl = taxable_and_gst(1000, GST_EXCLUSIVE)
        incl = taxable_and_gst(1000, GST_INCLUSIVE)
        self.assertNotEqual(excl["taxable"], incl["taxable"])
        self.assertEqual(round(excl["gross"] - incl["gross"], 2), 180.0)

    def test_inclusive_taxable_plus_gst_is_the_amount_entered(self):
        """Nothing may be lost or invented in the rounding: the party pays what was quoted."""
        for amount in (1, 99.99, 250, 1000, 123456.78):
            out = taxable_and_gst(amount, GST_INCLUSIVE)
            self.assertAlmostEqual(out["taxable"] + out["gst"], out["gross"], places=2)

    def test_exclusive_taxable_plus_gst_is_the_gross(self):
        for amount in (1, 99.99, 250, 1000, 123456.78):
            out = taxable_and_gst(amount, GST_EXCLUSIVE)
            self.assertAlmostEqual(out["taxable"] + out["gst"], out["gross"], places=2)

    def test_null_reads_as_exclusive(self):
        """EVERY agency created before these columns existed has NULL here. Reading that
        as inclusive would divide the taxable value of each of their lines by 1.18."""
        self.assertEqual(DEFAULT_GST_TREATMENT, GST_EXCLUSIVE)
        self.assertEqual(taxable_and_gst(1000, None), taxable_and_gst(1000, GST_EXCLUSIVE))

    def test_an_unrecognised_treatment_reads_as_exclusive_too(self):
        self.assertEqual(taxable_and_gst(1000, "sometimes")["gst_treatment"], GST_EXCLUSIVE)

    def test_it_uses_the_same_rate_as_the_rest_of_the_invoice(self):
        """A bill cannot be internally inconsistent — billing_calc owns the rate."""
        self.assertEqual(taxable_and_gst(1000, GST_EXCLUSIVE)["gst"], round(1000 * GST_RATE, 2))

    def test_an_explicit_rate_overrides_the_default(self):
        """gst_configurations can carry other rates; this takes one rather than growing
        a second source of truth."""
        out = taxable_and_gst(1000, GST_EXCLUSIVE, rate=0.05)
        self.assertEqual(out["gst"], 50.0)
        self.assertEqual(out["gross"], 1050.0)

    def test_zero_is_arithmetic_not_a_special_case(self):
        for treatment in GST_TREATMENTS:
            out = taxable_and_gst(0, treatment)
            self.assertEqual((out["taxable"], out["gst"], out["gross"]), (0.0, 0.0, 0.0))


# ══════════════════════════════════════════════════════════════════════════════
# A half-set rate is stored as nothing
# ══════════════════════════════════════════════════════════════════════════════

class TestHalfSetIsDropped(unittest.TestCase):
    """Either half alone bills 0.0 through compute_markup, so storing one would be a
    line silently priced at nothing while the row looks deliberately configured."""

    def test_a_type_with_no_value_is_dropped_whole(self):
        self.assertEqual(norm_service_fee("fixed", None, GST_INCLUSIVE), (None, None, None))

    def test_a_value_with_no_type_is_dropped_whole(self):
        self.assertEqual(norm_service_fee(None, 250, GST_INCLUSIVE), (None, None, None))

    def test_an_unknown_type_is_dropped(self):
        self.assertEqual(norm_service_fee("percent", 5, None), (None, None, None))

    def test_a_non_numeric_value_is_dropped(self):
        self.assertEqual(norm_service_fee("fixed", "lots", None), (None, None, None))

    def test_a_resolver_drops_a_half_set_row_too(self):
        """Guarded again on READ: the columns are plain nullable ones a psql session
        can put anything into, and this runs on every line of every bill."""
        self.assertEqual(
            vendor_service_charge(FakeAgency(vcv=250, vcg=GST_INCLUSIVE)),
            (None, None, DEFAULT_GST_TREATMENT),
        )


class TestZeroIsAnAnswer(unittest.TestCase):
    """"We deliberately charge them nothing" and "nobody has been asked" are different
    facts — the same distinction agencies.gst_registered is stored for."""

    def test_a_zero_rate_is_kept(self):
        self.assertEqual(norm_service_fee("percentage", 0, None), ("percentage", 0.0, GST_EXCLUSIVE))

    def test_a_zero_rate_survives_the_resolver(self):
        agency = FakeAgency(cft="fixed", cfv=0, cfg=GST_EXCLUSIVE)
        self.assertEqual(customer_service_fee(agency), ("fixed", 0.0, GST_EXCLUSIVE))

    def test_zero_is_not_the_same_as_unset(self):
        self.assertNotEqual(
            customer_service_fee(FakeAgency(cft="fixed", cfv=0)),
            customer_service_fee(FakeAgency()),
        )


class TestNormalisation(unittest.TestCase):

    def test_case_and_padding_are_normalised(self):
        self.assertEqual(
            norm_service_fee("  PERCENTAGE ", 2, " Inclusive "),
            ("percentage", 2.0, GST_INCLUSIVE),
        )

    def test_an_unknown_treatment_beside_a_valid_rate_keeps_the_rate(self):
        """The rate is the commercial fact; the treatment is only how it is presented,
        so a bad treatment falls back rather than voiding a real arrangement."""
        self.assertEqual(norm_service_fee("fixed", 250, "maybe"), ("fixed", 250.0, GST_EXCLUSIVE))

    def test_a_bool_is_not_a_rate(self):
        """True would otherwise arrive as 1.0 and configure a 1% charge."""
        self.assertEqual(norm_service_fee("percentage", True, None), (None, None, None))

    def test_every_declared_type_round_trips(self):
        for kind in SERVICE_FEE_TYPES:
            self.assertEqual(norm_service_fee(kind, 5, None)[0], kind)


# ══════════════════════════════════════════════════════════════════════════════
# The amount, and its sign on a refund
# ══════════════════════════════════════════════════════════════════════════════

class TestServiceAmount(unittest.TestCase):

    def test_percentage_is_a_share_of_the_base(self):
        self.assertEqual(service_amount(10000, "percentage", 2), 200.0)

    def test_fixed_ignores_the_base(self):
        self.assertEqual(service_amount(10000, "fixed", 250), 250.0)

    def test_a_refund_reverses_a_fixed_fee(self):
        """A credit note must not charge a fee on a ticket that was given back. The
        rule is compute_markup's, inherited by delegating rather than restating."""
        self.assertEqual(service_amount(-10000, "fixed", 500), -500.0)

    def test_a_refund_reverses_a_percentage_fee(self):
        self.assertEqual(service_amount(-10000, "percentage", 2), -200.0)

    def test_it_is_exactly_what_compute_markup_does(self):
        """Delegation, not a second implementation that can drift."""
        for base in (10000, -10000, 0):
            for kind, value in (("percentage", 2), ("fixed", 250), (None, 5)):
                self.assertEqual(
                    service_amount(base, kind, value), compute_markup(base, kind, value)
                )

    def test_no_rate_is_no_money(self):
        self.assertEqual(service_amount(10000, None, None), 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# The spreadsheet path — where a half-filled pair is an ERROR, not a drop
# ══════════════════════════════════════════════════════════════════════════════

class TestFromCells(unittest.TestCase):
    """The form cannot produce a half-filled pair; a spreadsheet easily can, and
    someone who typed 250 and forgot the type must hear about it."""

    P = "VENDOR_SERVICE_CHARGE"

    def test_a_sheet_without_the_columns_imports_as_it_always_did(self):
        self.assertEqual(service_fee_from_cells(cells(), self.P), ((None, None, None), None))

    def test_a_complete_triple_is_read(self):
        got, problem = service_fee_from_cells(
            cells(VENDOR_SERVICE_CHARGE_TYPE="percentage",
                  VENDOR_SERVICE_CHARGE_VALUE="2",
                  VENDOR_SERVICE_CHARGE_GST="exclusive"),
            self.P,
        )
        self.assertIsNone(problem)
        self.assertEqual(got, ("percentage", 2.0, GST_EXCLUSIVE))

    def test_a_blank_gst_defaults_rather_than_failing(self):
        got, problem = service_fee_from_cells(
            cells(VENDOR_SERVICE_CHARGE_TYPE="fixed", VENDOR_SERVICE_CHARGE_VALUE="250"), self.P,
        )
        self.assertIsNone(problem)
        self.assertEqual(got, ("fixed", 250.0, GST_EXCLUSIVE))

    def test_a_value_with_no_type_is_reported(self):
        got, problem = service_fee_from_cells(cells(VENDOR_SERVICE_CHARGE_VALUE="250"), self.P)
        self.assertEqual(got, (None, None, None))
        self.assertIn("_TYPE", problem)

    def test_a_type_with_no_value_is_reported(self):
        _, problem = service_fee_from_cells(cells(VENDOR_SERVICE_CHARGE_TYPE="fixed"), self.P)
        self.assertIn("_VALUE is required", problem)

    def test_an_unknown_type_is_reported_with_the_offending_text(self):
        _, problem = service_fee_from_cells(
            cells(VENDOR_SERVICE_CHARGE_TYPE="percent", VENDOR_SERVICE_CHARGE_VALUE="5"), self.P,
        )
        self.assertIn("percent", problem)
        self.assertIn("percentage or fixed", problem)

    def test_a_non_numeric_value_is_reported(self):
        _, problem = service_fee_from_cells(
            cells(VENDOR_SERVICE_CHARGE_TYPE="fixed", VENDOR_SERVICE_CHARGE_VALUE="lots"), self.P,
        )
        self.assertIn("not a number", problem)

    def test_a_negative_value_is_reported(self):
        """A negative service charge is a discount wearing the wrong name."""
        _, problem = service_fee_from_cells(
            cells(VENDOR_SERVICE_CHARGE_TYPE="fixed", VENDOR_SERVICE_CHARGE_VALUE="-5"), self.P,
        )
        self.assertIn("negative", problem)

    def test_an_unknown_gst_treatment_is_reported(self):
        """Unlike the form path, this does NOT quietly fall back — a sheet saying
        'maybe' is a mistake the importer can and should point at."""
        _, problem = service_fee_from_cells(
            cells(VENDOR_SERVICE_CHARGE_TYPE="fixed",
                  VENDOR_SERVICE_CHARGE_VALUE="250",
                  VENDOR_SERVICE_CHARGE_GST="maybe"),
            self.P,
        )
        self.assertIn("inclusive or exclusive", problem)

    def test_a_gst_cell_alone_is_not_worth_failing_an_import_over(self):
        self.assertEqual(
            service_fee_from_cells(cells(VENDOR_SERVICE_CHARGE_GST="inclusive"), self.P),
            ((None, None, None), None),
        )

    def test_the_customer_prefix_reads_its_own_columns(self):
        """Proving the prefix really is what selects the direction."""
        got, _ = service_fee_from_cells(
            cells(CUSTOMER_SERVICE_FEE_TYPE="fixed", CUSTOMER_SERVICE_FEE_VALUE="250"),
            "CUSTOMER_SERVICE_FEE",
        )
        self.assertEqual(got, ("fixed", 250.0, GST_EXCLUSIVE))


class TestDescribe(unittest.TestCase):

    def test_nothing_set_is_an_empty_string(self):
        """So a screen shows its own em-dash rather than this inventing one."""
        self.assertEqual(describe(None, None, None), "")

    def test_a_percentage_reads_as_a_percentage(self):
        self.assertEqual(describe("percentage", 2, GST_EXCLUSIVE), "2% · GST extra")

    def test_a_fixed_amount_reads_as_money(self):
        self.assertEqual(describe("fixed", 250, GST_INCLUSIVE), "₹250 · incl. GST")

    def test_a_half_set_rate_describes_as_nothing(self):
        self.assertEqual(describe("fixed", None, GST_INCLUSIVE), "")


if __name__ == "__main__":
    unittest.main()
