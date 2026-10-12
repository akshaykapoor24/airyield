"""Agency credentials: airline must match the channel, LoB is always B2B, and an
XLS AGENCY_CODE resolves to one agency row. Pure — no DB.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.agency_airline import AirlineCatalog, lob_error  # noqa: E402
from app.services.agency_code import code_resolver  # noqa: E402


def catalog():
    rows = [("Air India", "AI"), ("IndiGo", "6E"), ("Vistara", "UK"), ("Untyped Air", "ZZ")]
    return AirlineCatalog(
        {n.lower(): (n, c) for n, c in rows},
        {c: (n, c) for n, c in rows},
        {"GDS": {"air india", "vistara"}, "LCC": {"indigo", "air india"}},
    )


class AirlineTest(unittest.TestCase):
    def test_blank_is_allowed(self):
        self.assertEqual(catalog().resolve("", "", "GDS"), (None, None))

    def test_name_or_code_fills_the_other(self):
        self.assertEqual(catalog().resolve("indigo", "", "LCC"), ("IndiGo", "6E"))
        self.assertEqual(catalog().resolve("", "uk", "GDS"), ("Vistara", "UK"))

    def test_wrong_channel_refused(self):
        with self.assertRaises(ValueError):
            catalog().resolve("IndiGo", "", "GDS")

    def test_both_types_valid_on_both(self):
        self.assertEqual(catalog().resolve("Air India", "", "GDS")[1], "AI")
        self.assertEqual(catalog().resolve("Air India", "", "LCC")[1], "AI")

    def test_untyped_or_unknown_refused(self):
        with self.assertRaises(ValueError):
            catalog().resolve("Untyped Air", "", "GDS")
        with self.assertRaises(ValueError):
            catalog().resolve("Nope", "", "GDS")

    def test_name_code_mismatch_refused(self):
        with self.assertRaises(ValueError):
            catalog().resolve("IndiGo", "AI", "LCC")

    def test_lob(self):
        self.assertIsNone(lob_error(""))
        self.assertIsNone(lob_error("b2b"))
        self.assertIsNotNone(lob_error("B2C"))


class CodeResolverTest(unittest.TestCase):
    def setUp(self):
        A = lambda i, code, ch: SimpleNamespace(id=i, agency_code=code, channels=ch)  # noqa: E731
        self.resolve = code_resolver([A(1, "AG-0001", "GDS"), A(2, "AG-0001", "LCC"), A(3, "AG-0002", "GDS")])

    def test_unique_code(self):
        self.assertEqual(self.resolve("ag-0002", None)[0].id, 3)

    def test_shared_code_needs_channel(self):
        self.assertIsNone(self.resolve("AG-0001", None)[0])
        self.assertEqual(self.resolve("AG-0001", "LCC")[0].id, 2)

    def test_unknown(self):
        self.assertIsNone(self.resolve("AG-9999", "GDS")[0])


if __name__ == "__main__":
    unittest.main()
