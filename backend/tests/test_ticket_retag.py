"""Which party columns survive a tag — no DB, no network.

`uploaded_tickets` has four party columns and NO constraint tying the type to the
id, and the two billing scopes read only their own id column while ignoring
`customer_type` entirely. So a ticket carrying both `customer_id` and
`corporate_id` is claimable by the Customer Billing page AND the Corporate
Billing page, and `is_billed` is the only thing stopping a double invoice.

Nothing in the database prevents that. `derive_party` is what does, which is why
it is worth pinning here.

The load-bearing case is `upgrade_employee`. The LCC resolver deliberately
promotes a matched employee to their employer so the corporate can bill the
ticket — correct when a MACHINE is guessing who a passenger is. The re-tag
endpoint must not: a user choosing "bill this direct to the employee" is
correcting exactly that promotion, and silently re-applying it would make the
feature do nothing while reporting success.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.ticket_retag import derive_party  # noqa: E402


class TestStaleIdsAreDropped(unittest.TestCase):
    """An id left over from a previously chosen type must never be stored."""

    def test_direct_drops_a_stray_corporate_id(self):
        ct, cust, corp = derive_party("direct", 42, 99, upgrade_employee=False)
        self.assertEqual((ct, cust, corp), ("direct", 42, None))

    def test_corporate_keeps_a_co_sent_customer_id(self):
        """Not a stale id — it names WHO FLEW beside who pays, and that pair is
        what makes the ticket reachable from both billing screens."""
        ct, cust, corp = derive_party("corporate", 42, 99, upgrade_employee=False)
        self.assertEqual((ct, cust, corp), ("corporate", 42, 99))

    def test_corporate_alone_carries_no_customer(self):
        """Picking a company and nobody in particular bills only the company."""
        ct, cust, corp = derive_party("corporate", None, 99, upgrade_employee=False)
        self.assertEqual((ct, cust, corp), ("corporate", None, 99))

    def test_type_is_normalised(self):
        for raw in ("Direct", "  DIRECT  ", "direct"):
            with self.subTest(raw=raw):
                self.assertEqual(derive_party(raw, 1, None, upgrade_employee=False)[0], "direct")


class TestClearing(unittest.TestCase):
    def test_none_clears_every_column(self):
        self.assertEqual(derive_party(None, 42, 99), (None, None, None))

    def test_blank_is_treated_as_none(self):
        self.assertEqual(derive_party("   ", 42, 99), (None, None, None))


class TestEmployeeUpgrade(unittest.TestCase):
    """The rule that decides whether an employer keeps a claim on the ticket."""

    def test_machine_match_promotes_an_employee_to_their_employer(self):
        # The LCC resolver's behaviour, unchanged.
        ct, cust, corp = derive_party(
            "direct", 42, None, employee_corporate_id=7, upgrade_employee=True,
        )
        self.assertEqual((ct, cust, corp), ("corporate", 42, 7))

    def test_a_human_choosing_direct_leaves_the_employer_out(self):
        # THE point of the re-tag feature. If this ever returns a corporate_id,
        # the corporate keeps claiming the ticket and "bill this direct" is a lie.
        ct, cust, corp = derive_party(
            "direct", 42, None, employee_corporate_id=7, upgrade_employee=False,
        )
        self.assertEqual((ct, cust, corp), ("direct", 42, None))
        self.assertIsNone(corp)

    def test_an_individual_is_direct_either_way(self):
        for upgrade in (True, False):
            with self.subTest(upgrade_employee=upgrade):
                got = derive_party("direct", 42, None, employee_corporate_id=None,
                                   upgrade_employee=upgrade)
                self.assertEqual(got, ("direct", 42, None))

    def test_upgrade_defaults_to_on_so_existing_callers_are_unchanged(self):
        self.assertEqual(
            derive_party("direct", 42, None, employee_corporate_id=7),
            ("corporate", 42, 7),
        )


class TestWhoCanBill(unittest.TestCase):
    """The three tagged shapes, and who each one makes the payer.

    ONE TICKET, ONE PAYER — `corporate_id` decides. billing_calc's
    customer_ticket_scope claims a ticket only when it names the person AND names
    no company, so setting corporate_id is what moves the fare from the employee's
    bill to the employer's. Naming the person alongside records who travelled; it
    does not give them a second claim.
    """

    def test_direct_makes_the_person_the_payer(self):
        # Even for an employee: 'direct' is the deliberate opt-out that takes the
        # ticket off the employer's bill.
        _, cust, corp = derive_party(
            "direct", 42, 99, employee_corporate_id=7, upgrade_employee=False,
        )
        self.assertIsNotNone(cust)
        self.assertIsNone(corp, "a direct bill must not leave the employer a claim")

    def test_corporate_keeps_the_passenger_but_makes_the_company_the_payer(self):
        _, cust, corp = derive_party("corporate", 42, 99, upgrade_employee=False)
        self.assertEqual(cust, 42, "the row should still say who travelled")
        self.assertIsNotNone(corp, "the company must be the payer")

    def test_corporate_alone_names_no_passenger(self):
        _, cust, corp = derive_party("corporate", None, 99, upgrade_employee=False)
        self.assertIsNone(cust)
        self.assertIsNotNone(corp)


class TestUnsupportedType(unittest.TestCase):
    def test_agency_is_refused(self):
        # An agency claims tickets through its statement, never through this link.
        with self.assertRaises(ValueError):
            derive_party("agency", None, None)


if __name__ == "__main__":
    unittest.main()
