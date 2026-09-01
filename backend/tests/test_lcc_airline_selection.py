"""The one-carrier rule on an LCC upload's airline selection.

A statement may be linked to several of the tenant's ids — that is the point — but
never to ids from two carriers. The batch and every row it produces carry ONE
airline_code, stamped from this selection, and the file has no airline column to
attribute a row to one id rather than the other. A mixed selection is therefore not a
preference to accommodate, it is a state the rest of the schema cannot represent.

No DB, no network — resolve_selection is pure.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.lcc_airline_selection import (  # noqa: E402
    MixedAirlineSelection, resolve_selection,
)


class FakeTenantAirline:
    def __init__(self, id, airline_id, ref_id, airline_name):
        self.id = id
        self.airline_id = airline_id
        self.ref_id = ref_id
        self.airline_name = airline_name


def indigo(id, ref):
    return FakeTenantAirline(id, 153, ref, "INDIGO")


def air_asia(id, ref):
    return FakeTenantAirline(id, 219, ref, "AIR ASIA")


class ResolveSelectionTests(unittest.TestCase):

    def test_several_ids_of_one_airline_pass_in_pick_order(self):
        """Five Indigo logins on one statement is the case this exists for. Order
        matters: the first pick becomes the batch's primary id."""
        picked = [indigo(7, "6E-DEL-88213"), indigo(9, "6E-MAA-44510"), indigo(8, "6E-BOM-11902")]
        out = resolve_selection(picked)
        self.assertEqual([t.ref_id for t in out], ["6E-DEL-88213", "6E-MAA-44510", "6E-BOM-11902"])

    def test_single_id_still_works(self):
        out = resolve_selection([indigo(7, "rger8489")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].ref_id, "rger8489")

    def test_duplicates_collapse_keeping_the_first(self):
        a = indigo(7, "6E-DEL-88213")
        out = resolve_selection([a, indigo(9, "6E-MAA"), a])
        self.assertEqual([t.id for t in out], [7, 9])

    def test_two_carriers_are_refused(self):
        with self.assertRaises(MixedAirlineSelection):
            resolve_selection([indigo(7, "6E-DEL-88213"), air_asia(6, "uhfhsuhf")])

    def test_the_refusal_names_both_carriers(self):
        """The user has to know which pick to drop; "invalid selection" would not
        tell them."""
        with self.assertRaises(MixedAirlineSelection) as ctx:
            resolve_selection([indigo(7, "6E-DEL"), air_asia(6, "uhfhsuhf")])
        msg = str(ctx.exception)
        self.assertIn("INDIGO", msg)
        self.assertIn("AIR ASIA", msg)

    def test_mixed_is_caught_even_when_most_ids_agree(self):
        """The odd one out is last and outnumbered — still a refusal."""
        with self.assertRaises(MixedAirlineSelection):
            resolve_selection([indigo(7, "a"), indigo(8, "b"), indigo(9, "c"), air_asia(6, "d")])

    def test_empty_selection_is_refused(self):
        with self.assertRaises(ValueError):
            resolve_selection([])

    def test_a_missing_airline_name_does_not_crash_the_message(self):
        """airline_name is a nullable snapshot column."""
        nameless = FakeTenantAirline(4, 54, "ktgh65", None)
        with self.assertRaises(MixedAirlineSelection) as ctx:
            resolve_selection([indigo(7, "6E-DEL"), nameless])
        self.assertIn("INDIGO", str(ctx.exception))


class RequiresAirlineIdTests(unittest.TestCase):
    """WHICH statement types demand an airline id at upload.

    All the spec-driven types share one upload endpoint and one frontend view, so this
    flag is the only thing keeping a mandatory field off the types that do not need it.
    A BSP, TGQ HMPR, NDC or third-party statement names its own carrier; making the user
    declare one there would be a pointless blocker on every import.
    """

    def test_the_lcc_types_require_it(self):
        from app.services import statement_spec as spec
        for slug in ("lcc-di", "lcc-divided-pnr", "lcc-flown-report", "lcc-cta-bta"):
            self.assertTrue(spec.requires_airline_id(slug), slug)

    def test_no_other_type_requires_it(self):
        from app.services import statement_spec as spec
        for slug in ("tgq-hmpr", "ndc", "tp-gds", "tp-lcc"):
            self.assertFalse(spec.requires_airline_id(slug), slug)

    def test_an_unknown_slug_does_not_require_it(self):
        """`spec_for` returns None for an unknown slug — that must read as False, not
        raise, or a stale bookmark would 500 instead of 404."""
        from app.services import statement_spec as spec
        self.assertFalse(spec.requires_airline_id("nope"))
        self.assertFalse(spec.requires_airline_id(""))


if __name__ == "__main__":
    unittest.main()
