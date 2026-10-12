"""Vendor ↔ Internal reconciliation — the matching rules, on the real Globe cases."""
import unittest

from app.services.vendor_internal_recon import (
    DIFFERENCE, MATCHED, NETTED, REFUND, SALE, Line, _compare, _netted_row, _pair,
)


def line(side, kind, net, fare=0.0, commission=0.0, charges=0.0, gst=0.0, tds=0.0, **kw):
    return Line(side=side, id=kw.pop("id", 1), serial=kw.pop("serial", "5808583279"),
                code=kw.pop("code", "607"), kind=kind, pax=kw.pop("pax", "SAHOTA/VIKAS"),
                pnr=kw.pop("pnr", None), sector="IST/AUH/DEL", date=None, ref=None, source=None,
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


if __name__ == "__main__":
    unittest.main()
