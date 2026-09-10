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
    TREATMENT_INTER,
    TREATMENT_INTRA,
    TREATMENT_UNSPLIT,
    compute_gst,
    compute_markup,
    gst_taxable,
    interstate_from_treatment,
    passenger_name,
    safe_date,
    split_gst,
    to_float,
    ticket_matched_by,
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

    def test_refund_reverses_the_tax_it_charged(self):
        # This is the decision the previous version of this test was pinned for.
        # Clamping a credit note at zero meant the reversal returned the fare and the
        # markup but NOT the 18% originally charged on them — the customer was
        # short-credited by the tax on every refunded ticket. A credit note reverses
        # tax; that is what makes it a credit note.
        self.assertAlmostEqual(compute_gst(-3728.0, -300.0, "reseller"), -4028.0 * GST_RATE)
        self.assertAlmostEqual(compute_gst(-3728.0, -300.0, "agency"), -300.0 * GST_RATE)

    def test_oversized_discount_cannot_create_negative_tax(self):
        # The clamp still does the job it was written for. The sign of the BASE is
        # what separates the two cases: this is a sale over-discounted, not a refund.
        self.assertEqual(compute_gst(100.0, 0.0, "reseller", discount=10_000.0), 0.0)
        self.assertEqual(compute_gst(100.0, 50.0, "agency", discount=10_000.0), 0.0)

    def test_a_zero_base_still_clamps(self):
        # `base < 0` is the test, not `base <= 0` — a zero-fare line is not a credit.
        self.assertEqual(compute_gst(0.0, 100.0, "agency", discount=10_000.0), 0.0)


class TestSplitGst(unittest.TestCase):
    """CGST + SGST or IGST — never both, and never invented.

    Getting this wrong does not change the invoice total, which is exactly why it
    is dangerous: the money looks right while the tax sits in the wrong box on a
    GSTR-1 return, payable to a government that is not owed it.
    """

    def test_intra_state_splits_into_two_equal_halves(self):
        # Agency rule: tax on the markup. 1000 markup -> 90 + 90.
        got = split_gst(5000.0, 1000.0, "agency", interstate=False)
        self.assertEqual(got["cgst"], 90.0)
        self.assertEqual(got["sgst"], 90.0)
        self.assertEqual(got["igst"], 0.0)
        self.assertEqual(got["gst_amount"], 180.0)
        self.assertEqual(got["gst_treatment"], TREATMENT_INTRA)

    def test_inter_state_is_the_whole_rate_as_igst(self):
        got = split_gst(5000.0, 1000.0, "agency", interstate=True)
        self.assertEqual(got["igst"], 180.0)
        self.assertEqual(got["cgst"], 0.0)
        self.assertEqual(got["sgst"], 0.0)
        self.assertEqual(got["gst_treatment"], TREATMENT_INTER)

    def test_the_two_treatments_cost_the_same(self):
        """9 + 9 = 18. Splitting the heads must not change what is owed —
        this is what makes the split safe to ship ahead of any rate change."""
        for base, markup, bt in ((5000, 1000, "agency"), (12345.67, 987.65, "reseller")):
            with self.subTest(base=base):
                intra = split_gst(base, markup, bt, interstate=False)
                inter = split_gst(base, markup, bt, interstate=True)
                self.assertAlmostEqual(intra["gst_amount"], inter["gst_amount"], places=1)

    def test_cgst_and_sgst_are_always_equal(self):
        """An invoice showing CGST 9.01 against SGST 9.00 is a broken invoice.
        Each head is taken from the taxable value at 9%, never as half of an
        already-rounded 18% total, which is what would make them differ."""
        for markup in (100.05, 33.33, 0.07, 1234.56, 999.99):
            with self.subTest(markup=markup):
                got = split_gst(0.0, markup, "agency", interstate=False)
                self.assertEqual(got["cgst"], got["sgst"])
                self.assertEqual(round(got["cgst"] + got["sgst"], 2), got["gst_amount"])

    def test_undecidable_charges_nothing_to_any_head(self):
        """None is not False. A missing state must never become a silent CGST+SGST
        — that would file inter-state tax as state tax and nothing would say so."""
        got = split_gst(5000.0, 1000.0, "agency", interstate=None)
        self.assertEqual((got["cgst"], got["sgst"], got["igst"]), (0.0, 0.0, 0.0))
        self.assertEqual(got["gst_treatment"], TREATMENT_UNSPLIT)
        # The total is still reported: the row must show what is owed even while
        # it cannot say under which head.
        self.assertEqual(got["gst_amount"], 180.0)

    def test_interstate_has_no_default(self):
        """A default of False would bill CGST+SGST at every call site that forgot
        the argument, silently and wrongly."""
        with self.assertRaises(TypeError):
            split_gst(5000.0, 1000.0, "agency")   # type: ignore[call-arg]

    def test_discount_reduces_the_taxable_value_before_the_rate(self):
        got = split_gst(0.0, 1000.0, "agency", 200.0, interstate=False)
        self.assertEqual(got["gst_amount"], 144.0)     # 800 * 18%
        self.assertEqual(got["cgst"], 72.0)

    def test_a_refund_reverses_tax_under_both_heads(self):
        """Live data carries a -745.00 line. The tax on it WAS charged when the
        ticket sold, so the credit note has to give it back — under the same heads,
        which is what lets the two lines cancel on a GST return."""
        got = split_gst(-745.0, -74.5, "reseller", interstate=False)
        taxable = -745.0 - 74.5
        self.assertEqual(got["cgst"], round(taxable * 0.09, 2))
        self.assertEqual(got["sgst"], round(taxable * 0.09, 2))
        self.assertEqual(got["gst_amount"], got["cgst"] + got["sgst"])
        self.assertLess(got["gst_amount"], 0.0)
        self.assertEqual(got["igst"], 0.0)

    def test_a_refund_reverses_igst_interstate(self):
        got = split_gst(-745.0, -74.5, "reseller", interstate=True)
        self.assertEqual(got["igst"], round(-819.5 * GST_RATE, 2))
        self.assertEqual(got["gst_amount"], got["igst"])
        self.assertEqual((got["cgst"], got["sgst"]), (0.0, 0.0))

    def test_a_refund_and_its_sale_cancel(self):
        """The property that matters: credit a ticket in full and the tax nets out."""
        sale = split_gst(5000.0, 500.0, "reseller", interstate=False)
        credit = split_gst(-5000.0, -500.0, "reseller", interstate=False)
        self.assertAlmostEqual(sale["gst_amount"] + credit["gst_amount"], 0.0)

    def test_an_unset_billing_type_is_not_taxed(self):
        got = split_gst(5000.0, 1000.0, None, interstate=False)
        self.assertEqual(got["gst_amount"], 0.0)
        # Still labelled: the treatment describes the supply, not the amount.
        self.assertEqual(got["gst_treatment"], TREATMENT_INTRA)

    def test_it_agrees_with_the_single_figure_it_replaces(self):
        """The migration path: every existing caller's number has to survive."""
        for base, markup, bt, disc in (
            (5000.0, 1000.0, "agency", 0.0),
            (5000.0, 1000.0, "reseller", 250.0),
            (0.0, 300.0, "agency", 0.0),
        ):
            with self.subTest(bt=bt):
                old = round(compute_gst(base, markup, bt, disc), 2)
                new = split_gst(base, markup, bt, disc, interstate=True)["gst_amount"]
                self.assertEqual(new, old)


class TestGstTaxable(unittest.TestCase):
    def test_the_two_rules_the_business_stated(self):
        self.assertEqual(gst_taxable(5000.0, 1000.0, "reseller"), 6000.0)   # whole sale
        self.assertEqual(gst_taxable(5000.0, 1000.0, "agency"), 1000.0)     # margin only

    def test_rate_times_taxable_is_the_legacy_figure(self):
        self.assertAlmostEqual(
            gst_taxable(5000.0, 1000.0, "agency") * GST_RATE,
            compute_gst(5000.0, 1000.0, "agency"),
        )


class TestInterstateFromTreatment(unittest.TestCase):
    """Editing a raised bill re-applies what it was raised under.

    Re-deciding from the party's current address would move an issued invoice
    between CGST+SGST and IGST when someone edits a customer's GSTIN — changing
    a figure that may already have been filed, with no record of the change.
    """

    def test_round_trips_both_decided_treatments(self):
        self.assertTrue(interstate_from_treatment(TREATMENT_INTER))
        self.assertFalse(interstate_from_treatment(TREATMENT_INTRA))

    def test_unsplit_stays_undecided(self):
        self.assertIsNone(interstate_from_treatment(TREATMENT_UNSPLIT))

    def test_a_billing_raised_before_the_split_reads_as_undecided(self):
        """NULL on every pre-billing_gst_split_01 row. Those bills keep their
        single total rather than gaining heads nobody chose."""
        self.assertIsNone(interstate_from_treatment(None))

    def test_an_unknown_string_is_undecided_not_intra(self):
        self.assertIsNone(interstate_from_treatment("cgst"))


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


class _PartyTicket:
    """Only the four party columns ticket_matched_by reads."""
    def __init__(self, customer_id=None, corporate_id=None,
                 customer_type=None, customer_agency_id=None,
                 pax_name=None, first_name=None, last_name=None):
        self.customer_id = customer_id
        self.corporate_id = corporate_id
        self.customer_type = customer_type
        self.customer_agency_id = customer_agency_id
        self.pax_name = pax_name
        self.first_name = first_name
        self.last_name = last_name


class _Party:
    def __init__(self, id, first_name=None, last_name=None):
        self.id = id
        self.first_name = first_name
        self.last_name = last_name


class TestOneTicketOnePayer(unittest.TestCase):
    """`corporate_id` decides who pays, and only one party may claim a ticket.

    `uploaded_tickets.billing_id` is a single FK, so a ticket two parties can both
    claim is a race: whoever invoices first takes it and the other silently loses
    the fare. That is not hypothetical — an employee's ticket routed to their
    employer carries BOTH ids, and reading customer_id alone as a claim put every
    corporate ticket on the employee's bill too.

    ticket_matched_by is the Python twin of customer_ticket_scope; these assertions
    are what stop the two drifting, because the list query and the create-billing
    guard have to agree or the selector offers rows the POST rejects.
    """

    JATIN = _Party(21, "Jatin", "Wasnik")
    ACME = _Party(7)

    def test_employee_ticket_routed_to_the_employer_is_not_the_employees(self):
        t = _PartyTicket(customer_id=21, corporate_id=7, customer_type="corporate")
        self.assertIsNone(
            ticket_matched_by(t, customer=self.JATIN, names=[("Jatin", "Wasnik")]),
            "naming a company must take the ticket off the person's bill",
        )

    def test_the_employer_does_claim_it(self):
        t = _PartyTicket(customer_id=21, corporate_id=7, customer_type="corporate")
        self.assertEqual(ticket_matched_by(t, corporate=self.ACME, names=[]), "link")

    def test_a_direct_ticket_is_the_persons(self):
        t = _PartyTicket(customer_id=21, customer_type="direct")
        self.assertEqual(ticket_matched_by(t, customer=self.JATIN, names=[]), "link")

    def test_exactly_one_party_claims_each_shape(self):
        for label, t in (
            ("employer-paid", _PartyTicket(customer_id=21, corporate_id=7)),
            ("direct",        _PartyTicket(customer_id=21)),
            ("company only",  _PartyTicket(corporate_id=7)),
        ):
            with self.subTest(shape=label):
                claims = [
                    ticket_matched_by(t, customer=self.JATIN, names=[]) is not None,
                    ticket_matched_by(t, corporate=self.ACME, names=[]) is not None,
                ]
                self.assertEqual(sum(claims), 1, f"{label}: {sum(claims)} parties could bill this")

    def test_an_untagged_ticket_still_falls_back_to_the_passenger_name(self):
        t = _PartyTicket(first_name="Jatin", last_name="Wasnik")
        self.assertEqual(
            ticket_matched_by(t, customer=self.JATIN, names=[("Jatin", "Wasnik")]), "name",
        )


if __name__ == "__main__":
    unittest.main()
