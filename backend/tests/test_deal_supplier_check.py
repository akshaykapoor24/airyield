"""Is a deal file from the supplier picked on the upload form? Pure — no DB, no files.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.deal_supplier_check import Candidate, FileText, check, distinctive  # noqa: E402

AIRLINES = ["Air India", "Air India Express", "Royal Jordanian", "IndiGo", "Make Air"]
AKBAR = Candidate("Akbar Travels of India Private Limited", "Akbar Travels of India Private Limited", [30], "AG-0003")
LORDS = Candidate("Lords Travel Pvt. Ltd.", "Lords Travel Pvt. Ltd.", [29], "AG-0002")
MMT = Candidate("Make My Trip (India) Private Limited", "Make My Trip (India) Private Limited", [32], "AG-0005")
ROYAL = Candidate("Royal Travels", "Royal Travels")
AIR_INDIA_LTD = Candidate("Air India Limited", "Air India Limited")
OTHERS = [AKBAR, LORDS, MMT, ROYAL, AIR_INDIA_LTD]

LORDS_PDF = FileText(
    head="LORDS DEAL 18 MAR LORDS Deal Sheet Eff 18 Mar 2026",
    body="AIR INDIA (INTL) AI (LORDS ISSUANCE) 2.00% ... make sure IATA entry ... AI (LORDS ISSUANCE)",
)


def run(text, selected):
    return check(text, selected, [o for o in OTHERS if o is not selected], AIRLINES)


class NameTest(unittest.TestCase):
    def test_distinctive_words(self):
        self.assertEqual(distinctive("Lords Travel Pvt. Ltd."), ["lords"])
        self.assertEqual(distinctive("Air India Limited"), [])

    def test_wrong_supplier_is_a_mismatch(self):
        v = run(LORDS_PDF, AKBAR)
        self.assertEqual(v.status, "mismatch")
        self.assertEqual(v.found, LORDS.label)
        self.assertEqual(v.found_agency_ids, [29])

    def test_right_supplier_matches(self):
        self.assertEqual(run(LORDS_PDF, LORDS).status, "match")

    def test_a_stray_word_does_not_beat_the_title(self):
        # "make" is in the text, but the title says LORDS.
        self.assertEqual(run(LORDS_PDF, MMT).status, "mismatch")

    def test_airline_names_are_not_suppliers(self):
        text = FileText(head="deal sheet", body="Royal Jordanian 3% Royal Jordanian 2% Air India 1% Air India 4%")
        self.assertEqual(run(text, AKBAR).status, "unknown")

    def test_nobody_named_is_unknown(self):
        self.assertEqual(run(FileText(head="march deals", body="IndiGo 2% IndiGo 3%"), AKBAR).status, "unknown")

    def test_one_passing_mention_is_not_enough(self):
        text = FileText(head="march deals", body="ref: lords circular")
        self.assertEqual(run(text, AKBAR).status, "unknown")

    def test_compact_name(self):
        text = FileText(head="MakeMyTrip deal sheet", body="")
        self.assertEqual(run(text, MMT).status, "match")


class VocabularyTest(unittest.TestCase):
    """Supplier-master names that share a word with every deal sheet."""

    MASTER = [Candidate("Global Business Services", "Global Business Services"),
              Candidate("Prem Travels", "Prem Travels"),
              Candidate("Vicky Tourism Private Limited", "Vicky Tourism Private Limited")]

    def run_with(self, text):
        return check(text, AKBAR, [LORDS, *self.MASTER], AIRLINES)

    def test_cabin_words_are_not_suppliers(self):
        # Mirror: no supplier named, but "Business" and "Prem Eco" on every page.
        text = FileText(head="Mirror PCC Deal Sheet",
                        body="Eco 1% Prem Eco 2% Business 3% Prem Eco 1% Business 2% Prem Eco")
        self.assertEqual(self.run_with(text).status, "unknown")

    def test_whole_master_name_in_the_text_counts(self):
        # Vicky: the file name says nothing, the footer names the company in full.
        text = FileText(head="Deal Sheet Effective 03Oct26",
                        body="VICKY AMEX CARD ... Vicky Tourism Limited ... vickyonline.in")
        v = self.run_with(text)
        self.assertEqual((v.status, v.found), ("mismatch", "Vicky Tourism Private Limited"))

    def test_own_agency_outranks_master(self):
        akbar_master = Candidate("Akbar Online Booking Co. Private Limited",
                                 "Akbar Online Booking Co. Private Limited")
        text = FileText(head="AKBAR TRAVELS PLB SHEET", body="akbartravels.in Akbar Travels")
        v = check(text, LORDS, [akbar_master, AKBAR], AIRLINES)
        self.assertEqual(v.found, AKBAR.label)


class CodeTest(unittest.TestCase):
    def test_code_match(self):
        v = run(FileText(head="x", body="", supplier_codes=["AG-0003"]), AKBAR)
        self.assertEqual((v.status, v.basis), ("match", "code"))

    def test_code_mismatch_names_the_owner(self):
        v = run(FileText(head="Akbar deal", body="", supplier_codes=["AG-0002"]), AKBAR)
        self.assertEqual(v.status, "mismatch")     # the code wins over the name
        self.assertEqual(v.found_agency_ids, [29])

    def test_code_of_another_branch_is_named(self):
        # Mumbai branch picked, the template carries the Delhi branch's code.
        akbar_bom = Candidate("Akbar Travels — Mumbai · GDS", AKBAR.name, [41], "AG-0009")
        akbar_del = Candidate("Akbar Travels — Delhi · GDS", AKBAR.name, [30], "AG-0003")
        v = check(FileText(head="x", body="", supplier_codes=["AG-0003"]), akbar_bom,
                  [LORDS], AIRLINES, code_owners=[akbar_del])
        self.assertEqual((v.status, v.found_agency_ids), ("mismatch", [30]))

    def test_unknown_code(self):
        v = run(FileText(head="x", body="", supplier_codes=["ZZ-9"]), AKBAR)
        self.assertEqual(v.status, "mismatch")
        self.assertIn("not one of your agencies", v.message)


if __name__ == "__main__":
    unittest.main()
