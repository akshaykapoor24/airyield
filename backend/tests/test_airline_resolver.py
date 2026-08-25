"""Unit tests for airline-master resolution — no DB, no network, no API key.

Every case here is a real cell from one of the three supplier deal sheets in
`Desktop\\Airyield Docs`. The point of pinning them is that the channel-qualifier
regexes are easy to widen by accident: an alternative that also eats "(INTL)"
would quietly change every Air India row's Flight Type, and nothing else in the
pipeline would notice.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.airline_resolver import (  # noqa: E402
    AMBIGUOUS,
    CONFLICT,
    MULTI_CARRIER,
    NEW,
    RESOLVED,
    UNRESOLVED,
    AirlineIndex,
    airline_match_key,
    carrier_code_from_row_field,
    clean_airline_code,
    looks_like_airline_name,
    names_compatible,
    strip_channel_qualifier,
)


class TestCleanAirlineCode(unittest.TestCase):
    CASES = [
        # cell                                                    code   multi
        ("AI (LORDS ISSUANCE)",                                   "AI",  False),
        ("AI (1st Apr 2026) (XO SALE)",                           "AI",  False),
        ("AI (SAARC/ME) (1st Apr 2026) (XO SALE)",                "AI",  False),
        ("EY (T/E/G & GCC SECTOR) LORDS ISSUANCE",                "EY",  False),
        ("SQ (OB/IB till 31 Mar26)",                              "SQ",  False),
        ("SQ (1st Apr 2026)",                                     "SQ",  False),
        ("6E (XO SALE)",                                          "6E",  False),
        ("Q2 (XO SALE)",                                          "Q2",  False),
        ("8D (XO SALE)",                                          "8D",  False),
        ("JJ ( XO SALE)",                                         "JJ",  False),   # space inside paren
        ("CA (Xo SALE)",                                          "CA",  False),   # mixed case
        ("TR (LORDS  ISSUANCE)",                                  "TR",  False),   # double space
        ("AI\n(LORDS ISSUANCE)",                                  "AI",  False),   # cells keep newlines
        ("BA",                                                    "BA",  False),
        ("9I",                                                    "9I",  False),
        # Multi-carrier cells: first code wins, flag set.
        ("AF/KL/DL (XO SALE)",                                    "AF",  True),
        ("KL/AF/DL",                                              "KL",  True),
        ("LH/LX -ROW (Rest Of World) (LORDS ISSUANCE)",           "LH",  True),
        # Junk / not-a-code cells must yield None rather than a plausible fake.
        ("YY+ ONWARDS AIR CANADA PURE FLT ONLY (On AC Docs only) (LORDS ISSUANCE)", None, False),
        ("ANZ",                                                   None,  False),   # 3-char rejected
        ("",                                                      None,  False),
        (None,                                                    None,  False),
        ("12345678",                                              None,  False),   # agency IATA number
    ]

    def test_cases(self):
        for cell, code, multi in self.CASES:
            with self.subTest(cell=cell):
                self.assertEqual(clean_airline_code(cell), (code, multi))

    def test_swapped_column_yields_no_code(self):
        """Two Lords rows transpose the name and code columns. A NAME landing in
        the code cell must not produce a code — "AIR CANADA (...)" -> "AIR" would
        be a real 3-letter-looking token that no master row can match."""
        self.assertEqual(clean_airline_code("AIR CANADA (Pure AC flts) (LORDS ISSUANCE)")[0], None)
        self.assertEqual(clean_airline_code("AirFrance / KLM (LORDS ISSUANCE)")[0], None)

    def test_agency_iata_number_is_not_a_carrier_code(self):
        # confirm_upload reads ExtractedRow.iata_code as a code fallback for the
        # column-mapping path; that same field also carries the agency's IATA
        # number, which must never be mistaken for a designator.
        self.assertIsNone(carrier_code_from_row_field("14395852"))
        self.assertIsNone(carrier_code_from_row_field("  14395852 "))
        self.assertEqual(carrier_code_from_row_field("AI (LORDS ISSUANCE)"), "AI")


class TestStripChannelQualifier(unittest.TestCase):
    def test_channel_qualifiers_are_removed(self):
        self.assertEqual(strip_channel_qualifier("Virgin Atlantic (XO SALE)"), "Virgin Atlantic")
        self.assertEqual(strip_channel_qualifier("Uganda (XO SALE)"), "Uganda")
        self.assertEqual(strip_channel_qualifier("US Bangla (XO SALE)"), "US Bangla")
        self.assertEqual(strip_channel_qualifier("Scandavian Air ( XO SALE)"), "Scandavian Air")
        self.assertEqual(strip_channel_qualifier("NOK AIR (LORDS ISSUANCE)"), "NOK AIR")
        # Unparenthesised trailing form, printed on the same sheet.
        self.assertEqual(
            strip_channel_qualifier("ETIHAD (T/E/G & GCC SECTOR) LORDS ISSUANCE"),
            "ETIHAD (T/E/G & GCC SECTOR)",
        )

    def test_meaningful_qualifiers_survive(self):
        """The load-bearing assertion. (INTL)/(DOM) drive Flight Type via
        `ft_from_airline_name`, and (S&T CLS)/(PRIVATE FARES)/(NDC) distinguish
        rate variants of the same carrier."""
        self.assertEqual(strip_channel_qualifier("INDIGO ( INTL ) (XO SALE)"), "INDIGO (INTL)")
        self.assertEqual(strip_channel_qualifier("AIR ASIA INTL (LORDS ISSUANCE)"), "AIR ASIA INTL")
        self.assertEqual(strip_channel_qualifier("AF/KL (NDC ) (LORDS ISSUANCE)"), "AF/KL (NDC)")
        self.assertEqual(
            strip_channel_qualifier("AIR CANADA (Pure AC flts) (LORDS ISSUANCE)"),
            "AIR CANADA (Pure AC flts)",
        )
        self.assertIn("(INTL)", strip_channel_qualifier("AIR INDIA (INTL) (OB/IB till 31 Mar 2026)"))
        self.assertIn("(S&T CLS)", strip_channel_qualifier("AIR INDIA (DOM) (S&T CLS ) (OB 1st Apr 2026 Onwards)"))

    def test_names_without_a_qualifier_are_untouched(self):
        for name in ("BIMAN BANGLADESH", "SPICEJT INTL", "American Airline", "Air Peace"):
            self.assertEqual(strip_channel_qualifier(name), name)


class TestAirlineMatchKey(unittest.TestCase):
    def test_key_drops_every_parenthetical_and_channel_word(self):
        self.assertEqual(airline_match_key("AIR INDIA (INTL) (OB/IB till 31 Mar 2026)"), "AIR INDIA")
        self.assertEqual(airline_match_key("AIR INDIA (DOM) (S&T CLS ) (OB 1st Apr 2026)"), "AIR INDIA")
        self.assertEqual(airline_match_key("Virgin Atlantic (XO SALE)"), "VIRGIN ATLANTIC")
        self.assertEqual(airline_match_key("ETIHAD (T/E/G & GCC SECTOR) LORDS ISSUANCE"), "ETIHAD")

    def test_variant_modifiers_key_to_the_base_carrier(self):
        # The sheet lists these as separate rows of the same airline.
        self.assertEqual(airline_match_key("Etihad INCENTIVE"), "ETIHAD")
        self.assertEqual(airline_match_key("ITA AIRWAYS (PLB)"), "ITA AIRWAYS")
        self.assertEqual(airline_match_key("AIR INDIA (Additional Incentive)"), "AIR INDIA")

    def test_unbalanced_parenthesis(self):
        # Akbar prints this with no closing bracket; without the open-paren rule
        # the row could never match anything.
        self.assertEqual(airline_match_key("AIR NEWZELAND( SIN/CHC or AKL & V.V"), "AIR NEWZELAND")

    def test_empty(self):
        self.assertEqual(airline_match_key(None), "")
        self.assertEqual(airline_match_key("   "), "")


class TestNamesCompatible(unittest.TestCase):
    # Real sheet-spelling / master-spelling pairs. These must rename.
    ACCEPT = [
        ("AIR NEWZELAND", "AIR NEW ZEALAND"),
        ("TAP AIR PORTUAL", "TAP PORTUGAL"),
        ("SHANGDONG", "SHANDONG AIRLINES"),
        ("AZERBEIJAN AIRLINES", "AZERBAIJAN AIRLINES"),
        ("JAZZERA AIRWAYS", "JAZEERA AIRWAYS"),
        ("SPICEJT INTL", "SPICEJET"),
        ("PHILLIPINES AIRLINES", "PHILIPPINE AIRLINES"),
        ("ELAL ISREAL", "EL AL ISRAEL AIRLINES"),
        ("SCANDAVIAN AIR", "SAS SCANDINAVIAN AIRLINES"),
        ("UGANDA", "UGANDA AIRLINES"),
        ("VIRGIN ATLANTIC", "VIRGIN ATLANTIC"),
    ]
    # Genuinely different carriers that share a code, or whose code cell is wrong
    # in the source document. These must NOT rename.
    REJECT = [
        ("AMERICAN AIRLINE", "AIR INDIA"),      # the Lords sheet's wrong code cell
        ("AVIANCE AIR", "AIR EUROPA"),          # UX listed twice on one sheet
        ("ITA AIRWAYS", "ALITALIA"),
        ("LATAM GROUP", "LAN AIRLINES"),
        ("BATIK AIR", "MALINDO AIRWAYS"),
        ("FIJI AIR", "AIR PACIFIC"),
        ("PARATA AIR", "THAI SMILE AIRWAYS"),
    ]

    def test_accepts(self):
        for sheet, master in self.ACCEPT:
            with self.subTest(pair=(sheet, master)):
                self.assertTrue(names_compatible(sheet, master))

    def test_rejects(self):
        for sheet, master in self.REJECT:
            with self.subTest(pair=(sheet, master)):
                self.assertFalse(names_compatible(sheet, master))

    def test_generic_words_alone_never_make_a_match(self):
        self.assertFalse(names_compatible("AIR", "AIR INDIA"))
        self.assertFalse(names_compatible("AIRLINES", "AIR EUROPA"))


class TestLooksLikeAirlineName(unittest.TestCase):
    def test_rejects_sheet_furniture(self):
        for junk in [
            "18008910375 9891545161 9891545160",
            "lordsxo99@gmail.com",
            "ALL DEALS ARE SUBJECT TO CHANGE WITHOUT PRIOR NOTICE",
            "0.50% Deal Extra on all Domestic Airlines if Issued through our Portal "
            "https://lordstravelsonline.com",
            "Que your PNR to AMADEUS DELVS3**8-T",
            "5.00%",
            "",
            None,
        ]:
            with self.subTest(junk=junk):
                self.assertFalse(looks_like_airline_name(junk))

    def test_accepts_real_names(self):
        for name in ("Virgin Atlantic", "AIR IQ", "US Bangla", "Air Peace", "TAP AIR Portual"):
            with self.subTest(name=name):
                self.assertTrue(looks_like_airline_name(name))


# A miniature master mirroring the shapes that matter in the real one.
MASTER = [
    (1,  "AIR INDIA",          "AI", "FY"),
    (2,  "VIRGIN ATLANTIC",    "VS", None),
    (3,  "AIR EUROPA",         "UX", None),
    (4,  "AMERICAN AIRLINES",  "AA", None),
    (5,  "UGANDA AIRLINES",    "UR", None),
    (6,  "SPICEJET",           "SG", None),
    (7,  "AIR NEW ZEALAND",    "NZ", None),
    (8,  "ALITALIA",           "AZ", None),
    (9,  "AIR FRANCE",         "AF", "FY"),
    (10, "KLM ROYAL DUTCH AIRLINES", "KL", None),
    (11, "BIMAN BANGLADESH AIRLINES", "BG", None),
    (12, "DELTA AIRLINES",     "DL", None),
    (13, "LUFTHANSA",          "LH", None),
    (14, "SWISS",              "LX", None),
]


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.index = AirlineIndex.from_rows(MASTER)

    def test_name_match_uses_the_masters_canonical_name(self):
        m = self.index.resolve("Virgin Atlantic (XO SALE)", "VS (XO SALE)")
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.saved_name, "VIRGIN ATLANTIC")
        self.assertEqual(m.airline_id, 2)

    def test_meaningful_qualifier_still_resolves_to_the_base_carrier(self):
        for cell in ("AIR INDIA (INTL) (OB/IB till 31 Mar 2026)",
                     "AIR INDIA (DOM) (S&T CLS ) (OB 1st Apr 2026 Onwards)",
                     "AIR INDIA (DOM) (PRIVATE FARES )"):
            with self.subTest(cell=cell):
                m = self.index.resolve(cell, "AI (LORDS ISSUANCE)")
                self.assertEqual(m.status, RESOLVED)
                self.assertEqual(m.saved_name, "AIR INDIA")

    def test_wrong_code_cell_does_not_rename(self):
        """The whole reason resolution is name-first.

        The Lords sheet really prints ['American Airline', 'AI (1st Apr 2026)
        (LORDS ISSUANCE)']. Code-first would file a 2% American Airlines deal
        under Air India and look entirely normal doing it.
        """
        m = self.index.resolve("American Airline", "AI (1st Apr 2026) (LORDS ISSUANCE)")
        self.assertEqual(m.status, CONFLICT)
        self.assertEqual(m.saved_name, "American Airline")
        self.assertNotEqual(m.saved_name, "AIR INDIA")
        self.assertIn("AIR INDIA", m.note)

    def test_shared_code_between_two_carriers_conflicts(self):
        # The same sheet gives UX to both Air Europa and Aviance Air.
        self.assertEqual(self.index.resolve("Air Europa (XO SALE)", "UX (XO SALE)").status, RESOLVED)
        m = self.index.resolve("Aviance Air (XO SALE)", "UX (XO SALE)")
        self.assertEqual(m.status, CONFLICT)
        self.assertEqual(m.saved_name, "Aviance Air")

    def test_code_only_match_renames_when_the_names_agree(self):
        m = self.index.resolve("AIR NEWZELAND( SIN/CHC or AKL & V.V", "NZ (XO SALE)")
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.saved_name, "AIR NEW ZEALAND")

    def test_multi_carrier_cell_is_never_renamed(self):
        m = self.index.resolve("AirFrance / KLM / Delta (XO SALE)", "AF/KL/DL (XO SALE)")
        self.assertEqual(m.status, MULTI_CARRIER)
        self.assertEqual(m.saved_name, "AirFrance / KLM / Delta")

    def test_extract_and_confirm_agree_on_multi_carrier(self):
        """Regression: the code reaches confirm ALREADY cleaned to one designator,
        so "AF/KL/DL" arrives as "AF". Detecting multi-carrier from the code cell
        alone made the review table say "multi-carrier" while the save silently
        renamed the row to AIR FRANCE. Both stages must agree."""
        for name, raw, cleaned in [
            ("AirFrance / KLM / Delta (XO SALE)", "AF/KL/DL (XO SALE)", "AF"),
            ("AIRFRANCE/KLM/DL", "KL/AF/DL", "KL"),
        ]:
            with self.subTest(name=name):
                at_extract = self.index.resolve(name, raw)
                at_confirm = self.index.resolve(name, cleaned)
                self.assertEqual(at_extract.status, MULTI_CARRIER)
                self.assertEqual(at_confirm.status, at_extract.status)
                self.assertEqual(at_confirm.saved_name, at_extract.saved_name)

    def test_a_route_slash_is_not_a_second_carrier(self):
        """Akbar prints "AIR NEWZELAND( SIN/CHC or AKL & V.V" — SIN/CHC is a
        route. Treating it as multi-carrier would block a legitimate rename."""
        m = self.index.resolve("AIR NEWZELAND( SIN/CHC or AKL & V.V", "NZ")
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.saved_name, "AIR NEW ZEALAND")

    def test_missing_airline_is_a_creation_candidate(self):
        m = self.index.resolve("Thai Vietjet (XO SALE)", "VZ (XO SALE)")
        self.assertEqual(m.status, NEW)
        self.assertEqual(m.display_name, "Thai Vietjet")
        self.assertEqual(m.code, "VZ")

    def test_no_code_means_it_cannot_be_created(self):
        # airlines.iata_code is NOT NULL — never fabricate one.
        m = self.index.resolve("AIR IQ", "")
        self.assertEqual(m.status, UNRESOLVED)
        self.assertIsNone(m.code)

    def test_junk_row_is_never_a_creation_candidate(self):
        m = self.index.resolve("Airport Assistance Fee", "")
        self.assertEqual(m.status, UNRESOLVED)
        m = self.index.resolve("SENT US MAIL FOR ISSUANCE ON lordsxo99@gmail.com", "BG")
        self.assertNotEqual(m.status, NEW)

    def test_channel_qualifier_never_survives_into_a_saved_name(self):
        for name, code in [
            ("Virgin Atlantic (XO SALE)", "VS"),
            ("Thai Vietjet (XO SALE)", "VZ"),          # NEW
            ("Aviance Air (XO SALE)", "UX"),           # CONFLICT
            ("NOK AIR (LORDS ISSUANCE)", "DD"),        # NEW
            ("AIR IQ", ""),                            # UNRESOLVED
        ]:
            with self.subTest(name=name):
                saved = self.index.resolve(name, code).saved_name.upper()
                self.assertNotIn("XO SALE", saved)
                self.assertNotIn("LORDS ISSUANCE", saved)

    def test_ambiguous_when_two_master_rows_share_a_name_key(self):
        index = AirlineIndex.from_rows(MASTER + [(99, "AIR INDIA", "I5", None)])
        m = index.resolve("AIR INDIA (INTL)", "AI")
        self.assertEqual(m.status, AMBIGUOUS)
        self.assertEqual(m.saved_name, "AIR INDIA (INTL)")

    def test_adopt_makes_a_new_airline_resolvable(self):
        class _Row:
            id, name, iata_code, contract_year = 42, "THAI VIETJET AIR", "VZ", None
        self.assertEqual(self.index.resolve("Thai Vietjet (XO SALE)", "VZ").status, NEW)
        self.index.adopt(_Row())
        m = self.index.resolve("Thai Vietjet (XO SALE)", "VZ")
        self.assertEqual(m.status, RESOLVED)
        self.assertEqual(m.saved_name, "THAI VIETJET AIR")

    def test_contract_year_lookup_is_case_insensitive(self):
        # The master's casing is inconsistent; the fallback used to miss entirely
        # because the name still carried its "(XO SALE)" qualifier.
        self.assertEqual(self.index.contract_year_for("air india"), "FY")
        self.assertEqual(self.index.contract_year_for("AIR INDIA"), "FY")
        self.assertIsNone(self.index.contract_year_for("Virgin Atlantic"))
        self.assertIsNone(self.index.contract_year_for("AIR INDIA (INTL) (XO SALE)"))


class TestSplitCarriers(unittest.TestCase):
    """One row quoting one rate for several carriers is several deals.

    "AirFrance / KLM / Delta" at 2.50 / 3.00 / 3.00 is three airlines x three
    cabins = nine entries, and leaving it as a single row named
    "AirFrance / KLM / Delta" makes all three unmatchable against a ticket.
    """

    def setUp(self):
        self.index = AirlineIndex.from_rows(MASTER)

    def names(self, raw_name, raw_code):
        return [m.canonical_name for m in self.index.split_carriers(raw_name, raw_code)]

    def test_three_carriers(self):
        got = self.names("AirFrance / KLM / Delta (XO SALE)", "AF/KL/DL (XO SALE)")
        self.assertEqual(got, ["AIR FRANCE", "KLM ROYAL DUTCH AIRLINES", "DELTA AIRLINES"])

    def test_cells_disagreeing_on_order_are_not_zipped(self):
        """Akbar prints the name "AIRFRANCE/KLM/DL" against the code "KL/AF/DL".
        Positional pairing would file Air France's rate under KLM."""
        got = self.names("AIRFRANCE/KLM/DL", "KL/AF/DL")
        self.assertEqual(sorted(got), ["AIR FRANCE", "DELTA AIRLINES", "KLM ROYAL DUTCH AIRLINES"])

    def test_transposed_columns(self):
        """The name cell holds the codes and the code cell holds the names —
        there is no usable designator, so this row resolves as UNRESOLVED, yet it
        still names two carriers."""
        got = self.names("AF/KL (NDC ) (LORDS ISSUANCE)", "AirFrance / KLM (LORDS ISSUANCE)")
        self.assertEqual(sorted(got), ["AIR FRANCE", "KLM ROYAL DUTCH AIRLINES"])

    def test_qualifier_after_the_carrier_list(self):
        for name, code in [
            ("LUFTHANSA /SWISS ROW (REST OF WORLD) (LORDS ISSUANCE)", "LH/LX -ROW (Rest Of World)"),
            ("LUFTHANSA /SWISS A++ (USA CANADA) (LORDS ISSUANCE)", "LH/LX - A++ (USA CANADA)"),
            ("LUFTHANSA/SWISS AIR (ROW)", "LH/LX"),
            ("LUFTHANSA/SWISS (EXTRA INCENTIVE)", "LH/LX"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.names(name, code), ["LUFTHANSA", "SWISS"])

    def test_single_carrier_rows_never_split(self):
        for name, code in [
            ("Virgin Atlantic (XO SALE)", "VS (XO SALE)"),
            ("AIR INDIA (INTL) (OB/IB till 31 Mar 2026)", "AI (LORDS ISSUANCE)"),
            ("BIMAN BANGLADESH", "BG"),
            # A route, not a second carrier.
            ("AIR NEWZELAND( SIN/CHC or AKL & V.V", "NZ"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.index.split_carriers(name, code), [])

    def test_a_wrong_code_cell_can_never_become_a_split(self):
        """The split must not become a back door around the conflict guard: one
        fragment can never satisfy the >= 2 rule, so "American Airline" + "AI"
        stays a conflict rather than silently resolving to Air India."""
        self.assertEqual(self.index.split_carriers("American Airline", "AI (1st Apr 2026)"), [])
        self.assertEqual(self.index.split_carriers("Aviance Air (XO SALE)", "UX (XO SALE)"), [])

    def test_partial_identification_refuses_to_split(self):
        """Dropping a carrier is worse than leaving the row flagged — the
        reviewer can still read all three names off the untouched cell."""
        index = AirlineIndex.from_rows([r for r in MASTER if r[2] != "DL"])
        self.assertEqual(index.split_carriers("AirFrance / KLM / Delta", "AF/KL/DL"), [])

    def test_split_entries_are_fully_resolved(self):
        for m in self.index.split_carriers("AirFrance / KLM / Delta (XO SALE)", "AF/KL/DL (XO SALE)"):
            self.assertEqual(m.status, RESOLVED)
            self.assertEqual(m.saved_name, m.canonical_name)
            self.assertIn(m.code, ("AF", "KL", "DL"))
            # A split row must re-resolve cleanly on save, or confirm would
            # write a different name than the review table showed.
            again = self.index.resolve(m.saved_name, m.code)
            self.assertEqual(again.status, RESOLVED)
            self.assertEqual(again.saved_name, m.saved_name)


if __name__ == "__main__":
    unittest.main()
