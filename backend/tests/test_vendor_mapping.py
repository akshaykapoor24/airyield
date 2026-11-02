"""Payment Module → Vendor Mapping and Vendor Payments: the vendor's statement against the MO on
the fare, what each line pays, holds and claims, and one account per vendor.

The figures are the real ones of TripJack's and Brightsun's first-week-of-October statements
against Yatra's sales report (the MO), checked 2026-10-29.

Run:  python -m unittest discover backend/tests
"""
import os
import sys
import unittest
from datetime import date, datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import vendor_internal_recon as recon  # noqa: E402
from app.services import vendor_mapping as vm  # noqa: E402

TJ = recon.vendor_key("Trip Jack Private Limited", "MUMBAI")
BS = recon.vendor_key("Brightsun", "new delhi")


def line(side, kind, net, base, tax, ssr=0.0, commission=0.0, tds=0.0, **kw):
    ident = kw.pop("id", 1)
    amounts = dict(fare=kw.pop("fare", base + tax + ssr), commission=commission, charges=0.0, gst=0.0, tds=tds,
                   net=net, commission_net=0.0, base=base, tax=tax, ssr=ssr)
    if side == "internal":
        amounts["comm_expected"] = kw.pop("comm_expected", 0.0)
    return recon.Line(side=side, id=ident, line_ids=[ident], serial=kw.pop("serial", "3978648383"), code="98",
                      kind=kind, pax="MR KUMAR", pnr=kw.pop("pnr", None), sector="DEL/BOM",
                      date=kw.pop("date", "2026-10-03"), ref=kw.pop("ref", None), source=kw.pop("source", None),
                      booked=kw.pop("booked", "2026-10-03"), vendor_key=kw.pop("vendor_key", TJ),
                      batches=kw.pop("batches", ["tj-1"]), amounts=amounts)


def stmt(batch, start, end, key=TJ, billed=0.0, opening=None, closing=None, slug="tp-gds"):
    return recon.Stmt(batch_id=batch, file_name=f"{batch}.xlsx", uploaded_at=datetime(2026, 10, 8),
                      period_from=date.fromisoformat(start), period_to=date.fromisoformat(end), vendor_key=key,
                      vendor_name="Trip Jack Private Limited", opening=opening, closing=closing, billed=billed,
                      slug=slug)


def book(vendor, internal, stmts=()):
    return recon.Book(vendor=vendor, internal=internal,
                      vendors={TJ: recon.Vendor(TJ, "Trip Jack Private Limited", "MUMBAI", ["GDS"], [41]),
                               BS: recon.Vendor(BS, "Brightsun", "new delhi", ["GDS"], [45])},
                      stmts={s.batch_id: s for s in stmts}, internal_ends={})


def mapped(vendor, internal, stmts=(), decisions=None):
    b = book(vendor, internal, stmts)
    out = vm.build_rows(b)
    vm.apply_decisions(out, decisions or {})
    return vm.Mapping(book=b, rows=out)


def decision(row, what, **over):
    return {row["key"]: {"decision": what, "note": "n", "status": row["status"],
                         "vendor_fare": over.get("vendor_fare", row["vendor"]["fare"]),
                         "mo_fare": over.get("mo_fare", row["mo"]["fare"] if row["mo"] else None),
                         "vendor_net": row["vendor"]["net"], "decided_at": None}}


class FareTests(unittest.TestCase):
    def test_the_fare_decides_not_the_net(self):
        # TripJack 3978648383: 41,005 + 19,288 on both; the vendor's net carries its commission.
        m = mapped([line("vendor", recon.SALE, 56295.75, 41005, 19288, commission=4078.82, tds=81.58)],
                   [line("internal", recon.SALE, 60293.0, 41005, 19288, comm_expected=3009.69)])
        r = m.rows[0]
        self.assertEqual(r["status"], vm.MATCHED)
        self.assertEqual(r["pay"], {"state": vm.PAY_CLEAR, "hold": 0.0, "claim": 0.0, "payable": 56295.75})
        self.assertEqual(r["commission_gap"], 1069.13)       # shown, never held

    def test_a_higher_fare_holds_the_excess_only(self):
        # TripJack 5809142216: tax 4,254 on the statement, 211 in the MO.
        m = mapped([line("vendor", recon.SALE, 5774.0, 1520, 4254, serial="5809142216")],
                   [line("internal", recon.SALE, 1731.0, 1520, 211, serial="5809142216")])
        r = m.rows[0]
        self.assertEqual((r["status"], r["gap"]), (vm.FARE_DIFF, 4043.0))
        self.assertTrue(r["hints"][0].startswith("Tax differs by 4,043.00"))
        self.assertEqual(r["pay"], {"state": vm.PAY_PART, "hold": 4043.0, "claim": 0.0, "payable": 1731.0})
        self.assertTrue(r["open"])

    def test_a_lower_fare_is_reviewed_not_held(self):
        m = mapped([line("vendor", recon.SALE, 359.0, 0, 359, fare=359)],
                   [line("internal", recon.SALE, 174097.0, 133270, 40827)])
        r = m.rows[0]
        self.assertEqual((r["status"], r["pay"]["state"], r["pay"]["hold"]), (vm.FARE_DIFF, vm.PAY_REVIEW, 0.0))
        self.assertIn("charges-only line", r["hints"][0])

    def test_a_refund_is_compared_on_what_it_gives_back(self):
        # TripJack 4849253318 prints the original fare (47,510) on its refund, positive, and
        # credits 39,200 net, the 288.44 commission taken back: 39,488.44 given back. The MO's
        # refund line gives back 15,428 + 24,060 — its Amount is the original ticket's.
        m = mapped([line("vendor", recon.REFUND, -39200.0, 23450, 24060, commission=288.44)],
                   [line("internal", recon.REFUND, 47510.0, -15428, -24060)])
        r = m.rows[0]
        self.assertEqual((r["status"], r["vendor"]["fare"], r["mo"]["fare"]), (vm.MATCHED, -39488.44, -39488.0))
        # Brightsun 4848850620 prints its refund negative: 31,168.04 credited + 875.47 − 17.51 TDS.
        m = mapped([line("vendor", recon.REFUND, -31168.04, -14550, -17476, commission=-875.47, tds=17.51)],
                   [line("internal", recon.REFUND, 32026.0, -14550, -17476)])
        self.assertEqual((m.rows[0]["status"], m.rows[0]["vendor"]["fare"]), (vm.MATCHED, -32026.0))


class KnockOffTests(unittest.TestCase):
    """A ticket is one row: each side's sale and refund knocked off, final against final."""

    def test_a_charges_line_against_an_mo_sale_and_refund(self):
        # Brightsun 3978247297: one 359 line of charges; the MO sold it at 1,74,097 and Yatra's
        # refund report gives back 1,73,743 (its Amount is the sale's — not what came back).
        m = mapped([line("vendor", recon.SALE, 359.0, 0, 0, fare=359.0, serial="3978247297")],
                   [line("internal", recon.SALE, 174097.0, 133270, 40827, serial="3978247297", id=1),
                    line("internal", recon.REFUND, 174097.0, -132916, -40827, serial="3978247297", id=2)])
        r = m.rows[0]
        self.assertEqual((r["kind"], r["mo_kind"], r["mo"]["fare"], r["gap"]), (vm.recon.SALE, vm.SALE_REFUND, 354.0, 5.0))
        self.assertEqual(r["pay"], {"state": vm.PAY_PART, "hold": 5.0, "claim": 0.0, "payable": 354.0})
        self.assertEqual([x["kind"] for x in r["mo_lines"]], [recon.SALE, recon.REFUND])
        self.assertEqual(r["mo_lines"][1]["fare"], -173743.0)
        self.assertIn("MO: sale 174,097.00 − refund 173,743.00 = 354.00", r["hints"][-1])

    def test_both_sides_sold_and_refunded(self):
        # TripJack 3978648421: a 354.01 cancellation charge billed as a sale, its refund line
        # crediting 0.01; the MO sold at 38,504 and refunded 38,150.
        m = mapped([line("vendor", recon.SALE, 354.01, 0, 354.01, id=1),
                    line("vendor", recon.REFUND, -0.01, 0, 354.01, id=2)],
                   [line("internal", recon.SALE, 38504.0, 29145, 9359, id=1),
                    line("internal", recon.REFUND, 38504.0, -28791, -9359, id=2)])
        r = m.rows[0]
        self.assertEqual(len(m.rows), 1)
        self.assertEqual((r["kind"], r["mo_kind"], r["status"]), (vm.SALE_REFUND, vm.SALE_REFUND, vm.MATCHED))
        self.assertEqual((r["vendor"]["fare"], r["mo"]["fare"], r["vendor"]["net"]), (354.0, 354.0, 354.0))

    def test_the_vendor_has_not_credited_the_refund_yet(self):
        m = mapped([line("vendor", recon.SALE, 7421.0, 5894, 1527)],
                   [line("internal", recon.SALE, 7421.0, 5894, 1527, id=1),
                    line("internal", recon.REFUND, 7421.0, -5844, -1527, id=2)])
        r = m.rows[0]
        self.assertEqual((r["status"], r["gap"]), (vm.FARE_DIFF, 7371.0))
        self.assertEqual(r["pay"]["hold"], 7371.0)          # held until the vendor credits it
        self.assertTrue(r["hints"][0].startswith("The MO has this ticket refunded (7,371.00 back)"))

    def test_the_vendor_credited_a_refund_the_mo_lacks(self):
        m = mapped([line("vendor", recon.SALE, 7421.0, 5894, 1527, id=1),
                    line("vendor", recon.REFUND, -7371.0, -5844, -1527, id=2)],
                   [line("internal", recon.SALE, 7421.0, 5894, 1527)])
        r = m.rows[0]
        self.assertEqual((r["status"], r["gap"], r["pay"]["state"]), (vm.FARE_DIFF, -7371.0, vm.PAY_REVIEW))
        self.assertTrue(r["hints"][0].startswith("The vendor credited a refund of 7,371.00 the MO does not have"))

    def test_a_refund_printed_with_mixed_signs_is_given_back(self):
        # Yatra 3978247334: two sales of 5,57,158 and a refund printing its Basic POSITIVE and
        # its tax negative — all of it given back; the final is one sale, as the vendor billed.
        m = mapped([line("vendor", recon.SALE, 543712.22, 334095, 223063)],
                   [line("internal", recon.SALE, 557158.0, 334095, 223063, id=1),
                    line("internal", recon.SALE, 557158.0, 334095, 223063, id=2),
                    line("internal", recon.REFUND, 557158.0, 334095, -223063, id=3)])
        self.assertEqual((m.rows[0]["mo"]["fare"], m.rows[0]["status"]), (557158.0, vm.MATCHED))

    def test_a_negative_fare_on_a_vendor_sale_line_is_a_refund(self):
        # Brightsun 4848180964: its second line is a "sale" by its status, Basic −41,385.
        m = mapped([line("vendor", recon.SALE, 59.0, 0, 0, fare=59.0, id=1),
                    line("vendor", recon.SALE, 2289.83, -41385, -30422, commission=-2336.56, tds=46.73, id=2)],
                   [line("internal", recon.REFUND, 71807.0, -30281, -30422)])
        r = m.rows[0]
        self.assertEqual(r["kind"], vm.SALE_REFUND)
        self.assertEqual(r["vendor_lines"][1]["kind"], recon.REFUND)

    def test_the_airline_cancellation_charge_is_not_given_back(self):
        # Yatra 5809142213: the refund prints the whole Basic (1,18,022) and the airline kept all
        # of it as its cancellation charge — only the 169 tax came back.
        def mo_refund(base, tax, charge, nett=0.0, **kw):
            ln = line("internal", recon.REFUND, 169.0, base, tax, **kw)
            ln.amounts.update(airline_charge=charge, net_cancel=nett)
            return ln
        m = mapped([line("vendor", recon.SALE, 169.0, 0, 169, serial="5809142213", id=1),
                    line("vendor", recon.REFUND, -4153.0, 0, -4153, serial="5809142213", id=2)],
                   [line("internal", recon.SALE, 169.0, 0, 169, serial="5809142213", id=1),
                    mo_refund(-118022, -169, 118022, -117853, serial="5809142213", id=2)])
        r = m.rows[0]
        self.assertEqual((r["mo_lines"][1]["fare"], r["mo_lines"][1]["charge"], r["mo"]["fare"]), (-169.0, 118022.0, 0.0))
        self.assertIn("The airline kept 118,022.00 as its cancellation charge", r["hints"][-1])

    def test_the_cancellation_charge_on_both_sides(self):
        # TripJack 4849253318 prints the original 47,510 on its refund with an Agent Penalty of
        # 8,022; Yatra's refund Basic is already less the same 8,022 and prints it again on the
        # sale. Both sides: 39,488 given back, the charge 8,022 — counted once.
        v = line("vendor", recon.REFUND, -39200.0, 23450, 24060, commission=288.44)
        v.amounts["canc_charge"] = 8022.0
        refund = line("internal", recon.REFUND, 47510.0, -15428, -24060)
        refund.amounts.update(airline_charge=8022.0, net_cancel=39488.0)     # = Basic + Tax: already off
        r = mapped([v], [refund]).rows[0]
        self.assertEqual((r["vendor"]["fare"], r["mo"]["fare"], r["status"]), (-39488.0, -39488.0, vm.MATCHED))
        self.assertTrue(r["vendor_lines"][0]["charge_applied"])
        self.assertFalse(r["mo_lines"][0]["charge_applied"])
        self.assertEqual((r["vendor"]["charge"], r["mo"]["charge"]), (8022.0, 8022.0))

    def test_the_charge_printed_on_the_sale_only_is_taken_off_the_refund_once(self):
        sale = line("internal", recon.SALE, 41896.0, 23790, 18106, id=1)
        sale.amounts["airline_charge"] = 354.0
        refund = line("internal", recon.REFUND, 41896.0, -23790, -18106, id=2)
        r = mapped([line("vendor", recon.SALE, 354.0, 0, 354)], [sale, refund]).rows[0]
        self.assertEqual((r["mo_lines"][1]["fare"], r["mo"]["fare"], r["mo"]["charge"]), (-41542.0, 354.0, 354.0))
        self.assertEqual(r["status"], vm.MATCHED)

    def test_a_charges_line_is_not_taken_off_again(self):
        # Brightsun's "Sales" line of 359 carries Cancellation Charges of 300 — it bills them.
        v = line("vendor", recon.SALE, 359.0, 0, 0, fare=359.0)
        v.amounts["canc_charge"] = 300.0
        r = mapped([v], [line("internal", recon.SALE, 354.0, 354, 0)]).rows[0]
        self.assertEqual((r["vendor"]["fare"], r["vendor"]["charge"]), (359.0, 300.0))
        self.assertFalse(r["vendor_lines"][0]["charge_applied"])

    def test_a_charge_already_off_the_basic_is_not_taken_twice(self):
        # 5882961640: sold at 23,790; the refund Basic is 23,436 — the 354 charge already off it.
        nett = dict(base=-23436, tax=-18106, airline_charge=354)
        self.assertEqual(vm.mo_given_back({**nett, "net_cancel": 41542}, 23790), 41542)
        self.assertEqual(vm.mo_given_back(nett, 23790), 41542)              # told by the sale
        # Printed apart (DCYP2D16E): Net Cancellation Amount 1,424 = 3,093 + 1,799 − 3,468.
        self.assertEqual(vm.mo_given_back({"base": 3093, "tax": -1799, "airline_charge": 3468, "net_cancel": 1424}, 3093), 1424)
        self.assertEqual(vm.mo_given_back({"base": -23790, "tax": -18106, "airline_charge": 354}, 23790), 41542)
        self.assertEqual(vm.mo_given_back({"base": -100, "tax": -10}), 110)  # no charge: all of it

    def test_one_row_per_ticket_and_vendor(self):
        m = mapped([line("vendor", recon.SALE, 100.0, 80, 20, id=1),
                    line("vendor", recon.SALE, 100.0, 80, 20, id=2, vendor_key=BS)],
                   [line("internal", recon.SALE, 100.0, 80, 20)])
        self.assertEqual(sorted(r["vendor_name"] for r in m.rows), ["Brightsun", "Trip Jack Private Limited"])
        self.assertTrue(all(any(h.startswith("Also billed by") for h in r["hints"]) for r in m.rows))


class PayableTests(unittest.TestCase):
    def test_not_in_the_mo_holds_a_sale_and_takes_a_credit(self):
        m = mapped([line("vendor", recon.SALE, 237402.42, 200000, 43300, serial="3978247281", id=1),
                    line("vendor", recon.REFUND, -39200.0, 23450, 24060, serial="3978648401", id=2)], [])
        by = {r["kind"]: r for r in m.rows}
        self.assertEqual(by[recon.SALE]["pay"], {"state": vm.PAY_HOLD, "hold": 237402.42, "claim": 0.0, "payable": 0.0})
        self.assertEqual(by[recon.REFUND]["pay"]["state"], vm.PAY_CREDIT)
        self.assertEqual(by[recon.REFUND]["pay"]["payable"], -39200.0)

    def test_booked_under_another_vendor_is_held(self):
        m = mapped([line("vendor", recon.SALE, 60293.0, 41005, 19288)],
                   [line("internal", recon.SALE, 60293.0, 41005, 19288, vendor_key=BS)])
        r = m.rows[0]
        self.assertEqual((r["status"], r["mo_vendor_name"]), (vm.OTHER_VENDOR, "Brightsun"))
        self.assertEqual(r["pay"]["hold"], 60293.0)

    def test_decisions_claim_or_pay(self):
        v = [line("vendor", recon.SALE, 5774.0, 1520, 4254, serial="5809142216")]
        i = [line("internal", recon.SALE, 1731.0, 1520, 211, serial="5809142216")]
        row = mapped(v, i).rows[0]
        claimed = mapped(v, i, decisions=decision(row, "vendor_wrong")).rows[0]
        self.assertEqual(claimed["pay"], {"state": vm.PAY_CLAIM, "hold": 0.0, "claim": 4043.0, "payable": 1731.0})
        self.assertFalse(claimed["open"])
        accepted = mapped(v, i, decisions=decision(row, "accepted")).rows[0]
        self.assertEqual(accepted["pay"]["payable"], 5774.0)
        # Taken on other figures: the line is open again, its old decision beside it.
        stale = mapped(v, i, decisions=decision(row, "accepted", mo_fare=1500.0)).rows[0]
        self.assertTrue(stale["open"] and stale["decision"]["stale"])
        self.assertEqual(stale["pay"]["hold"], 4043.0)


class SummaryTests(unittest.TestCase):
    def test_the_tiles_add_up_from_the_vendor_side_only(self):
        m = mapped(
            [line("vendor", recon.SALE, 60293.0, 41005, 19288, serial="1", id=1),             # matched
             line("vendor", recon.SALE, 5774.0, 1520, 4254, serial="2", id=2),                # +4,043 over MO
             line("vendor", recon.SALE, 359.0, 0, 359, serial="3", id=3),                     # below MO
             line("vendor", recon.SALE, 22850.0, 20000, 2850, serial="4", id=4),              # not in MO
             line("vendor", recon.REFUND, -39200.0, 23450, 24060, serial="5", id=5)],         # refund, not in MO
            [line("internal", recon.SALE, 60293.0, 41005, 19288, serial="1"),
             line("internal", recon.SALE, 1731.0, 1520, 211, serial="2"),
             line("internal", recon.SALE, 174097.0, 133270, 40827, serial="3"),
             line("internal", recon.SALE, 9000.0, 8000, 1000, serial="9")])                   # MO only: never counted
        s = vm.summarize(m.rows)
        self.assertEqual(s["lines"], 5)
        self.assertEqual({k: v["lines"] for k, v in s["status"].items()},
                         {vm.MATCHED: 1, vm.FARE_DIFF: 2, vm.NOT_IN_MO: 2, vm.OTHER_VENDOR: 0})
        self.assertEqual((s["fare_excess"], s["fare_short"]), (4043.0, -173738.0))
        self.assertEqual((s["status"][vm.NOT_IN_MO]["sales"], s["status"][vm.NOT_IN_MO]["refunds"]), (22850.0, 1))
        self.assertEqual(s["billed"], 50076.0)
        self.assertEqual(len(m.rows), 5)              # the MO-only ticket is not a row


class TaxTests(unittest.TestCase):
    def test_a_total_tax_column_that_is_the_other_taxes(self):
        # Brightsun 3978247263: SellTax 9,116 mapped onto Total Tax, YQ / YR / K3 apart.
        big = {"yq": 13963, "yr": 11970, "k3": 49562, "taxes": 9116}
        small = {"yq": 5210, "taxes": 5532}          # 3978247304 — other taxes above its YQ
        rows = [SimpleNamespace(batch_id="bs", data=d) for d in (big, big, small)]
        rows.append(SimpleNamespace(batch_id="tj", data={"yq": 9618, "k3": 2532, "other_taxes": 7138, "taxes": 19288}))
        self.assertEqual(recon.total_tax_is_other_taxes(rows), {"bs"})
        self.assertEqual(recon.vendor_tax(big, True), 84611)
        self.assertEqual(recon.vendor_tax(small, True), 10742)
        self.assertEqual(recon.vendor_tax({"yq": 9618, "k3": 2532, "other_taxes": 7138, "taxes": 19288}), 19288)
        self.assertEqual(recon.vendor_tax({"yq": 100, "other_taxes": 50}), 150)


class AccountTests(unittest.TestCase):
    def test_allocation_oldest_first_and_a_payment_against_one_statement(self):
        items = [{"ref": "w1", "due": 1000.0, "day": date(2026, 10, 7)},
                 {"ref": "w2", "due": -200.0, "day": date(2026, 10, 14)},      # a credit statement
                 {"ref": "w3", "due": 500.0, "day": date(2026, 10, 21)}]
        pays = [{"amount": 300.0, "day": date(2026, 10, 22), "statement": "w3"},
                {"amount": 1000.0, "day": date(2026, 10, 25), "statement": None}]
        left = vm.allocate(items, pays)
        # 300 goes to w3 as paid; the credit and the 1,000 then settle w1 and the rest of w3.
        self.assertEqual([it["paid"] for it in items], [1000.0, 0.0, 500.0])
        self.assertEqual(items[1]["credit_used"], 200.0)
        self.assertEqual(left, 0.0)                 # 1,300 paid + the 200 credit = the 1,500 owed
        self.assertEqual([p["applied"] for p in pays], [300.0, 1000.0])

    def test_paying_more_than_is_owed_leaves_an_advance(self):
        items = [{"ref": "w1", "due": 1000.0, "day": date(2026, 10, 7)}]
        pays = [{"amount": 1250.0, "day": date(2026, 10, 9), "statement": None}]
        self.assertEqual(vm.allocate(items, pays), 250.0)
        self.assertEqual(items[0]["paid"], 1000.0)

    def test_one_vendor_account(self):
        stmts = [stmt("tj-1", "2026-10-01", "2026-10-07", billed=6000.0, opening=500.0, closing=4300.0),
                 stmt("tj-2", "2026-10-08", "2026-10-14", billed=2000.0)]
        v = [line("vendor", recon.SALE, 5774.0, 1520, 4254, serial="1", batches=["tj-1"], id=1),
             line("vendor", recon.SALE, 226.0, 200, 26, serial="2", batches=["tj-1"], id=2),
             line("vendor", recon.SALE, 2000.0, 1800, 200, serial="3", batches=["tj-2"], id=3,
                  date="2026-10-10", booked="2026-10-10")]
        i = [line("internal", recon.SALE, 1731.0, 1520, 211, serial="1"),
             line("internal", recon.SALE, 226.0, 200, 26, serial="2"),
             line("internal", recon.SALE, 2000.0, 1800, 200, serial="3", booked="2026-10-10")]
        first = mapped(v, i, stmts)
        claim = next(r for r in first.rows if r["ticket_number"] == "1")
        m = mapped(v, i, stmts, decisions=decision(claim, "vendor_wrong"))
        pay = SimpleNamespace(id=7, payment_date=date(2026, 10, 9), amount=2200, status="completed",
                              mode="NEFT", reference="UTR1", remarks=None, vendor_batch_id=None,
                              void_reason=None, voided_at=None, created_at=datetime(2026, 10, 9), vendor_name=None)
        a = vm.account(m, TJ, [pay], date(2026, 10, 29))
        t = a["totals"]
        # 500 opening + 8,000 billed − 4,043 claimed − 2,200 paid.
        self.assertEqual((t["billed"], t["claims"], t["paid"], t["balance"]), (8000.0, 4043.0, 2200.0, 2257.0))
        self.assertEqual(t["payable_now"], 2257.0)
        s1, s2 = a["statements"]
        self.assertEqual((s1["due"], s1["paid"], s1["state"]), (1957.0, 1700.0, "part_paid"))   # opening first
        self.assertEqual((s2["balance"], s2["state"]), (2000.0, "unpaid"))
        self.assertEqual([e["balance"] for e in a["ledger"]], [500.0, 6500.0, 2457.0, 257.0, 2257.0])
        # The vendor printed 4,300 at 7 Oct: 500 + 6,000 billed, nothing paid by then.
        self.assertEqual(a["check"], {"as_at": "2026-10-07", "statement": "tj-1", "file_name": "tj-1.xlsx",
                                      "vendor": 4300.0, "ours": 6500.0, "difference": -2200.0})
        self.assertEqual(sum(b["amount"] for b in a["aging"]), 2257.0)


if __name__ == "__main__":
    unittest.main()
