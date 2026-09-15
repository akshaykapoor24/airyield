"""Per-category markup: which rate a party charges on one line of their bill.

The reason this file is careful out of proportion to its size: it sits directly in front of
`billing_calc.compute_markup` on a LIVE product, and the four call sites in
api/v1/{customers,corporates}.py that used to read two columns now go through it. The first
test class is therefore the whole safety argument — with no overrides configured, which is
every party in the live workspace, `markup_for` must return *literally* the two values those
call sites used to pass.

The other load-bearing case is the opposite of an obvious one: a category with no override
falls back to the party's DEFAULT, never to zero. Charging nothing would make every party
silently sell hotels at no margin the day hotel billing switches on, and nothing on any
screen would report it.

No DB, no network — all three functions are pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import markup_categories as mc  # noqa: E402
from app.services.billing_calc import compute_markup  # noqa: E402
from app.services.party_markup import (  # noqa: E402
    CATEGORY_COLUMNS,
    category_markups_from_cells,
    category_of,
    category_summary,
    line_markup,
    markup_for,
    norm_category_markups,
    pax_of,
)


class FakeParty:
    """Only the three attributes `markup_for` reads."""

    def __init__(self, markup_type="percentage", markup_value=10, category_markups=None):
        self.markup_type = markup_type
        self.markup_value = markup_value
        self.category_markups = category_markups


class TestNothingMovesWithoutAnOverride(unittest.TestCase):
    """THE SAFETY ARGUMENT. Every one of the 28 live parties has `category_markups` NULL."""

    def test_a_party_with_no_overrides_returns_its_own_columns(self):
        p = FakeParty("fixed", 500)
        for category in (None, *mc.CATEGORY_SLUGS):
            with self.subTest(category=category):
                self.assertEqual(markup_for(p, category), ("fixed", 500))

    def test_an_empty_dict_is_the_same_as_none(self):
        self.assertEqual(markup_for(FakeParty(category_markups={}), "hotel"),
                         ("percentage", 10))

    def test_it_is_the_two_arguments_compute_markup_already_took(self):
        """The arithmetic proof, over the shapes that actually differ:
        a sale, a REFUND (where `fixed` follows the sign), and a zero base."""
        for mtype, mval in (("percentage", 5), ("fixed", 300), (None, None), ("fixed", 0)):
            p = FakeParty(mtype, mval)
            for base in (5529.0, -3728.0, 0.0, 100.05):
                for category in (None, "air", "hotel", "mice"):
                    with self.subTest(mtype=mtype, base=base, category=category):
                        self.assertEqual(
                            compute_markup(base, *markup_for(p, category)),
                            compute_markup(base, p.markup_type, p.markup_value),
                        )

    def test_a_party_object_missing_the_column_entirely_still_resolves(self):
        """A Pydantic row or a partial SELECT has no `category_markups` attribute."""
        class Old:
            markup_type, markup_value = "percentage", 7
        self.assertEqual(markup_for(Old(), "hotel"), ("percentage", 7))


class TestOverrides(unittest.TestCase):

    def setUp(self):
        self.p = FakeParty("percentage", 10, {
            "hotel": {"type": "fixed", "value": 500},
            "train": {"type": "percentage", "value": 0},
        })

    def test_an_override_wins_for_its_own_category_only(self):
        self.assertEqual(markup_for(self.p, "hotel"), ("fixed", 500))
        self.assertEqual(markup_for(self.p, "air"), ("percentage", 10))
        self.assertEqual(markup_for(self.p, "bus"), ("percentage", 10))

    def test_a_missing_category_falls_back_to_the_default_not_to_nothing(self):
        """PINNED so nobody "fixes" it to zero. An absent override means "as usual"; a
        category quietly priced at nothing the day its bills come online is a revenue leak
        no screen would report."""
        mtype, mval = markup_for(self.p, "mice")
        self.assertEqual((mtype, mval), ("percentage", 10))
        self.assertNotEqual(compute_markup(1000.0, mtype, mval), 0.0)

    def test_a_zero_override_is_an_override_not_a_blank(self):
        """"No margin on trains" has to survive — the same call party_inherit.is_blank
        makes for markup_value. Hence `mval is None`, never `not mval`."""
        self.assertEqual(markup_for(self.p, "train"), ("percentage", 0))
        self.assertEqual(compute_markup(1000.0, *markup_for(self.p, "train")), 0.0)

    def test_no_category_takes_the_default_even_when_overrides_exist(self):
        self.assertEqual(markup_for(self.p, None), ("percentage", 10))


class TestJunkCannotReachTheArithmetic(unittest.TestCase):
    """JSONB holds whatever a psql session puts there, and this runs on every line."""

    def test_a_half_set_override_falls_back(self):
        for entry in ({"type": "fixed"}, {"value": 500}, {}):
            with self.subTest(entry=entry):
                p = FakeParty(category_markups={"hotel": entry})
                self.assertEqual(markup_for(p, "hotel"), ("percentage", 10))

    def test_an_unknown_markup_type_falls_back(self):
        p = FakeParty(category_markups={"hotel": {"type": "flat", "value": 500}})
        self.assertEqual(markup_for(p, "hotel"), ("percentage", 10))

    def test_a_non_dict_column_or_entry_falls_back(self):
        for column in ("5%", [], 7, {"hotel": "5%"}, {"hotel": None}):
            with self.subTest(column=column):
                p = FakeParty(category_markups=column)
                self.assertEqual(markup_for(p, "hotel"), ("percentage", 10))


class TestNormalise(unittest.TestCase):

    def test_it_returns_none_for_empty_so_the_column_stays_null(self):
        """NULL and {} must not be two spellings of one state — party_inherit.is_blank,
        markup_for and the browser would each have to handle both."""
        for raw in ({}, None, "junk", [], {"visa": {"type": "fixed", "value": 1}}):
            with self.subTest(raw=raw):
                self.assertIsNone(norm_category_markups(raw))

    def test_an_unknown_category_is_dropped_not_rejected(self):
        """Matches _norm_choice's silent coercion: a category from a newer or older
        frontend must not fail the whole save."""
        self.assertEqual(
            norm_category_markups({"visa": {"type": "fixed", "value": 9},
                                   "car": {"type": "fixed", "value": 3}}),
            {"car": {"type": "fixed", "value": 3.0}})

    def test_half_set_entries_are_pruned(self):
        self.assertIsNone(norm_category_markups({"hotel": {"type": "percentage"},
                                                 "bus": {"value": 5}}))

    def test_zero_is_kept(self):
        self.assertEqual(norm_category_markups({"hotel": {"type": "percentage", "value": 0}}),
                         {"hotel": {"type": "percentage", "value": 0.0}})

    def test_spellings_are_aliased_and_the_order_is_canonical(self):
        self.assertEqual(
            norm_category_markups({"Train": {"type": "fixed", "value": 100},
                                   "Flight": {"type": "PERCENTAGE", "value": 2}}),
            {"air": {"type": "percentage", "value": 2.0},
             "train": {"type": "fixed", "value": 100.0}})

    def test_a_string_value_from_a_jsonb_round_trip_is_accepted(self):
        self.assertEqual(norm_category_markups({"hotel": {"type": "fixed", "value": "500"}}),
                         {"hotel": {"type": "fixed", "value": 500.0}})

    def test_a_booleanish_value_is_not_a_number(self):
        self.assertIsNone(norm_category_markups({"hotel": {"type": "fixed", "value": True}}))

    def test_what_it_stores_is_what_markup_for_reads(self):
        """The round trip: nothing survives normalisation that then falls back on read."""
        stored = norm_category_markups({"Hotel": {"type": "fixed", "value": 500}})
        self.assertEqual(markup_for(FakeParty(category_markups=stored), "hotel"),
                         ("fixed", 500.0))


class TestCategoryOf(unittest.TestCase):

    @staticmethod
    def ticket(category):
        from types import SimpleNamespace
        return SimpleNamespace(product_category=category)

    def test_a_line_with_no_category_attribute_is_a_flight(self):
        """Matches the column default: every writer except the Third Party API projection
        writes flights."""
        self.assertEqual(category_of(object()), mc.CATEGORY_AIR)

    def test_it_reads_the_stored_category(self):
        for slug in ("air", "hotel", "train", "bus", "car"):
            with self.subTest(slug=slug):
                self.assertEqual(category_of(self.ticket(slug)), slug)

    def test_a_blank_column_is_a_flight(self):
        self.assertEqual(category_of(self.ticket(None)), mc.CATEGORY_AIR)
        self.assertEqual(category_of(self.ticket("")), mc.CATEGORY_AIR)

    def test_a_spelling_is_aliased_and_junk_is_none(self):
        self.assertEqual(category_of(self.ticket("Hotel")), mc.CATEGORY_HOTEL)
        # None → markup_for answers with the party default rather than a guessed category.
        self.assertIsNone(category_of(self.ticket("visa")))

    def test_air_resolves_to_the_default_on_every_live_party(self):
        """Which is what keeps existing air invoices unchanged."""
        p = FakeParty("fixed", 250)
        self.assertEqual(markup_for(p, category_of(object())), ("fixed", 250))

    def test_a_hotel_line_takes_the_hotel_override(self):
        p = FakeParty("percentage", 5, {"air": {"type": "fixed", "value": 300},
                                        "hotel": {"type": "fixed", "value": 200}})
        self.assertEqual(markup_for(p, category_of(self.ticket("hotel"))), ("fixed", 200))
        self.assertEqual(markup_for(p, category_of(self.ticket("air"))), ("fixed", 300))
        # No bus override → the party default, never zero.
        self.assertEqual(markup_for(p, category_of(self.ticket("bus"))), ("percentage", 5))


class TestLineMarkupPerPax(unittest.TestCase):
    """A FIXED markup is per passenger; a percentage is not multiplied again."""

    @staticmethod
    def ticket(pax=1, category="air"):
        from types import SimpleNamespace
        return SimpleNamespace(pax_count=pax, product_category=category)

    def test_one_pax_is_exactly_what_billing_always_charged(self):
        """The safety argument: every line except a multi-pax aggregator booking."""
        for party in (FakeParty("fixed", 250), FakeParty("percentage", 5), FakeParty(None, None)):
            with self.subTest(party=party.markup_type):
                expected = compute_markup(1000.0, party.markup_type, party.markup_value)
                self.assertEqual(line_markup(1000.0, party, self.ticket(1))[0], expected)

    def test_a_fixed_markup_is_charged_per_passenger(self):
        amount, note = line_markup(14700.0, FakeParty("fixed", 300), self.ticket(6))
        self.assertEqual(amount, 1800.0)
        self.assertEqual(note, "₹300 × 6 pax")

    def test_a_percentage_is_not_multiplied(self):
        """2% of a six-passenger booking's amount already covers all six."""
        amount, note = line_markup(14700.0, FakeParty("percentage", 2), self.ticket(6))
        self.assertAlmostEqual(amount, 294.0)
        self.assertEqual(note, "2% of fare")

    def test_a_credit_reverses_the_markup_for_every_passenger(self):
        amount, _ = line_markup(-1380.0, FakeParty("fixed", 300), self.ticket(2))
        self.assertEqual(amount, -600.0)

    def test_the_category_override_is_what_gets_multiplied(self):
        p = FakeParty("percentage", 5, {"hotel": {"type": "fixed", "value": 200}})
        self.assertEqual(line_markup(4000.0, p, self.ticket(3, "hotel"))[0], 600.0)
        # No bus override → the percentage default, unmultiplied.
        self.assertAlmostEqual(line_markup(2154.0, p, self.ticket(3, "bus"))[0], 107.7)

    def test_a_missing_zero_or_garbage_pax_is_one_passenger(self):
        """A 0 would zero the fixed markup — a line billed at cost with nothing to say why."""
        from types import SimpleNamespace
        for ticket in (object(), SimpleNamespace(pax_count=None),
                       SimpleNamespace(pax_count=0), SimpleNamespace(pax_count=-2),
                       SimpleNamespace(pax_count="six")):
            with self.subTest(ticket=ticket):
                self.assertEqual(pax_of(ticket), 1)
                self.assertEqual(line_markup(100.0, FakeParty("fixed", 50), ticket)[0], 50.0)

    def test_no_markup_type_is_no_markup_and_no_note(self):
        self.assertEqual(line_markup(100.0, FakeParty(None, None), self.ticket(4)), (0.0, None))


class TestVocabulary(unittest.TestCase):

    def test_the_six_slugs_and_their_order(self):
        # Keep in step with frontend/src/lib/party.ts MARKUP_CATEGORIES. If this fails, the
        # form and the server disagree about what a category is called.
        self.assertEqual(mc.CATEGORY_SLUGS, ("air", "hotel", "train", "bus", "car", "mice"))

    def test_every_tp_api_product_value_maps_to_a_slug(self):
        """So the day a hotel row becomes billable, the projection can hand over its
        `product_type` unchanged and no new translation table is needed."""
        from app.services.tp_api_spec import PRODUCT_VALUES
        for product in PRODUCT_VALUES:
            with self.subTest(product=product):
                self.assertIn(mc.category_slug(product), mc.CATEGORY_SLUGS)
        self.assertEqual(mc.category_slug("Flight"), mc.CATEGORY_AIR)

    def test_an_unknown_spelling_is_none_rather_than_a_guess(self):
        self.assertIsNone(mc.category_slug("visa"))
        self.assertIsNone(mc.category_slug(None))

    def test_series_and_sit_are_not_mice(self):
        """series_contracts.contract_type holds three contract types; only one is MICE."""
        self.assertIsNone(mc.category_slug("series"))
        self.assertIsNone(mc.category_slug("sit"))

    def test_the_markup_types_are_the_two_compute_markup_branches_on(self):
        for mtype in mc.MARKUP_TYPES:
            self.assertNotEqual(compute_markup(100.0, mtype, 10), 0.0)
        self.assertEqual(compute_markup(100.0, "flat", 10), 0.0)


class TestSummary(unittest.TestCase):

    def test_it_reads_as_the_screen_shows_it(self):
        p = FakeParty(category_markups={"hotel": {"type": "fixed", "value": 500},
                                        "train": {"type": "percentage", "value": 0}})
        self.assertEqual(category_summary(p), "Hotel ₹500 · Train 0%")

    def test_no_overrides_is_empty(self):
        self.assertEqual(category_summary(FakeParty()), "")

    def test_junk_is_skipped_rather_than_rendered(self):
        p = FakeParty(category_markups={"hotel": "5%", "car": {"type": "fixed", "value": 3}})
        self.assertEqual(category_summary(p), "Car ₹3")


class TestSpreadsheetColumns(unittest.TestCase):
    """The optional <CATEGORY>_MARKUP_TYPE / _VALUE import columns."""

    @staticmethod
    def cells(**values):
        return lambda column: values.get(column)

    def test_column_names_and_order(self):
        self.assertEqual(CATEGORY_COLUMNS[:2], ("AIR_MARKUP_TYPE", "AIR_MARKUP_VALUE"))
        self.assertEqual(CATEGORY_COLUMNS[-2:], ("MICE_MARKUP_TYPE", "MICE_MARKUP_VALUE"))
        self.assertEqual(len(CATEGORY_COLUMNS), 2 * len(mc.CATEGORY_SLUGS))

    def test_an_old_template_without_the_columns_imports_as_before(self):
        self.assertEqual(category_markups_from_cells(self.cells()), (None, None))

    def test_filled_pairs_become_overrides(self):
        got, problem = category_markups_from_cells(self.cells(
            AIR_MARKUP_TYPE="Fixed", AIR_MARKUP_VALUE="300",
            HOTEL_MARKUP_TYPE="percentage", HOTEL_MARKUP_VALUE="5.0",
        ))
        self.assertIsNone(problem)
        self.assertEqual(got, {"air": {"type": "fixed", "value": 300.0},
                               "hotel": {"type": "percentage", "value": 5.0}})

    def test_zero_is_a_real_override(self):
        got, problem = category_markups_from_cells(self.cells(
            TRAIN_MARKUP_TYPE="percentage", TRAIN_MARKUP_VALUE="0"))
        self.assertIsNone(problem)
        self.assertEqual(got, {"train": {"type": "percentage", "value": 0.0}})

    def test_half_filled_pairs_are_reported_not_dropped(self):
        for cells, column in (
            ({"HOTEL_MARKUP_VALUE": "300"}, "HOTEL_MARKUP_TYPE"),
            ({"HOTEL_MARKUP_TYPE": "fixed"}, "HOTEL_MARKUP_VALUE"),
        ):
            with self.subTest(cells=cells):
                got, problem = category_markups_from_cells(self.cells(**cells))
                self.assertIsNone(got)
                self.assertIn(column, problem)

    def test_junk_is_reported(self):
        _, problem = category_markups_from_cells(self.cells(
            BUS_MARKUP_TYPE="flat", BUS_MARKUP_VALUE="10"))
        self.assertIn("BUS_MARKUP_TYPE", problem)
        for bad in ("ten", "nan"):
            with self.subTest(value=bad):
                _, problem = category_markups_from_cells(self.cells(
                    CAR_MARKUP_TYPE="fixed", CAR_MARKUP_VALUE=bad))
                self.assertIn("not a number", problem)


if __name__ == "__main__":
    unittest.main()
