"""Adding a statement passenger to the Employee Master.

The worklist could always MATCH a passenger against the Employee Master; it could
never add one. This is that button, and the thing it can get wrong is filing the same
person twice — which is expensive, because a duplicate splits one traveller's tickets
across two records and each of them then resolves AMBIGUOUS forever after.

Two different duplicate checks stand in the way, and the gap between them is the whole
reason both are needed:

  * `party_dedupe.CustomerDuplicates` keys on the EXACT name string per employer. It
    catches a re-run of the same button, and it claims each identity as it goes so a
    bulk pass over two rows naming one passenger files them once.
  * `customer_resolver.CustomerIndex` keys order-insensitively and drops single-letter
    initials. It catches "JATIN L K WASNIK" against a "Jatin lk wasnik" already on
    file — which the first check waves straight through, because the two strings
    differ.

No DB: the pieces under test are the key functions and the inheritance rule, all pure.
The endpoint itself is exercised by hand against a real batch.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.customer_resolver import (  # noqa: E402
    AMBIGUOUS, INITIALS_ONLY, RESOLVED, CustomerIndex, MasterRow, split_person_name,
)
from app.services.party_dedupe import CustomerDuplicates  # noqa: E402
from app.services.party_inherit import INHERITED_FIELDS, inherit_from_corporate  # noqa: E402


class FakeCorporate:
    """The corporate columns the create reads."""

    def __init__(self, **kw):
        self.id = kw.pop("id", 5)
        self.company = kw.pop("company", "fareqube")
        for f in ("phone", "email", "markup_type", "markup_value",
                  "billing_type", "gst_no", "pan_no", "state"):
            setattr(self, f, kw.pop(f, None))
        self.gst_registered = kw.pop("gst_registered", False)


def blank_employee() -> dict:
    """What the statement can supply about a passenger: nothing but their name."""
    values = {f: None for f in ("phone", "email", "markup_type", "markup_value",
                                "billing_type", "gst_no", "pan_no")}
    values["gst_registered"] = False
    return values


class TestNameSplit(unittest.TestCase):
    """The statement gives ONE name string; Customer stores first and last."""

    def test_the_last_token_is_the_surname(self):
        for display, expected in (
            ("MADHU MAYOORI", ("MADHU", "MAYOORI")),
            ("Arambam Sanathoi Singh", ("Arambam Sanathoi", "Singh")),
            ("Amal Murugan Kaunder", ("Amal Murugan", "Kaunder")),
            ("JATIN L K WASNIK", ("JATIN L K", "WASNIK")),
        ):
            self.assertEqual(split_person_name(display), expected, display)

    def test_a_created_employee_matches_the_row_that_created_them(self):
        """The round trip that makes the button worth pressing: file the passenger,
        and the next re-match resolves their other rows to the new record."""
        for display in ("MADHU MAYOORI", "Amal Murugan Kaunder", "Arambam Sanathoi Singh"):
            first, last = split_person_name(display)
            idx = CustomerIndex.from_rows([MasterRow(1, first, last, 5, "fareqube")])
            m = idx.resolve(display)
            self.assertEqual(m.status, RESOLVED, display)
            self.assertEqual(m.customer_id, 1)
            self.assertEqual(m.corporate_id, 5)


class TestInheritance(unittest.TestCase):
    """There is no form here, so the copy-down the browser normally does
    (lib/party.ts seedFromCorporate) has to happen server-side."""

    def test_a_blank_employee_takes_the_corporates_terms(self):
        corp = FakeCorporate(phone="011-1234", email="info@fareqube.com",
                             markup_type="percentage", markup_value=5,
                             billing_type="reseller")
        filled = inherit_from_corporate(blank_employee(), corp)
        self.assertEqual(filled["billing_type"], "reseller")
        self.assertEqual(filled["markup_type"], "percentage")
        self.assertEqual(filled["markup_value"], 5)
        self.assertEqual(filled["email"], "info@fareqube.com")
        self.assertEqual(filled["phone"], "011-1234")

    def test_billing_type_matters_because_without_it_no_gst_is_charged(self):
        """`gst_taxable` returns 0.0 for an unset billing type — an employee created
        without one would be invoiced with no tax at all."""
        from app.services.billing_calc import gst_taxable
        self.assertEqual(gst_taxable(5000.0, 250.0, None), 0.0)
        corp = FakeCorporate(billing_type="reseller")
        self.assertEqual(inherit_from_corporate(blank_employee(), corp)["billing_type"],
                         "reseller")

    def test_the_gst_pair_travels_together_or_not_at_all(self):
        registered = FakeCorporate(gst_registered=True, gst_no="07AAACO2563P1Z3")
        filled = inherit_from_corporate(blank_employee(), registered)
        self.assertTrue(filled["gst_registered"])
        self.assertEqual(filled["gst_no"], "07AAACO2563P1Z3")

        # fareqube in the live workspace is NOT registered — no number, no flag.
        unregistered = FakeCorporate(gst_registered=False, gst_no=None)
        filled = inherit_from_corporate(blank_employee(), unregistered)
        self.assertNotIn("gst_registered", filled)
        self.assertNotIn("gst_no", filled)

    def test_state_is_not_inherited(self):
        """Place of supply for a DIRECT bill is where the PERSON is, not their
        employer — the form makes the same exclusion deliberately."""
        self.assertNotIn("state", INHERITED_FIELDS)
        corp = FakeCorporate(state="delhi")
        self.assertNotIn("state", inherit_from_corporate(blank_employee(), corp))

    def test_company_is_not_inherited_it_is_mirrored(self):
        """`company` is rewritten by the routers on link, unlink and rename, so it is
        set from the corporate directly rather than through the inherit list."""
        self.assertNotIn("company", INHERITED_FIELDS)


class TestExactDuplicateCheck(unittest.TestCase):
    def test_the_same_passenger_under_the_same_employer_is_refused(self):
        dupes = CustomerDuplicates.from_rows([("MADHU", "MAYOORI", 5, "fareqube")])
        self.assertIsNotNone(dupes.check("MADHU", "MAYOORI", 5, "fareqube"))

    def test_the_same_name_under_a_different_employer_is_a_different_person(self):
        dupes = CustomerDuplicates.from_rows([("MADHU", "MAYOORI", 5, "fareqube")])
        self.assertIsNone(dupes.check("MADHU", "MAYOORI", 6, "gtmvantage"))

    def test_check_claims_the_identity_so_a_bulk_run_files_a_passenger_once(self):
        """Two rows naming one passenger: the first creates, the second is told why
        it did not. Without the claim, a bulk pass would file them twice."""
        dupes = CustomerDuplicates.from_rows([])
        self.assertIsNone(dupes.check("MADHU", "MAYOORI", 5, "fareqube"))
        self.assertIsNotNone(dupes.check("MADHU", "MAYOORI", 5, "fareqube"))

    def test_it_does_NOT_catch_a_respelling(self):
        """The gap this leaves is why the resolver check below exists too."""
        dupes = CustomerDuplicates.from_rows([("Jatin lk", "wasnik", 5, "fareqube")])
        self.assertIsNone(dupes.check("JATIN L K", "WASNIK", 5, "fareqube"))


class TestResolverDuplicateCheck(unittest.TestCase):
    """The second guard: the same key the worklist matched on in the first place."""

    def setUp(self):
        self.idx = CustomerIndex.from_rows([
            MasterRow(1, "Jatin lk", "wasnik", 5, "fareqube"),
            MasterRow(2, "MADHU", "MAYOORI", 5, "fareqube"),
            MasterRow(3, "RIPUL", "BERRY", 6, "gtmvantage"),
        ])

    def _blocked_by(self, display, corporate_id):
        """Mirrors the endpoint's check: a candidate under the SAME employer blocks."""
        match = self.idx.resolve(display)
        for cid in match.candidate_ids:
            known = self.idx.get(cid)
            if known is not None and known.corporate_id == corporate_id:
                return known.full_name
        return None

    def test_a_respelling_under_the_same_employer_is_caught(self):
        """The live case: the worklist showed 'Initials only' against this very
        person, and creating would have filed a second record for them."""
        self.assertEqual(self.idx.resolve("JATIN L K WASNIK").status, INITIALS_ONLY)
        self.assertEqual(self._blocked_by("JATIN L K WASNIK", 5), "Jatin lk wasnik")

    def test_an_exact_match_under_the_same_employer_is_caught(self):
        self.assertEqual(self._blocked_by("MADHU MAYOORI", 5), "MADHU MAYOORI")

    def test_case_and_word_order_do_not_get_past_it(self):
        self.assertEqual(self._blocked_by("mayoori madhu", 5), "MADHU MAYOORI")

    def test_the_same_name_under_a_DIFFERENT_employer_is_allowed(self):
        """Two people of one name at two companies are two people — the same stance
        the exact check takes, and it must not be undone here."""
        self.assertIsNone(self._blocked_by("RIPUL BERRY", 5))
        self.assertEqual(self._blocked_by("RIPUL BERRY", 6), "RIPUL BERRY")

    def test_a_genuinely_new_passenger_is_allowed(self):
        self.assertIsNone(self._blocked_by("Arambam Sanathoi Singh", 5))

    def test_an_ambiguous_name_under_the_employer_still_blocks(self):
        idx = CustomerIndex.from_rows([
            MasterRow(1, "RAJ", "KUMAR", 5, "fareqube"),
            MasterRow(2, "KUMAR", "RAJ", 5, "fareqube"),
        ])
        self.assertEqual(idx.resolve("RAJ KUMAR").status, AMBIGUOUS)
        blocked = [idx.get(c).full_name for c in idx.resolve("RAJ KUMAR").candidate_ids
                   if idx.get(c).corporate_id == 5]
        self.assertEqual(len(blocked), 2)


if __name__ == "__main__":
    unittest.main()
