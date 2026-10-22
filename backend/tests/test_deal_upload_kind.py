"""Unit tests for the uploaded-deal kind decision — no DB, no network.

Business Type (B2B / B2C / B2E / MICE) is not the deal kind. An airline deal sold
through a B2C channel is still an airline deal, and saving it as B2B drops its
contract year, trigger and payout type.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.deals import _is_b2b_upload  # noqa: E402
from app.models.deal import DealDirection  # noqa: E402

IN, OUT = DealDirection.INBOUND, DealDirection.OUTBOUND


class IsB2bUploadTests(unittest.TestCase):
    def test_airline_keeps_its_kind_whatever_the_business_type(self):
        for bt in ("B2B", "B2C", "B2E", "MICE", None, ""):
            with self.subTest(business_type=bt):
                self.assertFalse(_is_b2b_upload("airline", bt, IN))

    def test_b2b_is_b2b(self):
        self.assertTrue(_is_b2b_upload("b2b", None, IN))
        self.assertTrue(_is_b2b_upload(" B2B ", "B2B", IN))

    def test_no_kind_falls_back_to_business_type(self):
        self.assertTrue(_is_b2b_upload(None, "B2B", IN))
        self.assertTrue(_is_b2b_upload("", "B2C", IN))
        self.assertFalse(_is_b2b_upload(None, None, IN))

    def test_outbound_is_always_b2b(self):
        self.assertTrue(_is_b2b_upload("airline", None, OUT))
        self.assertTrue(_is_b2b_upload(None, None, OUT))


if __name__ == "__main__":
    unittest.main()
