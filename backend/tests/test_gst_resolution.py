"""Matching an LCC row's billing party by the GST number on the booking.

A GSTIN is an exact identifier the airline printed on the booking, so it beats
comparing a passenger's name against a master that may not contain that traveller at
all. It also decides who gets invoiced, so the ways it can go wrong are expensive: an
employer's GSTIN sits on every one of their employees' customer records, so a naive
single index calls every corporate booking AMBIGUOUS and the feature quietly does
nothing; and a placeholder like "NA" typed into two unrelated records would otherwise
match them to each other.

No DB, no network — built through `CustomerIndex.from_rows`.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.customer_resolver import (  # noqa: E402
    AMBIGUOUS, RESOLVED, UNRESOLVED, GST_REASON,
    CustomerIndex, MasterRow, PartyRow, gst_key,
)

ACME_GST = "07AAACZ6844Q1ZI"
ORIX_GST = "07AAACO2563P1Z3"


def index(customers=(), parties=(), customer_gst=None):
    return CustomerIndex.from_rows(list(customers), list(parties), customer_gst or {})


class TestGstKey(unittest.TestCase):
    def test_case_and_punctuation_are_ignored(self):
        self.assertEqual(gst_key(" 07-aaacz 6844q1zi "), ACME_GST)

    def test_placeholders_never_become_a_key(self):
        for junk in ("", "   ", None, "NA", "na", "N/A", "nil", "None", "0",
                     "Not Applicable", "not registered"):
            self.assertIsNone(gst_key(junk), repr(junk))


class TestCorporateFirst(unittest.TestCase):
    def test_a_corporate_holding_the_gstin_resolves_to_it(self):
        idx = index(parties=[PartyRow(7, "ZELLEVEN HEALTHCARE", ACME_GST)])
        m = idx.resolve("SOMEONE UNKNOWN", gstin=ACME_GST)
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.customer_type, "corporate")
        self.assertEqual(m.corporate_id, 7)
        self.assertIsNone(m.customer_id)
        self.assertEqual(m.note, GST_REASON)

    def test_a_corporate_with_no_customers_is_still_reachable(self):
        """`CustomerIndex.load` used to reach corporates only through a customer
        join, so an employer with nobody on the master could not be matched — which
        is precisely the case a GST-keyed statement line is for."""
        idx = index(customers=[], parties=[PartyRow(7, "ZELLEVEN HEALTHCARE", ACME_GST)])
        self.assertEqual(idx.resolve(None, gstin=ACME_GST).corporate_id, 7)

    def test_two_unrelated_corporates_are_never_tie_broken(self):
        idx = index(parties=[PartyRow(7, "A LTD", ACME_GST), PartyRow(8, "B LTD", ACME_GST)])
        m = idx.resolve("ANY NAME", gstin=ACME_GST)
        self.assertEqual(m.status, AMBIGUOUS)
        self.assertEqual(set(m.candidate_ids), {7, 8})
        self.assertIsNone(m.corporate_id)


class TestEmployeesSharingAnEmployerGstin(unittest.TestCase):
    """The case that would otherwise make the whole feature a no-op."""

    def setUp(self):
        self.staff = [
            MasterRow(1, "ANA", "SHARMA", 7, "ZELLEVEN HEALTHCARE"),
            MasterRow(2, "BEN", "SHARMA", 7, "ZELLEVEN HEALTHCARE"),
            MasterRow(3, "CAT", "RAO", 7, "ZELLEVEN HEALTHCARE"),
        ]
        self.gst = {1: ACME_GST, 2: ACME_GST, 3: ACME_GST}

    def test_three_employees_of_one_corporate_resolve_to_the_corporate(self):
        idx = index(self.staff, customer_gst=self.gst)
        m = idx.resolve("ANY PASSENGER", gstin=ACME_GST)
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.customer_type, "corporate")
        self.assertEqual(m.corporate_id, 7)

    def test_the_same_gstin_across_two_corporates_is_ambiguous(self):
        staff = self.staff + [MasterRow(4, "DEV", "IYER", 9, "OTHER LTD")]
        idx = index(staff, customer_gst={**self.gst, 4: ACME_GST})
        self.assertEqual(idx.resolve("ANY", gstin=ACME_GST).status, AMBIGUOUS)

    def test_customers_with_no_corporate_sharing_a_gstin_are_ambiguous(self):
        loose = [MasterRow(1, "ANA", "SHARMA"), MasterRow(2, "BEN", "SHARMA")]
        idx = index(loose, customer_gst={1: ACME_GST, 2: ACME_GST})
        self.assertEqual(idx.resolve("ANY", gstin=ACME_GST).status, AMBIGUOUS)

    def test_a_single_customer_holding_a_gstin_resolves_to_them(self):
        idx = index([MasterRow(1, "ANA", "SHARMA")], customer_gst={1: ORIX_GST})
        m = idx.resolve("SOMEONE ELSE", gstin=ORIX_GST)
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.customer_id, 1)
        self.assertEqual(m.customer_type, "direct")

    def test_corporates_win_over_customers(self):
        idx = index(self.staff,
                    parties=[PartyRow(7, "ZELLEVEN HEALTHCARE", ACME_GST)],
                    customer_gst=self.gst)
        m = idx.resolve("ANY", gstin=ACME_GST)
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.corporate_id, 7)
        self.assertIsNone(m.customer_id)


class TestFallThroughToTheName(unittest.TestCase):
    """A GSTIN that resolves to nothing must not stop a name from matching — the name
    path is what every existing (non-GST) statement relies on."""

    def setUp(self):
        self.idx = index([MasterRow(1, "MADHU", "MAYOORI")],
                         parties=[PartyRow(7, "ZELLEVEN HEALTHCARE", ACME_GST)])

    def test_no_gstin_at_all(self):
        self.assertEqual(self.idx.resolve("MADHU MAYOORI").customer_id, 1)

    def test_placeholder_gstin(self):
        self.assertEqual(self.idx.resolve("MADHU MAYOORI", gstin="NA").customer_id, 1)

    def test_gstin_the_master_does_not_know(self):
        m = self.idx.resolve("MADHU MAYOORI", gstin="27AAAAA0000A1Z5")
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.customer_id, 1)

    def test_gst_wins_when_both_could_match(self):
        idx = index([MasterRow(1, "MADHU", "MAYOORI")],
                    parties=[PartyRow(7, "ZELLEVEN HEALTHCARE", ACME_GST)])
        m = idx.resolve("MADHU MAYOORI", gstin=ACME_GST)
        self.assertEqual(m.corporate_id, 7)
        self.assertIsNone(m.customer_id)
        self.assertEqual(m.note, GST_REASON)

    def test_unknown_gstin_and_unknown_name_is_still_unresolved(self):
        m = self.idx.resolve("NOBODY AT ALL", gstin="27AAAAA0000A1Z5")
        self.assertEqual(m.status, UNRESOLVED)


class TestBackwardCompatibility(unittest.TestCase):
    def test_from_rows_still_takes_customers_alone(self):
        idx = CustomerIndex.from_rows([(1, "MADHU", "MAYOORI", None, None)])
        self.assertEqual(len(idx), 1)
        self.assertEqual(idx.resolve("MADHU MAYOORI").customer_id, 1)

    def test_resolve_without_a_gstin_argument_is_unchanged(self):
        idx = index([MasterRow(1, "ANA", "SHARMA", 7, "ACME")])
        m = idx.resolve("ANA SHARMA")
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual((m.customer_id, m.corporate_id, m.customer_type),
                         (1, 7, "corporate"))


if __name__ == "__main__":
    unittest.main()
