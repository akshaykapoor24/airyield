"""The NDC statement spec and its column mapping.

NDC is the first spec-driven type that goes through the map -> review -> confirm wizard
rather than being read verbatim, so two things are worth pinning down: that an airline's
raw export still maps itself (otherwise the wizard is 69 dropdowns of manual work), and
that the spec's own cross-references — filters, summary, money, required groups — name
fields that actually exist. A typo in any of those is silent: the filter simply never
matches, the total is always zero, the required check can never pass.

No DB, no network — the spec and the mapper are pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import ndc_spec, spec_mapping  # noqa: E402
from app.services import statement_spec as spec  # noqa: E402

SLUG = "ndc"

# Air India's export exactly as it arrives: `User Name` first, format hints baked into the
# header cells, a trailing space on one, a line break inside another.
AI_HEADERS = [
    "User Name", "Booking Signin", "TKT Issue Signin", "Agency Name", "Agency Type",
    "Document No", "Inconnection Doc number", "Coupon number", "Document Type", "Product",
    "TXN Sequence", "TXN Type", "Airline PNR", "Child/Parent PNR", "Airline",
    "Airline IATA Code", "Payment Status", "TTL (Due Time Limit)", "Date Of Booking",
    "Time Of Booking", "Date Of Issue ", "Time Of Issue\n(HH:MM:SS - 24 hr format)",
    "Class Of Booking", "FareBasis", "Flight No", "Sectors", "Coupon Status",
    "Departure Date", "Departure Time (HH:MM)", "Arrival Date", "Arrival Time(HH:MM)",
    "Passenger Name", "Passenger Type", "Conjunction Ticket No", "Tour Code", "Deal Code",
    "Agency Code", "Form Of Payment", "Total Fare", "Basic Fare", "Total Tax",
    "Payment Amount", "Penalty Amount", "Payment Surcharge", "PNR Level Surcharge",
    "Amount Retained At PNR Level", "Amount Held", "PNR Level", "Currency", "Discount",
    "Promo Code", "Service Fee", "Application FOP", "Payment Reference Id", "Cabin Code",
    "Cabin Name", "AE Tax", "DE Tax", "F6 Tax", "FR Tax", "IN Tax", "K3 Tax", "O4 Tax",
    "P2 Tax", "QX Tax", "RA Tax", "TP Tax", "YQ Tax", "YR Tax", "ZR Tax",
]

# A ticketed sale, and the ancillary line that follows it — the ancillary has no document
# number, which is exactly the case the required-fields rule has to accommodate.
TICKET_ROW = {
    "User Name": "ASHISH BAJAJ", "Document No": "0982185569174", "Product": "Flight",
    "TXN Type": "PAID_BOOKING", "Airline PNR": "9FTDB8", "Airline": "AI",
    "Passenger Name": "NITIN/CHAUHAN", "Total Fare": "7747.00", "Basic Fare": "5642.00",
    "Payment Amount": "7747.00", "YQ Tax": "399.00", "Date Of Issue ": "15-Aug-2026",
    "Departure Time (HH:MM)": "20:00", "Tour Code": " ",
}
SEAT_ROW = {
    "User Name": "ASHISH BAJAJ", "Document No": " ", "Product": "Seat",
    "TXN Type": "FREE_SEAT", "Airline PNR": "9FTDB8", "Airline": "AI",
    "Passenger Name": "NITIN/CHAUHAN", "Total Fare": "0.00", "Payment Amount": "0.00",
}


class TestColumns(unittest.TestCase):
    def test_user_name_is_not_a_column(self):
        """It is the same on every line of an export — a property of the download, not the
        ticket. The uploader is already recorded on the batch."""
        fields = spec.fields(SLUG)
        self.assertNotIn("user_name", fields)
        self.assertNotIn("username", fields)

    def test_every_column_is_distinct(self):
        fields = spec.fields(SLUG)
        self.assertEqual(len(fields), len(set(fields)), "two NDC columns share a field key")
        headers = [c["header"] for c in spec.columns(SLUG)]
        self.assertEqual(len(headers), len(set(headers)))

    def test_columns_carry_a_known_group(self):
        """`spec_mapping.column_groups` orders by GROUP_ORDER and appends the rest; an
        unlisted group is not an error but it is always an oversight."""
        for c in spec.columns(SLUG):
            self.assertIn(c.get("group"), ndc_spec.GROUP_ORDER, f"{c['header']} is ungrouped")

    def test_taxes_are_columns_not_a_folded_array(self):
        """An NDC export names its taxes (`YQ Tax`), unlike TGQ HMPR's generic
        Tax_TypeN/TaxN pairs — so folding is off and each code is its own field."""
        self.assertFalse(spec.fold_taxes(SLUG))
        self.assertIn("yq_tax", spec.fields(SLUG))
        self.assertIn("k3_tax", spec.fields(SLUG))


class TestSpecCrossReferences(unittest.TestCase):
    """Every field a spec key names must be a real column. None of these fail loudly."""

    def _fields(self):
        return set(spec.fields(SLUG))

    def test_filters_name_real_fields(self):
        for f in spec.filter_specs(SLUG):
            self.assertIn(f["field"], self._fields(), f"filter {f['label']}")
            self.assertIn(f["type"], ("select", "text"))

    def test_summary_and_money_name_real_fields(self):
        for f in spec.summary_fields(SLUG):
            self.assertIn(f["field"], self._fields(), f"summary {f['label']}")
        for field in spec.money_fields(SLUG):
            self.assertIn(field, self._fields(), f"money field {field}")

    def test_summary_fields_are_money_fields(self):
        """A column totalled in the slab but not formatted as money reads as a bare
        integer next to its own total."""
        money = spec.money_fields(SLUG)
        for f in spec.summary_fields(SLUG):
            self.assertIn(f["field"], money)

    def test_required_and_advisory_name_real_fields(self):
        for group in spec.required_groups(SLUG) + spec.advisory_groups(SLUG):
            self.assertTrue(group["fields"], f"{group['label']} lists no fields")
            for field in group["fields"]:
                self.assertIn(field, self._fields(), f"{group['label']} -> {field}")

    def test_an_ancillary_row_can_satisfy_the_required_identifier(self):
        """Seat and unpaid-hold lines carry no Document No. If the identifier rule did not
        accept a PNR, confirm would reject the very rows the spec says to import."""
        identifier = next(g for g in spec.required_groups(SLUG)
                          if g["label"] == "a booking identifier")
        self.assertIn("airline_pnr", identifier["fields"])

    def test_no_alias_claims_two_fields(self):
        """The one that actually matters. `SpecMapper` resolves a collision to whichever
        alias was registered first, so the failure is a column landing in the wrong field —
        no error, no blank cell, just a wrong number."""
        owner: dict[str, str] = {}
        for field, names in spec.aliases(SLUG).items():
            for a in names:
                key = spec.norm(a)
                self.assertEqual(owner.setdefault(key, field), field,
                                 f"alias '{a}' claims both {owner[key]} and {field}")

    def test_no_alias_is_redundant(self):
        """Matching is on norm() of both sides, so "Office Id" and "Office ID" are one
        alias written twice. Harmless, but it reads as coverage the list does not have."""
        for field, names in spec.aliases(SLUG).items():
            keys = [spec.norm(a) for a in names]
            self.assertEqual(len(keys), len(set(keys)),
                             f"{field} lists aliases that normalize identically: {names}")


class TestAutoMapping(unittest.TestCase):
    def setUp(self):
        self.mapper = spec_mapping.mapper_for(SLUG)

    def test_air_india_export_maps_itself(self):
        """The whole point of the alias list. If this drops, the uploader is handed 69
        dropdowns for a file we already understand."""
        suggested = self.mapper.suggest_mapping(AI_HEADERS)
        missing = [c["header"] for c in spec.columns(SLUG) if c["field"] not in suggested]
        self.assertEqual(missing, [], "these fields no longer auto-map")

    def test_user_name_is_the_only_column_dropped(self):
        suggested = self.mapper.suggest_mapping(AI_HEADERS)
        used = set(suggested.values())
        self.assertEqual([c for c in AI_HEADERS if c not in used], ["User Name"])

    def test_template_round_trips(self):
        """A file built from Download template comes back fully mapped, which is what the
        wizard's "this file matches the template" banner is asserting."""
        headers = spec.template_headers(SLUG)
        self.assertEqual(len(headers), len(spec.columns(SLUG)))
        suggested = self.mapper.suggest_mapping(headers)
        self.assertEqual(len(suggested), len(spec.columns(SLUG)))

    def test_a_field_is_claimed_once(self):
        """"Document No" and "Ticket No" both mean document_no. Taking the second would
        silently overwrite the first; the user resolves it on the mapping screen."""
        colmap = self.mapper.build_col_map(["Document No", "Ticket No", "Airline PNR"])
        self.assertEqual(colmap, {"Document No": "document_no", "Airline PNR": "airline_pnr"})


class TestRowBuilding(unittest.TestCase):
    def setUp(self):
        self.mapper = spec_mapping.mapper_for(SLUG)
        self.colmap = self.mapper.suggest_mapping(AI_HEADERS)

    def _build(self, row, overrides=None):
        return self.mapper.build_row_mapped(row, AI_HEADERS, self.colmap, overrides)["data"]

    def test_ticket_row_keeps_its_values_verbatim(self):
        data = self._build(TICKET_ROW)
        self.assertEqual(data["document_no"], "0982185569174")
        self.assertEqual(data["payment_amount"], "7747.00")
        self.assertEqual(data["yq_tax"], "399.00")
        self.assertEqual(data["date_of_issue"], "15-Aug-2026")
        self.assertEqual(data["departure_time"], "20:00")

    def test_user_name_never_reaches_the_row(self):
        self.assertNotIn("user_name", self._build(TICKET_ROW))

    def test_blank_cells_are_absent_not_empty(self):
        """The export pads unused cells with a single space; storing that would make
        `Tour Code` look populated everywhere."""
        self.assertNotIn("tour_code", self._build(TICKET_ROW))

    def test_ancillary_row_survives(self):
        """No Document No, no fare breakdown — still a real transaction line, and dropping
        it would stop the file reconciling against the airline's own totals."""
        data = self._build(SEAT_ROW)
        self.assertNotIn("document_no", data)
        self.assertEqual(data["product"], "Seat")
        self.assertEqual(data["txn_type"], "FREE_SEAT")
        self.assertEqual(data["airline_pnr"], "9FTDB8")

    def test_a_review_edit_wins_over_the_file(self):
        data = self._build(TICKET_ROW, {"passenger_name": "NITIN CHAUHAN"})
        self.assertEqual(data["passenger_name"], "NITIN CHAUHAN")

    def test_an_empty_edit_clears_the_field(self):
        """How a reviewer deletes a value the sheet got wrong."""
        data = self._build(TICKET_ROW, {"passenger_name": ""})
        self.assertNotIn("passenger_name", data)


if __name__ == "__main__":
    unittest.main()
