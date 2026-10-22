"""Airline Master: the business type asked for on every new airline id.

No DB, no network — the rule lives in the request schemas and one pure helper the
spreadsheet import shares with them.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

from pydantic import ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas.tenant_airline import (  # noqa: E402
    TenantAirlineBulkCreate, TenantAirlineCreate, TenantAirlineUpdate,
    normalize_business_type,
)


class NormalizeTests(unittest.TestCase):
    def test_canonical_spelling(self):
        self.assertEqual(normalize_business_type(" b2c "), "B2C")
        self.assertEqual(normalize_business_type("mice"), "MICE")

    def test_blank_is_none(self):
        for v in (None, "", "   "):
            with self.subTest(value=v):
                self.assertIsNone(normalize_business_type(v))

    def test_unknown_is_refused(self):
        with self.assertRaises(ValueError):
            normalize_business_type("B2X")


class RequestSchemaTests(unittest.TestCase):
    def test_new_ids_must_say_their_business_type(self):
        with self.assertRaises(ValidationError):
            TenantAirlineBulkCreate(airline_id=1, ids=[{"ref_id": "6E-1"}])
        with self.assertRaises(ValidationError):
            TenantAirlineBulkCreate(airline_id=1, ids=[{"ref_id": "6E-1", "business_type": ""}])
        with self.assertRaises(ValidationError):
            TenantAirlineCreate(airline_id=1, ref_id="6E-1")

    def test_new_id_business_type_is_normalised(self):
        bulk = TenantAirlineBulkCreate(airline_id=1, ids=[{"ref_id": "6E-1", "business_type": "b2e"}])
        self.assertEqual(bulk.ids[0].business_type, "B2E")

    def test_update_leaves_it_alone_unless_sent(self):
        self.assertNotIn("business_type", TenantAirlineUpdate(is_active=False).model_dump(exclude_unset=True))
        self.assertEqual(TenantAirlineUpdate(business_type="b2b").business_type, "B2B")

    def test_update_cannot_clear_it(self):
        with self.assertRaises(ValidationError):
            TenantAirlineUpdate(business_type=None)
        with self.assertRaises(ValidationError):
            TenantAirlineUpdate(business_type="")


if __name__ == "__main__":
    unittest.main()
