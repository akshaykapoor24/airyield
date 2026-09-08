"""Unit tests for user-supplied column mapping — no DB, no network.

`build_row_mapped` is what makes a consolidator's own spreadsheet importable: the alias map
answers "which field is this column", and this answers the same question the other way
round, from a choice a person made. The cases that matter are the ones where a mapping is
WRONG or STALE — a field pointing at a column the file does not have, a source column used
twice, an edit that clears a value — because each of those silently produces plausible rows
if it is handled carelessly.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import flat_statement as fs  # noqa: E402


# A consolidator who names nothing the way we do.
OTHER_HEADERS = ["Carrier", "Tkt", "PNR Ref", "Sale Dt", "Fly Dt", "Fare", "Fuel",
                 "Tax", "Comm", "Payable", "Pax"]
OTHER_ROW = {
    "Carrier": "TURKISH AIRLINES", "Tkt": "4848358656", "PNR Ref": "ABC123",
    "Sale Dt": "08-08-2026", "Fly Dt": "15-08-2026", "Fare": "66,250.00",
    "Fuel": "0", "Tax": "23069", "Comm": "0", "Payable": "89437", "Pax": "MR AJAY",
}
MAPPING = {
    "airline_name": "Carrier", "ticket_number": "Tkt", "pnr": "PNR Ref",
    "booking_date": "Sale Dt", "travel_date": "Fly Dt", "base_fare": "Fare",
    "yq": "Fuel", "other_taxes": "Tax", "commission_amount": "Comm",
    "net_amount": "Payable", "passenger_name": "Pax",
}


def build(headers, values, mapping, overrides=None):
    return fs.get("tp-gds").build_row_mapped(dict(zip(headers, values)) if isinstance(values, list)
                                             else values, headers, mapping, overrides)


class TestMappedBuild(unittest.TestCase):
    def test_a_foreign_layout_maps_onto_our_fields(self):
        d = build(OTHER_HEADERS, OTHER_ROW, MAPPING)["data"]
        self.assertEqual(d["airline_name"], "TURKISH AIRLINES")
        self.assertEqual(d["ticket_number"], "4848358656")
        self.assertEqual(d["pnr"], "ABC123")
        self.assertEqual(d["passenger_name"], "MR AJAY")

    def test_derivation_still_runs_after_mapping(self):
        """Dates and amounts are normalised whichever way the column was found — a mapped
        file that skipped this would break plb_accrual and the commission run silently."""
        d = build(OTHER_HEADERS, OTHER_ROW, MAPPING)["data"]
        self.assertEqual(d["booking_date"], "2026-08-08")
        self.assertEqual(d["travel_date"], "2026-08-15")
        self.assertEqual(d["base_fare"], "66250.00")
        self.assertEqual(d["issue_date"], "2026-08-08")
        self.assertEqual(d["issue_date_source"], "booked_date")

    def test_the_aliases_are_not_consulted(self):
        """`Tax` would alias to `taxes`, but the user mapped it to `other_taxes`. The
        user's choice must win, or the mapping screen is theatre."""
        d = build(OTHER_HEADERS, OTHER_ROW, MAPPING)["data"]
        self.assertEqual(d["other_taxes"], "23069")
        self.assertNotIn("taxes", d)

    def test_an_unmapped_column_is_not_imported(self):
        d = build(OTHER_HEADERS, OTHER_ROW, {"ticket_number": "Tkt"})["data"]
        self.assertEqual(set(d) - {"issue_date_source"}, {"ticket_number"})

    def test_a_field_pointing_at_a_missing_column_is_dropped(self):
        """A mapping reused against a different export must not store empty strings under
        every field it can no longer find."""
        d = build(OTHER_HEADERS, OTHER_ROW,
                  {**MAPPING, "sector": "Route (not in this file)"})["data"]
        self.assertNotIn("sector", d)

    def test_one_column_may_feed_two_fields(self):
        """Allowed — the UI warns, because it is usually a mistake, but a file that really
        does put the same value in two places should still import."""
        d = build(OTHER_HEADERS, OTHER_ROW,
                  {"ticket_number": "Tkt", "pnr": "Tkt", "base_fare": "Fare"})["data"]
        self.assertEqual(d["ticket_number"], d["pnr"])

    def test_raw_data_keeps_the_file_not_our_reading_of_it(self):
        """Reprocess re-reads raw_data, so it must hold the source columns under the
        source's own names — not the mapped ones."""
        raw = build(OTHER_HEADERS, OTHER_ROW, MAPPING)["raw_data"]
        self.assertEqual(raw["Payable"], "89437")
        self.assertNotIn("net_amount", raw)

    def test_an_empty_row_yields_no_data(self):
        blank = {h: "" for h in OTHER_HEADERS}
        self.assertEqual(build(OTHER_HEADERS, blank, MAPPING)["data"], {})


class TestReviewEdits(unittest.TestCase):
    def test_an_edit_replaces_the_mapped_value(self):
        d = build(OTHER_HEADERS, OTHER_ROW, MAPPING, {"base_fare": "70000"})["data"]
        self.assertEqual(d["base_fare"], "70000")

    def test_an_edited_value_is_still_normalised(self):
        """Typing 13-08-2026 into the review grid must arrive as a date, not as text."""
        d = build(OTHER_HEADERS, OTHER_ROW, MAPPING, {"travel_date": "13-08-2026"})["data"]
        self.assertEqual(d["travel_date"], "2026-08-13")
        d = build(OTHER_HEADERS, OTHER_ROW, MAPPING, {"base_fare": "1,23,456.78"})["data"]
        self.assertEqual(d["base_fare"], "123456.78")

    def test_an_edit_can_add_a_field_the_mapping_never_covered(self):
        d = build(OTHER_HEADERS, OTHER_ROW, MAPPING, {"segment_type": "INTERNATIONAL"})["data"]
        self.assertEqual(d["segment_type"], "INTERNATIONAL")

    def test_clearing_a_cell_removes_the_field(self):
        d = build(OTHER_HEADERS, OTHER_ROW, MAPPING, {"commission_amount": ""})["data"]
        self.assertNotIn("commission_amount", d)

    def test_an_edit_feeds_the_derived_total(self):
        """total_fare is derived from the amounts, so a corrected fare has to change it —
        otherwise the correction is visible on screen and absent from the accrual."""
        base = build(OTHER_HEADERS, OTHER_ROW, MAPPING)["data"]
        edited = build(OTHER_HEADERS, OTHER_ROW, MAPPING, {"base_fare": "70000"})["data"]
        self.assertNotEqual(base["total_fare"], edited["total_fare"])
        self.assertEqual(float(edited["total_fare"]), 70000 + 0 + 23069)


class TestSuggestMapping(unittest.TestCase):
    def test_our_own_template_suggests_itself_completely(self):
        headers = [c["header"] for c in fs.TP_GDS_DISPLAY]
        suggested = fs.get("tp-gds").suggest_mapping(headers)
        missing = [c["field"] for c in fs.TP_GDS_DISPLAY if c["field"] not in suggested]
        self.assertEqual(missing, [], f"template fields with no suggestion: {missing}")

    def test_it_points_field_to_column_not_the_other_way(self):
        """The mapping UI asks 'which of my columns is the Basic Fare', so the suggestion
        has to be keyed by field."""
        suggested = fs.get("tp-gds").suggest_mapping(["Basic Fare", "Ticket No"])
        self.assertEqual(suggested, {"base_fare": "Basic Fare", "ticket_number": "Ticket No"})

    def test_a_foreign_layout_suggests_only_what_it_recognises(self):
        suggested = fs.get("tp-gds").suggest_mapping(OTHER_HEADERS)
        # "Fare", "Tax", "PNR Ref" -> no; "Pax" -> passenger_count; "Comm" -> commission_rate.
        self.assertIn("passenger_count", suggested)
        self.assertNotIn("net_amount", suggested)
        self.assertLess(len(suggested), len(OTHER_HEADERS))


class TestColumnGroups(unittest.TestCase):
    def test_every_column_lands_in_a_group(self):
        for slug in ("tp-gds", "tp-lcc"):
            grouped = {c["field"] for g in fs.column_groups(slug) for c in g["columns"]}
            declared = {c["field"] for c in fs.get(slug).display_columns}
            self.assertEqual(grouped, declared, slug)

    def test_groups_are_in_the_declared_order(self):
        names = [g["group"] for g in fs.column_groups("tp-gds")]
        self.assertEqual(names, [g for g in fs.GROUP_ORDER if g in names])

    def test_the_money_group_holds_the_fields_commission_runs_on(self):
        money = {c["field"] for g in fs.column_groups("tp-gds") if g["group"] == "Money"
                 for c in g["columns"]}
        for f in ("base_fare", "yq", "other_taxes", "commission_amount",
                  "incentive_amount", "tds", "net_amount"):
            self.assertIn(f, money)

    def test_required_and_advisory_name_real_fields(self):
        """A required group listing a field that does not exist would be unsatisfiable."""
        fields = {c["field"] for c in fs.get("tp-gds").display_columns}
        for g in fs.REQUIRED_GROUPS + fs.ADVISORY_GROUPS:
            for f in g["fields"]:
                self.assertIn(f, fields, f"{g['label']} names unknown field {f!r}")

    def test_required_is_about_being_findable_advisory_about_being_priceable(self):
        """The split is the whole policy: refuse what makes a row unusable, warn about what
        makes it merely unmatched."""
        required = {f for g in fs.REQUIRED_GROUPS for f in g["fields"]}
        advisory = {f for g in fs.ADVISORY_GROUPS for f in g["fields"]}
        self.assertTrue({"ticket_number", "base_fare"} <= required)
        self.assertTrue({"airline_name", "booking_date"} <= advisory)
        self.assertEqual(required & advisory, set())


if __name__ == "__main__":
    unittest.main()
