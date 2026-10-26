"""Third Party GDS: every upload screened against the agency's saved lines — no DB.

The rule (services/tp_gds_reupload.py): each entry of a new file is EXACT (already saved —
left out unless the user saves it again), PARTIAL (the same ticket and event as a saved line
with its passenger, a date or an amount changed — saved and flagged unless the user leaves it
out), IN_FILE (repeats an earlier line of the same file — saved and flagged unless left out)
or NEW, against every statement already saved for the same agency, whatever its period.
Pinned here: what makes two lines the same, the cases the business walked through, the
lookup of the saved lines, the router's use of it, and the migration that keys them.

Run:  python -m unittest discover backend/tests
"""
import asyncio
import importlib.util
import os
import re
import sys
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: E402,F401
from fastapi import HTTPException  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402

from app.api.v1 import statements as router  # noqa: E402
from app.models.statement_row import ThirdPartyGds, ThirdPartyGdsLeftOut  # noqa: E402
from app.models.third_party_statement import ThirdPartyStatement  # noqa: E402
from app.services import tp_gds_reupload as ru  # noqa: E402

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
DEDUP_MIGRATION = VERSIONS / "tp_gds_dedup_01_line_keys.py"
PERIOD_MIGRATION = VERSIONS / "tp_gds_period_01_statement_period.py"
DUPES_MIGRATION = VERSIONS / "tp_gds_dupes_02_partial_and_in_file.py"
LEFT_OUT_MIGRATION = VERSIONS / "tp_gds_left_out_01_left_out_lines.py"
STD_MIGRATION = VERSIONS / "tp_gds_std_01_tax_parts.py"
STD_02_MIGRATION = VERSIONS / "tp_gds_std_02_ssr_gst_parts.py"
STD_03_MIGRATION = VERSIONS / "tp_gds_std_03_refund.py"

USER = SimpleNamespace(id=7, tenant_id=3, full_name="Test User")
AGENCY = SimpleNamespace(id=751, agency_id=28)          # Globe Air Travels, SUPP-0751
WEEK1 = (date(2026, 8, 1), date(2026, 8, 7))
WEEK2 = (date(2026, 8, 8), date(2026, 8, 15))

# Shaped like the real 01–07 Aug statement: an issue and, in the same file, its refund.
ISSUE = {"ticket_number": "4847728655", "ticket_prefix": "235", "ticket_status": "CONFIRMED",
         "issue_date": "2026-03-08", "booking_date": "2026-03-08", "passenger_name": "MR ROTAS KUMAR",
         "base_fare": "68000", "net_amount": "69742.164", "week": "01-07TH AUG 26",
         "sector": "DEL/IST/MAD/AMS/IST/DEL"}
REFUND = {**ISSUE, "ticket_status": "CANCELLED", "issue_date": "2026-08-07", "booking_date": "2026-08-07",
          "base_fare": "-68000", "net_amount": "-69680", "sector": "DEL-IST / IST-MAD / MAD-AMS / AMS-IST / IST-DEL"}
BALANCE = {"row_kind": "closing", "row_label": "BALANCE", "net_amount": "627257.4144"}


def ticket(n: int, **over) -> dict:
    return {"ticket_number": f"58090561{n:02d}", "ticket_status": "CONFIRMED", "issue_date": "2026-08-01",
            "booking_date": "2026-08-01", "passenger_name": f"PAX {n}", "base_fare": str(1000 + n),
            "net_amount": str(1100 + n), "week": "01-07TH AUG 26", **over}


def line(data: dict) -> ThirdPartyGds:
    return ThirdPartyGds(data=data)


def lines(*datas) -> list[ThirdPartyGds]:
    return [line(d) for d in datas]


def earlier(batch_id="B1", file="WEEK 1.xlsx", period=WEEK1, at=datetime(2026, 8, 7, 18, 0)):
    return ru.Earlier(batch_id, file, period[0], period[1], at, 0, 0)


_ids = iter(range(1000, 100000))


def saved_from(datas, batch_id="B1") -> list[ru.Saved]:
    """What `saved_lines` reads for these lines, saved under `batch_id`."""
    out = []
    for d in datas:
        stored = ThirdPartyGds(data=d).data
        out.append(ru.Saved(next(_ids), batch_id, ru.line_key(stored), ru.match_key(stored), stored))
    return out


def screen(new, saved=(), *, uploads=(earlier(),), period=WEEK1, **kw) -> ru.Screen:
    objs = lines(*new)
    return ru.partition(objs, list(saved), earlier=list(uploads), period=period,
                        indexes=list(range(len(objs))), **kw)


def kinds(s: ru.Screen) -> list[str]:
    return [e.kind for e in s.entries]


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeDB:
    """Hands out the given results in order and records each statement it was given."""

    def __init__(self, *results):
        self.results = [_Rows(r) for r in results]
        self.statements, self.log = [], []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return self.results.pop(0) if self.results else _Rows([])

    def add(self, obj):
        self.log.append(("add", obj))

    def add_all(self, objs):
        self.log.append(("add_all", list(objs)))

    async def flush(self):
        self.log.append(("flush", None))


def saved_row(line_id: int, batch_id: str, d: dict, *, file="WEEK 1.xlsx", period=WEEK1,
              at=datetime(2026, 8, 7, 18, 0)) -> tuple:
    """A row as `saved_lines_query` selects it."""
    stored = ThirdPartyGds(data=d)
    cols = [getattr(stored, c.key) for c in ru._SAVED_COLUMNS]
    return (line_id, batch_id, ru.line_key(stored.data), ru.match_key(stored.data), *cols,
            file, period[0], period[1], at, 1, 1)


# ── what makes two lines the same ────────────────────────────────────────────
class KeyTests(unittest.TestCase):
    def test_an_issue_and_its_refund_are_different_entries(self):
        self.assertNotEqual(ru.line_key(ISSUE), ru.line_key(REFUND))
        self.assertNotEqual(ru.match_key(ISSUE), ru.match_key(REFUND))

    def test_statement_level_columns_do_not_matter(self):
        again = {**ISSUE, "week": "08-15TH AUG 26", "invoice_number": "INV-2", "username": "x",
                 "sector": "DEL-IST / IST-MAD"}
        self.assertEqual(ru.line_key(ISSUE), ru.line_key(again))

    def test_float_noise_case_and_spacing_do_not_matter(self):
        a = {**ISSUE, "net_amount": "64927.530999999995", "passenger_name": "Mr  Rotas Kumar "}
        b = {**ISSUE, "net_amount": "64927.531", "passenger_name": "MR ROTAS KUMAR"}
        self.assertEqual(ru.line_key(a), ru.line_key(b))

    def test_ticket_with_or_without_its_prefix(self):
        with_prefix = {**ISSUE, "ticket_number": "2354847728655"}
        self.assertEqual(ru.line_key(with_prefix), ru.line_key(ISSUE))
        self.assertEqual(ru.match_key(with_prefix), ru.match_key(ISSUE))

    def test_a_changed_amount_name_or_date_is_the_same_entry_but_not_the_same_line(self):
        for change in ({"net_amount": "70000"}, {"base_fare": "67000"}, {"issue_date": "2026-03-09"},
                       {"booking_date": "2026-03-09"}, {"passenger_name": "MR R KUMAR"}):
            with self.subTest(change=change):
                self.assertNotEqual(ru.line_key(ISSUE), ru.line_key({**ISSUE, **change}))
                self.assertEqual(ru.match_key(ISSUE), ru.match_key({**ISSUE, **change}))

    def test_pnr_stands_in_for_a_missing_ticket_and_names_its_passenger(self):
        no_ticket = {k: v for k, v in ISSUE.items() if k != "ticket_number"}
        a, b = {**no_ticket, "pnr": "7ayl3s"}, {**no_ticket, "pnr": "7AYL3S"}
        self.assertEqual(ru.line_key(a), ru.line_key(b))
        self.assertEqual(ru.match_key(a), ru.match_key(b))
        # Two passengers on one booking are two entries.
        self.assertNotEqual(ru.match_key(a), ru.match_key({**a, "passenger_name": "MRS KUMAR"}))

    def test_a_line_with_nothing_to_name_it_matches_only_an_identical_line(self):
        scratch = {"customer_name": "ticket 1", "customer_id": "20000", "airline_name": "20000"}
        k = ru.line_key(scratch)
        self.assertIsNotNone(k)
        self.assertIsNone(ru.match_key(scratch))
        self.assertEqual(ru.line_key({**scratch, "week": "08-15TH AUG 26"}), k)
        self.assertNotEqual(ru.line_key({**scratch, "airline_name": "5000"}), k)

    def test_balance_lines_have_no_key(self):
        self.assertIsNone(ru.line_key(BALANCE))
        self.assertIsNone(ru.match_key(BALANCE))

    def test_the_stored_line_gives_the_same_keys_as_the_parsed_one(self):
        self.assertEqual(ru.line_key(ThirdPartyGds(data=ISSUE).data), ru.line_key(ISSUE))
        self.assertEqual(ru.match_key(ThirdPartyGds(data=ISSUE).data), ru.match_key(ISSUE))

    def test_the_key_is_the_old_key_extended_with_the_booked_date(self):
        """tp_gds_dedup_01 stored `base_key`; tp_gds_dupes_02 extends what it stored."""
        dedup = _load(DEDUP_MIGRATION, "tp_gds_dedup_01")
        for d in (ISSUE, REFUND, BALANCE, ticket(7), {**ISSUE, "ticket_number": None, "pnr": "ab12"},
                  {**ISSUE, "passenger_name": None, "first_name": "A", "last_name": "B"},
                  {"customer_name": "ticket 1", "customer_id": "20000", "week": "W"}):
            with self.subTest(d=d.get("ticket_number")):
                self.assertEqual(dedup.entry_keys(d)[0], ru.base_key(d))
                self.assertEqual(ru.extend_key(dedup.entry_keys(d)[0], d.get("booking_date")), ru.line_key(d))

    def test_the_migration_keys_lines_as_the_service_does(self):
        mig = _load(DUPES_MIGRATION, "tp_gds_dupes_02")
        for d in (ISSUE, REFUND, BALANCE, ticket(7), {**ISSUE, "ticket_number": None, "pnr": "ab12"},
                  {"customer_name": "ticket 1", "customer_id": "20000", "week": "W"}):
            with self.subTest(d=d.get("ticket_number")):
                self.assertEqual(mig.extend_key(mig.base_key(d), d.get("booking_date")), ru.line_key(d))
                self.assertEqual(mig.match_key(d), ru.match_key(d))

    def test_differences_name_what_changed(self):
        diff = ru.differences({**ISSUE, "net_amount": "70000", "passenger_name": "MR R KUMAR"}, ISSUE)
        self.assertEqual([(d["field"], d["label"], d["file"], d["saved"]) for d in diff],
                         [("passenger", "Passenger", "MR R KUMAR", "MR ROTAS KUMAR"),
                          ("net_amount", "Net Amount", "70000", "69742.164")])
        self.assertEqual(ru.differences({**ISSUE, "net_amount": "69742.1640000001"}, ISSUE), [])


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parsed(**data) -> ThirdPartyGds:
    """A line as the parser makes it — so an Issue Date left blank is the Booked Date's copy."""
    from app.services import flat_statement
    flat_statement._derive_tp_gds(data)
    return ThirdPartyGds(data=data)


# ── the cases from the business, same agency throughout ──────────────────────
class ScenarioTests(unittest.TestCase):
    def test_1_a_new_user_uploads_01_07_and_everything_is_new(self):
        s = screen([ticket(i) for i in range(5)] + [BALANCE], uploads=())
        self.assertEqual(kinds(s), ["new"] * 5)
        d = s.decide()
        self.assertEqual((len(d.kept), d.kept_entries, len(d.left_out)), (6, 5, 0))
        self.assertIsNone(s.refusal(d))
        self.assertTrue(all(o.duplicate_kind is None for o in d.kept))

    def test_2_the_same_01_07_file_again_is_all_already_uploaded_and_not_saved(self):
        week = [ticket(i) for i in range(4)]
        s = screen(week + [BALANCE], saved_from(week), uploads=[earlier(file="TRIUMPHH 01-07.xlsx")])
        self.assertEqual(kinds(s), ["exact"] * 4)
        d = s.decide()
        self.assertEqual(s.refusal(d), "All 4 entries of this file are already saved (in TRIUMPHH 01-07.xlsx) "
                                       "— there is nothing new to save.")
        self.assertEqual(d.duplicate_of, "B1")
        self.assertEqual(d.left_net, sum(Decimal(1100 + i) for i in range(4)))

    def test_2b_the_user_can_save_them_again_and_they_are_flagged(self):
        week = [ticket(i) for i in range(2)]
        saved = saved_from(week)
        s = screen(week, saved)
        d = s.decide({"exact": "save"})
        self.assertIsNone(s.refusal(d))
        self.assertEqual([(o.duplicate_kind, o.duplicate_of_id) for o in d.kept],
                         [("exact", saved[0].id), ("exact", saved[1].id)])

    def test_3_01_07_again_with_extra_tickets_saves_only_the_extras(self):
        week = [ticket(i) for i in range(20)]
        s = screen(week + [ticket(i) for i in range(20, 25)] + [BALANCE], saved_from(week))
        self.assertEqual(s.counts["exact"], 20)
        self.assertEqual(s.counts["new"], 5)
        d = s.decide()
        self.assertEqual([o.data.get("passenger_name") for o in d.kept],
                         [f"PAX {i}" for i in range(20, 25)] + [None])        # + the balance line
        self.assertEqual(len(d.left_out), 20)

    def test_4_a_changed_amount_name_or_booked_date_is_a_partial_duplicate_saved_and_flagged(self):
        saved = saved_from([ticket(1), ticket(2), ticket(3)])
        s = screen([ticket(1, net_amount="1250"), ticket(2, passenger_name="MR PAX TWO"),
                    ticket(3, booking_date="2026-08-03")], saved)
        self.assertEqual(kinds(s), ["partial"] * 3)
        self.assertEqual([[f["field"] for f in e.fields] for e in s.entries],
                         [["net_amount"], ["passenger"], ["booking_date"]])
        self.assertEqual((s.entries[0].fields[0]["file"], s.entries[0].fields[0]["saved"]), ("1250", "1101"))
        d = s.decide()
        self.assertEqual([(o.duplicate_kind, o.duplicate_of_id, o.duplicate_fields) for o in d.kept],
                         [("partial", saved[0].id, "net_amount"), ("partial", saved[1].id, "passenger"),
                          ("partial", saved[2].id, "booking_date")])

    def test_4b_partial_duplicates_can_be_left_out(self):
        s = screen([ticket(1, net_amount="1250"), ticket(9)], saved_from([ticket(1)]))
        d = s.decide({"partial": "skip"})
        self.assertEqual([o.data["passenger_name"] for o in d.kept], ["PAX 9"])
        self.assertEqual(dict(d.left_kinds), {"partial": 1})

    def test_5_08_15_carrying_01_07_tickets_finds_them_whatever_the_period(self):
        first_week = [ticket(i) for i in range(3)]
        second = first_week[:2] + [ticket(i, booking_date="2026-08-09", issue_date="2026-08-09",
                                          week="08-15TH AUG 26") for i in range(10, 13)]
        s = screen(second, saved_from(first_week), period=WEEK2)
        self.assertEqual(kinds(s), ["exact", "exact", "new", "new", "new"])
        listed = s.preview()["listed"]
        self.assertEqual([(r["index"], r["kind"], r["source_file"], r["period_label"]) for r in listed],
                         [(0, "exact", "WEEK 1.xlsx", "01–07 Aug 2026"), (1, "exact", "WEEK 1.xlsx", "01–07 Aug 2026")])

    def test_6_a_ticket_whose_date_moved_into_08_15_rest_the_same_is_a_partial(self):
        """Issue Date copied from the Booked Date on both sides: one change, not two."""
        before = parsed(ticket_number="5809056101", ticket_status="CONFIRMED", booking_date="2026-08-06",
                        passenger_name="PAX 1", base_fare="1001", net_amount="1101")
        after = parsed(ticket_number="5809056101", ticket_status="CONFIRMED", booking_date="2026-08-09",
                       passenger_name="PAX 1", base_fare="1001", net_amount="1101")
        stored = before.data
        saved = [ru.Saved(1, "B1", ru.line_key(stored), ru.match_key(stored), stored)]
        s = ru.partition([after], saved, earlier=[earlier()], period=WEEK2, indexes=[0])
        self.assertEqual(kinds(s), ["partial"])
        self.assertEqual([f["field"] for f in s.entries[0].fields], ["booking_date"])
        self.assertEqual(s.decide().kept[0].duplicate_kind, "partial")

    def test_7_a_ticket_twice_in_the_same_file_is_repeated_in_file_saved_and_flagged(self):
        s = screen([ticket(1), ticket(2), ticket(1), ticket(2, net_amount="999")], uploads=())
        self.assertEqual(kinds(s), ["new", "new", "in_file", "in_file"])
        self.assertEqual([e.twin_index for e in s.entries[2:]], [0, 1])
        self.assertEqual(s.entries[2].fields, [])
        self.assertEqual([f["field"] for f in s.entries[3].fields], ["net_amount"])
        d = s.decide()
        self.assertEqual([o.duplicate_kind for o in d.kept], [None, None, "in_file", "in_file"])
        self.assertEqual(d.kept[3].duplicate_fields, "net_amount")
        self.assertIsNone(d.kept[2].duplicate_of_id)
        self.assertEqual(len(s.decide({"in_file": "skip"}).kept), 2)

    def test_a_refund_of_a_saved_ticket_is_new(self):
        s = screen([REFUND], saved_from([ISSUE]))
        self.assertEqual(kinds(s), ["new"])

    def test_by_count_one_saved_copy_absorbs_one_repeat(self):
        s = screen([ticket(1), ticket(1)], saved_from([ticket(1)]))
        self.assertEqual(kinds(s), ["exact", "in_file"])
        self.assertEqual(len(s.decide().kept), 1)

    def test_a_saved_line_twice_absorbs_two(self):
        s = screen([ticket(1), ticket(1)], saved_from([ticket(1), ticket(1)]))
        self.assertEqual(kinds(s), ["exact", "exact"])

    def test_a_changed_copy_before_the_exact_one_leaves_the_saved_line_to_the_exact_one(self):
        s = screen([ticket(1, net_amount="1250"), ticket(1)], saved_from([ticket(1)]))
        self.assertEqual(kinds(s), ["partial", "exact"])

    def test_a_partial_is_compared_with_the_closest_and_then_latest_saved_line(self):
        saved = saved_from([ticket(1, net_amount="1200")], "B1") + saved_from([ticket(1, net_amount="1300")], "B2")
        s = screen([ticket(1, net_amount="1400")], saved, uploads=[earlier("B1"), earlier("B2", "WEEK 2.xlsx", WEEK2)])
        self.assertEqual((s.entries[0].kind, s.entries[0].saved.batch_id), ("partial", "B2"))
        s = screen([ticket(1, net_amount="1300", passenger_name="X")], saved,
                   uploads=[earlier("B1"), earlier("B2", "WEEK 2.xlsx", WEEK2)])
        self.assertEqual(len(s.entries[0].fields), 1)                  # only the name, against B2

    def test_a_line_corrected_on_review_to_what_was_saved_is_exact(self):
        saved = saved_from([ticket(1)])
        corrected = line(ticket(1))
        s = ru.partition([corrected], saved, earlier=[earlier()], period=WEEK1, indexes=[0],
                         key_data=[ThirdPartyGds(data=ticket(1, net_amount="1250")).data])
        self.assertEqual(kinds(s), ["exact"])

    def test_a_saved_line_corrected_since_still_matches_the_vendors_resend(self):
        """Its key is the line as the vendor sent it, so the same uncorrected line is exact."""
        as_sent = ticket(1, passenger_name="PAX  1 TYPO")
        corrected = ThirdPartyGds(data=ticket(1)).data
        saved = [ru.Saved(1, "B1", ru.line_key(as_sent), ru.match_key(as_sent), corrected)]
        s = screen([as_sent], saved)
        self.assertEqual(kinds(s), ["exact"])

    def test_row_choices_override_the_bucket(self):
        week = [ticket(i) for i in range(3)]
        s = screen(week + [ticket(3, net_amount="5")], saved_from(week + [ticket(3)]))
        d = s.decide({"rows": {"1": "save", 3: "skip"}})
        self.assertEqual([o.data["passenger_name"] for o in d.kept], ["PAX 1"])
        self.assertEqual(dict(d.saved_kinds), {"exact": 1})
        self.assertEqual(dict(d.left_kinds), {"exact": 2, "partial": 1})

    def test_balance_lines_are_never_compared_and_always_kept(self):
        s = screen([BALANCE, ticket(1)], saved_from([ticket(1)]))
        self.assertEqual((len(s.entries), s.balance_lines), (1, 1))
        self.assertIsNotNone(s.refusal(s.decide()))
        self.assertEqual(s.decide({"exact": "save"}).kept[0].data["row_kind"], "closing")

    def test_everything_left_out_by_choice_is_refused_too(self):
        s = screen([ticket(1, net_amount="5"), ticket(2)], saved_from([ticket(1), ticket(2)]))
        self.assertEqual(s.refusal(s.decide({"partial": "skip"})),
                         "Every entry of this file is left out as a duplicate — there is nothing to save.")

    def test_a_new_line_is_always_saved_whatever_its_row_says(self):
        s = screen([ticket(1), ticket(1)], uploads=())
        d = s.decide({"rows": {0: "skip", 1: "skip"}})
        self.assertEqual((d.kept_entries, s.refusal(d)), (1, None))

    def test_preview_and_summary(self):
        saved = saved_from([ticket(1), ticket(2)])
        s = screen([ticket(1), ticket(2, net_amount="1500"), ticket(5), ticket(5), BALANCE], saved)
        p = s.preview()
        self.assertEqual(p["counts"], {"exact": 1, "partial": 1, "in_file": 1, "new": 1})
        self.assertEqual((p["total"], p["balance_lines"]), (4, 1))
        self.assertEqual(p["defaults"], {"exact": "skip", "partial": "save", "in_file": "save"})
        self.assertEqual([(r["index"], r["kind"], r["batch_id"], r["of_index"]) for r in p["rows"]],
                         [(0, "exact", "B1", None), (1, "partial", "B1", None), (3, "in_file", None, 2)])
        self.assertEqual(p["net"], {"exact": "1101", "partial": "1500", "in_file": "1105", "new": "1105"})
        self.assertEqual([(e["batch_id"], e["exact"], e["partial"]) for e in p["earlier"]], [("B1", 1, 1)])
        summary = s.summary(s.decide())
        self.assertEqual((summary["saved"], summary["left_out"], summary["new"], summary["left_out_net"]),
                         ({"exact": 0, "partial": 1, "in_file": 1}, {"exact": 1, "partial": 0, "in_file": 0},
                          3, "1101"))
        self.assertEqual([r["index"] for r in summary["left_out_lines"]], [0])

    def test_only_the_uploads_holding_a_match_are_named(self):
        s = screen([ticket(1)], saved_from([ticket(1)], "B2"),
                   uploads=[earlier("B1"), earlier("B2", "WEEK 2.xlsx", WEEK2)])
        self.assertEqual([e.batch_id for e in s.earlier], ["B2"])


class ChoiceTests(unittest.TestCase):
    def test_defaults_and_overrides(self):
        self.assertEqual(ru.normalize_choices(None), {"exact": "skip", "partial": "save", "in_file": "save", "rows": {}})
        self.assertEqual(ru.normalize_choices({"exact": "save", "rows": {"4": "skip"}})["rows"], {4: "skip"})

    def test_anything_else_is_refused(self):
        for bad in ({"exact": "maybe"}, {"rows": {"x": "save"}}, {"rows": {"1": "keep"}}, {"rows": []},
                    {"new": "skip"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    ru.normalize_choices(bad)


# ── reading what is saved ────────────────────────────────────────────────────
class SavedLinesTests(unittest.TestCase):
    def test_overlapping_uploads_for_the_already_uploaded_question(self):
        sql = _sql(ru.earlier_uploads_query(USER, AGENCY, *WEEK1))
        for cond in ("third_party_statements.tenant_id = 3", "third_party_statements.created_by_id = 7",
                     "third_party_statements.slug = 'tp-gds'",
                     "statement_batch_suppliers.supplier_id = 751", "statement_batch_suppliers.agency_id = 28",
                     "third_party_statements.period_from <= '2026-08-07'",
                     "third_party_statements.period_to >= '2026-08-01'"):
            self.assertIn(cond, sql)

    def test_the_agencys_saved_lines_of_any_period_carrying_a_key(self):
        sql = _sql(ru.saved_lines_query(USER, AGENCY, dedup_keys=["k1"], match_keys=["m1"]))
        for cond in ("third_party_gds.tenant_id = 3", "third_party_gds.created_by_id = 7",
                     "third_party_statements.slug = 'tp-gds'", "statement_batch_suppliers.supplier_id = 751",
                     "statement_batch_suppliers.agency_id = 28", "third_party_gds.dedup_key IN ('k1')",
                     "third_party_gds.match_key IN ('m1')"):
            self.assertIn(cond, sql)
        self.assertNotIn("period_from <=", sql)
        self.assertIn("ORDER BY third_party_statements.uploaded_at ASC", sql)

    def test_an_agency_that_cannot_be_named_compares_with_nothing(self):
        nobody = SimpleNamespace(id=None, agency_id=None)
        self.assertIsNone(ru.saved_lines_query(USER, nobody, dedup_keys=["k"]))
        db = FakeDB()
        out = asyncio.run(ru.compare(db, USER, nobody, WEEK1, lines(ticket(1))))
        self.assertEqual((kinds(out), db.statements), (["new"], []))

    def test_compare_reads_the_saved_lines_and_names_their_uploads(self):
        week1 = saved_row(11, "B1", ticket(1))
        db = FakeDB([week1], [week1])      # found by its exact key, and again by its entry key
        out = asyncio.run(ru.compare(db, USER, AGENCY, WEEK2, lines(ticket(1), ticket(2, net_amount="5")),
                                     indexes=[4, 5]))
        self.assertEqual(kinds(out), ["exact", "new"])
        self.assertEqual((out.entries[0].index, out.entries[0].saved.id), (4, 11))
        self.assertEqual([(e.batch_id, e.source_file, e.period_label) for e in out.earlier],
                         [("B1", "WEEK 1.xlsx", "01–07 Aug 2026")])

    def test_compare_finds_a_partial_by_its_entry_key(self):
        db = FakeDB([], [saved_row(11, "B1", ticket(1))])
        out = asyncio.run(ru.compare(db, USER, AGENCY, WEEK1, lines(ticket(1, net_amount="1250"))))
        self.assertEqual(kinds(out), ["partial"])
        self.assertEqual(out.entries[0].fields[0]["saved"], "1101")

    def test_every_line_is_keyed_and_a_corrected_one_on_its_reading_as_sent(self):
        corrected = line({**ticket(1), "passenger_name": "PAX ONE"})
        plain = line(ticket(2))
        asyncio.run(ru.compare(FakeDB(), USER, AGENCY, None, [corrected, plain],
                               key_data=[ThirdPartyGds(data=ticket(1)).data, None]))
        self.assertEqual((corrected.dedup_key, corrected.match_key), (ru.line_key(ticket(1)), ru.match_key(ticket(1))))
        self.assertEqual(plain.dedup_key, ru.line_key(ticket(2)))

    def test_keys_are_looked_up_in_chunks(self):
        many = [ticket(i % 100, ticket_number=f"9{i:09d}") for i in range(2500)]
        db = FakeDB()
        asyncio.run(ru.compare(db, USER, AGENCY, WEEK1, lines(*many)))
        self.assertEqual(len(db.statements), 4)        # 2 × exact keys, 2 × entry keys


class WeekTests(unittest.TestCase):
    def test_a_week_outside_the_declared_period_is_named(self):
        objs = lines(ticket(1), ticket(2), ticket(3, week="08-15TH AUG 26"), BALANCE)
        out = ru.weeks_outside(objs, WEEK2, date(2026, 10, 17))
        self.assertEqual([(w["week"], w["rows"], w["period_label"]) for w in out],
                         [("01-07TH AUG 26", 2, "01–07 Aug 2026")])


class DatesOutsideTests(unittest.TestCase):
    """Before / after the period — flagged for review, not dropped."""

    def test_the_real_weeks_issue_of_an_older_ticket_is_flagged_and_its_refund_is_not(self):
        out = ru.dates_outside(lines(ISSUE, REFUND, BALANCE), WEEK1, indexes=[0, 1, 2])
        d = out.as_dict()
        self.assertEqual((d["count"], d["period_label"]), (1, "01–07 Aug 2026"))
        self.assertEqual(d["rows"], [{"index": 0, "outside": {"booking_date": "before", "issue_date": "before"}}])

    def test_before_after_and_the_period_ends_themselves(self):
        objs = [parsed(ticket_number="1", booking_date="2026-07-31"),
                parsed(ticket_number="2", booking_date="2026-08-01"),
                parsed(ticket_number="3", booking_date="2026-08-07"),
                parsed(ticket_number="4", booking_date="2026-08-08"),
                parsed(ticket_number="5", booking_date="2026-08-02", issue_date="2026-08-09")]
        rows = ru.dates_outside(objs, WEEK1, indexes=[0, 1, 2, 3, 4]).as_dict()["rows"]
        self.assertEqual(rows, [{"index": 0, "outside": {"booking_date": "before"}},
                                {"index": 3, "outside": {"booking_date": "after"}},
                                {"index": 4, "outside": {"issue_date": "after"}}])

    def test_an_issue_date_copied_from_the_booked_date_is_not_reported_twice(self):
        out = ru.dates_outside([parsed(ticket_number="1", booking_date="2026-08-22")], WEEK1)
        self.assertEqual(out.lines[0]["outside"], {"booking_date": "after"})

    def test_an_unreadable_date_is_flagged_and_a_blank_one_is_not(self):
        out = ru.dates_outside([parsed(ticket_number="1", booking_date="N/A"),
                                parsed(ticket_number="2", passenger_name="NO DATE")], WEEK1, indexes=[0, 1])
        self.assertEqual(out.as_dict()["rows"], [{"index": 0, "outside": {"booking_date": "unreadable"}}])

    def test_skipped_rows_and_a_missing_period_are_not_checked(self):
        objs = lines(ISSUE, ticket(1, issue_date="2026-09-01"))
        self.assertEqual(ru.dates_outside(objs, WEEK1, indexes=[0, 1], skip={0}).as_dict()["count"], 1)
        self.assertEqual(ru.dates_outside(objs, None).as_dict()["count"], 0)


# ── the router ───────────────────────────────────────────────────────────────
class PeriodFormTests(unittest.TestCase):
    def test_required_for_third_party_gds(self):
        self.assertEqual(router._period_form("tp-gds", "2026-08-01", "2026-08-07"), WEEK1)
        for a, b in ((None, "2026-08-07"), ("2026-08-01", ""), ("01/08/2026", "2026-08-07"),
                     ("2026-08-08", "2026-08-07"), ("2025-01-01", "2026-08-07")):
            with self.subTest(a=a, b=b):
                with self.assertRaises(HTTPException) as cm:
                    router._period_form("tp-gds", a, b)
                self.assertEqual(cm.exception.status_code, 400)

    def test_ignored_by_every_other_type(self):
        for slug in ("tp-lcc", "tp-api", "ndc", "mo-gds"):
            with self.subTest(slug=slug):
                self.assertIsNone(router._period_form(slug, "2026-08-01", "2026-08-07"))

    def test_guess_from_the_file_name(self):
        out = asyncio.run(router.guess_period("tp-gds", file_name="TRIUMPHH BSP STATMENT 01-07TH AUG 26 (5).xlsx",
                                              current_user=USER))
        self.assertEqual((out["period_from"], out["period_to"]), ("2026-08-01", "2026-08-07"))


class ChoicesFormTests(unittest.TestCase):
    def test_third_party_gds_reads_them_and_fills_in_the_defaults(self):
        self.assertEqual(router._duplicate_choices_form("tp-gds", None)["exact"], "skip")
        got = router._duplicate_choices_form("tp-gds", '{"exact": "save", "rows": {"3": "skip"}}')
        self.assertEqual((got["exact"], got["partial"], got["rows"]), ("save", "save", {3: "skip"}))

    def test_unreadable_choices_are_a_400(self):
        for raw in ("[1]", "{", '{"exact": "x"}'):
            with self.subTest(raw=raw):
                with self.assertRaises(HTTPException) as cm:
                    router._duplicate_choices_form("tp-gds", raw)
                self.assertEqual(cm.exception.status_code, 400)

    def test_ignored_by_every_other_type(self):
        self.assertIsNone(router._duplicate_choices_form("tp-lcc", '{"exact": "x"}'))


class ScreenRouteTests(unittest.TestCase):
    def test_other_types_are_not_screened(self):
        db = FakeDB()
        self.assertEqual(asyncio.run(router._screen_duplicates(db, "tp-lcc", USER, AGENCY, WEEK1, ["x"])),
                         (["x"], None, None))
        self.assertEqual(db.statements, [])

    def test_nothing_to_save_is_refused_with_nothing_saved(self):
        row = saved_row(11, "B1", ISSUE)
        db = FakeDB([], [row], [row])
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(router._screen_duplicates(db, "tp-gds", USER, AGENCY, WEEK2, lines(ISSUE)))
        self.assertEqual(cm.exception.status_code, 409)
        self.assertIn("already saved (in WEEK 1.xlsx)", cm.exception.detail)
        self.assertTrue(cm.exception.detail.endswith("Nothing was saved."))
        # The agency is locked before anything is read, so two saves cannot both save in full.
        self.assertIn("pg_advisory_xact_lock", str(db.statements[0]))

    def test_saving_them_again_by_choice_goes_through(self):
        row = saved_row(11, "B1", ISSUE)
        kept, screen_, decision = asyncio.run(router._screen_duplicates(
            FakeDB([], [row], [row]), "tp-gds", USER, AGENCY, WEEK2, lines(ISSUE),
            choices=router._duplicate_choices_form("tp-gds", '{"exact": "save"}')))
        self.assertEqual([(o.duplicate_kind, o.duplicate_of_id) for o in kept], [("exact", 11)])

    def test_new_lines_go_through(self):
        row = saved_row(11, "B1", ISSUE)
        kept, screen_, decision = asyncio.run(router._screen_duplicates(
            FakeDB([], [row], [row]), "tp-gds", USER, AGENCY, WEEK1, lines(ISSUE, REFUND)))
        self.assertEqual((len(kept), len(decision.left_out)), (1, 1))

    def test_the_lock_is_per_agency_and_stable(self):
        a = router._agency_lock(USER, AGENCY)
        self.assertEqual(a, router._agency_lock(USER, SimpleNamespace(id=751, agency_id=28)))
        self.assertNotEqual(a, router._agency_lock(USER, SimpleNamespace(id=752, agency_id=29)))
        self.assertTrue(-2**63 <= a < 2**63)


class WriteTests(unittest.TestCase):
    def test_header_and_lines_carry_the_period_the_tally_and_the_flags(self):
        s = screen([ISSUE, REFUND, ticket(1), ticket(1), BALANCE], saved_from([ISSUE]))
        d = s.decide()
        db = FakeDB()
        asyncio.run(router._write_lines(
            db, "tp-gds", USER, d.kept, batch_id="b-2", source_file="WEEK 1 v2.xlsx",
            file_url=None, uploaded_at=datetime(2026, 8, 15, 11, 0), period=WEEK1, decision=d))
        self.assertEqual([k for k, _ in db.log], ["add", "flush", "add_all"])
        header = db.log[0][1]
        self.assertIsInstance(header, ThirdPartyStatement)
        self.assertEqual((header.period_from, header.period_to), WEEK1)
        # 4 entries in the file (the BALANCE line is not one): 1 already saved, 3 saved.
        self.assertEqual((header.total_entries, header.duplicate_entries, header.new_entries), (4, 1, 3))
        written = db.log[2][1]
        self.assertEqual({(l.period_from, l.period_to) for l in written}, {WEEK1})
        self.assertEqual([l.duplicate_kind for l in written], [None, None, "in_file", None])

    def test_the_control_row_counts_what_was_left_out(self):
        s = screen([ISSUE, ticket(1)], saved_from([ISSUE]))
        d = s.decide()
        control = router._control_row("tp-gds", USER, "b-2", content=b"", filename="x.csv", header_row=None,
                                      file_rows=2, objs=d.kept, expected_count=None, expected_amount=None,
                                      decision=d)
        self.assertEqual((control.duplicate_rows, control.duplicate_net, control.duplicate_of),
                         (1, Decimal("69742.164"), "B1"))

    def test_the_flags_are_not_data_fields(self):
        obj = ThirdPartyGds(data=ISSUE)
        obj.duplicate_kind, obj.duplicate_fields, obj.match_key = "partial", "net_amount", "m"
        for key in ("duplicate_kind", "duplicate_fields", "duplicate_of_id", "match_key", "period_from"):
            self.assertNotIn(key, obj.data)
        obj.data = {**ISSUE, "net_amount": "1"}           # a cell edit rewrites every field…
        self.assertEqual(obj.duplicate_kind, "partial")   # …and leaves the flag

    def test_the_left_out_lines_are_kept_after_the_saved_ones_are_flushed(self):
        s = screen([ISSUE, ticket(1), BALANCE], saved_from([ISSUE]))
        d = s.decide()
        db = FakeDB()
        asyncio.run(router._write_lines(
            db, "tp-gds", USER, d.kept, batch_id="b-2", source_file="WEEK 1 v2.xlsx",
            file_url=None, uploaded_at=datetime(2026, 8, 15, 11, 0), period=WEEK1, decision=d, screen=s))
        self.assertEqual([k for k, _ in db.log], ["add", "flush", "add_all", "flush", "add_all"])
        kept = db.log[4][1]
        self.assertEqual([type(r) for r in kept], [ThirdPartyGdsLeftOut])
        self.assertEqual((kept[0].batch_id, kept[0].tenant_id, kept[0].created_by_id, kept[0].kind),
                         ("b-2", 3, 7, "exact"))

    def test_nothing_left_out_writes_nothing_more(self):
        s = screen([ticket(1)])
        d = s.decide()
        db = FakeDB()
        asyncio.run(router._write_lines(
            db, "tp-gds", USER, d.kept, batch_id="b-1", source_file="f.xlsx", file_url=None,
            uploaded_at=datetime(2026, 8, 7), period=WEEK1, decision=d, screen=s))
        self.assertEqual([k for k, _ in db.log], ["add", "flush", "add_all"])


class LeftOutTests(unittest.TestCase):
    """Each line an upload leaves out is kept, as its file had it, with the saved line it repeats."""

    def _flushed(self, d: ru.Decision, first_id: int = 500) -> None:
        for n, obj in enumerate(d.kept):
            obj.id = first_id + n

    def test_each_left_out_line_points_at_the_saved_line_it_repeats(self):
        saved = saved_from([ISSUE])
        # ISSUE: already uploaded · ticket 1: new · ticket 1 again: repeats row 1, saved here ·
        # ISSUE again: repeats row 0, which is itself left out — so the earlier upload's line.
        s = screen([ISSUE, ticket(1), ticket(1), ISSUE], saved)
        self.assertEqual(kinds(s), ["exact", "new", "in_file", "in_file"])
        d = s.decide({"in_file": "skip"})
        self._flushed(d)
        rows = ru.left_out_rows(s, d, tenant_id=3, created_by_id=7, batch_id="b-2")
        self.assertEqual([(r.file_row, r.kind, r.repeat_of_id) for r in rows],
                         [(0, "exact", saved[0].id), (2, "in_file", 500), (3, "in_file", saved[0].id)])

    def test_the_line_is_kept_exactly_as_the_file_had_it(self):
        s = screen([{**ISSUE, "week": "08-15TH AUG 26", "airline_code": "TK"}], saved_from([ISSUE]))
        d = s.decide()
        [row] = ru.left_out_rows(s, d, tenant_id=3, created_by_id=7, batch_id="b-2")
        self.assertEqual(row.data, s.lines[0].data)
        self.assertEqual(row.data["week"], "08-15TH AUG 26")
        self.assertEqual((row.dedup_key, row.match_key), (s.lines[0].dedup_key, s.lines[0].match_key))

    def test_a_partial_left_out_says_what_changed(self):
        saved = saved_from([ticket(1)])
        s = screen([ticket(1, net_amount="999"), ticket(2)], saved)
        d = s.decide({"partial": "skip"})
        [row] = ru.left_out_rows(s, d, tenant_id=3, created_by_id=7, batch_id="b-2")
        self.assertEqual((row.kind, row.differs, row.repeat_of_id), ("partial", "net_amount", saved[0].id))

    def test_lines_saved_by_choice_are_not_kept_twice(self):
        s = screen([ISSUE, ticket(1)], saved_from([ISSUE]))
        d = s.decide({"exact": "save"})
        self.assertEqual(ru.left_out_rows(s, d, tenant_id=3, created_by_id=7, batch_id="b-2"), [])

    def test_the_kept_line_has_every_field_of_a_saved_one(self):
        self.assertEqual({(f.key, f.kind) for f in ThirdPartyGdsLeftOut.data_fields()},
                         {(f.key, f.kind) for f in ThirdPartyGds.data_fields()})


class MigrationTests(unittest.TestCase):
    src = DUPES_MIGRATION.read_text(encoding="utf-8")

    def test_chains_onto_the_previous_head_without_forking(self):
        self.assertIn("down_revision: Union[str, None] = 'ticket_date_formats_01'", self.src)
        siblings = [f.name for f in VERSIONS.glob("*.py") if f != DUPES_MIGRATION
                    and "down_revision: Union[str, None] = 'ticket_date_formats_01'" in f.read_text(encoding="utf-8")]
        self.assertEqual(siblings, [], "another migration also revises ticket_date_formats_01")

    def test_creates_the_model_columns_and_names(self):
        table = ThirdPartyGds.__table__
        for col in ("match_key", "duplicate_kind", "duplicate_of_id", "duplicate_fields"):
            with self.subTest(column=col):
                self.assertIn(col, table.c)
                self.assertIn(f"sa.Column('{col}'", self.src)
        index_names = {ix.name for ix in table.indexes}
        for name in ("ix_third_party_gds_dedup_key", "ix_third_party_gds_match_key",
                     "ix_third_party_gds_duplicate_of_id"):
            with self.subTest(index=name):
                self.assertIn(name, index_names)
                self.assertIn(f"'{name}'", self.src)
        constraint_names = {c.name for c in table.constraints if c.name}
        for name in ("ck_third_party_gds_duplicate_kind", "fk_third_party_gds_duplicate_of"):
            with self.subTest(constraint=name):
                self.assertIn(name, constraint_names)
                self.assertIn(f"'{name}'", self.src)

    def test_the_period_migration_dropped_the_old_screen(self):
        cols = ThirdPartyGds.__table__.c
        for gone in ("near_match_id", "dedup_group"):
            self.assertNotIn(gone, cols)
        self.assertNotIn("third_party_gds_duplicates", ThirdPartyGds.metadata.tables)
        period = PERIOD_MIGRATION.read_text(encoding="utf-8")
        # Its downgrade recreates the dedup_key index under the very name and columns this one drops.
        self.assertIn("op.create_index('ix_third_party_gds_dedup_key', _G, ['tenant_id', 'created_by_id', 'dedup_key'])",
                      period)
        self.assertIn("op.create_index('ix_third_party_gds_dedup_key', _T, ['tenant_id', 'created_by_id', 'dedup_key'])",
                      self.src)


class LeftOutMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = LEFT_OUT_MIGRATION.read_text(encoding="utf-8")
        cls.mig = _load(LEFT_OUT_MIGRATION, "tp_gds_left_out_01")

    def test_chains_onto_the_previous_head_without_forking(self):
        self.assertIn("down_revision: Union[str, None] = 'internal_dupes_01'", self.src)
        siblings = [f.name for f in VERSIONS.glob("*.py") if f != LEFT_OUT_MIGRATION
                    and "down_revision: Union[str, None] = 'internal_dupes_01'" in f.read_text(encoding="utf-8")]
        self.assertEqual(siblings, [], "another migration also revises internal_dupes_01")

    def test_creates_every_model_column(self):
        frozen = {name for name, _key, _type in self.mig._COLUMNS}
        # Added to both line tables later: YR, K3 and a derived Total Tax; then the SSR and GST
        # parts, ADM, Discount, UATP Amount and Card Type; then Refund.
        added = {name for name, _key, _type in _load(STD_MIGRATION, "tp_gds_std_01")._COLUMNS}
        added |= {name for name, _key, _type in _load(STD_02_MIGRATION, "tp_gds_std_02")._COLUMNS}
        added |= {name for name, _key, _type in _load(STD_03_MIGRATION, "tp_gds_std_03")._COLUMNS}
        self.assertEqual(frozen | added, {f.attr for f in ThirdPartyGdsLeftOut.data_fields()})
        own = set(ThirdPartyGdsLeftOut.__table__.c.keys()) - frozen - added
        for col in own:
            with self.subTest(column=col):
                self.assertIn(f"sa.Column('{col}'", self.src)
        self.assertIn("ck_third_party_gds_left_out_kind", self.src)
        for col in ("tenant_id", "created_by_id", "batch_id", "repeat_of_id"):
            self.assertIn(f"ix_third_party_gds_left_out_{col}", {ix.name for ix in ThirdPartyGdsLeftOut.__table__.indexes})


if __name__ == "__main__":
    unittest.main()
