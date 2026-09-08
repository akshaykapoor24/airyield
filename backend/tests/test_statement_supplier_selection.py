"""Unit tests for third-party statement → Supplier master attribution — no DB, no network.

The source is the PLATFORM-ADMIN supplier master, not the tenant's Agency Master, and that
is the whole point: it is the same list `deals.supplier_name` is picked from, so both sides
of the B2B match name the same thing. Attributing a statement to an agency could not line
up with a deal at all, because `agencies` splits one vendor into a GDS row and an LCC row.

What is left to check is small on purpose. A supplier row is one branch with a unique
`code`, so the id alone identifies the counterparty — there is no channel rule here because
there is no channel. What remains is existence and `is_active`.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.statement_supplier_selection import (  # noqa: E402
    InactiveSupplier,
    UnknownSupplier,
    resolve_supplier_choice,
    supplier_label,
)


class FakeSupplier:
    """Only the fields the rule and the label read."""

    def __init__(self, name="Riya Travel & Tours (India) Private Limited",
                 code="SUPP-0421", branch=None, city="MUMBAI", is_active=True, id=421):
        self.id = id
        self.name = name
        self.code = code
        self.branch = branch
        self.city = city
        self.is_active = is_active


class TestSelection(unittest.TestCase):
    def test_a_real_active_supplier_passes(self):
        s = FakeSupplier()
        self.assertIs(resolve_supplier_choice(s), s)

    def test_nothing_picked_is_refused_and_says_where_the_names_come_from(self):
        with self.assertRaises(UnknownSupplier) as cm:
            resolve_supplier_choice(None)
        self.assertIn("Supplier master", str(cm.exception))

    def test_an_id_that_resolves_to_nothing_looks_the_same_as_none(self):
        """resolve_for_upload returns None for an unknown id, so a stale client and an
        empty pick must produce the same answer."""
        with self.assertRaises(UnknownSupplier):
            resolve_supplier_choice(None)

    def test_an_inactive_supplier_is_refused(self):
        with self.assertRaises(InactiveSupplier) as cm:
            resolve_supplier_choice(FakeSupplier(is_active=False))
        self.assertIn("inactive", str(cm.exception).lower())

    def test_the_inactive_message_names_the_branch(self):
        """Fourteen rows share this name, so a message that stopped at the name would not
        say which one is inactive."""
        with self.assertRaises(InactiveSupplier) as cm:
            resolve_supplier_choice(FakeSupplier(is_active=False, city="MUMBAI"))
        self.assertIn("MUMBAI", str(cm.exception))


class TestLabel(unittest.TestCase):
    def test_label_carries_branch_and_code(self):
        self.assertEqual(
            supplier_label(FakeSupplier(name="3A Travels", code="SUPP-0525", city="JABALPUR")),
            "3A Travels — JABALPUR · SUPP-0525",
        )

    def test_branch_wins_over_city_when_the_master_has_one(self):
        s = FakeSupplier(name="Trade Wings Limited", branch="Andheri", city="MUMBAI",
                         code="SUPP-0900")
        self.assertIn("Andheri", supplier_label(s))
        self.assertNotIn("MUMBAI", supplier_label(s))

    def test_two_branches_of_one_vendor_get_different_labels(self):
        """141 of the master's 2,340 names repeat across branches. A label that stopped at
        the name would render identical options and the pick would be a coin toss."""
        a = supplier_label(FakeSupplier(city="MUMBAI", code="SUPP-0421"))
        b = supplier_label(FakeSupplier(city="DELHI", code="SUPP-0422"))
        self.assertNotEqual(a, b)

    def test_a_supplier_with_neither_branch_nor_city_still_labels(self):
        s = FakeSupplier(branch=None, city=None, code="SUPP-0001")
        self.assertIn("SUPP-0001", supplier_label(s))

    def test_the_code_is_always_present_because_it_is_the_unique_one(self):
        for s in (FakeSupplier(city=None), FakeSupplier(branch="X"), FakeSupplier()):
            self.assertIn(s.code, supplier_label(s))


if __name__ == "__main__":
    unittest.main()
