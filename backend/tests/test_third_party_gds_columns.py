"""Third Party GDS lines are stored a column per field, with no JSONB — no DB, no network.

`third_party_gds` keeps every field of the statement in its own typed column and `data` is
rebuilt over them (models/typed_statement.py), so the fifteen readers written against
`data["net_amount"]` are unchanged. These pin that every template column has a home, that
a line survives the trip into the columns and back as the same strings, what happens to a
value that does not fit, that the SQL form needs no bind parameters, and that the migration
builds the columns the model declares.

Run:  python -m unittest discover backend/tests
"""
import importlib.util
import os
import sys
import unittest
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: E402,F401
from sqlalchemy import Date, Integer, Numeric, select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api.v1 import statements as router  # noqa: E402
from app.models.statement_row import STATEMENT_MODELS, ThirdPartyGds  # noqa: E402
from app.models.typed_statement import UNPARSED_KEY, is_typed, sql_relation  # noqa: E402
from app.services import flat_statement  # noqa: E402
from app.services.report_download import queries as rd_queries  # noqa: E402
from app.services.report_download.registry import get_source  # noqa: E402

G = ThirdPartyGds
MIGRATION = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions",
                         "tp_gds_columns_01_typed_columns.py")
# The columns added since, by migrations that ADD to the table rather than build it.
ADDED_BY = [os.path.join(os.path.dirname(__file__), "..", "alembic", "versions", f)
            for f in ("tp_gds_std_01_tax_parts.py", "tp_gds_std_02_ssr_gst_parts.py",
                      "tp_gds_std_03_refund.py")]

# The standard columns the user set (2026-10-25), as the mapping screen names them, and the
# real export's own spelling of the ones it prints differently.
STATEMENT_HEADERS = [
    "Week", "Booked / Issue Date", "Transaction Date", "Travel Date", "Airline Name",
    "Airline Code", "Ticket Prefix", "Segment Type", "S PNR", "Airline PNR", "CRS PNR",
    "Ticket No", "Invoice Type", "Invoice No", "Pax First Name", "Pax Last Name", "Pax Count",
    "Sector", "Flight No", "Class", "Payment Mode", "Card Type", "Basic Fare", "YQ Tax",
    "YR Tax", "K3 Tax", "Other Taxes", "Total Tax", "Seat Selection", "Excess Baggage", "Meals",
    "Total Fare", "Reschedule Charges", "Cancellation Charges", "Refund", "ADM",
    "Agent Commission", "Incentive", "Discount", "Comm %", "Service Charge", "SF", "CGST",
    "SGST", "IGST", "TDS Amount", "Markup", "Agent Penalty", "UATP Amount",
    "Net Amount", "Payment Status", "Remarks",
]
REAL_EXPORT_SPELLINGS = ["Booked Date", "Date of Travel", "Airline Category", "TicketPrefix",
                         "Status", "First Name", "Last Name", "YQ Fare", "Cancellation Markup",
                         # Brightsun, Riya and Akbar, October 2026
                         "Seat_Selection", "Excessbagage", "CGST_Sell", "SGST_Sell", "IGST_Sell",
                         "DIS_Sell", "PaidByCreditCard", "UATP Amt.", "Disc. Amt.", "CardAmt",
                         "RFD_SELL"]

# One full line of the real export, as the parser hands it over.
LINE = {
    "week": "01-07TH AUG 26", "booking_date": "2026-08-01", "issue_date": "2026-08-01",
    "issue_date_source": "booked_date", "travel_date": "2026-09-14",
    "customer_name": "TRIUMPHH TRAVEL N MORE PRIVATE LIMITED", "customer_id": "2102611",
    "airline_name": "TURKISH AIRLINES", "airline_code": "TK", "ticket_prefix": "235",
    "segment_type": "INTERNATIONAL", "pnr": "7AYL3S", "airline_pnr": "URL6KI",
    "ticket_number": "5809056126", "ticket_status": "CONFIRMED", "pax_type": "ADT",
    "first_name": "SINGH/VANSHDEEP", "passenger_name": "SINGH/VANSHDEEP", "passenger_count": "1",
    "sector": "DEL-IST / IST-DEL", "flight_number": "717", "base_fare": "95927",
    "yq": "7657", "other_taxes": "-10444", "ssr_amount": "0", "total_fare": "99090.00",
    "total_fare_source": "derived", "commission_amount": "999.57", "tds": "8.363999999999999",
    "service_fee": "500", "gst_on_sf": "90", "net_amount": "-104166.9572",
    "airline_id": "98", "airline_master_name": "TURKISH AIRLINES",
}


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


class SchemaTests(unittest.TestCase):
    def test_every_statement_column_has_a_typed_column(self):
        builder = flat_statement.get("tp-gds")
        fields = builder.build_col_map(STATEMENT_HEADERS)
        self.assertEqual(len(fields), len(STATEMENT_HEADERS), "a header no longer parses")
        for spelling in REAL_EXPORT_SPELLINGS:
            self.assertIn(spelling, builder.build_col_map([spelling]), spelling)
        keys = {f.key for f in G.data_fields()}
        for header, field in fields.items():
            with self.subTest(header=header):
                self.assertIn(field, keys)

    def test_every_template_field_has_a_column(self):
        keys = {f.key for f in G.data_fields()}
        for c in flat_statement.TP_GDS_DISPLAY:
            with self.subTest(field=c["field"]):
                self.assertIn(c["field"], keys)

    def test_no_json_is_stored(self):
        cols = {c.name: c for c in G.__table__.columns}
        for gone in ("data", "raw_data", "taxes", "segments", "ssr"):
            self.assertNotIn(gone, cols)
        self.assertFalse([c.name for c in cols.values() if type(c.type).__name__ in ("JSONB", "JSON")])

    def test_dates_amounts_and_counts_are_typed(self):
        c = G.__table__.c
        for name in ("booking_date", "transaction_date", "issue_date", "travel_date"):
            self.assertIsInstance(c[name].type, Date, name)
        for name in ("base_fare", "net_amount", "total_tax", "commission_rate", "tds"):
            self.assertIsInstance(c[name].type, Numeric, name)
        self.assertIsInstance(c["passenger_count"].type, Integer)

    def test_only_gds_is_typed(self):
        for slug, model in STATEMENT_MODELS.items():
            with self.subTest(slug=slug):
                self.assertEqual(is_typed(model), slug == "tp-gds")


class RoundTripTests(unittest.TestCase):
    def test_a_line_comes_back_as_the_same_strings(self):
        row = G(data=LINE)
        self.assertEqual(row.data, LINE)

    def test_values_land_typed(self):
        row = G(data=LINE)
        self.assertEqual(row.booking_date, date(2026, 8, 1))
        self.assertEqual(row.net_amount, Decimal("-104166.9572"))
        self.assertEqual(row.total_fare, Decimal("99090.00"))
        self.assertEqual(row.passenger_count, 1)
        self.assertEqual(row.airline_id, 98)

    def test_renamed_keys(self):
        row = G(data={"taxes": "1200", "__edited__": "pnr,sector"})
        self.assertEqual((row.total_tax, row.edited_fields), (Decimal("1200"), "pnr,sector"))
        self.assertEqual(row.data, {"taxes": "1200", "__edited__": "pnr,sector"})

    def test_parser_output_fits(self):
        """Everything the tp-gds parser can produce for a template line has a column."""
        builder = flat_statement.get("tp-gds")
        headers = [c["header"] for c in builder.display_columns]
        cells = {h: "1" for h in headers}
        cells.update({"Booked Date": "01-08-2026", "Date of Travel": "14/09/2026",
                      "Issue Date": "", "Total Fare": "", "First Name": "A", "Last Name": "B"})
        b = builder.build_row(cells, headers)
        row = G(data=b["data"])
        self.assertIsNone(row.unparsed_fields)
        self.assertEqual(row.data, b["data"])


class MisfitTests(unittest.TestCase):
    def test_text_in_an_amount_column_is_dropped_and_recorded(self):
        row = G(data={"net_amount": "-5000", "cancellation_markup": "LESS PAYMENT"})
        self.assertIsNone(row.cancellation_markup)
        self.assertEqual(row.unparsed_fields, "cancellation_markup")
        self.assertEqual(row.data, {"net_amount": "-5000", UNPARSED_KEY: "cancellation_markup"})

    def test_unreadable_date_is_dropped_and_recorded(self):
        row = G(data={"travel_date": "31/02/2026", "booking_date": "2026-02-30"})
        self.assertEqual((row.travel_date, row.booking_date), (None, None))
        self.assertEqual(row.unparsed_fields, "booking_date,travel_date")

    def test_a_fractional_pax_count_does_not_fit(self):
        self.assertEqual(G(data={"passenger_count": "1.5"}).unparsed_fields, "passenger_count")
        self.assertEqual(G(data={"passenger_count": "2.0"}).passenger_count, 2)

    def test_the_record_survives_a_round_trip_and_clears_on_correction(self):
        row = G(data={"cancellation_markup": "LESS PAYMENT", "pnr": "ABC123"})
        row.data = {**row.data, "pnr": "XYZ999"}           # an edit to another cell
        self.assertEqual(row.unparsed_fields, "cancellation_markup")
        row.data = {**row.data, "cancellation_markup": "125"}
        self.assertIsNone(row.unparsed_fields)
        self.assertEqual(row.cancellation_markup, Decimal("125"))

    def test_assignment_replaces_every_field(self):
        row = G(data=LINE)
        row.data = {"pnr": "ONLY"}
        self.assertEqual(row.data, {"pnr": "ONLY"})
        self.assertIsNone(row.net_amount)

    def test_a_field_with_no_column_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            G(data={"pnr": "X", "product_type": "HOTEL"})
        self.assertIn("product_type", str(cm.exception))


class SqlTests(unittest.TestCase):
    def test_data_reads_compile_without_bind_parameters_for_the_keys(self):
        compiled = select(G.data).compile(dialect=postgresql.dialect())
        self.assertEqual(compiled.params, {})
        self.assertIn("jsonb_strip_nulls", str(compiled))

    def test_every_field_is_in_the_sql_form(self):
        sql = _sql(select(G.data))
        for f in G.data_fields():
            with self.subTest(key=f.key):
                self.assertIn(f"'{f.key}', CAST(third_party_gds.{f.attr} AS TEXT)", sql)

    def test_a_key_lookup_still_works(self):
        sql = _sql(select(G.id).where(G.data["row_kind"].astext.is_(None)))
        self.assertIn("->>", sql)

    def test_relation_for_raw_sql(self):
        rel = sql_relation(G)
        self.assertTrue(rel.startswith("(SELECT ") and rel.endswith(")"))
        self.assertNotIn(":", rel)
        self.assertIn(" AS data", rel)
        for col in ("id", "tenant_id", "created_by_id", "batch_id", "uploaded_at", "source_format"):
            self.assertIn(f"third_party_gds.{col}", rel)
        self.assertEqual(sql_relation(STATEMENT_MODELS["tp-lcc"]), "third_party_lcc")


class WriterTests(unittest.TestCase):
    def test_upload_leaves_the_json_companions_off_a_typed_line(self):
        line = router._line(G, tenant_id=1, created_by_id=1, batch_id="b", data={"pnr": "X"},
                            taxes=[], segments=[], ssr=[], raw_data={"PNR": "X"},
                            source_format="third-party-gds-v2")
        self.assertEqual((line.pnr, line.source_format), ("X", "third-party-gds-v2"))

    def test_other_types_keep_them(self):
        m = STATEMENT_MODELS["tp-lcc"]
        line = router._line(m, data={"pnr": "X"}, taxes=[], segments=[], ssr=[], raw_data={"PNR": "X"})
        self.assertEqual(line.raw_data, {"PNR": "X"})


class ReportDownloadTests(unittest.TestCase):
    def test_streams_provenance_plus_rebuilt_data(self):
        cols = rd_queries._stream_columns(get_source("tp-gds"), None)
        names = [c.name for c in cols]
        self.assertIn("data", names)
        self.assertIn("batch_id", names)
        self.assertNotIn("net_amount", names)

    def test_explicit_data_column(self):
        cols = rd_queries._stream_columns(get_source("tp-gds"), ("id", "data", "source_format"))
        self.assertEqual([c.name for c in cols], ["id", "data", "source_format"])


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("tp_gds_columns_01", MIGRATION)
        cls.mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mig)
        cls.added = []
        for path in ADDED_BY:
            spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cls.added += mod._COLUMNS

    def test_columns_match_the_model(self):
        model = {f.attr: (f.key, f.kind) for f in G.data_fields()}
        migration = {c: (k, self.mig._kind(t)) for c, k, t in self.mig._COLUMNS + self.added}
        self.assertEqual(migration, model)

    def test_frozen_coercion_agrees_with_the_model(self):
        from app.models import typed_statement
        for value, kind in [("2026-08-01", "date"), ("31/02/2026", "date"), ("-104166.9572", "number"),
                            ("LESS PAYMENT", "number"), ("1", "int"), ("1.5", "int"), ("  ", "text"),
                            ("1,234.50", "number"), (None, "number")]:
            with self.subTest(value=value, kind=kind):
                self.assertEqual(self.mig._coerce(value, kind), typed_statement._coerce(value, kind))


if __name__ == "__main__":
    unittest.main()
