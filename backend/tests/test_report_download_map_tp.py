"""Report download — Third Party GDS / LCC / API rows on the Combined sheet and TP detail sheets.

Pinned: types follow the commission / billing classifiers (void, refund, not-a-sale, TBO
MZ/RM credits, MMT retained-on-cancel), amounts are type-signed with U columns as magnitudes,
Counts In Net follows design §B.3 rules 8-9, the TP data flags fire, non-air API rows carry
no airline fields, identity fields need include_pii, and the de-dup / link keys are stable.

No DB, no network.  Run: python -m unittest test_report_download_map_tp   (from backend/tests)
"""
import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402
from app.services.report_download import columns as C  # noqa: E402
from app.services.report_download.mappers import base  # noqa: E402
from app.services.report_download.mappers import third_party as tp  # noqa: E402
from app.services.report_download.types import (  # noqa: E402
    DocKey, LinkResult, MapCtx, ReportOptions, SupplierSnap, UploadMeta,
)

GDS_V2 = "third-party-gds-v2"
LCC_V2 = "third-party-lcc-v2"


def _ctx(slug, *, include_pii=False, extra_keys=(), supplier=True):
    sup = SupplierSnap(supplier_id=42, name="Riya Travel", code="RIYA", branch="Mumbai") if supplier else None
    return MapCtx(
        upload=UploadMeta(source_key=slug, upload_id="b-1", file_name="stmt.xlsx",
                          uploaded_at=datetime(2026, 8, 3, 10, 0), supplier=sup),
        options=ReportOptions(include_pii=include_pii),
        extra_keys=tuple(extra_keys),
    )


def _row(data, *, source_format=GDS_V2, rid=7, **extra):
    return SimpleNamespace(id=rid, batch_id="b-1", source_file="stmt.xlsx",
                           uploaded_at=datetime(2026, 8, 3, 10, 0), data=data,
                           source_format=source_format, raw_data={}, **extra)


def _gds(**over):
    """Row 1 of the real 40-column export after ingest (net identity closes: 89437)."""
    d = {
        "week": "27-Jul-2026 to 02-Aug-2026", "booking_date": "2026-07-28",
        "issue_date": "2026-07-28", "issue_date_source": "booked_date",
        "travel_date": "2026-08-15", "customer_name": "ACME CORP",
        "airline_name": "AIR INDIA", "airline_master_name": "Air India", "airline_id": "12",
        "airline_code": "AI", "ticket_prefix": "98", "segment_type": "International",
        "pnr": "S1PNR", "airline_pnr": "AIPNR1", "gds_pnr": "CRS123",
        "ticket_number": "5805708071", "ticket_status": "CONFIRMED", "booking_type": "Online",
        "username": "riya.agent1", "issuing_office": "BOMRI28AA",
        "first_name": "RAHUL", "last_name": "SHARMA", "passenger_name": "RAHUL SHARMA",
        "sector": "BOM-LHR-BOM", "flight_number": "AI131", "booking_class": "Y",
        "payment_method": "Credit", "base_fare": "66250", "other_taxes": "23069",
        "total_fare": "89319.00", "total_fare_source": "derived",
        "service_charge": "100", "gst_on_sf": "18", "net_amount": "89437",
        "invoice_number": "INV/26/0001",
    }
    d.update(over)
    return d


def _api_mmt_flight(**over):
    d = {
        "booking_id": "NF7A1B2C3D", "invoice_number": "MMT/INV/77", "pnr": "Q8ZK2L",
        "booked_by": "ops@agency.in", "booking_status": "Confirmed",
        "product_type": "Flight", "intl_dom": "DOM", "passenger_name": "Neha Verma",
        "pax_count": "2", "transaction_date": "2026-07-30", "booking_date": "2026-07-29",
        "start_date": "2026-08-10", "payment_due_date": "2026-08-05",
        "airline_property_name": "IndiGo", "flight_number": "6E 2134",
        "origin_code": "DEL", "destination_code": "BOM", "booking_class": "S",
        "base_fare": "12000", "taxes": "1500", "total_paid_amount": "13508",
        "convenience_fee": "8", "payment_mode": "Wallet", "vendor": "MakeMyTrip",
    }
    d.update(over)
    return d


def _api_tbo(**over):
    d = {
        "invoice_number": "SM/2627/701490", "reference_no": "TBOB9214471937388143",
        "product_type": "Train", "passenger_name": "lovekush singh X 1", "pax_count": "1",
        "transaction_date": "2026-08-01", "base_fare": "335", "net_amount": "390",
        "convenience_fee": "35.40", "service_charges": "14.74", "vendor": "TBO",
    }
    d.update(over)
    return d


class GdsTypeAndNetTests(unittest.TestCase):
    def test_confirmed_sale_columns(self):
        out = tp.to_common("tp-gds", _row(_gds()), _ctx("tp-gds"))
        self.assertEqual(out["category"], C.CAT_TP)
        self.assertEqual(out["source_type"], "Third Party GDS")
        self.assertEqual(out["row_ref"], "third_party_gds:7")
        self.assertEqual(out["transaction_type"], C.SALE)
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        self.assertEqual(out["settled_with"], "Consolidator – Riya Travel (RIYA)")
        self.assertEqual(out["agent_signon"], "riya.agent1")
        self.assertEqual(out["airline_numeric"], "098")
        self.assertEqual(out["airline_code"], "AI")
        self.assertEqual(out["airline_name"], "Air India")
        self.assertEqual(out["product"], "Air")
        self.assertEqual(out["ticket_number"], "0985805708071")
        self.assertEqual(out["document_number"], "5805708071")
        self.assertEqual(out["source_txn_type"], "CONFIRMED")
        self.assertEqual(out["airline_pnr"], "AIPNR1")
        self.assertEqual(out["gds_ref"], "CRS123")
        self.assertEqual(out["invoice_ref"], "INV/26/0001")
        self.assertEqual(out["issue_date"], date(2026, 7, 28))
        self.assertEqual(out["travel_date"], date(2026, 8, 15))
        self.assertEqual(out["settlement_period"], "27-Jul-2026 to 02-Aug-2026")
        self.assertEqual(out["dom_intl"], "International")
        self.assertEqual(out["currency"], "INR")
        self.assertEqual(out["base_fare"], Decimal("66250"))
        self.assertEqual(out["total_taxes"], Decimal("23069"))
        self.assertEqual(out["gross_amount"], Decimal("89319.00"))
        self.assertEqual(out["service_fee"], Decimal("100"))
        self.assertEqual(out["gst_on_service"], Decimal("18"))
        self.assertEqual(out["net_payable"], Decimal("89437"))
        self.assertEqual(out["data_flags"], ["CURRENCY_ASSUMED", "TP_TOTAL_FARE_DERIVED"])

    def test_commission_row_and_derived_taxes(self):
        # Row 2 of the real export: 31670 + 21544 − 285.72 + 5.7144 = 52933.9944.
        d = _gds(base_fare="31670", other_taxes="21544", yq="0", commission_amount="285.72",
                 tds="5.7144", service_charge=None, gst_on_sf=None, net_amount="52933.9944",
                 currency="inr")
        out = tp.to_common("tp-gds", _row(d), _ctx("tp-gds"))
        self.assertEqual(out["commission"], Decimal("285.72"))
        self.assertEqual(out["tds"], Decimal("5.7144"))
        self.assertEqual(out["total_taxes"], Decimal("21544"))
        self.assertEqual(out["currency"], "INR")
        self.assertNotIn("CURRENCY_ASSUMED", out["data_flags"])
        self.assertNotIn("TP_NET_IDENTITY_MISMATCH", out["data_flags"])

    def test_void_with_full_net_is_verify(self):
        d = _gds(ticket_status="VOID")
        out = tp.to_common("tp-gds", _row(d), _ctx("tp-gds"))
        self.assertEqual(out["transaction_type"], C.VOID)
        self.assertEqual(out["counts_in_net"], C.NET_CANCELLED_VERIFY)
        self.assertEqual(out["net_payable"], Decimal("89437"))      # VOID: as stored

    def test_negative_cancellation_line_is_a_counted_credit(self):
        # The local consolidator export prints a cancellation as its own negative line
        # (−86,399 against the +89,437 sale). That line is the credit, so it must count.
        d = _gds(ticket_status="CANCELLED", net_amount="-86399")
        out = tp.to_common("tp-gds", _row(d), _ctx("tp-gds"))
        self.assertEqual(out["transaction_type"], C.REFUND)
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        self.assertEqual(out["net_payable"], Decimal("-86399"))

    def test_void_with_net_within_penalty_counts(self):
        d = _gds(ticket_status="Cancelled", base_fare="0", other_taxes="0", total_fare=None,
                 total_fare_source=None, service_charge=None, gst_on_sf=None,
                 agent_penalty="3000", cancellation_markup="500", net_amount="3500.80")
        out = tp.to_common("tp-gds", _row(d), _ctx("tp-gds"))
        self.assertEqual(out["transaction_type"], C.VOID)
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        self.assertEqual(out["penalty"], Decimal("3500"))

    def test_refunded_status_is_negative_refund(self):
        d = _gds(ticket_status="REFUNDED", agent_penalty="-3000", reschedule_charges="250")
        out = tp.to_common("tp-gds", _row(d), _ctx("tp-gds"))
        self.assertEqual(out["transaction_type"], C.REFUND)
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        self.assertEqual(out["net_payable"], Decimal("-89437"))
        self.assertEqual(out["base_fare"], Decimal("-66250"))
        self.assertEqual(out["gross_amount"], Decimal("-89319.00"))
        self.assertEqual(out["service_fee"], Decimal("100"))           # U: magnitude
        self.assertEqual(out["penalty"], Decimal("2750"))              # |−3000 + 250|

    def test_not_a_sale_statuses(self):
        for status in ("PENDING", "ON HOLD", "FAILED", "EXPIRED"):
            with self.subTest(status=status):
                out = tp.to_common("tp-gds", _row(_gds(ticket_status=status)), _ctx("tp-gds"))
                self.assertEqual(out["transaction_type"], C.NON_BILLABLE)
                self.assertEqual(out["counts_in_net"], C.NET_NOT_A_SALE)

    def test_unrecognised_status_is_flagged_sale(self):
        out = tp.to_common("tp-gds", _row(_gds(ticket_status="REISSUED")), _ctx("tp-gds"))
        self.assertEqual(out["transaction_type"], C.SALE)
        self.assertIn("TP_UNRECOGNISED_STATUS", out["data_flags"])
        blank = tp.to_common("tp-gds", _row(_gds(ticket_status=None)), _ctx("tp-gds"))
        self.assertEqual(blank["transaction_type"], C.SALE)
        self.assertNotIn("TP_UNRECOGNISED_STATUS", blank["data_flags"])

    def test_tp_canon(self):
        self.assertEqual(tp.tp_canon("tp-gds", {"ticket_status": "Voided"}), C.VOID)
        self.assertEqual(tp.tp_canon("tp-lcc", {"ticket_status": "Refund"}), C.REFUND)
        self.assertEqual(tp.tp_canon("tp-lcc", {"ticket_status": "Rejected"}), C.NON_BILLABLE)
        self.assertEqual(tp.tp_canon("tp-api", _api_mmt_flight()), C.SALE)
        with self.assertRaises(KeyError):
            tp.tp_canon("bsp", {})

    def test_statement_footer_lines_never_count(self):
        # The real GDS export ends with TOTAL / LESS PAYMENT / BALANCE lines the importer stores
        # as rows holding only a Net Amount; adding them to Net triple-counts the statement.
        for data in ({"net_amount": "2024899.8144"},
                     {"net_amount": "627257.4144", "cancellation_markup": "BALANCE"}):
            out = tp.to_common("tp-gds", _row(data), _ctx("tp-gds"))
            self.assertEqual(out["transaction_type"], C.NON_BILLABLE)
            self.assertEqual(out["counts_in_net"], C.NET_SUMMARY_ONLY)
            self.assertIsNone(tp.tp_sale_key("tp-gds", _row(data), _ctx("tp-gds")))
        self.assertTrue(tp.is_summary_line({"net_amount": "1"}))
        # a real line missing its status still is one: it has a ticket or a date
        self.assertFalse(tp.is_summary_line({"net_amount": "1", "ticket_number": "5805708071"}))
        self.assertFalse(tp.is_summary_line({"net_amount": "1", "issue_date": "2026-08-01"}))


class GdsFlagTests(unittest.TestCase):
    def test_stale_format(self):
        for fmt, stale in ((GDS_V2, False), ("third-party-gds-v1", True), (None, True)):
            with self.subTest(fmt=fmt):
                out = tp.to_common("tp-gds", _row(_gds(), source_format=fmt), _ctx("tp-gds"))
                self.assertEqual("TP_STALE_FORMAT" in out["data_flags"], stale)

    def test_airline_conflict(self):
        d = _gds(airline_conflict="Ticket prefix 098 is Air India but the name says Vistara")
        out = tp.to_common("tp-gds", _row(d), _ctx("tp-gds"))
        self.assertIn("TP_AIRLINE_CONFLICT", out["data_flags"])

    def test_net_identity_mismatch(self):
        out = tp.to_common("tp-gds", _row(_gds(net_amount="90000")), _ctx("tp-gds"))
        self.assertIn("TP_NET_IDENTITY_MISMATCH", out["data_flags"])

    def test_date_parse_failed_and_unreadable(self):
        d = _gds(issue_date="31/31/2026", date_parse_failed="issue_date")
        out = tp.to_common("tp-gds", _row(d), _ctx("tp-gds"))
        self.assertIsNone(out["issue_date"])
        self.assertIn("TP_DATE_PARSE_FAILED", out["data_flags"])
        self.assertIn("DATE_UNREADABLE", out["data_flags"])

    def test_unparseable_amount_is_blank_and_flagged(self):
        out = tp.to_common("tp-gds", _row(_gds(yq="abc")), _ctx("tp-gds"))
        self.assertIsNone(out["yq"])
        self.assertIn("AMOUNT_UNPARSEABLE", out["data_flags"])
        clean = tp.to_common("tp-gds", _row(_gds(yq="N/A")), _ctx("tp-gds"))
        self.assertNotIn("AMOUNT_UNPARSEABLE", clean["data_flags"])

    def test_nonstandard_ticket_and_fallbacks(self):
        d = _gds(ticket_prefix=None, ticket_number="58057080", username=None,
                 issuing_office=None, agency_code="AG01", airline_master_name=None,
                 passenger_name=None, invoice_number=None)
        out = tp.to_common("tp-gds", _row(d), _ctx("tp-gds", supplier=False))
        self.assertEqual(out["ticket_number"], "58057080")
        self.assertIn("TICKET_NO_NONSTANDARD", out["data_flags"])
        self.assertEqual(out["agent_signon"], "AG01")
        self.assertEqual(out["airline_name"], "AIR INDIA")
        self.assertEqual(out["passenger_name"], "RAHUL SHARMA")
        self.assertEqual(out["invoice_ref"], "S1PNR")
        self.assertEqual(out["settled_with"], "Consolidator")

    def test_link_applied_last(self):
        link = LinkResult(also_in_bsp="Yes – this report", counts_in_net="No – settled in BSP",
                          flags=["ALSO_IN_BSP", "TP_REFUND_WITHOUT_SALE"])
        out = tp.to_common("tp-gds", _row(_gds()), _ctx("tp-gds"), link)
        self.assertEqual(out["counts_in_net"], "No – settled in BSP")
        self.assertEqual(out["also_in_bsp"], "Yes – this report")
        self.assertEqual(out["data_flags"][-2:], ["ALSO_IN_BSP", "TP_REFUND_WITHOUT_SALE"])


class LccTests(unittest.TestCase):
    def test_lcc_columns(self):
        d = {
            "booking_date": "2026-07-02", "issue_date": "2026-07-02",
            "issue_date_source": "booking_date", "airline_name": "IndiGo", "airline_code": "6E",
            "segment_type": "DOM", "pnr": "K9LMNO", "booking_reference": "BR-5511",
            "ticket_number": "K9LMNO", "ticket_status": "Confirmed", "transaction_type": "Sale",
            "passenger_name": "ANITA RAO", "passenger_count": "1", "sector": "BLR-DEL",
            "base_fare": "4500", "taxes": "820", "convenience_fee": "250", "service_fee": "50",
            "ssr_amount": "400", "other_charges": "150", "total_fare": "6170",
            "gst_on_sf": "9", "net_amount": "6179", "agency_code": "SUBAG7", "currency": "INR",
        }
        out = tp.to_common("tp-lcc", _row(d, source_format=LCC_V2, rid=3), _ctx("tp-lcc"))
        self.assertEqual(out["row_ref"], "third_party_lcc:3")
        self.assertEqual(out["transaction_type"], C.SALE)
        self.assertEqual(out["agent_signon"], "SUBAG7")
        self.assertIsNone(out["airline_numeric"])
        self.assertEqual(out["ticket_number"], "K9LMNO")
        self.assertEqual(out["gds_ref"], "BR-5511")
        self.assertEqual(out["airline_pnr"], "K9LMNO")
        self.assertEqual(out["source_txn_type"], "Confirmed / Sale")
        self.assertEqual(out["dom_intl"], "Domestic")
        self.assertEqual(out["pax_count"], 1)
        self.assertEqual(out["total_taxes"], Decimal("820"))
        self.assertEqual(out["service_fee"], Decimal("300"))
        self.assertEqual(out["ancillary"], Decimal("550"))
        self.assertIsNone(out["penalty"])
        self.assertEqual(out["net_payable"], Decimal("6179"))
        self.assertEqual(out["data_flags"], ["SCHEMA_UNVERIFIED"])

    def test_lcc_void_without_penalty_columns(self):
        d = {"issue_date": "2026-07-02", "ticket_status": "CANCELLED", "net_amount": "0.50",
             "ticket_number": "K9LMNO"}
        out = tp.to_common("tp-lcc", _row(d, source_format=LCC_V2), _ctx("tp-lcc"))
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        d["net_amount"] = "6179"
        out = tp.to_common("tp-lcc", _row(d, source_format=LCC_V2), _ctx("tp-lcc"))
        self.assertEqual(out["counts_in_net"], C.NET_CANCELLED_VERIFY)


class ApiTests(unittest.TestCase):
    def _map(self, data, **row_extra):
        row = _row(data, source_format=row_extra.pop("source_format", "mmt-bookings-v1"),
                   rid=5, bill_pax_count=row_extra.pop("bill_pax_count", None), **row_extra)
        return tp.to_common("tp-api", row, _ctx("tp-api"))

    def test_mmt_flight_sale(self):
        out = self._map(_api_mmt_flight())
        self.assertEqual(out["row_ref"], "third_party_api:5")
        self.assertEqual(out["transaction_type"], C.SALE)
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        self.assertEqual(out["settled_with"], "Aggregator – Riya Travel (MakeMyTrip)")
        self.assertEqual(out["product"], "Air")
        self.assertEqual(out["airline_name"], "IndiGo")
        self.assertIsNone(out["airline_code"])
        self.assertIsNone(out["airline_numeric"])
        self.assertEqual(out["airline_pnr"], "Q8ZK2L")
        self.assertEqual(out["flight_no"], "6E 2134")
        self.assertEqual(out["document_number"], "MMT/INV/77")
        self.assertEqual(out["invoice_ref"], "NF7A1B2C3D")
        self.assertEqual(out["agent_signon"], "ops@agency.in")
        self.assertEqual(out["sector"], "DEL/BOM")
        self.assertEqual(out["dom_intl"], "Domestic")
        self.assertEqual(out["issue_date"], date(2026, 7, 30))
        self.assertEqual(out["travel_date"], date(2026, 8, 10))
        self.assertEqual(out["settlement_period"], "2026-08-05")
        self.assertEqual(out["pax_count"], 2)
        self.assertEqual(out["gross_amount"], Decimal("13508"))
        self.assertEqual(out["net_payable"], Decimal("13508"))
        self.assertEqual(out["form_of_payment"], "Wallet")
        self.assertEqual(out["currency"], "INR")
        self.assertEqual(out["data_flags"], ["CURRENCY_ASSUMED"])

    def test_tbo_credit_series_is_negative(self):
        d = _api_tbo(invoice_number="MZ/2627/143655", net_amount="145", base_fare="335",
                     cancellation_fee="190", convenience_fee=None, service_charges=None)
        out = self._map(d, source_format="tbo-statement-v1")
        self.assertEqual(out["transaction_type"], C.REFUND)
        self.assertEqual(out["net_payable"], Decimal("-145"))
        self.assertEqual(out["base_fare"], Decimal("-335"))
        self.assertEqual(out["gross_amount"], Decimal("-335"))       # base + taxes, derived
        self.assertEqual(out["penalty"], Decimal("190"))
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        self.assertIn("API_TBO_CREDIT", out["data_flags"])
        self.assertIn("API_GROSS_DERIVED", out["data_flags"])
        self.assertEqual(out["product"], "Train")
        self.assertEqual(out["settled_with"], "Aggregator – Riya Travel (TBO)")

    def test_tbo_sale_series_is_not_credit(self):
        out = self._map(_api_tbo(), source_format="tbo-statement-v1")
        self.assertEqual(out["transaction_type"], C.SALE)
        self.assertEqual(out["net_payable"], Decimal("390"))
        self.assertNotIn("API_TBO_CREDIT", out["data_flags"])

    def test_mmt_cancelled_with_refund_is_retained_cancellation(self):
        d = _api_mmt_flight(booking_status="Cancelled", total_paid_amount="15508",
                            refund_amount="12000")
        out = self._map(d)
        self.assertEqual(out["transaction_type"], C.CANCELLATION)
        self.assertEqual(out["gross_amount"], Decimal("3508"))
        self.assertEqual(out["net_payable"], Decimal("3508"))
        self.assertIn("API_RETAINED_ON_CANCEL", out["data_flags"])
        self.assertNotIn("API_GROSS_DERIVED", out["data_flags"])
        self.assertEqual(out["counts_in_net"], C.NET_YES)

    def test_mmt_cancelled_fully_refunded_is_void(self):
        d = _api_mmt_flight(booking_status="Cancelled", total_paid_amount="15508",
                            refund_amount="15507.50")
        out = self._map(d)
        self.assertEqual(out["transaction_type"], C.VOID)
        self.assertEqual(out["counts_in_net"], C.NET_CANCELLED)
        self.assertNotIn("API_RETAINED_ON_CANCEL", out["data_flags"])

    def test_refund_without_payment_needs_review(self):
        d = _api_mmt_flight(booking_status="Refunded", total_paid_amount="0", refund_amount="900")
        out = self._map(d)
        self.assertEqual(out["transaction_type"], C.REFUND)
        self.assertEqual(out["net_payable"], Decimal("-900"))
        self.assertIn("API_NEEDS_REVIEW", out["data_flags"])
        self.assertEqual(out["counts_in_net"], C.NET_NEEDS_REVIEW)

    def test_pending_and_no_amount_are_not_a_sale(self):
        pending = self._map(_api_mmt_flight(booking_status="Pending", total_paid_amount="0"))
        self.assertEqual(pending["transaction_type"], C.NON_BILLABLE)
        self.assertEqual(pending["counts_in_net"], C.NET_NOT_A_SALE)
        no_amount = self._map(_api_mmt_flight(total_paid_amount=None))
        self.assertEqual(no_amount["transaction_type"], C.NON_BILLABLE)
        self.assertEqual(no_amount["counts_in_net"], C.NET_NOT_A_SALE)

    def test_no_category_by_sign(self):
        out = self._map(_api_mmt_flight(product_type="Visa", total_paid_amount="3280"))
        self.assertEqual(out["transaction_type"], C.SALE)
        self.assertEqual(out["product"], "Visa")
        self.assertIn("API_NO_CATEGORY", out["data_flags"])
        self.assertIsNone(out["airline_name"])
        credit = self._map(_api_tbo(product_type="Visa", invoice_number="RM/2627/30789",
                                    net_amount="833"), source_format="tbo-statement-v1")
        self.assertEqual(credit["transaction_type"], C.REFUND)
        self.assertEqual(credit["net_payable"], Decimal("-833"))

    def test_gst_from_amount_keys(self):
        d = _api_tbo(sgst_amount="1.11", cgst_amount="1.10", igst_amount=None,
                     service_tax_amount="0.50", legacy_cess="0.00")
        self.assertEqual(self._map(d)["gst_on_service"], Decimal("2.71"))
        d["total_gst"] = "3.00"                                    # declared total wins
        self.assertEqual(self._map(d)["gst_on_service"], Decimal("3.50"))
        d.update(total_gst="0", sgst_amount=None, cgst_amount=None, service_tax_amount=None,
                 igst_amount="5.31")
        self.assertEqual(self._map(d)["gst_on_service"], Decimal("5.31"))

    def test_service_fee_excludes_agent_markup_and_tcs(self):
        d = _api_mmt_flight(service_charges="-20", convenience_fee="8", pg_charges="12",
                            agent_markup="500", discount="-75", tcs_amount="-65",
                            tds="-3", travel_insurance="199")
        out = self._map(d)
        self.assertEqual(out["service_fee"], Decimal("0"))         # |−20 + 8 + 12|
        self.assertEqual(out["discount"], Decimal("75"))
        self.assertEqual(out["tcs"], Decimal("65"))
        self.assertEqual(out["tds"], Decimal("3"))
        self.assertEqual(out["ancillary"], Decimal("199"))
        d.update(service_charges="20")
        self.assertEqual(self._map(d)["service_fee"], Decimal("40"))

    def test_hotel_row_blank_airline_and_pax_suffix(self):
        d = _api_tbo(product_type="Hotel", invoice_number="MW/2627/5521", pax_count=None,
                     airline_property_name="Trident Chennai", pnr="HTLCONF1",
                     flight_number="X1", passenger_name="GARIMA GUPTA X 6",
                     confirmation_no="CNF-889", intl_dom="Domestic")
        out = self._map(d, source_format="tbo-statement-v1", bill_pax_count=6)
        self.assertEqual(out["product"], "Hotel")
        for key in ("airline_numeric", "airline_code", "airline_name", "airline_pnr", "flight_no"):
            self.assertIsNone(out[key], key)
        self.assertEqual(out["passenger_name"], "GARIMA GUPTA")
        self.assertEqual(out["pax_count"], 6)
        self.assertEqual(out["gds_ref"], "CNF-889")
        self.assertEqual(out["invoice_ref"], "MW/2627/5521")
        self.assertEqual(out["counts_in_net"], C.NET_YES)

    def test_vendor_from_source_format_and_no_stale_flag(self):
        d = _api_tbo(vendor=None)
        out = self._map(d, source_format="tbo-statement-v1")
        self.assertEqual(out["settled_with"], "Aggregator – Riya Travel (TBO)")
        self.assertNotIn("TP_STALE_FORMAT", out["data_flags"])

    def test_every_flag_is_in_legend(self):
        rows = [
            ("tp-gds", _row(_gds(ticket_status="ODD", airline_conflict="x", net_amount="1",
                                 date_parse_failed="issue_date", yq="junk"), source_format=None)),
            ("tp-api", _row(_api_tbo(invoice_number="MZ/1/2", product_type="Visa"))),
        ]
        for slug, row in rows:
            out = tp.to_common(slug, row, _ctx(slug))
            self.assertTrue(set(out["data_flags"]) <= set(C.FLAG_LEGEND))


class DetailColumnTests(unittest.TestCase):
    def _headers(self, slug, **kw):
        return [c.header for c in tp.detail_columns(slug, _ctx(slug, **kw))]

    def test_gds_layout(self):
        cols = tp.detail_columns("tp-gds", _ctx("tp-gds", extra_keys=("legacy_note", "airline_id")))
        headers = [c.header for c in cols]
        self.assertEqual(headers[:4], ["Row Ref", "Source File", "Upload ID", "Uploaded At (UTC)"])
        self.assertEqual(headers[-3:], ["Supplier Name", "Supplier Code", "Supplier Branch"])
        for h in ("Ticket No", "Net Amount", "Format", "Airline (Master)", "Airline Conflict",
                  "Total Fare Source", "data.legacy_note"):
            self.assertIn(h, headers)
        self.assertNotIn("data.airline_id", headers)          # already a stamped column
        self.assertNotIn("Vendor", headers)

        row = _row(_gds(ssr_amount="N/A", airline_conflict="Prefix disagrees"), rid=11)
        by_header = dict(zip(headers, base.detail_values(cols, row, _ctx("tp-gds"))))
        self.assertEqual(by_header["Row Ref"], "third_party_gds:11")
        self.assertEqual(by_header["Net Amount"], Decimal("89437"))
        self.assertEqual(by_header["Service Charge"], Decimal("100"))
        self.assertEqual(by_header["SSR Amount"], "N/A")      # unreadable text kept
        self.assertEqual(by_header["Format"], GDS_V2)
        self.assertEqual(by_header["Airline (Master)"], "Air India")
        self.assertEqual(by_header["Supplier Code"], "RIYA")
        kinds = {c.header: c.kind for c in cols}
        self.assertEqual(kinds["Service Charge"], "money")
        self.assertEqual(kinds["Comm %"], "text")

    def test_api_pii_gated(self):
        gated = ("PAN", "Guardian PAN", "Passport No", "Passport Issue Date",
                 "Passport Expiry Date", "Mobile Number")
        without = self._headers("tp-api", extra_keys=("contact_email", "gstin"))
        with_pii = self._headers("tp-api", include_pii=True, extra_keys=("contact_email", "gstin"))
        for h in gated:
            self.assertNotIn(h, without)
            self.assertIn(h, with_pii)
        self.assertNotIn("data.contact_email", without)
        self.assertIn("data.contact_email", with_pii)
        self.assertIn("data.gstin", without)
        self.assertIn("Booking Status Source", without)
        self.assertEqual(without.count("Vendor"), 1)
        self.assertNotIn("Airline (Master)", without)

    def test_lcc_has_no_total_fare_source(self):
        headers = self._headers("tp-lcc")
        self.assertIn("Issue Date Source", headers)
        self.assertNotIn("Total Fare Source", headers)


class KeyTests(unittest.TestCase):
    def test_gds_natural_key_is_format_insensitive(self):
        ctx = _ctx("tp-gds")
        a = tp.tp_natural_key("tp-gds", _row(_gds()), ctx)
        b = tp.tp_natural_key("tp-gds", _row(_gds(net_amount="89,437.00", passenger_name=" rahul  sharma ",
                                                  issue_date="28-07-2026")), ctx)
        self.assertEqual(a, b)
        self.assertEqual(a, (42, "5805708071", "RAHUL SHARMA", "CONFIRMED", "INV/26/0001",
                             Decimal("89437"), "2026-07-28"))
        c = tp.tp_natural_key("tp-gds", _row(_gds(net_amount="89438")), ctx)
        self.assertNotEqual(a, c)

    def test_api_natural_key(self):
        key = tp.tp_natural_key("tp-api", _row(_api_mmt_flight()), _ctx("tp-api"))
        self.assertEqual(key, (42, "MMT/INV/77", "NF7A1B2C3D", "FLIGHT", Decimal("13508"),
                               "2026-07-30"))
        tbo = tp.tp_natural_key("tp-api", _row(_api_tbo()), _ctx("tp-api", supplier=False))
        self.assertEqual(tbo[0], None)
        self.assertEqual(tbo[4], Decimal("390"))

    def test_sale_and_refund_keys(self):
        ctx = _ctx("tp-gds")
        sale = _row(_gds())
        refund = _row(_gds(ticket_status="REFUNDED", ticket_number=" 5805708071 "))
        self.assertEqual(tp.tp_sale_key("tp-gds", sale, ctx), (42, "5805708071"))
        self.assertIsNone(tp.tp_refund_key("tp-gds", sale, ctx))
        self.assertEqual(tp.tp_refund_key("tp-gds", refund, ctx), (42, "5805708071"))
        self.assertIsNone(tp.tp_sale_key("tp-gds", refund, ctx))
        pnr_only = _row({"ticket_status": "Confirmed", "pnr": "k9lmno"})
        self.assertEqual(tp.tp_sale_key("tp-lcc", pnr_only, ctx), (42, "K9LMNO"))
        self.assertIsNone(tp.tp_sale_key("tp-gds", _row({"ticket_status": "Confirmed"}), ctx))
        self.assertIsNone(tp.tp_sale_key("tp-gds", _row(_gds(ticket_status="VOID")), ctx))
        self.assertIsNone(tp.tp_sale_key("tp-api", _row(_api_mmt_flight()), ctx))

    def test_gds_ticket_key(self):
        self.assertEqual(tp.gds_ticket_key(_row(_gds())), DocKey("098", "5805708071"))
        self.assertEqual(tp.gds_ticket_key(_row(_gds(ticket_prefix=None, ticket_number="0985805708071"))),
                         DocKey("098", "5805708071"))
        self.assertIsNone(tp.gds_ticket_key(_row({"ticket_prefix": "098"})))


if __name__ == "__main__":
    unittest.main()
