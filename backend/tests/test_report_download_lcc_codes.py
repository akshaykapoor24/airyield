"""Report download — LCC charge-code classifier.

Pinned: every code the LCC Detailed template can carry is classified (so seats and baggage
never inflate "Total Taxes"), sums keep "absent" distinct from zero, and JSON null is safe.

No DB, no network.  Run: python -m unittest test_report_download_lcc_codes   (from backend/tests)
"""
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import lcc_detailed_spec  # noqa: E402
from app.services.report_download import lcc_codes  # noqa: E402


class CoverageTests(unittest.TestCase):
    def test_every_template_code_is_classified_or_explicitly_unclassified(self):
        missing = [
            c for c in lcc_detailed_spec._TAX_CODES
            if lcc_codes.classify(c) == "unclassified" and c not in lcc_codes.UNCLASSIFIED
        ]
        self.assertEqual(missing, [])

    def test_buckets_are_disjoint(self):
        buckets = [lcc_codes.TAX, lcc_codes.ANCILLARY, lcc_codes.PENALTY, lcc_codes.FEE, lcc_codes.UNCLASSIFIED]
        for i, a in enumerate(buckets):
            for b in buckets[i + 1:]:
                self.assertFalse(a & b)


class ClassifyTests(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(lcc_codes.classify("GST"), "tax")
        self.assertEqual(lcc_codes.classify("udf"), "tax")
        self.assertEqual(lcc_codes.classify("SEAT"), "ancillary")
        self.assertEqual(lcc_codes.classify("XBPA"), "ancillary")
        self.assertEqual(lcc_codes.classify("CNX"), "penalty")
        self.assertEqual(lcc_codes.classify("CCF"), "fee")
        self.assertEqual(lcc_codes.classify("OVG"), "unclassified")
        self.assertEqual(lcc_codes.classify("ZZZZ"), "unclassified")
        self.assertEqual(lcc_codes.classify(None), "unclassified")

    def test_sort_codes_groups_by_class(self):
        self.assertEqual(lcc_codes.sort_codes(["SEAT", "cnx", "GST", "CCF", "OVG", "UDF", None, ""]),
                         ["GST", "UDF", "SEAT", "CNX", "CCF", "OVG"])


class SumsTests(unittest.TestCase):
    def test_sums_by_class_and_code(self):
        s = lcc_codes.sums([
            {"code": "GST", "amount": 250.5}, {"code": "UDF", "amount": "100"},
            {"code": "SEAT", "amount": 300}, {"code": "CNX", "amount": 3000},
            {"code": "CCF", "amount": 150}, {"code": "OVG", "amount": 20},
            {"code": "GST", "amount": 10}, {"code": "", "amount": 5}, {"code": "PSF", "amount": None},
        ])
        self.assertEqual(s.tax_total, Decimal("360.5"))
        self.assertEqual(s.ancillary, Decimal("300"))
        self.assertEqual(s.penalty, Decimal("3000"))
        self.assertEqual(s.fee, Decimal("150"))
        self.assertEqual(s.unclassified, Decimal("20"))
        self.assertEqual(s.code("gst"), Decimal("260.5"))
        self.assertIsNone(s.code("PSF"))
        self.assertEqual(s.unclassified_codes, ("OVG",))
        self.assertTrue(s.has_codes)

    def test_absent_class_is_none_not_zero(self):
        s = lcc_codes.sums([{"code": "GST", "amount": 5}])
        self.assertIsNone(s.ancillary)
        self.assertIsNone(s.penalty)

    def test_json_null_and_garbage(self):
        for value in (None, {}, "x", [None, "x", {"code": "GST", "amount": "abc"}]):
            with self.subTest(value=value):
                s = lcc_codes.sums(value)
                self.assertFalse(s.has_codes)
                self.assertIsNone(s.tax_total)


if __name__ == "__main__":
    unittest.main()
