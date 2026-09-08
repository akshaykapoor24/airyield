"""The reasons a row earns nothing must GROUP — no DB, no network.

The "Unmatched & skipped" tab groups by (status, reason) and shows at most 50 groups. A
reason that embeds the row's own ticket number therefore produces one group per row and
pushes every other reason off the screen.

This is not hypothetical. A real 203-row LCC Detailed batch produced 50 distinct reasons,
48 of them one refund bucket split by ticket, leaving two slots for everything else. These
tests exist so that cannot come back.

Run:  python -m unittest discover backend/tests
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import commission_core as core  # noqa: E402
from app.services.commission.calc_row import KIND_REFUND, KIND_SKIP, CalcRow  # noqa: E402
from app.services.commission.runner import CommissionRunner  # noqa: E402
from app.services.commission.third_party import ThirdPartyAdapter  # noqa: E402


def refund(ticket: str) -> CalcRow:
    return CalcRow(source_row_id=abs(hash(ticket)) % 10000, ticket_number=ticket,
                   kind=KIND_REFUND, airline_name="IndiGo")


class TestGroupableReasons(unittest.TestCase):
    """Every reason that can reach the gaps tab must be identical for identical causes."""

    def setUp(self):
        self.runner = CommissionRunner(ThirdPartyAdapter("tp-gds", "Third Party · GDS"))

    def _reason(self, ctx, original_index=None):
        import asyncio
        res = asyncio.run(self.runner.calculate_row(
            db=None, ctx=ctx, tenant_id=1, created_by_id=1,
            original_index=original_index or {}))
        return res.status, res.reason

    def test_an_unreversible_refund_reads_the_same_whatever_the_ticket(self):
        reasons = {self._reason(refund(t))[1]
                   for t in ("IHHSTR", "ZHILTH", "VBJHTZ", "U6NT5V", "Y7VW8S")}
        self.assertEqual(len(reasons), 1, f"one cause produced {len(reasons)} groups: {reasons}")

    def test_that_reason_names_no_ticket(self):
        _status, reason = self._reason(refund("IHHSTR"))
        self.assertNotIn("IHHSTR", reason)
        self.assertIn("Refund", reason)

    def test_it_is_still_a_skip_not_an_unmatched(self):
        """A refund with nothing to reverse never was a sale — grouping it with rows that
        have no deal would hide both."""
        status, _reason = self._reason(refund("IHHSTR"))
        self.assertEqual(status, "skipped")

    def test_a_not_a_sale_row_reads_the_same_whatever_it_is(self):
        reasons = {self._reason(CalcRow(source_row_id=i, kind=KIND_SKIP,
                                        kind_reason="Cancelled booking — not a sale"))[1]
                   for i in range(5)}
        self.assertEqual(len(reasons), 1)

    def test_no_carrier_and_no_date_read_the_same_whatever_the_row(self):
        no_air = {self._reason(CalcRow(source_row_id=i, ticket_number=f"T{i}"))[1]
                  for i in range(5)}
        self.assertEqual(len(no_air), 1, no_air)
        no_date = {self._reason(CalcRow(source_row_id=i, ticket_number=f"T{i}",
                                        airline_name="IndiGo"))[1]
                   for i in range(5)}
        self.assertEqual(len(no_date), 1, no_date)


class TestNeedsDataReason(unittest.TestCase):
    def test_it_is_identical_for_the_same_gap(self):
        a = core.needs_data_reason("B2B-000001", ["class"])
        b = core.needs_data_reason("B2B-000001", ["class"])
        self.assertEqual(a, b)

    def test_it_names_no_ticket_or_row(self):
        r = core.needs_data_reason("B2B-000001", ["class", "travel_date"])
        self.assertFalse(re.search(r"\b\d{10}\b", r), f"a document number leaked in: {r}")

    def test_the_remedy_is_the_only_per_source_part(self):
        """BSP says 'upload the TGQ HMPR'; a consolidator statement has no second document,
        so the advice has to differ — but it still groups, because it is per SOURCE and not
        per row."""
        bsp = core.needs_data_reason("AIR-000001", ["class"])
        tp = core.needs_data_reason("AIR-000001", ["class"], remedy="Ask the consolidator.")
        self.assertNotEqual(bsp, tp)
        self.assertIn("TGQ HMPR", bsp)
        self.assertIn("consolidator", tp)

    def test_it_stays_within_the_column(self):
        long_deal = "B2B-" + "9" * 200
        self.assertLessEqual(len(core.needs_data_reason(long_deal, ["class", "sector"])), 500)


if __name__ == "__main__":
    unittest.main()
