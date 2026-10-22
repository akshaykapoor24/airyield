"""Who a statement file is for, read off its name and the lines above its header — no DB.

Internal Statement → Upload Statement pre-selects the customer the file names: "GLOBE 01 AUG
TO 31 AUG.xls" is Globe Air Travels'. Pinned here: the real GLOBE file names and title lines,
the header used only when the name says nothing, the workspace's own name never taken for a
customer, ambiguity said rather than guessed, and the branch of an agency picked only when
something decides it.

Run:  python -m unittest discover backend/tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.statement_party import (  # noqa: E402
    AMBIGUOUS, RESOLVED, UNRESOLVED, PartyRow, PastUpload, identify,
)

GLOBE = PartyRow("agency", 28, "Globe Air Travels", ("NEW DELHI", "New Delhi", "Delhi"))
GLOBE_KOLKATA = PartyRow("agency", 29, "Globe Air Travels", ("KOLKATA", "Kolkata", "West Bengal"))
LORDS = PartyRow("agency", 31, "Lords Travel Pvt Ltd", ("MUMBAI",))
AKBAR = PartyRow("agency", 40, "Akbar Travels of India", ("MUMBAI",))
INFOSYS = PartyRow("corporate", 7, "Infosys Limited", ("Bengaluru",))
ROWS = [GLOBE, LORDS, AKBAR, INFOSYS]
TENANT = ["TRIUMPHH TRAVEL N MORE PRIVATE LIMITED"]
# The real GLOBE statement's lines above its header.
GLOBE_HEADER = ["TICKET STATEMENT", "For The Period 16 August 2026 To 22 August 2026",
                "GLOBE ALL INDIA SERVICES LIMITED - (WEST BENGAL)", "INR"]


class FileNameTests(unittest.TestCase):
    def test_the_real_globe_file_names(self):
        for name in ("GLOBE 01 AUG TO 31 AUG.xls", "GLOBE OUR 08 15 AUG 26.xls", "GLOBE 16 22 AUG 26.xls",
                     "GLOBE 23 31 AUG 26 (2).xls"):
            with self.subTest(name=name):
                g = identify(name, [], ROWS, [], TENANT)
                self.assertEqual((g.status, g.customer_type, g.party_id, g.source, g.matched),
                                 (RESOLVED, "agency", 28, "file name", "GLOBE"))

    def test_a_corporate(self):
        g = identify("INFOSYS JULY STATEMENT.xlsx", [], ROWS)
        self.assertEqual((g.status, g.customer_type, g.party_id), (RESOLVED, "corporate", 7))

    def test_the_header_when_the_name_says_nothing(self):
        g = identify("statement 16-22.xls", GLOBE_HEADER, ROWS)
        self.assertEqual((g.status, g.party_id, g.source), (RESOLVED, 28, "statement header"))

    def test_the_file_name_outranks_the_header(self):
        g = identify("LORDS 01 07 AUG.xlsx", GLOBE_HEADER, ROWS)
        self.assertEqual((g.status, g.party_id, g.source), (RESOLVED, 31, "file name"))

    def test_nothing_named_is_left_to_the_user(self):
        for name in ("test1.xlsx", "STATEMENT 01-07 AUG.xlsx", ""):
            with self.subTest(name=name):
                self.assertEqual(identify(name, [], ROWS).status, UNRESOLVED)

    def test_the_workspaces_own_name_is_not_a_customer(self):
        rows = ROWS + [PartyRow("agency", 99, "Triumphh Travels", ())]
        g = identify("TRIUMPHH BSP STATEMENT 08-15TH AUG 26.xlsx", [], rows, [], TENANT)
        self.assertEqual(g.status, UNRESOLVED)

    def test_paperwork_and_months_are_not_names(self):
        rows = [PartyRow("agency", 5, "Statement Travels", ()), PartyRow("agency", 6, "March Tours", ())]
        self.assertEqual(identify("BSP STATEMENT MARCH 2026.xlsx", [], rows).status, UNRESOLVED)

    def test_a_whole_name_written_without_spaces(self):
        rows = [PartyRow("agency", 8, "Make My Trip", ())]
        self.assertEqual(identify("MAKEMYTRIP 01-15 SEP.xlsx", [], rows).party_id, 8)


class AmbiguityTests(unittest.TestCase):
    def test_two_companies_named_is_asked(self):
        g = identify("LORDS and AKBAR combined.xlsx", [], ROWS)
        self.assertEqual((g.status, g.customer_type), (AMBIGUOUS, "agency"))
        self.assertEqual({c["id"] for c in g.candidates}, {31, 40})

    def test_an_agency_and_a_corporate_named_is_asked_with_no_type(self):
        g = identify("LORDS INFOSYS.xlsx", [], ROWS)
        self.assertEqual((g.status, g.customer_type), (AMBIGUOUS, None))

    def test_two_branches_with_nothing_to_decide(self):
        g = identify("GLOBE 01 AUG TO 31 AUG.xls", [], [GLOBE, GLOBE_KOLKATA])
        self.assertEqual((g.status, g.customer_type, g.name), (AMBIGUOUS, "agency", "Globe Air Travels"))
        self.assertEqual({c["id"] for c in g.candidates}, {28, 29})

    def test_a_branch_named_in_the_header_decides(self):
        g = identify("GLOBE OUR 08 15 AUG 26.xls", GLOBE_HEADER, [GLOBE, GLOBE_KOLKATA])
        self.assertEqual((g.status, g.party_id, g.narrowed_by), (RESOLVED, 29, "branch"))

    def test_the_last_upload_decides_first(self):
        g = identify("GLOBE OUR 08 15 AUG 26.xls", GLOBE_HEADER, [GLOBE, GLOBE_KOLKATA],
                     [PastUpload("agency", 28)])
        self.assertEqual((g.status, g.party_id, g.narrowed_by), (RESOLVED, 28, "previous upload"))

    def test_a_past_upload_of_another_type_does_not_decide(self):
        g = identify("GLOBE 01 AUG TO 31 AUG.xls", [], [GLOBE, GLOBE_KOLKATA], [PastUpload("corporate", 28)])
        self.assertEqual(g.status, AMBIGUOUS)


if __name__ == "__main__":
    unittest.main()
