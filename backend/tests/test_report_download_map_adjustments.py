"""ADM / ACM / RA mapper for the Workspace report download.

BSPlink memos never count in net (the billed BSP line does), their amount is type-signed
(ADM +, ACM −, RA −) whatever sign the export printed, and their components are raw
airline − agent deltas. The cases pin those rules, the "not yet billed (status …, sent to
DPC)" reason linking later overrides, the component identity check, unreadable-amount
flagging, and that contact name / e-mail / phone never reach a detail sheet without the PII
option.

No DB, no network: rows are SimpleNamespace views carrying every model column as text.

Run:  ..\\venv\\Scripts\\python.exe -m unittest test_report_download_map_adjustments -v   (from backend/tests)
"""

import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.airline_adjustment import ADJUSTMENT_MODELS  # noqa: E402
from app.services import airline_adjustment_spec as spec  # noqa: E402
from app.services.report_download import columns as C  # noqa: E402
from app.services.report_download.mappers import adjustments as M  # noqa: E402
from app.services.report_download.mappers.base import detail_values  # noqa: E402
from app.services.report_download.types import (  # noqa: E402
    AirlineInfo, AirlineMaster, LinkResult, MapCtx, ReportOptions, UploadMeta,
)

D = Decimal


def row(kind, **kw):
    base = {c.name: None for c in ADJUSTMENT_MODELS[kind].__table__.columns}
    base.update(id=7, batch_id="adj-1", source_file=f"{kind}.xlsx", airline_code="098",
                agent_code="14312345", document_number="6000123456", currency="INR",
                status="Pending", period="2026071")
    if kind == "ra":
        base.update(rtdn_number="5805708071", application_date="05-Jul-2026", amount="1,200.00",
                    passenger="SHARMA/RAHUL", forms_of_payment="CA")
    else:
        base.update(type=kind.upper() + "A" if kind == "adm" else "ACMA", issue_date="03/07/2026",
                    related_document="0985805708071", statistical_code="D")
    base.update(kw)
    return SimpleNamespace(**base)


def ctx(kind="adm", include_pii=False):
    airlines = AirlineMaster(by_numeric={"098": AirlineInfo("AI", "098", "Air India")},
                             by_iata={"AI": AirlineInfo("AI", "098", "Air India")})
    up = UploadMeta(source_key=kind, upload_id="adj-1", file_name=f"{kind}.xlsx",
                    uploaded_at=datetime(2026, 7, 16, 9, 0))
    return MapCtx(upload=up, options=ReportOptions(include_pii=include_pii), airlines=airlines)


class _LegendMixin:
    def assertLegendOnly(self, out):
        for f in out["data_flags"]:
            self.assertIn(f, C.FLAG_LEGEND)


class AdmAcmTests(_LegendMixin, unittest.TestCase):
    def test_adm_deltas_and_positive_sign(self):
        r = row("adm", airlines_fare="10,000.00", agents_fare="9,000.00",
                airlines_tax="500", agents_tax="450",
                airlines_commission="300", agents_commission="400",
                airlines_cancellation_penalty="0", agents_cancellation_penalty="250",
                airlines_miscellaneous_fee="75", agents_miscellaneous_fee=None,
                amount="-925.00")
        out = M.to_common("adm", r, ctx())
        self.assertEqual(out["transaction_type"], C.ADM)
        self.assertEqual(out["source_txn_type"], "ADMA")
        self.assertEqual(out["base_fare"], D("1000.00"))
        self.assertEqual(out["total_taxes"], D("50"))
        self.assertEqual(out["commission"], D("-100"))          # raw delta, not re-signed
        self.assertIsNone(out["supp_commission"])               # both sides blank
        self.assertEqual(out["penalty"], D("250"))              # |Δ|
        self.assertEqual(out["service_fee"], D("75"))
        self.assertEqual(out["gross_amount"], D("925.00"))      # ADM is +|amount|
        self.assertEqual(out["net_payable"], D("925.00"))
        # 1000 + 50 − (−100) + 0 + (−250) + 75 = 975 ≠ 925
        self.assertIn("MEMO_COMPONENTS_MISMATCH", out["data_flags"])
        self.assertLegendOnly(out)

    def test_adm_components_consistent(self):
        r = row("adm", airlines_fare="1000", agents_fare="0", airlines_tax="50", agents_tax="0",
                airlines_commission="0", agents_commission="100", amount="1150")
        out = M.to_common("adm", r, ctx())
        self.assertNotIn("MEMO_COMPONENTS_MISMATCH", out["data_flags"])
        self.assertEqual(out["gross_amount"], D("1150"))

    def test_memo_mismatch(self):
        out = M.to_common("adm", row("adm", airlines_fare="2000", agents_fare="1000", amount="5000"), ctx())
        self.assertIn("MEMO_COMPONENTS_MISMATCH", out["data_flags"])

    def test_no_component_check_without_components(self):
        out = M.to_common("adm", row("adm", amount="5000"), ctx())
        self.assertNotIn("MEMO_COMPONENTS_MISMATCH", out["data_flags"])
        self.assertIsNone(out["base_fare"])

    def test_acm_negative(self):
        for printed in ("750.00", "-750.00", "(750.00)"):
            out = M.to_common("acm", row("acm", amount=printed), ctx("acm"))
            self.assertEqual(out["transaction_type"], C.ACM)
            self.assertEqual(out["gross_amount"], D("-750.00"), printed)
            self.assertEqual(out["net_payable"], D("-750.00"), printed)

    def test_parties_dates_and_period(self):
        out = M.to_common("adm", row("adm"), ctx())
        self.assertEqual(out["settled_with"], "BSP (BSPlink)")
        self.assertEqual(out["agent_signon"], "14312345")
        self.assertEqual((out["airline_numeric"], out["airline_code"], out["airline_name"]),
                         ("098", "AI", "Air India"))
        self.assertEqual(out["document_number"], "6000123456")
        self.assertIsNone(out["ticket_number"])
        self.assertEqual(out["related_document"], "0985805708071")
        self.assertEqual(out["issue_date"], date(2026, 7, 3))
        self.assertEqual(out["settlement_period"], "2026071")
        self.assertEqual(out["dom_intl"], "Domestic")
        self.assertEqual(out["pax_count"], 0)
        self.assertEqual(out["currency"], "INR")
        self.assertEqual(out["row_ref"], "airline_adm:7")
        self.assertEqual((out["category"], out["source_type"]), ("BSP", "ADM"))

    def test_reporting_date_fallback_and_unreadable(self):
        out = M.to_common("adm", row("adm", issue_date="", reporting_date="15-Aug-26"), ctx())
        self.assertEqual(out["issue_date"], date(2026, 8, 15))
        self.assertNotIn("DATE_UNREADABLE", out["data_flags"])
        out = M.to_common("adm", row("adm", issue_date="soon", reporting_date=None), ctx())
        self.assertIsNone(out["issue_date"])
        self.assertIn("DATE_UNREADABLE", out["data_flags"])

    def test_currency_assumed(self):
        out = M.to_common("acm", row("acm", currency=" "), ctx("acm"))
        self.assertEqual(out["currency"], "INR")
        self.assertIn("CURRENCY_ASSUMED", out["data_flags"])

    def test_sent_to_dpc_in_status_and_default_net(self):
        out = M.to_common("adm", row("adm", status="Disputed", sent_to_dpc="Yes"), ctx())
        self.assertEqual(out["status"], "Disputed; sent to DPC")
        self.assertEqual(out["counts_in_net"],
                         f"{C.NET_MEMO_NOT_BILLED} (status: Disputed, sent to DPC)")
        out = M.to_common("adm", row("adm", status=None, sent_to_dpc="No"), ctx())
        self.assertIsNone(out["status"])
        self.assertEqual(out["counts_in_net"], f"{C.NET_MEMO_NOT_BILLED} (status: unknown)")
        self.assertEqual(M.to_common("adm", row("adm", status=None, sent_to_dpc="Y"), ctx())["status"],
                         "Sent to DPC")

    def test_link_overrides_default_net(self):
        link = LinkResult(counts_in_net=C.NET_MEMO_IN_BILLING, also_in_bsp="Yes – this report")
        out = M.to_common("adm", row("adm"), ctx(), link)
        self.assertEqual(out["counts_in_net"], C.NET_MEMO_IN_BILLING)
        self.assertEqual(out["also_in_bsp"], "Yes – this report")

    def test_unparseable_amount_flag(self):
        out = M.to_common("adm", row("adm", amount="12,34"), ctx())
        self.assertIsNone(out["gross_amount"])
        self.assertIsNone(out["net_payable"])
        self.assertIn("AMOUNT_UNPARSEABLE", out["data_flags"])
        self.assertLegendOnly(out)

    def test_unparseable_component_blanks_delta(self):
        out = M.to_common("adm", row("adm", airlines_fare="abc", agents_fare="100", amount="100"), ctx())
        self.assertIsNone(out["base_fare"])
        self.assertIn("AMOUNT_UNPARSEABLE", out["data_flags"])
        self.assertEqual(out["gross_amount"], D("100"))

    def test_placeholder_amount_is_blank_not_flagged(self):
        out = M.to_common("acm", row("acm", amount="N/A"), ctx("acm"))
        self.assertIsNone(out["gross_amount"])
        self.assertNotIn("AMOUNT_UNPARSEABLE", out["data_flags"])

    def test_alpha_airline_code_resolved(self):
        out = M.to_common("adm", row("adm", airline_code="ai"), ctx())
        self.assertEqual((out["airline_numeric"], out["airline_code"]), ("098", "AI"))

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            M.to_common("bsp", row("adm"), ctx())


class RaTests(_LegendMixin, unittest.TestCase):
    def test_ra_negative_and_fields(self):
        for printed in ("1,200.00", "-1200", "1200 CR"):
            out = M.to_common("ra", row("ra", amount=printed, sent_to_dpc="TRUE"), ctx("ra"))
            self.assertEqual(out["transaction_type"], C.REFUND)
            self.assertEqual(out["source_txn_type"], "RA")
            self.assertEqual(out["gross_amount"], D("-1200.00"), printed)
            self.assertEqual(out["net_payable"], D("-1200.00"), printed)
        self.assertEqual(out["ticket_number"], "0985805708071")
        self.assertEqual(out["related_document"], "0985805708071")
        self.assertEqual(out["passenger_name"], "SHARMA/RAHUL")
        self.assertEqual(out["form_of_payment"], "CA")
        self.assertEqual(out["issue_date"], date(2026, 7, 5))
        self.assertEqual(out["status"], "Pending; sent to DPC")
        self.assertEqual(out["pax_count"], 0)
        self.assertEqual(out["row_ref"], "airline_ra:7")
        self.assertIsNone(out["base_fare"])
        self.assertIsNone(out["dom_intl"])
        self.assertLegendOnly(out)

    def test_ra_application_date_fallback(self):
        out = M.to_common("ra", row("ra", application_date=None, reporting_date="2026-07-09"), ctx("ra"))
        self.assertEqual(out["issue_date"], date(2026, 7, 9))

    def test_ra_nonstandard_rtdn(self):
        out = M.to_common("ra", row("ra", rtdn_number="58057"), ctx("ra"))
        self.assertEqual(out["ticket_number"], "58057")
        self.assertIn("TICKET_NO_NONSTANDARD", out["data_flags"])


class DetailAndKeyTests(unittest.TestCase):
    def test_pii_gating_of_contact_fields(self):
        gated = {"Contact Name", "Contact Email", "Contact Phone"}
        for kind in ("adm", "acm"):
            closed = [c.header for c in M.detail_columns(kind, ctx(kind))]
            opened = [c.header for c in M.detail_columns(kind, ctx(kind, include_pii=True))]
            self.assertFalse(gated & set(closed), kind)
            self.assertTrue(gated <= set(opened), kind)
            self.assertEqual(opened[:4], ["Row Ref", "Source File", "Upload ID", "Uploaded At (UTC)"])
            self.assertEqual(opened[4:], spec.HEADERS[kind])
        ra = [c.header for c in M.detail_columns("ra", ctx("ra"))]
        self.assertEqual(ra[4:], spec.HEADERS["ra"])          # nothing gated on RA

    def test_detail_values_money_parsed_or_raw(self):
        c = ctx("adm")
        cols = M.detail_columns("adm", c)
        headers = [x.header for x in cols]
        r = row("adm", airlines_fare="1,000.50", agents_fare="junk", amount=None, contact_email="a@b.c")
        vals = dict(zip(headers, detail_values(cols, r, c)))
        self.assertEqual(vals["Airline's Fare"], D("1000.50"))
        self.assertEqual(vals["Agent's Fare"], "junk")
        self.assertIsNone(vals["Amount"])
        self.assertEqual(vals["Issue Date"], "03/07/2026")    # as stored
        self.assertEqual(vals["Row Ref"], "airline_adm:7")
        self.assertNotIn("Contact Email", vals)
        money_kinds = {x.header: x.kind for x in cols}
        self.assertEqual(money_kinds["Amount"], "money")
        self.assertEqual(money_kinds["Status"], "text")

    def test_memo_natural_key(self):
        self.assertEqual(M.memo_natural_key("adm", row("adm", amount="1,050.00")),
                         (98 * 10**10 + 6000123456, D("1050.00")))
        self.assertEqual(M.memo_natural_key("acm", row("acm", document_number="ACM-12X", amount="x")),
                         ("098|ACM12X", None))
        self.assertEqual(M.memo_natural_key("ra", row("ra", document_number=None)), (None, D("1200.00")))


if __name__ == "__main__":
    unittest.main()
