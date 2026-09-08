"""Which tax heads a sale carries — no DB, no network.

CGST + SGST or IGST is decided by comparing two states, and getting it wrong is
not a rounding error: it puts the whole tax in the wrong box on a GSTR-1 return
while the invoice total looks perfectly correct. So the cases pinned here are the
ones where the two candidate answers differ.

THE RULE THAT MATTERS MOST is that a GSTIN outranks a postal address. They can
disagree — this database has a workspace filed under state code 33 (Tamil Nadu)
carrying "Delhi" in its address block — and the GSTIN is the registration the tax
actually belongs to.

SECOND: an employee inherits their employer. When a corporate is billed for its
employee's ticket the corporate IS the recipient, so its registration decides.

THIRD: undecidable is a real answer, distinct from intra-state. Defaulting a
missing state to False would silently bill CGST + SGST on a supply that might be
inter-state, and nothing on screen would say so.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest
from types import SimpleNamespace as N

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.india_tax import gstin_state_code, is_interstate  # noqa: E402
from app.services.place_of_supply import (  # noqa: E402
    place_of_supply,
    recipient_side,
    state_choices,
    supplier_side,
)

DELHI_WS = N(gst_number="07ABCDE1234F1Z5", state="Delhi")
AC_SERVICES = N(gst_no="07AAACA7029A1Z9", state="Delhi")
MAHARASHTRA_CORP = N(gst_no="27AAPFU0939F1ZV", state="Maharashtra")


class TestGstinStateCode(unittest.TestCase):
    def test_reads_the_first_two_characters(self):
        self.assertEqual(gstin_state_code("07AAACA7029A1Z9"), "07")
        self.assertEqual(gstin_state_code("27AAPFU0939F1ZV"), "27")

    def test_a_bad_check_digit_still_yields_the_state(self):
        """The live workspace GSTIN 07ABCDE1234F1Z5 fails the mod-36 check digit.
        A mistyped character elsewhere does not make the state code meaningless,
        and refusing to read it would leave that workspace unable to bill."""
        self.assertEqual(gstin_state_code("07ABCDE1234F1Z5"), "07")

    def test_case_and_padding_are_absorbed(self):
        self.assertEqual(gstin_state_code("  07aaaca7029a1z9 "), "07")

    def test_a_code_that_is_not_a_state_is_none(self):
        self.assertIsNone(gstin_state_code("99AAACA7029A1Z9"))
        self.assertIsNone(gstin_state_code("AB AACA7029A1Z9"))
        self.assertIsNone(gstin_state_code(None))


class TestGstinBeatsTheAddress(unittest.TestCase):
    """The case that exists in the live data and would silently misfile tax."""

    def test_when_they_disagree_the_registration_wins(self):
        # Workspace 4: GSTIN says Tamil Nadu (33), address says Delhi.
        contradictory = N(gst_number="33AAACI1607G2Z5", state="Delhi")
        got = place_of_supply(contradictory, AC_SERVICES)
        self.assertTrue(got.interstate, "33 vs 07 must be inter-state")
        self.assertEqual(got.supplier_code, "33")

    def test_the_address_is_used_only_when_there_is_no_gstin(self):
        no_gstin = N(gst_no=None, state="Delhi")
        self.assertEqual(recipient_side(no_gstin), ("07", "state"))

    def test_state_text_is_matched_case_and_spelling_insensitively(self):
        # Live corporates carry 'delhi' lowercase; canonical_state absorbs it.
        self.assertEqual(recipient_side(N(gst_no=None, state="delhi"))[0], "07")
        self.assertEqual(recipient_side(N(gst_no=None, state="  DELHI "))[0], "07")


class TestEmployeeInheritsEmployer(unittest.TestCase):
    EMPLOYEE = N(gst_no=None, state=None, corporate=AC_SERVICES)

    def test_billed_through_the_company_uses_the_company(self):
        got = place_of_supply(DELHI_WS, self.EMPLOYEE, corporate=AC_SERVICES)
        self.assertFalse(got.interstate)
        self.assertEqual(got.recipient_code, "07")

    def test_the_employer_is_reached_even_when_not_passed_in(self):
        got = place_of_supply(DELHI_WS, self.EMPLOYEE)
        self.assertEqual(got.recipient_code, "07")

    def test_the_employers_state_decides_not_the_workspaces(self):
        far = N(gst_no="27AAPFU0939F1ZV", state="Maharashtra")
        employee = N(gst_no=None, state=None, corporate=far)
        got = place_of_supply(DELHI_WS, employee, corporate=far)
        self.assertTrue(got.interstate, "a Maharashtra employer means IGST")


class TestDirectCustomer(unittest.TestCase):
    """The business rule: ask the state; same as ours is CGST+SGST, else IGST."""

    def test_same_state_is_intra(self):
        got = place_of_supply(DELHI_WS, N(gst_no=None, state="Delhi", corporate=None))
        self.assertFalse(got.interstate)

    def test_different_state_is_inter(self):
        got = place_of_supply(DELHI_WS, N(gst_no=None, state="Karnataka", corporate=None))
        self.assertTrue(got.interstate)


class TestUndecidable(unittest.TestCase):
    """None, never False. A missing state must not become a silent CGST+SGST."""

    def test_recipient_with_nothing(self):
        got = place_of_supply(DELHI_WS, N(gst_no=None, state=None, corporate=None))
        self.assertIsNone(got.interstate)
        self.assertEqual(got.source, "no_recipient")
        self.assertIn("no GSTIN and no state", got.note)

    def test_supplier_with_nothing(self):
        # 6 of 8 live tenants have gst_number, state and gst_scheme all NULL.
        got = place_of_supply(N(gst_number=None, state=None), AC_SERVICES)
        self.assertIsNone(got.interstate)
        self.assertEqual(got.source, "no_supplier")
        self.assertIn("My Profile", got.note)

    def test_undecided_is_not_false(self):
        got = place_of_supply(N(gst_number=None, state=None), AC_SERVICES)
        self.assertIsNot(got.interstate, False)
        self.assertFalse(got.decided)


class TestIsInterstateHelper(unittest.TestCase):
    def test_matches_the_service(self):
        self.assertFalse(is_interstate("07AAACA7029A1Z9", None, "07ABCDE1234F1Z5", None))
        self.assertTrue(is_interstate("07AAACA7029A1Z9", None, "27AAPFU0939F1ZV", None))
        self.assertIsNone(is_interstate(None, None, "27AAPFU0939F1ZV", None))


class TestCustomerStateIsStoredCanonically(unittest.TestCase):
    """A direct customer's state is only useful if it can be read back.

    Place of supply resolves a state by matching it to a GSTIN state code, so a
    spelling india_tax cannot canonicalise is worth no more than a blank. The
    write path folds the aliases people actually type BEFORE storing, rather
    than hoping every reader remembers to.
    """

    def setUp(self):
        from app.api.v1.customers import _clean_state
        self.clean = _clean_state

    def test_aliases_fold_to_one_spelling(self):
        from app.core.india_tax import state_code
        for typed, stored in (
            ("delhi", "Delhi"),
            ("  NEW DELHI ", "Delhi"),
            ("Tamilnadu", "Tamil Nadu"),
            ("orissa", "Odisha"),
        ):
            with self.subTest(typed=typed):
                self.assertEqual(self.clean(typed), stored)
                self.assertIsNotNone(state_code(self.clean(typed)))

    def test_blank_is_none_so_unset_has_one_representation(self):
        self.assertIsNone(self.clean(""))
        self.assertIsNone(self.clean("   "))
        self.assertIsNone(self.clean(None))

    def test_an_unknown_state_is_kept_rather_than_dropped(self):
        """Refusing it would lose what the user typed. It reads back as
        undecidable, which the screen says out loud."""
        from app.core.india_tax import state_code
        self.assertEqual(self.clean("Atlantis"), "Atlantis")
        self.assertIsNone(state_code("Atlantis"))


class TestStateChoices(unittest.TestCase):
    def test_every_offered_state_has_a_code(self):
        """A picker must not offer a state place of supply cannot read back."""
        from app.core.india_tax import state_code
        for name in state_choices():
            with self.subTest(state=name):
                self.assertIsNotNone(state_code(name))

    def test_supplier_side_reads_the_tenant_spelling_of_the_column(self):
        # tenants.gst_number, not gst_no — the two masters differ.
        self.assertEqual(supplier_side(DELHI_WS), ("07", "gstin"))


if __name__ == "__main__":
    unittest.main()
