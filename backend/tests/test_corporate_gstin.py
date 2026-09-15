"""A corporate's state, GST registration and GSTIN — no DB, no network.

A corporate is Registered or Unregistered. Registered means a valid GSTIN, since
it decides the place of supply and so whether the invoice carries CGST + SGST or
IGST. Unregistered means no GSTIN at all — and then the STATE is what decides it,
which is why the state is required either way.

WHAT IS ACTUALLY CHECKED on a GSTIN, and why each one has caught something real here:
  * present at all      — two live corporates have none
  * mod-36 check digit  — a live corporate carries 22AAKCA8321M1ZD, which is
                          07AAKCA8321M1ZD with the state changed and the check
                          digit left behind
  * agrees with `state` — the same row says Delhi while its GSTIN says
                          Chhattisgarh, and those cannot both be right

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.corporates import (  # noqa: E402
    _GSTIN_REQUIRED, _STATE_REQUIRED, _gstin_problem, _is_registered, _tax_problem,
)

# Valid, and the one this workspace actually uses.
GOOD = "07AAACA7029A1Z9"


class TestGstinIsRequired(unittest.TestCase):
    def test_missing_is_refused(self):
        self.assertEqual(_gstin_problem(None), _GSTIN_REQUIRED)

    def test_blank_and_whitespace_are_refused(self):
        self.assertEqual(_gstin_problem(""), _GSTIN_REQUIRED)
        self.assertEqual(_gstin_problem("   "), _GSTIN_REQUIRED)

    def test_a_valid_one_passes(self):
        self.assertIsNone(_gstin_problem(GOOD))

    def test_case_and_padding_are_absorbed(self):
        self.assertIsNone(_gstin_problem("  07aaaca7029a1z9  "))


class TestGstinIsChecked(unittest.TestCase):
    """Requiring a GSTIN is worth little if any 15 characters are accepted."""

    def test_a_wrong_check_digit_is_caught(self):
        # The live value on corporate #6: 07AAKCA8321M1ZD with '07' changed to
        # '22' and the check digit left alone.
        problem = _gstin_problem("22AAKCA8321M1ZD")
        self.assertIsNotNone(problem)
        self.assertIn("check digit", problem)

    def test_the_wrong_length_is_caught(self):
        self.assertIsNotNone(_gstin_problem("07AAACA7029A1Z"))

    def test_a_code_that_is_not_a_state_is_caught(self):
        self.assertIsNotNone(_gstin_problem("99AAACA7029A1Z9"))


class TestGstinAgreesWithTheRestOfTheRow(unittest.TestCase):
    def test_a_state_that_contradicts_the_gstin_is_caught(self):
        problem = _gstin_problem(GOOD, state="Maharashtra")
        self.assertIsNotNone(problem)
        self.assertIn("Maharashtra", problem)

    def test_the_matching_state_passes(self):
        self.assertIsNone(_gstin_problem(GOOD, state="Delhi"))

    def test_state_spelling_is_absorbed(self):
        # Live corporates carry 'delhi' lowercase; 'New Delhi' is an alias.
        self.assertIsNone(_gstin_problem(GOOD, state="delhi"))
        self.assertIsNone(_gstin_problem(GOOD, state="New Delhi"))

    def test_no_state_is_not_a_gstin_problem(self):
        """The GSTIN check alone treats the state as a cross-check. Requiring the
        state is _tax_problem's job, below."""
        self.assertIsNone(_gstin_problem(GOOD, state=None))

    def test_a_pan_that_contradicts_the_gstin_is_caught(self):
        problem = _gstin_problem(GOOD, pan_no="ABCDE1234F")
        self.assertIsNotNone(problem)
        self.assertIn("PAN", problem)

    def test_the_embedded_pan_passes(self):
        self.assertIsNone(_gstin_problem(GOOD, pan_no="AAACA7029A"))


class TestRegisteredOrUnregistered(unittest.TestCase):
    def test_unregistered_needs_no_gstin(self):
        self.assertIsNone(_tax_problem(False, None, state="Maharashtra"))

    def test_unregistered_ignores_a_stray_gstin(self):
        # The router drops it rather than validating it — a leftover in a hidden field
        # must not stop the save.
        self.assertIsNone(_tax_problem(False, "22AAKCA8321M1ZD", state="Maharashtra"))

    def test_unregistered_still_checks_the_pan(self):
        problem = _tax_problem(False, None, pan_no="NOTAPAN", state="Maharashtra")
        self.assertIsNotNone(problem)
        self.assertIn("PAN", problem)

    def test_registered_without_gstin_is_refused(self):
        self.assertEqual(_tax_problem(True, None, state="Delhi"), _GSTIN_REQUIRED)

    def test_registered_with_a_matching_gstin_passes(self):
        self.assertIsNone(_tax_problem(True, GOOD, state="Delhi"))

    def test_registered_gstin_is_still_cross_checked_against_state(self):
        self.assertIsNotNone(_tax_problem(True, GOOD, state="Maharashtra"))


class TestStateIsRequired(unittest.TestCase):
    def test_missing_state_is_refused_either_way(self):
        for registered, gst in ((False, None), (True, GOOD)):
            with self.subTest(registered=registered):
                self.assertEqual(_tax_problem(registered, gst, state=None), _STATE_REQUIRED)
                self.assertEqual(_tax_problem(registered, gst, state="  "), _STATE_REQUIRED)


class TestRegistrationIsReadFromTheFlagFirst(unittest.TestCase):
    def test_an_explicit_flag_wins_over_the_gstin(self):
        self.assertFalse(_is_registered(False, GOOD))
        self.assertTrue(_is_registered(True, None))

    def test_spreadsheet_spellings(self):
        self.assertTrue(_is_registered("Registered", None))
        self.assertTrue(_is_registered("yes", None))
        self.assertFalse(_is_registered("Unregistered", GOOD))

    def test_no_flag_falls_back_to_whether_there_is_a_gstin(self):
        """A sheet with GST_NO and no GST_REGISTERED column is a sheet of registered
        corporates — reading it as unregistered would discard every GSTIN."""
        self.assertTrue(_is_registered(None, GOOD))
        self.assertTrue(_is_registered("", GOOD))
        self.assertFalse(_is_registered(None, None))
        self.assertFalse(_is_registered(None, "  "))


class TestItIsNonRaising(unittest.TestCase):
    """The bulk import paths attribute a problem to one row and save the rest,
    which a raising validator makes impossible."""

    def test_it_returns_a_string_rather_than_raising(self):
        for bad in (None, "", "22AAKCA8321M1ZD", "nonsense"):
            with self.subTest(value=bad):
                self.assertIsInstance(_gstin_problem(bad), str)


if __name__ == "__main__":
    unittest.main()
