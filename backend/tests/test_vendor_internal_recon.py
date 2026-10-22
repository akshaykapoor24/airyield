"""Vendor ↔ Internal reconciliation — the matching rules, on the real Globe cases."""
import unittest

from app.services.vendor_internal_recon import (
    DIFFERENCE, IN_PERIOD, INTERNAL_ONLY, MATCHED, NETTED, NEXT_STATEMENT, REFUND, SALE,
    VENDOR_ONLY, Line, _compare, _netted_row, _pair, _summary, apply_resolutions, match_lines,
)


def line(side, kind, net, fare=0.0, commission=0.0, charges=0.0, gst=0.0, tds=0.0, **kw):
    return Line(side=side, id=kw.pop("id", 1), serial=kw.pop("serial", "5808583279"),
                code=kw.pop("code", "607"), kind=kind, pax=kw.pop("pax", "SAHOTA/VIKAS"),
                pnr=kw.pop("pnr", None), sector="IST/AUH/DEL", date=kw.pop("date", None),
                ref=kw.pop("ref", None), source=kw.pop("source", None),
                amounts=dict(fare=fare, commission=commission, charges=charges, gst=gst, tds=tds, net=net))


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
        sale = line("vendor", SALE, 89375, fare=89257, charges=100, gst=18, id=1)
        refund = line("vendor", REFUND, -88785, fare=-89257, charges=354 + 100, gst=18, id=2)
        single = line("internal", SALE, 472, fare=354, charges=100, gst=18, id=3)
        row = _netted_row("4848173036", [sale, refund], single)
        self.assertEqual(row["kind"], NETTED)
        self.assertEqual(row["vendor"]["net"], 590)
        self.assertEqual(row["diff"]["net"], -118)
        self.assertIn("Sold and refunded on the vendor side", row["hints"][0])


def statements():
    """One of each case: Globe's weekly GDS statement against the monthly internal one."""
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


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.vendor, self.internal = statements()
        self.rows = match_lines(self.vendor, self.internal)
        self.by_ticket = {r["ticket_number"]: r for r in self.rows}

    def test_every_line_lands_in_one_case(self):
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

    def test_bridge_adds_up_to_the_net_difference(self):
        apply_resolutions(self.rows, {})
        s = _summary(self.rows, self.vendor, self.internal)
        self.assertEqual(round(sum(s["bridge"].values()), 2), s["net_difference"])
        self.assertEqual(s["bridge"][DIFFERENCE], -177.0)
        self.assertEqual(s["bridge"][VENDOR_ONLY], -8900.0)
        self.assertEqual(s["open"], {DIFFERENCE: 1, VENDOR_ONLY: 2, INTERNAL_ONLY: 2})

    def test_totals_count_tickets_as_well_as_lines(self):
        # A ticket sold and refunded is two lines but one ticket — on either side.
        vendor = [line("vendor", SALE, 500, serial="7", id=1), line("vendor", REFUND, -400, serial="7", id=2),
                  line("vendor", SALE, 300, serial="8", id=3)]
        internal = [line("internal", SALE, 500, serial="7", id=4)]
        rows = match_lines(vendor, internal)
        apply_resolutions(rows, {})
        s = _summary(rows, vendor, internal)
        self.assertEqual((s["vendor_lines"], s["vendor_tickets"]), (3, 2))
        self.assertEqual((s["internal_lines"], s["internal_tickets"]), (1, 1))
        self.assertEqual(s["tickets"], 2)


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
        s = _summary(self.rows, self.vendor, self.internal)
        self.assertEqual((s["open"][DIFFERENCE], s["resolved"][DIFFERENCE]), (0, 1))

    def test_changed_figures_reopen_the_line(self):
        # The internal statement was corrected to 12,200 after the decision was taken.
        apply_resolutions(self.rows, {self.diff["key"]: self.decision(internal_net=12200.0)})
        self.assertTrue(self.diff["open"])
        self.assertTrue(self.diff["resolution"]["stale"])

    def test_matched_lines_are_never_open(self):
        apply_resolutions(self.rows, {})
        self.assertTrue(all(not r["open"] for r in self.rows if r["status"] == MATCHED))


if __name__ == "__main__":
    unittest.main()
