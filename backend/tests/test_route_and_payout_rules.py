"""Inclusion / exclusion rules against a statement's Sector — no DB, no network.

Pinned against the October 2026 TripJack and Brightsun statements' own sectors:

  * a round trip's destination is its turnaround, not its last airport (DEL/ALA/DEL → ALA);
  * Continents / Country Group / City need the WHOLE route inside; origin / destination
    fields read one end; "vice versa" lets them match either way round;
  * a field the ticket cannot answer (no sector, an airport not in the Airport Master, no
    travel date) is UNDECIDED — never silently passed;
  * a rule blocks only its own incentive, and a deal whose rules leave the ticket out gives
    way to the next deal that covers it.

Run:  python -m unittest discover backend/tests
"""

import asyncio
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import commission_core as core  # noqa: E402
from app.services.commission.calc_row import CalcRow  # noqa: E402
from app.services.commission.runner import CommissionRunner  # noqa: E402
from app.services.deal_matching import (  # noqa: E402
    DealMatchResult, _class_matches_groups, _normalize_class_type,
)
from app.services.exclusion_evaluator import (  # noqa: E402
    RuleFacts, _to_date, evaluate_rule,
)
from app.services.route_resolution import (  # noqa: E402
    AirportView, build_route, parse_points,
)


def apt(code, country, continent, group, city):
    return AirportView(iata_code=code, country=country, continent=continent,
                       categorization=group, city_airport_name=city)


# As the platform's Airport Master holds them (Delhi's name is "Delhi - Indira Gandhi …").
MASTER = {a.iata_code: a for a in (
    apt("DEL", "India", "Asia", "MEAI/SAARC/APAC", "Delhi - Indira Gandhi International Airport"),
    apt("BOM", "India", "Asia", "MEAI/SAARC/APAC", "Mumbai"),
    apt("GOI", "India", "Asia", "MEAI/SAARC/APAC", "Goa"),
    apt("ALA", "Kazakhstan", "Asia", "MEAI", "Almaty"),
    apt("TAS", "Uzbekistan", "Asia", "MEAI", "Tashkent"),
    apt("KUL", "Malaysia", "Asia", "MEAI/APAC", "Kuala Lumpur"),
    apt("AKL", "New Zealand", "Oceania", "APAC", "Auckland"),
    apt("BKK", "Thailand", "Asia", "APAC", "Bangkok"),
    apt("LHR", "United Kingdom", "Europe", "EUROPEAN NATIONS", "London Heathrow"),
    apt("ELS", "South Africa", "Africa", "OTHER", "East London"),
    apt("YYZ", "Canada", "North America", "NAM", "Toronto"),
    apt("FRA", "Germany", "Europe", "EUROPEAN NATIONS", "Frankfurt"),
    apt("DAC", "Bangladesh", "Asia", "SAARC", "Dhaka"),
    apt("ATQ", "India", "Asia", "MEAI/SAARC/APAC", "Amritsar"),
)}


def route(sector, master=MASTER):
    points = parse_points(sector)
    return build_route(points, {p: master.get(p) for p in points}) if points else None


# Japan Airlines' rows in the Airline Class Master (E is Premium Economy there).
CABINS = {"H": "Economy", "N": "Economy", "S": "Economy", "Q": "Economy", "G": "Economy",
          "E": "Premium Economy", "C": "Business"}


def facts(sector="DEL/ALA/DEL", **kw):
    bc = kw.get("booking_class")
    if bc and "class_cabins" not in kw:
        codes = [c.strip().upper() for c in bc.replace(" ", "").split("/") if c.strip()]
        kw["class_cabins"] = {c: CABINS[c] for c in dict.fromkeys(codes)}
    return RuleFacts(sector=sector, route=route(sector), **kw)


class TestParsePoints(unittest.TestCase):
    def test_real_sectors(self):
        self.assertEqual(parse_points("DEL/ALA/DEL"), ("DEL", "ALA", "DEL"))
        # Brightsun pads after the slash.
        self.assertEqual(parse_points("KEF/FRA/ MXP"), ("KEF", "FRA", "MXP"))
        self.assertEqual(parse_points("del-bom"), ("DEL", "BOM"))

    def test_not_a_route(self):
        # "EMD" is an EMD line — and also Emerald, Australia. One token is never a route.
        for cell in ("EMD", "", None, "DEL/12", "DELHI/BOM"):
            self.assertIsNone(parse_points(cell), cell)

    def test_repeated_point_is_one_stop(self):
        self.assertEqual(parse_points("DEL/DEL/BOM"), ("DEL", "BOM"))


class TestDestination(unittest.TestCase):
    def test_round_trip_turnaround(self):
        r = route("DEL/ALA/DEL")
        self.assertEqual((r.origin, r.destination, r.round_trip), ("DEL", "ALA", True))
        self.assertEqual(route("BOM/ALA/TAS/ALA/BOM").destination, "TAS")

    def test_one_way_goes_to_the_last_airport(self):
        r = route("DEL/KUL/AKL")
        self.assertEqual((r.destination, r.round_trip), ("AKL", False))

    def test_back_home_through_another_airport(self):
        # Mumbai out, Delhi back — still a return to India, turning round in Almaty.
        r = route("BOM/ALA/DEL")
        self.assertEqual((r.destination, r.round_trip), ("ALA", True))

    def test_domestic_multi_leg_is_one_way(self):
        self.assertEqual(route("DEL/BOM/GOI").destination, "GOI")

    def test_missing_airports_are_reported(self):
        self.assertEqual(route("DEL/XXX/DEL").missing, ("XXX",))


class TestDirectionalFields(unittest.TestCase):
    def test_destination_of_a_round_trip(self):
        # The old engine judged DEL here, so an inclusion for Kazakhstan left this out.
        v = evaluate_rule({"destCountry": ["Kazakhstan"]}, facts(), inclusion=True)
        self.assertIs(v.applies, True)
        self.assertFalse(v.blocks)

    def test_origin_and_destination_fields(self):
        f = facts("DEL/KUL/AKL")
        self.assertIs(evaluate_rule({"originAirport": ["DEL"], "destAirport": ["AKL"]},
                                    f, inclusion=True).applies, True)
        self.assertIs(evaluate_rule({"destContinents": ["Oceania"]}, f, inclusion=True).applies, True)
        # KUL is a connection, not where the passenger is going.
        self.assertIs(evaluate_rule({"destCountry": ["Malaysia"]}, f, inclusion=True).applies, False)
        self.assertIs(evaluate_rule({"originCountryGroup": ["SAARC"]}, f, inclusion=True).applies, True)
        self.assertIs(evaluate_rule({"destCountryGroup": ["APAC"]}, f, inclusion=True).applies, True)

    def test_vice_versa(self):
        rule = {"originCountry": ["United Kingdom"], "destCountry": ["India"]}
        f = facts("DEL/LHR")
        self.assertIs(evaluate_rule(rule, f, inclusion=True).applies, False)
        v = evaluate_rule(rule, f, inclusion=True, vice_versa=True)
        self.assertIs(v.applies, True)
        self.assertTrue(v.reversed_route)
        # The flag may also arrive as a condition (the repository's rules editor).
        self.assertIs(evaluate_rule({**rule, "viceVersa": "true"}, f, inclusion=True).applies, True)


class TestWholeRouteFields(unittest.TestCase):
    def test_exclusion_asia_takes_only_routes_inside_asia(self):
        rule = {"continents": ["Asia"]}
        self.assertTrue(evaluate_rule(rule, facts("DEL/BKK"), inclusion=False).blocks)
        self.assertTrue(evaluate_rule(rule, facts("DEL/ALA/DEL"), inclusion=False).blocks)
        self.assertFalse(evaluate_rule(rule, facts("DEL/LHR"), inclusion=False).blocks)

    def test_inclusion_needs_both_ends_inside(self):
        self.assertTrue(evaluate_rule({"continents": ["Europe"]}, facts("DEL/LHR"), inclusion=True).blocks)
        self.assertFalse(evaluate_rule({"continents": ["Asia", "Europe"]}, facts("DEL/LHR"),
                                       inclusion=True).blocks)

    def test_country_group_reads_combined_categorization(self):
        # DEL is MEAI/SAARC/APAC, ALA is MEAI — both MEAI, not both SAARC.
        self.assertIs(evaluate_rule({"countryGroup": ["MEAI"]}, facts(), inclusion=True).applies, True)
        self.assertIs(evaluate_rule({"countryGroup": ["SAARC"]}, facts(), inclusion=True).applies, False)

    def test_city_is_a_whole_word(self):
        f = facts("DEL/LHR")
        self.assertIs(evaluate_rule({"city": ["Delhi", "London"]}, f, inclusion=True).applies, True)
        # "London" must not reach East London, South Africa.
        self.assertIs(evaluate_rule({"city": ["Delhi", "London"]}, facts("DEL/ELS"),
                                    inclusion=True).applies, False)

    def test_city_saved_as_the_full_master_name(self):
        # The batch page used to save the master's whole CITY_AIRPORT_NAME.
        rule = {"city": ["Delhi - Indira Gandhi International Airport", "London Heathrow"]}
        self.assertIs(evaluate_rule(rule, facts("DEL/LHR"), inclusion=True).applies, True)


class TestUndecided(unittest.TestCase):
    def test_airport_not_in_master(self):
        v = evaluate_rule({"destCountry": ["Kazakhstan"]}, facts("DEL/XXX/DEL"), inclusion=True)
        self.assertTrue(v.undecided)
        self.assertFalse(v.blocks)
        self.assertEqual(v.missing, {"airport"})

    def test_no_sector_and_unreadable_sector(self):
        for sector in (None, "EMD"):
            v = evaluate_rule({"destCountry": ["Kazakhstan"]}, facts(sector), inclusion=False)
            self.assertTrue(v.undecided, sector)
            self.assertEqual(v.missing, {"sector"})

    def test_a_definite_miss_outranks_an_unknown(self):
        # Class Q does not match an S ticket, so the exclusion cannot bite whatever the
        # unknown airport turns out to be.
        f = facts("DEL/XXX/DEL", booking_class="S", cabin_groups={"Economy"})
        v = evaluate_rule({"destCountry": ["Kazakhstan"], "class": ["Q"]}, f, inclusion=False)
        self.assertIs(v.applies, False)
        self.assertFalse(v.undecided)


class TestAllFieldsMustMatch(unittest.TestCase):
    def test_exclusion_needs_every_field(self):
        f = facts(booking_class="S", cabin_groups={"Economy"})
        self.assertTrue(evaluate_rule({"destCountry": ["Kazakhstan"], "class": ["S"]},
                                      f, inclusion=False).blocks)
        self.assertFalse(evaluate_rule({"destCountry": ["Kazakhstan"], "class": ["Q"]},
                                       f, inclusion=False).blocks)

    def test_empty_rule_constrains_nothing(self):
        for inclusion in (True, False):
            v = evaluate_rule({"dateExclusionTicket": "true"}, facts(), inclusion=inclusion)
            self.assertTrue(v.empty)
            self.assertFalse(v.blocks or v.undecided)


class TestClassRuleIsStrict(unittest.TestCase):
    """User's rule, 2026-10-27: inclusion needs EVERY segment listed, exclusion ANY."""

    def test_inclusion_needs_every_segment(self):
        f = facts(booking_class="H/ H/ E/ N")
        self.assertIs(evaluate_rule({"class": ["E"]}, f, inclusion=True).applies, False)
        self.assertIs(evaluate_rule({"class": ["H", "E", "N"]}, f, inclusion=True).applies, True)

    def test_exclusion_bites_on_any_segment(self):
        f = facts(booking_class="H/ H/ E/ N")
        self.assertTrue(evaluate_rule({"class": ["E"]}, f, inclusion=False).blocks)
        self.assertFalse(evaluate_rule({"class": ["Q"]}, f, inclusion=False).blocks)

    def test_cabin_names_still_work_through_the_master(self):
        f = facts(booking_class="E")
        self.assertIs(evaluate_rule({"class": ["Premium Economy"]}, f, inclusion=True).applies, True)
        self.assertIs(evaluate_rule({"class": ["Economy"]}, f, inclusion=True).applies, False)

    def test_no_class_is_undecided(self):
        v = evaluate_rule({"class": ["S"]}, facts(), inclusion=False)
        self.assertEqual(v.missing, {"class"})


class TestFareTypeCategory(unittest.TestCase):
    def test_normal_is_every_class(self):
        for bc in ("S", "G/ G", None):
            self.assertIs(evaluate_rule({"fareTypeCategory": ["Normal"]}, facts(booking_class=bc),
                                        inclusion=True).applies, True, bc)

    def test_group_is_g_class(self):
        self.assertIs(evaluate_rule({"fareTypeCategory": ["Group"]}, facts(booking_class="G/ G"),
                                    inclusion=True).applies, True)
        self.assertIs(evaluate_rule({"fareTypeCategory": ["Group"]}, facts(booking_class="S"),
                                    inclusion=True).applies, False)
        # Strict like Class: one G segment excludes, but does not make an all-G inclusion.
        self.assertTrue(evaluate_rule({"fareTypeCategory": ["Group"]}, facts(booking_class="G/ S"),
                                      inclusion=False).blocks)
        self.assertIs(evaluate_rule({"fareTypeCategory": ["Group"]}, facts(booking_class="G/ S"),
                                    inclusion=True).applies, False)

    def test_corporate_needs_a_listed_tour_code(self):
        rule = {"fareTypeCategory": ["Corporate"], "tourCode": ["INFOSYS24", "TCS2026"]}
        self.assertIs(evaluate_rule(rule, facts(tour_code="infosys24"), inclusion=True).applies, True)
        self.assertIs(evaluate_rule(rule, facts(tour_code="ABC123"), inclusion=True).applies, False)
        self.assertIs(evaluate_rule(rule, facts(), inclusion=True).applies, False)   # none printed
        # Tour Code is Corporate's parameter here, not a second condition.
        v = evaluate_rule(rule, facts(tour_code="TCS2026"), inclusion=True)
        self.assertEqual([s.field for s in v.steps], ["fareTypeCategory"])

    def test_excursion_and_tour_alike(self):
        for fc in ("Excursion", "Tour"):
            rule = {"fareTypeCategory": [fc], "tourCode": ["XTOUR"]}
            self.assertTrue(evaluate_rule(rule, facts(tour_code="XTOUR"), inclusion=False).blocks)

    def test_statement_without_tour_codes_is_undecided(self):
        rule = {"fareTypeCategory": ["Tour"], "tourCode": ["XTOUR"]}
        v = evaluate_rule(rule, facts(tour_code_known=False), inclusion=False)
        self.assertTrue(v.undecided)
        self.assertEqual(v.missing, {"tour_code"})

    def test_any_picked_value_may_match(self):
        rule = {"fareTypeCategory": ["Group", "Corporate"], "tourCode": ["INFOSYS24"]}
        self.assertIs(evaluate_rule(rule, facts(booking_class="G", tour_code="X"),
                                    inclusion=True).applies, True)


class TestTourCodeAlone(unittest.TestCase):
    def test_listed_code(self):
        self.assertTrue(evaluate_rule({"tourCode": ["ABC"]}, facts(tour_code="abc"),
                                      inclusion=False).blocks)
        self.assertFalse(evaluate_rule({"tourCode": ["ABC"]}, facts(), inclusion=False).blocks)

    def test_unknown_when_not_printed(self):
        v = evaluate_rule({"tourCode": ["ABC"]}, facts(tour_code_known=False), inclusion=True)
        self.assertEqual(v.missing, {"tour_code"})


class TestSoto(unittest.TestCase):
    """SOTO = the journey starts outside India; only the two ends count (user, 2026-10-27)."""

    def excluded(self, option, sector):
        return evaluate_rule({"soto": [option]}, facts(sector), inclusion=False).blocks

    def test_soto_all_is_any_journey_starting_abroad(self):
        self.assertFalse(self.excluded("SOTO All", "DEL/ALA/DEL"))
        self.assertTrue(self.excluded("SOTO All", "ALA/DEL"))
        self.assertTrue(self.excluded("SOTO All", "KUL/DAC"))

    def test_within_india_ends_in_india(self):
        self.assertTrue(self.excluded("SOTO within India", "ALA/DEL"))
        self.assertFalse(self.excluded("SOTO within India", "KUL/DAC"))
        self.assertFalse(self.excluded("SOTO within India", "DEL/ALA/DEL"))

    def test_outside_india_ends_outside_india(self):
        self.assertTrue(self.excluded("SOTO outside India", "KUL/DAC"))
        # A connection in Delhi does not make it Indian travel — the ends decide.
        self.assertTrue(self.excluded("SOTO outside India", "KUL/DEL/LHR"))
        self.assertFalse(self.excluded("SOTO outside India", "ALA/DEL"))
        # Amritsar is India: this Brightsun journey is not SOTO at all.
        self.assertFalse(self.excluded("SOTO outside India", "ATQ/DEL/LHR/YYZ"))

    def test_within_plus_outside_is_all(self):
        for sector in ("ALA/DEL", "KUL/DAC", "DEL/ALA/DEL", "KUL/DEL/LHR"):
            both = self.excluded("SOTO within India", sector) or self.excluded("SOTO outside India", sector)
            self.assertEqual(both, self.excluded("SOTO All", sector), sector)

    def test_unknown_origin_is_undecided(self):
        v = evaluate_rule({"soto": ["SOTO All"]}, facts("XXX/DEL"), inclusion=False)
        self.assertEqual(v.missing, {"airport"})


class TestTriggerRulesCountTowardTarget(unittest.TestCase):
    """Trigger rules decide what counts toward a slab target, not what is paid."""

    def test_counting(self):
        from app.services.deal_matching import _counts_toward_target
        rules = [(False, {"soto": ["SOTO All"]}, False)]          # Exclusion For Trigger
        self.assertEqual(_counts_toward_target(facts("DEL/ALA/DEL"), rules), "counted")
        self.assertEqual(_counts_toward_target(facts("ALA/DEL"), rules), "left_out")
        self.assertEqual(_counts_toward_target(facts("XXX/DEL"), rules), "unknown")
        incl = [(True, {"destCountry": ["Kazakhstan"]}, False)]   # Inclusion For Trigger
        self.assertEqual(_counts_toward_target(facts("DEL/ALA/DEL"), incl), "counted")
        self.assertEqual(_counts_toward_target(facts("DEL/LHR"), incl), "left_out")


class TestDomesticCountryRemoved(unittest.TestCase):
    def test_no_longer_judged(self):
        v = evaluate_rule({"domesticCountry": ["India"]}, facts("DEL/BOM"), inclusion=False)
        self.assertTrue(v.empty)
        self.assertFalse(v.blocks)


class TestDates(unittest.TestCase):
    def test_iso_is_not_read_day_first(self):
        # dateutil(dayfirst=True) reads this as 10 May.
        self.assertEqual(_to_date("2026-10-05"), date(2026, 10, 5))
        self.assertEqual(_to_date("05/10/2026"), date(2026, 10, 5))

    def test_travel_date_by_default(self):
        f = facts(issue_date=date(2026, 9, 28), travel_date=date(2026, 10, 5))
        rule = {"validFrom": "2026-10-01", "validTo": "2026-10-15"}
        self.assertIs(evaluate_rule(rule, f, inclusion=True).applies, True)
        # Ticket Date picked → the issue date (28 Sep) is tested instead.
        self.assertIs(evaluate_rule({**rule, "dateExclusionTicket": "true"}, f,
                                    inclusion=True).applies, False)

    def test_missing_travel_date_is_undecided(self):
        v = evaluate_rule({"validFrom": "2026-10-01"}, facts(issue_date=date(2026, 10, 1)),
                          inclusion=True)
        self.assertEqual(v.missing, {"travel_date"})


class TestClassMapping(unittest.TestCase):
    def test_premium_economy_is_its_own_cabin(self):
        self.assertEqual(_normalize_class_type("PREMIUM ECONOMY CLASS"), "Premium Economy")
        self.assertEqual(_normalize_class_type("ECONOMY CLASS"), "Economy")

    def test_deal_class_premium_covers_premium_economy_and_first(self):
        self.assertTrue(_class_matches_groups({"Premium Economy"}, "Premium"))
        self.assertTrue(_class_matches_groups({"First"}, "Premium"))
        self.assertFalse(_class_matches_groups({"Economy"}, "Premium"))
        self.assertFalse(_class_matches_groups({"Premium Economy"}, "Economy"))
        self.assertTrue(_class_matches_groups({"Business"}, "All"))


class FakeDb:
    """judge_payout_rules reads a deal's rules through a per-session cache — prefilled."""
    def __init__(self, rules_by_deal):
        self.info = {"_payout_rule_cache": rules_by_deal}


def ctx(**kw):
    base = dict(source_row_id=1, airline_name="AIR ASTANA", issue_date=date(2026, 10, 1),
                travel_date=date(2026, 10, 5), sector="DEL/ALA/DEL", booking_class="S",
                fare_amount=10000.0, statement_type="B2B")
    base.update(kw)
    return CalcRow(**base)


class TestPayoutRulesPerIncentive(unittest.TestCase):
    def test_exclusion_takes_out_only_its_incentive(self):
        db = FakeDb({7: [("PLB", False, {"destCountry": ["Kazakhstan"]}, False)]})
        out = asyncio.run(core.judge_payout_rules(
            db, 7, {"PLB": 500.0, "Super PLB": 100.0}, ctx(), facts()))
        self.assertEqual(out.kept, {"Super PLB": 100.0})
        self.assertIn("PLB", out.blocked)

    def test_undecided_rule_is_kept_but_unconfirmed(self):
        db = FakeDb({7: [("PLB", True, {"destCountry": ["Kazakhstan"]}, False)]})
        out = asyncio.run(core.judge_payout_rules(
            db, 7, {"PLB": 500.0}, ctx(sector="DEL/XXX/DEL"), facts("DEL/XXX/DEL")))
        self.assertEqual(out.kept, {"PLB": 500.0})
        self.assertEqual(out.unconfirmed, {"airport"})
        self.assertTrue(out.notes and "XXX" in out.notes[0])

    def test_tour_code_reason_says_map_the_column(self):
        text = core.needs_data_reason("B2B-000007", ["tour_code"], remedy="Ask the vendor.")
        self.assertIn("Tour Code column", text)

    def test_airport_reason_names_the_master(self):
        text = core.needs_data_reason("B2B-000007", ["airport"], remedy="Ask the vendor.")
        self.assertIn("Airport Master", text)
        self.assertNotIn("Ask the vendor", text)


def deal(deal_id, amount, **kw):
    return DealMatchResult(deal_id=deal_id, deal_type="b2b", deal_name="AIR ASTANA",
                           deal_no=f"B2B-{deal_id:06d}", calculated_incentive=amount,
                           incentive_breakdown={"PLB": amount}, **kw)


class TestNextDealWhenRulesSayNo(unittest.TestCase):
    def run_row(self, rules, matches, row=None):
        runner = CommissionRunner(adapter=object())
        with mock.patch("app.services.commission.runner.DealMatchingService.find_all_deals",
                        new=mock.AsyncMock(return_value=matches)), \
             mock.patch("app.services.commission.runner.load_facts",
                        new=mock.AsyncMock(return_value=facts())):
            return asyncio.run(runner.calculate_row(FakeDb(rules), row or ctx(), 1, 1))

    def test_inclusion_miss_falls_through_to_the_next_deal(self):
        rules = {1: [("PLB", True, {"destCountry": ["Uzbekistan"]}, False)], 2: []}
        res = self.run_row(rules, [deal(1, 800.0), deal(2, 300.0)])
        self.assertEqual((res.status, res.deal_id, res.incentive), ("calculated", 2, 300.0))

    def test_every_deal_ruled_out_is_excluded_on_the_best(self):
        rules = {1: [("PLB", True, {"destCountry": ["Uzbekistan"]}, False)],
                 2: [("PLB", False, {"destCountry": ["Kazakhstan"]}, False)]}
        res = self.run_row(rules, [deal(1, 800.0), deal(2, 300.0)])
        self.assertEqual((res.status, res.deal_id, res.incentive), ("excluded", 1, 0))

    def test_undecided_best_deal_withholds(self):
        rules = {1: [("PLB", True, {"originCountry": ["India"], "validFrom": "2026-10-01"}, False)]}
        res = self.run_row(rules, [deal(1, 800.0)], ctx(travel_date=None))
        # facts() carries no travel date either — the rule cannot be judged.
        self.assertEqual(res.status, "needs_data")


if __name__ == "__main__":
    unittest.main()
