"""A corporate must carry a GSTIN — no DB, no network.

The rule as the business stated it: "always required, no exceptions". It is not
a formality. A corporate's GSTIN decides the place of supply, which decides
whether its invoices carry CGST + SGST or IGST, and the corporate cannot claim
input credit on a bill that does not carry one.

So `gst_registered` is no longer a choice for a corporate. It is forced True
wherever a GSTIN is written, and the Unregistered option is gone from the form —
otherwise the two columns could disagree with each other.

WHAT IS ACTUALLY CHECKED, and why each one has caught something real here:
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

from app.api.v1.corporates import _GSTIN_REQUIRED, _gstin_problem  # noqa: E402

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

    def test_no_state_still_passes(self):
        """The state is a cross-check, not a second requirement — a corporate
        with a GSTIN and no address must still be saveable."""
        self.assertIsNone(_gstin_problem(GOOD, state=None))

    def test_a_pan_that_contradicts_the_gstin_is_caught(self):
        problem = _gstin_problem(GOOD, pan_no="ABCDE1234F")
        self.assertIsNotNone(problem)
        self.assertIn("PAN", problem)

    def test_the_embedded_pan_passes(self):
        self.assertIsNone(_gstin_problem(GOOD, pan_no="AAACA7029A"))


class TestItIsNonRaising(unittest.TestCase):
    """The bulk import paths attribute a problem to one row and save the rest,
    which a raising validator makes impossible."""

    def test_it_returns_a_string_rather_than_raising(self):
        for bad in (None, "", "22AAKCA8321M1ZD", "nonsense"):
            with self.subTest(value=bad):
                self.assertIsInstance(_gstin_problem(bad), str)


if __name__ == "__main__":
    unittest.main()
