"""Third-party statement service fee vs the agency's vendor service charge. Pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from types import SimpleNamespace as N

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import statement_sf_check as c  # noqa: E402


def agency(t, v, g="exclusive"):
    return N(vendor_service_charge_type=t, vendor_service_charge_value=v, vendor_service_charge_gst=g)


class SfCheckTest(unittest.TestCase):
    def test_matching_fixed_fee(self):
        out = c.check_row({"ticket_status": "CONFIRMED", "service_fee": "100", "gst_on_sf": "18"},
                          c.agreement_for(agency("fixed", 100)))
        self.assertEqual({k: v["status"] for k, v in out["__checks__"].items()},
                         {"service_fee": "ok", "gst_on_sf": "ok"})

    def test_overcharge_is_flagged_with_expected(self):
        out = c.check_row({"ticket_status": "CONFIRMED", "service_fee": "150", "gst_on_sf": "27"},
                          c.agreement_for(agency("fixed", 100)))
        self.assertEqual(out["__checks__"]["service_fee"]["status"], "mismatch")
        self.assertEqual(out["__checks__"]["gst_on_sf"]["expected"], "₹18")

    def test_inclusive_agreement_backs_tax_out(self):
        out = c.check_row({"ticket_status": "CONFIRMED", "service_fee": "100", "gst_on_sf": "18"},
                          c.agreement_for(agency("fixed", 118, "inclusive")))
        self.assertTrue(all(v["status"] == "ok" for v in out["__checks__"].values()))

    def test_percentage_is_of_basic_fare(self):
        out = c.check_row({"ticket_status": "CONFIRMED", "base_fare": "10000", "service_fee": "100",
                           "gst_on_sf": "18"}, c.agreement_for(agency("percentage", 1)))
        self.assertEqual(out["__checks__"]["service_fee"]["status"], "ok")

    def test_cancelled_is_a_refund_and_not_checked(self):
        out = c.check_row({"ticket_status": "CANCELLED", "service_fee": "500", "gst_on_sf": "90"},
                          c.agreement_for(agency("fixed", 100)))
        self.assertEqual(out, {"__kind__": "refund"})

    def test_no_agreement_no_check(self):
        self.assertIsNone(c.agreement_for(agency(None, None)))
        out = c.check_row({"ticket_status": "CONFIRMED", "service_fee": "100"}, None)
        self.assertNotIn("__checks__", out)

    def test_service_charge_column_is_used_when_sf_is_blank(self):
        out = c.check_row({"ticket_status": "", "service_charge": "100"}, c.agreement_for(agency("fixed", 100)))
        self.assertIn("service_charge", out["__checks__"])

    def test_summary(self):
        ag = c.agreement_for(agency("fixed", 100))
        rows = [c.check_row(d, ag) for d in (
            {"ticket_status": "CONFIRMED", "service_fee": "100", "gst_on_sf": "18"},
            {"ticket_status": "CONFIRMED", "service_fee": "150", "gst_on_sf": "27"},
            {"ticket_status": "CANCELLED", "service_fee": "500"},
        )]
        self.assertEqual(c.summarize(rows), {"issued": 2, "refunds": 1, "checked": 2, "mismatched": 1})


if __name__ == "__main__":
    unittest.main()
