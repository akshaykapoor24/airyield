"""Internal Statement's standard format — first read off Yatra's fortnightly B2B sales report.

The user's list (2026-10-28): which of the report's columns are loaded and where they land,
how the record is derived (names split, D / I, the route written one pair per segment,
Net Fare, Sales Channel from the ADT Ref), the columns skipped, and "All vendors" — one file
of every vendor's tickets, each row's vendor its own Payable To.
"""
import asyncio
import io
import unittest
from datetime import date, datetime
from types import SimpleNamespace

import openpyxl
from fastapi import HTTPException

from app.api.v1 import internal_tickets
from app.api.v1 import tickets as customer_tickets
from app.schemas.uploaded_ticket import ConfirmTicketUploadPayload, TicketRow
from app.services import sector_split, spreadsheet
from app.services import ticket_extraction as te

# Yatra's sales report header, exactly as ForNightlySalesReportB2B_20261016.xlsx prints it.
YATRA = [
    "booking_ref", "ADT_Ref", "booking_status", "document_no", "passenger_name", "date_generated",
    "Date_Of_Booking", "Date_Of_Travel", "origin", "destination", "Routing", "ticket_no", "airlinename",
    "airline", "Booking_Type", "Class", "Fare_Basis", "pnr_no", "Gross", "bASe_fare", "commission",
    "nett", "tax", "bsp_amount", "cost_net", "cost_tax", "cost_total", "yatra_cancellation_charge",
    "airline_cancellation_charge", "amount_recoverable", "Sales_Channel", "additional_fee",
    "Rebooking_Fee", "Our_Rebooking_fee", "Admin_fee", "Booking_fee", "Transaction_fee",
    "Corporate_name", "Branch_Name", "tkt_supplier_name", "iata_no", "trip_start_date", "flight_no",
    "CustomerCode", "VendorCode", "ticket_issue_date", "Meal Charges", "Baggage Charges",
    "seat block charges", "CreatedBy", "IATACommission", "PLB", "PaymentMode", "SegemntCount",
    "bookingClass",
]

LINE = {
    "booking_ref": "17733337", "ADT_Ref": "1510260082363", "booking_status": "TIX ISSUED",
    "document_no": "620617", "passenger_name": "Miss Afreen Fatima", "date_generated": "date_generated",
    "Date_Of_Booking": "15 Oct 2026", "Date_Of_Travel": "17 Oct 2026", "origin": "HYD",
    "destination": "SXR", "Routing": "HYD-DEL-DEL-SXR-", "ticket_no": "NIFNQE46E",
    "airlinename": "IndiGo", "airline": "6E", "Booking_Type": "D", "Class": "R", "Fare_Basis": None,
    "pnr_no": "NIFNQE", "Gross": "9388.00", "bASe_fare": "9388.00", "commission": "0.00",
    "nett": "9388.00", "tax": "2888.00", "bsp_amount": "12276.00", "cost_net": "9388.00",
    "cost_tax": "2888.00", "cost_total": "12276.00", "Sales_Channel": "ONLINE(Yatra-HO)",
    "additional_fee": "15.00", "Rebooking_Fee": "0.00", "Our_Rebooking_fee": "0.00",
    "Admin_fee": "0.00", "Booking_fee": "0.00", "Transaction_fee": "0.00",
    "Corporate_name": "Travclan Technology India Pvt Ltd",
    "Branch_Name": "Travclan Technology India Pvt Ltd", "tkt_supplier_name": "JETHI TRAVELS - 6E",
    "iata_no": "IGN5656A", "trip_start_date": "17 Oct 2026", "flight_no": "-706-5120",
    "CustomerCode": "C157938", "VendorCode": "V-100909", "ticket_issue_date": "Oct 15 2026 12:00AM",
    "CreatedBy": "Yatraonlinebooking", "IATACommission": "0.00", "PLB": "115.47",
    "SegemntCount": "2", "bookingClass": "ECONOMY",
}


def yatra_file(lines) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(YATRA)
    for ln in lines:
        ws.append([ln.get(h) for h in YATRA])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class StandardMappingTests(unittest.TestCase):
    def test_the_users_columns_map_and_the_rest_are_left_out(self):
        mapping = {canon: col for col, canon in te._build_col_map(YATRA).items()}
        self.assertEqual(mapping, {
            "booking_ref": "booking_ref", "adt_ref": "ADT_Ref", "booking_status": "booking_status",
            "doc_no": "document_no", "pax_name": "passenger_name", "ticket_date": "Date_Of_Booking",
            "departure_datetime": "Date_Of_Travel", "sector": "Routing", "ticket_number": "ticket_no",
            "airline_name": "airlinename", "airlines_code": "airline", "segment_type": "Booking_Type",
            "booking_class": "Class", "fare_basis": "Fare_Basis", "gds_pnr": "pnr_no",
            "sell_fare": "bASe_fare", "comm_sell": "commission", "net_fare": "nett", "sell_tax": "tax",
            "total_amt": "bsp_amount", "can_charge": "yatra_cancellation_charge",
            "supplier_can_charge": "airline_cancellation_charge", "sales_channel": "Sales_Channel",
            "serv_charge": "additional_fee", "reschedule_charge": "Rebooking_Fee",
            "customer_name": "Corporate_name", "supplier_name": "tkt_supplier_name", "iata_no": "iata_no",
            "flight_no": "flight_no", "customer_code": "CustomerCode", "vendor_code": "VendorCode",
            "meals": "Meal Charges", "excess_baggage": "Baggage Charges",
            "seat_selection": "seat block charges", "booked_by": "CreatedBy",
            "iata_comm_amt": "IATACommission", "plb_amount": "PLB", "payment_mode": "PaymentMode",
            "segment_count": "SegemntCount", "cabin_class": "bookingClass",
        })
        left = [h for h in YATRA if h not in mapping.values()]
        self.assertEqual(left, [
            "date_generated", "origin", "destination", "Gross", "cost_net", "cost_tax", "cost_total",
            "amount_recoverable", "Our_Rebooking_fee", "Admin_fee", "Booking_fee", "Transaction_fee",
            "Branch_Name", "trip_start_date", "ticket_issue_date",
        ])

    def test_booking_class_alone_is_still_the_rbd(self):
        self.assertEqual(te._build_col_map(["Ticket No", "BookingClass"])["BookingClass"], "booking_class")


class RowTests(unittest.TestCase):
    def test_a_name_without_a_slash_is_first_name_first(self):
        self.assertEqual(te._parse_pax_name("Mr Nisha Bothra"), ("Bothra", "Nisha"))
        self.assertEqual(te._parse_pax_name("MR VENKATA SURYANARAYANA RAJU GADHIRAJU"),
                         ("GADHIRAJU", "VENKATA SURYANARAYANA RAJU"))
        self.assertEqual(te._parse_pax_name("SAHOTA/VIKAS MR"), ("SAHOTA", "VIKAS"))
        self.assertEqual(te._parse_pax_name("INF DIYA MISS"), ("DIYA", None))

    def derive(self, **over):
        row = {"ticket_number": "NIFNQE46E", "sector": "HYD-DEL-DEL-SXR-", "segment_count": "2",
               "flight_no": "-706-5120", "segment_type": "D", "cabin_class": "ECONOMY", **over}
        return te.derive_ticket_row(row, is_airline=False)

    def test_the_route_is_read_one_pair_per_segment(self):
        r = self.derive()
        self.assertEqual(r["sector"], "HYD/DEL DEL/SXR")
        self.assertEqual(r["segment_count"], 2)
        self.assertEqual(r["flight_no"], "706 5120")
        # An open jaw: two segments, no BOM/PNQ leg nobody flew.
        self.assertEqual(self.derive(sector="DEL-BOM-PNQ-DEL-")["sector"], "DEL/BOM PNQ/DEL")

    def test_words_are_spelled_out(self):
        r = self.derive()
        self.assertEqual((r["segment_type"], r["cabin_class"]), ("Domestic", "Economy"))
        self.assertEqual(self.derive(segment_type="I", cabin_class="premium economy")["cabin_class"], "Premium Economy")
        self.assertEqual(self.derive(segment_type="I")["segment_type"], "International")

    def test_a_carrier_dash_flight_number_is_left_alone(self):
        self.assertEqual(self.derive(flight_no="6E-2134")["flight_no"], "6E-2134")

    def test_a_refund_status_marks_a_refund(self):
        self.assertEqual(self.derive(booking_status="REFUNDED")["invoice_type"], "Refund")
        self.assertNotIn("invoice_type", self.derive(booking_status="TIX ISSUED"))

    def test_net_fare_and_sales_channel(self):
        r = te.apply_internal_standard({"sell_fare": 1000.0, "comm_sell": 30.0, "adt_ref": None,
                                        "sales_channel": "ONLINE(Yatra-HO)"})
        # The user's rule decides when the file has an ADT Ref column: none here → Offline.
        self.assertEqual((r["net_fare"], r["sales_channel"]), (970.0, "Offline"))
        self.assertEqual(te.apply_internal_standard({"adt_ref": "1510260082363"})["sales_channel"], "Online")
        self.assertEqual(te.apply_internal_standard({"sales_channel": "OFFLINE(Yatra-QJU)"})["sales_channel"], "Offline")
        # A printed Net Fare is kept.
        self.assertEqual(te.apply_internal_standard({"sell_fare": 1000.0, "net_fare": 990.0})["net_fare"], 990.0)


class SectorTests(unittest.TestCase):
    def test_a_leg_from_an_airport_to_itself_is_never_flown(self):
        self.assertEqual(sector_split.leg_sectors("HYD-DEL-DEL-SXR-"), (["HYD/DEL", "DEL/SXR"], sector_split.SPLIT))
        self.assertEqual(sector_split.leg_sectors("IST-AUH-DEL- -"), (["IST/AUH", "AUH/DEL"], sector_split.SPLIT))
        self.assertEqual(sector_split.leg_sectors("DEL-DEL-"), ([], sector_split.UNPARSED))

    def test_segment_pairs_needs_two_airports_a_segment(self):
        self.assertEqual(sector_split.segment_pairs("IDR-BOM-", 1), ["IDR/BOM"])
        self.assertIsNone(sector_split.segment_pairs("IST-AUH-DEL-", 2))
        self.assertIsNone(sector_split.segment_pairs("IDR/BOM", 1))


class ExtractTests(unittest.TestCase):
    def extract(self, content, **kw):
        return asyncio.run(te.TicketExtractionService.extract(content, "ForNightlySalesReportB2B_20261016.xlsx", **kw))

    def test_the_first_read_sends_columns_only(self):
        res = self.extract(yatra_file([LINE, LINE]), include_rows=False)
        self.assertEqual((res["rows"], res["total_rows"]), ([], 2))
        self.assertEqual(res["suggested_mapping"]["plb_amount"], "PLB")

    def test_the_standard_read(self):
        content = yatra_file([LINE])
        mapping = self.extract(content, include_rows=False)["suggested_mapping"]
        row = self.extract(content, column_mapping=mapping, split_legs=False, keep_raw=False,
                           internal_standard=True,
                           date_formats={"ticket_date": "DMY", "departure_datetime": "DMY"})["rows"][0]
        # A sales report is not a BSP file because it has a Fare_Basis column.
        self.assertEqual(row["statement_type"], "B2B")
        self.assertNotIn("raw_data", row)
        self.assertEqual(
            {k: row.get(k) for k in ("ticket_date", "departure_datetime", "first_name", "last_name", "sector",
                                     "segment_type", "cabin_class", "net_fare", "total_amt", "sales_channel",
                                     "serv_charge", "plb_amount", "supplier_name", "vendor_code", "booked_by")},
            {"ticket_date": "2026-10-15", "departure_datetime": "2026-10-17", "first_name": "Afreen",
             "last_name": "Fatima", "sector": "HYD/DEL DEL/SXR", "segment_type": "Domestic",
             "cabin_class": "Economy", "net_fare": 9388.0, "total_amt": 12276.0, "sales_channel": "Online",
             "serv_charge": 15.0, "plb_amount": 115.47, "supplier_name": "JETHI TRAVELS - 6E",
             "vendor_code": "V-100909", "booked_by": "Yatraonlinebooking"})

    def test_customer_data_still_keeps_every_cell(self):
        content = yatra_file([LINE])
        mapping = self.extract(content, include_rows=False)["suggested_mapping"]
        row = self.extract(content, column_mapping=mapping)["rows"][0]
        self.assertEqual(row["raw_data"]["Gross"], "9388.00")


class ReaderTests(unittest.TestCase):
    def test_a_column_filled_to_the_bottom_does_not_make_the_sheet_that_long(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Ticket No", "Pax", "Note"])
        for i in range(20):
            ws.append([f"10000000{i:02d}", "A B", "x"])
        for _ in range(200):                      # Yatra's date_generated: one cell a row
            ws.append([None, None, "date_generated"])
        buf = io.BytesIO()
        wb.save(buf)
        real = spreadsheet._IMPLAUSIBLE_ROWS, spreadsheet._THIN_RUN
        spreadsheet._IMPLAUSIBLE_ROWS, spreadsheet._THIN_RUN = 100, 50
        try:
            grid = spreadsheet.read_grid(buf.getvalue(), "x.xlsx", None)[0]
        finally:
            spreadsheet._IMPLAUSIBLE_ROWS, spreadsheet._THIN_RUN = real
        self.assertEqual(len(grid), 21)


class AllVendorsTests(unittest.TestCase):
    def payload(self, rows, **over):
        base = dict(file_name="ForNightlySalesReportB2B_20261016.xlsx", rows=[TicketRow(**r) for r in rows],
                    agency="All vendors", valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 15),
                    date_formats={"ticket_date": "DMY", "departure_datetime": "DMY"}, multi_vendor=True)
        base.update(over)
        return ConfirmTicketUploadPayload(**base)

    def test_customer_data_refuses_an_all_vendors_statement(self):
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(customer_tickets.confirm_ticket_upload(
                self.payload([{"ticket_number": "1"}]), db=None, current_user=SimpleNamespace(id=1, tenant_id=1)))
        self.assertEqual(cm.exception.status_code, 422)

    def test_each_row_is_filed_under_its_own_vendor(self):
        impl = internal_tickets._impl

        async def airlines(*_a, **_k):
            return {}, {}

        async def payables(rows, *_a, **_k):
            return [dict(payable_type="b2b", payable_airline_id=None, payable_agency_id=r.payable_agency_id,
                         payable_to=f"Agency {r.payable_agency_id}") if r.payable_agency_id else {} for r in rows]

        real = impl._resolve_airlines, impl._resolve_payables
        impl._resolve_airlines, impl._resolve_payables = airlines, payables
        try:
            rows = [TicketRow(ticket_number="A1", payable_type="b2b", payable_agency_id=12,
                              supplier_name="JETHI TRAVELS - 6E", plb_amount=60.96, cabin_class="Economy"),
                    TicketRow(ticket_number="B2", supplier_name="IATA BSP")]
            built = asyncio.run(impl._build_uploaded_tickets(
                rows, None, batch_id="b", file_name="f", statement_type="B2B", tenant_id=1, created_by_id=1,
                now=datetime(2026, 10, 28), party=impl.CustomerParty("agency", name="All vendors", label="B2B"),
                multi_vendor=True))
        finally:
            impl._resolve_airlines, impl._resolve_payables = real
        self.assertEqual([(t.customer_type, t.customer_agency_id, t.payable_agency_id) for t in built],
                         [("agency", 12, 12), ("agency", None, None)])
        self.assertEqual((built[0].supplier_name, built[0].plb_amount, built[0].cabin_class),
                         ("JETHI TRAVELS - 6E", 60.96, "Economy"))
        self.assertIsNone(built[0].raw_data)

    def test_the_flags_are_internal_statements_only(self):
        self.assertEqual((customer_tickets.KEEP_RAW_DATA, customer_tickets.INTERNAL_STANDARD,
                          customer_tickets.MULTI_VENDOR), (True, False, False))
        impl = internal_tickets._impl
        self.assertEqual((impl.KEEP_RAW_DATA, impl.INTERNAL_STANDARD, impl.MULTI_VENDOR), (False, True, True))


if __name__ == "__main__":
    unittest.main()


# ── The column mapping remembered for the next file (services/saved_mapping.py) ──────────

from app.models.statement_column_mapping import StatementColumnMapping  # noqa: E402
from app.services import saved_mapping  # noqa: E402

USER = SimpleNamespace(id=14, tenant_id=1)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class MappingDB:
    """Just enough of an AsyncSession for saved_mapping: every select returns the rows kept
    so far (newest first), and add() keeps one."""
    def __init__(self):
        self.rows: list[StatementColumnMapping] = []

    async def execute(self, _stmt):
        return _Result(sorted(self.rows, key=lambda r: r.updated_at, reverse=True))

    def add(self, row):
        self.rows.append(row)

    def begin_nested(self):
        return _Nested()


def yatra_mapping():
    return {canon: col for col, canon in te._build_col_map(YATRA).items()}


class RememberedMappingTests(unittest.TestCase):
    def setUp(self):
        self.db = MappingDB()
        self.fields = customer_tickets.mapping_fields()
        self.by_name = yatra_mapping()

    def remember(self, who, columns=YATRA, column_map=None):
        return asyncio.run(saved_mapping.remember(
            self.db, USER, internal_tickets.MAPPING_SLUG, who, columns, column_map or self.by_name,
            self.fields, source_file="ForNightlySalesReportB2B_20261016.xlsx", batch_id="b1"))

    def propose(self, who, columns=YATRA):
        by_name = {c: col for col, c in te._build_col_map(columns).items()}
        return asyncio.run(saved_mapping.propose_for(
            self.db, USER, internal_tickets.MAPPING_SLUG, who, columns, self.fields, by_name))

    def test_whom_a_statement_was_for(self):
        P, mp = customer_tickets.CustomerParty, customer_tickets.mapping_party
        self.assertEqual(mp(P("agency", agency_id=12, name="Globe")).party_key, "agency:12")
        self.assertEqual(mp(P("corporate", corporate_id=5)).party_key, "corporate:5")
        self.assertEqual(mp(P("direct", customer_id=3)).party_key, "direct:3")
        self.assertEqual(mp(P("direct")).party_key, "direct")
        self.assertEqual(mp(None, multi_vendor=True).party_key, "all-vendors")
        self.assertEqual(mp(None, multi_vendor=True).name, "All vendors")
        self.assertIsNone(mp(P()).party_key)
        # Never an agency/supplier id: those key Third Party GDS's vendor mappings.
        self.assertEqual((mp(P("agency", agency_id=12)).agency_id, mp(P("agency", agency_id=12)).id), (None, None))

    def test_the_next_file_with_the_same_columns_opens_as_it_was_saved(self):
        all_vendors = customer_tickets.mapping_party(None, multi_vendor=True)
        # The user maps Payment Mode by hand to a column the names did not match, and leaves
        # Fare_Basis out on purpose.
        saved = {**{k: v for k, v in self.by_name.items() if k != "fare_basis"}, "narration": "Branch_Name"}
        row = self.remember(all_vendors, column_map=saved)
        self.assertEqual((row.party_key, row.vendor_name, row.slug), ("all-vendors", "All vendors", "internal-statement"))

        p = self.propose(all_vendors)
        self.assertEqual(p.match, saved_mapping.VENDOR)
        self.assertEqual(p.mapping, saved)
        self.assertNotIn("fare_basis", p.mapping)

    def test_columns_changed_since_keep_the_mapping_for_the_rest(self):
        all_vendors = customer_tickets.mapping_party(None, multi_vendor=True)
        self.remember(all_vendors, column_map={**self.by_name, "narration": "Branch_Name"})
        p = self.propose(all_vendors, columns=[c for c in YATRA if c != "PaymentMode"] + ["Remarks"])
        self.assertEqual(p.match, saved_mapping.VENDOR_CHANGED)
        self.assertEqual(p.mapping["narration"], "Branch_Name")
        self.assertNotIn("payment_mode", p.mapping)
        self.assertEqual((p.new_columns, p.gone_columns), (["Remarks"], ["PaymentMode"]))

    def test_another_customers_mapping_only_on_the_exact_columns(self):
        self.remember(customer_tickets.mapping_party(customer_tickets.CustomerParty("agency", agency_id=12, name="Globe")))
        other = customer_tickets.mapping_party(customer_tickets.CustomerParty("agency", agency_id=13))
        self.assertEqual(self.propose(other).match, saved_mapping.LAYOUT)
        self.assertIsNone(self.propose(other, columns=YATRA + ["Remarks"]).match)

    def test_saving_again_updates_the_one_mapping(self):
        all_vendors = customer_tickets.mapping_party(None, multi_vendor=True)
        self.remember(all_vendors)
        self.remember(all_vendors, column_map={**self.by_name, "narration": "Branch_Name"})
        self.assertEqual(len(self.db.rows), 1)
        self.assertEqual(self.db.rows[0].column_map["narration"], "Branch_Name")

    def test_a_vendor_keyed_mapping_is_unchanged(self):
        row = SimpleNamespace(agency_id=7, supplier_id=None, party_key=None)
        self.assertTrue(saved_mapping._same_vendor(row, 7, None))
        self.assertFalse(saved_mapping._same_vendor(row, None, None, "agency:7"))

    def test_confirm_remembers_only_where_it_is_switched_on(self):
        payload = ConfirmTicketUploadPayload(
            file_name="f.xlsx", rows=[TicketRow(ticket_number="1")], agency="All vendors",
            valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 15), multi_vendor=True,
            columns=YATRA, column_map=self.by_name)
        who = customer_tickets.mapping_party(None, multi_vendor=True)
        asyncio.run(customer_tickets._remember_mapping(self.db, USER, payload, who, "b1"))
        self.assertEqual(self.db.rows, [])                       # Customer data: off
        asyncio.run(internal_tickets._impl._remember_mapping(self.db, USER, payload, who, "b1"))
        self.assertEqual(len(self.db.rows), 1)
        # No columns sent (a punched ticket, an older page): nothing to remember.
        bare = payload.model_copy(update={"columns": None})
        self.db.rows.clear()
        asyncio.run(internal_tickets._impl._remember_mapping(self.db, USER, bare, who, "b1"))
        self.assertEqual(self.db.rows, [])


# ── Statement Type and the period from the booking dates (2026-10-29) ──────────────────────

class _SaveDB:
    """Just enough of an AsyncSession for confirm with the duplicate check off: what is added."""
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


class StatementTypeAndPeriodTests(unittest.TestCase):
    """The upload asks Booking / MO or Accounting and no Valid From / To: the statement is filed
    under the first and last Booking Date of its tickets, and named after them."""

    ROWS = [dict(ticket_number="1", ticket_date="2026-10-03"),
            dict(ticket_number="2", doc_date="2026-09-30"),            # no Booking Date: its Doc Date
            dict(ticket_number="3", ticket_date="2026-10-15T00:00:00"),
            dict(ticket_number="4", ticket_date="not a date")]

    def confirm(self, rows=ROWS, **over):
        impl = internal_tickets._impl

        async def build(*_a, **_k):
            return []

        db = _SaveDB()
        real = impl._build_uploaded_tickets, impl.DUPLICATE_CHECK
        impl._build_uploaded_tickets, impl.DUPLICATE_CHECK = build, False
        try:
            base = dict(file_name="ForNightlySalesReportB2B_20261016.xlsx", rows=[TicketRow(**r) for r in rows],
                        agency="All vendors", multi_vendor=True, statement_category="booking",
                        date_formats={"ticket_date": "DMY", "departure_datetime": "DMY"})
            base.update(over)
            asyncio.run(impl.confirm_ticket_upload(ConfirmTicketUploadPayload(**base), db=db, current_user=USER))
        finally:
            impl._build_uploaded_tickets, impl.DUPLICATE_CHECK = real
        return db.added[0]

    def test_no_period_sent_is_the_booking_dates(self):
        stmt = self.confirm()
        self.assertEqual((stmt.valid_from, stmt.valid_to), (date(2026, 9, 30), date(2026, 10, 15)))
        self.assertEqual(stmt.statement_category, "booking")
        self.assertEqual(stmt.statement_name, "B2B - All vendors - Booking/MO - 2026-09-30")

    def test_an_accounting_statement_with_its_own_period_and_name(self):
        stmt = self.confirm(statement_category="accounting",
                            valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 31))
        self.assertEqual((stmt.valid_from, stmt.valid_to), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(stmt.statement_name, "B2B - All vendors - Accounting - 2026-10-01")
        named = self.confirm(statement_name="  Yatra Oct accounts  ")
        self.assertEqual(named.statement_name, "Yatra Oct accounts")

    def test_no_dated_ticket_is_filed_under_the_upload_day(self):
        stmt = self.confirm(rows=[dict(ticket_number="1")])
        self.assertEqual(stmt.valid_from, stmt.valid_to)
        self.assertEqual(stmt.valid_from, datetime.utcnow().date())

    def test_an_unknown_statement_type_is_refused(self):
        with self.assertRaises(HTTPException) as cm:
            self.confirm(statement_category="sales")
        self.assertEqual(cm.exception.status_code, 422)

    def test_customer_data_sends_no_statement_type(self):
        self.assertIsNone(ConfirmTicketUploadPayload(file_name="f", rows=[], agency="x").statement_category)
