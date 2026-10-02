"""A new bill is never dated before the user's last bill for anyone.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.billing_dates import LastBilling, date_error  # noqa: E402

LAST = LastBilling(date(2026, 9, 26), "ORIX CORPORATION INDIA LIMITED - MY/26-27/0101")


class DateErrorTests(unittest.TestCase):

    def test_a_first_bill_can_carry_any_date(self):
        self.assertIsNone(date_error(date(2020, 1, 1), None))

    def test_the_same_day_as_the_last_bill_is_allowed(self):
        self.assertIsNone(date_error(date(2026, 9, 26), LAST))

    def test_a_later_day_is_allowed(self):
        self.assertIsNone(date_error(date(2026, 9, 27), LAST))

    def test_an_earlier_day_is_refused_and_says_why(self):
        msg = date_error(date(2026, 9, 25), LAST)
        self.assertIsNotNone(msg)
        self.assertIn("26-09-2026", msg)
        self.assertIn("MY/26-27/0101", msg)


if __name__ == "__main__":
    unittest.main()
