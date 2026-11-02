"""Internal Statement's background upload — the parts of services/internal_import.py that decide
something without a database: what a staging row keeps beside its line, how an edit is checked,
which lines an "All vendors" save keeps, and the one column the internal ticket table holds
wider than the customer's.

The worker's read and save run against Postgres; they were exercised on a 1-lakh-line Yatra
sales report (read 45 s, save 85 s for 88,167 tickets) and are not repeated here.

No DB, no network.

Run:  python -m unittest tests.test_internal_import -v      (from backend/)
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: E402,F401 — every table, as the app sees them
from app.models.internal_ticket import InternalUploadedTicket  # noqa: E402
from app.models.uploaded_ticket import UploadedTicket  # noqa: E402
from app.services import internal_import as imp  # noqa: E402
from app.services import ticket_duplicates  # noqa: E402


class LineFacts(unittest.TestCase):
    def test_channel_is_gds_for_a_document_number(self):
        self.assertEqual(imp.channel("5808583279"), "GDS")
        self.assertEqual(imp.channel("098-7654321012"), "GDS")
        self.assertEqual(imp.channel("J6XK58"), "LCC")
        self.assertEqual(imp.channel(None), "LCC")

    def test_supplier_group_matches_the_page(self):
        self.assertEqual(imp.supplier_group({"supplier_name": " JETHI TRAVELS - 6E ", "ticket_number": "J6XK58"}),
                         "JETHI TRAVELS - 6E|LCC")
        self.assertEqual(imp.supplier_group({"ticket_number": "5808583279"}), "|GDS")

    def test_bad_date_is_a_value_not_read(self):
        self.assertFalse(imp.bad_date({"ticket_date": "2026-10-01", "departure_datetime": "2026-10-15 06:00"}))
        self.assertTrue(imp.bad_date({"ticket_date": "31/02/2026"}))
        self.assertTrue(imp.bad_date({"doc_date": "Oct-26"}))
        self.assertFalse(imp.bad_date({}))

    def test_facts(self):
        data = {"ticket_number": "5808583279", "pax_name": "SINGH/PRIYA", "ticket_date": "2026-10-01",
                "total_amt": 6000.0, "booking_class": "J K L M N O P Q R T U V W X Y Z"}
        f = imp.facts(data)
        self.assertEqual(f["dedup_key"], ticket_duplicates.ticket_key(data))
        self.assertEqual(f["supplier_group"], "|GDS")
        self.assertFalse(f["bad_date"])
        self.assertFalse(f["too_long"])
        self.assertIn("singh/priya", f["search_text"])
        self.assertIn("6000.0", f["search_text"])

    def test_clean_drops_empty_fields(self):
        out = imp.clean({"row_order": 3, "pax_name": "A", "sector": None, "total_amt": "120.5"})
        self.assertEqual(out["total_amt"], 120.5)
        self.assertNotIn("sector", out)

    def test_filled_fields(self):
        self.assertEqual(imp.filled_fields([{"a": "x", "b": ""}, {"c": 0, "d": None}]), ["a", "c"])


class TooLong(unittest.TestCase):
    def test_booking_class_is_wider_on_the_internal_table_only(self):
        self.assertEqual(InternalUploadedTicket.__table__.c.booking_class.type.length, 100)
        self.assertEqual(UploadedTicket.__table__.c.booking_class.type.length, 20)
        self.assertEqual(imp.LIMITS["booking_class"], 100)

    def test_a_value_longer_than_its_column_is_flagged(self):
        limit = imp.LIMITS["gds_pnr"]
        self.assertEqual(imp.too_long({"gds_pnr": "X" * (limit + 1), "pax_name": "A"}), ["gds_pnr"])
        self.assertEqual(imp.too_long({"gds_pnr": "X" * limit}), [])
        self.assertTrue(imp.facts({"gds_pnr": "X" * (limit + 1)})["too_long"])

    def test_message(self):
        self.assertIn("1 row has", imp.too_long_message(1))
        self.assertIn("1,250 rows have", imp.too_long_message(1250))


class Edits(unittest.TestCase):
    BASE = {"row_order": 1, "pax_name": "SINGH/PRIYA", "total_amt": 6000.0, "sector": "DEL/BOM"}

    def test_sets_and_clears(self):
        out = imp.edited(self.BASE, {"pax_name": "  KAUR/SIMRAN ", "sector": "", "total_amt": "6100.5"})
        self.assertEqual(out["pax_name"], "KAUR/SIMRAN")
        self.assertNotIn("sector", out)
        self.assertEqual(out["total_amt"], 6100.5)

    def test_a_value_that_is_not_one_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            imp.edited(self.BASE, {"total_amt": "1,250 abc"})
        self.assertIn("total_amt", str(caught.exception))

    def test_only_ticket_fields(self):
        with self.assertRaises(ValueError):
            imp.edited(self.BASE, {"raw_data": {"x": 1}})
        with self.assertRaises(ValueError):
            imp.edited(self.BASE, {"not_a_field": "x"})


class VendorPicks(unittest.TestCase):
    ROWS = [
        {"ticket_number": "J6XK58", "airlines_code": "6E"},
        {"ticket_number": "5808583279", "airlines_code": "ai"},
        {"ticket_number": "5808583280", "airlines_code": "ZZ"},
        {"ticket_number": "K9QQ11", "airlines_code": "6E"},
    ]
    GROUPS = ["JETHI|LCC", "IATA BSP|GDS", "IATA BSP|GDS", "UNPICKED|LCC"]

    def test_each_line_follows_its_supplier(self):
        kept, dropped = imp.apply_vendor_picks(
            self.ROWS, self.GROUPS, {"JETHI|LCC": "agency:43", "IATA BSP|GDS": "airline", "UNPICKED|LCC": ""},
            {"AI": 7, "6E": 9})
        self.assertEqual(dropped, 2)   # ZZ is not in the airline master; UNPICKED has no vendor
        self.assertEqual(kept[0], {**self.ROWS[0], "payable_type": "b2b", "payable_agency_id": 43})
        self.assertEqual(kept[1], {**self.ROWS[1], "payable_type": "airline", "payable_airline_id": 7})

    def test_a_malformed_pick_is_no_vendor(self):
        kept, dropped = imp.apply_vendor_picks(self.ROWS[:1], self.GROUPS[:1], {"JETHI|LCC": "agency:x"}, {})
        self.assertEqual((kept, dropped), ([], 1))


class CancellationColumns(unittest.TestCase):
    """Date of Cancellation and Net Cancellation Amount: found by Yatra's refund-report names,
    the date read in the Booking Date's declared format, and the line a refund."""

    def workbook(self, rows) -> bytes:
        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Date_Of_Booking", "ticket_no", "passenger_name", "Date_Of_Travel",
                   "bASe_fare", "tax", "bsp_amount", "date_of_cancellation", "NettRefundableAmount"])
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def extract(self, order):
        import asyncio
        from app.services.ticket_extraction import TicketExtractionService
        content = self.workbook([
            ["05/10/2026", "5808583279", "Mr Arjun Singh", "13/10/2026", 5033, -1351, 6384, "06/10/2026", 6384],
            ["05/10/2026", "5808583280", "Ms Priya Kaur", "13/10/2026", 5200, 1760, 6960, None, None],
        ])
        return asyncio.run(TicketExtractionService.extract(
            content, "refunds.xlsx", split_legs=False, keep_raw=False, internal_standard=True, fast_read=True,
            date_formats={"ticket_date": order, "departure_datetime": "DMY"}))

    def test_mapped_by_name_and_dated_like_the_booking_date(self):
        out = self.extract("DMY")
        self.assertEqual(out["suggested_mapping"]["cancellation_date"], "date_of_cancellation")
        self.assertEqual(out["suggested_mapping"]["net_cancellation_amount"], "NettRefundableAmount")
        refund, sale = out["rows"]
        self.assertEqual(refund["cancellation_date"], "2026-10-06")
        self.assertEqual(refund["net_cancellation_amount"], 6384.0)
        self.assertEqual(self.extract("MDY")["rows"][0]["cancellation_date"], "2026-06-10")
        self.assertEqual((ticket_duplicates.kind(refund), ticket_duplicates.kind(sale)), ("R", "S"))
        self.assertEqual(imp.clean(refund)["net_cancellation_amount"], 6384.0)


class JobView(unittest.TestCase):
    def test_queued_for_counts_while_waiting(self):
        job = SimpleNamespace(
            id="i", status="parsing", phase="queued", total_rows=0, processed_rows=0, error=None,
            file_name="f.xlsx", sheet_name="Sheet1", header_row=0, column_map={}, date_formats=None,
            batch_id=None, result=None, read_info={"columns": ["A"], "filled": ["pax_name"]},
            updated_at=datetime.utcnow() - timedelta(seconds=30))
        v = imp.view(job)
        self.assertGreaterEqual(v["queued_for"], 29)
        self.assertNotIn("columns", v["read"])
        self.assertEqual(v["read"]["filled"], ["pax_name"])
        job.phase = "reading"
        self.assertEqual(imp.view(job)["queued_for"], 0)


class ShortError(unittest.TestCase):
    def test_one_line(self):
        self.assertEqual(imp.short_error(ValueError("first line\nSQL: INSERT …")), "first line")


if __name__ == "__main__":
    unittest.main()
