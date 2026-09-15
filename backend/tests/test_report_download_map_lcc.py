"""Report download — LCC Detailed and LCC ledger mappers.

Pinned: seat / baggage / cancellation / convenience charges land in their own Combined columns
instead of inflating Total Taxes; account rows keep their stored sign (only cancellation credits
are relabelled); payment movements never count and net to their payment amount; ledgers never
count; personal data stays out of the detail sheets unless asked for; natural keys ignore
formatting noise.

No DB, no network.  Run: python -m unittest test_report_download_map_lcc   (from backend/tests)
"""
import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.lcc_detailed import _bill_kind as api_bill_kind  # noqa: E402
from app.models.lcc_detailed import LccDetailed  # noqa: E402
from app.services.commission.lcc_detailed import _sector as commission_sector  # noqa: E402
from app.services.report_download import columns as C  # noqa: E402
from app.services.report_download.mappers import lcc  # noqa: E402
from app.services.report_download.types import (  # noqa: E402
    AirlineSnap, LinkResult, MapCtx, ReportOptions, UploadMeta,
)

UPLOADED = datetime(2026, 8, 1, 9, 30)
SNAP = AirlineSnap(tenant_airline_id=7, airline_id=70, name="IndiGo", code="6E",
                   iata_numeric_code="312", ref_id="r1")


def detailed(**kw):
    """An LccDetailed row view: every model column present, None unless given."""
    base = {c.name: None for c in LccDetailed.__table__.columns}
    base.update(id=101, batch_id="b-lcc", airline_code="6E", airline_name="IndiGo",
                transaction_date=datetime(2026, 7, 3, 11, 0), name1="SHARMA/RAHUL MR",
                name="Booking Contact", total=Decimal("5000.00"), base_fare=Decimal("4000.00"),
                currency_code="INR", record_locator="ABC123", bill_kind="sale")
    base.update(kw)
    return SimpleNamespace(**base)


def ledger(**data):
    return SimpleNamespace(id=55, batch_id="b-led", source_file="ledger.xlsx", uploaded_at=UPLOADED,
                           data=data, taxes=None, segments=None, ssr=None, raw_data={"x": 1},
                           source_format="std")


def ctx(source_key="lcc-detailed", *, include_pii=False, tax_codes=(), extra_keys=(), airline=SNAP,
        header=None):
    if header is None and source_key == "lcc-detailed":
        header = SimpleNamespace(airline_name="IndiGo", source_format="indigo")
    return MapCtx(
        upload=UploadMeta(source_key, "b-1", "file.xlsx", UPLOADED, header=header, airline=airline),
        options=ReportOptions(include_pii=include_pii), tax_codes=tax_codes, extra_keys=extra_keys,
    )


def common(row, **kw):
    return lcc.to_common("lcc-detailed", row, ctx(**kw))


def values(cols, row, c):
    return {col.header: col.getter(row, c) for col in cols}


class DetailedChargeCodeTests(unittest.TestCase):
    def setUp(self):
        self.row = detailed(
            total=Decimal("6200.00"), base_fare=Decimal("4000.00"), taxes_total=Decimal("2200.00"),
            taxes=[
                {"code": "GST", "amount": "210"}, {"code": "UDF", "amount": "300"},
                {"code": "YQ", "amount": "100"}, {"code": "SEAT", "amount": "350"},
                {"code": "XBPA", "amount": "900"}, {"code": "CNX", "amount": "-250"},
                {"code": "CCF", "amount": "-150"}, {"code": "NMV", "amount": "40"},
            ],
        )
        self.out = common(self.row)

    def test_ancillary_codes_go_to_ancillary(self):
        self.assertEqual(self.out["ancillary"], Decimal("1250"))

    def test_cancellation_code_goes_to_penalty_unsigned(self):
        self.assertEqual(self.out["penalty"], Decimal("250"))

    def test_convenience_fee_goes_to_service_fee_unsigned(self):
        self.assertEqual(self.out["service_fee"], Decimal("150"))

    def test_gst_is_k3_and_yq_yr_pivot(self):
        self.assertEqual(self.out["k3"], Decimal("210"))
        self.assertEqual(self.out["yq"], Decimal("100"))
        self.assertIsNone(self.out["yr"])

    def test_unclassified_code_flagged_and_inside_total_taxes(self):
        self.assertIn("LCC_CODE_UNCLASSIFIED", self.out["data_flags"])
        # tax codes GST+UDF+YQ = 610, plus unclassified NMV 40; not the stored lump 2200.
        self.assertEqual(self.out["total_taxes"], Decimal("650"))
        self.assertEqual(self.out["other_taxes"], Decimal("340"))

    def test_money_as_stored(self):
        self.assertEqual(self.out["base_fare"], Decimal("4000.00"))
        self.assertEqual(self.out["gross_amount"], Decimal("6200.00"))
        self.assertEqual(self.out["net_payable"], Decimal("6200.00"))
        self.assertEqual(self.out["counts_in_net"], C.NET_YES)
        self.assertEqual(self.out["transaction_type"], C.SALE)

    def test_no_unclassified_flag_when_all_codes_known(self):
        out = common(detailed(taxes=[{"code": "GST", "amount": "50"}]))
        self.assertNotIn("LCC_CODE_UNCLASSIFIED", out["data_flags"])
        self.assertEqual(out["total_taxes"], Decimal("50"))

    def test_unreadable_code_amount_flagged(self):
        out = common(detailed(taxes=[{"code": "GST", "amount": "abc"}]))
        self.assertIn("AMOUNT_UNPARSEABLE", out["data_flags"])


class DetailedTaxFallbackTests(unittest.TestCase):
    def test_lump_taxes_total_when_no_codes(self):
        out = common(detailed(taxes=[], taxes_total=Decimal("1000.00"),
                              other_ssr_total=Decimal("300"), other_fee_total=Decimal("-75")))
        self.assertEqual(out["total_taxes"], Decimal("1000.00"))
        self.assertEqual(out["other_taxes"], Decimal("1000.00"))
        self.assertEqual(out["ancillary"], Decimal("300"))
        self.assertEqual(out["service_fee"], Decimal("75"))
        self.assertNotIn("TAXES_DERIVED", out["data_flags"])

    def test_taxes_derived_from_total_minus_base(self):
        out = common(detailed(taxes=None, taxes_total=None, total=Decimal("5000"), base_fare=Decimal("4200")))
        self.assertEqual(out["total_taxes"], Decimal("800"))
        self.assertIn("TAXES_DERIVED", out["data_flags"])

    def test_no_taxes_at_all_stays_blank(self):
        out = common(detailed(taxes=None, taxes_total=None, base_fare=None))
        self.assertIsNone(out["total_taxes"])
        self.assertIsNone(out["other_taxes"])
        self.assertNotIn("TAXES_DERIVED", out["data_flags"])

    def test_negative_residual_flagged(self):
        out = common(detailed(taxes=[{"code": "GST", "amount": "500"}, {"code": "UDF", "amount": "-600"}]))
        self.assertEqual(out["total_taxes"], Decimal("-100"))
        self.assertEqual(out["other_taxes"], Decimal("-600"))
        self.assertNotIn("NEG_TAX_RESIDUAL", out["data_flags"])
        out = common(detailed(taxes=[{"code": "GST", "amount": "500"}, {"code": "UDF", "amount": "-300"}]))
        self.assertEqual(out["other_taxes"], Decimal("-300"))
        self.assertIn("NEG_TAX_RESIDUAL", out["data_flags"])

    def test_json_null_taxes_and_segments_are_safe(self):
        out = common(detailed(taxes=None, segments=None, ssr=None))
        self.assertIsNone(out["sector"])
        self.assertIsNone(out["flight_no"])
        self.assertIsNone(out["yq"])
        cols = lcc.detail_columns("lcc-detailed", ctx(tax_codes=("GST",)))
        vals = values(cols, detailed(taxes=None, segments=None, ssr=None), ctx())
        self.assertIsNone(vals["Segments"])
        self.assertIsNone(vals["Tax GST"])


class DetailedTypeAndSignTests(unittest.TestCase):
    def test_account_cancellation_credit_is_credit_transfer_with_stored_sign(self):
        row = detailed(row_kind="account", movement_kind="cancellation_credit", bill_kind="refund",
                       total=Decimal("-3200.00"), base_fare=None)
        out = common(row)
        self.assertEqual(lcc.lcc_canon(row), C.CREDIT_TRANSFER)
        self.assertEqual(out["transaction_type"], C.CREDIT_TRANSFER)
        self.assertEqual(out["gross_amount"], Decimal("-3200.00"))
        self.assertEqual(out["net_payable"], Decimal("-3200.00"))
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        self.assertIn("LCC_MERGED_ACCOUNT_ROW", out["data_flags"])

    def test_cancellation_credit_on_non_account_row_keeps_bill_kind(self):
        row = detailed(row_kind="pax", movement_kind="cancellation_credit", bill_kind="refund",
                       total=Decimal("-10"))
        self.assertEqual(lcc.lcc_canon(row), C.REFUND)

    def test_payment_movement_not_counted_and_nets_to_payment_amount(self):
        row = detailed(bill_kind="payment", total=Decimal("0"), payment_amount=Decimal("1234.50"))
        out = common(row)
        self.assertEqual(out["transaction_type"], C.PAYMENT)
        self.assertEqual(out["counts_in_net"], C.NET_LCC_PAYMENT)
        self.assertEqual(out["net_payable"], Decimal("1234.50"))
        self.assertEqual(out["gross_amount"], Decimal("0"))
        self.assertIn("LCC_PAYMENT_MOVEMENT", out["data_flags"])

    def test_balance_movement_is_payment(self):
        row = detailed(movement_kind="balance", bill_kind="sale", total=Decimal("900"))
        self.assertEqual(lcc.lcc_canon(row), C.PAYMENT)

    def test_canon_falls_back_to_total_sign(self):
        self.assertEqual(lcc.lcc_canon(detailed(bill_kind=None, total=Decimal("10"))), C.SALE)
        self.assertEqual(lcc.lcc_canon(detailed(bill_kind=None, total=Decimal("-10"))), C.REFUND)
        self.assertEqual(lcc.lcc_canon(detailed(bill_kind=None, total=None)), C.PAYMENT)
        self.assertEqual(lcc.lcc_canon(detailed(bill_kind="REFUND", total=Decimal("10"))), C.REFUND)

    def test_note_sign_conflict(self):
        out = common(detailed(row_kind="account", movement_kind="booking_payment", bill_kind="refund",
                              total=Decimal("-5516")))
        self.assertIn("LCC_NOTE_SIGN_CONFLICT", out["data_flags"])
        self.assertEqual(out["gross_amount"], Decimal("-5516"))      # never re-signed
        out = common(detailed(row_kind="account", movement_kind="refund", total=Decimal("5073")))
        self.assertIn("LCC_NOTE_SIGN_CONFLICT", out["data_flags"])
        out = common(detailed(row_kind="account", movement_kind="booking_payment", total=Decimal("5516")))
        self.assertNotIn("LCC_NOTE_SIGN_CONFLICT", out["data_flags"])

    def test_local_copies_match_originals(self):
        for total in (None, Decimal("0"), Decimal("0.00"), Decimal("12.5"), Decimal("-3"), 7, -7.5):
            self.assertEqual(lcc._bill_kind(total), api_bill_kind(total), total)
        for segs in (None, [], [{"route": "DEL-BOM"}, {"route": "BOM-MAA"}],
                     [{"route": "del/bom"}, {"route": None}, {"route": "BOM/DEL"}], [{"flight_no": "1"}]):
            row = detailed(segments=segs)
            self.assertEqual(lcc._sector(row), commission_sector(row), segs)


class DetailedCurrencyAndIdentityTests(unittest.TestCase):
    def test_account_currency_from_foreign_currency_code(self):
        out = common(detailed(row_kind="account", currency_code="INR", foreign_currency_code="aed"))
        self.assertEqual(out["currency"], "AED")
        self.assertIn("PAYMENT_CURRENCY_DIFFERS", out["data_flags"])

    def test_pax_row_currency_is_currency_code(self):
        out = common(detailed(row_kind="pax", currency_code="INR", foreign_currency_code="AED"))
        self.assertEqual(out["currency"], "INR")
        self.assertIn("PAYMENT_CURRENCY_DIFFERS", out["data_flags"])

    def test_currency_assumed_when_absent(self):
        out = common(detailed(currency_code=None))
        self.assertEqual(out["currency"], "INR")
        self.assertIn("CURRENCY_ASSUMED", out["data_flags"])
        self.assertNotIn("PAYMENT_CURRENCY_DIFFERS", out["data_flags"])

    def test_parties_document_booking_and_itinerary(self):
        row = detailed(
            source_agent_code=None, source_organization_code="ORG1", gst_number="27abcde1234f1z5",
            transaction_type="PPAccountCredit", movement_kind="refund", account_transaction_id="AT9",
            payment_number="PN1", parent_pnr="OLD111", payment_status="Approved",
            gds_record_locator="GDS1", bill_pax_count=3, pax_count=2,
            booking_date=datetime(2026, 6, 30, 8, 0), departure_date=date(2026, 7, 20),
            international=False, product_class="Saver", booking_promo_code="PROMO",
            payment_method_code="AG",
            segments=[{"route": "DEL-BOM", "flight_no": "2571"}, {"route": "BOM-MAA", "flight_no": "613"}],
        )
        out = common(row)
        self.assertEqual(out["category"], C.CAT_LCC)
        self.assertEqual(out["source_type"], "LCC Detailed Statement")
        self.assertEqual(out["row_ref"], "lcc_detailed:101")
        self.assertEqual(out["uploaded_at"], UPLOADED)
        self.assertEqual(out["settled_with"], "Airline direct – IndiGo")
        self.assertEqual(out["agent_signon"], "ORG1")
        self.assertEqual((out["airline_numeric"], out["airline_code"], out["airline_name"]),
                         ("312", "6E", "IndiGo"))
        self.assertEqual(out["booking_party_gstin"], "27ABCDE1234F1Z5")
        self.assertEqual(out["product"], C.PRODUCT_AIR)
        self.assertEqual(out["source_txn_type"], "PPAccountCredit/refund")
        self.assertEqual(out["document_number"], "AT9")
        self.assertIsNone(out["ticket_number"])
        self.assertEqual(out["related_document"], "OLD111")
        self.assertEqual(out["status"], "Approved")
        self.assertEqual((out["airline_pnr"], out["gds_ref"], out["invoice_ref"]), ("ABC123", "GDS1", "PN1"))
        self.assertEqual(out["passenger_name"], "SHARMA/RAHUL MR")     # name1, not name
        self.assertEqual(out["pax_count"], 3)
        self.assertEqual((out["issue_date"], out["booking_date"], out["travel_date"]),
                         (date(2026, 7, 3), date(2026, 6, 30), date(2026, 7, 20)))
        self.assertEqual(out["sector"], "DEL/BOM/MAA")
        self.assertEqual(out["dom_intl"], "Domestic")
        self.assertEqual(out["flight_no"], "2571/613")
        self.assertIsNone(out["booking_class"])
        self.assertEqual(out["fare_basis"], "Saver")
        self.assertIn("FARE_FAMILY_NOT_RBD", out["data_flags"])
        self.assertEqual(out["tour_code"], "PROMO")
        self.assertEqual(out["form_of_payment"], "AG")

    def test_fallbacks(self):
        out = common(detailed(source_agent_code="AG1", source_organization_code="ORG1", pax_count=2,
                              account_transaction_id=None, payment_number="PN7", international=True,
                              airline_code=None, transaction_date=None))
        self.assertEqual(out["agent_signon"], "AG1")
        self.assertEqual(out["pax_count"], 2)
        self.assertEqual(out["document_number"], "PN7")
        self.assertEqual(out["dom_intl"], "International")
        self.assertEqual(out["airline_code"], "6E")                    # from the batch airline
        self.assertIsNone(out["issue_date"])
        self.assertIn("DATE_UNREADABLE", out["data_flags"])

    def test_link_applied_last(self):
        link = LinkResult(counts_in_net=C.NET_SUPERSEDED, flags=["DUPLICATE_SUPERSEDED"])
        out = lcc.to_common("lcc-detailed", detailed(), ctx(), link)
        self.assertEqual(out["counts_in_net"], C.NET_SUPERSEDED)
        self.assertIn("DUPLICATE_SUPERSEDED", out["data_flags"])

    def test_every_emitted_flag_is_in_legend(self):
        rows = [detailed(row_kind="account", movement_kind="booking_payment", total=Decimal("-1"),
                         foreign_currency_code="USD", taxes=[{"code": "ZZZ", "amount": "x"}],
                         product_class="Flexi", transaction_date=None)]
        for r in rows:
            for f in common(r)["data_flags"]:
                self.assertIn(f, C.FLAG_LEGEND)

    def test_unknown_source_raises(self):
        with self.assertRaises(KeyError):
            lcc.to_common("tp-gds", detailed(), ctx())
        with self.assertRaises(KeyError):
            lcc.detail_columns("bsp", ctx())


class DetailedDetailColumnTests(unittest.TestCase):
    def test_provenance_first_and_pii_gated(self):
        headers = [c.header for c in lcc.detail_columns("lcc-detailed", ctx())]
        self.assertEqual(headers[:4], ["Row Ref", "Source File", "Upload ID", "Uploaded At (UTC)"])
        for gated in ("EmailAddress", "HomePhone", "GSTEmailAddress"):
            self.assertNotIn(gated, headers)
        for kept in ("Name1", "GSTNumber", "GSTCompanyName", "Tax Total", "AccountTransactionID"):
            self.assertIn(kept, headers)
        with_pii = [c.header for c in lcc.detail_columns("lcc-detailed", ctx(include_pii=True))]
        for gated in ("EmailAddress", "HomePhone", "GSTEmailAddress"):
            self.assertIn(gated, with_pii)

    def test_derived_columns_and_tax_pivot(self):
        c = ctx(tax_codes=("GST", "SEAT", "CNX"), extra_keys=("remark", "mobile"))
        cols = lcc.detail_columns("lcc-detailed", c)
        headers = [col.header for col in cols]
        tail = ["Airline", "Departure Date", "Row Kind", "Movement", "Bill Kind", "Segments", "SSR",
                "Format", "Tax GST", "Tax SEAT", "Tax CNX", "extra.remark"]
        self.assertEqual(headers[-len(tail):], tail)
        self.assertNotIn("extra.mobile", headers)
        row = detailed(
            id=9, row_kind="pax", movement_kind=None, departure_date=date(2026, 7, 9),
            taxes=[{"code": "GST", "amount": "10"}, {"code": "GST", "amount": "5"}, {"code": "SEAT", "amount": "99"}],
            segments=[{"route": "DEL-BOM", "flight_no": "2571"}, "junk"], ssr=[{"code": "XBPA", "amount": 900}],
            extra={"remark": "hello"}, email_address="a@b.c",
        )
        vals = values(cols, row, c)
        self.assertEqual(vals["Row Ref"], "lcc_detailed:9")
        self.assertEqual(vals["Source File"], "file.xlsx")
        self.assertEqual(vals["Airline"], "6E IndiGo")
        self.assertEqual(vals["Segments"], "DEL-BOM 2571")
        self.assertEqual(vals["SSR"], "XBPA 900")
        self.assertEqual(vals["Format"], "indigo")
        self.assertEqual(vals["Tax GST"], Decimal("15"))
        self.assertEqual(vals["Tax SEAT"], Decimal("99"))
        self.assertIsNone(vals["Tax CNX"])
        self.assertEqual(vals["extra.remark"], "hello")
        self.assertEqual(vals["Total"], Decimal("5000.00"))
        kinds = {col.header: col.kind for col in cols}
        self.assertEqual((kinds["Transaction Date"], kinds["Total"], kinds["PaxCount"], kinds["Tax GST"]),
                         ("datetime", "money", "int", "money"))

    def test_pivot_cache_does_not_leak_between_rows(self):
        c = ctx(tax_codes=("GST",))
        col = [x for x in lcc.detail_columns("lcc-detailed", c) if x.header == "Tax GST"][0]
        a = detailed(taxes=[{"code": "GST", "amount": "1"}])
        b = detailed(taxes=[{"code": "GST", "amount": "2"}])
        self.assertEqual([col.getter(a, c), col.getter(b, c), col.getter(a, c)],
                         [Decimal("1"), Decimal("2"), Decimal("1")])


class DetailedNaturalKeyTests(unittest.TestCase):
    def test_stable_across_formatting(self):
        a = detailed(record_locator="abc123 ", name1="sharma/rahul mr", total=Decimal("5000.00"))
        b = detailed(id=999, record_locator="ABC123", name1="SHARMA/RAHUL MR", total=Decimal("5000"))
        self.assertEqual(lcc.lcc_natural_key(a), lcc.lcc_natural_key(b))
        self.assertEqual(hash(lcc.lcc_natural_key(a)), hash(lcc.lcc_natural_key(b)))

    def test_distinguishes_records(self):
        a = detailed(account_transaction_id="AT1")
        b = detailed(account_transaction_id="AT2")
        self.assertNotEqual(lcc.lcc_natural_key(a), lcc.lcc_natural_key(b))
        self.assertEqual(len(lcc.lcc_natural_key(a)), 7)


class LedgerMappingTests(unittest.TestCase):
    def map(self, slug, row, **kw):
        return lcc.to_common(slug, row, ctx(slug, **kw))

    def test_di(self):
        out = self.map("lcc-di", ledger(deposit_date="01-Jul-2026", type="Credit", agency_code=None,
                                        agent_name="Ace Travels", detail="NEFT 123", amount="1,50,000.00"))
        self.assertEqual(out["category"], C.CAT_LCC)
        self.assertEqual(out["source_type"], "LCC DI Statement")
        self.assertEqual(out["row_ref"], "lcc_di:55")
        self.assertEqual(out["settled_with"], "Airline direct – IndiGo")
        self.assertEqual(out["transaction_type"], C.DEPOSIT)
        self.assertEqual(out["source_txn_type"], "Credit")
        self.assertIsNone(out["product"])
        self.assertEqual(out["agent_signon"], "Ace Travels")
        self.assertEqual((out["airline_numeric"], out["airline_code"], out["airline_name"]), ("312", "6E", "IndiGo"))
        self.assertEqual(out["issue_date"], date(2026, 7, 1))
        self.assertEqual(out["gross_amount"], Decimal("150000.00"))
        self.assertEqual(out["net_payable"], Decimal("150000.00"))
        self.assertEqual(out["currency"], "INR")
        self.assertIn("CURRENCY_ASSUMED", out["data_flags"])
        self.assertEqual(out["counts_in_net"], C.NET_LEDGER)
        self.assertNotIn("SCHEMA_UNVERIFIED", out["data_flags"])

    def test_divided(self):
        out = self.map("lcc-divided-pnr", ledger(
            booking_date="2026-06-28", parent_pnr="PAR111", divided_date="", child_pnr="CHD222",
            payment_amount="-2500", currency="inr", payment_method="AG", source_agent_code="SA1",
            agency_code="IGNORED", booking_promo_code="P1"))
        self.assertEqual(out["transaction_type"], C.PNR_DIVIDE)
        self.assertIsNone(out["product"])
        self.assertEqual(out["agent_signon"], "SA1")
        self.assertEqual(out["related_document"], "PAR111")
        self.assertEqual(out["airline_pnr"], "CHD222")
        self.assertEqual(out["issue_date"], date(2026, 6, 28))          # divided_date blank → booking_date
        self.assertEqual(out["booking_date"], date(2026, 6, 28))
        self.assertEqual(out["gross_amount"], Decimal("-2500"))          # as stored
        self.assertEqual(out["net_payable"], Decimal("-2500"))
        self.assertEqual(out["currency"], "INR")
        self.assertEqual(out["form_of_payment"], "AG")
        self.assertEqual(out["tour_code"], "P1")
        self.assertEqual(out["counts_in_net"], C.NET_LEDGER)

    def test_flown(self):
        out = self.map("lcc-flown-report", ledger(
            flown_date="bad", travel_date="15/07/2026", booking_date="01/07/2026", pnr="xyz789",
            ticket_number="3121234567890", airline_code="", flight_number="6E 2571", origin="DEL",
            destination="BOM", booking_class="R", fare_basis="", product_class="Saver",
            passenger_name="KUMAR/AMIT", passenger_count="2", base_fare="4000", taxes="800",
            total_fare="4800", currency="INR", commission_amount="120", incentive_amount="(50)",
            net_fare="4680", flown_status="", coupon_status="F", agency_code="AG9", payment_method="CC"))
        self.assertEqual(out["transaction_type"], C.FLOWN)
        self.assertEqual(out["product"], C.PRODUCT_AIR)
        self.assertIn("SCHEMA_UNVERIFIED", out["data_flags"])
        self.assertEqual(out["document_number"], "3121234567890")
        self.assertEqual(out["ticket_number"], "3121234567890")
        self.assertEqual(out["status"], "F")
        self.assertEqual(out["airline_pnr"], "xyz789")
        self.assertEqual(out["airline_code"], "6E")
        self.assertEqual(out["agent_signon"], "AG9")
        self.assertEqual(out["pax_count"], 2)
        self.assertEqual(out["issue_date"], date(2026, 7, 15))           # flown_date unreadable → travel_date
        self.assertEqual(out["travel_date"], date(2026, 7, 15))
        self.assertEqual(out["sector"], "DEL/BOM")
        self.assertEqual(out["flight_no"], "6E 2571")
        self.assertEqual(out["booking_class"], "R")
        self.assertEqual(out["fare_basis"], "Saver")
        self.assertIn("FARE_FAMILY_NOT_RBD", out["data_flags"])
        self.assertEqual((out["base_fare"], out["total_taxes"], out["gross_amount"]),
                         (Decimal("4000"), Decimal("800"), Decimal("4800")))
        self.assertEqual((out["commission"], out["incentive_declared"], out["net_payable"]),
                         (Decimal("120"), Decimal("-50"), Decimal("4680")))
        self.assertEqual(out["form_of_payment"], "CC")
        self.assertEqual(out["counts_in_net"], C.NET_LEDGER)

    def test_cta_bta_payment_and_refund(self):
        row = ledger(account_type="CTA", account_number="1234XXXX", transaction_date="",
                     booking_date="02-Jul-2026", travel_date="10-Jul-2026", pnr="PNR1", ticket_number="",
                     invoice_number="INV-9", passenger_name="A/B", sector="DEL-BLR", booking_class="Y",
                     base_fare="1000", taxes="180", fee_amount="-25", total_amount="1205", currency="INR",
                     card_scheme="UATP", reference_number="REF7", agency_code="AG1", payment_status="Settled",
                     gst_number="29aaaaa0000a1z5")
        out = self.map("lcc-cta-bta", row)
        self.assertEqual(out["transaction_type"], C.PAYMENT)
        self.assertEqual(out["source_txn_type"], "CTA")
        self.assertEqual(out["document_number"], "INV-9")
        self.assertIsNone(out["ticket_number"])
        self.assertEqual((out["status"], out["airline_pnr"], out["gds_ref"], out["invoice_ref"]),
                         ("Settled", "PNR1", "REF7", "INV-9"))
        self.assertEqual(out["booking_party_gstin"], "29AAAAA0000A1Z5")
        self.assertEqual(out["issue_date"], date(2026, 7, 2))
        self.assertEqual(out["travel_date"], date(2026, 7, 10))
        self.assertEqual(out["sector"], "DEL-BLR")
        self.assertEqual(out["service_fee"], Decimal("25"))
        self.assertEqual((out["gross_amount"], out["net_payable"]), (Decimal("1205"), Decimal("1205")))
        self.assertEqual(out["form_of_payment"], "UATP")
        self.assertIn("SCHEMA_UNVERIFIED", out["data_flags"])
        self.assertEqual(out["counts_in_net"], C.NET_LEDGER)
        row.data["payment_status"] = "Refunded"
        self.assertEqual(self.map("lcc-cta-bta", row)["transaction_type"], C.REFUND)

    def test_pnr_shaped_or_short_ticket_not_promoted(self):
        for raw in ("ABC123", "123456789", "98-5805708071-933"):
            out = self.map("lcc-flown-report", ledger(ticket_number=raw, flown_date="01-Jul-2026"))
            self.assertIsNone(out["ticket_number"], raw)
            self.assertNotIn("TICKET_NO_NONSTANDARD", out["data_flags"])
        out = self.map("lcc-flown-report", ledger(ticket_number="1234567890", flown_date="01-Jul-2026"))
        self.assertEqual(out["ticket_number"], "3121234567890")          # 10-digit serial + airline code
        out = self.map("lcc-flown-report", ledger(ticket_number="1234567890", flown_date="01-Jul-2026"),
                       airline=None)
        self.assertIsNone(out["ticket_number"])
        self.assertEqual(out["settled_with"], "Airline direct")

    def test_unreadable_date_and_amount_flagged(self):
        out = self.map("lcc-di", ledger(deposit_date="someday", amount="12,34"))
        self.assertIsNone(out["issue_date"])
        self.assertIn("DATE_UNREADABLE", out["data_flags"])
        self.assertIsNone(out["gross_amount"])
        self.assertIn("AMOUNT_UNPARSEABLE", out["data_flags"])
        out = self.map("lcc-di", ledger(deposit_date="01-Jul-2026", amount="N/A"))
        self.assertNotIn("AMOUNT_UNPARSEABLE", out["data_flags"])

    def test_ledgers_never_count_even_with_empty_data(self):
        for slug in lcc.LEDGER_KEYS:
            row = SimpleNamespace(id=1, data=None)
            out = lcc.to_common(slug, row, ctx(slug))
            self.assertEqual(out["counts_in_net"], C.NET_LEDGER, slug)
            self.assertIn("DATE_UNREADABLE", out["data_flags"])

    def test_link_applied(self):
        link = LinkResult(linked_document="PNR1", linked_via="LCC Detailed PNR", flags=["ALSO_IN_LCC_DETAILED"])
        out = lcc.to_common("lcc-cta-bta", ledger(pnr="PNR1"), ctx("lcc-cta-bta"), link)
        self.assertEqual((out["linked_document"], out["linked_via"]), ("PNR1", "LCC Detailed PNR"))
        self.assertIn("ALSO_IN_LCC_DETAILED", out["data_flags"])
        self.assertEqual(out["counts_in_net"], C.NET_LEDGER)


class LedgerHelpersTests(unittest.TestCase):
    def test_ledger_pnrs(self):
        self.assertEqual(lcc.ledger_pnrs("lcc-flown-report", ledger(pnr=" abc123 ")), ["ABC123"])
        self.assertEqual(lcc.ledger_pnrs("lcc-cta-bta", ledger(pnr="")), [])
        self.assertEqual(lcc.ledger_pnrs("lcc-divided-pnr", ledger(parent_pnr="par1", child_pnr="chd2")),
                         ["PAR1", "CHD2"])
        self.assertEqual(lcc.ledger_pnrs("lcc-divided-pnr", ledger(parent_pnr=None, child_pnr="chd2")), ["CHD2"])
        self.assertEqual(lcc.ledger_pnrs("lcc-di", ledger(detail="PNR ABC123")), [])
        self.assertIs(lcc.ledger_pnr, lcc.ledger_pnrs)
        with self.assertRaises(KeyError):
            lcc.ledger_pnrs("lcc-detailed", ledger())

    def test_natural_keys_stable_and_scoped_to_airline(self):
        c = ctx("lcc-di")
        a = ledger(deposit_date="01-Jul-2026", type="credit", amount="1,000.00", detail="neft 1")
        b = ledger(deposit_date="2026-07-01", type="CREDIT ", amount="1000", detail="NEFT 1")
        self.assertEqual(lcc.ledger_natural_key("lcc-di", a, c), lcc.ledger_natural_key("lcc-di", b, c))
        self.assertEqual(lcc.ledger_natural_key("lcc-di", a, c)[0], 7)
        other_airline = ctx("lcc-di", airline=AirlineSnap(8, 80, "AIX", "IX", "090", None))
        self.assertNotEqual(lcc.ledger_natural_key("lcc-di", a, c), lcc.ledger_natural_key("lcc-di", a, other_airline))

        keys = {
            "lcc-divided-pnr": ledger(parent_pnr="P", child_pnr="C", divided_date="01/07/2026", payment_amount="5"),
            "lcc-flown-report": ledger(pnr="PNR9", flight_number="2571", flown_date="01-Jul-26", passenger_name="x/y"),
            "lcc-cta-bta": ledger(invoice_number="I1", ticket_number="T1", transaction_date="2026-07-01",
                                  total_amount="99"),
        }
        for slug, row in keys.items():
            k = lcc.ledger_natural_key(slug, row, ctx(slug))
            self.assertEqual(len(k), 5, slug)
            self.assertEqual(k, lcc.ledger_natural_key(slug, row, ctx(slug)))
            hash(k)
        flown = lcc.ledger_natural_key("lcc-flown-report", keys["lcc-flown-report"], ctx("lcc-flown-report"))
        self.assertEqual(flown, (7, "PNR9", "2571", "2026-07-01", "X/Y"))
        with self.assertRaises(KeyError):
            lcc.ledger_natural_key("lcc-detailed", ledger(), c)

    def test_detail_columns_pii_money_and_extra_keys(self):
        c = ctx("lcc-cta-bta", extra_keys=("merchant_city", "contact_mobile", "pnr"))
        cols = lcc.detail_columns("lcc-cta-bta", c)
        headers = [col.header for col in cols]
        self.assertEqual(headers[:4], ["Row Ref", "Source File", "Upload ID", "Uploaded At (UTC)"])
        self.assertNotIn("Account No", headers)
        self.assertIn("Card Scheme", headers)
        self.assertIn("data.merchant_city", headers)
        self.assertNotIn("data.contact_mobile", headers)
        self.assertNotIn("data.pnr", headers)                              # already a display column
        self.assertEqual(headers[-2:], ["Format", "data.merchant_city"])
        with_pii = [col.header for col in lcc.detail_columns("lcc-cta-bta", ctx("lcc-cta-bta", include_pii=True))]
        self.assertIn("Account No", with_pii)

        row = ledger(total_amount="1,205.50", fee_amount="n/a?", pnr="PNR1", merchant_city="Pune")
        vals = values(cols, row, c)
        self.assertEqual(vals["Row Ref"], "lcc_cta_bta:55")
        self.assertEqual(vals["Total Amount"], Decimal("1205.50"))
        self.assertEqual(vals["Fees"], "n/a?")                             # unreadable text kept
        self.assertEqual(vals["PNR"], "PNR1")
        self.assertEqual(vals["Format"], "std")
        self.assertEqual(vals["data.merchant_city"], "Pune")
        kinds = {col.header: col.kind for col in cols}
        self.assertEqual((kinds["Total Amount"], kinds["PNR"]), ("money", "text"))

    def test_detail_columns_every_ledger(self):
        expected_tables = {"lcc-di": "lcc_di", "lcc-divided-pnr": "lcc_divided_pnr",
                           "lcc-flown-report": "lcc_flown_report", "lcc-cta-bta": "lcc_cta_bta"}
        for slug, table in expected_tables.items():
            c = ctx(slug)
            cols = lcc.detail_columns(slug, c)
            self.assertEqual(cols[0].getter(ledger(), c), f"{table}:55")
            money = {col.header for col in cols if col.kind == "money"}
            self.assertTrue(money, slug)


if __name__ == "__main__":
    unittest.main()
