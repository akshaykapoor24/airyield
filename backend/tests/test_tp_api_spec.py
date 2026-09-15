"""The Third Party API statement spec — an aggregator's multi-product booking export.

This is the first type on this router whose one table holds more than one PRODUCT (hotel,
flight, train, bus, car) and more than one VENDOR (MakeMyTrip, TBO), and both of those make
things silent that are loud elsewhere:

* Auto-mapping is the whole user experience. Ninety-three fields is not a form anyone fills
  in by hand, so a single mistyped alias is not a visible error — it is one dropdown the
  uploader has to notice is blank among ninety-two that are not.
* `spec_mapping.SpecMapper` resolves aliases with `setdefault`, so an alias claiming two
  fields does not raise: it quietly resolves to whichever came first in spec order, and the
  symptom is a right-looking number in the wrong column.
* Normalization runs on values that are already stored as strings. A date this does not
  understand is kept verbatim, which looks fine on screen and empties a monthly bucket.

So the cases below pin the two real header rows, the spec's internal cross-references, and
every value conversion, against exactly those failure modes.

No DB, no network — the spec and the mapper are pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import spec_mapping, tp_api_spec  # noqa: E402
from app.services import statement_spec as spec  # noqa: E402

SLUG = "tp-api"

# MakeMyTrip's booking export, exactly as it arrives — including its own misspelling of
# "Departure" in the country column.
MMT_HEADERS = [
    "Booking Id", "PNR", "Booking Platform", "Lob", "Booking Status", "Primary Traveller",
    "No of Pax", "Booking Date", "Booking Time", "Travel Date", "Trip Type", "Payment Mode",
    "Pending Amount", "Payment Due Date", "Total Paid Amount",
    "Total Wallet Amount(At the Time of Booking)", "PG Amount", "E-Coupon Amount",
    "Promo Cash Amount", "My Cash", "Plus Amount", "PG Charges", "Refund Amount",
    "Depature/Hotel Country", "Airline/Property Name", "Flight Number",
    "Departure/Hotel City", "Arrival City", "Check-In/Departure Date",
    "Check-In/Departure Time", "Check-Out/Arrival Date", "Check-Out/Arrival Time",
    "Booked By", "Booking Type", "TDS Deducted",
]

# TBO's statement, exactly as it arrives — shouty casing, trailing spaces on several cells,
# a leading space on others.
TBO_HEADERS = [
    "DATE", "INVOICE NUMBER", "PRODUCT TYPE", "CATEGORY", "PAX NAME", "RATEOFEXCHANGE",
    " Hotel Name", "Hotel Star Rating", "NARRATION", "REFERENCE NO.", "Confirmation No.",
    "TBO Confirmation No.", " SUPPLIER BILL NUMBER", "BASIC AMOUNT", "TAXES",
    "DISC PAID AMOUNT", "SERVICE CHARGES", "SERVICE TAX AMOUNT", "SGST Rate", "SGST Amt",
    "CGST Rate", "CGST Amt", "IGST Rate", "IGST Amt", " Total GST", "SWACHH BHARAT CESS",
    "KRISHI KALYAN CESS", "EDU. CESS(STX) AMOUNT", "TDS AMOUNT", "EDU. CESS(TDS) AMOUNT",
    "NET", "CANCELLATION FEE", "PaymentID", "PGCharges", "Convenience Fee",
    "Travel Insurance", "Booking Class", "Mobile Number", "AgentMarkup", "Quota",
    "ERS PGCharges", "ERS AgentServiceCharge", "ERS GSTInvoiceNumber", "Catering Charge",
    "PassportNo", "PassportIssueDate", "PassportExpDate", "CheckInDate", "CheckOutDate ",
    "DestinationCity ", "No of Nights", "Amendment Type", " INTL/ DOM",
    "Booking Confirmation Date", "No of Rooms", "Vehicle Type", "No of Vehicle", "PAN",
    "GuardianPAN", "OXITRXID", "TCS Rate", "TCS Amount", "TCSDeclarationType", "Created By",
    "BookingMode", "Agency Reference",
]

# The three columns that are READ but are deliberately not fields — they fold into
# `legacy_cess`. Everything else in either file must map.
FOLDED = {"SWACHH BHARAT CESS", "KRISHI KALYAN CESS", "EDU. CESS(STX) AMOUNT"}


class TestAutoMapping(unittest.TestCase):
    """Does a vendor's raw file map itself?

    93 fields is not a form anyone fills in by hand, so this is the test that stops a
    mistyped alias shipping. The failure message names the columns that did not map,
    because "expected 63, got 62" is not something anyone can act on.
    """

    def _unmapped(self, headers):
        m = spec_mapping.mapper_for(SLUG).build_col_map(headers)
        return [h for h in headers if h not in m]

    def test_the_makemytrip_export_maps_completely(self):
        self.assertEqual(self._unmapped(MMT_HEADERS), [])

    def test_the_tbo_statement_maps_completely_apart_from_the_folded_cesses(self):
        self.assertEqual(set(self._unmapped(TBO_HEADERS)), FOLDED)

    def test_our_own_template_maps_itself(self):
        """The product tells people that filling in the downloaded template is the surest
        way to have everything read correctly. That is only true if it round-trips."""
        headers = spec.template_headers(SLUG)
        self.assertEqual(self._unmapped(headers), [])
        m = spec_mapping.mapper_for(SLUG).build_col_map(headers)
        for col, field in m.items():
            self.assertEqual(field, tp_api_spec._norm(col))


class TestSpecIntegrity(unittest.TestCase):
    """The cross-references, all of which fail silently when wrong."""

    def test_no_alias_claims_two_fields(self):
        # Asserted at import too, but pinned here so the reason survives: SpecMapper uses
        # setdefault, so a collision is a wrong number rather than an error.
        tp_api_spec._assert_unique_aliases()

    def test_every_canonical_header_reads_back_as_its_own_field(self):
        tp_api_spec._assert_headers_round_trip()

    def test_every_referenced_field_exists(self):
        fields = set(spec.fields(SLUG))
        named = (
            [(f["field"], "FILTERS") for f in tp_api_spec.FILTERS]
            + [(f["field"], "SUMMARY") for f in tp_api_spec.SUMMARY]
            + [(f, "MONEY_FIELDS") for f in tp_api_spec.MONEY_FIELDS]
            + [(f, "AI_FILLABLE") for f in tp_api_spec.AI_FILLABLE]
            + [(f, "_RATE_FIELDS") for f in tp_api_spec._RATE_FIELDS]
            + [(f, "_COUNT_FIELDS") for f in tp_api_spec._COUNT_FIELDS]
            + [(f, "_DATE_FIELDS") for f in tp_api_spec._DATE_FIELDS]
            + [(f, g["label"]) for g in tp_api_spec.REQUIRED_GROUPS for f in g["fields"]]
            + [(f, g["label"]) for g in tp_api_spec.ADVISORY_GROUPS for f in g["fields"]]
        )
        for field, where in named:
            with self.subTest(field=field, where=where):
                self.assertIn(field, fields, f"{where} names a field that does not exist")

    def test_rates_and_counts_are_not_money(self):
        """A rate in SUMMARY would have the router SUM percentages; a count formatted as
        money would render "2 nights" as "2.00"."""
        money = spec.money_fields(SLUG)
        for field in (*tp_api_spec._RATE_FIELDS, *tp_api_spec._COUNT_FIELDS):
            with self.subTest(field=field):
                self.assertNotIn(field, money)

    def test_the_identity_columns_are_not_facet_filters(self):
        """/records/facets returns up to 200 distinct values for every `select` filter, so a
        passport or PAN facet would be a bulk PII disclosure by construction. They stay
        stored and visible — they are simply not a dropdown."""
        selects = {f["field"] for f in tp_api_spec.FILTERS if f["type"] == "select"}
        for field in ("pan", "guardian_pan", "passport_no", "mobile_number"):
            with self.subTest(field=field):
                self.assertNotIn(field, selects)

    def test_net_amount_and_total_paid_amount_are_separate_fields(self):
        """TBO's NET is an invoice payable; MMT's Total Paid Amount is a tender total that
        reads 0 on a pending row. Aliasing them together would make a SUM over a
        mixed-vendor file meaningless."""
        index = {tp_api_spec._norm(a): f
                 for f, names in tp_api_spec.ALIASES.items() for a in names}
        self.assertEqual(index["net"], "net_amount")
        self.assertEqual(index["total_paid_amount"], "total_paid_amount")

    def test_category_does_not_claim_product_type(self):
        """TBO ships both. Letting CATEGORY ("R") claim product_type would overwrite the
        real PRODUCT TYPE column on every line."""
        index = {tp_api_spec._norm(a): f
                 for f, names in tp_api_spec.ALIASES.items() for a in names}
        self.assertEqual(index["category"], "category")
        self.assertEqual(index["product_type"], "product_type")
        self.assertEqual(index["lob"], "product_type")


class TestRequiredGroups(unittest.TestCase):
    """What the confirm step refuses.

    The reason this type has its own rule at all: `flat_statement.REQUIRED_GROUPS` demands a
    ticket number or a PNR, and an MMT hotel line has neither.
    """

    def _satisfied(self, headers):
        colmap = spec_mapping.mapper_for(SLUG).suggest_mapping(headers)
        return [g for g in spec.required_groups(SLUG) if not any(colmap.get(f) for f in g["fields"])]

    def test_a_makemytrip_file_satisfies_them(self):
        self.assertEqual(self._satisfied(MMT_HEADERS), [])

    def test_a_tbo_file_satisfies_them(self):
        self.assertEqual(self._satisfied(TBO_HEADERS), [])

    def test_the_shared_flat_statement_rule_would_refuse_both_real_files(self):
        """Why this type carries its own rule — asserted so nobody 'simplifies' it back
        onto the shared one.

        Each vendor fails a DIFFERENT half, which is what makes the shared rule unfixable
        here rather than merely strict:

        * TBO has no PNR, ticket number or any other document reference the shared rule
          recognises — it identifies a line by invoice and confirmation number.
        * MMT has none of `base_fare` / `net_amount` / `total_fare`; its money columns are
          `Total Paid Amount` and `Pending Amount`, which are tender figures, not an
          invoice total.

        (MMT does carry a PNR COLUMN, so it passes the identifier half — but that column is
        empty on every hotel and train line, so passing says nothing about those rows. That
        is the second reason the shared rule is the wrong instrument: it is checked against
        the column map, not the values.)
        """
        from app.services import flat_statement
        mapper = spec_mapping.mapper_for(SLUG)
        identifier, amount = flat_statement.REQUIRED_GROUPS

        tbo = mapper.suggest_mapping(TBO_HEADERS)
        self.assertFalse(any(tbo.get(f) for f in identifier["fields"]),
                         "TBO would now pass the shared identifier rule")

        mmt = mapper.suggest_mapping(MMT_HEADERS)
        self.assertFalse(any(mmt.get(f) for f in amount["fields"]),
                         "MMT would now pass the shared amount rule")

    def test_this_types_own_rule_accepts_what_the_shared_one_refuses(self):
        self.assertEqual(self._satisfied(MMT_HEADERS), [])
        self.assertEqual(self._satisfied(TBO_HEADERS), [])

    def test_a_file_with_no_identifier_is_refused(self):
        colmap = spec_mapping.mapper_for(SLUG).suggest_mapping(["Base Fare", "Taxes"])
        missing = [g["label"] for g in spec.required_groups(SLUG)
                   if not any(colmap.get(f) for f in g["fields"])]
        self.assertEqual(missing, ["a booking identifier"])


class TestFormatDetection(unittest.TestCase):
    def test_each_vendor_is_recognised(self):
        self.assertEqual(tp_api_spec.detect_format(MMT_HEADERS), tp_api_spec.MMT)
        self.assertEqual(tp_api_spec.detect_format(TBO_HEADERS), tp_api_spec.TBO)

    def test_an_unknown_file_is_none_rather_than_a_guess(self):
        """A third aggregator's file still imports — it just carries no vendor label.
        Provenance that is sometimes invented is worse than provenance sometimes absent."""
        self.assertIsNone(tp_api_spec.detect_format(["Booking Ref", "Amount", "Date"]))
        self.assertIsNone(tp_api_spec.detect_format([]))

    def test_the_label_is_only_for_a_known_format(self):
        self.assertEqual(tp_api_spec.format_label(tp_api_spec.TBO), "TBO")
        self.assertIsNone(tp_api_spec.format_label(None))

    def test_the_vendor_is_mirrored_into_data_so_it_can_be_filtered(self):
        # The drill-in filter builds `data->>field`; it cannot reach the real column.
        data = {}
        tp_api_spec.stamp_vendor(data, tp_api_spec.MMT)
        self.assertEqual(data["vendor"], "MakeMyTrip")
        self.assertIn("vendor", {f["field"] for f in tp_api_spec.FILTERS})

    def test_an_unknown_format_stamps_nothing(self):
        data = {}
        tp_api_spec.stamp_vendor(data, None)
        self.assertEqual(data, {})


class TestLegacyCess(unittest.TestCase):
    """The three dead pre-GST cesses, folded — the same shape as ndc_spec's Other Taxes."""

    def test_the_three_cesses_are_added_together(self):
        self.assertEqual(
            tp_api_spec.derive({"swachh_bharat_cess": "1.50", "krishi_kalyan_cess": "1.55",
                                "edu_cess_stx_amount": "0.95"}),
            {"legacy_cess": "4.00"},
        )

    def test_a_line_without_them_derives_nothing(self):
        """An absent column and a genuine zero are different facts. Writing "0.00" for a
        file that never had these columns would invent a figure the vendor never sent."""
        self.assertEqual(tp_api_spec.derive({"basic_amount": "3260.40"}), {})

    def test_an_unreadable_cell_is_skipped_not_counted_as_zero(self):
        self.assertEqual(tp_api_spec.derive({"swachh_bharat_cess": "N/A",
                                             "krishi_kalyan_cess": "2.00"}),
                         {"legacy_cess": "2.00"})

    def test_thousands_separators_survive(self):
        self.assertEqual(tp_api_spec.derive({"swachh_bharat_cess": "1,234.50"}),
                         {"legacy_cess": "1234.50"})

    def test_legacy_cess_is_a_column_and_reads_as_money(self):
        self.assertIn("legacy_cess", spec.fields(SLUG))
        self.assertIn("legacy_cess", spec.money_fields(SLUG))


class TestNormalizeDates(unittest.TestCase):
    def test_tbos_yyyymmdd_is_read_correctly(self):
        """TBO's DATE is 20260801. Read month-first it is a different year entirely."""
        self.assertEqual(tp_api_spec.to_iso_date("20260801"), "2026-08-01")

    def test_a_numeric_cell_that_round_tripped_through_float_still_reads(self):
        """calamine and openpyxl can hand a date column back as a number, so the cleaned
        string is "20260801.0" — which dateutil rejects outright."""
        self.assertEqual(tp_api_spec.to_iso_date("20260801.0"), "2026-08-01")

    def test_an_indian_day_first_date_is_not_read_month_first(self):
        self.assertEqual(tp_api_spec.to_iso_date("13-08-2026"), "2026-08-13")

    def test_an_iso_date_is_left_alone(self):
        self.assertEqual(tp_api_spec.to_iso_date("2026-08-29"), "2026-08-29")

    def test_nonsense_is_none_rather_than_a_guess(self):
        self.assertIsNone(tp_api_spec.to_iso_date("not a date"))
        self.assertIsNone(tp_api_spec.to_iso_date(""))

    def test_an_unparseable_date_keeps_its_text_and_is_flagged(self):
        data = {"booking_date": "sometime in August"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["booking_date"], "sometime in August")
        self.assertEqual(data["date_parse_failed"], "booking_date")

    def test_a_good_row_carries_no_failure_flag(self):
        data = {"booking_date": "20260801"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["booking_date"], "2026-08-01")
        self.assertNotIn("date_parse_failed", data)


class TestNormalizeVocabularies(unittest.TestCase):
    def test_both_vendors_land_on_one_product_vocabulary(self):
        for raw, want in (("Hotel", "Hotel"), ("hotel", "Hotel"), ("HOTELS", "Hotel"),
                          ("Flight", "Flight"), ("air", "Flight"),
                          ("Train", "Train"), ("RAIL", "Train"),
                          ("Bus", "Bus"), ("cab", "Car")):
            with self.subTest(raw=raw):
                data = {"product_type": raw}
                tp_api_spec.normalize(data)
                self.assertEqual(data["product_type"], want)

    def test_an_unknown_product_passes_through_verbatim(self):
        """Not "Other": it then shows up in the Category facet, where a human notices a new
        product name. "Other" would bury it."""
        data = {"product_type": "Activity"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["product_type"], "Activity")

    def test_status_lands_on_one_vocabulary(self):
        for raw, want in (("Cancelled", "Cancelled"), ("Pending Payment", "Pending"),
                          ("Travelled", "Travelled"), ("booked", "Confirmed")):
            with self.subTest(raw=raw):
                data = {"booking_status": raw}
                tp_api_spec.normalize(data)
                self.assertEqual(data["booking_status"], want)

    def test_a_cancelled_amendment_infers_a_status_and_says_so(self):
        """TBO ships no status column. An inferred value a user cannot tell from a read one
        is how a reconciliation quietly goes wrong, so it is stamped."""
        data = {"amendment_type": "Cancellation"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["booking_status"], "Cancelled")
        self.assertEqual(data["booking_status_source"], "amendment_type")

    def test_a_real_status_is_never_overwritten_by_the_inference(self):
        data = {"booking_status": "Travelled", "amendment_type": "Cancellation"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["booking_status"], "Travelled")
        self.assertNotIn("booking_status_source", data)

    def test_the_pax_count_is_read_off_tbos_name_suffix(self):
        data = {"passenger_name": "lovekush singh X 1"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["pax_count"], "1")

    def test_a_real_pax_column_wins_over_the_suffix(self):
        data = {"passenger_name": "lovekush singh X 1", "pax_count": "3"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["pax_count"], "3")


class TestNormalizeAmounts(unittest.TestCase):
    """The router's `_num` only strips commas in SQL, so anything it cannot read SUMs as 0
    in the summary slab with nothing on screen to say so."""

    def test_indian_grouping_and_bracket_negatives(self):
        data = {"net_amount": "1,23,456.78", "refund_amount": "(285.72)",
                "base_fare": "₹1,234"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["net_amount"], "123456.78")
        self.assertEqual(data["refund_amount"], "-285.72")
        self.assertEqual(data["base_fare"], "1234")

    def test_rates_and_counts_are_normalised_too(self):
        data = {"sgst_rate": "2.5", "no_of_nights": "2"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["sgst_rate"], "2.5")
        self.assertEqual(data["no_of_nights"], "2")

    def test_an_unreadable_amount_keeps_its_text(self):
        data = {"net_amount": "see invoice"}
        tp_api_spec.normalize(data)
        self.assertEqual(data["net_amount"], "see invoice")

    def test_an_absent_field_is_not_invented(self):
        data = {"net_amount": "10"}
        tp_api_spec.normalize(data)
        self.assertNotIn("total_paid_amount", data)


class TestPrecedence(unittest.TestCase):
    """Derived < mapped < the reviewer's correction — and normalize runs over all three.

    This is the order `/confirm` applies, and it is what makes the review step's promise
    true: a cell corrected to "13-08-2026" is normalised exactly as the file's own value was.
    """

    def _confirm_like(self, row, columns, colmap, overrides=None):
        mapper = spec_mapping.mapper_for(SLUG)
        data = mapper.build_row_mapped(row, columns, colmap, overrides)["data"]
        extra = tp_api_spec.derive({tp_api_spec._norm(c): row.get(c) for c in columns})
        if extra:
            data = {**extra, **data}
        tp_api_spec.normalize(data)
        return data

    def test_a_file_carrying_its_own_legacy_cess_column_wins_over_the_derivation(self):
        row = {"Legacy Cess": "99.00", "SWACHH BHARAT CESS": "1.00"}
        data = self._confirm_like(row, list(row), {"legacy_cess": "Legacy Cess"})
        # "99.00", not "99": to_number_str strips separators and signs but keeps the
        # precision the vendor wrote, so a paise column stays a paise column.
        self.assertEqual(data["legacy_cess"], "99.00")

    def test_a_reviewers_correction_wins_over_the_file(self):
        row = {"NET": "100.00"}
        data = self._confirm_like(row, list(row), {"net_amount": "NET"},
                                  {"net_amount": "250.00"})
        self.assertEqual(data["net_amount"], "250.00")

    def test_a_reviewers_correction_is_still_normalised(self):
        row = {"DATE": "20260801", "NET": "1"}
        data = self._confirm_like(
            row, list(row), {"transaction_date": "DATE", "net_amount": "NET"},
            {"transaction_date": "13-08-2026", "net_amount": "1,23,456.78"},
        )
        self.assertEqual(data["transaction_date"], "2026-08-13")
        self.assertEqual(data["net_amount"], "123456.78")

    def test_a_real_tbo_train_line_lands_the_way_it_should(self):
        row = dict(zip(TBO_HEADERS, [
            "20260801", "SM/2627/566301", "Train", "R", "lovekush singh X 1", "1",
            "", "", "Train Name-NZM RAJDHANI Train number- 22221", "8151629905", "", "0",
            "", "3260.4", "0", "0", "14.74", "2.21", "0", "0", "0", "0", "18", "3.05",
            "3.05", "0", "0", "0", "0", "0", "3280", "0", "", "0", "35.4", "0", "3A",
            "9990447555", "0", "General", "32.6", "40", "PS26815162990511", "400",
            "", "", "", "", "", "", "0", "", "None", "", "0", "", "0", "", "", "0", "0",
            "NotSet", "", "", "",
        ]))
        colmap = spec_mapping.mapper_for(SLUG).suggest_mapping(TBO_HEADERS)
        data = self._confirm_like(row, TBO_HEADERS, colmap)
        self.assertEqual(data["product_type"], "Train")
        self.assertEqual(data["transaction_date"], "2026-08-01")
        self.assertEqual(data["invoice_number"], "SM/2627/566301")
        self.assertEqual(data["net_amount"], "3280")
        self.assertEqual(data["base_fare"], "3260.4")
        self.assertEqual(data["pax_count"], "1")
        self.assertEqual(data["booking_class"], "3A")
        self.assertEqual(data["quota"], "General")
        # The three cesses were 0.00 on this line but PRESENT, so the fold ran.
        self.assertEqual(data["legacy_cess"], "0.00")
        # And the narration is stored as text, waiting for the AI pass.
        self.assertIn("Train Name-NZM RAJDHANI", data["narration"])

    def test_a_real_makemytrip_hotel_line_lands_the_way_it_should(self):
        row = dict(zip(MMT_HEADERS, [
            "NH23065512619254", "", "desktop", "Hotel", "Cancelled", "RAJEEV JETLY", "1",
            "2026-08-29", "01:34", "2026-09-20", "", "DUMMY", "0", "2026-09-17 23:59:00",
            "0", "0", "0", "0", "0", "0", "0", "0", "0", "India", "Taj Santacruz, Mumbai",
            "", "MUMBAI", "", "2026-09-20", "00:00", "2026-09-24", "00:00", "Naveen Gupta",
            "", "0",
        ]))
        colmap = spec_mapping.mapper_for(SLUG).suggest_mapping(MMT_HEADERS)
        data = self._confirm_like(row, MMT_HEADERS, colmap)
        self.assertEqual(data["product_type"], "Hotel")
        self.assertEqual(data["booking_status"], "Cancelled")
        self.assertEqual(data["booking_id"], "NH23065512619254")
        self.assertEqual(data["airline_property_name"], "Taj Santacruz, Mumbai")
        self.assertEqual(data["start_date"], "2026-09-20")
        self.assertEqual(data["end_date"], "2026-09-24")
        self.assertEqual(data["origin_country"], "India")
        # A hotel line has no ticket number and no PNR — the case flat_statement refuses.
        self.assertNotIn("pnr", data)
        # No cess columns at all in this export, so nothing is invented.
        self.assertNotIn("legacy_cess", data)


class TestRegistryWiring(unittest.TestCase):
    """The hooks the router reads, and the guarantee that no other type grew them."""

    def test_the_registry_hands_out_this_types_hooks(self):
        self.assertIs(spec.normalize_row(SLUG), tp_api_spec.normalize)
        self.assertIs(spec.detect_format(SLUG), tp_api_spec.detect_format)
        self.assertIs(spec.derive_row(SLUG), tp_api_spec.derive)
        self.assertEqual(spec.ai_narration(SLUG), tp_api_spec.AI_NARRATION)

    def test_no_other_type_normalises_detects_a_format_or_has_a_narration(self):
        """All three run on the shared router, so a hook leaking onto another type would
        change how its rows are stored — silently, and on every line."""
        for other in spec.STATEMENT_SPECS:
            if other == SLUG:
                continue
            with self.subTest(slug=other):
                self.assertIsNone(spec.normalize_row(other))
                self.assertIsNone(spec.detect_format(other))
                self.assertIsNone(spec.ai_narration(other))

    def test_it_is_mapping_driven_and_needs_a_supplier(self):
        self.assertTrue(spec.supports_mapping(SLUG))
        self.assertTrue(spec.requires_supplier(SLUG))
        self.assertIsNone(spec.parser(SLUG))   # spec-driven, not a flat_statement builder

    def test_it_keeps_every_row(self):
        """A cancelled booking is still a statement line — it carries a refund and a
        cancellation fee. This is the deliberate contrast with NDC."""
        self.assertIsNone(spec.drop_row(SLUG))
        self.assertIsNone(spec.row_filter(SLUG))

    def test_it_has_its_own_table(self):
        from app.models.statement_row import STATEMENT_MODELS
        self.assertEqual(STATEMENT_MODELS[SLUG].__tablename__, "third_party_api")

    def test_the_format_column_is_declared_and_filled_on_the_same_condition(self):
        """A declared column nothing fills is an empty column on every row.

        `_display_columns` and the `/records` serializer decide this independently, and they
        drifted once already: the column was added for a spec-driven type while the
        serializer still branched on `parser` alone, so Format rendered blank on every line.
        """
        from app.api.v1 import statements as router
        from app.services import statement_spec as s
        for slug in s.STATEMENT_SPECS:
            with self.subTest(slug=slug):
                declared = any(c["field"] == "__format__" for c in router._display_columns(slug))
                filled = bool(s.parser(slug)) or s.detect_format(slug) is not None
                self.assertEqual(declared, filled)

    def test_the_staleness_check_does_not_apply_to_it(self):
        """It has TWO legitimate formats. A single-value equality check would flag every
        batch of one vendor as stale forever."""
        from app.services import flat_statement
        self.assertNotIn(SLUG, flat_statement.CURRENT_SOURCE_FORMATS)


if __name__ == "__main__":
    unittest.main()
