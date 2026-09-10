"""The NDC statement spec and its column mapping.

NDC is the first spec-driven type that goes through the map -> review -> confirm wizard
rather than being read verbatim, so two things are worth pinning down: that an airline's
raw export still maps itself (otherwise the wizard is dozens of dropdowns of manual work),
and that the spec's own cross-references — filters, summary, money, required groups — name
fields that actually exist. A typo in any of those is silent: the filter simply never
matches, the total is always zero, the required check can never pass.

It is also the only type that drops rows on content and the only one that derives a field
from more than one column, so both of those get their own case here.

No DB, no network — the spec and the mapper are pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest
from decimal import Decimal

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
#
# The tax cells are the real ones from that line, and they are the arithmetic the
# `Other Taxes` fold has to preserve: K3 311 + YQ 399 + YR 170 + (IN 989 + P2 236) = 2105,
# which is the line's own `Total Tax`.
TICKET_ROW = {
    "User Name": "ASHISH BAJAJ", "Document No": "0982185569174", "Product": "Flight",
    "TXN Type": "PAID_BOOKING", "Airline PNR": "9FTDB8", "Airline": "AI",
    "Passenger Name": "NITIN/CHAUHAN", "Total Fare": "7747.00", "Basic Fare": "5642.00",
    "Total Tax": "2105.00", "Payment Amount": "7747.00",
    "Date Of Booking": "15-Aug-2026", "Date Of Issue ": "15-Aug-2026",
    "Departure Date": "15-Aug-2026", "Departure Time (HH:MM)": "20:00",
    "IN Tax": "989.00", "K3 Tax": "311.00", "P2 Tax": "236.00",
    "YQ Tax": "399.00", "YR Tax": "170.00",
    "Tour Code": " ",
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

    def test_the_spec_keeps_forty_three_columns(self):
        """69 in the export, 43 kept. Pinned because the trim is a judgement call that the
        module docstring states as a number — the two must not drift apart."""
        self.assertEqual(len(spec.columns(SLUG)), 43)

    def test_billing_reads_payment_amount_and_date_of_issue(self):
        """Both were trimmed out and both came back for services/ndc_billing_projection.py:
        `Payment Amount` is the only signed figure in the file and becomes `total_amt`, the
        billing base; `Date Of Issue` becomes `ticket_date`, which deal validity and BSP
        reconciliation are checked against."""
        fields = set(spec.fields(SLUG))
        self.assertIn("payment_amount", fields)
        self.assertIn("date_of_issue", fields)
        # It is an amount, and it is worth a total of its own beside Total Fare.
        self.assertIn("payment_amount", spec.money_fields(SLUG))
        self.assertIn("payment_amount", [f["field"] for f in spec.summary_fields(SLUG)])
        # An unmapped issue date is a warning, not a refusal — the projection falls back
        # to Date Of Booking rather than refusing the whole upload.
        dates = next(g for g in spec.advisory_groups(SLUG) if g["label"] == "a date")
        self.assertIn("date_of_issue", dates["fields"])
        self.assertIn("date_of_issue", [f["field"] for f in spec.filter_specs(SLUG)])


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
        """The whole point of the alias list. If this drops, the uploader is handed dozens
        of dropdowns for a file we already understand.

        `Other Taxes` is exempt: it is derived from eleven of the airline's columns rather
        than mapped from one, so there is nothing in the export for it to match."""
        suggested = self.mapper.suggest_mapping(AI_HEADERS)
        missing = [c["header"] for c in spec.columns(SLUG)
                   if c["field"] not in suggested and c["field"] != ndc_spec.DERIVED_FIELD]
        self.assertEqual(missing, [], "these fields no longer auto-map")

    def test_exactly_the_trimmed_columns_go_unmapped(self):
        """The spec keeps 43 of the export's columns. This is the list of what it lets go —
        spelled out, because "the mapping dropped a column" is otherwise indistinguishable
        from a broken alias, and both look like an empty cell."""
        used = set(self.mapper.suggest_mapping(AI_HEADERS).values())
        self.assertEqual([c for c in AI_HEADERS if c not in used], [
            # In the export's own column order, so a diff points at the file.
            "User Name",                    # a property of the download, not the row
            "Agency Name",                  # the same agency on every line
            "TXN Sequence",                 # the portal's own per-PNR numbering
            "TTL (Due Time Limit)",         # only ever set on the unpaid holds we now skip
            "Time Of Booking",
            "Time Of Issue\n(HH:MM:SS - 24 hr format)",
            "Departure Time (HH:MM)", "Arrival Date", "Arrival Time(HH:MM)",
            "Agency Code",                  # as Agency Name
            "Payment Surcharge", "PNR Level Surcharge",
            "Amount Retained At PNR Level", "Amount Held", "PNR Level",
            "Application FOP", "Payment Reference Id",   # the airline's gateway, not ours
            # Folded into Other Taxes rather than dropped — see TestOtherTaxes.
            "AE Tax", "DE Tax", "F6 Tax", "FR Tax", "IN Tax",
            "O4 Tax", "P2 Tax", "QX Tax", "RA Tax", "TP Tax", "ZR Tax",
        ])

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
        self.assertEqual(data["total_fare"], "7747.00")
        self.assertEqual(data["yq_tax"], "399.00")
        self.assertEqual(data["date_of_booking"], "15-Aug-2026")
        self.assertEqual(data["departure_date"], "15-Aug-2026")

    def test_the_trimmed_columns_never_reach_the_row(self):
        """The mapper drops a source column it has no field for, so the trim is not just a
        narrower screen — the values are not stored either."""
        data = self._build(TICKET_ROW)
        for gone in ("departure_time", "agency_name", "txn_sequence", "amount_held",
                     "in_tax", "p2_tax"):
            self.assertNotIn(gone, data)

    def test_the_two_columns_billing_reads_are_stored(self):
        """`Payment Amount` and `Date Of Issue` came back for the billing projection —
        `total_amt` and `ticket_date` have nothing else to read. The export heads the second
        with a trailing space, which `norm` collapses, so no alias is involved."""
        data = self._build(TICKET_ROW)
        self.assertEqual(data["payment_amount"], "7747.00")
        self.assertEqual(data["date_of_issue"], "15-Aug-2026")
        self.assertEqual(spec.norm("Date Of Issue "), spec.norm("Date Of Issue"))

    def test_user_name_never_reaches_the_row(self):
        self.assertNotIn("user_name", self._build(TICKET_ROW))

    def test_blank_cells_are_absent_not_empty(self):
        """The export pads unused cells with a single space; storing that would make
        `Tour Code` look populated everywhere."""
        self.assertNotIn("tour_code", self._build(TICKET_ROW))

    def test_ancillary_row_still_maps(self):
        """The MAPPER builds every line, including the ones the row filter later discards.

        Keeping those two apart matters: `is_excluded` reads `txn_type` off the built row,
        so a mapper that quietly dropped the line would leave the filter nothing to judge —
        and would take PAID_SEAT with it, which is a sale."""
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


class TestOtherTaxes(unittest.TestCase):
    """Eleven of the airline's tax columns, added into one.

    The failure this guards against is arithmetic, not plumbing: a code left out of the sum
    makes `Other Taxes` quietly short, and the only way to notice is that K3 + YQ + YR +
    Other Taxes stops equalling the line's own `Total Tax`.
    """

    @staticmethod
    def _values(row: dict) -> dict:
        """The row keyed the way the router hands it over — normalised source headers."""
        return {spec.norm(k): v for k, v in row.items()}

    def test_it_adds_the_minor_codes_and_leaves_the_named_ones_alone(self):
        derived = ndc_spec.derive(self._values(TICKET_ROW))
        self.assertEqual(derived, {"other_taxes": "1225.00"})   # IN 989 + P2 236

    def test_the_four_tax_columns_still_reconcile_to_total_tax(self):
        """The whole point of folding rather than dropping. If this fails the repository is
        showing a tax breakdown that does not add up to the tax it also shows."""
        mapper = spec_mapping.mapper_for(SLUG)
        colmap = mapper.suggest_mapping(AI_HEADERS)
        data = mapper.build_row_mapped(TICKET_ROW, AI_HEADERS, colmap, None)["data"]
        data = {**ndc_spec.derive(self._values(TICKET_ROW)), **data}
        parts = sum(Decimal(data[f]) for f in ("k3_tax", "yq_tax", "yr_tax", "other_taxes"))
        self.assertEqual(parts, Decimal(data["total_tax"]))

    def test_a_line_with_none_of_them_gets_no_field(self):
        """An absent column and a genuine zero are different facts. Writing "0.00" for a
        file that never carried those columns invents a total the airline never sent."""
        self.assertEqual(ndc_spec.derive(self._values(SEAT_ROW)), {})

    def test_thousands_separators_and_dashes_survive(self):
        """Values are stored as the vendor wrote them, and an export pads an empty cell with
        "—" or a space. A separator misread would multiply the total by a thousand."""
        derived = ndc_spec.derive({"ae_tax": "1,234.50", "de_tax": " ", "f6_tax": "—",
                                   "in_tax": "10"})
        self.assertEqual(derived, {"other_taxes": "1244.50"})

    def test_an_unreadable_cell_is_skipped_not_counted_as_zero(self):
        derived = ndc_spec.derive({"ae_tax": "N/A", "in_tax": "100.00"})
        self.assertEqual(derived, {"other_taxes": "100.00"})

    def test_bare_code_headers_are_recognised(self):
        """Some portals head the column "AE" rather than "AE Tax" — the same pairs the
        per-code aliases used to carry before these columns were folded."""
        self.assertEqual(ndc_spec.derive({"ae": "50", "zr": "25"}),
                         {"other_taxes": "75.00"})

    def test_the_kept_codes_are_not_in_the_sum(self):
        """K3, YQ and YR have columns of their own. Counting them here would double them."""
        for kept in ("k3", "yq", "yr", "k3_tax", "yq_tax", "yr_tax", "total_tax"):
            self.assertNotIn(kept, ndc_spec.OTHER_TAX_KEYS)

    def test_other_taxes_is_a_column_and_reads_as_money(self):
        self.assertIn(ndc_spec.DERIVED_FIELD, spec.fields(SLUG))
        self.assertIn(ndc_spec.DERIVED_FIELD, spec.money_fields(SLUG))

    def test_the_registry_hands_out_the_derivation(self):
        self.assertIs(spec.derive_row(SLUG), ndc_spec.derive)
        for other in spec.STATEMENT_SPECS:
            if other != SLUG:
                self.assertIsNone(spec.derive_row(other), f"{other} derives fields too")


class TestRowFilter(unittest.TestCase):
    """Which lines of the ledger reach the table.

    Air India's export is ten TXN Types; only the six where money moved are transactions.
    The rule runs at ingest, so a mistake here is not a wrong screen — it is rows that were
    never written, or unpaid holds counted as sales in Commission income.
    """

    def test_the_six_paid_types_are_kept(self):
        for txn in ("PAID_BOOKING", "PAID_SEAT", "REFUND", "REFUND_SEAT",
                    "SPLIT_BOOKING", "TICKETING"):
            with self.subTest(txn=txn):
                self.assertFalse(ndc_spec.is_excluded({"txn_type": txn}))

    def test_the_unpaid_and_free_types_are_dropped(self):
        for txn in ("UNPAID_BOOKING", "UNPAID_CANCEL", "UNPAID_SEAT", "FREE_SEAT"):
            with self.subTest(txn=txn):
                self.assertTrue(ndc_spec.is_excluded({"txn_type": txn}))

    def test_the_two_lists_do_not_overlap_and_cover_the_export(self):
        """A value in both lists would make the docstring and the code disagree, and the
        ten together are every type Air India's export emits."""
        self.assertFalse(ndc_spec.EXCLUDED_TXN_TYPES & ndc_spec.KEPT_TXN_TYPES)
        self.assertEqual(len(ndc_spec.EXCLUDED_TXN_TYPES | ndc_spec.KEPT_TXN_TYPES), 10)

    def test_spelling_variants_are_the_same_transaction(self):
        """Another portal's "Free Seat" is Air India's FREE_SEAT. Matching the raw string
        would let it through as an unrecognised type."""
        for raw in ("Free Seat", "free-seat", " FREE_SEAT ", "unpaid booking"):
            with self.subTest(raw=raw):
                self.assertTrue(ndc_spec.is_excluded({"txn_type": raw}))

    def test_an_unrecognised_type_imports(self):
        """The drop list names what to discard, so a carrier's type we have never seen
        arrives and is visible in the TXN Type filter instead of vanishing."""
        self.assertFalse(ndc_spec.is_excluded({"txn_type": "VOID"}))

    def test_an_unmapped_or_blank_txn_type_imports(self):
        """Not knowing a row's type is not evidence that it is an unpaid hold — and if an
        unmapped column dropped rows, mapping nothing would empty the whole file."""
        self.assertFalse(ndc_spec.is_excluded({"document_no": "0982185569174"}))
        self.assertFalse(ndc_spec.is_excluded({"txn_type": ""}))
        self.assertFalse(ndc_spec.is_excluded({"txn_type": "  "}))
        self.assertFalse(ndc_spec.is_excluded({"txn_type": None}))

    def test_it_reads_a_built_row(self):
        """End to end against the real export: the mapper builds both lines, and the filter
        keeps the sale and drops the free seat."""
        mapper = spec_mapping.mapper_for(SLUG)
        colmap = mapper.suggest_mapping(AI_HEADERS)
        build = lambda r: mapper.build_row_mapped(r, AI_HEADERS, colmap, None)["data"]  # noqa: E731
        self.assertFalse(ndc_spec.is_excluded(build(TICKET_ROW)))
        self.assertTrue(ndc_spec.is_excluded(build(SEAT_ROW)))


class TestRowFilterWiring(unittest.TestCase):
    """The registry hooks. A filter the router never calls is a filter that does nothing."""

    def test_the_registry_hands_out_the_filter(self):
        self.assertIs(spec.drop_row(SLUG), ndc_spec.is_excluded)

    def test_only_ndc_supports_billing(self):
        """Nine slugs share one router and one frontend view. The flag is what stops a
        Billing column, eight endpoints and a set of `bill_*` columns leaking onto the
        types that have none of them — `_BillingMixin` is on `Ndc` alone."""
        self.assertTrue(spec.supports_billing(SLUG))
        for other in spec.STATEMENT_SPECS:
            if other != SLUG:
                self.assertFalse(spec.supports_billing(other), other)

    def test_no_other_type_drops_rows(self):
        """Opt-in per type, like requires_airline_id — these types share one router, and a
        filter leaking onto BSP or TGQ HMPR would silently shrink their imports."""
        for other in spec.STATEMENT_SPECS:
            if other != SLUG:
                with self.subTest(slug=other):
                    self.assertIsNone(spec.drop_row(other))
                    self.assertIsNone(spec.row_filter(other))

    def test_the_screen_description_matches_the_rule(self):
        """The wizard greys rows out from ROW_FILTER while the API drops them with
        `is_excluded`. If the two lists drift, the preview lies about what will be saved."""
        rf = spec.row_filter(SLUG)
        self.assertEqual(set(rf["exclude"]), ndc_spec.EXCLUDED_TXN_TYPES)
        self.assertEqual(set(rf["keep"]), ndc_spec.KEPT_TXN_TYPES)
        self.assertIn(rf["field"], spec.fields(SLUG))
        # The column the rule reads has to be one the user can actually map onto.
        self.assertIn(rf["header"], ndc_spec.HEADERS)


if __name__ == "__main__":
    unittest.main()
