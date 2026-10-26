"""Vendor ↔ Internal reconciliation — the matching rules, the eight cases, the vendor filters
and the balance, on the real Globe cases.

Run:  python -m unittest discover backend/tests
"""
import os
import sys
import unittest
from datetime import date, datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import HTTPException  # noqa: E402

from app.api.v1 import vendor_internal_reconciliation as api  # noqa: E402
from app.services.vendor_internal_recon import (  # noqa: E402
    ALREADY_UPLOADED, CASE_IDS, DIFFERENCE, EXTRA_COMMISSION, EXTRA_FARE, EXTRA_REFUND, IN_PERIOD, INTERNAL_ONLY,
    LESS_COMMISSION, LESS_FARE, LESS_REFUND, MATCHED, NETTED, NEXT_STATEMENT, REFUND, SALE,
    VENDOR_ONLY, Book, Line, Repeat, Scope, Stmt, Vendor, _compare, _netted_row, _pair, _vendor_commission,
    annotate, apply_resolutions, balance, books_agency, build_view, in_scope, match_lines, row_cases,
    summarize, vendor_key,
)

GLOBE = vendor_key("Globe Air Travels", "NEW DELHI")
LORDS = vendor_key("Lords Travel Pvt. Ltd.", "NEW DELHI")


def line(side, kind, net, fare=0.0, commission=0.0, charges=0.0, gst=0.0, tds=0.0, **kw):
    comm_net = kw.pop("commission_net", None)
    if comm_net is None:
        comm_net = (_vendor_commission(kind, commission, tds) if side == "vendor" else -commission + tds)
    ident = kw.pop("id", 1)
    return Line(side=side, id=ident, line_ids=[ident], serial=kw.pop("serial", "5808583279"),
                code=kw.pop("code", "607"), kind=kind, pax=kw.pop("pax", "SAHOTA/VIKAS"),
                pnr=kw.pop("pnr", None), sector="IST/AUH/DEL", date=kw.pop("date", None),
                ref=kw.pop("ref", None), source=kw.pop("source", None),
                booked=kw.pop("booked", None), vendor_key=kw.pop("vendor_key", None),
                batches=kw.pop("batches", []),
                amounts=dict(fare=fare, commission=commission, charges=charges, gst=gst, tds=tds, net=net,
                             commission_net=comm_net))


def book(vendor, internal, stmts=(), vendors=(GLOBE, LORDS), internal_ends=None, repeats=()):
    names = {GLOBE: "Globe Air Travels", LORDS: "Lords Travel Pvt. Ltd."}
    return Book(vendor=vendor, internal=internal,
                vendors={k: Vendor(k, names[k], "NEW DELHI", ["GDS"]) for k in vendors},
                stmts={s.batch_id: s for s in stmts}, internal_ends=internal_ends or {},
                repeats=list(repeats))


def stmt(batch, start, end, key=GLOBE, opening=None, closing=None, billed=0.0, lines=0):
    return Stmt(batch_id=batch, file_name=f"{batch}.xlsx", uploaded_at=datetime(2026, 10, 22),
                period_from=date.fromisoformat(start), period_to=date.fromisoformat(end), vendor_key=key,
                vendor_name="Globe Air Travels", opening=opening, closing=closing, billed=billed, lines=lines)


def reconciled(vendor, internal, **kw):
    rows = match_lines(vendor, internal)
    apply_resolutions(rows, {})
    b = book(vendor, internal, **kw)
    annotate(rows, b)
    return rows, b


class CompareTests(unittest.TestCase):
    def test_round_off_is_a_match(self):
        v = line("vendor", SALE, 89437.31, fare=89319, charges=100, gst=18)
        i = line("internal", SALE, 89437.0, fare=89319, charges=100, gst=18)
        status, diff, hints = _compare(v, i)
        self.assertEqual(status, MATCHED)
        self.assertIn("Round-off", hints[0])

    def test_fare_difference_is_explained(self):
        # EY 607 5808583279: 55,069 on the vendor, 55,062 internally.
        v = line("vendor", SALE, 54985.31, fare=55069, commission=205.81, charges=100, gst=18, tds=4.12)
        i = line("internal", SALE, 54978.0, fare=55062, commission=205.81, charges=100, gst=18, tds=4.12)
        status, diff, hints = _compare(v, i)
        self.assertEqual(status, DIFFERENCE)
        self.assertEqual(diff["fare"], -7.0)
        self.assertTrue(hints[0].startswith("Fare + taxes differs by -7.00"))

    def test_code_mismatch_is_a_hint_not_a_break(self):
        v = line("vendor", SALE, 472, code="75")
        i = line("internal", SALE, 472, code="125")
        status, _, hints = _compare(v, i)
        self.assertEqual(status, MATCHED)
        self.assertTrue(any("Airline code differs" in h for h in hints))


class PairingTests(unittest.TestCase):
    def test_closest_net_pairs_first(self):
        vs = [line("vendor", SALE, 100, id=1), line("vendor", SALE, 5000, id=2)]
        is_ = [line("internal", SALE, 5001, id=3)]
        pairs, lv, li = _pair(vs, is_)
        self.assertEqual([(p[0].id, p[1].id) for p in pairs], [(2, 3)])
        self.assertEqual([x.id for x in lv], [1])


class NettedTests(unittest.TestCase):
    def test_sold_and_voided_compared_whole(self):
        # Vendor sells 89,257 and refunds it, keeping charges; internal books 472 once.
        sale = line("vendor", SALE, 89375, fare=89257, charges=100, gst=18, id=1, batches=["W1"])
        refund = line("vendor", REFUND, -88785, fare=-89257, charges=354 + 100, gst=18, id=2, batches=["W2"])
        single = line("internal", SALE, 472, fare=354, charges=100, gst=18, id=3)
        row = _netted_row("4848173036", [sale, refund], single)
        self.assertEqual(row["kind"], NETTED)
        self.assertEqual(row["vendor"]["net"], 590)
        self.assertEqual(row["diff"]["net"], -118)
        self.assertIn("Sold and refunded on the vendor side", row["hints"][0])
        # Both statements it came from, and how many lines it sums.
        self.assertEqual((row["vendor"]["statements"], row["vendor"]["lines"]), (["W1", "W2"], 2))


def statements():
    """One of each status: Globe's weekly GDS statement against the monthly internal one."""
    v = lambda serial, net, **kw: line("vendor", SALE, net, fare=net, serial=serial,
                                       ref="08-15TH AUG 26", source="TRIUMPHH 08-15.xlsx", **kw)
    i = lambda serial, net, doc, **kw: line("internal", SALE, net, fare=net, serial=serial,
                                            ref=doc, source="GLOBE 01 AUG TO 31 AUG.xls", **kw)
    vendor = [
        v("1111111111", 5000, id=1, date="2026-08-10"),           # matched
        v("2222222222", 12337, id=2, date="2026-08-13"),          # difference: vendor 177 more
        v("3333333333", 8000, id=3, date="2026-08-14"),           # GDS only, inside internal's dates
        v("6666666666", 900, id=6, date="2026-08-15"),            # makes 15 Aug the vendor's last date
    ]
    internal = [
        i("1111111111", 5000.4, "IS26/ 1001", id=11, date="2026-08-10"),
        i("2222222222", 12160, "IS26/ 1082", id=12, date="2026-08-13"),
        i("4444444444", 700, "IS26/ 1090", id=14, date="2026-08-12"),     # internal only, vendor covers it
        i("5555555555", 9000, "IS26/ 1185", id=15, date="2026-08-28"),    # internal only, after vendor's last
    ]
    return vendor, internal


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.vendor, self.internal = statements()
        self.rows = match_lines(self.vendor, self.internal)
        self.by_ticket = {r["ticket_number"]: r for r in self.rows}

    def test_every_line_lands_in_one_status(self):
        status = {t: r["status"] for t, r in self.by_ticket.items()}
        self.assertEqual(status, {
            "1111111111": MATCHED, "2222222222": DIFFERENCE, "3333333333": VENDOR_ONLY,
            "6666666666": VENDOR_ONLY, "4444444444": INTERNAL_ONLY, "5555555555": INTERNAL_ONLY,
        })

    def test_keys_name_the_line_not_the_row_id(self):
        self.assertEqual(self.by_ticket["2222222222"]["key"], "2222222222|sale|08-15TH AUG 26|IS26/ 1082")
        self.assertEqual(self.by_ticket["4444444444"]["key"], "4444444444|sale||IS26/ 1090")
        # A re-upload gives new row ids — the keys must not move.
        for ln in self.vendor + self.internal:
            ln.id += 1000
        again = {r["ticket_number"]: r["key"] for r in match_lines(self.vendor, self.internal)}
        self.assertEqual(again, {t: r["key"] for t, r in self.by_ticket.items()})

    def test_identical_keys_are_numbered(self):
        vendor = [line("vendor", SALE, 100, serial="7", id=1, ref="W1"),
                  line("vendor", SALE, 100, serial="7", id=2, ref="W1")]
        keys = sorted(r["key"] for r in match_lines(vendor, []))
        self.assertEqual(keys, ["7|sale|W1|", "7|sale|W1|#2"])

    def test_one_sided_lines_say_whether_to_wait(self):
        # Vendor dates run to 15 Aug: an internal ticket of 28 Aug is simply not billed yet,
        # one of 12 Aug should already be on the GDS statement.
        self.assertEqual(self.by_ticket["5555555555"]["pending"], NEXT_STATEMENT)
        self.assertEqual(self.by_ticket["4444444444"]["pending"], IN_PERIOD)
        self.assertEqual(self.by_ticket["3333333333"]["pending"], IN_PERIOD)
        self.assertIsNone(self.by_ticket["2222222222"]["pending"])


# ── the eight cases ──────────────────────────────────────────────────────────
def diff_row(kind, v, i):
    rows = match_lines([v], [i])
    apply_resolutions(rows, {})
    return rows[0]


class CaseTests(unittest.TestCase):
    def test_a_sale_billed_higher_is_extra_fare_and_less(self):
        # 160 1955514325: service fee 150 + GST 27 on the vendor, none in the books.
        r = diff_row(SALE, line("vendor", SALE, 12337, fare=12160, charges=150, gst=27),
                     line("internal", SALE, 12160, fare=12160))
        self.assertEqual(row_cases(r), [{"case": EXTRA_FARE, "amount": -177.0}])

    def test_a_sale_billed_lower_is_less_fare_and_add(self):
        r = diff_row(SALE, line("vendor", SALE, 9000, fare=9000), line("internal", SALE, 9250, fare=9250))
        self.assertEqual(row_cases(r), [{"case": LESS_FARE, "amount": 250.0}])

    def test_a_refund_splits_into_its_charges_and_its_commission(self):
        # 235 4847760583: the vendor keeps 354 more cancellation charges AND takes back its
        # 122.75 commission (less 2.455 TDS) — 474.29 in all, as two items that add up to it.
        v = line("vendor", REFUND, -87302.71, fare=-90697, commission=-122.75, tds=-2.455, charges=3256, gst=18)
        i = line("internal", REFUND, -87777.0, fare=-90697, charges=2902, gst=18)
        cases = row_cases(diff_row(REFUND, v, i))
        self.assertEqual(cases, [{"case": EXTRA_REFUND, "amount": -353.99},
                                 {"case": EXTRA_COMMISSION, "amount": -120.3}])
        self.assertEqual(round(sum(c["amount"] for c in cases), 2), -474.29)

    def test_a_commission_reversal_printed_positive_is_still_a_reversal(self):
        # 5808515002: the vendor prints the refund's commission +135.30 (−155.88 on another line);
        # either way it is taken back, so the whole 138.01 is commission, none of it refund.
        v = line("vendor", REFUND, -72512.99, fare=-72769, commission=135.3, tds=2.71, charges=100, gst=18)
        i = line("internal", REFUND, -72651.0, fare=-72769, charges=100, gst=18)
        self.assertEqual(row_cases(diff_row(REFUND, v, i)), [{"case": EXTRA_COMMISSION, "amount": -138.01}])
        self.assertEqual(_vendor_commission(REFUND, 135.3, 2.71), _vendor_commission(REFUND, -135.3, 2.71))
        self.assertAlmostEqual(_vendor_commission(SALE, 226.89, 4.53), -222.36)

    def test_more_commission_passed_on_is_less_commission_and_add(self):
        # The vendor passes on 300 commission (less 6 TDS) the books do not have: it bills 294 less.
        v = line("vendor", SALE, 9706, fare=10000, commission=300, tds=6)
        i = line("internal", SALE, 10000, fare=10000)
        self.assertEqual(row_cases(diff_row(SALE, v, i)), [{"case": LESS_COMMISSION, "amount": 294.0}])

    def test_less_refund_charges_is_add(self):
        # The books credit 8,800, the vendor 9,000: the vendor credited MORE — less refund
        # charges, and the 200 is added to the vendor's figure to reach the books.
        v = line("vendor", REFUND, -9000, fare=-9500, charges=500)
        i = line("internal", REFUND, -8800, fare=-9500, charges=700)
        self.assertEqual(row_cases(diff_row(REFUND, v, i)), [{"case": LESS_REFUND, "amount": 200.0}])

    def test_a_ticket_compared_whole_is_a_refund(self):
        sale = line("vendor", SALE, 89375, fare=89257, charges=100, gst=18, id=1)
        refund = line("vendor", REFUND, -88785, fare=-89257, charges=454, gst=18, id=2)
        single = line("internal", SALE, 472, fare=354, charges=100, gst=18, id=3)
        r = _netted_row("4848173036", [sale, refund], single)
        self.assertEqual(row_cases(r), [{"case": EXTRA_REFUND, "amount": -118.0}])

    def test_paisa_of_one_part_go_with_the_other(self):
        # 4848853966: the vendor passes on 1.41 commission (0.03 TDS) the books do not have, and
        # the books' rupee rounding adds 0.30 — one item of 1.68, not a commission one and a
        # 0.30 "fare" one.
        v = line("vendor", SALE, 998.62, fare=1000, commission=1.41, tds=0.03)
        i = line("internal", SALE, 1000.30, fare=1000)
        self.assertEqual(row_cases(diff_row(SALE, v, i)), [{"case": LESS_COMMISSION, "amount": 1.68}])

    def test_one_sided_lines_and_their_signs(self):
        rows = match_lines([line("vendor", REFUND, -80370, serial="1", id=1)],
                           [line("internal", SALE, 9000, serial="2", id=2)])
        by = {r["ticket_number"]: row_cases(r) for r in rows}
        # A refund the vendor credited that the books lack: books are higher — ADD.
        self.assertEqual(by["1"], [{"case": VENDOR_ONLY, "amount": 80370.0}])
        self.assertEqual(by["2"], [{"case": INTERNAL_ONLY, "amount": 9000.0}])

    def test_matched_lines_make_no_case(self):
        self.assertEqual(row_cases(diff_row(SALE, line("vendor", SALE, 5000), line("internal", SALE, 5000.4))), [])


class SummaryTests(unittest.TestCase):
    def test_billed_plus_the_cases_is_your_books(self):
        vendor, internal = statements()
        rows, _ = reconciled(vendor, internal)
        s = summarize(rows)
        total = sum(s["cases"][c]["amount"] for c in CASE_IDS)
        self.assertEqual(round(s["vendor_billed"] + total + s["round_off"], 2), s["books"])
        self.assertEqual(s["cases"][EXTRA_FARE]["amount"], -177.0)
        self.assertEqual(s["cases"][VENDOR_ONLY]["amount"], -8900.0)
        self.assertEqual(s["cases"][INTERNAL_ONLY]["amount"], 9700.0)
        self.assertEqual(s["round_off"], 0.4)
        self.assertEqual((s["open"]["lines"], s["matched"]["lines"]), (5, 1))

    def test_totals_count_tickets_as_well_as_lines(self):
        # A ticket sold and refunded is two lines but one ticket — on either side.
        vendor = [line("vendor", SALE, 500, serial="7", id=1), line("vendor", REFUND, -400, serial="7", id=2),
                  line("vendor", SALE, 300, serial="8", id=3)]
        internal = [line("internal", SALE, 500, serial="7", id=4)]
        rows, _ = reconciled(vendor, internal)
        s = summarize(rows)
        self.assertEqual((s["vendor_lines"], s["books_lines"], s["tickets"]), (3, 1, 2))

    def test_a_resolved_line_counts_as_resolved_in_its_case(self):
        vendor, internal = statements()
        rows = match_lines(vendor, internal)
        diff = next(r for r in rows if r["status"] == DIFFERENCE)
        apply_resolutions(rows, {diff["key"]: {"id": 1, "decision": "vendor_wrong", "note": None,
                                               "status": DIFFERENCE, "vendor_net": 12337.0,
                                               "internal_net": 12160.0, "difference": -177.0,
                                               "resolved_at": None}})
        annotate(rows, book(vendor, internal))
        c = summarize(rows)["cases"][EXTRA_FARE]
        self.assertEqual((c["open"], c["resolved"], c["amount"]), (0, 1, -177.0))


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.vendor, self.internal = statements()
        self.rows = match_lines(self.vendor, self.internal)
        self.diff = next(r for r in self.rows if r["status"] == DIFFERENCE)

    def decision(self, **over):
        return {"id": 1, "decision": "vendor_wrong", "note": None, "status": DIFFERENCE,
                "vendor_net": 12337.0, "internal_net": 12160.0, "difference": -177.0,
                "resolved_at": None, **over}

    def test_a_decision_on_the_same_figures_closes_the_line(self):
        apply_resolutions(self.rows, {self.diff["key"]: self.decision()})
        self.assertFalse(self.diff["open"])
        self.assertFalse(self.diff["resolution"]["stale"])

    def test_changed_figures_reopen_the_line(self):
        # The internal statement was corrected to 12,200 after the decision was taken.
        apply_resolutions(self.rows, {self.diff["key"]: self.decision(internal_net=12200.0)})
        self.assertTrue(self.diff["open"])
        self.assertTrue(self.diff["resolution"]["stale"])

    def test_matched_lines_are_never_open(self):
        apply_resolutions(self.rows, {})
        self.assertTrue(all(not r["open"] for r in self.rows if r["status"] == MATCHED))


# ── vendors, scope and the balance ───────────────────────────────────────────
class AttributionTests(unittest.TestCase):
    def ticket(self, **kw):
        base = dict(payable_type=None, payable_agency_id=None, customer_type=None, customer_agency_id=None)
        return SimpleNamespace(**{**base, **kw})

    def test_payable_to_then_the_agency_it_was_filed_under(self):
        statement = SimpleNamespace(customer_type="agency", customer_agency_id=28)
        self.assertEqual(books_agency(self.ticket(payable_type="b2b", payable_agency_id=37,
                                                  customer_type="agency", customer_agency_id=28), statement), 37)
        self.assertEqual(books_agency(self.ticket(customer_type="agency", customer_agency_id=28)), 28)
        self.assertEqual(books_agency(self.ticket(), statement), 28)
        # Bought from the airline direct, sold to a corporate: no vendor statement to meet.
        self.assertIsNone(books_agency(self.ticket(payable_type="airline", customer_type="corporate"),
                                       SimpleNamespace(customer_type="corporate", customer_agency_id=None)))

    def test_one_vendor_whatever_the_channel_and_spacing(self):
        self.assertEqual(vendor_key("Globe Air Travels", "NEW DELHI"), vendor_key(" globe  air travels ", "New Delhi"))
        self.assertNotEqual(vendor_key("Globe Air Travels", "NEW DELHI"), vendor_key("Globe Air Travels", "MUMBAI"))
        self.assertIsNone(vendor_key("", "NEW DELHI"))


def two_weeks():
    """Globe's 01-07 and 08-15 Aug statements against the monthly books."""
    w1, w2 = stmt("W1", "2026-08-01", "2026-08-07"), stmt("W2", "2026-08-08", "2026-08-15")
    v = lambda serial, net, batch, day, **kw: line(
        "vendor", SALE, net, fare=net, serial=serial, batches=[batch], booked=day, date=day,
        vendor_key=GLOBE, ref=batch, source=f"{batch}.xlsx", **kw)
    i = lambda serial, net, day, **kw: line(
        "internal", SALE, net, fare=net, serial=serial, booked=day, date=day, vendor_key=kw.pop("vk", GLOBE),
        ref=f"IS/{serial}", batches=["M1"], **kw)
    vendor = [v("1", 1000, "W1", "2026-08-02", id=1), v("2", 2000, "W2", "2026-08-10", id=2),
              v("3", 3000, "W2", "2026-08-12", id=3)]
    internal = [i("1", 1000, "2026-08-02", id=11), i("2", 1900, "2026-08-10", id=12),
                i("4", 400, "2026-08-05", id=14), i("5", 500, "2026-08-20", id=15),
                i("6", 600, "2026-08-06", id=16, vk=None)]
    return vendor, internal, [w1, w2]


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.vendor, self.internal, self.stmts = two_weeks()
        self.rows, self.book = reconciled(self.vendor, self.internal, stmts=self.stmts)
        self.by = {r["ticket_number"]: r for r in self.rows}

    def tickets(self, **scope):
        return sorted(r["ticket_number"] for r in self.rows if in_scope(r, Scope(**scope), self.book.stmts))

    def test_every_vendor_by_default(self):
        self.assertEqual(self.tickets(), ["1", "2", "3", "4", "5", "6"])

    def test_one_vendor_leaves_out_the_tickets_of_no_vendor(self):
        self.assertEqual(self.tickets(vendor=GLOBE), ["1", "2", "3", "4", "5"])
        self.assertEqual(self.tickets(vendor=LORDS), [])

    def test_a_statement_holds_its_lines_and_what_it_should_have_carried(self):
        # W1 billed ticket 1; ticket 4 is Globe's, dated in W1's days, billed nowhere.
        self.assertEqual(self.tickets(statement="W1"), ["1", "4"])
        # Ticket 5 (20 Aug) is after both statements: in neither.
        self.assertEqual(self.tickets(statement="W2"), ["2", "3"])

    def test_the_booking_period(self):
        self.assertEqual(self.tickets(date_from="2026-08-05", date_to="2026-08-10"), ["2", "4", "6"])

    def test_waiting_is_judged_against_the_vendors_own_statements(self):
        # Globe's statements end on 15 Aug: ticket 5 (20 Aug) is expected in the next one,
        # ticket 4 (5 Aug) should already have been billed.
        self.assertEqual((self.by["5"]["pending"], self.by["4"]["pending"]), (NEXT_STATEMENT, IN_PERIOD))
        # A vendor with no statement loaded yet: everything of its in the books is still to come.
        rows, _ = reconciled([], [line("internal", SALE, 100, serial="9", vendor_key=LORDS, date="2026-08-03")])
        self.assertEqual(rows[0]["pending"], NEXT_STATEMENT)

    def test_a_ticket_with_no_vendor_says_so(self):
        self.assertTrue(any("No vendor for this ticket" in h for h in self.by["6"]["hints"]))

    def test_a_ticket_booked_under_another_vendor_is_matched_and_flagged(self):
        vendor = [line("vendor", SALE, 500, serial="7", vendor_key=LORDS)]
        internal = [line("internal", SALE, 500, serial="7", vendor_key=GLOBE)]
        rows, _ = reconciled(vendor, internal)
        self.assertEqual((rows[0]["status"], rows[0]["vendor_id"], rows[0]["books_vendor_id"]), (MATCHED, LORDS, GLOBE))
        self.assertTrue(any("booked under Globe Air Travels" in h for h in rows[0]["hints"]))

    def test_a_ticket_billed_twice_says_where(self):
        vendor = [line("vendor", SALE, 500, serial="7", id=1, vendor_key=GLOBE, source="GLOBE W1.xlsx"),
                  line("vendor", SALE, 500, serial="7", id=2, vendor_key=LORDS, source="LORDS W1.xlsx")]
        rows, _ = reconciled(vendor, [line("internal", SALE, 500, serial="7", vendor_key=GLOBE)])
        twice = next(r for r in rows if r["status"] == VENDOR_ONLY)
        self.assertTrue(twice["hints"][0].startswith("Billed more than once"))


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.vendor, self.internal, stmts = two_weeks()
        # W1: opening 10,000 + billed 1,000 − payments 6,000 = 5,000. W2 prints no closing.
        stmts[0].opening, stmts[0].closing, stmts[0].billed = 10000.0, 5000.0, 1000.0
        stmts[1].billed = 5000.0
        self.stmts = stmts
        self.rows, self.book = reconciled(self.vendor, self.internal, stmts=stmts)

    def test_as_at_the_statements_end_line_by_line(self):
        b = balance(GLOBE, self.book, self.rows, statement="W1")
        self.assertTrue(b["available"])
        self.assertEqual((b["as_at"], b["since"], b["closing"], b["payments"]), ("2026-08-07", "2026-08-01", 5000.0, 6000.0))
        # To 7 Aug: the vendor billed ticket 1 (1,000); the books have tickets 1 and 4 (1,400).
        self.assertEqual((b["vendor_upto"], b["books_upto"], b["items"], b["books"]), (1000.0, 1400.0, 400.0, 5400.0))
        # Tickets 2, 3 and 5 on either side are after it.
        self.assertEqual(b["later"], 4)

    def test_latest_statement_with_a_closing_balance(self):
        self.assertEqual(balance(GLOBE, self.book, self.rows)["statement"]["batch_id"], "W1")

    def test_a_statement_without_a_closing_balance_says_so(self):
        b = balance(GLOBE, self.book, self.rows, statement="W2")
        self.assertEqual((b["available"], b["reason"]), (False, "This statement prints no closing balance."))

    def test_the_view_for_one_statement(self):
        rows = match_lines(self.vendor, self.internal)
        apply_resolutions(rows, {})
        out = build_view(rows, self.book, Scope(statement="W1"), "summary")
        s = out["summary"]
        self.assertEqual((s["statement"]["billed"], s["statement"]["other_billed"]), (1000.0, 0.0))
        self.assertEqual(s["balance"]["statement"]["batch_id"], "W1")
        self.assertEqual(out["rows"], [])


def left_out(serial, net, kind, of_id, *, row, batch="W2", day="2026-08-02", **kw):
    """A line of `batch`'s file its upload left out, repeating saved vendor line `of_id`."""
    ln = line("vendor", SALE, net, fare=net, serial=serial, batches=[batch], booked=day, date=day,
              vendor_key=GLOBE, ref=batch, source=f"{batch}.xlsx", id=900 + row)
    return Repeat(line=ln, kind=kind, of_id=of_id, file_row=row, **kw)


class AlreadyUploadedTests(unittest.TestCase):
    """08-15's file carried ticket 1, already saved on 01-07 and matched there, and ticket 3
    twice; its upload left those copies out. Shown with 08-15, reconciled where they are saved."""

    def setUp(self):
        self.vendor, self.internal, self.stmts = two_weeks()
        self.repeats = [left_out("1", 1000, "exact", 1, row=0),
                        left_out("3", 3000, "in_file", 3, row=4, day="2026-08-12")]

    def view(self, name, scope=Scope(statement="W2"), repeats=None, resolutions=None):
        rows = match_lines(self.vendor, self.internal)
        apply_resolutions(rows, resolutions or {})
        b = book(self.vendor, self.internal, stmts=self.stmts,
                 repeats=self.repeats if repeats is None else repeats)
        return build_view(rows, b, scope, name)

    def test_a_statement_lists_what_its_upload_left_out_and_where_each_is_reconciled(self):
        out = self.view(ALREADY_UPLOADED)
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["counts"][ALREADY_UPLOADED], 2)
        got = [(p["ticket_number"], p["left_out"], p["state"], p["file_row"]) for p in out["repeats"]]
        self.assertEqual(got, [("1", "exact", MATCHED, 0), ("3", "in_file", "open", 4)])
        first = out["repeats"][0]
        self.assertEqual(first["original"]["internal"]["ref"], "IS/1")
        self.assertEqual((first["statement"]["batch_id"], first["first_statement"]["batch_id"]), ("W2", "W1"))
        self.assertEqual(first["vendor"]["net"], 1000.0)

    def test_they_are_never_counted_in_the_reconciliation(self):
        with_them = self.view("summary")["summary"]
        without = self.view("summary", repeats=[])["summary"]
        for k in ("vendor_billed", "vendor_lines", "books", "difference", "cases", "lines"):
            with self.subTest(figure=k):
                self.assertEqual(with_them[k], without[k])
        self.assertEqual(with_them["already_uploaded"],
                         {"lines": 2, "amount": 4000.0, MATCHED: 1, "resolved": 0, "open": 1, "unsaved": 0,
                          "unlisted": 0})

    def test_they_belong_to_their_own_statement_not_the_one_they_repeat(self):
        out = self.view(MATCHED, scope=Scope(statement="W1"))
        self.assertEqual(out["counts"][ALREADY_UPLOADED], 0)
        [one] = out["rows"]
        self.assertIn("Sent again on W2.xlsx — not saved there (already uploaded)", one["hints"])

    def test_the_vendor_and_the_booking_period_narrow_them_too(self):
        self.assertEqual(self.view(ALREADY_UPLOADED, Scope(vendor=LORDS))["counts"][ALREADY_UPLOADED], 0)
        out = self.view(ALREADY_UPLOADED, Scope(date_from="2026-08-10"))
        self.assertEqual([p["ticket_number"] for p in out["repeats"]], ["3"])

    def test_a_resolved_original_reads_resolved(self):
        rows = match_lines(self.vendor, self.internal)
        key = next(r["key"] for r in rows if r["ticket_number"] == "3")
        res = {key: {"id": 1, "decision": "accepted", "note": None, "status": VENDOR_ONLY, "vendor_net": 3000.0,
                     "internal_net": None, "difference": None, "resolved_at": None}}
        out = self.view(ALREADY_UPLOADED, resolutions=res)
        self.assertEqual([p["state"] for p in out["repeats"]], [MATCHED, "resolved"])

    def test_a_line_whose_original_is_gone_says_so(self):
        out = self.view(ALREADY_UPLOADED, repeats=[left_out("1", 1000, "exact", None, row=0)])
        [p] = out["repeats"]
        self.assertEqual((p["state"], p["original"], p["first_statement"]), ("unsaved", None, None))

    def test_a_partial_left_out_names_what_changed(self):
        out = self.view(ALREADY_UPLOADED, repeats=[left_out("1", 999, "partial", 1, row=0, differs=["net_amount"])])
        self.assertEqual(out["repeats"][0]["differs"], ["Net Amount"])

    def test_the_statement_balance_counts_them_in_what_its_file_billed(self):
        w2 = self.stmts[1]
        # W2: its own lines 2,000 + 3,000, and ticket 1 again (1,000), all printed on the file;
        # opening 5,000 + 6,000 − payments 2,000 = 9,000.
        w2.billed, w2.repeats, w2.repeats_net = 5000.0, 1, 1000.0
        w2.opening, w2.closing = 5000.0, 9000.0
        rows, b = reconciled(self.vendor, self.internal, stmts=self.stmts)
        bal = balance(GLOBE, b, rows, statement="W2")
        self.assertEqual((bal["billed"], bal["payments"], bal["repeated"]),
                         (6000.0, 2000.0, {"lines": 1, "amount": 1000.0}))
        # Each ticket once on the vendor's side: 1, 2 and 3.
        self.assertEqual(bal["vendor_upto"], 6000.0)

    def test_uploads_before_they_were_kept_are_counted(self):
        self.stmts[1].unlisted = 3
        s = self.view("summary")["summary"]
        self.assertEqual((s["already_uploaded"]["unlisted"], s["statement"]["repeats_unlisted"]), (3, 3))


class ViewTests(unittest.TestCase):
    def setUp(self):
        vendor, internal, stmts = two_weeks()
        self.args = (vendor, internal, stmts)

    def view(self, name, scope=Scope()):
        vendor, internal, stmts = self.args
        rows = match_lines(vendor, internal)
        apply_resolutions(rows, {})
        return build_view(rows, book(vendor, internal, stmts=stmts), scope, name)

    def test_each_view_picks_its_rows(self):
        self.assertEqual([r["ticket_number"] for r in self.view(LESS_FARE)["rows"]], [])
        self.assertEqual([r["ticket_number"] for r in self.view(EXTRA_FARE)["rows"]], ["2"])
        self.assertEqual(sorted(r["ticket_number"] for r in self.view(INTERNAL_ONLY)["rows"]), ["4", "5", "6"])
        self.assertEqual([r["ticket_number"] for r in self.view(MATCHED)["rows"]], ["1"])
        out = self.view("summary")
        self.assertEqual(out["rows"], [])
        self.assertEqual((out["counts"][EXTRA_FARE], out["counts"][VENDOR_ONLY], out["counts"]["all"]), (1, 1, 6))

    def test_every_vendor_shows_each_vendors_figures(self):
        s = self.view("summary")["summary"]
        self.assertIsNone(s["balance"])
        self.assertEqual([v["vendor_id"] for v in s["by_vendor"]], [GLOBE, None])
        globe = s["by_vendor"][0]
        self.assertEqual((globe["vendor_billed"], globe["books"], globe["statements"]), (6000.0, 3800.0, 2))

    def test_one_vendor_has_no_vendor_table(self):
        self.assertEqual(self.view("summary", Scope(vendor=GLOBE))["summary"]["by_vendor"], [])

    def test_one_vendor_lists_its_statements_and_where_each_stands(self):
        table = self.view("summary", Scope(vendor=GLOBE))["summary"]["statements"]
        self.assertEqual([x["batch_id"] for x in table], ["W2", "W1"])
        w2, w1 = table
        # W1: ticket 1 matched, and ticket 4 in the books in its period that it did not bill.
        self.assertEqual((w1["reconciled"]["matched"], w1["reconciled"]["open"], w1["reconciled"]["difference"]),
                         (1, 1, 400.0))
        # W2: ticket 2 billed 100 higher, ticket 3 not in the books.
        self.assertEqual((w2["reconciled"]["matched"], w2["reconciled"]["open"], w2["reconciled"]["open_amount"]),
                         (0, 2, -3100.0))

    def test_a_statement_lists_its_vendors_statements_too(self):
        table = self.view("summary", Scope(statement="W1"))["summary"]["statements"]
        self.assertEqual([x["batch_id"] for x in table], ["W2", "W1"])

    def test_every_vendor_lists_no_statements(self):
        self.assertEqual(self.view("summary")["summary"]["statements"], [])

    def test_all_tickets_is_every_line_in_the_filters(self):
        out = self.view("all", Scope(vendor=GLOBE))
        self.assertEqual(sorted(r["ticket_number"] for r in out["rows"]), ["1", "2", "3", "4", "5"])

    def test_unmatched_is_every_line_but_the_matched_ones(self):
        out = self.view("unmatched", Scope(vendor=GLOBE))
        self.assertEqual(sorted(r["ticket_number"] for r in out["rows"]), ["2", "3", "4", "5"])
        self.assertEqual(out["counts"]["unmatched"] + out["counts"][MATCHED], out["counts"]["all"])

    def test_the_options_list_vendors_and_statements(self):
        o = self.view("summary")["options"]
        self.assertEqual([(v["id"], v["statements"], v["books_tickets"]) for v in o["vendors"]],
                         [(GLOBE, 2, 4), (LORDS, 0, 0)])
        self.assertEqual([s["batch_id"] for s in o["statements"]], ["W2", "W1"])
        self.assertEqual(o["unassigned_books"], 1)


class ApiTests(unittest.TestCase):
    def test_an_unknown_view_is_refused(self):
        with self.assertRaises(HTTPException) as cm:
            api._scope(None, None, None, None, "everything")
        self.assertEqual(cm.exception.status_code, 400)

    def test_a_backwards_period_is_refused(self):
        with self.assertRaises(HTTPException):
            api._scope(None, None, date(2026, 8, 15), date(2026, 8, 1), "all")

    def test_the_scope_as_the_engine_reads_it(self):
        s = api._scope(GLOBE, "", date(2026, 8, 1), date(2026, 8, 15), "summary")
        self.assertEqual(s, Scope(vendor=GLOBE, statement=None, date_from="2026-08-01", date_to="2026-08-15"))

    def test_no_sources_endpoint_any_more(self):
        paths = {r.path for r in api.router.routes}
        self.assertEqual(paths, {"", "/resolutions", "/resolutions/reopen"})


if __name__ == "__main__":
    unittest.main()
