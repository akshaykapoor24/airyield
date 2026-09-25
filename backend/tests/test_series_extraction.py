"""Series contract reading, penalties and reminders — pinned against the two sample contracts.

The model's raw answers below are what a correct read of the two sample PDFs looks like:
the Air France/KLM Group Sales Agreement A 5854811-1/1 (L64E9A, 12 pax, DEL-CDG-YYZ,
27 Dec 2023) and the Air India group request GRP123003 (DELATQDEL, 60 pax, DEL-ATQ-DEL,
30 Apr / 01 May 2025). What is tested is everything AFTER the model — the normalisation,
the cross-checks, the penalty arithmetic and the reminder stages — which is the part that
has to be right every time. No DB, no network, no API key.

Run:  ..\\venv\\Scripts\\python.exe -m unittest tests.test_series_extraction -v   (from backend/)
"""
import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.series import deadlines as dl, extraction, penalties, reminders  # noqa: E402

TODAY = date(2023, 9, 8)   # D-110 for the Air France departure


def _term(**kw):
    base = dict(rule_type="CANCELLATION", scope="GROUP", phase="ANY", days_before_max=None,
                days_before_min=None, share_min_pct=None, share_max_pct=None,
                charge_type="PCT_OF_BASIS", charge_value=None, charge_basis="NET_FARE",
                cabin=None, plus_gst=False, description=None, source_text=None,
                source_page=3)
    base.update(kw)
    return base


AF_RAW = {
    "doc_kind": "CONTRACT",
    "summary": "Air France/KLM group sales agreement for 12 passengers DEL-CDG-YYZ.",
    "header": {
        "contract_type": "GROUP", "source_type": "AIRLINE",
        "contract_number": "A 5854811-1/1", "group_reference": "L64E9A",
        "group_name": "Direct Canada DEC", "airline_code": "AF", "airline_name": "Air France KLM",
        "supplier_name": None, "supplier_ref": None, "currency": "INR",
        "contracted_pax": 12, "minimum_pax": 10, "maximum_pax": None,
        "materialization_floor_pct": None, "cabin": "ECONOMY",
        "contract_date": "2023-01-03", "option_expires_on": "2023-01-06",
        "foc_per_paid": None, "baggage_allowance": None, "event_name": None,
    },
    "departures": [{
        "departure_date": "2023-12-27", "requested_pax": 12,
        "sectors": [
            {"direction": "OUTBOUND", "origin": "DEL", "destination": "CDG", "airline_code": "AF",
             "flight_number": "AF 225", "departure_at": "2023-12-27T01:05",
             "arrival_at": "2023-12-27T07:00", "cabin": "ECONOMY", "rbd": "U"},
            {"direction": "OUTBOUND", "origin": "CDG", "destination": "YYZ", "airline_code": "AF",
             "flight_number": "AF356", "departure_at": "2023-12-27T14:20",
             "arrival_at": "2023-12-27T16:45", "cabin": "ECONOMY", "rbd": "U"},
        ],
    }],
    "series_pattern": None,
    "fare_components": [
        {"component_code": "BASE", "label": "Net fare", "amount_per_pax": 64600,
         "is_guaranteed_until_ticketing": False, "is_refundable_on_noshow": False},
        {"component_code": "YR_F", "label": "Sustainable Fuel Contribution (YR-F)", "amount_per_pax": 249,
         "is_guaranteed_until_ticketing": True, "is_refundable_on_noshow": False},
        {"component_code": "YR_I", "label": "YR-I,YQ", "amount_per_pax": 19050,
         "is_guaranteed_until_ticketing": True, "is_refundable_on_noshow": False},
        {"component_code": "TAX_STATUTORY", "label": "Taxes", "amount_per_pax": 7357,
         "is_guaranteed_until_ticketing": False, "is_refundable_on_noshow": False},
    ],
    "fare_totals": {"per_pax_total": 91256, "group_total": 1095072, "group_total_excluding_taxes": 775200},
    "payment_schedule": [
        {"kind": "ADVANCE_DEPOSIT", "due_date": "2023-01-06", "due_offset_days": None, "amount": 38760,
         "pct": None, "pct_basis": None, "is_refundable": None, "notes": None},
        {"kind": "DEPOSIT", "due_date": "2023-09-18", "due_offset_days": None, "amount": 193800,
         "pct": None, "pct_basis": None, "is_refundable": None, "notes": None},
        {"kind": "FINAL_PAYMENT", "due_date": "2023-12-19", "due_offset_days": 8, "amount": None,
         "pct": None, "pct_basis": None, "is_refundable": None, "notes": None},
    ],
    "deadlines": [
        {"deadline_type": "NAME_LIST", "offset_days": 30, "offset_hours": None,
         "stated_date": "2023-11-27", "action_required": None},
        {"deadline_type": "TICKETING", "offset_days": 8, "offset_hours": None,
         "stated_date": "2023-12-19", "action_required": None},
        # A payment extracted as a deadline must be dropped — the schedule raises it.
        {"deadline_type": "FINAL_PAYMENT", "offset_days": 8, "offset_hours": None,
         "stated_date": "2023-12-19", "action_required": None},
    ],
    "terms": [
        _term(days_before_min=121, charge_value=5),
        _term(days_before_max=120, days_before_min=101, charge_value=15),
        _term(days_before_max=100, days_before_min=31, charge_value=30),
        _term(days_before_max=30, days_before_min=0, charge_value=100),
        _term(phase="AFTER_TICKETING", charge_type="NON_REFUNDABLE", charge_basis=None),
        _term(scope="PARTIAL", days_before_min=121, share_max_pct=20, charge_type="FREE", charge_basis=None),
        _term(scope="PARTIAL", days_before_min=121, share_min_pct=20, charge_value=5),
        _term(rule_type="DEVIATION", scope="PER_PAX", charge_type="FARE_DIFFERENCE", charge_basis=None),
    ],
    "passengers": [],
    "evidence": [
        {"field": "header.contract_number", "page": 2, "quote": "N° A 5854811 -1/1"},
        {"field": "departures[0].sectors[0].flight_number", "page": 3, "quote": "AF 225 U Economy 27/12/23"},
    ],
    "notes_for_reviewer": ["A handwritten mark on page 1 was ignored."],
}

AI_RAW = {
    "doc_kind": "QUOTATION",
    "summary": "Air India group request for 60 passengers DEL-ATQ-DEL. No fare is quoted.",
    "header": {
        "contract_type": "SIT", "source_type": "AIRLINE",
        "contract_number": "GRP123003", "group_reference": None, "group_name": "DELATQDEL",
        "airline_code": "ai", "airline_name": "Air India", "supplier_name": None, "supplier_ref": None,
        "currency": None, "contracted_pax": 60, "minimum_pax": 10, "maximum_pax": 99,
        "materialization_floor_pct": 80, "cabin": "Economy", "contract_date": "2025-03-26",
        "option_expires_on": None, "foc_per_paid": None, "baggage_allowance": None, "event_name": None,
    },
    "departures": [{
        "departure_date": None, "requested_pax": 60,
        "sectors": [
            {"direction": "OUTBOUND", "origin": "del", "destination": "ATQ", "airline_code": None,
             "flight_number": "AI-495", "departure_at": "2025-04-30T08:30", "arrival_at": "2025-04-30T09:40",
             "cabin": None, "rbd": None},
            {"direction": "INBOUND", "origin": "ATQ", "destination": "DEL", "airline_code": None,
             "flight_number": "AI-462", "departure_at": "2025-05-01T16:15", "arrival_at": "2025-05-01T17:35",
             "cabin": None, "rbd": None},
        ],
    }],
    "series_pattern": None,
    "fare_components": [],
    "fare_totals": {"per_pax_total": None, "group_total": None, "group_total_excluding_taxes": None},
    "payment_schedule": [],
    "deadlines": [
        {"deadline_type": "NO_SHOW_CUTOFF", "offset_days": None, "offset_hours": 24,
         "stated_date": None, "action_required": None},
    ],
    "terms": [
        _term(phase="BEFORE_TICKETING", charge_type="DEPOSIT_FORFEIT", charge_basis=None),
        _term(rule_type="SEAT_RELEASE", scope="PARTIAL", phase="AFTER_DEPOSIT_BEFORE_FINAL",
              share_max_pct=20, charge_type="FREE", charge_basis=None),
        _term(rule_type="SEAT_RELEASE", scope="PARTIAL", share_min_pct=20, share_max_pct=50,
              charge_value=50, charge_basis="AI_RETENTION"),
        _term(rule_type="NAME_CHANGE", scope="PER_PAX", cabin="ECONOMY", charge_type="FIXED_PER_PAX",
              charge_value=4000, charge_basis=None, plus_gst=True),
        _term(rule_type="NAME_CHANGE", scope="PER_PAX", cabin="BUSINESS", charge_type="FIXED_PER_PAX",
              charge_value=9000, charge_basis=None, plus_gst=True),
        _term(rule_type="NO_SHOW", scope="PER_PAX", charge_type="TAXES_ONLY_REFUNDABLE", charge_basis=None),
        # A made-up enum from the model is dropped, not stored.
        _term(rule_type="SOMETHING_ELSE", charge_type="FREE"),
    ],
    "passengers": [],
    "evidence": [],
    "notes_for_reviewer": [],
}


class AirFranceRead(unittest.TestCase):
    def setUp(self):
        self.draft = extraction.normalize(AF_RAW, today=TODAY)

    def test_header_is_carried_across(self):
        h = self.draft.header
        self.assertEqual(h["contract_number"], "A 5854811-1/1")
        self.assertEqual(h["group_reference"], "L64E9A")
        self.assertEqual(h["airline_code"], "AF")
        self.assertEqual(h["contracted_pax"], 12)
        self.assertEqual(h["minimum_pax"], 10)
        self.assertEqual(h["option_expires_on"], "2023-01-06")

    def test_flight_numbers_lose_their_spaces(self):
        sectors = self.draft.allocations[0]["sectors"]
        self.assertEqual([s["flight_number"] for s in sectors], ["AF225", "AF356"])
        self.assertEqual(sectors[0]["departure_at"], "2023-12-27T01:05")
        self.assertEqual(sectors[0]["rbd"], "U")

    def test_fare_matches_the_printed_totals_without_warning(self):
        self.assertEqual(sum(c["amount_per_pax"] for c in self.draft.fare_components), 91256)
        fare_warnings = [w for w in self.draft.warnings if w["field"] == "fare_components"]
        self.assertEqual(fare_warnings, [])

    def test_deposits_are_recognised_as_percentages_of_the_net_fare(self):
        first, second, final = self.draft.payment_schedule
        self.assertEqual((first["pct"], first["pct_basis"]), (5.0, "NET_FARE"))
        self.assertEqual((second["pct"], second["pct_basis"]), (25.0, "NET_FARE"))
        self.assertIsNone(final["pct"])
        self.assertEqual(final["due_date"], "2023-12-19")

    def test_payment_dates_are_not_duplicated_as_deadlines(self):
        kinds = [d["deadline_type"] for d in self.draft.deadlines]
        self.assertNotIn("FINAL_PAYMENT", kinds)
        self.assertIn("NAME_LIST", kinds)
        self.assertIn("TICKETING", kinds)
        # The option date on the header becomes a deadline of its own.
        self.assertIn("OPTION_EXPIRY", kinds)

    def test_printed_deadlines_that_agree_with_their_offsets_raise_nothing(self):
        self.assertFalse([w for w in self.draft.warnings if (w["field"] or "").startswith("deadlines")])

    def test_all_eight_terms_survive(self):
        self.assertEqual(len(self.draft.terms), 8)
        self.assertFalse([w for w in self.draft.warnings if "overlap" in w["message"]])

    def test_an_old_contract_is_flagged(self):
        draft = extraction.normalize(AF_RAW, today=date(2026, 9, 24))
        self.assertTrue(any("in the past" in w["message"] for w in draft.warnings))

    def test_evidence_paths_use_the_forms_names(self):
        self.assertIn("allocations[0].sectors[0].flight_number", self.draft.evidence)
        self.assertEqual(self.draft.evidence["header.contract_number"]["page"], 2)

    def test_reviewer_notes_come_through_as_info(self):
        self.assertTrue(any(w["level"] == "info" and "handwritten" in w["message"] for w in self.draft.warnings))


class AirIndiaRead(unittest.TestCase):
    def setUp(self):
        self.draft = extraction.normalize(AI_RAW, today=date(2025, 4, 1))

    def test_codes_and_cabin_are_normalised(self):
        h = self.draft.header
        self.assertEqual(h["airline_code"], "AI")
        self.assertEqual(h["cabin"], "ECONOMY")
        self.assertEqual(h["currency"], "INR")
        self.assertEqual(h["materialization_floor_pct"], 80)
        self.assertEqual(h["contract_type"], "SIT")

    def test_departure_date_comes_from_the_first_leg(self):
        dep = self.draft.allocations[0]
        self.assertEqual(dep["departure_date"], "2025-04-30")
        self.assertEqual(dep["sectors"][0]["origin"], "DEL")
        self.assertEqual(dep["sectors"][0]["flight_number"], "AI495")
        self.assertEqual(dep["sectors"][1]["direction"], "INBOUND")
        # A leg without its own carrier takes the contract's.
        self.assertEqual(dep["sectors"][1]["airline_code"], "AI")

    def test_a_missing_fare_is_a_warning_not_a_zero(self):
        self.assertEqual(self.draft.fare_components, [])
        self.assertTrue(any(w["field"] == "fare_components" for w in self.draft.warnings))

    def test_no_show_keeps_its_hours(self):
        (no_show,) = [d for d in self.draft.deadlines if d["deadline_type"] == "NO_SHOW_CUTOFF"]
        self.assertEqual(no_show["offset_hours"], 24)

    def test_an_invented_rule_type_is_dropped(self):
        self.assertEqual(len(self.draft.terms), 6)
        self.assertNotIn("SOMETHING_ELSE", {t["rule_type"] for t in self.draft.terms})


class Checks(unittest.TestCase):
    def test_components_that_do_not_add_up_are_flagged(self):
        raw = dict(AF_RAW, fare_totals={"per_pax_total": 99999, "group_total": None,
                                        "group_total_excluding_taxes": None})
        draft = extraction.normalize(raw, today=TODAY)
        self.assertTrue(any("99,999.00" in w["message"] for w in draft.warnings))

    def test_a_stated_date_that_disagrees_with_its_offset_is_flagged(self):
        raw = dict(AF_RAW, deadlines=[{"deadline_type": "NAME_LIST", "offset_days": 30, "offset_hours": None,
                                       "stated_date": "2023-11-20", "action_required": None}])
        draft = extraction.normalize(raw, today=TODAY)
        self.assertTrue(any("printed date is used" in w["message"] for w in draft.warnings))

    def test_overlapping_cancellation_bands_are_flagged(self):
        raw = dict(AF_RAW, terms=[_term(days_before_max=120, days_before_min=90, charge_value=10),
                                  _term(days_before_max=100, days_before_min=31, charge_value=30)])
        draft = extraction.normalize(raw, today=TODAY)
        self.assertTrue(any("overlap" in w["message"] for w in draft.warnings))

    def test_a_series_pattern_expands_into_dated_departures(self):
        template = {"departure_date": "2025-11-04", "requested_pax": 20, "sectors": [
            {"origin": "DEL", "destination": "DXB", "departure_at": "2025-11-04T10:00",
             "arrival_at": "2025-11-04T12:30"}]}
        pattern = {"weekdays": ["TUE", "SAT"], "date_from": "2025-11-01", "date_to": "2025-11-15",
                   "seats_per_departure": 20}
        out = extraction.expand_series(pattern, template)
        self.assertEqual([d["departure_date"] for d in out],
                         ["2025-11-01", "2025-11-04", "2025-11-08", "2025-11-11", "2025-11-15"])
        self.assertEqual(out[2]["sectors"][0]["departure_at"], "2025-11-08T10:00")

    def test_strict_schema_lists_every_property_as_required(self):
        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "object" or node.get("type") == ["object", "null"]:
                    self.assertFalse(node.get("additionalProperties", True))
                    self.assertEqual(sorted(node["required"]), sorted(node["properties"]))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(extraction.SCHEMA["schema"])


def _terms(raw_terms):
    return [SimpleNamespace(allocation_id=None, **t) for t in raw_terms]


def _components(raw):
    return [SimpleNamespace(
        component_code=c["component_code"], amount_per_pax=Decimal(str(c["amount_per_pax"])),
        is_guaranteed_until_ticketing=c["is_guaranteed_until_ticketing"],
        is_refundable_on_noshow=c["is_refundable_on_noshow"],
    ) for c in raw]


class AirFranceExposure(unittest.TestCase):
    """What cancelling the whole Air France group costs, depending on the day."""

    def setUp(self):
        self.terms = _terms(AF_RAW["terms"])
        self.components = _components(AF_RAW["fare_components"])

    def exposure(self, today, **kw):
        return penalties.cancellation_exposure(
            self.terms, self.components, departure_date=date(2023, 12, 27), today=today, seats=12, **kw)

    def test_at_d_minus_110_the_fifteen_percent_band_applies(self):
        e = self.exposure(TODAY)
        self.assertEqual(e.days_before, 110)
        self.assertEqual(e.per_pax, Decimal("9690.00"))
        self.assertEqual(e.amount, Decimal("116280.00"))
        # The band ends 101 days out; the day after, 30%.
        self.assertEqual(e.holds_until, date(2023, 9, 17))
        self.assertIn("30%", e.next_description)
        self.assertEqual(e.next_per_pax, Decimal("19380.00"))

    def test_far_out_it_costs_exactly_the_first_deposit(self):
        # 5% of 775,200 is 38,760 — the advance deposit on the same agreement.
        self.assertEqual(self.exposure(date(2023, 6, 1)).amount, Decimal("38760.00"))

    def test_inside_thirty_days_it_is_the_whole_net_fare(self):
        self.assertEqual(self.exposure(date(2023, 12, 10)).amount, Decimal("775200.00"))

    def test_after_ticketing_nothing_comes_back(self):
        e = self.exposure(date(2023, 12, 22), ticketed=True)
        self.assertEqual(e.per_pax, Decimal("91256"))

    def test_the_band_edges_become_three_penalty_steps(self):
        steps = penalties.penalty_step_specs(self.terms)
        self.assertEqual([s.offset_days for s in steps], [121, 101, 31])

    def test_a_contract_without_cancellation_terms_is_unknown(self):
        self.assertIsNone(penalties.cancellation_exposure(
            [], self.components, departure_date=date(2023, 12, 27), today=TODAY, seats=12))


class AirIndiaExposure(unittest.TestCase):
    def test_group_cancellation_forfeits_the_deposit_actually_paid(self):
        terms = _terms(AI_RAW["terms"][:1])
        e = penalties.cancellation_exposure(
            terms, [], departure_date=date(2025, 4, 30), today=date(2025, 4, 1),
            seats=60, deposit_paid=Decimal("120000"))
        self.assertEqual(e.amount, Decimal("120000.00"))

    def test_per_cabin_grid_describes_itself(self):
        (econ,) = [t for t in _terms(AI_RAW["terms"]) if t.cabin == "ECONOMY"]
        text = penalties.describe(econ)
        self.assertIn("4,000 per passenger", text)
        self.assertIn("GST", text)


class Reminders(unittest.TestCase):
    def test_stages(self):
        self.assertIsNone(reminders.stage(10))
        self.assertEqual(reminders.stage(7), "week")
        self.assertEqual(reminders.stage(3), "soon")
        self.assertEqual(reminders.stage(0), "today")
        self.assertEqual(reminders.stage(-2), "overdue")
        # An old contract's deadlines do not flood the bell.
        self.assertIsNone(reminders.stage(-400))

    def test_penalty_step_wording_is_about_the_day_after(self):
        contract = SimpleNamespace(id=1, contract_number="A 5854811-1/1", group_name="Direct Canada DEC",
                                   airline_code="AF", currency="INR")
        deadline = SimpleNamespace(deadline_type="PENALTY_STEP", action_required=None,
                                   effective_date=date(2023, 9, 17))
        title, _ = reminders.message(contract, deadline, 2)
        self.assertEqual(title, "Cancellation charge rises in 3 days — A 5854811-1/1")


class PenaltyStepIdentity(unittest.TestCase):
    def test_several_steps_on_one_departure_are_different_deadlines(self):
        self.assertNotEqual(dl.identity("PENALTY_STEP", 5, 121), dl.identity("PENALTY_STEP", 5, 101))

    def test_other_types_stay_one_per_departure(self):
        self.assertEqual(dl.identity("NAME_LIST", 5, 30), dl.identity("NAME_LIST", 5, 45))


if __name__ == "__main__":
    unittest.main()
