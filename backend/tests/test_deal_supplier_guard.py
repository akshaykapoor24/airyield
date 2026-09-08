"""Unit tests for the B2B supplier guard — no DB, no network.

`_supplier_guard` sits on live paths that predate it: the BSP commission run
(services/bsp_commission.py) and the ticket calculation run (api/v1/tickets.py) both call
`find_all_deals` / `diagnose_match` passing only `supplier_agency`. Every one of those
calls must behave EXACTLY as it did before the id existed — a change there is a wrong
money figure on screens that have nothing to do with third-party statements.

`test_no_id_is_byte_identical_to_the_old_rule` is the guard for that, and it asserts
against a literal re-implementation of the code this replaced rather than against a
restatement of the new behaviour. If it ever fails, the compatibility contract is broken,
not the test.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.deal_matching import (  # noqa: E402
    SUPPLIER_ANY,
    SUPPLIER_BY_ID,
    SUPPLIER_BY_NAME,
    _supplier_guard,
)


class FakeDeal:
    """`supplier_id` is a row in the platform-admin Supplier master — the same list the
    statement is attributed to, and the same one `supplier_name` was picked from."""

    def __init__(self, supplier_name=None, supplier_id=None):
        self.supplier_name = supplier_name
        self.supplier_id = supplier_id


def old_rule(deal, supplier_agency):
    """Verbatim behaviour of the code this replaced (deal_matching.py, pre-change):

        if deal_type_str == "b2b" and supplier_agency:
            if deal.supplier_name and deal.supplier_name.lower() != supplier_agency.lower():
                continue

    i.e. reached only when supplier_agency is truthy; `continue` means "not a candidate".
    """
    if deal.supplier_name and deal.supplier_name.lower() != supplier_agency.lower():
        return False
    return True


class TestBackwardCompatibility(unittest.TestCase):
    """The contract: with no id passed, the guard IS the old rule."""

    CASES = [
        # deal supplier_name          statement agency name
        ("Lords Travels",             "Lords Travels"),
        ("Lords Travels",             "LORDS TRAVELS"),
        ("lords travels",             "Lords Travels"),
        ("Lords Travels",             "Riya Travel & Tours"),
        ("Riya Travel & Tours",       "Riya Travel & Tours"),
        (None,                        "Lords Travels"),
        ("",                          "Lords Travels"),
        ("Lords Travels — Delhi",     "Lords Travels"),
    ]

    def test_no_id_is_byte_identical_to_the_old_rule(self):
        for supplier_name, agency in self.CASES:
            deal = FakeDeal(supplier_name=supplier_name)
            new, _how = _supplier_guard(deal, agency, None)
            self.assertEqual(new, old_rule(deal, agency),
                             f"deal.supplier_name={supplier_name!r} vs agency={agency!r}")

    def test_a_deal_carrying_an_id_still_falls_back_when_the_caller_has_none(self):
        """A backfilled deal must not stop matching for a caller that passes only a name —
        BSP and the ticket run never pass an id."""
        deal = FakeDeal(supplier_name="Lords Travels", supplier_id=42)
        passes, how = _supplier_guard(deal, "Lords Travels", None)
        self.assertTrue(passes)
        self.assertEqual(how, SUPPLIER_BY_NAME)


class TestIdMatching(unittest.TestCase):
    def test_matching_ids_pass_and_report_id(self):
        deal = FakeDeal(supplier_name="Lords Travels", supplier_id=42)
        self.assertEqual(_supplier_guard(deal, "Lords Travels", 42), (True, SUPPLIER_BY_ID))

    def test_different_ids_fail_even_when_the_names_are_identical(self):
        """The whole reason the column exists: 141 of the supplier master's 2,340 names
        repeat across branches — 'Riya Travel & Tours' is fourteen rows — and each branch
        is its own contract."""
        deal = FakeDeal(supplier_name="Lords Travels", supplier_id=42)
        passes, how = _supplier_guard(deal, "Lords Travels", 77)
        self.assertFalse(passes)
        self.assertEqual(how, SUPPLIER_BY_ID)

    def test_id_wins_over_a_disagreeing_name(self):
        """A renamed master row must not break a deal that is linked by id."""
        deal = FakeDeal(supplier_name="Lords Travels (old name)", supplier_id=42)
        self.assertEqual(_supplier_guard(deal, "Lords Travels", 42), (True, SUPPLIER_BY_ID))

    def test_a_deal_without_an_id_falls_back_to_name_even_when_the_caller_has_one(self):
        """Deals written before the column exists still have to match, or every legacy
        contract would stop paying the day a statement gained an agency."""
        deal = FakeDeal(supplier_name="Lords Travels")
        self.assertEqual(_supplier_guard(deal, "Lords Travels", 42), (True, SUPPLIER_BY_NAME))
        self.assertEqual(_supplier_guard(deal, "Riya Travel", 42), (False, SUPPLIER_BY_NAME))


class TestUnrestricted(unittest.TestCase):
    def test_a_deal_naming_no_supplier_matches_anything(self):
        deal = FakeDeal()
        self.assertEqual(_supplier_guard(deal, "Lords Travels", 42), (True, SUPPLIER_ANY))
        self.assertEqual(_supplier_guard(deal, None, None), (True, SUPPLIER_ANY))

    def test_an_unidentified_statement_cannot_be_narrowed(self):
        """Nothing to compare against is not a mismatch — it is the pre-Stage-2 world, and
        those statements must keep matching."""
        deal = FakeDeal(supplier_name="Lords Travels")
        self.assertEqual(_supplier_guard(deal, None, None), (True, SUPPLIER_ANY))


class TestReportedMode(unittest.TestCase):
    def test_every_outcome_names_how_it_was_decided(self):
        """The caller shows a different chip for each, so an unverified name match is never
        presented like a certain id match."""
        for deal, agency, agency_id, expected in [
            (FakeDeal("A", 1), "A", 1, SUPPLIER_BY_ID),
            (FakeDeal("A", 1), "A", 2, SUPPLIER_BY_ID),
            (FakeDeal("A"), "A", 2, SUPPLIER_BY_NAME),
            (FakeDeal("A"), "B", None, SUPPLIER_BY_NAME),
            (FakeDeal(), "A", 1, SUPPLIER_ANY),
        ]:
            self.assertEqual(_supplier_guard(deal, agency, agency_id)[1], expected)


if __name__ == "__main__":
    unittest.main()
