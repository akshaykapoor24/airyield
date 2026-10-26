"""Multi-supplier deal sheets: which Agency Master row each Source value names.

The Source values are the real ones from a weekly vendor-comparison sheet — AKBAR,
BRIGHTSUN, RIYA, TSC, TRIPJACK, YATRA, YATRA(TSI), YATRA(YFB). What is pinned here is
the conservative rule: an agency is PICKED only on strong evidence (or because the user
picked it last time); everything weaker is offered, never chosen.

No DB, no network.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.deal_vendor_resolver import (  # noqa: E402
    AMBIGUOUS, BLANK, MATCHED, NOT_ONBOARDED, REMEMBERED, SOURCE_MAP_KEY, SUGGESTED,
    AgencyRef, learn_mappings, multi_vendor_label, remembered_from, resolve_source, source_key,
)

AKBAR_GDS = AgencyRef(1, "Akbar Travels of India Pvt Ltd", "GDS", "DEL01", "Delhi", "AG-0001")
AKBAR_LCC = AgencyRef(2, "Akbar Travels of India Pvt Ltd", "LCC", "DEL01", "Delhi", "AG-0001")
RIYA_BOM = AgencyRef(3, "Riya Travel & Tours (India) Pvt Ltd", "GDS", "BOM01", "Mumbai", "AG-0002")
RIYA_DEL = AgencyRef(4, "Riya Travel & Tours (India) Pvt Ltd", "GDS", "DEL02", "Delhi", "AG-0003")
TSI_YATRA = AgencyRef(5, "TSI Yatra Pvt Ltd", "GDS", "MAIN", None, "AG-0004")
YATRA_ONLINE = AgencyRef(6, "Yatra Online Ltd", "GDS", "MAIN", None, "AG-0005")
YATRA_FB = AgencyRef(7, "Yatra For Business Pvt Ltd", "GDS", "MAIN", None, "AG-0006")
BRIGHTSUN_LCC = AgencyRef(8, "Brightsun Travel (India) Pvt Ltd", "LCC", "MAIN", None, "AG-0007")
SKY_CONNECT = AgencyRef(9, "The Sky Connect", "GDS", "MAIN", None, "AG-0008")
TRIP_JACK = AgencyRef(10, "Trip Jack Pvt Ltd", "GDS", "MAIN", None, "AG-0009")

BOOK = [AKBAR_GDS, AKBAR_LCC, RIYA_BOM, RIYA_DEL, TSI_YATRA, YATRA_ONLINE, YATRA_FB,
        BRIGHTSUN_LCC, SKY_CONNECT, TRIP_JACK]


def resolve(cell, channel="GDS", book=BOOK, remembered=None):
    return resolve_source(cell, channel, book, remembered)


class MatchedTest(unittest.TestCase):
    """Picked automatically: the Source names exactly one agency on the row's channel."""

    def test_short_name_picks_the_row_on_this_channel(self):
        self.assertEqual((resolve("AKBAR").status, resolve("AKBAR").agency_id), (MATCHED, 1))
        self.assertEqual(resolve("AKBAR", "LCC").agency_id, 2)

    def test_qualifier_picks_the_agency_it_names(self):
        # The sheet keeps YATRA, YATRA(TSI) and YATRA(YFB) apart — so must the upload.
        self.assertEqual(resolve("YATRA(TSI)").agency_id, 5)
        self.assertEqual(resolve("YATRA(YFB)").agency_id, 7)    # Y-F-B are its initials

    def test_branch_in_the_cell_picks_the_branch(self):
        m = resolve("RIYA MUMBAI")
        self.assertEqual((m.status, m.agency_id), (MATCHED, 3))

    def test_name_written_without_spaces(self):
        self.assertEqual(resolve("TRIPJACK").agency_id, 10)

    def test_agency_code_in_the_cell(self):
        self.assertEqual(resolve("AG-0003").agency_id, 4)


class NeedsAPersonTest(unittest.TestCase):
    """Never picked: the reviewer chooses, and the choice is offered."""

    def test_two_branches_is_ambiguous(self):
        m = resolve("RIYA")
        self.assertEqual((m.status, m.agency_id, sorted(m.candidates)), (AMBIGUOUS, None, [3, 4]))

    def test_plain_yatra_is_not_the_tsi_entity(self):
        # TSI Yatra says something the cell does not, so it is not even offered
        # while two agencies match the cell exactly.
        m = resolve("YATRA")
        self.assertEqual((m.status, sorted(m.candidates)), (AMBIGUOUS, [6, 7]))

    def test_acronym_is_only_suggested(self):
        m = resolve("TSC")
        self.assertEqual((m.status, m.agency_id, m.candidates), (SUGGESTED, None, [9]))
        self.assertIn("initials", m.note)

    def test_partial_name_is_only_suggested(self):
        money = AgencyRef(11, "Money Yatra Pvt Ltd", "GDS")
        m = resolve("YATRA", book=[money])
        self.assertEqual((m.status, m.candidates), (SUGGESTED, [11]))

    def test_wrong_channel_is_only_suggested(self):
        m = resolve("BRIGHTSUN")                 # onboarded on LCC, the row is GDS
        self.assertEqual((m.status, m.agency_id, m.candidates), (SUGGESTED, None, [8]))
        self.assertIn("LCC only", m.note)

    def test_unknown_and_blank(self):
        self.assertEqual(resolve("SONDHI").status, NOT_ONBOARDED)
        self.assertEqual(resolve("").status, BLANK)
        self.assertEqual(resolve(None).status, BLANK)


class RememberedTest(unittest.TestCase):
    def test_a_past_decision_settles_an_ambiguous_source(self):
        m = resolve("RIYA", remembered={"riya": 4})
        self.assertEqual((m.status, m.agency_id), (REMEMBERED, 4))

    def test_follows_the_same_branch_onto_the_other_channel(self):
        m = resolve("AKBAR", "LCC", remembered={"akbar": 1})
        self.assertEqual((m.status, m.agency_id), (REMEMBERED, 2))

    def test_a_vanished_agency_falls_back_to_names(self):
        # 99 was deleted or deactivated since — it is not in the book any more.
        m = resolve("AKBAR", remembered={"akbar": 99})
        self.assertEqual((m.status, m.agency_id), (MATCHED, 1))

    def test_learn_takes_the_majority_and_skips_ties(self):
        learned = learn_mappings([
            ("AKBAR", 1), ("AKBAR", 1), ("akbar", 2),
            ("RIYA", 3), ("RIYA", 4),
            ("", 5), ("TSC", None),
        ])
        self.assertEqual(learned, {"akbar": {"source": "AKBAR", "agency_id": 1}})

    def test_newest_statement_wins(self):
        maps = [
            {SOURCE_MAP_KEY: {"akbar": {"source": "AKBAR", "agency_id": 2}}},
            None,
            {"airline": "A/L"},
            {SOURCE_MAP_KEY: {"akbar": {"agency_id": 1}, "riya": {"agency_id": 3}}},
        ]
        self.assertEqual(remembered_from(maps), {"akbar": 2, "riya": 3})

    def test_source_key(self):
        self.assertEqual(source_key(" Yatra (TSI) "), "yatratsi")


class LabelTest(unittest.TestCase):
    def test_one_and_many(self):
        self.assertEqual(multi_vendor_label(["Akbar", "Akbar ", None]), "Akbar")
        self.assertEqual(multi_vendor_label(["Riya", "Akbar", "TSC"]), "3 suppliers: Akbar, Riya, TSC")

    def test_fits_the_column(self):
        names = [f"Supplier Number {i:02d} Travels Private Limited" for i in range(30)]
        label = multi_vendor_label(names)
        self.assertLessEqual(len(label), 300)
        self.assertTrue(label.startswith("30 suppliers: Supplier Number 00"))
        self.assertRegex(label, r"\+\d+ more$")


if __name__ == "__main__":
    unittest.main()
