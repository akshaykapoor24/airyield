"""Report download — NDC mapper: per-line Combined rows that roll up to the billed ticket.

Grouping is ``ndc_billing_projection.build_groups`` itself, so what is pinned here is the
report's use of it:

* fare components sit on the anchor row only — a SPLIT_BOOKING / coupon repeat and a seat
  line carry Net only (``NDC_LATCHED`` / ``NDC_ANCILLARY``), so nothing is counted twice;
* Σ Net Payable over a group equals the group total the invoice bills;
* a refund whose export prints positive magnitudes comes out negative;
* a seat line has Pax 0; group type, document key, stored-grouping fallback and the detail
  sheet's billing columns.

No DB, no network.
Run:  ..\\venv\\Scripts\\python.exe -m unittest test_report_download_map_ndc -v   (from backend/tests)
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
from app.services.report_download.mappers import base, ndc  # noqa: E402
from app.services.report_download.types import (  # noqa: E402
    AirlineInfo, AirlineMaster, DocKey, LinkResult, MapCtx, ReportOptions, UploadMeta,
)

DOC = "0982185569174"


def _line(rid: int, **data) -> SimpleNamespace:
    d = {
        "booking_signin": "desk1", "tkt_issue_signin": "tkt1", "document_no": DOC,
        "product": "Flight", "txn_type": "TICKETING", "airline_pnr": "ABC123",
        "child_parent_pnr": "PARENT1", "coupon_status": "OPEN", "airline": "AI",
        "airline_iata_code": "098", "date_of_booking": "01-07-2026", "date_of_issue": "02-07-2026",
        "departure_date": "15-07-2026", "flight_no": "AI 101", "sectors": "DEL-BOM",
        "class_of_booking": "Y", "farebasis": "YIN", "passenger_name": "NITIN CHAUHAN",
        "form_of_payment": "CASH", "currency": "INR", "payment_status": "PAID",
    }
    d.update(data)
    return SimpleNamespace(id=rid, row_seq=rid, data={k: v for k, v in d.items() if v is not None},
                           bill_group_key=None, bill_is_anchor=False, bill_latch_status=None)


def _ticketing(rid=1, **over):
    base_ = dict(total_fare="5000.00", basic_fare="4000.00", total_tax="1000.00",
                 payment_amount="5000.00", k3_tax="200.00", yq_tax="500.00", yr_tax="100.00",
                 other_taxes="200.00", penalty_amount="-150.00", service_fee="50.00",
                 discount="-25.00", tour_code="TC1")
    base_.update(over)
    return _line(rid, **base_)


def ctx() -> MapCtx:
    return MapCtx(
        upload=UploadMeta("ndc", "n1", "ndc.xlsx", datetime(2026, 7, 3)),
        airlines=AirlineMaster(by_numeric={"098": AirlineInfo("AI", "098", "Air India")}),
    )


def _rows_for(groups, c=None):
    by_row = ndc.groups_by_row(groups)
    return {r.id: ndc.to_common("ndc", r, c or ctx(), group=by_row[r.id]) for g in groups for r in g.rows}


_COMPONENTS = ("base_fare", "yq", "yr", "k3", "other_taxes", "total_taxes", "gross_amount",
               "penalty", "service_fee", "discount")


class GroupTests(unittest.TestCase):

    def setUp(self):
        self.ticket = _ticketing(1)
        self.split = _line(2, txn_type="SPLIT_BOOKING", payment_amount="1200.00",
                           total_fare="1200.00", basic_fare="1000.00", total_tax="200.00")
        self.seat = _line(3, product="Seat", txn_type="PAID_SEAT", document_no=None,
                          payment_amount="350.00", total_fare="350.00", basic_fare="300.00")
        self.groups = ndc.ndc_groups([self.seat, self.split, self.ticket])

    def test_split_booking_and_ticketing_group_carries_components_on_the_anchor_only(self):
        self.assertEqual(len(self.groups), 1)
        g = self.groups[0]
        self.assertIs(g.anchor, self.ticket)
        self.assertEqual([r.id for r in g.rows], [1, 2, 3])
        self.assertEqual(g.roles, {1: ndc.ROLE_ANCHOR, 2: ndc.ROLE_LATCHED, 3: ndc.ROLE_ANCILLARY})
        self.assertEqual(g.canon, C.SALE)
        rows = _rows_for(self.groups)

        anchor = rows[1]
        self.assertEqual(anchor["base_fare"], Decimal("4000.00"))
        self.assertEqual((anchor["yq"], anchor["yr"], anchor["k3"], anchor["other_taxes"]),
                         (Decimal("500.00"), Decimal("100.00"), Decimal("200.00"), Decimal("200.00")))
        self.assertEqual(anchor["total_taxes"], Decimal("1000.00"))
        self.assertEqual(anchor["gross_amount"], Decimal("5000.00"))
        self.assertEqual((anchor["penalty"], anchor["service_fee"], anchor["discount"]),
                         (Decimal("150.00"), Decimal("50.00"), Decimal("25.00")))
        self.assertEqual(anchor["pax_count"], 1)
        self.assertIsNone(anchor["ancillary"])
        self.assertNotIn("NDC_LATCHED", anchor["data_flags"])

        latched = rows[2]
        for col in _COMPONENTS:
            self.assertIsNone(latched[col], col)
        self.assertEqual(latched["pax_count"], 0)
        self.assertEqual(latched["net_payable"], Decimal("1200.00"))
        self.assertIn("NDC_LATCHED", latched["data_flags"])
        self.assertEqual(latched["transaction_type"], C.SALE)

        seat = rows[3]
        for col in _COMPONENTS:
            self.assertIsNone(seat[col], col)
        self.assertEqual(seat["pax_count"], 0)
        self.assertEqual((seat["ancillary"], seat["net_payable"]), (Decimal("350.00"), Decimal("350.00")))
        self.assertIn("NDC_ANCILLARY", seat["data_flags"])
        self.assertIn("NDC_LATCHED", seat["data_flags"])
        self.assertEqual(seat["transaction_type"], C.SALE)          # inherits the group's type

    def test_net_over_the_group_equals_the_group_total(self):
        g = self.groups[0]
        rows = _rows_for(self.groups)
        self.assertEqual(g.total, Decimal("6550.00"))
        self.assertEqual(sum(r["net_payable"] for r in rows.values()), g.total)

    def test_anchor_row_maps_every_ndc_column(self):
        row = _rows_for(self.groups)[1]
        self.assertEqual(row["row_ref"], "ndc:1")
        self.assertEqual((row["category"], row["source_type"]), (C.CAT_BSP, "NDC"))
        self.assertEqual(row["settled_with"], "Airline NDC – AI")
        self.assertEqual(row["agent_signon"], "tkt1")
        self.assertEqual((row["airline_numeric"], row["airline_code"], row["airline_name"]),
                         ("098", "AI", "Air India"))
        self.assertEqual((row["product"], row["source_txn_type"]), ("Air", "TICKETING/Flight"))
        self.assertEqual((row["document_number"], row["ticket_number"]), (DOC, DOC))
        self.assertEqual(row["status"], "OPEN")
        self.assertEqual((row["airline_pnr"], row["gds_ref"], row["passenger_name"]),
                         ("ABC123", "PARENT1", "NITIN CHAUHAN"))
        self.assertEqual((row["issue_date"], row["booking_date"], row["travel_date"]),
                         (date(2026, 7, 2), date(2026, 7, 1), date(2026, 7, 15)))
        self.assertEqual((row["sector"], row["flight_no"], row["booking_class"], row["fare_basis"]),
                         ("DEL-BOM", "AI 101", "Y", "YIN"))
        self.assertEqual((row["tour_code"], row["currency"], row["form_of_payment"]), ("TC1", "INR", "CASH"))
        self.assertEqual(row["net_payable"], Decimal("5000.00"))
        self.assertEqual(row["counts_in_net"], C.NET_YES)
        self.assertEqual(row["data_flags"], [])
        self.assertEqual(set(row), set(C.COMBINED_KEYS))

    def test_group_doc_key_and_natural_key(self):
        self.assertEqual(ndc.group_doc_key(self.groups[0]), DocKey("098", "2185569174"))
        self.assertEqual(ndc.ndc_natural_key(self.ticket), (DOC, "TICKETING", None, "5000.00", "02-07-2026"))


class RefundAndTypeTests(unittest.TestCase):

    def test_refund_with_positive_fare_comes_out_negative(self):
        refund = _ticketing(5, txn_type="REFUND", payment_amount="-4000.00", penalty_amount="1000.00")
        refund_seat = _line(6, product="Seat", txn_type="REFUND_SEAT", document_no=None,
                            payment_amount="350.00")
        sale = _ticketing(4)
        groups = ndc.ndc_groups([sale, refund, refund_seat])
        by_key = {g.key: g for g in groups}
        credit = by_key[f"C:{DOC}"]
        self.assertEqual(credit.canon, C.REFUND)
        self.assertEqual(by_key[f"D:{DOC}"].canon, C.SALE)
        rows = _rows_for(groups)
        r = rows[5]
        self.assertEqual(r["transaction_type"], C.REFUND)
        self.assertEqual(r["gross_amount"], Decimal("-5000.00"))
        self.assertEqual(r["base_fare"], Decimal("-4000.00"))
        self.assertEqual(r["k3"], Decimal("-200.00"))
        self.assertEqual(r["penalty"], Decimal("1000.00"))          # unsigned column
        self.assertEqual(r["net_payable"], Decimal("-4000.00"))
        self.assertEqual(rows[6]["net_payable"], Decimal("-350.00"))
        self.assertEqual(rows[6]["transaction_type"], C.REFUND)
        self.assertEqual(sum(rows[i]["net_payable"] for i in (5, 6)), credit.total)

    def test_orphan_seat_line_is_its_own_emd_with_pax_zero(self):
        seat = _line(8, product="Seat", txn_type="PAID_SEAT", document_no=None,
                     airline_pnr="ZZZ999", payment_amount="400.00", basic_fare="400.00")
        (g,) = ndc.ndc_groups([seat])
        self.assertEqual(g.canon, C.EMD)
        self.assertIsNone(ndc.group_doc_key(g))
        row = ndc.to_common("ndc", seat, ctx(), group=g)
        self.assertEqual(row["pax_count"], 0)
        self.assertIn("NDC_ANCILLARY", row["data_flags"])
        self.assertNotIn("NDC_LATCHED", row["data_flags"])
        self.assertIsNone(row["base_fare"])
        self.assertEqual((row["ancillary"], row["net_payable"]), (Decimal("400.00"), Decimal("400.00")))

    def test_zero_settled_ticket_is_void(self):
        (g,) = ndc.ndc_groups([_ticketing(9, payment_amount="0.00")])
        self.assertEqual(g.canon, C.VOID)

    def test_stored_grouping_fallback_is_flagged(self):
        coupon = _line(11, txn_type="SPLIT_BOOKING", payment_amount="1200.00", basic_fare="1000.00")
        coupon.bill_latch_status = "latched"
        row = ndc.to_common("ndc", coupon, ctx())
        self.assertIn("NDC_GROUPING_STORED", row["data_flags"])
        self.assertIn("NDC_LATCHED", row["data_flags"])
        self.assertIsNone(row["base_fare"])
        self.assertEqual(row["net_payable"], Decimal("1200.00"))
        anchor = ndc.to_common("ndc", _ticketing(12), ctx())
        self.assertEqual(anchor["base_fare"], Decimal("4000.00"))
        self.assertEqual(anchor["pax_count"], 1)

    def test_dates_currency_and_unreadable_amounts(self):
        line = _ticketing(13, date_of_issue=None, currency=None, basic_fare="abc")
        (g,) = ndc.ndc_groups([line])
        row = ndc.to_common("ndc", line, ctx(), group=g)
        self.assertEqual(row["issue_date"], date(2026, 7, 1))       # booking date fallback
        self.assertEqual(row["currency"], "INR")
        self.assertIn("CURRENCY_ASSUMED", row["data_flags"])
        self.assertIsNone(row["base_fare"])
        self.assertIn("AMOUNT_UNPARSEABLE", row["data_flags"])
        undated = _ticketing(14, date_of_issue=None, date_of_booking=None)
        (g2,) = ndc.ndc_groups([undated])
        self.assertIn("DATE_UNREADABLE", ndc.to_common("ndc", undated, ctx(), group=g2)["data_flags"])

    def test_link_is_applied_last(self):
        line = _ticketing(15)
        (g,) = ndc.ndc_groups([line])
        link = LinkResult(also_in_bsp="Yes – this report", counts_in_net=C.NET_NDC_IN_BSP)
        row = ndc.to_common("ndc", line, ctx(), link=link, group=g)
        self.assertEqual((row["also_in_bsp"], row["counts_in_net"]), ("Yes – this report", C.NET_NDC_IN_BSP))


class DetailSheetTests(unittest.TestCase):

    def test_columns_values_and_billing_grouping(self):
        c = MapCtx(upload=UploadMeta("ndc", "n1", "ndc.xlsx", datetime(2026, 7, 3)),
                   options=ReportOptions(include_pii=False), extra_keys=("portal_ref", "card_number"))
        cols = ndc.detail_columns("ndc", c)
        headers = [col.header for col in cols]
        self.assertEqual(headers[:4], ["Row Ref", "Source File", "Upload ID", "Uploaded At (UTC)"])
        self.assertEqual(headers[-4:], ["Group Key", "Anchor", "Latch Status", "data.portal_ref"])
        self.assertIn("Passenger Name", headers)
        line = _ticketing(21, total_fare="1,234.50", basic_fare="n/a?", portal_ref="P-9")
        line.bill_group_key, line.bill_is_anchor, line.bill_latch_status = f"D:{DOC}", True, "anchor"
        values = dict(zip(headers, base.detail_values(cols, line, c)))
        self.assertEqual(values["Row Ref"], "ndc:21")
        self.assertEqual(values["Total Fare"], Decimal("1234.50"))
        self.assertEqual(values["Basic Fare"], "n/a?")
        self.assertEqual((values["Group Key"], values["Anchor"], values["Latch Status"]),
                         (f"D:{DOC}", "Yes", "anchor"))
        self.assertEqual(values["data.portal_ref"], "P-9")
        self.assertEqual({col.header: col.kind for col in cols}["Payment Amount"], "money")


if __name__ == "__main__":
    unittest.main()
