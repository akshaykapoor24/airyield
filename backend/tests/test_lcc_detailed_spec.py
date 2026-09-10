"""The LCC Detailed standard column spec.

This spec is the contract between three things that must not drift apart: the template
a user downloads, the mapping wizard's auto-match, and the typed columns rows land in.
Widening it for account-style exports (Air India Express) touched all three, so what is
guarded here is mostly what growing it must NOT break — the template's existing column
order, the green "this is the template" banner for a file filled in against the old
129 columns, and the canonical alias map the other statement types share.

No DB, no network — the spec is pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import lcc_detailed_spec as spec  # noqa: E402
from app.services.lcc_statement import _ALIAS_TO_CANON, LCC_ALIASES  # noqa: E402


# The 27 core headers as they stood before the account columns were appended. Their
# order is the template's and the drill-in grid's, so it is a compatibility surface.
LEGACY_CORE = [
    "Transaction Date", "Name", "PaymentDtm", "PaymentMethodCode", "PaymentAmount",
    "PaymentNumber", "BookingDate", "RecordLocator", "SourceOrganizationCode",
    "BookingPromoCode", "ReceivedBy", "SourceAgentCode", "International",
    "CurrencyCode", "ProductClass", "PaxCount", "Name1", "EmailAddress", "HomePhone",
    "GDS_recordcode", "GDS_recordlocator", "GDS_BookingSystemCode", "PaymentStatus",
    "Total", "BaseFare", "OtherFeeTotal", "OtherSSRTotal",
]

AIX_PAX_COLUMNS = [
    "sourceOrganization", "organizationName", "BookingDate", "BookingTime",
    "RecordLocator", "PaxFirstName", "PaxLastName", "PaxType", "Depart_Station",
    "Arrive_Station", "DepartureDate", "DepartureCarrierCode", "FlightNumber",
    "CurrencyCode", "BaseFare", "Tax", "TransactionFee", "OtherServices", "TotalFare",
]

AIX_ACCOUNT_COLUMNS = [
    "SourceOrganization", "OrganizationName", "AccountTransactionID", "ACAmount",
    "TransactionDate", "AccountTransactionType", "PaymentMethodCode", "Reference",
    "PNR", "ParentPNR", "CurrencyCode", "ForeignAmount", "ForeignCurrencyCode",
    "BookingContactNumber", "Note", "EmailAddress", "GSTCompanyName", "GSTNumber",
    "GSTEmailAddress", "BookingPromoCode", "SSRCode", "FeeCode", "CreatedAgentCode",
]


class TestShape(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(spec.CORE_COLUMNS), 39)
        self.assertEqual(len(spec.LCC_STANDARD_COLUMNS), 141)
        self.assertEqual(len(spec.LCC_STANDARD_HEADERS), 141)

    def test_headers_and_fields_are_unique(self):
        headers = spec.LCC_STANDARD_HEADERS
        fields = [c["field"] for c in spec.LCC_STANDARD_COLUMNS]
        self.assertEqual(len(headers), len(set(headers)))
        self.assertEqual(len(fields), len(set(fields)))

    def test_legacy_core_order_is_untouched(self):
        """New columns are APPENDED. Inserting one would silently reshuffle both the
        downloadable template and the drill-in grid for every existing user."""
        got = [c["header"] for c in spec.CORE_COLUMNS][:len(LEGACY_CORE)]
        self.assertEqual(got, LEGACY_CORE)

    def test_maxlens_fit_the_real_values(self):
        """`_coerce` TRUNCATES silently rather than raising, so a column one character
        too short loses data without a word anywhere."""
        by_field = {c["field"]: c for c in spec.CORE_COLUMNS}
        worst = {
            "gst_number": "07AAACO2563P1Z3",              # a GSTIN is 15
            "transaction_type": "PPAccountDebitForPayment",
            "fee_code": "SEAT,VFPF",                       # a LIST, not a code
            "ssr_code": "SEAT,VFPF",
            "parent_pnr": "DB5MNK",
            "pax_type": "ADT",
            "account_transaction_id": "58849215",
        }
        for field, value in worst.items():
            maxlen = by_field[field]["maxlen"]
            self.assertGreaterEqual(maxlen, len(value), f"{field} truncates {value!r}")
            self.assertEqual(spec._coerce("str", value, maxlen), value)


class TestTemplateMatch(unittest.TestCase):
    """`is_template_match` drives the wizard's green "looks like the standard
    template" banner. Keyed as "do you have all of OURS" it would go amber for every
    existing user the moment the template grew, on a file that still maps perfectly."""

    def test_the_current_template_matches(self):
        _, _, tmpl = spec.suggest_mapping(spec.LCC_STANDARD_HEADERS)
        self.assertTrue(tmpl)

    def test_a_file_filled_against_the_old_129_columns_still_matches(self):
        legacy = LEGACY_CORE + spec._TAX_CODES + [
            f"{o} Leg{suffix}"
            for o in ("First", "Second", "Third", "Fourth", "Fifth")
            for suffix in ("", " Flight No", " Dep Date")
        ]
        self.assertEqual(len(legacy), 129)
        mapping, matched, tmpl = spec.suggest_mapping(legacy)
        self.assertTrue(tmpl, "the previous template stopped being recognised")
        self.assertEqual(matched, 129)

    def test_a_raw_airline_export_is_not_a_template_match(self):
        for cols in (AIX_PAX_COLUMNS, AIX_ACCOUNT_COLUMNS):
            _, _, tmpl = spec.suggest_mapping(cols)
            self.assertFalse(tmpl)

    def test_a_handful_of_coincidental_columns_is_not_a_match(self):
        _, _, tmpl = spec.suggest_mapping(["Name", "Total", "CurrencyCode"])
        self.assertFalse(tmpl)


class TestAutoMapping(unittest.TestCase):
    def test_account_export_maps_its_own_headers(self):
        mapping, _, _ = spec.suggest_mapping(AIX_ACCOUNT_COLUMNS)
        expected = {
            "record_locator": "PNR",                      # the join key
            # The transaction amount, and it lands in `total` because that is the
            # field `_bill_kind` and the invoice read. NOT ACAmount, which is a
            # constant account identifier.
            "total": "ForeignAmount",
            "transaction_type": "AccountTransactionType",
            "parent_pnr": "ParentPNR",
            "gst_number": "GSTNumber",
            "gst_company_name": "GSTCompanyName",
            "gst_email": "GSTEmailAddress",
            "note": "Note",
            "fee_code": "FeeCode",
            "ssr_code": "SSRCode",
            "foreign_currency_code": "ForeignCurrencyCode",
            "account_transaction_id": "AccountTransactionID",
            "source_organization_code": "SourceOrganization",
            "name": "OrganizationName",
            "source_agent_code": "CreatedAgentCode",
            "home_phone": "BookingContactNumber",
            "transaction_date": "TransactionDate",
        }
        for field, col in expected.items():
            self.assertEqual(mapping.get(field), col, f"{field} did not map")

    def test_acamount_is_never_treated_as_money(self):
        """It is a constant account identifier (8894431 on every sampled row)."""
        mapping, _, _ = spec.suggest_mapping(AIX_ACCOUNT_COLUMNS)
        self.assertNotIn("ACAmount", mapping.values())

    def test_passenger_export_maps_its_money(self):
        mapping, _, _ = spec.suggest_mapping(AIX_PAX_COLUMNS)
        self.assertEqual(mapping.get("total"), "TotalFare")
        self.assertEqual(mapping.get("base_fare"), "BaseFare")
        self.assertEqual(mapping.get("taxes_total"), "Tax")
        self.assertEqual(mapping.get("other_fee_total"), "TransactionFee")
        self.assertEqual(mapping.get("other_ssr_total"), "OtherServices")
        self.assertEqual(mapping.get("record_locator"), "RecordLocator")
        self.assertEqual(mapping.get("pax_type"), "PaxType")

    def test_total_is_mapped_or_nothing_is_billable(self):
        """`_bill_kind` reads `total` and nothing else. Unmapped, every row of an AIX
        upload classifies as a payment and the billing worklist shows zero."""
        mapping, _, _ = spec.suggest_mapping(AIX_PAX_COLUMNS)
        self.assertIn("total", mapping)


class TestSpecAliasesAreLocal(unittest.TestCase):
    """`lcc_statement._ALIAS_TO_CANON` is built by flattening LCC_ALIASES
    last-writer-wins. Adding "pnr" there would re-point it away from the canonical
    `pnr` field, and "organizationname" would steal it from `organization_name` —
    so these fallbacks live in the spec instead."""

    def test_canonical_alias_map_is_untouched(self):
        self.assertEqual(_ALIAS_TO_CANON["pnr"], "pnr")
        self.assertEqual(_ALIAS_TO_CANON["organizationname"], "organization_name")
        self.assertEqual(_ALIAS_TO_CANON["sourceorganization"], "source_organization")
        self.assertEqual(_ALIAS_TO_CANON["acamount"], "transaction_amount")

    def test_spec_aliases_did_not_leak_into_lcc_aliases(self):
        for field, aliases in spec._SPEC_ALIASES.items():
            for alias in aliases:
                self.assertNotIn(
                    alias, LCC_ALIASES.get(field, []),
                    f"{alias!r} was added to LCC_ALIASES as well as _SPEC_ALIASES",
                )


class TestTaxesTotalPrecedence(unittest.TestCase):
    """An account-style export ships one lump-sum `Tax` column and no per-code
    columns. Deriving `taxes_total` unconditionally overwrote the only tax figure the
    file had."""

    def test_a_mapped_lump_sum_survives(self):
        row = spec.build_typed_row({"Tax": "2510", "TotalFare": "9763"},
                                   {"taxes_total": "Tax", "total": "TotalFare"})
        self.assertEqual(row["taxes_total"], Decimal("2510"))

    def test_an_unmapped_one_still_derives_from_the_codes(self):
        row = spec.build_typed_row({"YX": "100", "UDF": "50", "Total": "1000"},
                                   {"tax_yx": "YX", "tax_udf": "UDF", "total": "Total"})
        self.assertEqual(row["taxes_total"], Decimal("150"))

    def test_a_mapped_zero_is_not_overwritten(self):
        """0 is a real answer — "this booking was taxed nothing" — and `is None` is
        what distinguishes it from "the file did not say"."""
        row = spec.build_typed_row({"Tax": "0", "YX": "100"},
                                   {"taxes_total": "Tax", "tax_yx": "YX"})
        self.assertEqual(row["taxes_total"], Decimal("0"))


class TestDatetimes(unittest.TestCase):
    def test_offset_stamped_values_come_back_naive(self):
        """Every DateTime column here is naive. asyncpg refuses an aware value for
        one, and `_flush`'s row-by-row fallback would turn that refusal into a batch
        that reports "completed" with zero rows."""
        got = spec._to_datetime("2026-08-15T01:49:20.513+0000")
        self.assertIsNone(got.tzinfo)
        self.assertEqual((got.year, got.month, got.day, got.hour), (2026, 8, 15, 1))

    def test_offsets_are_converted_not_merely_stripped(self):
        got = spec._to_datetime("2026-08-15T07:19:20+0530")
        self.assertIsNone(got.tzinfo)
        self.assertEqual((got.hour, got.minute), (1, 49))   # 07:19 IST is 01:49 UTC

    def test_aix_date_formats(self):
        cases = {
            "01 Sep 26 13:41:15": (2026, 9, 1, 13, 41, 15),
            "01 Sep 26": (2026, 9, 1, 0, 0, 0),
            "2026-09-02": (2026, 9, 2, 0, 0, 0),
            # what an Excel date cell becomes once the reader stringifies it
            "2026-09-01 00:00:00": (2026, 9, 1, 0, 0, 0),
        }
        for text, expected in cases.items():
            d = spec._to_datetime(text)
            self.assertIsNotNone(d, text)
            self.assertEqual(
                (d.year, d.month, d.day, d.hour, d.minute, d.second), expected, text)

    def test_day_first_is_still_honoured(self):
        d = spec._to_datetime("03/04/2026")
        self.assertEqual((d.day, d.month), (3, 4))


class TestFilters(unittest.TestCase):
    def test_every_filter_field_is_a_real_column_or_the_pseudo_one(self):
        from app.models.lcc_detailed import LccDetailed
        for f in spec.FILTERS:
            if f["field"] == spec.SEGMENTS_FILTER_FIELD:
                continue
            self.assertTrue(hasattr(LccDetailed, f["field"]),
                            f"filter {f['field']} has no column")

    def test_fee_code_is_text_not_a_facet(self):
        """Its real values are comma-joined lists ("SEAT,VFPF"), so a distinct-value
        dropdown would offer combinations as though they were codes."""
        fee = next(f for f in spec.FILTERS if f["field"] == "fee_code")
        self.assertEqual(fee["type"], "text")

    def test_summary_fields_are_all_numeric_columns(self):
        by_field = {c["field"]: c for c in spec.CORE_COLUMNS}
        for s in spec.SUMMARY_FIELDS:
            col = by_field.get(s["field"])
            if col is not None:
                self.assertEqual(col["dtype"], "numeric", s["field"])


class TestRowShape(unittest.TestCase):
    def test_built_rows_share_one_key_set(self):
        """The worker bulk-inserts with executemany, which needs every row to carry
        the same keys."""
        a = spec.build_typed_row({"Total": "100"}, {"total": "Total"})
        b = spec.build_typed_row({"RecordLocator": "ABC123"}, {"record_locator": "RecordLocator"})
        self.assertEqual(set(a), set(b))

    def test_derived_discriminators_are_always_present(self):
        row = spec.build_typed_row({"Total": "100"}, {"total": "Total"})
        self.assertIn("row_kind", row)
        self.assertIn("movement_kind", row)


if __name__ == "__main__":
    unittest.main()
