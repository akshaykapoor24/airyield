"""Series / SIT / MICE / Group — the arithmetic, checked against two real contracts.

The fixtures below are not invented. They are the Air India group agreement GRP123003
(DELATQDEL, 60 pax, DEL-ATQ-DEL, 30 Apr / 01 May 2025) and the Air France/KLM Group Sales
Agreement A 5854811-1/1 (group reference L64E9A, "Direct Canada DEC", 12 passengers,
DEL-CDG-YYZ on 27 December 2023). Every figure asserted here is printed on one of those
two documents, which is the point: the module exists to make those documents computable,
so the documents are the test.

No DB, no network.

Run:  ..\\venv\\Scripts\\python.exe -m unittest tests.test_series_contracts -v   (from backend/)
"""
import os
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.series import bases, deadlines as dl, rollups  # noqa: E402
from app.services.series.matching import norm_pnr  # noqa: E402


def component(code, amount, *, guaranteed=False, refundable=False):
    return SimpleNamespace(
        component_code=code,
        amount_per_pax=Decimal(str(amount)),
        is_guaranteed_until_ticketing=guaranteed,
        is_refundable_on_noshow=refundable,
    )


# Air France/KLM A 5854811-1/1, "DETAILS OF YOUR RESERVATION", per passenger.
# YR-F and YR-I/YQ are "Guaranteed until date of ticketing or until contract is
# reissued"; taxes are "subject to change at date of ticketing".
AF_COMPONENTS = [
    component("BASE", "64600.00"),
    component("YR_F", "249.00", guaranteed=True),
    component("YR_I", "19050.00", guaranteed=True),
    component("TAX_STATUTORY", "7357.00", refundable=True),
]
AF_PAX = 12
AF_DEPARTURE = date(2023, 12, 27)

# Air India freezes "AI retention (Base +YQ)" and lets statutory taxes float. The contract
# quotes no fare, so these are illustrative amounts — what is being asserted is which
# components the basis adds, not what they are worth.
AI_COMPONENTS = [
    component("BASE", "9000.00", guaranteed=True),
    component("YQ", "1200.00", guaranteed=True),
    component("TAX_STATUTORY", "850.00", refundable=True),
]


class AirFranceFare(unittest.TestCase):
    """The four contracted lines, and the totals the agreement prints for them."""

    def test_the_four_components_add_to_the_printed_per_pax_fare(self):
        self.assertEqual(bases.fare_per_pax(AF_COMPONENTS), Decimal("91256.00"))

    def test_twelve_passengers_reach_the_printed_grand_total(self):
        # "Total amount including carrier-imposed international surcharge and taxes:
        #  1 095 072.00 INR"
        total = rollups.contract_cost(bases.fare_per_pax(AF_COMPONENTS), AF_PAX)
        self.assertEqual(total, Decimal("1095072.00"))

    def test_each_printed_subtotal_is_reproduced(self):
        per_code = bases.split_by_code(AF_COMPONENTS)
        for code, printed in (
            ("BASE", "775200.00"),          # "Total amount excluding ... surcharge and taxes"
            ("YR_F", "2988.00"),            # "Total amount of Sustainable Fuel Contribution"
            ("YR_I", "228600.00"),          # "Total amount of carrier-imposed ... surcharge"
            ("TAX_STATUTORY", "88284.00"),  # "Total amount of taxes"
        ):
            with self.subTest(code=code):
                self.assertEqual(
                    rollups.contract_cost(per_code[code], AF_PAX), Decimal(printed)
                )

    def test_net_fare_basis_is_the_base_alone(self):
        # The deposits prove this: they price off 775 200, not off 1 095 072.
        self.assertEqual(
            bases.basis_amount(AF_COMPONENTS, bases.BASIS_NET_FARE), Decimal("64600.00")
        )

    def test_guaranteed_is_the_two_surcharges_and_not_the_tax(self):
        self.assertEqual(bases.guaranteed_total(AF_COMPONENTS), Decimal("19299.00"))
        # What a tax movement between contract and ticketing can still cost per seat.
        self.assertEqual(
            bases.exposed_to_tax_movement(AF_COMPONENTS), Decimal("71957.00")
        )


class AirFranceDeposits(unittest.TestCase):
    """The agreement's two deposits are percentages of the NET fare, not of the total.

    This is the whole reason a schedule row carries `pct_basis`. Priced against the grand
    total the same percentages would give 54,753.60 and 273,768.00, and neither is on the
    document.
    """

    def _deposit(self, pct: str) -> Decimal:
        per_pax = bases.basis_amount(AF_COMPONENTS, bases.BASIS_NET_FARE)
        total = rollups.contract_cost(per_pax, AF_PAX)
        return rollups.money(total * Decimal(pct) / Decimal(100))

    def test_first_deposit_is_five_percent_of_net_fare(self):
        # "38 760.00 INR required before 06 January 2023."
        self.assertEqual(self._deposit("5"), Decimal("38760.00"))

    def test_second_deposit_is_twenty_five_percent_of_net_fare(self):
        # "193 800.00 INR required before 18 September 2023."
        self.assertEqual(self._deposit("25"), Decimal("193800.00"))

    def test_pricing_off_the_grand_total_would_not_match_the_document(self):
        grand = rollups.contract_cost(bases.fare_per_pax(AF_COMPONENTS), AF_PAX)
        self.assertNotEqual(
            rollups.money(grand * Decimal("5") / Decimal(100)), Decimal("38760.00")
        )


class AirIndiaRetention(unittest.TestCase):
    """"Only AI retention (Base +YQ) will freeze." """

    def test_retention_is_base_plus_yq(self):
        self.assertEqual(
            bases.basis_amount(AI_COMPONENTS, bases.BASIS_AI_RETENTION),
            Decimal("10200.00"),
        )

    def test_retention_excludes_statutory_tax(self):
        self.assertLess(
            bases.basis_amount(AI_COMPONENTS, bases.BASIS_AI_RETENTION),
            bases.fare_per_pax(AI_COMPONENTS),
        )

    def test_only_statutory_taxes_come_back_on_a_no_show(self):
        # "For 'No-Show' passengers – only statutory taxes are refundable."
        self.assertEqual(bases.refundable_on_noshow(AI_COMPONENTS), Decimal("850.00"))

    def test_the_two_contracts_do_not_share_a_basis(self):
        # The point of the whole basis mechanism: one `penalty_percent` column could not
        # serve both documents.
        self.assertNotEqual(
            bases.BASIS_COMPONENTS[bases.BASIS_NET_FARE],
            bases.BASIS_COMPONENTS[bases.BASIS_AI_RETENTION],
        )

    def test_an_unknown_basis_is_zero_rather_than_an_exception(self):
        # A visibly wrong penalty costs nobody money; a 500 mid-save loses the contract.
        self.assertEqual(bases.basis_amount(AI_COMPONENTS, "NO_SUCH_BASIS"), Decimal("0"))


class Materialization(unittest.TestCase):
    """"Minimum group materialisation should be 80% of group size." """

    def test_eighty_percent_of_sixty_needs_forty_eight_seats(self):
        self.assertEqual(
            rollups.seats_needed_for_floor(60, None, Decimal("80")), 48
        )

    def test_a_partial_seat_rounds_up_because_nobody_flies_a_fifth_of_a_seat(self):
        # 80% of 59 is 47.2.
        self.assertEqual(
            rollups.seats_needed_for_floor(59, None, Decimal("80")), 48
        )

    def test_the_denominator_is_the_size_firmed_at_deposit(self):
        # "The group size would be firmed up from the day of the advance deposit ... and
        #  the same would be treated as sacrosanct viz 100% of the group size."
        self.assertEqual(rollups.materialization_denominator(50, 60), 50)

    def test_the_requested_size_is_used_until_a_deposit_firms_one(self):
        self.assertEqual(rollups.materialization_denominator(None, 60), 60)

    def test_forty_eight_of_sixty_meets_the_floor_exactly(self):
        pct = rollups.materialization_pct(48, None, 60)
        self.assertEqual(pct, Decimal("80.00"))
        self.assertIs(rollups.meets_materialization(pct, Decimal("80")), True)

    def test_forty_seven_of_sixty_does_not(self):
        pct = rollups.materialization_pct(47, None, 60)
        self.assertIs(rollups.meets_materialization(pct, Decimal("80")), False)

    def test_an_unsized_contract_is_unknown_and_not_zero(self):
        # Rendering "no denominator yet" as 0% would light up a below-floor warning on
        # every draft on the screen.
        self.assertIsNone(rollups.materialization_pct(0, None, None))
        self.assertIsNone(rollups.meets_materialization(None, Decimal("80")))


class PassengerTypes(unittest.TestCase):
    """Who takes a seat, and who counts toward the floor."""

    def test_a_child_counts_as_an_adult(self):
        # "One child would be counted as one adult to fulfil the minimum materialization."
        self.assertEqual(rollups.seat_flags("CHD"), (True, True))

    def test_an_infant_with_a_seat_is_treated_as_a_child(self):
        # "An infant occupying seat - is to be treated as a Child."
        self.assertEqual(rollups.seat_flags("INF_SEAT"), (True, True))

    def test_an_infant_without_a_seat_is_neither(self):
        # "An infant without a seat - ticket will be similar to normal infant ticket."
        self.assertEqual(rollups.seat_flags("INF_LAP"), (False, False))

    def test_a_lap_infant_does_not_move_the_materialization_figure(self):
        roster = ["ADT"] * 47 + ["CHD"] + ["INF_LAP"] * 5
        counting = sum(1 for p in roster if rollups.seat_flags(p)[1])
        self.assertEqual(counting, 48)
        self.assertIs(
            rollups.meets_materialization(
                rollups.materialization_pct(counting, None, 60), Decimal("80")
            ),
            True,
        )


class AirFranceDeadlines(unittest.TestCase):
    """The agreement prints the rule AND the answer. Both are checked."""

    def test_name_list_at_d_minus_30_lands_on_the_printed_date(self):
        # "no later than 30 days before departure date, which is 27 November 2023"
        built = dl.build(
            dl.DeadlineSpec(dl.TYPE_NAME_LIST, dl.ANCHOR_DEPARTURE, offset_days=30),
            departure_date=AF_DEPARTURE,
        )
        self.assertEqual(built.computed_date, date(2023, 11, 27))

    def test_ticketing_at_d_minus_8_lands_on_the_printed_date(self):
        # "no later than 8 days before departure date, which is 19 December 2023"
        built = dl.build(
            dl.DeadlineSpec(dl.TYPE_TICKETING, dl.ANCHOR_DEPARTURE, offset_days=8),
            departure_date=AF_DEPARTURE,
        )
        self.assertEqual(built.computed_date, date(2023, 12, 19))

    def test_rule_and_printed_date_agreeing_is_not_a_divergence(self):
        built = dl.build(
            dl.DeadlineSpec(
                dl.TYPE_NAME_LIST, dl.ANCHOR_DEPARTURE,
                offset_days=30, stated_date=date(2023, 11, 27),
            ),
            departure_date=AF_DEPARTURE,
        )
        self.assertFalse(built.has_divergence)
        self.assertEqual(built.effective_date, date(2023, 11, 27))

    def test_when_they_disagree_the_airlines_date_wins_and_is_flagged(self):
        # Contracts contain arithmetic errors, and the airline enforces what it printed.
        built = dl.build(
            dl.DeadlineSpec(
                dl.TYPE_NAME_LIST, dl.ANCHOR_DEPARTURE,
                offset_days=30, stated_date=date(2023, 11, 20),
            ),
            departure_date=AF_DEPARTURE,
        )
        self.assertTrue(built.has_divergence)
        self.assertEqual(built.effective_date, date(2023, 11, 20))
        self.assertEqual(built.computed_date, date(2023, 11, 27))

    def test_a_deadline_with_no_resolvable_date_is_not_written(self):
        specs = [dl.DeadlineSpec(dl.TYPE_NAME_LIST, dl.ANCHOR_DEPARTURE, offset_days=30)]
        self.assertEqual(dl.build_all(specs, departure_date=None), [])


class AirIndiaDeadlines(unittest.TestCase):

    def test_no_show_cutoff_is_hours_before_the_actual_departure_time(self):
        # "No-show is when a passenger/agent fails to cancel the booking at least D-24
        #  hours before departure." AI-495 leaves 30 Apr 2025 at 08:30, so the cut-off is
        #  08:30 on 29 April — not midnight, and not 30 April.
        built = dl.build(
            dl.DeadlineSpec(dl.TYPE_NO_SHOW_CUTOFF, dl.ANCHOR_DEPARTURE, offset_hours=24),
            departure_date=date(2025, 4, 30),
            departure_at=datetime(2025, 4, 30, 8, 30),
        )
        self.assertEqual(built.computed_date, date(2025, 4, 29))

    def test_deviation_window_is_d_minus_30(self):
        # "Deviated travel date must be within D-30 days of departure."
        built = dl.build(
            dl.DeadlineSpec(dl.TYPE_DEVIATION_CUTOFF, dl.ANCHOR_DEPARTURE, offset_days=30),
            departure_date=date(2025, 4, 30),
        )
        self.assertEqual(built.computed_date, date(2025, 3, 31))

    def test_an_hours_offset_without_a_departure_time_rounds_up_to_whole_days(self):
        built = dl.build(
            dl.DeadlineSpec(dl.TYPE_NO_SHOW_CUTOFF, dl.ANCHOR_DEPARTURE, offset_hours=36),
            departure_date=date(2025, 4, 30),
        )
        # 36 hours is a day and a half; erring early is the only safe direction.
        self.assertEqual(built.computed_date, date(2025, 4, 28))


class DeadlineRegeneration(unittest.TestCase):
    """Rebuilding the timeline must not undo what a person did to it."""

    def _existing(self, **kw):
        base = dict(
            deadline_type=dl.TYPE_NAME_LIST, allocation_id=1, stated_date=None,
            status="open",
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_a_hand_entered_stated_date_survives_regeneration(self):
        built = [dl.build(
            dl.DeadlineSpec(dl.TYPE_NAME_LIST, dl.ANCHOR_DEPARTURE, offset_days=30,
                            allocation_id=1),
            departure_date=AF_DEPARTURE,
        )]
        existing = [self._existing(stated_date=date(2023, 11, 20))]
        fresh, stale = dl.merge_preserving_overrides(built, existing)
        self.assertEqual(fresh[0].effective_date, date(2023, 11, 20))
        self.assertTrue(fresh[0].has_divergence)
        self.assertEqual(stale, [])

    def test_a_settled_deadline_is_never_swept_away(self):
        existing = [self._existing(deadline_type=dl.TYPE_DEPOSIT, status="met")]
        _, stale = dl.merge_preserving_overrides([], existing)
        self.assertEqual(stale, [])

    def test_an_open_deadline_the_contract_no_longer_has_is_swept(self):
        existing = [self._existing(deadline_type=dl.TYPE_DEPOSIT, status="open")]
        _, stale = dl.merge_preserving_overrides([], existing)
        self.assertEqual(len(stale), 1)

    def test_a_paid_instalment_stops_generating_a_deadline(self):
        rows = [
            SimpleNamespace(due_date=date(2023, 1, 6), status="paid",
                            kind="ADVANCE_DEPOSIT", allocation_id=None),
            SimpleNamespace(due_date=date(2023, 9, 18), status="pending",
                            kind="DEPOSIT", allocation_id=None),
        ]
        specs = dl.specs_from_payment_schedule(rows)
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].stated_date, date(2023, 9, 18))


class MarginSign(unittest.TestCase):
    """Positive means the sale earned money — `sell_reconciliation`'s convention, NOT
    `bsp_reconciliation`'s inverted one. Cheap test, expensive mistake."""

    def test_a_profitable_contract_has_a_positive_margin(self):
        self.assertEqual(
            rollups.margin(Decimal("1200000"), Decimal("1095072"), Decimal("0")),
            Decimal("104928.00"),
        )

    def test_a_loss_making_contract_has_a_negative_margin(self):
        self.assertLess(
            rollups.margin(Decimal("900000"), Decimal("1095072"), Decimal("0")), 0
        )

    def test_penalties_reduce_the_margin(self):
        without = rollups.margin(Decimal("1200000"), Decimal("1095072"), Decimal("0"))
        with_penalty = rollups.margin(
            Decimal("1200000"), Decimal("1095072"), Decimal("19380")
        )
        self.assertEqual(without - with_penalty, Decimal("19380.00"))

    def test_money_rounds_half_up_not_to_even(self):
        # Bankers' rounding is Python's default and is not what an invoice does.
        self.assertEqual(rollups.money(Decimal("2.345")), Decimal("2.35"))
        self.assertEqual(rollups.money(Decimal("2.355")), Decimal("2.36"))


class PaymentStatus(unittest.TestCase):

    def test_nothing_paid_is_pending(self):
        self.assertEqual(rollups.schedule_status(1000, 0, None), "pending")

    def test_part_paid_is_partial(self):
        self.assertEqual(rollups.schedule_status(1000, 400, None), "partial")

    def test_paid_in_full_is_paid(self):
        self.assertEqual(rollups.schedule_status(1000, 1000, None), "paid")

    def test_overpayment_still_reads_as_paid(self):
        self.assertEqual(rollups.schedule_status(1000, 1200, None), "paid")

    def test_a_waived_instalment_is_never_recomputed_away(self):
        self.assertEqual(rollups.schedule_status(1000, 0, "waived"), "waived")

    def test_an_instalment_with_no_amount_yet_stays_pending(self):
        # A percentage whose base has not been entered is not a settled instalment.
        self.assertEqual(rollups.schedule_status(None, 0, None), "pending")


class DerivedLateness(unittest.TestCase):
    """Overdue is a comparison, not a column — there is no scheduler to maintain one."""

    TODAY = date(2023, 12, 1)

    def test_a_past_due_unpaid_instalment_is_overdue(self):
        self.assertTrue(rollups.is_overdue(date(2023, 11, 20), self.TODAY, "pending"))

    def test_a_paid_instalment_is_never_overdue_however_old(self):
        self.assertFalse(rollups.is_overdue(date(2020, 1, 1), self.TODAY, "paid"))

    def test_a_waived_instalment_is_never_overdue(self):
        self.assertFalse(rollups.is_overdue(date(2020, 1, 1), self.TODAY, "waived"))

    def test_urgency_buckets(self):
        for target, expected in (
            (date(2023, 11, 28), "overdue"),
            (date(2023, 12, 1), "today"),
            (date(2023, 12, 3), "critical"),
            (date(2023, 12, 10), "soon"),
            (date(2024, 3, 1), "scheduled"),
        ):
            with self.subTest(target=target):
                self.assertEqual(
                    rollups.deadline_urgency(target, self.TODAY, "open"), expected
                )

    def test_a_settled_deadline_is_never_urgent(self):
        self.assertEqual(
            rollups.deadline_urgency(date(2020, 1, 1), self.TODAY, "met"), "settled"
        )


class IssuanceStatus(unittest.TestCase):

    def test_nothing_issued_is_pending(self):
        self.assertEqual(rollups.issuance_status(0, 60), "pending")

    def test_short_of_the_seats_is_partial(self):
        self.assertEqual(rollups.issuance_status(45, 60), "partial")

    def test_all_seats_issued_is_complete(self):
        self.assertEqual(rollups.issuance_status(60, 60), "complete")

    def test_more_tickets_than_seats_is_flagged_not_hidden(self):
        # Either a PNR is on the wrong contract or the group grew. Both need a human.
        self.assertEqual(rollups.issuance_status(61, 60), "over_issued")

    def test_a_contract_with_one_untouched_booking_is_not_complete(self):
        self.assertEqual(rollups.worst_status(["complete", "pending"]), "partial")

    def test_over_issued_outranks_everything(self):
        self.assertEqual(
            rollups.worst_status(["complete", "partial", "over_issued"]), "over_issued"
        )

    def test_all_pending_stays_pending(self):
        self.assertEqual(rollups.worst_status(["pending", "pending"]), "pending")


class PnrNormalisation(unittest.TestCase):

    def test_punctuation_and_case_are_normalised_away(self):
        self.assertEqual(norm_pnr(" ab-c12 3 "), "ABC123")

    def test_leading_zeros_are_kept(self):
        # A PNR is a fixed-width record locator: "0ABCDE" and "ABCDE" are two different
        # bookings. This is the one way it differs from ticket-number normalisation.
        self.assertEqual(norm_pnr("0ABCDE"), "0ABCDE")
        self.assertNotEqual(norm_pnr("0ABCDE"), norm_pnr("ABCDE"))

    def test_empty_and_punctuation_only_are_none(self):
        self.assertIsNone(norm_pnr(""))
        self.assertIsNone(norm_pnr("---"))
        self.assertIsNone(norm_pnr(None))


class SqlAndPythonNormalisationAgree(unittest.TestCase):
    """The functional indexes in series_v2_01 are built on PNR_NORM_SQL. If it stops
    matching `norm_pnr`, the planner finds rows the code then discards, or misses rows it
    would have kept."""

    def test_the_migration_and_the_service_declare_the_same_expression(self):
        import re
        from pathlib import Path
        from app.services.series.matching import PNR_NORM_SQL

        migration = Path(__file__).resolve().parents[1] / "alembic" / "versions" / \
            "series_v2_01_rebuild_series_contracts.py"
        text = migration.read_text(encoding="utf-8")
        for col in ("gds_pnr", "air_pnr"):
            with self.subTest(col=col):
                self.assertIn(PNR_NORM_SQL.format(col=col), text)


if __name__ == "__main__":
    unittest.main()
