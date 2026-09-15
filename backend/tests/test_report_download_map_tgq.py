"""Report download — TGQ HMPR mapper: re-assembling a ticket from its per-sector legs.

Legs are built by running the REAL ingest split (``sector_split.apply_ticket_no`` +
``split_row`` with the TGQ spec config, mirroring ``api/v1/statements._build_rows``), so the
tests exercise exactly what the table holds. Pinned, in order of consequence:

* money is folded from ``orig_data`` when present, summed across legs only when every leg
  holds an allocated number, and a copied non-numeric cell ("₹11,800") is never multiplied;
* refunds use Total_Refund_Amount and the refund date, and come out negative;
* AirlineFee lands in Other Taxes; K3 / YR (and YQ when YQTax is blank) come from the taxes;
* pre-split batches, grand-total lines, and a ticket whose legs straddle a fetch chunk;
* card data never reaches the workbook; contact data only with the PII option.

No DB, no network.
Run:  ..\\venv\\Scripts\\python.exe -m unittest test_report_download_map_tgq -v   (from backend/tests)
"""
import itertools
import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402
from app.services import sector_split  # noqa: E402
from app.services import statement_spec as spec  # noqa: E402
from app.services.report_download import columns as C  # noqa: E402
from app.services.report_download.mappers import base, tgq  # noqa: E402
from app.services.report_download.types import (  # noqa: E402
    AirlineInfo, AirlineMaster, LinkResult, MapCtx, ReportOptions, UploadMeta,
)

_SPLIT = spec.split_config("tgq-hmpr")
_TICKET_NO = spec.ticket_no_config("tgq-hmpr")


def _source(**over) -> dict:
    d = {
        "sno": "1", "pcc": "ABC1", "airline": "AI", "ticket_date": "23APR26",
        "ticket_no": "098 5805708071", "air_name": "AIR INDIA", "air_pnr": "ABC123",
        "gal_pnr": "XYZ789", "pax_name": "CHAUHAN/NITIN MR", "booking_signon": "ZZ9",
        "ticketing_signon": "AB1", "document_type": "TKT", "fare_basis": "LOWIN",
        "base_fare": "10000", "basefarecurrency": "INR", "yqtax": "500", "total_tax": "1800",
        "airlinefee": "0", "total_fare": "11800", "comm": "1", "comm_amount": "100",
        "fop": "CC", "fop_details": "VI4111111111111111", "cc_auth": "123456",
        "cc_doexpiry": "12/29", "tour_code": None, "value_code": "VC1", "net_remit": "11700",
        "transaction_type": "SALE", "exchanged_for": None, "invoice_no": "INV-1",
        "void_exchange_refund_date": None, "sectors": "BOM/DEL DEL/BOM",
        "flightno": "AI-101 AI-102", "traveldt": "28APR 05MAY", "class": "L U",
        "coupon_status": "OPEN OPEN", "total_refund_amount": "0", "roe": "83.5",
        "gstn": "27ABCDE1234F1Z5", "businessphonenumber": "+91 99999 00000",
        "businessemailaddress": "a@b.com", "entityaddressline1": "1 Road",
        "cliententityname": "ACME",
    }
    d.update(over)
    return d


_TAXES = [
    {"type": "K3", "amount": "500"}, {"type": "YQ", "amount": "500"},
    {"type": "YR", "amount": "300"}, {"type": "IN", "amount": "500"},
]


def ingest(source: dict, taxes=None, *, seq: int = 1, batch: str = "b1", start_id: int = 1) -> list:
    """One source line → its stored legs, exactly as statements._build_rows writes them."""
    taxes = list(taxes if taxes is not None else _TAXES)
    data, derived = sector_split.apply_ticket_no(source, _TICKET_NO)
    legs = []
    for i, (leg_data, leg_taxes, idx, count, status) in enumerate(sector_split.split_row(data, taxes, _SPLIT)):
        changed = count > 1 or derived
        legs.append(SimpleNamespace(
            id=start_id + i, batch_id=batch, source_file="hmpr.xlsx",
            uploaded_at=datetime(2026, 7, 2), data=leg_data, taxes=leg_taxes, row_seq=seq,
            sector_index=idx, sector_count=count, split_status=status, is_total=False,
            orig_data=source if changed else None, orig_taxes=taxes if count > 1 else None,
        ))
    return legs


def legacy(legs: list) -> list:
    """Legs of a batch split before orig_data/orig_taxes were written."""
    for leg in legs:
        leg.orig_data = None
        leg.orig_taxes = None
    return legs


def ctx(include_pii: bool = False, extra_keys=()) -> MapCtx:
    return MapCtx(
        upload=UploadMeta("tgq-hmpr", "b1", "hmpr.xlsx", datetime(2026, 7, 2)),
        options=ReportOptions(include_pii=include_pii),
        airlines=AirlineMaster(by_numeric={"098": AirlineInfo("AI", "098", "Air India")}),
        extra_keys=tuple(extra_keys),
    )


def common(legs, link=None, c=None) -> dict:
    fold = tgq.fold_tgq_ticket(legs)
    return tgq.to_common("tgq-hmpr", fold, c or ctx(), link)


class FoldMoneyTests(unittest.TestCase):

    def test_orig_data_wins_over_the_legs(self):
        legs = ingest(_source())
        self.assertEqual(len(legs), 2)
        for leg in legs:                   # corrupt the allocation: orig_data must still win
            leg.data = {**leg.data, "base_fare": "1"}
        fold = tgq.fold_tgq_ticket(legs)
        self.assertEqual(tgq.fold_money(fold, "base_fare"), Decimal("10000"))
        self.assertEqual(tgq.fold_taxes(fold), {"K3": Decimal("500"), "YQ": Decimal("500"),
                                                "YR": Decimal("300"), "IN": Decimal("500")})
        self.assertEqual(fold.flags, [])

    def test_numeric_legs_are_summed_when_orig_data_is_missing(self):
        legs = legacy(ingest(_source(sectors="BOM/DEL DEL/MAA MAA/BOM", base_fare="6395",
                                     flightno="A B C", traveldt="28APR 29APR 30APR",
                                     **{"class": "L L U"}, coupon_status="OPEN")))
        self.assertEqual([leg.data["base_fare"] for leg in legs], ["2131.67", "2131.67", "2131.66"])
        fold = tgq.fold_tgq_ticket(legs)
        self.assertEqual(tgq.fold_money(fold, "base_fare"), Decimal("6395"))
        self.assertEqual(tgq.fold_taxes(fold)["K3"], Decimal("500"))
        self.assertNotIn("TGQ_MONEY_UNSPLIT", fold.flags)

    def test_non_numeric_cell_copied_to_three_legs_is_not_tripled(self):
        legs = legacy(ingest(_source(sectors="BOM/DEL DEL/MAA MAA/BOM", total_fare="₹11,800",
                                     flightno="A B C", traveldt="28APR 29APR 30APR")))
        self.assertEqual([leg.data["total_fare"] for leg in legs], ["₹11,800"] * 3)
        fold = tgq.fold_tgq_ticket(legs)
        self.assertEqual(tgq.fold_money(fold, "total_fare"), Decimal("11800"))
        self.assertIn("TGQ_MONEY_UNSPLIT", fold.flags)
        row = tgq.to_common("tgq-hmpr", fold, ctx())
        self.assertEqual(row["gross_amount"], Decimal("11800"))
        self.assertIn("TGQ_MONEY_UNSPLIT", row["data_flags"])

    def test_non_numeric_tax_copied_to_legs_is_not_multiplied(self):
        legs = legacy(ingest(_source(), taxes=[{"type": "K3", "amount": "₹500"}]))
        fold = tgq.fold_tgq_ticket(legs)
        self.assertEqual(tgq.fold_taxes(fold), {"K3": Decimal("500")})
        self.assertIn("TGQ_MONEY_UNSPLIT", fold.flags)

    def test_a_field_ingest_never_divides_is_not_summed(self):
        fold = tgq.fold_tgq_ticket(legacy(ingest(_source())))
        self.assertEqual(tgq.fold_money(fold, "roe"), Decimal("83.5"))

    def test_unreadable_amount_is_blank_and_flagged(self):
        fold = tgq.fold_tgq_ticket(ingest(_source(sectors="BOM/DEL", flightno="AI1", traveldt="28APR",
                                                  **{"class": "L"}, coupon_status="OPEN",
                                                  comm_amount="abc")))
        self.assertIsNone(tgq.fold_money(fold, "comm_amount"))
        self.assertIn("AMOUNT_UNPARSEABLE", fold.flags)


class CombinedRowTests(unittest.TestCase):

    def test_sale_ticket_maps_every_tgq_column(self):
        row = common(ingest(_source()))
        self.assertEqual(row["row_ref"], "tgq_hmpr:b1#1")
        self.assertEqual(row["category"], C.CAT_BSP)
        self.assertEqual(row["source_type"], "TGQ HMPR")
        self.assertEqual(row["settled_with"], "Not settled – GDS record")
        self.assertEqual(row["agent_signon"], "AB1")
        self.assertEqual((row["airline_numeric"], row["airline_code"], row["airline_name"]),
                         ("098", "AI", "AIR INDIA"))
        self.assertEqual(row["booking_party_gstin"], "27ABCDE1234F1Z5")
        self.assertEqual((row["product"], row["transaction_type"], row["source_txn_type"]),
                         ("Air", C.SALE, "SALE"))
        self.assertEqual(row["document_number"], "5805708071")
        self.assertEqual(row["ticket_number"], "0985805708071")
        self.assertEqual(row["status"], "OPEN")
        self.assertEqual((row["airline_pnr"], row["gds_ref"], row["invoice_ref"]), ("ABC123", "XYZ789", "INV-1"))
        self.assertEqual((row["passenger_name"], row["pax_count"]), ("CHAUHAN/NITIN MR", 1))
        self.assertEqual(row["issue_date"], date(2026, 4, 23))
        self.assertIsNone(row["booking_date"])
        self.assertEqual(row["travel_date"], date(2026, 4, 28))
        self.assertIn("TRAVEL_YEAR_INFERRED", row["data_flags"])
        self.assertEqual((row["sector"], row["flight_no"], row["booking_class"]),
                         ("BOM/DEL/BOM", "AI-101/AI-102", "L/U"))
        self.assertEqual((row["fare_basis"], row["tour_code"], row["currency"]), ("LOWIN", "VC1", "INR"))
        self.assertEqual(row["base_fare"], Decimal("10000"))
        self.assertEqual((row["yq"], row["yr"], row["k3"]), (Decimal("500"), Decimal("300"), Decimal("500")))
        self.assertEqual(row["total_taxes"], Decimal("1800"))
        self.assertEqual(row["other_taxes"], Decimal("500"))       # IN
        self.assertEqual(row["gross_amount"], Decimal("11800"))
        self.assertEqual(row["commission"], Decimal("100"))
        self.assertEqual(row["net_payable"], Decimal("11700"))
        self.assertEqual(row["counts_in_net"], C.NET_TGQ_NOT_IN_BSP)
        self.assertEqual(row["not_in_bsp"], "Yes")
        self.assertEqual(set(row), set(C.COMBINED_KEYS))
        for flag in row["data_flags"]:
            self.assertIn(flag, C.FLAG_LEGEND)

    def test_refund_uses_refund_amount_and_refund_date_and_is_negative(self):
        row = common(ingest(_source(transaction_type="REFUND", total_refund_amount="9000",
                                    void_exchange_refund_date="15MAY26")))
        self.assertEqual(row["transaction_type"], C.REFUND)
        self.assertEqual(row["issue_date"], date(2026, 5, 15))
        self.assertEqual(row["booking_date"], date(2026, 4, 23))
        self.assertEqual(row["gross_amount"], Decimal("-9000"))
        self.assertEqual(row["net_payable"], Decimal("-9000"))
        self.assertEqual(row["base_fare"], Decimal("-10000"))
        self.assertEqual(row["commission"], Decimal("-100"))
        self.assertEqual(row["total_taxes"], Decimal("-1800"))
        self.assertEqual(row["k3"], Decimal("-500"))

    def test_refund_without_a_readable_refund_date_keeps_the_ticket_date(self):
        row = common(ingest(_source(transaction_type="REFUND", total_refund_amount="9000")))
        self.assertEqual(row["issue_date"], date(2026, 4, 23))

    def test_airline_fee_lands_in_other_taxes_and_yq_falls_back_to_taxes(self):
        row = common(ingest(_source(airlinefee="150", yqtax=None)))
        self.assertEqual(row["yq"], Decimal("500"))                # taxes[YQ]
        self.assertEqual(row["k3"], Decimal("500"))
        self.assertEqual(row["yr"], Decimal("300"))
        self.assertEqual(row["other_taxes"], Decimal("650"))      # 1800 − 500 − 300 − 500 + 150

    def test_pre_split_batch_is_folded_on_the_fly(self):
        leg = SimpleNamespace(
            id=7, batch_id="old", source_file="old.xlsx", uploaded_at=None,
            data=_source(), taxes=list(_TAXES), row_seq=None, sector_index=None,
            sector_count=None, split_status=None, is_total=False, orig_data=None, orig_taxes=None,
        )
        fold = tgq.fold_tgq_ticket([leg])
        self.assertTrue(fold.pre_split)
        self.assertEqual(fold.code, "098")
        self.assertEqual(fold.flags, ["TGQ_PRE_SPLIT"])
        row = tgq.to_common("tgq-hmpr", fold, ctx())
        self.assertEqual(row["row_ref"], "tgq_hmpr:7")
        self.assertEqual(row["ticket_number"], "0985805708071")
        self.assertEqual((row["sector"], row["flight_no"], row["booking_class"], row["status"]),
                         ("BOM/DEL/BOM", "AI-101/AI-102", "L/U", "OPEN"))
        self.assertEqual(row["travel_date"], date(2026, 4, 28))
        self.assertEqual(row["base_fare"], Decimal("10000"))
        self.assertEqual(row["k3"], Decimal("500"))
        self.assertIn("TGQ_PRE_SPLIT", row["data_flags"])

    def test_total_line_folds_to_none(self):
        total = _source(sno="Total", ticket_no=None, pax_name=None, sectors=None)
        stored = SimpleNamespace(id=9, batch_id="b1", row_seq=9, sector_index=1, sector_count=1,
                                 split_status="total", is_total=True, data=total, taxes=[],
                                 orig_data=None, orig_taxes=None)
        self.assertIsNone(tgq.fold_tgq_ticket([stored]))
        # a batch imported before is_total existed: recognised by content
        stored.is_total, stored.sector_count = False, None
        self.assertIsNone(tgq.fold_tgq_ticket([stored]))
        self.assertIsNone(tgq.fold_tgq_ticket([]))

    def test_no_ticket_number_is_unmatchable(self):
        row = common(ingest(_source(ticket_no=None)))
        self.assertIn("TGQ_UNMATCHABLE", row["data_flags"])
        self.assertEqual(row["not_in_bsp"], "Unknown – no ticket no.")
        self.assertEqual(row["counts_in_net"], C.NET_TGQ_UNMATCHABLE)

    def test_link_is_applied_last(self):
        link = LinkResult(not_in_bsp="In another BSP upload (bsp.pdf)",
                          counts_in_net=C.NET_TGQ_OTHER_UPLOAD, flags=["ALSO_IN_NDC"])
        row = common(ingest(_source()), link=link)
        self.assertEqual(row["counts_in_net"], C.NET_TGQ_OTHER_UPLOAD)
        self.assertEqual(row["not_in_bsp"], "In another BSP upload (bsp.pdf)")
        self.assertIn("ALSO_IN_NDC", row["data_flags"])

    def test_conjunction_ticket_shows_its_first_document(self):
        row = common(ingest(_source(ticket_no="618 5800920932-933", airline="SQ")))
        self.assertEqual(row["airline_numeric"], "618")
        self.assertEqual(row["document_number"], "5800920932-933")
        self.assertEqual(row["ticket_number"], "6185800920932")
        self.assertNotIn("TICKET_NO_NONSTANDARD", row["data_flags"])

    def test_canonical_types_and_emd_pax(self):
        self.assertEqual(tgq.tgq_canon({"transaction_type": "VOID"}), C.VOID)
        self.assertEqual(tgq.tgq_canon({"transaction_type": "EXCHANGE"}), C.EXCHANGE)
        self.assertEqual(tgq.tgq_canon({"transaction_type": "REISSUE"}), C.EXCHANGE)
        self.assertEqual(tgq.tgq_canon({"transaction_type": "SALE", "total_refund_amount": "12"}), C.REFUND)
        self.assertEqual(tgq.tgq_canon({"transaction_type": "SALE", "document_type": "EMD-S"}), C.EMD)
        self.assertEqual(tgq.tgq_canon({"transaction_type": "SALE", "total_refund_amount": "0"}), C.SALE)
        self.assertEqual(tgq.tgq_canon({}), C.UNKNOWN)
        row = common(ingest(_source(document_type="EMD")))
        self.assertEqual((row["transaction_type"], row["pax_count"]), (C.EMD, 0))

    def test_fare_currency_and_unreadable_date_flags(self):
        row = common(ingest(_source(basefarecurrency="USD", ticket_date="someday")))
        self.assertIn("FARE_CURRENCY_DIFFERS", row["data_flags"])
        self.assertIn("DATE_UNREADABLE", row["data_flags"])
        self.assertIsNone(row["issue_date"])
        self.assertEqual(row["currency"], "INR")

    def test_fop_is_never_fop_details(self):
        row = common(ingest(_source()))
        self.assertEqual(row["form_of_payment"], "CC")
        self.assertNotIn("VI4111111111111111", [str(v) for v in row.values()])

    def test_natural_key_is_document_and_type(self):
        fold = tgq.fold_tgq_ticket(ingest(_source()))
        self.assertEqual(tgq.tgq_natural_key(fold), (98 * 10**10 + 5805708071, C.SALE))
        self.assertIsNone(tgq.tgq_natural_key(tgq.fold_tgq_ticket(ingest(_source(ticket_no=None)))))

    def test_wrong_source_key_is_refused(self):
        with self.assertRaises(ValueError):
            tgq.to_common("ndc", tgq.fold_tgq_ticket(ingest(_source())), ctx())


class GroupingTests(unittest.TestCase):

    def test_group_carries_across_a_chunk_boundary(self):
        t1 = ingest(_source(sectors="BOM/DEL DEL/MAA MAA/BOM", flightno="A B C",
                            traveldt="28APR 29APR 30APR"), seq=1)
        t2 = ingest(_source(ticket_no="098 5805708072"), seq=2, start_id=10)
        chunks = [t1[:2], [t1[2], *t2]]

        grouper = tgq.TgqLegGrouper()
        self.assertEqual(grouper.feed(chunks[0]), [])              # still open
        closed = grouper.feed(chunks[1])
        self.assertEqual([[leg.id for leg in g] for g in closed], [[1, 2, 3]])
        self.assertEqual([leg.id for leg in grouper.flush()], [10, 11])
        self.assertIsNone(grouper.flush())

        groups = list(tgq.iter_folds(itertools.chain.from_iterable(chunks)))
        self.assertEqual([len(g) for g in groups], [3, 2])
        folds = [tgq.fold_tgq_ticket(g) for g in groups]
        self.assertEqual(tgq.fold_money(folds[0], "base_fare"), Decimal("10000"))
        self.assertEqual(folds[1].serial, "5805708072")

    def test_rows_without_row_seq_are_tickets_of_their_own(self):
        a = SimpleNamespace(id=1, batch_id="old", row_seq=None)
        b = SimpleNamespace(id=2, batch_id="old", row_seq=None)
        self.assertNotEqual(tgq.tgq_group_key(a), tgq.tgq_group_key(b))
        self.assertEqual(len(list(tgq.iter_folds([a, b]))), 2)


class DetailSheetTests(unittest.TestCase):

    def _headers(self, **kw):
        return [c.header for c in tgq.detail_columns("tgq-hmpr", ctx(**kw))]

    def test_card_fields_never_contact_fields_only_with_pii(self):
        plain, with_pii = self._headers(), self._headers(include_pii=True)
        for header in (plain, with_pii):
            for card in ("FOP_Details", "CC_Auth", "CC_DOExpiry"):
                self.assertNotIn(card, header)
            self.assertIn("FOP", header)
            self.assertIn("GSTN", header)
        for contact in ("BusinessPhoneNumber", "BusinessEmailAddress", "EntityAddressLine1"):
            self.assertNotIn(contact, plain)
            self.assertIn(contact, with_pii)

    def test_one_row_per_leg_with_leg_taxes_and_parsed_money(self):
        c = ctx(extra_keys=("custom_note", "fop_details"))
        cols = tgq.detail_columns("tgq-hmpr", c)
        headers = [col.header for col in cols]
        self.assertEqual(headers[:6], ["Row Ref", "Source File", "Upload ID", "Uploaded At (UTC)", "Ticket Ref", "Leg"])
        self.assertEqual(headers[-1], "data.custom_note")           # fop_details refused even as an extra key
        legs = ingest(_source(base_fare="10000", total_fare="abc"))
        leg2 = dict(zip(headers, base.detail_values(cols, legs[1], c)))
        self.assertEqual(leg2["Row Ref"], "tgq_hmpr:2")
        self.assertEqual(leg2["Ticket Ref"], "tgq_hmpr:b1#1")        # joins the Combined row_ref
        self.assertEqual(leg2["Leg"], "2/2")
        self.assertEqual(leg2["Base_Fare"], Decimal("5000"))
        self.assertEqual(leg2["Total_Fare"], "abc")
        self.assertEqual(leg2["Airline_Code"], "098")
        self.assertEqual(leg2["Sectors"], "DEL/BOM")
        self.assertEqual(leg2["Taxes"], "K3 250 · YQ 250 · YR 150 · IN 250")
        self.assertEqual(leg2["Source File"], "hmpr.xlsx")
        kinds = {col.header: col.kind for col in cols}
        self.assertEqual(kinds["Base_Fare"], "money")
        self.assertEqual(kinds["Pax_Name"], "text")


if __name__ == "__main__":
    unittest.main()
