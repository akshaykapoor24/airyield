"""What counts as the same party twice — and, just as much, what does not.

The dangerous half of this feature is the FALSE positive. Employee Master and Corporate
Master are linked, and services/party_inherit copies a corporate's phone, email, GSTIN,
PAN, markup and billing type onto every employee under it — so a company's whole staff
sharing all eight of those is the normal case, not a duplicate. A rule that keyed on any
of them would refuse the second colleague of every corporate that fills its people's
blanks. Half of these tests exist to hold that line.

No DB, no network — `from_rows` is the same index `load` builds, minus the query.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.party_dedupe import (  # noqa: E402
    CorporateDuplicates, CustomerDuplicates, code_key, employer_key, name_key,
)


class NormalisationTests(unittest.TestCase):
    def test_name_key_lowers_and_collapses(self):
        self.assertEqual(name_key("  Acme   Pvt Ltd "), "acme pvt ltd")
        self.assertEqual(name_key("ACME PVT LTD"), "acme pvt ltd")

    def test_name_key_of_nothing_is_empty_not_none(self):
        # Callers use it as a dict key; None and "" must not be two different employers.
        self.assertEqual(name_key(None), "")
        self.assertEqual(name_key("   "), "")

    def test_code_key_uppers_and_strips(self):
        self.assertEqual(code_key(" 27abcde1234f1z5 "), "27ABCDE1234F1Z5")
        self.assertEqual(code_key(None), "")

    def test_employer_key_prefers_the_link_over_the_text(self):
        # Two spellings, one corporate: the id is what they are compared under.
        self.assertEqual(employer_key(7, "Acme"), employer_key(7, "ACME  PVT  LTD"))

    def test_an_id_and_a_name_never_collide(self):
        # An unlinked row spelling out a corporate's name is what Re-link exists to fix;
        # refusing to save it would leave the user no way to get there.
        self.assertNotEqual(employer_key(7, "Acme"), employer_key(None, "Acme"))

    def test_individual_direct_is_a_real_employer_value(self):
        self.assertEqual(employer_key(None, None), employer_key(None, "   "))


class EmployeeDuplicateTests(unittest.TestCase):
    """One NAME per EMPLOYER, per workspace."""

    def setUp(self):
        # Two colleagues at corporate 7, and one individual.
        self.master = CustomerDuplicates.from_rows([
            ("John", "Doe", 7, "Acme Pvt Ltd"),
            ("Jane", "Roe", 7, "Acme Pvt Ltd"),
            ("Sam", None, None, None),
        ])

    def test_same_name_same_employer_is_refused(self):
        clash = self.master.check("John", "Doe", 7, "Acme Pvt Ltd")
        self.assertIsNotNone(clash)
        self.assertIn("already exists in Employee Master", clash)
        self.assertIn("Acme Pvt Ltd", clash)

    def test_case_and_spacing_do_not_make_a_new_person(self):
        self.assertIsNotNone(self.master.check("  john ", "DOE", 7, "Acme Pvt Ltd"))

    def test_same_name_different_employer_is_allowed(self):
        self.assertIsNone(self.master.check("John", "Doe", 9, "Beta Traders"))

    def test_same_name_as_an_individual_is_allowed_when_the_other_is_employed(self):
        self.assertIsNone(self.master.check("John", "Doe", None, None))

    def test_two_individuals_of_one_name_collide_with_each_other(self):
        clash = self.master.check("Sam", None, None, None)
        self.assertIsNotNone(clash)
        self.assertIn("individual / direct", clash)

    def test_a_last_name_tells_two_people_apart(self):
        self.assertIsNone(self.master.check("John", "Smith", 7, "Acme Pvt Ltd"))

    def test_inherited_fields_are_not_identity(self):
        """The whole point: colleagues share phone, email, GSTIN and PAN by design.

        `check` is not even offered them — this asserts the signature stays that way, so
        importing a second employee under a corporate that fills their blanks cannot be
        read as re-importing the first.
        """
        self.assertIsNone(self.master.check("Priya", "Nair", 7, "Acme Pvt Ltd"))
        self.assertIsNone(self.master.check("Ravi", "Kumar", 7, "Acme Pvt Ltd"))


class EmployeeBatchTests(unittest.TestCase):
    """A file that repeats itself — which no query can see."""

    def test_the_second_copy_in_one_file_is_refused(self):
        register = CustomerDuplicates.from_rows([])
        self.assertIsNone(register.check("John", "Doe", 7, "Acme"))
        clash = register.check("John", "Doe", 7, "Acme")
        self.assertIsNotNone(clash)
        self.assertIn("listed more than once in this file", clash)

    def test_a_file_repeat_reads_differently_from_one_already_on_file(self):
        register = CustomerDuplicates.from_rows([("John", "Doe", 7, "Acme")])
        self.assertIn("already exists in Employee Master", register.check("John", "Doe", 7, "Acme"))

    def test_claim_can_be_withheld(self):
        register = CustomerDuplicates.from_rows([])
        self.assertIsNone(register.check("John", "Doe", 7, "Acme", claim=False))
        self.assertIsNone(register.check("John", "Doe", 7, "Acme"))


class EmployeeEditTests(unittest.TestCase):
    """An edit is judged on what the row will HOLD, excused from clashing with itself."""

    def setUp(self):
        self.rows = [("John", "Doe", 7, "Acme"), ("Jane", "Roe", 7, "Acme")]

    def _register(self):
        return CustomerDuplicates.from_rows(self.rows)

    def test_saving_a_row_unchanged_is_not_a_duplicate_of_itself(self):
        own = CustomerDuplicates.key("John", "Doe", 7, "Acme")
        self.assertIsNone(self._register().check("John", "Doe", 7, "Acme", exclude=own))

    def test_editing_a_field_that_is_not_identity_is_not_a_duplicate(self):
        own = CustomerDuplicates.key("John", "Doe", 7, "Acme")
        # Same identity, different title/phone/whatever — those are not passed at all.
        self.assertIsNone(self._register().check("John", "Doe", 7, "Acme", exclude=own))

    def test_renaming_onto_a_colleague_is_refused(self):
        own = CustomerDuplicates.key("John", "Doe", 7, "Acme")
        self.assertIsNotNone(self._register().check("Jane", "Roe", 7, "Acme", exclude=own))

    def test_moving_to_an_employer_that_already_has_that_name_is_refused(self):
        rows = self.rows + [("John", "Doe", 9, "Beta")]
        register = CustomerDuplicates.from_rows(rows)
        own = CustomerDuplicates.key("John", "Doe", 9, "Beta")
        self.assertIsNotNone(register.check("John", "Doe", 7, "Acme", exclude=own))


class EmployeeCodeTests(unittest.TestCase):
    """The second identity facet — and the whole point of it.

    Before the code existed, two people genuinely called Rahul Sharma at one corporate could
    not both be saved: the register refused the second and told the user to change a name or
    an employer. The code is the third option that message was missing.
    """

    def setUp(self):
        # (first, last, corporate_id, company, employee_code)
        self.rows = [("Rahul", "Sharma", 7, "Acme", "EMP-001")]

    def _register(self, rows=None):
        return CustomerDuplicates.from_rows(rows if rows is not None else self.rows)

    def test_two_of_one_name_are_allowed_when_their_codes_differ(self):
        """THE FEATURE."""
        self.assertIsNone(
            self._register().check("Rahul", "Sharma", 7, "Acme", "EMP-002"))

    def test_two_of_one_name_are_still_refused_when_neither_has_a_code(self):
        """THE REGRESSION GUARD. Nothing tells them apart, so nothing should pretend to."""
        register = self._register([("Rahul", "Sharma", 7, "Acme", None)])
        clash = register.check("Rahul", "Sharma", 7, "Acme", None)
        self.assertIsNotNone(clash)
        self.assertIn("Employee Code", clash)      # the refusal names the fix

    def test_a_third_uncoded_namesake_is_still_refused(self):
        register = self._register([("Rahul", "Sharma", 7, "Acme", None)])
        self.assertIsNone(register.check("Rahul", "Sharma", 7, "Acme", "EMP-009"))
        self.assertIsNotNone(register.check("Rahul", "Sharma", 7, "Acme", None))

    def test_a_code_cannot_be_shared_even_by_a_different_person(self):
        clash = self._register().check("Priya", "Nair", 7, "Acme", "EMP-001")
        self.assertIsNotNone(clash)
        self.assertIn("EMP-001", clash)
        self.assertIn("Rahul Sharma", clash)       # names who already holds it

    def test_a_code_cannot_be_shared_across_employers_either(self):
        """Workspace-scoped, not per-corporate: a code meaning two people in one workspace
        is not an identifier, and searching it would return both."""
        self.assertIsNotNone(self._register().check("Priya", "Nair", 9, "Beta", "EMP-001"))

    def test_a_blank_code_occupies_no_code_identity(self):
        """Mirrors the blank-GSTIN rule on CorporateDuplicates."""
        register = self._register([("Rahul", "Sharma", 7, "Acme", None)])
        self.assertIsNone(register.check("Priya", "Nair", 7, "Acme", None))
        self.assertIsNone(register.check("Anil", "Kumar", 9, "Beta", ""))

    def test_an_uncoded_namesake_of_a_coded_employee_is_refused(self):
        """THE HOLE THIS CLOSES. The person keys differ only by a code the new row does not
        have, so it used to read as someone new — and it is exactly the row a sheet without
        codes produces when it re-imports someone already on file."""
        clash = self._register().check("rahul", " SHARMA ", 7, "Acme", None)
        self.assertIsNotNone(clash)
        self.assertIn("EMP-001", clash)            # says which namesake it collides with
        self.assertIn("Employee Code", clash)      # and names the fix

    def test_the_uncoded_namesake_is_still_free_under_another_employer(self):
        self.assertIsNone(self._register().check("Rahul", "Sharma", 9, "Beta", None))

    def test_existing_uncoded_then_new_coded_still_works(self):
        """The order Employee Master's form suggests: the existing person, then the new one
        with a code. Only the uncoded arrival is checked against `named`."""
        register = self._register([("Rahul", "Sharma", 7, "Acme", None)])
        self.assertIsNone(register.check("Rahul", "Sharma", 7, "Acme", "EMP-002"))

    def test_editing_an_employee_who_already_shares_a_name_is_not_blocked(self):
        """A workspace can hold an uncoded Rahul next to a coded one. Re-saving the uncoded
        one without moving him must not be refused."""
        register = self._register([("Rahul", "Sharma", 7, "Acme", None),
                                   ("Rahul", "Sharma", 7, "Acme", "EMP-002")])
        own = CustomerDuplicates.keys("Rahul", "Sharma", 7, "Acme", None)
        self.assertIsNone(register.check("Rahul", "Sharma", 7, "Acme", None, exclude=own))

    def test_removing_the_code_is_refused_while_a_coded_namesake_remains(self):
        register = self._register([("Rahul", "Sharma", 7, "Acme", "EMP-001"),
                                   ("Rahul", "Sharma", 7, "Acme", "EMP-002")])
        own = CustomerDuplicates.keys("Rahul", "Sharma", 7, "Acme", "EMP-002")
        self.assertIsNotNone(register.check("Rahul", "Sharma", 7, "Acme", None, exclude=own))

    def test_a_file_with_a_coded_then_an_uncoded_namesake_refuses_the_second(self):
        register = self._register([])
        self.assertIsNone(register.check("Amit", "Rao", 7, "Acme", "A1"))
        self.assertIsNotNone(register.check("Amit", "Rao", 7, "Acme", None))

    def test_case_and_padding_do_not_make_a_new_code(self):
        self.assertIsNotNone(self._register().check("Priya", "Nair", 7, "Acme", " emp-001 "))

    def test_editing_a_coded_employee_is_not_a_duplicate_of_itself(self):
        own = CustomerDuplicates.keys("Rahul", "Sharma", 7, "Acme", "EMP-001")
        self.assertIsNone(
            self._register().check("Rahul", "Sharma", 7, "Acme", "EMP-001", exclude=own))

    def test_changing_the_code_while_keeping_the_name_is_allowed(self):
        """Each facet is excused independently, like the corporate name/GSTIN pair."""
        own = CustomerDuplicates.keys("Rahul", "Sharma", 7, "Acme", "EMP-001")
        self.assertIsNone(
            self._register().check("Rahul", "Sharma", 7, "Acme", "EMP-007", exclude=own))

    def test_a_file_listing_one_code_twice_is_caught(self):
        register = self._register([])
        self.assertIsNone(register.check("Rahul", "Sharma", 7, "Acme", "EMP-001"))
        clash = register.check("Priya", "Nair", 7, "Acme", "EMP-001")
        self.assertIsNotNone(clash)
        self.assertIn("more than once in this file", clash)

    def test_four_tuples_still_load(self):
        """from_rows is called with four-tuples by callers written before the code, and by
        the tests above; a row with no code has to behave exactly as it did then."""
        register = CustomerDuplicates.from_rows([("John", "Doe", 7, "Acme")])
        self.assertIsNotNone(register.check("John", "Doe", 7, "Acme"))
        self.assertIsNone(register.check("Jane", "Roe", 7, "Acme"))


class CorporateDuplicateTests(unittest.TestCase):
    """One NAME and one GSTIN per workspace, each decisive on its own."""

    def setUp(self):
        self.master = CorporateDuplicates.from_rows([
            ("Acme Pvt Ltd", "27ABCDE1234F1Z5"),
            ("Beta Traders", "09ABCDE1234F1Z5"),
        ])

    def test_same_name_is_refused(self):
        clash = self.master.check("acme   pvt ltd", "33ZZZZZ9999Z1Z5")
        self.assertIsNotNone(clash)
        self.assertIn("already in Corporate Master", clash)

    def test_the_name_message_says_why_it_matters(self):
        # It is the key the employee import links people to their employer by.
        self.assertIn("employee import", self.master.check("Acme Pvt Ltd", "33ZZZZZ9999Z1Z5"))

    def test_same_gstin_under_a_different_name_is_refused(self):
        clash = self.master.check("Acme Private Limited", "27abcde1234f1z5")
        self.assertIsNotNone(clash)
        self.assertIn("27ABCDE1234F1Z5", clash)
        self.assertIn("Acme Pvt Ltd", clash)

    def test_a_genuinely_new_corporate_is_allowed(self):
        self.assertIsNone(self.master.check("Gamma LLP", "29ABCDE1234F1Z5"))

    def test_a_blank_gstin_occupies_no_identity(self):
        # Two nameless rows with no number are not each other's duplicate — the router
        # rejects them for having no name and no GSTIN, which is the honest error.
        register = CorporateDuplicates.from_rows([])
        self.assertIsNone(register.check(None, None))
        self.assertIsNone(register.check(None, None))

    def test_the_second_copy_in_one_file_is_refused(self):
        register = CorporateDuplicates.from_rows([])
        self.assertIsNone(register.check("Acme Pvt Ltd", "27ABCDE1234F1Z5"))
        clash = register.check("Acme Pvt Ltd", "27ABCDE1234F1Z5")
        self.assertIn("more than once in this file", clash)


class CorporateEditTests(unittest.TestCase):
    def setUp(self):
        self.rows = [("Acme Pvt Ltd", "27ABCDE1234F1Z5"), ("Beta Traders", "09ABCDE1234F1Z5")]

    def _register(self):
        return CorporateDuplicates.from_rows(self.rows)

    def test_saving_unchanged_is_not_a_duplicate_of_itself(self):
        own = CorporateDuplicates.keys("Acme Pvt Ltd", "27ABCDE1234F1Z5")
        self.assertIsNone(self._register().check("Acme Pvt Ltd", "27ABCDE1234F1Z5", exclude=own))

    def test_renaming_while_keeping_the_gstin_is_allowed(self):
        """Each facet is excused independently, or no corporate could ever be renamed."""
        own = CorporateDuplicates.keys("Acme Pvt Ltd", "27ABCDE1234F1Z5")
        self.assertIsNone(self._register().check("Acme Private Limited", "27ABCDE1234F1Z5", exclude=own))

    def test_correcting_the_gstin_while_keeping_the_name_is_allowed(self):
        own = CorporateDuplicates.keys("Acme Pvt Ltd", "27ABCDE1234F1Z5")
        self.assertIsNone(self._register().check("Acme Pvt Ltd", "24ABCDE1234F1Z5", exclude=own))

    def test_renaming_onto_another_corporate_is_still_refused(self):
        own = CorporateDuplicates.keys("Acme Pvt Ltd", "27ABCDE1234F1Z5")
        self.assertIsNotNone(self._register().check("Beta Traders", "27ABCDE1234F1Z5", exclude=own))

    def test_taking_another_corporates_gstin_is_still_refused(self):
        own = CorporateDuplicates.keys("Acme Pvt Ltd", "27ABCDE1234F1Z5")
        self.assertIsNotNone(self._register().check("Acme Pvt Ltd", "09ABCDE1234F1Z5", exclude=own))


if __name__ == "__main__":
    unittest.main()
