"""Unit tests for passenger → customer resolution — no DB, no network.

Every passenger name here is a real value from the live LCC statement
`TransactionReport_All_15Aug2026_25Aug2026`. The pairs that must NOT match are the
point of the file: this resolver deliberately has no similarity threshold, because on
that statement's 101 distinct keys a 0.72 cutoff produces eight pairs of different
people. If someone reintroduces fuzzy matching, `test_no_fuzzy_drift` is what fails.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.customer_resolver import (  # noqa: E402
    AMBIGUOUS,
    INITIALS_ONLY,
    RESOLVED,
    UNRESOLVED,
    CustomerIndex,
    MasterRow,
    person_match_key,
    split_person_name,
    summarise,
)


class TestPersonMatchKey(unittest.TestCase):
    def key(self, name):
        return person_match_key(name)[0]

    def test_case_and_whitespace(self):
        self.assertEqual(self.key("shivchand yadav"), self.key("shivchand YADAV"))
        self.assertEqual(self.key("  Hemal   Shah "), "HEMAL SHAH")

    def test_word_order_does_not_matter(self):
        # The whole reason the key is a SORTED multiset: both spellings are in the
        # same real statement and are one passenger.
        self.assertEqual(self.key("S Shreyas"), self.key("Shreyas S"))
        self.assertEqual(self.key("SACHIN DUBEY"), self.key("DUBEY SACHIN"))

    def test_punctuation_is_dropped(self):
        self.assertEqual(self.key("R.D. AGGARWAL"), self.key("R D AGGARWAL"))
        self.assertEqual(self.key("O'BRIEN"), "OBRIEN")

    def test_digits_are_dropped(self):
        self.assertEqual(self.key("HEMAL SHAH 2"), "HEMAL SHAH")

    def test_gds_slash_form(self):
        self.assertEqual(self.key("YADAV/SHIVCHAND"), self.key("SHIVCHAND YADAV"))

    def test_titles_are_dropped(self):
        for title in ("MR", "MRS", "MS", "MSTR", "DR", "SHRI", "INF", "CHD"):
            self.assertEqual(self.key(f"{title} HEMAL SHAH"), "HEMAL SHAH", title)

    def test_glued_title_suffix(self):
        self.assertEqual(self.key("SHAHHEMALMR"), "SHAHHEMAL")

    def test_title_only_name_does_not_become_the_empty_key(self):
        # Must not collide with every other blank row.
        self.assertEqual(self.key("MR"), "MR")

    def test_initials_are_separated_not_keyed(self):
        key, initials = person_match_key("R D AGGARWAL")
        self.assertEqual(key, "AGGARWAL")
        self.assertEqual(initials, frozenset({"R", "D"}))

    def test_blank(self):
        self.assertEqual(person_match_key(None), ("", frozenset()))
        self.assertEqual(person_match_key("   "), ("", frozenset()))


class TestSplitPersonName(unittest.TestCase):
    def test_last_token_is_the_surname(self):
        self.assertEqual(split_person_name("Atul Kumar Dwivedi"), ("Atul Kumar", "Dwivedi"))

    def test_single_token(self):
        self.assertEqual(split_person_name("Shreyas"), ("Shreyas", None))

    def test_title_is_dropped(self):
        self.assertEqual(split_person_name("MR Hemal Shah"), ("Hemal", "Shah"))

    def test_blank(self):
        self.assertEqual(split_person_name(None), (None, None))


# Deliberately small, like the real dev tenant: 2 customers, one an employee.
_MASTER = [
    MasterRow(11, "mohit", "pandey", corporate_id=4, corporate_name="gtmvantage"),
    MasterRow(12, "ashwani", "agarwal"),
]


class TestResolveExact(unittest.TestCase):
    def setUp(self):
        self.index = CustomerIndex.from_rows(_MASTER)

    def test_exact_match(self):
        m = self.index.resolve("MOHIT PANDEY")
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.customer_id, 11)
        self.assertEqual(m.canonical_name, "mohit pandey")
        self.assertTrue(m.is_billable)

    def test_employee_resolves_to_corporate_type_and_carries_both_ids(self):
        # corporates.py:524-535 defines a corporate's tickets as its employees'
        # tickets, so an employee match has to reach the corporate too.
        m = self.index.resolve("Pandey Mohit")
        self.assertEqual(m.customer_type, "corporate")
        self.assertEqual(m.corporate_id, 4)
        self.assertEqual(m.customer_id, 11)

    def test_customer_without_corporate_is_direct(self):
        m = self.index.resolve("ashwani agarwal")
        self.assertEqual(m.customer_type, "direct")
        self.assertIsNone(m.corporate_id)

    def test_unknown_passenger(self):
        m = self.index.resolve("SHIVCHAND YADAV")
        self.assertEqual(m.status, UNRESOLVED)
        self.assertIsNone(m.customer_id)
        self.assertFalse(m.is_billable)

    def test_blank_name(self):
        self.assertEqual(self.index.resolve("").status, UNRESOLVED)


class TestAmbiguity(unittest.TestCase):
    def test_duplicate_names_are_never_tie_broken(self):
        # `customers` has no unique constraint on the name and the real DB has three
        # rows called "ZZ Disc Test".
        index = CustomerIndex.from_rows([
            MasterRow(7, "ZZ Disc", "Test"),
            MasterRow(8, "ZZ Disc", "Test"),
            MasterRow(9, "ZZ Disc", "Test"),
        ])
        m = index.resolve("ZZ Disc Test")
        self.assertEqual(m.status, AMBIGUOUS)
        self.assertIsNone(m.customer_id)
        self.assertEqual(sorted(m.candidate_ids), [7, 8, 9])
        self.assertFalse(m.is_billable)

    def test_eight_sujoyta_ghosh_rows_all_ambiguous(self):
        index = CustomerIndex.from_rows([
            MasterRow(20, "Sujoyta", "Ghosh"),
            MasterRow(21, "SUJOYTA", "GHOSH"),
        ])
        m = index.resolve("SUJOYTA GHOSH")
        self.assertEqual(m.status, AMBIGUOUS)
        self.assertEqual(sorted(m.candidate_ids), [20, 21])


class TestInitials(unittest.TestCase):
    def test_initials_never_auto_resolve(self):
        index = CustomerIndex.from_rows([MasterRow(30, "Rajesh", "Aggarwal")])
        m = index.resolve("R D AGGARWAL")
        self.assertEqual(m.status, INITIALS_ONLY)
        # The candidate is offered for one-click review, but the row is not billable
        # until a human confirms it.
        self.assertEqual(m.candidate_ids, (30,))
        self.assertFalse(m.is_billable)

    def test_initials_with_several_candidates_is_ambiguous(self):
        index = CustomerIndex.from_rows([
            MasterRow(30, "Rajesh", "Aggarwal"),
            MasterRow(31, "Harsh", "Aggarwal"),
        ])
        m = index.resolve("R D AGGARWAL")
        self.assertEqual(m.status, AMBIGUOUS)
        self.assertEqual(sorted(m.candidate_ids), [30, 31])

    def test_key_equality_beats_the_initials_path(self):
        # A customer literally recorded as "Shreyas S" keys to "SHREYAS", so both
        # real spellings of that passenger resolve outright.
        index = CustomerIndex.from_rows([MasterRow(40, "Shreyas", "S")])
        for spelling in ("S Shreyas", "Shreyas S", "SHREYAS"):
            m = index.resolve(spelling)
            self.assertEqual(m.status, RESOLVED, spelling)
            self.assertEqual(m.customer_id, 40)

    def test_no_initials_means_no_subset_matching(self):
        # Without an initial to explain the missing token, a bare surname must NOT
        # reach into a fuller name — this is the airline resolver's subset rule,
        # which is wrong for people.
        index = CustomerIndex.from_rows([MasterRow(30, "Rajesh", "Aggarwal")])
        self.assertEqual(index.resolve("AGGARWAL").status, UNRESOLVED)


class TestNoFuzzyDrift(unittest.TestCase):
    """The pairs a 0.72 similarity threshold would wrongly merge."""

    def setUp(self):
        self.index = CustomerIndex.from_rows([
            MasterRow(50, "Akshay", "Kumar"),
            MasterRow(51, "Anil Kumar", "Mehta"),
            MasterRow(52, "Harsh", "Aggarwal"),
        ])

    def test_ashish_does_not_become_akshay(self):
        self.assertEqual(self.index.resolve("ASHISH KUMAR").status, UNRESOLVED)

    def test_ashwini_mishra_does_not_become_anil_mehta(self):
        self.assertEqual(self.index.resolve("ASHWINI KUMAR MISHRA").status, UNRESOLVED)

    def test_bare_surname_does_not_become_harsh_aggarwal(self):
        self.assertEqual(self.index.resolve("AGGARWAL").status, UNRESOLVED)

    def test_aashish_does_not_become_akshay(self):
        self.assertEqual(self.index.resolve("AASHISH KUMAR").status, UNRESOLVED)


class TestSummarise(unittest.TestCase):
    def test_counts_by_status(self):
        index = CustomerIndex.from_rows(_MASTER)
        matches = [index.resolve(n) for n in
                   ("mohit pandey", "ashwani agarwal", "SHIVCHAND YADAV", "AKSHAY KUMAR")]
        self.assertEqual(summarise(matches), {RESOLVED: 2, UNRESOLVED: 2})

    def test_empty(self):
        self.assertEqual(summarise([]), {})


class TestIndexBasics(unittest.TestCase):
    def test_len_and_get(self):
        index = CustomerIndex.from_rows(_MASTER)
        self.assertEqual(len(index), 2)
        self.assertEqual(index.get(11).full_name, "mohit pandey")
        self.assertIsNone(index.get(999))

    def test_tuples_are_accepted(self):
        index = CustomerIndex.from_rows([(60, "Naresh", "Nikhare", None, None)])
        self.assertEqual(index.resolve("Naresh Nikhare").customer_id, 60)

    def test_customer_with_no_last_name(self):
        index = CustomerIndex.from_rows([MasterRow(70, "Shreyas")])
        self.assertEqual(index.resolve("Shreyas").status, RESOLVED)


if __name__ == "__main__":
    unittest.main()
