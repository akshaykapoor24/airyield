"""Importing an Indian consolidator's own ticket statement.

The file that drove this work is `GLOBE OUR 08 15 AUG 26.xls` — a weekly statement
from Globe All India Services. Reading it exposed four separate defects, three of
which were about money rather than about the file:

1. Its 23 headers auto-mapped 5. Everything else was silently dropped.
2. `Ticket No.` reads "607 5808583279" — the airline's IATA accounting code, then
   the document serial. `_classify_ticket` read the leading digit as a document-type
   marker, so every 6xx- and 8xx-plated carrier (607 Etihad, 618 Singapore) became
   an ADM or ACM **credit note**, and a credit note has its commission zeroed.
3. Its sector is a hyphen chain with fixed-width padding, "IST-AUH-DEL-   -". No
   grammar here understood it, so nothing split and every multi-leg ticket landed
   as one row.
4. Its last row is an unlabelled block of column sums. Imported as a ticket, it
   doubled every figure in the batch.

These are pure-function tests: no DB, no network, no file IO except the optional
real-file case.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import asyncio
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.tickets import _classify_ticket  # noqa: E402
from app.services import sector_split  # noqa: E402
from app.services.sector_split import SPLIT, SINGLE, UNPARSED, leg_sectors  # noqa: E402
from app.services.ticket_extraction import (  # noqa: E402
    NUMERIC_COLS, _PER_TICKET_RATES, _SPLIT_FIN_COLS, _build_col_map, _is_total_line,
    _leg_share, _normalize_date, _parse_pax_name, TicketExtractionService,
    derive_ticket_row, recognised_count,
)

GLOBE_HEADERS = [
    "Doc Date", "DocNo", "Ticket No.", "PNR No.", "Reference", "Narration",
    "Sector / Description", "Pax Name", "AL", "Travel Date", "Basic Fare",
    "YQ Tax", "YR Tax", "K3 Tax", "OC Tax", "Other Taxes", "%%%%", "Discount",
    "Serv. Chrgs", "RAF", "GST", "TDS", "BillAmount",
]


class TestColumnVocabulary(unittest.TestCase):
    """A consolidator's headers are not our template's and not a BSP export's."""

    def test_every_globe_header_finds_a_home(self):
        col_map = _build_col_map(GLOBE_HEADERS)
        missing = [h for h in GLOBE_HEADERS if h not in col_map]
        self.assertEqual(missing, [], f"unmapped: {missing}")

    def test_the_columns_that_decide_money_land_where_they_belong(self):
        col_map = _build_col_map(GLOBE_HEADERS)
        for header, canonical in {
            "Ticket No.": "ticket_number",
            "AL": "airlines_code",
            "Sector / Description": "sector",
            "Travel Date": "departure_datetime",
            "Basic Fare": "sell_fare",
            "YQ Tax": "sell_tax_yq",
            "YR Tax": "sale_yr",
            "K3 Tax": "sale_k3",
            "OC Tax": "oc_tax",
            "Other Taxes": "other_tax",
            "Serv. Chrgs": "serv_charge",
            "RAF": "raf",
            "GST": "gst_sell",
            "TDS": "tds_sell",
            "Discount": "dis_sell",
            "BillAmount": "total_amt",
            "%%%%": "comm_percent",
        }.items():
            self.assertEqual(col_map.get(header), canonical, header)

    def test_gst_is_not_confused_with_k3(self):
        # K3 is GST on the air fare; the "GST" column beside a service charge is the
        # tax on that charge. They land on different lines of a return.
        col_map = _build_col_map(["GST", "K3 Tax"])
        self.assertEqual(col_map["GST"], "gst_sell")
        self.assertEqual(col_map["K3 Tax"], "sale_k3")

    def test_a_service_charge_never_becomes_an_ancillary_incentive_base(self):
        # booking_fee_sell / can_charge are incentive bases. A consolidator's own
        # fee landing in one would change a payout, not just a column.
        col_map = _build_col_map(["Serv. Chrgs", "RAF"])
        self.assertEqual(col_map["Serv. Chrgs"], "serv_charge")
        self.assertEqual(col_map["RAF"], "raf")

    def test_a_percent_only_header_still_resolves(self):
        # "%%%%" normalises to the empty string, so it survives only through the
        # raw-lowercase half of the alias index.
        self.assertEqual(_build_col_map(["%%%%"]), {"%%%%": "comm_percent"})

    def test_a_header_that_normalises_to_nothing_matches_nothing(self):
        # ...and the empty key must not become a wildcard for every other one.
        self.assertEqual(_build_col_map(["###", "---", "..."]), {})

    def test_net_remit_belongs_to_net_remit_not_net_amt(self):
        # Both fields listed this alias. Whichever wins must be the field named
        # after it, or a column called Net_Remit silently lands in net_amt.
        self.assertEqual(_build_col_map(["Net_Remit"])["Net_Remit"], "net_remit")

    def test_fop_details_belongs_to_fop_details_not_cc(self):
        self.assertEqual(_build_col_map(["FOP_Details"])["FOP_Details"], "fop_details")

    def test_a_field_is_claimed_only_once(self):
        # Two columns normalising onto one field: the second must not overwrite the
        # first silently — the user resolves it on the mapping screen.
        col_map = _build_col_map(["Ticket No.", "Ticket Number"])
        self.assertEqual(list(col_map.values()).count("ticket_number"), 1)

    def test_recognised_count_scores_a_header_row_above_a_data_row(self):
        header = recognised_count(GLOBE_HEADERS)
        data = recognised_count(["2026-08-08", "IS26/ 1067", "607 5808583279", "HNVTK1"])
        self.assertGreater(header, 15)
        self.assertGreater(header, data)


class TestTicketNumberClassification(unittest.TestCase):
    """The bug that turned Etihad's tickets into credit notes."""

    def test_the_accounting_prefix_is_not_a_document_type_marker(self):
        # 607 is Etihad. Before the fix this returned ("ADM", "Credit Note").
        self.assertEqual(_classify_ticket("607 5808583279", None), (None, None))

    def test_and_not_once_the_number_is_joined_up_either(self):
        self.assertEqual(_classify_ticket("6075808583279", None), (None, None))

    def test_singapore_airlines_618_is_not_an_adm(self):
        self.assertEqual(_classify_ticket("618 5894667924", None), (None, None))

    def test_a_real_adm_serial_is_still_classified(self):
        # The rule itself is right — it just has to read the serial.
        self.assertEqual(_classify_ticket("6123456789", None), ("ADM", "Credit Note"))

    def test_a_real_acm_serial_is_still_classified(self):
        self.assertEqual(_classify_ticket("8123456789", None), ("ACM", "Credit Note"))

    def test_a_refund_application_is_still_classified(self):
        self.assertEqual(_classify_ticket("4001234567", None)[0], "RA")

    def test_an_already_credited_row_is_not_overridden(self):
        self.assertEqual(_classify_ticket("6123456789", "Credit Note"), ("ADM", None))

    def test_the_prefix_is_split_off_and_kept(self):
        self.assertEqual(sector_split.split_ticket_no("607 5808583279"), ("607", "5808583279"))

    def test_derive_joins_the_number_and_records_the_carrier_prefix(self):
        row = derive_ticket_row({"ticket_number": "607 5808583279"}, is_airline=False)
        self.assertEqual(row["ticket_number"], "6075808583279")
        self.assertEqual(row["ticket_prefix"], "607")
        # With no AL column, the accounting code is the only carrier evidence there is.
        self.assertEqual(row["airlines_code"], "607")

    def test_a_mapped_airline_column_is_never_overwritten_by_the_prefix(self):
        row = derive_ticket_row(
            {"ticket_number": "607 5808583279", "airlines_code": "EY"}, is_airline=False)
        self.assertEqual(row["airlines_code"], "EY")


class TestSectorGrammar(unittest.TestCase):
    """The hyphen chain, and the refusal to guess."""

    def test_a_three_airport_chain_becomes_two_legs(self):
        self.assertEqual(leg_sectors("IST-AUH-DEL-   -"), (["IST/AUH", "AUH/DEL"], SPLIT))

    def test_a_two_airport_chain_is_a_single_leg(self):
        self.assertEqual(leg_sectors("MAD-MLA-   -   -   "), (["MAD/MLA"], SINGLE))

    def test_the_existing_grammars_are_untouched(self):
        self.assertEqual(leg_sectors("CCU/BKK BKK/CCU"), (["CCU/BKK", "BKK/CCU"], SPLIT))
        self.assertEqual(leg_sectors("DEL/BOM/MAA"), (["DEL/BOM", "BOM/MAA"], SPLIT))

    def test_a_date_is_not_a_route(self):
        self.assertEqual(leg_sectors("08-08-2026"), ([], UNPARSED))

    def test_free_text_with_hyphens_is_not_a_route(self):
        self.assertEqual(leg_sectors("REFUND - MISC - ADJ"), ([], UNPARSED))

    def test_a_gap_in_the_middle_refuses_rather_than_guesses(self):
        # Which leg is missing? Unknowable — and dividing money across the wrong
        # number of legs is exactly what this module exists to prevent.
        self.assertEqual(leg_sectors("DEL-   -SKG"), ([], UNPARSED))

    def test_a_non_airport_token_refuses(self):
        self.assertEqual(leg_sectors("DEL-XXX9-SKG"), ([], UNPARSED))

    def test_derive_rewrites_the_sector_into_the_grammar_everything_else_speaks(self):
        row = derive_ticket_row({"sector": "IST-AUH-DEL-   -"}, is_airline=False)
        self.assertEqual(row["sector"], "IST/AUH AUH/DEL")

    def test_an_unparseable_sector_is_left_exactly_as_it_was(self):
        row = derive_ticket_row({"sector": "REFUND - MISC"}, is_airline=False)
        self.assertEqual(row["sector"], "REFUND - MISC")


class TestMoneySplitting(unittest.TestCase):
    """Leg rows must re-sum to the ticket they came from."""

    def test_every_amount_is_divided_and_every_rate_is_not(self):
        self.assertEqual(_SPLIT_FIN_COLS, NUMERIC_COLS - _PER_TICKET_RATES)
        for rate in ("comm_percent", "roe", "nuc"):
            self.assertNotIn(rate, _SPLIT_FIN_COLS, f"{rate} is a rate, not an amount")

    def test_the_columns_that_used_to_be_copied_whole_are_now_divided(self):
        # A two-leg ticket reported twice its own BillAmount before this.
        for col in ("total_amt", "dis_sell", "tds_sell", "other_tax"):
            self.assertIn(col, _SPLIT_FIN_COLS)

    def test_the_consolidator_amounts_are_divided_too(self):
        for col in ("oc_tax", "raf", "serv_charge", "gst_sell"):
            self.assertIn(col, _SPLIT_FIN_COLS)

    def test_an_uneven_amount_re_sums_exactly(self):
        # round(6395 / 3, 2) * 3 == 6395.01 — a paisa invented out of nothing.
        parts = [_leg_share(6395.0, 3, i) for i in range(3)]
        self.assertAlmostEqual(sum(parts), 6395.0, places=2)

    def test_a_refund_splits_without_losing_its_sign(self):
        parts = [_leg_share(-62995.0, 3, i) for i in range(3)]
        self.assertAlmostEqual(sum(parts), -62995.0, places=2)
        self.assertTrue(all(p < 0 for p in parts))


class TestTotalLines(unittest.TestCase):
    """A statement's own summary row is not a ticket."""

    def test_an_unlabelled_row_of_sums_is_recognised(self):
        # What the real file carries: no "Total" anywhere, just amounts with no
        # document attached to them.
        self.assertTrue(_is_total_line({"sell_fare": -142666.0, "total_amt": -78288.0}))

    def test_a_labelled_total_is_recognised_too(self):
        self.assertTrue(_is_total_line({"narration": "Total"}))

    def test_a_ticket_is_never_mistaken_for_one(self):
        self.assertFalse(_is_total_line({"ticket_number": "6075808583279", "sell_fare": 36045.0}))

    def test_a_row_identified_only_by_its_passenger_is_still_a_ticket(self):
        self.assertFalse(_is_total_line({"pax_name": "SAHOTA/VIKAS", "sell_fare": 100.0}))

    def test_a_row_identified_only_by_a_voucher_is_still_a_ticket(self):
        self.assertFalse(_is_total_line({"doc_no": "IS26/ 1067", "sell_fare": 100.0}))


class TestRowDerivations(unittest.TestCase):

    def test_a_courtesy_title_is_not_a_surname(self):
        # "MR. SAHOTA" would never match a customer search for SAHOTA.
        self.assertEqual(_parse_pax_name("MR. SAHOTA/VIKAS"), ("SAHOTA", "VIKAS"))
        self.assertEqual(_parse_pax_name("BAMBA/YUVRAJ MR"), ("BAMBA", "YUVRAJ"))
        self.assertEqual(_parse_pax_name("INF DIYA MISS"), ("DIYA", None))

    def test_a_name_that_is_only_a_title_is_left_alone(self):
        self.assertEqual(_parse_pax_name("MR")[0], "MR")

    def test_a_pax_name_column_is_split_on_a_b2b_statement_too(self):
        row = derive_ticket_row({"pax_name": "MR. SAHOTA/VIKAS"}, is_airline=False)
        self.assertEqual((row["last_name"], row["first_name"]), ("SAHOTA", "VIKAS"))

    def test_an_excel_datetime_keeps_its_day_and_month(self):
        # dateutil with dayfirst=True read "2026-08-11 00:00:00" as 8 November,
        # moving the ticket a quarter down the calendar and out of its contract.
        self.assertEqual(_normalize_date("2026-08-11 00:00:00"), "2026-08-11")

    def test_an_indian_date_is_still_read_day_first(self):
        self.assertEqual(_normalize_date("11/08/2026"), "2026-08-11")
        self.assertEqual(_normalize_date("11-Aug-26"), "2026-08-11")

    def test_a_wholly_negative_row_is_a_credit_note(self):
        row = derive_ticket_row(
            {"sell_fare": -62995.0, "total_amt": -64608.0}, is_airline=False)
        self.assertEqual(row["invoice_type"], "Credit Note")
        # A refund is not an ADM — that is a different document with a different cause.
        self.assertIsNone(row.get("adm_acm_ra"))

    def test_a_sale_is_not(self):
        row = derive_ticket_row({"sell_fare": 36045.0, "total_amt": 54978.0}, is_airline=False)
        self.assertIsNone(row.get("invoice_type"))

    def test_a_declared_invoice_type_always_wins(self):
        row = derive_ticket_row(
            {"sell_fare": -100.0, "invoice_type": "Refund"}, is_airline=False)
        self.assertEqual(row["invoice_type"], "Refund")


def _workbook(rows, sheets=("Sheet1",)) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheets[0]
    for r in rows:
        ws.append(list(r))
    for name in sheets[1:]:
        wb.create_sheet(name)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestEndToEndExtraction(unittest.TestCase):
    """The whole parse, over a workbook shaped exactly like the real statement."""

    HEADERS = GLOBE_HEADERS

    def _file(self) -> bytes:
        return _workbook([
            ["TICKET STATEMENT"],
            ["For The Period 8 August 2026 To 15 August 2026"],
            ["GLOBE ALL INDIA SERVICES LIMITED - (WEST BENGAL)", "INR"],
            self.HEADERS,
            # a two-leg sale: three airports, so it becomes one row per flown leg
            ["2026-08-08", "IS26/ 1067", "607 5808583279", "HNVTK1", "", "",
             "IST-AUH-DEL-   -", "MR. SAHOTA/VIKAS", "EY", "2026-08-11",
             "36045", "14741", "0", "0", "0", "4276", "0.57", "205.81", "100",
             "0", "18", "4.12", "54978"],
            # a refund
            ["2026-08-08", "IR26/ 358", "125 4847730951", "9WVN43", "", "",
             "BCN-MLA-   -", "SAHOTA/VIKAS", "BA", "2026-07-26",
             "-62995", "0", "0", "0", "0", "-2046", "0", "0", "0", "415", "18",
             "0", "-64608"],
            # the statement's own total line: amounts, no document
            ["", "", "", "", "", "", "", "", "", "",
             "-26950", "14741", "0", "0", "0", "2230", "0.57", "205.81", "100",
             "415", "36", "4.12", "-9630"],
        ], sheets=("Sheet1", "Sheet2", "Sheet3"))

    def setUp(self):
        self.result = asyncio.run(
            TicketExtractionService.extract(self._file(), "globe.xlsx"))

    def test_it_reads_under_the_preamble_and_picks_the_sheet_with_data(self):
        self.assertEqual(self.result["header_row"], 3)
        self.assertEqual(self.result["sheet_name"], "Sheet1")
        self.assertEqual(self.result["sheet_names"], ["Sheet1", "Sheet2", "Sheet3"])

    def test_it_maps_every_column(self):
        self.assertEqual(self.result["unmapped_columns"], [])
        self.assertEqual(len(self.result["suggested_mapping"]), len(self.HEADERS))

    def test_it_offers_the_statement_period_for_the_date_fields(self):
        self.assertEqual(self.result["detected_from"], "2026-08-08")
        self.assertEqual(self.result["detected_to"], "2026-08-15")

    def test_it_drops_the_total_line_and_says_so(self):
        # 2 documents, one of them two legs -> 3 rows. The total line is not one.
        self.assertEqual(self.result["total_rows"], 3)
        self.assertTrue(any("total" in w.lower() for w in self.result["warnings"]),
                        self.result["warnings"])

    def test_the_money_matches_the_statement_as_printed(self):
        rows = self.result["rows"]
        # -26950 is the file's own printed total for Basic Fare.
        self.assertAlmostEqual(sum(r.get("sell_fare") or 0 for r in rows), -26950.0, places=2)
        self.assertAlmostEqual(sum(r.get("total_amt") or 0 for r in rows), -9630.0, places=2)
        self.assertAlmostEqual(sum(r.get("raf") or 0 for r in rows), 415.0, places=2)
        self.assertAlmostEqual(sum(r.get("serv_charge") or 0 for r in rows), 100.0, places=2)

    def test_every_source_cell_survives_even_where_nothing_mapped_it(self):
        for row in self.result["rows"]:
            self.assertEqual(set(row["raw_data"]), set(self.HEADERS))

    def test_the_refund_is_a_credit_note_and_not_an_adm(self):
        refund = next(r for r in self.result["rows"] if (r.get("sell_fare") or 0) < 0)
        self.assertEqual(refund["invoice_type"], "Credit Note")
        self.assertIsNone(refund.get("adm_acm_ra"))

    def test_a_pinned_read_returns_exactly_the_same_columns(self):
        # This is what stops the second call — the one carrying the mapping — from
        # renaming every column and discarding it.
        again = asyncio.run(TicketExtractionService.extract(
            self._file(), "globe.xlsx",
            sheet_name=self.result["sheet_name"], header_row=self.result["header_row"]))
        self.assertEqual(again["xls_columns"], self.result["xls_columns"])


if __name__ == "__main__":
    unittest.main()
