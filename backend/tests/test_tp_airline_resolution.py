"""Unit tests for third-party carrier resolution — no DB, no network.

The prefixes here are the real ones from the sample export (235 Turkish, 275 APG,
157 Qatar, 607 Etihad). Two behaviours are worth pinning hard, because both fail
silently in production rather than raising:

  * a row that resolves to the WRONG carrier claims another airline's deal;
  * a row that resolves to NO carrier vanishes from PLB accrual, which joins on
    `airlines.iata_code = data->>'airline_code'`.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.tp_airline_resolution import (  # noqa: E402
    BY_CODE,
    BY_NAME,
    BY_PREFIX,
    TpAirlineIndex,
    normalize_prefix,
    resolve_tp_airline,
    stamp,
)
from app.services.airline_resolver import airline_match_key  # noqa: E402


def make_index(rows, ambiguous_names=()):
    """rows: [(id, numeric, iata, name)] — a stand-in for the airline master."""
    by_numeric, by_code, by_name_key = {}, {}, {}
    for pk, numeric, iata, name in rows:
        value = (pk, iata, name)
        by_numeric[numeric] = value
        by_code[iata] = value
        by_name_key[airline_match_key(name)] = value
    for name in ambiguous_names:
        by_name_key[airline_match_key(name)] = None
    return TpAirlineIndex(by_numeric=by_numeric, by_code=by_code, by_name_key=by_name_key)


MASTER = make_index([
    (1, "235", "TK", "Turkish Airlines"),
    (2, "275", "GP", "APG Airlines"),
    (3, "157", "QR", "Qatar Airways"),
    (4, "607", "EY", "Etihad Airways"),
    (5, "098", "AI", "Air India"),
])


class TestNormalizePrefix(unittest.TestCase):
    def test_real_prefixes(self):
        for raw in ("235", " 235 ", "235-", "0235"):
            self.assertEqual(normalize_prefix(raw), "235", raw)

    def test_zero_padding_matches_the_master_key(self):
        """The master zero-pads to three (api/v1/bsp.py::_airline_iata_name_map)."""
        self.assertEqual(normalize_prefix("98"), "098")
        self.assertEqual(normalize_prefix("098"), "098")

    def test_a_ticket_number_is_rejected_not_truncated(self):
        """Taking the first three digits of 4848358656 would give '484' — possibly a real
        carrier, and certainly the wrong one. Refusing is the only safe answer."""
        self.assertIsNone(normalize_prefix("4848358656"))
        self.assertIsNone(normalize_prefix("2358"))

    def test_blank_is_none(self):
        for junk in ("", "   ", None, "N/A"):
            self.assertIsNone(normalize_prefix(junk))


class TestResolution(unittest.TestCase):
    def test_prefix_alone_resolves_every_carrier_in_the_sample(self):
        for prefix, code, name in (("235", "TK", "Turkish Airlines"), ("275", "GP", "APG Airlines"),
                                   ("157", "QR", "Qatar Airways"), ("607", "EY", "Etihad Airways")):
            m = resolve_tp_airline(prefix, None, None, MASTER)
            self.assertTrue(m.resolved, prefix)
            self.assertEqual((m.iata_code, m.name, m.source), (code, name, BY_PREFIX))

    def test_the_real_row_shape_resolves(self):
        """Airline Code is blank on every row of the real export — the prefix carries it."""
        m = resolve_tp_airline("235", "", "TURKISH AIRLINES", MASTER)
        self.assertEqual(m.name, "Turkish Airlines")
        self.assertEqual(m.iata_code, "TK")
        self.assertEqual(m.source, BY_PREFIX)
        self.assertFalse(m.conflict)

    def test_uppercase_file_spelling_matches_the_master(self):
        """Deal matching compares against the MASTER's spelling, so the export's
        'TURKISH AIRLINES' has to arrive as 'Turkish Airlines' or nothing matches."""
        m = resolve_tp_airline(None, None, "TURKISH AIRLINES", MASTER)
        self.assertEqual((m.name, m.source), ("Turkish Airlines", BY_NAME))

    def test_code_is_used_when_there_is_no_prefix(self):
        m = resolve_tp_airline(None, "EY", None, MASTER)
        self.assertEqual((m.name, m.source), ("Etihad Airways", BY_CODE))

    def test_precedence_is_prefix_then_code_then_name(self):
        m = resolve_tp_airline("235", "EY", "QATAR AIRWAYS", MASTER)
        self.assertEqual((m.name, m.source), ("Turkish Airlines", BY_PREFIX))
        m = resolve_tp_airline(None, "EY", "QATAR AIRWAYS", MASTER)
        self.assertEqual((m.name, m.source), ("Etihad Airways", BY_CODE))

    def test_prefix_wins_a_disagreement_but_the_row_says_so(self):
        m = resolve_tp_airline("235", None, "QATAR AIRWAYS", MASTER)
        self.assertEqual(m.name, "Turkish Airlines")
        self.assertTrue(m.conflict)
        self.assertEqual(m.conflict_name, "Qatar Airways")

    def test_agreement_is_not_a_conflict(self):
        m = resolve_tp_airline("235", None, "TURKISH AIRLINES", MASTER)
        self.assertFalse(m.conflict)

    def test_an_unknown_name_is_silence_not_contradiction(self):
        """A carrier the master has never seen must not flag the prefix as disputed."""
        m = resolve_tp_airline("235", None, "SOME NEW CARRIER", MASTER)
        self.assertTrue(m.resolved)
        self.assertFalse(m.conflict)

    def test_nothing_identifiable_resolves_to_nothing(self):
        m = resolve_tp_airline(None, "", "", MASTER)
        self.assertFalse(m.resolved)
        self.assertIsNone(m.airline_id)
        self.assertIsNone(m.source)

    def test_an_ambiguous_name_is_refused(self):
        """Two master rows sharing a normalized key are an ambiguity, not a match."""
        index = make_index([(1, "235", "TK", "Turkish Airlines")], ambiguous_names=["Fly Air"])
        m = resolve_tp_airline(None, None, "FLY AIR", index)
        self.assertFalse(m.resolved)

    def test_an_ambiguous_name_does_not_block_the_prefix(self):
        index = make_index([(1, "235", "TK", "Turkish Airlines")], ambiguous_names=["Fly Air"])
        m = resolve_tp_airline("235", None, "FLY AIR", index)
        self.assertEqual(m.name, "Turkish Airlines")
        self.assertFalse(m.conflict)

    def test_an_empty_master_resolves_nothing(self):
        m = resolve_tp_airline("235", "TK", "TURKISH AIRLINES", TpAirlineIndex())
        self.assertFalse(m.resolved)


class TestStamp(unittest.TestCase):
    def test_the_file_spelling_is_preserved(self):
        data = {"airline_name": "TURKISH AIRLINES"}
        stamp(data, resolve_tp_airline("235", None, "TURKISH AIRLINES", MASTER))
        self.assertEqual(data["airline_name"], "TURKISH AIRLINES")
        self.assertEqual(data["airline_master_name"], "Turkish Airlines")

    def test_a_blank_airline_code_is_filled_for_plb_accrual(self):
        data = {"airline_name": "TURKISH AIRLINES"}
        stamp(data, resolve_tp_airline("235", None, "TURKISH AIRLINES", MASTER))
        self.assertEqual(data["airline_code"], "TK")
        self.assertEqual(data["airline_id"], "1")

    def test_a_stated_airline_code_is_not_overwritten(self):
        data = {"airline_code": "TK "}
        stamp(data, resolve_tp_airline("235", None, None, MASTER))
        self.assertEqual(data["airline_code"], "TK ")

    def test_a_conflict_is_recorded_in_words(self):
        data = {}
        stamp(data, resolve_tp_airline("235", None, "QATAR AIRWAYS", MASTER))
        self.assertIn("Turkish Airlines", data["airline_conflict"])
        self.assertIn("Qatar Airways", data["airline_conflict"])

    def test_an_unresolved_row_is_left_untouched(self):
        data = {"airline_name": "MYSTERY AIR"}
        self.assertFalse(stamp(data, resolve_tp_airline(None, None, "MYSTERY AIR", MASTER)))
        self.assertEqual(data, {"airline_name": "MYSTERY AIR"})


if __name__ == "__main__":
    unittest.main()
