"""Unit tests for the Third Party statement normalizer — no DB, no network.

Every header and value here is from a REAL consolidator GDS export (40 columns). The
point of pinning them is that the alias map is one flat `{alias: canonical}` dict: a
string added under a second canonical field silently steals a column from the first, with
no error and no blank cell — just a wrong number in Commission income. Three such
collisions were live before these tests existed (`status`, `service_charge`,
`payment_mode`).

The Net Amount identity is the other anchor. It is what proves `Agent Commission` is
GROSS and `TDS Amount` is withheld from it, which is in turn what makes the
declared-vs-computed variance compare like with like.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import flat_statement as fs  # noqa: E402


# ── The real export ──────────────────────────────────────────────────────────
GDS_HEADERS = [
    "Week", "Booked Date", "Customer Name", "Customer ID", "Airline Name", "Airline Category",
    "S PNR", "Airline PNR", "CRS PNR", "TicketPrefix", "Ticket No", "Status", "Booking Type",
    "Username", "Pax Type", "First Name", "Last Name", "Sector", "Flight No", "Trip Type",
    "Travel Type", "Payment Mode", "Class", "Issuing Office", "Airline Code", "Date of Travel",
    "Basic Fare", "YQ Fare", "Other Taxes", "SSR Amount", "Reschedule Charges",
    "Agent Commission", "Incentive", "TDS Amount", "Service Charge", "SF", "GST On SF",
    "Agent Penalty", "Cancellation Markup", "Net Amount",
]

# Turkish Airlines: no commission, a service fee and its GST.
ROW_TURKISH = [
    "08-15TH AUG 26", "08-08-2026", "TRIUMPHH TRAVEL N MORE PRIVATE", "2102611",
    "TURKISH AIRLINES", "INTERNATIONAL", " ", "", "", "235", "4848358656", "CONFIRMED",
    "", "", "", "MR AJAY", "", "DEL/IST/MAD/MLA/IST/DEL", "717", "", "", "", "", "", "",
    "08-08-2026", "66250", "0", "23069", "", "", "0", "", "0", "", "100", "18", "", "", "89437",
]

# Etihad: the row that proves the TDS relationship — 5.7144 is exactly 2% of 285.72, and
# the identity only closes if the commission is SUBTRACTED and the TDS ADDED BACK.
ROW_ETIHAD = [
    "08-15TH AUG 26", "13-08-2026", "TRIUMPHH TRAVEL N MORE PRIVATE", "2102611",
    "ETIHAD AIRWAYS", "INTERNATIONAL", "", "", "", "607", "5808675862", "CONFIRMED",
    "", "", "", "MR ASHOK KUMAR", "", "JAI/JMK", "329", "", "", "", "", "", "",
    "24-08-2026", "31670", "0", "21544", "", "", "285.72", "", "5.7144", "0", "", "", "", "",
    "52933.9944",
]


def build(headers, values, slug="tp-gds"):
    return fs.get(slug).build_row(dict(zip(headers, values)), headers)


def net_from_components(d):
    """The vendor's own Net Amount, recomputed from the columns it prints."""
    f = lambda k: float(d.get(k) or 0)  # noqa: E731
    return (f("base_fare") + f("yq") + f("other_taxes") + f("ssr_amount") + f("reschedule_charges")
            - f("commission_amount") - f("incentive_amount") + f("tds")
            + f("service_charge") + f("service_fee") + f("gst_on_sf")
            + f("agent_penalty") + f("cancellation_markup"))


class TestGdsColumnMapping(unittest.TestCase):
    def test_every_real_header_maps(self):
        colmap = fs.get("tp-gds").build_col_map(GDS_HEADERS)
        unmapped = [h for h in GDS_HEADERS if h not in colmap]
        self.assertEqual(unmapped, [], f"unmapped real-export headers: {unmapped}")

    def test_money_headers_map_to_the_named_field(self):
        """The regression that mattered: every one of these missed before the rewrite, so
        the rows imported with no fare, no tax and no commission to calculate on."""
        colmap = fs.get("tp-gds").build_col_map(GDS_HEADERS)
        for header, field in [
            ("Basic Fare", "base_fare"), ("YQ Fare", "yq"), ("Other Taxes", "other_taxes"),
            ("SSR Amount", "ssr_amount"), ("Reschedule Charges", "reschedule_charges"),
            ("Agent Commission", "commission_amount"), ("Incentive", "incentive_amount"),
            ("TDS Amount", "tds"), ("Service Charge", "service_charge"), ("SF", "service_fee"),
            ("GST On SF", "gst_on_sf"), ("Agent Penalty", "agent_penalty"),
            ("Cancellation Markup", "cancellation_markup"), ("Net Amount", "net_amount"),
        ]:
            self.assertEqual(colmap.get(header), field, f"{header!r} -> {colmap.get(header)!r}")

    def test_identity_headers_map_to_the_named_field(self):
        colmap = fs.get("tp-gds").build_col_map(GDS_HEADERS)
        for header, field in [
            ("Booked Date", "booking_date"), ("Date of Travel", "travel_date"),
            ("Airline Name", "airline_name"), ("Airline Code", "airline_code"),
            ("Airline Category", "segment_type"), ("TicketPrefix", "ticket_prefix"),
            ("Ticket No", "ticket_number"), ("S PNR", "pnr"), ("CRS PNR", "gds_pnr"),
            ("Airline PNR", "airline_pnr"), ("Class", "booking_class"), ("Sector", "sector"),
            ("Payment Mode", "payment_method"),
        ]:
            self.assertEqual(colmap.get(header), field, f"{header!r} -> {colmap.get(header)!r}")

    def test_status_is_the_ticket_status_not_the_payment_status(self):
        """`Status` used to be claimed by `payment_status`, so the issue/refund/skip policy
        saw nothing at all and every cancelled ticket would have been priced as a sale."""
        colmap = fs.get("tp-gds").build_col_map(GDS_HEADERS)
        self.assertEqual(colmap.get("Status"), "ticket_status")

    def test_service_charge_is_not_markup(self):
        """`service_charge` was an alias of `markup`. They are different invoice lines and
        both appear in the Net Amount identity."""
        colmap = fs.get("tp-gds").build_col_map(["Service Charge", "Markup"])
        self.assertEqual(colmap.get("Service Charge"), "service_charge")
        self.assertEqual(colmap.get("Markup"), "markup")

    def test_legacy_superset_still_parses(self):
        """The pre-existing speculative schema is kept so another consolidator's file, and
        any batch uploaded before the rewrite, still maps exactly as it did."""
        legacy = ["Transaction Date", "Issue Date", "Travel Date", "PNR", "GDS PNR", "Ticket No",
                  "Type", "Airline", "Sector", "Flight No", "Passenger", "Pax", "Class",
                  "Base Fare", "Taxes", "YQ", "Total Fare", "Currency", "Commission", "Comm %",
                  "Markup", "Service Fee", "TDS", "Net Amount", "Invoice No", "Agency Code",
                  "Consolidator", "GDS", "Payment Status", "Remarks"]
        colmap = fs.get("tp-gds").build_col_map(legacy)
        self.assertEqual([h for h in legacy if h not in colmap], [])

    def test_unknown_headers_reach_raw_data_only(self):
        out = build(["Ticket No", "Some Vendor Column"], ["123", "keep me"])
        self.assertNotIn("some_vendor_column", out["data"])
        self.assertEqual(out["raw_data"]["Some Vendor Column"], "keep me")


class TestAliasIntegrity(unittest.TestCase):
    """Structural guards. `register` raises on violation, so these assert the guard exists
    rather than re-deriving it — but they name the failure if someone removes the check."""

    def test_no_alias_claims_two_canonical_fields(self):
        for name, aliases in (("tp-gds", fs._TP_GDS_ALIASES), ("tp-lcc", fs._TP_LCC_ALIASES)):
            flat = [a for names in aliases.values() for a in names]
            dupes = sorted({a for a in flat if flat.count(a) > 1})
            self.assertEqual(dupes, [], f"{name}: aliases claimed by two fields: {dupes}")

    def test_every_template_header_reads_back(self):
        """The template is what users are told to fill in; a header it emits that the
        parser cannot read silently drops that column."""
        for slug, display in (("tp-gds", fs.TP_GDS_DISPLAY), ("tp-lcc", fs.TP_LCC_DISPLAY)):
            colmap = fs.get(slug).build_col_map([c["header"] for c in display])
            broken = [c["header"] for c in display if colmap.get(c["header"]) != c["field"]]
            self.assertEqual(broken, [], f"{slug}: headers that do not round-trip: {broken}")

    def test_register_rejects_a_colliding_alias(self):
        with self.assertRaises(ValueError):
            fs.register("__test_collision", [("a", "A"), ("b", "B")],
                        {"a": ["a", "shared"], "b": ["b", "shared"]}, "test")

    def test_register_rejects_a_header_that_cannot_read_back(self):
        with self.assertRaises(ValueError):
            fs.register("__test_roundtrip", [("a", "Not An Alias")], {"a": ["a"]}, "test")


class TestValueCoercion(unittest.TestCase):
    def test_dates_become_iso(self):
        self.assertEqual(fs.to_iso_date("08-08-2026"), "2026-08-08")
        self.assertEqual(fs.to_iso_date("24-08-2026"), "2026-08-24")
        self.assertEqual(fs.to_iso_date("2026-08-24"), "2026-08-24")
        self.assertEqual(fs.to_iso_date("24/08/2026"), "2026-08-24")
        self.assertEqual(fs.to_iso_date("24-Aug-2026"), "2026-08-24")

    def test_day_comes_first(self):
        """13-08-2026 is 13 August. Month-first would make it invalid, and would silently
        misread every ambiguous date in the first twelve days of a month."""
        self.assertEqual(fs.to_iso_date("13-08-2026"), "2026-08-13")
        self.assertEqual(fs.to_iso_date("05-09-2026"), "2026-09-05")

    def test_unparseable_date_is_none_not_a_guess(self):
        for junk in ("", "   ", "n/a", "TBA", None):
            self.assertIsNone(fs.to_iso_date(junk))

    def test_numbers_lose_their_formatting(self):
        self.assertEqual(fs.to_number_str("1,23,456.78"), "123456.78")
        self.assertEqual(fs.to_number_str(" 66250 "), "66250")
        self.assertEqual(fs.to_number_str("₹ 89,437.00"), "89437.00")
        self.assertEqual(fs.to_number_str("(285.72)"), "-285.72")
        self.assertEqual(fs.to_number_str("285.72-"), "-285.72")
        self.assertEqual(fs.to_number_str("0"), "0")

    def test_non_numbers_are_none(self):
        for junk in ("", "N/A", "-", "abc", None):
            self.assertIsNone(fs.to_number_str(junk))

    def test_amounts_keep_full_precision(self):
        """5.7144 is a 2% TDS on 285.72. Rounding it here would break the identity."""
        self.assertEqual(fs.to_number_str("5.7144"), "5.7144")
        self.assertEqual(fs.to_number_str("52,933.9944"), "52933.9944")


class TestDerivedFields(unittest.TestCase):
    def test_passenger_name_joins_first_and_last(self):
        """Two source columns cannot both map to `passenger_name` — build_col_map keeps the
        first and drops the second — so the surname is recovered here or not at all."""
        d = build(["First Name", "Last Name"], ["MS ANU", "FNU"])["data"]
        self.assertEqual(d["passenger_name"], "MS ANU FNU")

    def test_passenger_name_survives_a_missing_surname(self):
        d = build(["First Name", "Last Name"], ["MR AJAY", ""])["data"]
        self.assertEqual(d["passenger_name"], "MR AJAY")

    def test_an_explicit_passenger_column_is_not_overwritten(self):
        d = build(["Passenger", "First Name"], ["FULL NAME HERE", "IGNORED"])["data"]
        self.assertEqual(d["passenger_name"], "FULL NAME HERE")

    def test_issue_date_falls_back_to_booked_date_and_says_so(self):
        """The export has no ticketing-date column, and deal validity keys off the issue
        date. The assumption is recorded so the diagnosis popup can show it."""
        d = build(GDS_HEADERS, ROW_TURKISH)["data"]
        self.assertEqual(d["issue_date"], "2026-08-08")
        self.assertEqual(d["issue_date_source"], "booked_date")

    def test_an_explicit_issue_date_wins(self):
        d = build(["Issue Date", "Booked Date"], ["01-08-2026", "08-08-2026"])["data"]
        self.assertEqual(d["issue_date"], "2026-08-01")
        self.assertNotIn("issue_date_source", d)

    def test_total_fare_is_derived_for_plb_accrual(self):
        """plb_accrual sums `total_fare` for gross revenue; the export has no such column,
        so without this a third-party statement contributes a gross of zero."""
        d = build(GDS_HEADERS, ROW_TURKISH)["data"]
        self.assertEqual(float(d["total_fare"]), 66250 + 0 + 23069)
        self.assertEqual(d["total_fare_source"], "derived")

    def test_raw_data_keeps_the_original_strings(self):
        """Reprocess re-runs the parser over raw_data, so it must stay verbatim."""
        raw = build(GDS_HEADERS, ROW_TURKISH)["raw_data"]
        self.assertEqual(raw["Booked Date"], "08-08-2026")
        self.assertEqual(raw["Net Amount"], "89437")


class TestNetAmountIdentity(unittest.TestCase):
    """Net = Basic + YQ + Other Taxes + SSR + Reschedule
             - Agent Commission - Incentive + TDS
             + Service Charge + SF + GST On SF + Agent Penalty + Cancellation Markup"""

    def test_turkish_row_closes(self):
        d = build(GDS_HEADERS, ROW_TURKISH)["data"]
        self.assertAlmostEqual(net_from_components(d), float(d["net_amount"]), places=4)
        self.assertEqual(float(d["net_amount"]), 89437.0)

    def test_etihad_row_closes_and_proves_the_tds_relationship(self):
        d = build(GDS_HEADERS, ROW_ETIHAD)["data"]
        self.assertAlmostEqual(net_from_components(d), float(d["net_amount"]), places=4)
        commission, tds = float(d["commission_amount"]), float(d["tds"])
        self.assertAlmostEqual(tds, commission * 0.02, places=4)

    def test_commission_is_gross_of_tds(self):
        """A variance that netted the TDS off first would print a phantom 2% shortfall on
        every commission-bearing row, so the direction of this is load-bearing."""
        d = build(GDS_HEADERS, ROW_ETIHAD)["data"]
        gross, tds = float(d["commission_amount"]), float(d["tds"])
        cash_received = gross - tds
        self.assertAlmostEqual(gross, 285.72, places=4)
        self.assertAlmostEqual(cash_received, 280.0056, places=4)

    def test_a_comma_formatted_file_still_closes(self):
        values = list(ROW_TURKISH)
        values[GDS_HEADERS.index("Basic Fare")] = "66,250.00"
        values[GDS_HEADERS.index("Other Taxes")] = "23,069.00"
        values[GDS_HEADERS.index("Net Amount")] = "89,437.00"
        d = build(GDS_HEADERS, values)["data"]
        self.assertAlmostEqual(net_from_components(d), 89437.0, places=4)


class TestSourceFormat(unittest.TestCase):
    def test_current_labels_are_declared(self):
        """`CURRENT_SOURCE_FORMATS` is what tells a batch it predates the real schema and
        should be reprocessed; a label that drifts from the builder's makes every batch
        look stale (or none of them)."""
        for slug, label in fs.CURRENT_SOURCE_FORMATS.items():
            self.assertEqual(fs.get(slug)._fmt, label)

    def test_a_parsed_row_carries_the_current_label(self):
        self.assertEqual(build(GDS_HEADERS, ROW_TURKISH)["source_format"], "third-party-gds-v2")


if __name__ == "__main__":
    unittest.main()
