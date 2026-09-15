"""What a Third Party API booking IS, read off TBO's narration — no DB, no network.

Every string below is a real NARRATION cell from a TBO statement, including its quirks: the
padded day in "Aug  2 2026", station names that sometimes carry a code in brackets and
sometimes are only the code, and a property name whose ampersand arrived double-escaped.
These descriptions are printed on invoices, so a quirk that leaks through is a customer-facing
typo.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import tp_api_itinerary as itin  # noqa: E402

TRAIN = {
    "product_type": "Train", "booking_class": "3A", "quota": "General",
    "reference_no": "8151629905", "pax_count": "1",
    "narration": ("Train Name-NZM RAJDHANI Train number- 22221 TravelDate-Aug  2 2026  "
                  "From-C SHIVAJI MAH T (CSMT) To-H NIZAMUDDIN (NZM)"),
}
TRAIN_CODES_ONLY = {
    "product_type": "Train", "booking_class": "SL", "reference_no": "TBOB9214474740577357",
    "narration": "Train Name-SHRAM SHKTI EXP Train number- 12451 TravelDate-Sep  1 2026  From-CNB To-NDLS",
}
HOTEL = {
    "product_type": "Hotel", "airline_property_name": "Hyatt Regency Pune &amp;amp; Residences",
    "destination": "Pune", "start_date": "2026-08-30", "end_date": "2026-08-31",
    "no_of_nights": "1", "no_of_rooms": "1", "hotel_star_rating": "5",
    "narration": ("Hyatt Regency Pune &amp;amp; Residences Address-Weikfield IT Park Nagar Road "
                  "Pune Maharashtra IN RoomName-Executive Apartment  1 Bedroom 1 King Bed "
                  "Checkin Date-Aug 30 2026 CheckOut Date-Aug 31 2026 City Reference-Pune"),
}
BUS = {
    "product_type": "Bus",
    "narration": "TicketNo- 9BS3V6YG SeatName-3L Source-Delhi Destination-Indore DateOfJourney-Aug 23 2026",
}
MMT_HOTEL = {
    "product_type": "Hotel", "airline_property_name": "Hotel Deviram Palace", "origin": "AGRA",
    "start_date": "2026-08-26", "end_date": "2026-08-27", "pax_count": "1",
}


class TestTrain(unittest.TestCase):
    def test_the_whole_itinerary_is_read_from_the_sentence(self):
        d = itin.describe(TRAIN, "train")
        self.assertEqual(d["train_name"], "NZM RAJDHANI")
        self.assertEqual(d["train_number"], "22221")
        self.assertEqual((d["from_station"], d["from_code"]), ("C SHIVAJI MAH T", "CSMT"))
        self.assertEqual((d["to_station"], d["to_code"]), ("H NIZAMUDDIN", "NZM"))
        self.assertEqual(d["journey_date"], "2026-08-02")      # the padded day
        self.assertEqual((d["class"], d["quota"]), ("3A", "General"))

    def test_the_summary_is_one_readable_line(self):
        self.assertEqual(itin.summary(TRAIN, "train"),
                         "22221 NZM RAJDHANI · CSMT → NZM · 3A · 02 Aug 2026")

    def test_a_bare_station_code_is_a_code(self):
        d = itin.describe(TRAIN_CODES_ONLY, "train")
        self.assertEqual((d["from_code"], d["to_code"]), ("CNB", "NDLS"))
        self.assertNotIn("from_station", d)

    def test_only_a_ten_digit_reference_is_a_pnr(self):
        """TBO's "TBOB…" reference is its own id for a berth IRCTC never confirmed."""
        self.assertEqual(itin.describe(TRAIN, "train")["pnr"], "8151629905")
        self.assertNotIn("pnr", itin.describe(TRAIN_CODES_ONLY, "train"))

    def test_a_mapped_column_beats_the_narration(self):
        """The AI pass or a mapped column already filled it — that is the better source."""
        d = itin.describe({**TRAIN, "train_name": "RAJDHANI EXPRESS", "origin_code": "BCT"}, "train")
        self.assertEqual((d["train_name"], d["from_code"]), ("RAJDHANI EXPRESS", "BCT"))

    def test_no_narration_is_not_an_error(self):
        d = itin.describe({"product_type": "Train", "booking_class": "CC"}, "train")
        self.assertEqual(d["title"], "Train")
        self.assertEqual(d["class"], "CC")


class TestHotel(unittest.TestCase):
    def test_the_double_escaped_ampersand_is_decoded(self):
        d = itin.describe(HOTEL, "hotel")
        self.assertEqual(d["property"], "Hyatt Regency Pune & Residences")
        self.assertNotIn("&amp;", d["summary"])

    def test_the_stay_is_read(self):
        d = itin.describe(HOTEL, "hotel")
        self.assertEqual((d["check_in"], d["check_out"], d["nights"], d["rooms"]),
                         ("2026-08-30", "2026-08-31", "1", "1"))
        self.assertEqual(d["room_name"], "Executive Apartment 1 Bedroom 1 King Bed")
        self.assertEqual(d["city"], "Pune")
        self.assertEqual(d["summary"],
                         "Hyatt Regency Pune & Residences · Pune · 30 Aug → 31 Aug 2026 · 1 night")

    def test_nights_are_counted_when_the_file_does_not_say(self):
        """MakeMyTrip has no nights column — only the two dates."""
        d = itin.describe(MMT_HOTEL, "hotel")
        self.assertEqual(d["nights"], "1")
        self.assertEqual(d["city"], "AGRA")

    def test_dates_come_from_the_narration_when_unmapped(self):
        d = itin.describe({k: v for k, v in HOTEL.items()
                           if k not in ("start_date", "end_date", "no_of_nights")}, "hotel")
        self.assertEqual((d["check_in"], d["check_out"], d["nights"]),
                         ("2026-08-30", "2026-08-31", "1"))


class TestBus(unittest.TestCase):
    def test_the_journey_is_read(self):
        d = itin.describe(BUS, "bus")
        self.assertEqual((d["ticket_no"], d["seat"], d["from"], d["to"], d["journey_date"]),
                         ("9BS3V6YG", "3L", "Delhi", "Indore", "2026-08-23"))
        self.assertEqual(d["summary"], "Delhi → Indore · Seat 3L · 23 Aug 2026")


class TestShape(unittest.TestCase):
    def test_no_category_is_no_description(self):
        self.assertIsNone(itin.describe(TRAIN, None))
        self.assertIsNone(itin.summary(TRAIN, None))

    def test_every_description_names_its_category(self):
        for data, cat, label in ((TRAIN, "train", "Train"), (HOTEL, "hotel", "Hotel"),
                                 (BUS, "bus", "Bus"), ({"product_type": "Car"}, "car", "Car")):
            with self.subTest(category=cat):
                d = itin.describe(data, cat)
                self.assertEqual((d["category"], d["label"]), (cat, label))
                self.assertIn("title", d)

    def test_unknown_values_are_omitted_not_null(self):
        d = itin.describe({"product_type": "Bus"}, "bus")
        self.assertNotIn(None, d.values())

    def test_travel_date_picks_the_start_of_the_service(self):
        self.assertEqual(itin.travel_date(itin.describe(HOTEL, "hotel")), "2026-08-30")
        self.assertEqual(itin.travel_date(itin.describe(TRAIN, "train")), "2026-08-02")
        self.assertIsNone(itin.travel_date(None))

    def test_an_unreadable_narration_date_is_dropped_not_guessed(self):
        self.assertIsNone(itin._narr_date("Aug 32 2026"))
        self.assertIsNone(itin._narr_date("2026-08-02"))


if __name__ == "__main__":
    unittest.main()
