"""BSP Detailed / Summary mapper for the Workspace report download.

A BSP statement is the settlement document, so the cases below pin — in order of
consequence — that no printed amount is ever re-signed (refunds, card-paid balances, negative
CANX), that the component check reads signed values (a refund with a retained penalty is
consistent), that K3 never absorbs IN, that a blank pivot stays blank, and that TGQ
enrichment anchors travel years the way the commission engine does. Summary line kinds must
match the frontend so a user adding up the sheet never counts an airline twice.

No DB, no network: rows are SimpleNamespace views carrying every BspStatementRow column.

Run:  ..\\venv\\Scripts\\python.exe -m unittest test_report_download_map_bsp -v   (from backend/tests)
"""

import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.bsp_statement import BspStatementRow  # noqa: E402
from app.services.bsp_tgq_enrichment import TgqTicket  # noqa: E402
from app.services.report_download import columns as C  # noqa: E402
from app.services.report_download.mappers import bsp as M  # noqa: E402
from app.services.report_download.mappers.base import detail_values  # noqa: E402
from app.services.report_download.types import (  # noqa: E402
    AirlineInfo, AirlineMaster, LinkResult, MapCtx, ReportOptions, TaxComponent, UploadMeta,
)

_FIELDS = tuple(c.name for c in BspStatementRow.__table__.columns)
D = Decimal


def row(**kw):
    base = {f: None for f in _FIELDS}
    base.update(id=101, statement_id="stmt-1", airline_accounting_code="098",
                transaction_type="TKTT", issue_date=date(2026, 7, 3), taxes=[])
    base.update(kw)
    return SimpleNamespace(**base)


def tax(ctype, code, amount):
    return TaxComponent(ctype, code, None if amount is None else D(str(amount)))


def header(**kw):
    base = dict(batch_id="stmt-1", file_name="bsp.pdf", period_from=date(2026, 7, 1),
                period_to=date(2026, 7, 15), statement_name="BSP 1-15 Jul")
    base.update(kw)
    return SimpleNamespace(**base)


def summary(**kw):
    base = dict(agent_code="14312345", agent_name="ACME TRAVELS", currency="INR",
                billing_period_code="2026071", period_from=date(2026, 7, 1),
                period_to=date(2026, 7, 15), match_status="matched")
    base.update(kw)
    return SimpleNamespace(**base)


def ctx(*, hdr=None, sm="default", tax_codes=(), extra_keys=(), tgq_files=None):
    airlines = AirlineMaster(by_numeric={"098": AirlineInfo("AI", "098", "Air India")},
                             by_iata={"AI": AirlineInfo("AI", "098", "Air India")})
    up = UploadMeta(source_key="bsp", upload_id="stmt-1", file_name="bsp.pdf",
                    uploaded_at=datetime(2026, 7, 16, 9, 0),
                    header=hdr if hdr is not None else header(),
                    summary_header=summary() if sm == "default" else sm)
    return MapCtx(upload=up, options=ReportOptions(), airlines=airlines,
                  tgq_files=tgq_files or {}, tax_codes=tuple(tax_codes), extra_keys=tuple(extra_keys))


def flags(out):
    return list(out["data_flags"])


class _LegendMixin:
    def assertLegendOnly(self, out):
        for f in out["data_flags"]:
            self.assertIn(f, C.FLAG_LEGEND)


class AsStoredMoneyTests(_LegendMixin, unittest.TestCase):
    def test_rfnd_negative_written_as_stored(self):
        out = M.to_common("bsp", row(transaction_type="RFND", ticket_number="5805708071",
                                     document_number="5805708071",
                                     transaction_amount=D("-9200.00"), fare_amount=D("-9000"),
                                     penalty_amount=D("280"), balance_payable=D("-9200"),
                                     taxes=[tax("TAX", "YQ", -480)]), ctx())
        self.assertEqual(out["transaction_type"], C.REFUND)
        self.assertEqual(out["gross_amount"], D("-9200.00"))
        self.assertEqual(out["net_payable"], D("-9200"))
        self.assertEqual(out["base_fare"], D("-9000"))
        self.assertEqual(out["penalty"], D("280"))
        self.assertEqual(out["counts_in_net"], C.NET_YES)
        self.assertLegendOnly(out)

    def test_rfnd_positive_not_resigned(self):
        out = M.to_common("bsp", row(transaction_type="RFND", ticket_number="5805708071",
                                     transaction_amount=D("150.00"), balance_payable=D("150.00")), ctx())
        self.assertEqual(out["gross_amount"], D("150.00"))
        self.assertEqual(out["net_payable"], D("150.00"))

    def test_card_paid_tktt_negative_balance_preserved(self):
        out = M.to_common("bsp", row(form_of_payment="CC", ticket_number="5805708071",
                                     document_number="5805708071",
                                     transaction_amount=D("10500"), fare_amount=D("10000"),
                                     standard_commission_amount=D("-40"),
                                     balance_payable=D("-40"), taxes=[tax("TAX", "K3", 500)]), ctx())
        self.assertEqual(out["transaction_type"], C.SALE)
        self.assertEqual(out["form_of_payment"], "CC")
        self.assertEqual(out["gross_amount"], D("10500"))
        self.assertEqual(out["net_payable"], D("-40"))
        self.assertEqual(out["commission"], D("-40"))
        self.assertNotIn("GROSS_COMPONENTS_MISMATCH", flags(out))

    def test_negative_canx_preserved(self):
        out = M.to_common("bsp", row(transaction_type="CANX", ticket_number="5805708071",
                                     document_number="5805708071", transaction_amount=D("-500")), ctx())
        self.assertEqual(out["transaction_type"], C.CANCELLATION)
        self.assertEqual(out["gross_amount"], D("-500"))
        self.assertEqual(out["document_number"], "5805708071")
        self.assertEqual(out["pax_count"], 1)
        self.assertNotIn("SPDR_DISTRIBUTED", flags(out))

    def test_canx_with_spdr_no_uses_ticket_number(self):
        r = row(transaction_type="CANX", ticket_number="5805708071", document_number="9100000001",
                spdr_no="9100000001", transaction_amount=D("-1500"),
                raw_data={"section": "ISSUES", "settlement_section": "DEBIT MEMOS",
                          "settlement_category": "BSP"})
        out = M.to_common("bsp", r, ctx())
        self.assertEqual(out["document_number"], "5805708071")
        self.assertEqual(out["ticket_number"], "0985805708071")
        self.assertEqual(out["related_document"], "9100000001")
        self.assertEqual(out["gross_amount"], D("-1500"))
        self.assertIn("SPDR_DISTRIBUTED", flags(out))
        self.assertLegendOnly(out)

    def test_spdr_zeroed_and_stat_amended(self):
        out = M.to_common("bsp", row(transaction_type="SPDR", document_number="9100000001",
                                     ticket_number="9100000001", transaction_amount=D("0"),
                                     raw_data={"spdr_split": {"amount": "1500", "unit": "500", "count": 3},
                                               "stat_amended": True}), ctx())
        self.assertEqual(out["transaction_type"], C.ADM)
        self.assertEqual(out["pax_count"], 0)
        self.assertIn("SPDR_ZEROED", flags(out))
        self.assertIn("STAT_AMENDED", flags(out))

    def test_emd_ancillary_and_tasf_service_fee(self):
        emd = M.to_common("bsp", row(transaction_type="EMDA", document_number="5800000001",
                                     transaction_amount=D("1200")), ctx())
        self.assertEqual(emd["transaction_type"], C.EMD)
        self.assertEqual(emd["ancillary"], D("1200"))
        self.assertEqual(emd["pax_count"], 0)
        self.assertIsNone(emd["ticket_number"])
        tasf = M.to_common("bsp", row(transaction_type="TASF", document_number="5800000002",
                                      ticket_number="5800000002", transaction_amount=D("-350")), ctx())
        self.assertEqual(tasf["transaction_type"], C.AGENT_FEE)
        self.assertEqual(tasf["service_fee"], D("350"))
        self.assertEqual(tasf["gross_amount"], D("-350"))
        self.assertEqual(tasf["pax_count"], 0)


class GrossCheckTests(unittest.TestCase):
    def test_refund_with_penalty_passes_signed_check(self):
        out = M.to_common("bsp", row(transaction_type="RFND", ticket_number="5805708071",
                                     fare_amount=D("-9000"), penalty_amount=D("280"),
                                     transaction_amount=D("-9200"),
                                     taxes=[tax("TAX", "YQ", -480), tax("PENALTY", "CP", 280)]), ctx())
        self.assertNotIn("GROSS_COMPONENTS_MISMATCH", flags(out))
        self.assertEqual(out["penalty"], D("280"))       # PENALTY breakup not added again

    def test_real_mismatch_flags(self):
        out = M.to_common("bsp", row(transaction_type="RFND", ticket_number="5805708071",
                                     fare_amount=D("-9000"), penalty_amount=D("280"),
                                     transaction_amount=D("-9760"),
                                     taxes=[tax("TAX", "YQ", -480)]), ctx())
        self.assertIn("GROSS_COMPONENTS_MISMATCH", flags(out))

    def test_check_skipped_without_fare(self):
        out = M.to_common("bsp", row(transaction_amount=D("5000"), ticket_number="5805708071"), ctx())
        self.assertNotIn("GROSS_COMPONENTS_MISMATCH", flags(out))

    def test_fee_counts_in_check(self):
        out = M.to_common("bsp", row(ticket_number="5805708071", fare_amount=D("1000"),
                                     transaction_amount=D("1180"),
                                     taxes=[tax("TAX", "K3", 50), tax("FEE", "OB", 130)]), ctx())
        self.assertNotIn("GROSS_COMPONENTS_MISMATCH", flags(out))


class TaxPivotTests(unittest.TestCase):
    def test_k3_excludes_in(self):
        taxes = [tax("TAX", "K3", 100), tax("TAX", "IN", 50), tax("TAX", "YQ", 200),
                 tax("TAX", "yr", 10), tax("FEE", "OB", 20), tax("PENALTY", "CP", 999),
                 tax("TAX", "YQ", 5)]
        self.assertEqual(M.tax_pivot(taxes), {"K3": D(100), "IN": D(50), "YQ": D(205), "YR": D(10), "OB": D(20)})
        self.assertEqual(M.tax_type_sums(taxes), (D(365), D(20)))
        out = M.to_common("bsp", row(ticket_number="5805708071", taxes=taxes), ctx())
        self.assertEqual(out["k3"], D(100))
        self.assertEqual(out["yq"], D(205))
        self.assertEqual(out["yr"], D(10))
        self.assertEqual(out["total_taxes"], D(385))
        self.assertEqual(out["other_taxes"], D(70))      # IN 50 + OB 20

    def test_blank_pivot_stays_blank(self):
        self.assertEqual(M.tax_pivot([]), {})
        self.assertEqual(M.tax_pivot(None), {})
        self.assertEqual(M.tax_type_sums([tax("PENALTY", "CP", 10), tax("TAX", "YQ", None)]), (None, None))
        out = M.to_common("bsp", row(ticket_number="5805708071", transaction_amount=D("1000")), ctx())
        for key in ("yq", "yr", "k3", "other_taxes", "total_taxes", "base_fare", "penalty"):
            self.assertIsNone(out[key], key)

    def test_negative_tax_residual(self):
        out = M.to_common("bsp", row(ticket_number="5805708071",
                                     taxes=[tax("TAX", "YQ", 150), tax("TAX", "XT", -50)]), ctx())
        self.assertEqual(out["other_taxes"], D(-50))
        self.assertIn("NEG_TAX_RESIDUAL", flags(out))


class IdentityTests(_LegendMixin, unittest.TestCase):
    def test_parties_currency_and_period(self):
        out = M.to_common("bsp", row(ticket_number="0985805708071", stat="I71", tour=["INGBAFF500", "X"]), ctx())
        self.assertEqual(out["settled_with"], "BSP – ACME TRAVELS")
        self.assertEqual(out["agent_signon"], "14312345")
        self.assertEqual(out["airline_numeric"], "098")
        self.assertEqual(out["airline_code"], "AI")
        self.assertEqual(out["airline_name"], "Air India")
        self.assertEqual(out["currency"], "INR")
        self.assertEqual(out["dom_intl"], "International")
        self.assertEqual(out["tour_code"], "INGBAFF500")
        self.assertEqual(out["settlement_period"], "01-Jul-2026 – 15-Jul-2026 (2026071)")
        self.assertEqual(out["row_ref"], "bsp_statement_rows:101")
        self.assertEqual((out["category"], out["source_type"], out["product"]), ("BSP", "BSP", "Air"))
        self.assertEqual(out["ticket_number"], "0985805708071")
        self.assertNotIn("CURRENCY_ASSUMED", flags(out))

    def test_currency_assumed_without_summary(self):
        out = M.to_common("bsp", row(ticket_number="5805708071"), ctx(sm=None))
        self.assertEqual(out["currency"], "INR")
        self.assertIn("CURRENCY_ASSUMED", flags(out))
        self.assertEqual(out["settled_with"], "BSP")
        self.assertIsNone(out["agent_signon"])
        self.assertEqual(out["settlement_period"], "01-Jul-2026 – 15-Jul-2026")

    def test_issue_date_fallback(self):
        out = M.to_common("bsp", row(ticket_number="5805708071", issue_date=None), ctx())
        self.assertEqual(out["issue_date"], date(2026, 7, 1))
        self.assertIn("ISSUE_DATE_FALLBACK", flags(out))
        out = M.to_common("bsp", row(issue_date=None), ctx(hdr=header(period_from=None)))
        self.assertIsNone(out["issue_date"])
        self.assertIn("DATE_UNREADABLE", flags(out))

    def test_refund_notice_takes_ticket_from_rtdn(self):
        r = row(transaction_type="RFND", document_number="0012345678", ticket_number=None,
                rtdn=None, associated_docs={"rtdn": {"doc": "5805708071"},
                                            "exchanges": [{"doc": "5805708071"}]})
        out = M.to_common("bsp", r, ctx())
        self.assertEqual(out["document_number"], "0012345678")
        self.assertEqual(out["ticket_number"], "0985805708071")
        self.assertEqual(out["related_document"], "0985805708071")
        self.assertEqual(out["transaction_type"], C.REFUND)
        self.assertEqual(out["pax_count"], 1)

    def test_exchange_related_document(self):
        r = row(ticket_number="5805708099", document_number="5805708099",
                associated_docs={"exchanges": [{"doc": "5805708071", "indicator": "EX"}]})
        out = M.to_common("bsp", r, ctx())
        self.assertEqual(out["transaction_type"], C.EXCHANGE)
        self.assertEqual(out["related_document"], "0985805708071")

    def test_nonstandard_ticket_flag(self):
        out = M.to_common("bsp", row(ticket_number="5800920932-933"), ctx())
        self.assertEqual(out["ticket_number"], "5800920932-933")
        self.assertIn("TICKET_NO_NONSTANDARD", flags(out))

    def test_legacy_row_fallback(self):
        r = row(transaction_type="refund", airline_accounting_code=None, airline_code="AI",
                ticket_number="0985805708071", document_number="0985805708071",
                gross=D("-1000"), commission=D("-50"), net_due=D("-950"))
        out = M.to_common("bsp", r, ctx())
        self.assertEqual(out["transaction_type"], C.REFUND)
        self.assertIn("LEGACY_BSP_EXCEL", flags(out))
        self.assertEqual(out["base_fare"], D("-1000"))
        self.assertEqual(out["gross_amount"], D("-1000"))
        self.assertEqual(out["commission"], D("-50"))
        self.assertEqual(out["net_payable"], D("-950"))
        self.assertEqual(out["airline_code"], "AI")
        self.assertEqual(out["airline_numeric"], "098")
        self.assertLegendOnly(out)

    def test_legacy_detected_from_money_columns(self):
        out = M.to_common("bsp", row(transaction_type="TKTT", ticket_number="5805708071", gross=D("900")), ctx())
        self.assertIn("LEGACY_BSP_EXCEL", flags(out))

    def test_unknown_type_flag(self):
        out = M.to_common("bsp", row(transaction_type="ZZZZ", ticket_number="5805708071"), ctx())
        self.assertEqual(out["transaction_type"], C.UNKNOWN)
        self.assertIn("TXN_UNMAPPED", flags(out))

    def test_link_applied_last(self):
        link = LinkResult(counts_in_net=C.NET_SUPERSEDED, linked_via="override", flags=["ALSO_IN_NDC"])
        out = M.to_common("bsp", row(ticket_number="5805708071"), ctx(), link)
        self.assertEqual(out["counts_in_net"], C.NET_SUPERSEDED)
        self.assertEqual(out["linked_via"], "override")
        self.assertIn("ALSO_IN_NDC", flags(out))

    def test_summary_source_has_no_combined_rows(self):
        with self.assertRaises(ValueError):
            M.to_common("bsp-summary", row(), ctx())

    def test_natural_key(self):
        r = row(document_number="5805708071", transaction_amount=D("100.00"))
        self.assertEqual(M.bsp_natural_key(r), (98 * 10**10 + 5805708071, C.SALE, D("100.00"), date(2026, 7, 3)))
        self.assertEqual(M.bsp_natural_key(row(document_number="12AB", airline_accounting_code=None))[0], "|12AB")
        self.assertIsNone(M.bsp_natural_key(row(document_number=None))[0])


def ticket(**kw):
    base = dict(sector="BOM/DEL", booking_class="L/U", travel_raw="14MAY", ticket_date_raw="23APR26",
                leg_count=2, batch_id="tgq-1", pax_name="SHARMA/RAHUL MR", air_pnr="ABC123",
                gal_pnr="XYZ789", flight_numbers="AI-2928/AI-2362", fare_basis="LOWIN")
    base.update(kw)
    return TgqTicket(**base)


class TgqEnrichmentTests(_LegendMixin, unittest.TestCase):
    def test_sale_enriched_from_tgq(self):
        out = M.to_common("bsp", row(ticket_number="5805708071", document_number="5805708071",
                                     issue_date=date(2026, 4, 23)),
                          ctx(tgq_files={"tgq-1": "hmpr_apr.xlsx"}), tgq=(ticket(), "document"))
        self.assertEqual(out["passenger_name"], "SHARMA/RAHUL MR")
        self.assertEqual(out["airline_pnr"], "ABC123")
        self.assertEqual(out["gds_ref"], "XYZ789")
        self.assertEqual(out["flight_no"], "AI-2928/AI-2362")
        self.assertEqual(out["fare_basis"], "LOWIN")
        self.assertEqual(out["sector"], "BOM/DEL")
        self.assertEqual(out["booking_class"], "L/U")
        self.assertEqual(out["travel_date"], date(2026, 5, 14))
        self.assertEqual(out["tgq_enriched"], "Yes (document)")
        self.assertEqual(out["linked_via"], "TGQ HMPR document (hmpr_apr.xlsx)")
        self.assertIn("TRAVEL_YEAR_INFERRED", flags(out))
        self.assertNotIn("TGQ_ENRICH_STORED", flags(out))
        self.assertLegendOnly(out)

    def test_sale_travel_anchored_on_bsp_issue_date(self):
        # TGQ's own ticket date is a year off; the BSP issue date is authoritative for a sale.
        out = M.to_common("bsp", row(ticket_number="5805708071", issue_date=date(2026, 12, 23)),
                          ctx(), tgq=(ticket(travel_raw="05JAN", ticket_date_raw="23DEC25"), "rtdn"))
        self.assertEqual(out["travel_date"], date(2027, 1, 5))
        self.assertEqual(out["tgq_enriched"], "Yes (rtdn)")
        self.assertEqual(out["linked_via"], "TGQ HMPR rtdn")

    def test_refund_travel_anchored_on_tgq_ticket_date(self):
        # A refund settles months after issue; anchoring on its issue date would push travel a year.
        out = M.to_common("bsp", row(transaction_type="RFND", ticket_number="5805708071",
                                     issue_date=date(2027, 1, 10)),
                          ctx(), tgq=(ticket(), "document"))
        self.assertEqual(out["travel_date"], date(2026, 5, 14))
        self.assertIn("TRAVEL_YEAR_INFERRED", flags(out))

    def test_explicit_travel_date_not_flagged(self):
        out = M.to_common("bsp", row(ticket_number="5805708071"), ctx(),
                          tgq=(ticket(travel_raw="14MAY26"), "normalised"))
        self.assertEqual(out["travel_date"], date(2026, 5, 14))
        self.assertNotIn("TRAVEL_YEAR_INFERRED", flags(out))

    def test_stored_enrichment_fallback(self):
        r = row(ticket_number="5805708071", enriched_sector="DEL/BOM", enriched_booking_class="Y",
                enriched_travel_date=date(2026, 8, 1), enriched_travel_date_source="inferred")
        out = M.to_common("bsp", r, ctx())
        self.assertEqual(out["sector"], "DEL/BOM")
        self.assertEqual(out["booking_class"], "Y")
        self.assertEqual(out["travel_date"], date(2026, 8, 1))
        self.assertEqual(out["tgq_enriched"], "No")
        self.assertIn("TGQ_ENRICH_STORED", flags(out))
        self.assertIn("TRAVEL_YEAR_INFERRED", flags(out))
        self.assertIsNone(out["passenger_name"])
        self.assertIsNone(out["linked_via"])

    def test_no_enrichment_at_all(self):
        out = M.to_common("bsp", row(ticket_number="5805708071"), ctx())
        self.assertEqual(out["tgq_enriched"], "No")
        self.assertNotIn("TGQ_ENRICH_STORED", flags(out))
        self.assertIsNone(out["travel_date"])

    def test_live_match_blank_sector_uses_stored(self):
        out = M.to_common("bsp", row(ticket_number="5805708071", enriched_sector="DEL/BOM"), ctx(),
                          tgq=(ticket(sector=None), "document"))
        self.assertEqual(out["sector"], "DEL/BOM")
        self.assertIn("TGQ_ENRICH_STORED", flags(out))


def srow(id, category, code, fop, balance=None, name=None):
    return SimpleNamespace(id=id, category=category, airline_code=code, airline_iata=None,
                           airline_name=name, fop=fop, issues=D("100"), refunds=None,
                           debit_memos=None, credit_memos=None, std_comm=None, sup_comm=None,
                           tax_on_comm=None, balance_payable=balance, doc_count=3)


class SummaryTests(unittest.TestCase):
    def test_line_kinds_multi_fop_and_single(self):
        rows = [srow(1, "BSP", "098", "CASH"), srow(2, "BSP", "098", "CARD"),
                srow(3, "BSP", "098", "TOTAL", D("500")), srow(4, "BSP", "176", "CASH", D("90")),
                srow(5, "WEBSALES-EDIS", "098", "CASH", D("10"))]
        kinds = M.summary_line_kinds(rows)
        self.assertEqual(kinds[1], (M.LINE_FOP, False))
        self.assertEqual(kinds[2], (M.LINE_FOP, False))
        self.assertEqual(kinds[3], (M.LINE_TOTAL, True))
        self.assertEqual(kinds[4], (M.LINE_SINGLE, True))
        self.assertEqual(kinds[5], (M.LINE_SINGLE, True))    # a different category is its own group

    def test_line_kinds_without_total_line(self):
        rows = [srow(1, None, None, "CASH", name="X AIR"), srow(2, None, None, "CARD", D("5"), name="X AIR"),
                srow(3, "BSP", "001", "CASH"), srow(4, "BSP", "001", "CARD")]
        kinds = M.summary_line_kinds(rows)
        self.assertEqual(kinds[2], (M.LINE_TOTAL, True))     # first line with a balance
        self.assertEqual(kinds[1], (M.LINE_FOP, False))
        self.assertEqual(kinds[4], (M.LINE_TOTAL, True))     # else the last line
        self.assertEqual(kinds[3], (M.LINE_FOP, False))

    def test_summary_detail_columns(self):
        sm = summary()
        c = ctx(hdr=sm)
        cols = M.detail_columns("bsp-summary", c)
        headers = [x.header for x in cols]
        self.assertEqual(headers[:4], ["Row Ref", "Source File", "Upload ID", "Uploaded At (UTC)"])
        for h in ("Category", "Airline Code", "IATA", "Airline", "FOP", "Issues", "Refunds",
                  "Debit Memos", "Credit Memos", "Std Comm", "Sup Comm", "Tax on Comm",
                  "Balance Payable", "Docs", "Agent Code", "Agent", "Period", "Billing Period Code",
                  "Currency", "Match Status", "Line Kind", "Use For Totals"):
            self.assertIn(h, headers)
        r = srow(7, "BSP", "098", "TOTAL", D("500"))
        r.line_kind, r.use_for_totals = M.LINE_TOTAL, True
        vals = dict(zip(headers, detail_values(cols, r, c)))
        self.assertEqual(vals["Row Ref"], "bsp_summary_rows:7")
        self.assertEqual(vals["Issues"], D("100"))
        self.assertIsNone(vals["Refunds"])
        self.assertEqual(vals["Agent"], "ACME TRAVELS")
        self.assertEqual(vals["Period"], "01-Jul-2026 – 15-Jul-2026")
        self.assertEqual(vals["Line Kind"], M.LINE_TOTAL)
        self.assertEqual(vals["Use For Totals"], "Y")
        bare = dict(zip(headers, detail_values(cols, srow(8, "BSP", "098", "CASH"), c)))
        self.assertIsNone(bare["Line Kind"])
        self.assertIsNone(bare["Use For Totals"])


class TieOutTests(unittest.TestCase):
    def test_sections(self):
        self.assertEqual(M.tie_out_section(row(raw_data={"section": "ISSUES"})), "ISSUE")
        self.assertEqual(M.tie_out_section(row(raw_data={"section": "Refunds"})), "REFUND")
        self.assertEqual(M.tie_out_section(row(raw_data={"section": "ISSUES",
                                                         "settlement_section": "DEBIT MEMOS"})), "DEBIT")
        self.assertEqual(M.tie_out_section(row(raw_data={"section": "CREDIT MEMOS",
                                                         "settlement_section": None})), "CREDIT")
        self.assertEqual(M.tie_out_section(row(raw_data='{"section": "ISSUES"}')), "ISSUE")
        self.assertIsNone(M.tie_out_section(row(raw_data={"section": "TOTALS"})))
        self.assertIsNone(M.tie_out_section(row(raw_data=None)))


class DetailColumnTests(unittest.TestCase):
    def test_bsp_detail_columns_and_values(self):
        c = ctx(tax_codes=("YQ", "YR", "K3", "IN"))
        cols = M.detail_columns("bsp", c)
        headers = [x.header for x in cols]
        self.assertEqual(headers[:4], ["Row Ref", "Source File", "Upload ID", "Uploaded At (UTC)"])
        for h in ("Document #", "Ticket No", "Txn", "Air", "Airline", "Issue Date", "CPUI", "NR", "STAT",
                  "FOP", "Txn Amt", "Fare", "Tax (TAX)", "F&C (FEE)", "Pen", "Net Sales", "Std %",
                  "Std Comm", "Supp %", "Supp Disc", "Tax/Comm", "Balance", "Tour", "Alt Docs",
                  "SPDR No", "RTDN", "Assoc RTDN", "Exchanges", "ESAC", "WAVR", "Section", "Category",
                  "Settlement Section", "Settlement Category", "SPDR Split", "Stat Amended",
                  "Match Status", "Commission Status", "Calculated Incentive", "Matched Deal",
                  "Enriched Sector", "Enriched Class", "Enriched Travel Date", "Enrichment Ref"):
            self.assertIn(h, headers)
        self.assertEqual(headers[-4:], ["Tax YQ", "Tax YR", "Tax K3", "Tax IN"])
        self.assertNotIn("Gross", headers)
        self.assertNotIn("Tax (other codes)", headers)

        r = row(document_number="5805708071", transaction_amount=D("-9200"), tour=["T1", "T2"],
                alt_document_numbers=["5805708072"], associated_docs={"rtdn": {"doc": "5805700000"}},
                raw_data={"section": "REFUNDS", "spdr_split": {"amount": "1500", "unit": "500", "count": 3},
                          "stat_amended": True},
                taxes=[tax("TAX", "YQ", -400), tax("FEE", "OB", -20), tax("PENALTY", "CP", 280)])
        vals = dict(zip(headers, detail_values(cols, r, c)))
        self.assertEqual(vals["Txn Amt"], D("-9200"))
        self.assertEqual(vals["Tax (TAX)"], D("-400"))
        self.assertEqual(vals["F&C (FEE)"], D("-20"))
        self.assertIsNone(vals["Fare"])
        self.assertEqual(vals["Tax YQ"], D("-400"))
        self.assertIsNone(vals["Tax K3"])                   # blank, never 0
        self.assertEqual(vals["Tour"], "T1, T2")
        self.assertEqual(vals["Assoc RTDN"], "5805700000")
        self.assertEqual(vals["Section"], "REFUNDS")
        self.assertEqual(vals["SPDR Split"], "1500 split into 3 × 500")
        self.assertEqual(vals["Stat Amended"], "Yes")
        self.assertEqual(vals["Statement Period"], "01-Jul-2026 – 15-Jul-2026")
        # The per-row tax cache must not leak one row's pivot into the next row.
        vals2 = dict(zip(headers, detail_values(cols, row(taxes=[tax("TAX", "K3", 7)]), c)))
        self.assertIsNone(vals2["Tax YQ"])
        self.assertEqual(vals2["Tax K3"], D(7))

    def test_legacy_columns_and_tax_cap(self):
        codes = tuple(f"C{i:02d}" for i in range(M.TAX_PIVOT_CAP + 2))
        c = ctx(tax_codes=codes, extra_keys=(M.LEGACY_KEY,))
        cols = M.detail_columns("bsp", c)
        headers = [x.header for x in cols]
        self.assertEqual(headers[-7:], ["Tax (other codes)", "Gross", "Commission", "ADM", "ACM", "Refund", "Net Due"])
        self.assertEqual(sum(h.startswith("Tax C") for h in headers), M.TAX_PIVOT_CAP)
        r = row(gross=D("1000"), taxes=[tax("TAX", codes[-1], 3), tax("TAX", codes[-2], 4), tax("TAX", "C00", 1)])
        vals = dict(zip(headers, detail_values(cols, r, c)))
        self.assertEqual(vals["Tax (other codes)"], D(7))
        self.assertEqual(vals["Tax C00"], D(1))
        self.assertEqual(vals["Gross"], D("1000"))
        self.assertIsNone(vals["Net Due"])

    def test_unknown_source(self):
        with self.assertRaises(ValueError):
            M.detail_columns("tgq-hmpr", ctx())


if __name__ == "__main__":
    unittest.main()
