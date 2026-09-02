"""What an employee inherits from their corporate, and — more importantly — what it must
never overwrite.

This decides real money. A blank markup means a customer is billed at ZERO markup
(api/v1/customers.py prices from the customer's own columns, never the corporate's), so
filling the blanks is the whole point of the feature; and overwriting a value someone set
on purpose would silently move a per-employee override onto the employer's terms.

No DB, no network — inherit_from_corporate is pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.party_inherit import (  # noqa: E402
    INHERITED_FIELDS, inherit_from_corporate, is_blank,
)


class FakeCorporate:
    """A corporate on full terms unless a test says otherwise."""

    def __init__(self, **kw):
        self.__dict__.update({
            "phone": "+91-2200000000",
            "email": "accounts@acme.test",
            "markup_type": "percentage",
            "markup_value": 10,
            "billing_type": "reseller",
            "gst_registered": True,
            "gst_no": "27ABCDE1234F1Z5",
            "pan_no": "ABCDE1234F",
            **kw,
        })


def blank_employee(**kw):
    """An imported row with nothing filled in — the case this feature exists for."""
    values = {f: None for f in INHERITED_FIELDS}
    values["gst_registered"] = False        # NOT NULL boolean, so False not None
    values.update(kw)
    return values


class IsBlankTests(unittest.TestCase):

    def test_none_and_empty_string_are_blank(self):
        self.assertTrue(is_blank("phone", None))
        self.assertTrue(is_blank("phone", ""))
        self.assertTrue(is_blank("phone", "   "))

    def test_a_value_is_not_blank(self):
        self.assertFalse(is_blank("phone", "+91-99"))
        self.assertFalse(is_blank("markup_type", "fixed"))

    def test_gst_registered_blank_is_false_not_none(self):
        # It is a NOT NULL boolean — there is no "unset" to tell apart from False.
        self.assertTrue(is_blank("gst_registered", False))
        self.assertFalse(is_blank("gst_registered", True))

    def test_zero_markup_value_is_NOT_blank(self):
        # A deliberate 0% has to survive. Treating it as blank would overwrite the one
        # value a user set to mean "no margin on this person".
        self.assertFalse(is_blank("markup_value", 0))
        self.assertTrue(is_blank("markup_value", None))


class InheritTests(unittest.TestCase):

    def test_a_wholly_blank_employee_takes_everything(self):
        filled = inherit_from_corporate(blank_employee(), FakeCorporate())
        self.assertEqual(set(filled), set(INHERITED_FIELDS))
        self.assertEqual(filled["markup_type"], "percentage")
        self.assertEqual(filled["markup_value"], 10)
        self.assertEqual(filled["billing_type"], "reseller")

    def test_a_value_the_sheet_supplied_is_never_overwritten(self):
        # The load-bearing rule: inherited is a default, not a binding.
        filled = inherit_from_corporate(
            blank_employee(billing_type="agency", markup_value=25), FakeCorporate()
        )
        self.assertNotIn("billing_type", filled)
        self.assertNotIn("markup_value", filled)
        self.assertIn("markup_type", filled)     # still blank, so still inherited

    def test_zero_markup_value_survives(self):
        filled = inherit_from_corporate(blank_employee(markup_value=0), FakeCorporate())
        self.assertNotIn("markup_value", filled)

    def test_nothing_is_invented_when_the_corporate_is_blank_too(self):
        bare = FakeCorporate(markup_type=None, markup_value=None, billing_type=None,
                             phone=None, email=None, pan_no=None,
                             gst_registered=False, gst_no=None)
        self.assertEqual(inherit_from_corporate(blank_employee(), bare), {})

    def test_no_corporate_means_no_inheritance(self):
        self.assertEqual(inherit_from_corporate(blank_employee(), None), {})

    def test_the_input_is_not_mutated(self):
        values = blank_employee()
        before = dict(values)
        inherit_from_corporate(values, FakeCorporate())
        self.assertEqual(values, before)

    def test_company_is_not_inherited(self):
        # It is a mirror the routers keep in sync, not a default. If it ever appears
        # here, two places are writing the same column with different rules.
        self.assertNotIn("company", INHERITED_FIELDS)
        filled = inherit_from_corporate(blank_employee(), FakeCorporate())
        self.assertNotIn("company", filled)


class MarkupPairTests(unittest.TestCase):
    """A markup value only means anything under the type it was quoted as."""

    def test_a_blank_employee_takes_both_halves(self):
        filled = inherit_from_corporate(blank_employee(), FakeCorporate())
        self.assertEqual(filled["markup_type"], "percentage")
        self.assertEqual(filled["markup_value"], 10)

    def test_a_value_never_travels_onto_a_DIFFERENT_type(self):
        # THE money case. An employee on "fixed" with no value, inheriting the 10 from a
        # "percentage 10" corporate, would bill ₹10 a ticket instead of 10%.
        filled = inherit_from_corporate(
            blank_employee(markup_type="fixed"), FakeCorporate()
        )
        self.assertNotIn("markup_type", filled)      # theirs
        self.assertNotIn("markup_value", filled)     # and so the value must not follow

    def test_a_value_does_travel_when_the_type_already_agrees(self):
        filled = inherit_from_corporate(
            blank_employee(markup_type="percentage"), FakeCorporate()
        )
        self.assertNotIn("markup_type", filled)
        self.assertEqual(filled["markup_value"], 10)

    def test_a_type_with_no_value_on_the_corporate_inherits_only_the_type(self):
        typed = FakeCorporate(markup_value=None)
        filled = inherit_from_corporate(blank_employee(), typed)
        self.assertEqual(filled["markup_type"], "percentage")
        self.assertNotIn("markup_value", filled)

    def test_a_corporate_with_a_value_but_no_type_gives_neither(self):
        # Nothing to quote the number under, so it would be meaningless on the employee.
        odd = FakeCorporate(markup_type=None)
        filled = inherit_from_corporate(blank_employee(), odd)
        self.assertNotIn("markup_type", filled)
        self.assertNotIn("markup_value", filled)


class GstPairTests(unittest.TestCase):

    def test_gst_is_inherited_as_a_pair(self):
        filled = inherit_from_corporate(blank_employee(), FakeCorporate())
        self.assertTrue(filled["gst_registered"])
        self.assertEqual(filled["gst_no"], "27ABCDE1234F1Z5")

    def test_an_employee_with_their_own_gst_keeps_it(self):
        filled = inherit_from_corporate(
            blank_employee(gst_registered=True, gst_no="09ZZZZZ9999Z1Z9"), FakeCorporate()
        )
        self.assertNotIn("gst_registered", filled)
        self.assertNotIn("gst_no", filled)

    def test_a_gst_number_without_the_flag_still_blocks_inheritance(self):
        # Half-filled is still the user's data; do not overwrite the number they typed.
        filled = inherit_from_corporate(
            blank_employee(gst_no="09ZZZZZ9999Z1Z9"), FakeCorporate()
        )
        self.assertNotIn("gst_no", filled)
        self.assertNotIn("gst_registered", filled)

    def test_an_unregistered_corporate_never_registers_its_employee(self):
        unreg = FakeCorporate(gst_registered=False, gst_no=None)
        filled = inherit_from_corporate(blank_employee(), unreg)
        self.assertNotIn("gst_registered", filled)
        self.assertNotIn("gst_no", filled)

    def test_a_registered_corporate_with_no_number_sets_neither(self):
        # Never leave gst_registered true with no number — the routers treat that pair
        # as an invariant and would null the number straight back out.
        odd = FakeCorporate(gst_registered=True, gst_no=None)
        filled = inherit_from_corporate(blank_employee(), odd)
        self.assertNotIn("gst_registered", filled)
        self.assertNotIn("gst_no", filled)

    def test_pan_is_independent_of_the_gst_pair(self):
        unreg = FakeCorporate(gst_registered=False, gst_no=None)
        filled = inherit_from_corporate(blank_employee(), unreg)
        self.assertEqual(filled["pan_no"], "ABCDE1234F")


class FieldListTests(unittest.TestCase):

    def test_the_eight_fields_match_the_frontend_twin(self):
        # lib/party.ts INHERITED_FIELDS. If this fails, the same employee gets different
        # terms depending on whether they were typed in or imported.
        self.assertEqual(INHERITED_FIELDS, (
            "phone", "email", "markup_type", "markup_value",
            "billing_type", "gst_registered", "gst_no", "pan_no",
        ))


if __name__ == "__main__":
    unittest.main()
