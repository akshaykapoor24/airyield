"""Report download — the PII policy must classify every field a report could export.

Pinned: card data is never exported (not even with the PII option), identity/contact data is
opt-in, and every spec field / upload alias that looks sensitive is explicitly listed — so a
new supplier column cannot slip into a workbook unreviewed.

No DB, no network.  Run: python -m unittest test_report_download_pii   (from backend/tests)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402
from app.models.statement_row import STATEMENT_MODELS  # noqa: E402
from app.services import airline_adjustment_spec, flat_statement, lcc_detailed_spec, statement_spec, tp_api_spec  # noqa: E402
from app.services.report_download import pii  # noqa: E402


def _all_keys() -> set[str]:
    keys: set[str] = set()
    for slug in STATEMENT_MODELS:
        keys.update(c["field"] for c in statement_spec.columns(slug))
    keys.update(c["field"] for c in lcc_detailed_spec.CORE_COLUMNS)
    for kind in ("adm", "acm", "ra"):
        keys.update(airline_adjustment_spec.fields(kind))
    for mod in (tp_api_spec, flat_statement):
        for name in dir(mod):
            val = getattr(mod, name)
            if isinstance(val, dict) and "ALIAS" in name.upper():
                for k, v in val.items():
                    keys.add(str(k))
                    for x in (v if isinstance(v, (list, tuple, set, frozenset)) else [v]):
                        if isinstance(x, str):
                            keys.add(x)
    return keys


class ClassificationCoverageTests(unittest.TestCase):
    def test_every_sensitive_looking_field_is_explicitly_listed(self):
        unlisted = sorted(
            k for k in _all_keys()
            if pii.is_sensitive(k)
            and not pii.is_never(k)
            and pii.norm_key(k) not in pii.GATED
            and pii.norm_key(k) not in pii.ALLOWED_SENSITIVE
        )
        self.assertEqual(unlisted, [], "Classify these in services/report_download/pii.py")

    def test_lists_do_not_overlap(self):
        self.assertFalse(pii.NEVER & pii.GATED)
        self.assertFalse(pii.NEVER & pii.ALLOWED_SENSITIVE)
        self.assertFalse(pii.GATED & pii.ALLOWED_SENSITIVE)


class PolicyTests(unittest.TestCase):
    def test_card_data_never_exported_even_with_pii(self):
        for key in ("fop_details", "FOP_Details", "cc_auth", "cc_doexpiry", "Card Number", "pax_card_number_2", "CVV"):
            with self.subTest(key=key):
                self.assertFalse(pii.allowed(key, include_pii=True))
                self.assertFalse(pii.allowed(key, include_pii=False))

    def test_identity_and_contact_are_opt_in(self):
        for key in ("pan", "PAN No", "guardian_pan", "passport_no", "Passport Number", "mobile_number",
                    "Mobile", "email_address", "home_phone", "gst_email", "businessemailaddress",
                    "contact_email", "contact_phone", "entityaddressline1", "account_number"):
            with self.subTest(key=key):
                self.assertFalse(pii.allowed(key, include_pii=False))
                self.assertTrue(pii.allowed(key, include_pii=True))

    def test_look_alikes_are_allowed(self):
        for key in ("gstn", "gst_number", "gst_company_name", "cliententityname", "total_gst",
                    "cgst_amount", "gst_on_sf", "card_scheme", "pcc", "booking_pcc", "fop",
                    "account_name", "account_transaction_id"):
            with self.subTest(key=key):
                self.assertTrue(pii.allowed(key, include_pii=False))

    def test_unknown_look_alike_fails_closed(self):
        self.assertFalse(pii.allowed("passenger_mobile_2", include_pii=False))
        self.assertTrue(pii.allowed("passenger_mobile_2", include_pii=True))

    def test_ordinary_fields_allowed(self):
        for key in ("ticket_no", "pax_name", "company", "base_fare", "sectors", "ac_acct"):
            with self.subTest(key=key):
                self.assertTrue(pii.allowed(key, include_pii=False))


if __name__ == "__main__":
    unittest.main()
