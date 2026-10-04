"""Payment Module: a consolidator's bill against our mid-office record, per ticket.

The judgements that decide whether the payable figure can be trusted:

  * the key is the document serial, with the airline code kept beside it as the check;
  * the statement's own BALANCE line is a balance, never a ticket;
  * both sides are netted per ticket, so a cancellation is not compared to a whole sale;
  * variance is vendor − MO, to the rupee — two records of one bill carry no markup;
  * commission adjusts the payable only where a deal priced the row and the vendor's own
    arithmetic closed — a skipped cancellation's claw-back is never "owed to us".

No DB, no network.  Run:  ..\\venv\\Scripts\\python.exe -m pytest test_payment_reconciliation.py
"""
from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.payment_reconciliation import (  # noqa: E402
    COMMISSION_NOT_RUN, COMMISSION_PARTIAL, COMMISSION_PRICED, COMMISSION_SKIPPED,
    COMMISSION_UNPRICED, STATUS_MATCHED, STATUS_MINOR_DIFF, STATUS_MISMATCH, STATUS_MO_ONLY,
    STATUS_POSSIBLE, STATUS_VENDOR_ONLY,
)
from app.services.payment_reconciliation import (  # noqa: E402
    CalcFigure, _pax_key, balance_figures, balance_kind, build_pay_row, exact_net,
    group_rows, reconcile, split_rows, tally,
)
from app.services.reconciliation.adapters import _norm  # noqa: E402

D = Decimal

# Where the real consolidator export lives on the machine that prompted the feature.
REAL_STATEMENT = os.environ.get(
    "TP_GDS_SAMPLE",
    r"C:\Users\manve\OneDrive\Desktop\FareQube Docs\TriumphTravel"
    r"\TRIUMPHH BSP STATEMENT 16-22ND AUG 26.xlsx",
)


def data(ticket: str | None = "5808758786", prefix: str | None = "157", **over) -> dict:
    """A `third_party_gds` / `mid_office_gds` `data` blob as ingest writes one — amounts as
    STRINGS. Net = 1000 + 0 + 200 - 0 + 0 + 100 + 18 = 1318. A None in `over` drops a key."""
    d = {
        "ticket_number": ticket, "ticket_prefix": prefix, "ticket_status": "CONFIRMED",
        "base_fare": "1000", "yq": "0", "other_taxes": "200", "total_fare": "1200.00",
        "commission_amount": "0", "tds": "0", "service_fee": "100", "gst_on_sf": "18",
        "net_amount": "1318", "airline_master_name": "QATAR AIRWAYS", "airline_code": "QR",
        "issue_date": "2026-08-16", "passenger_name": "DANIAL NAHAR", "sector": "DEL/IST",
    }
    d.update(over)
    return {k: v for k, v in d.items() if v is not None}


def row(rid: int, **kw):
    return build_pay_row(rid, data(**kw))


def one(results: list[dict], status: str) -> dict:
    hits = [r for r in results if r["match_status"] == status]
    assert len(hits) == 1, f"expected one {status}, got {[r['match_status'] for r in results]}"
    return hits[0]


# ── normalising a row ────────────────────────────────────────────────────────
class TestNormaliser(unittest.TestCase):

    def test_the_serial_is_the_key_and_the_code_rides_beside_it(self):
        r = row(1)
        self.assertEqual(r.ticket_key, _norm("5808758786"))
        self.assertEqual(r.ticket_prefix, "157")
        self.assertEqual(r.ticket_number, "5808758786")

    def test_a_two_digit_prefix_is_padded(self):
        self.assertEqual(row(1, prefix="75").ticket_prefix, "075")

    def test_a_cell_holding_both_halves_is_split(self):
        r = row(1, ticket="607 5808583279", prefix=None)
        self.assertEqual((r.ticket_prefix, r.ticket_number), ("607", "5808583279"))

    def test_tax_is_yq_plus_the_rest_of_the_bill(self):
        self.assertEqual(row(1, yq="150", other_taxes="200").amounts["tax"], D("350"))

    def test_total_tax_stands_in_for_other_taxes_never_beside_it(self):
        r = row(1, yq="150", other_taxes=None, taxes="200")
        self.assertEqual(r.amounts["tax"], D("350"))

    def test_tax_is_none_when_nothing_is_printed(self):
        self.assertIsNone(row(1, yq=None, other_taxes=None).amounts["tax"])

    def test_an_unparseable_amount_is_noted_not_zeroed(self):
        r = row(1, base_fare="N/A")
        self.assertIsNone(r.amounts["fare"])
        self.assertTrue(any("base_fare" in n for n in r.notes))

    def test_the_master_airline_spelling_wins(self):
        r = row(1, airline_name="QATAR AIRWAYS Q.C.S.C", airline_master_name="QATAR AIRWAYS")
        self.assertEqual(r.airline_name, "QATAR AIRWAYS")

    def test_passenger_key_ignores_title_order_and_punctuation(self):
        self.assertEqual(_pax_key("MR. SAHOTA/VIKAS"), _pax_key("Mr Vikas Sahota"))
        self.assertIsNone(_pax_key("MR"))


# ── balance lines ────────────────────────────────────────────────────────────
class TestBalanceLines(unittest.TestCase):

    # Exactly what ingest stores for the real export's last line.
    BALANCE_ROW = {"cancellation_markup": "BALANCE", "net_amount": "960428.4259999999"}

    def test_the_real_closing_line_is_a_balance(self):
        self.assertEqual(balance_kind(self.BALANCE_ROW), ("closing", "BALANCE"))

    def test_an_old_line_kept_as_a_row_is_the_opening(self):
        self.assertEqual(balance_kind({"cancellation_markup": "OLD", "net_amount": "627257"}),
                         ("opening", "OLD"))

    def test_a_labelled_total_is_neither_balance(self):
        self.assertEqual(balance_kind({"remarks": "Grand Total", "net_amount": "5"})[0], "total")

    def test_a_booking_is_never_a_balance_line_whatever_its_remarks_say(self):
        self.assertIsNone(balance_kind(data(remarks="BALANCE")))

    def test_a_lone_unlabelled_net_is_a_footer(self):
        self.assertEqual(balance_kind({"net_amount": "100"}), ("total", "UNLABELLED TOTAL"))

    def test_an_unidentified_row_with_real_money_is_not_swallowed(self):
        self.assertIsNone(balance_kind({"base_fare": "100", "net_amount": "100"}))

    def test_split_rows_lifts_balance_lines_out_of_the_tickets(self):
        tickets, lines = split_rows([(1, data()), (2, self.BALANCE_ROW)])
        self.assertEqual([t.row_id for t in tickets], [1])
        self.assertEqual(lines, [{"kind": "closing", "label": "BALANCE", "row_id": 2,
                                  "amount": 960428.43, "raw": "960428.4259999999"}])

    def test_the_derived_opening_is_not_skewed_by_per_ticket_rounding(self):
        # Two tickets of x.0062 each round up a paisa apiece; the unrounded sum does not.
        tickets = [row(1, net_amount="100.0062"), row(2, ticket="5808758787", net_amount="100.0062")]
        self.assertEqual(exact_net(tickets), D("200.0124"))
        out = balance_figures([{"kind": "closing", "amount": 1200.01, "raw": "1200.0124"}],
                              exact_net(tickets))
        self.assertEqual(out["opening"], 1000.0)

    def test_opening_is_derived_from_closing_minus_the_period_net(self):
        # The real 16-22 Aug statement: OLD 627,257 + Σ net 333,171.43 = BALANCE 960,428.43.
        out = balance_figures([{"kind": "closing", "amount": 960428.43}], D("333171.43"))
        self.assertEqual(out, {"closing": 960428.43, "opening": 627257.0,
                               "opening_derived": True, "payments": None})

    def test_payments_in_the_period_are_added_back_to_the_derived_opening(self):
        # The 08-15 Aug statement prints a LESS PAYMENT line: opening + Σ net − payments =
        # closing, so the opening is closing − Σ net + payments. The sign as printed is moot.
        out = balance_figures([{"kind": "payment", "amount": -400.0},
                               {"kind": "closing", "amount": 600.0}], D("300"))
        self.assertEqual(out, {"closing": 600.0, "opening": 700.0,
                               "opening_derived": True, "payments": 400.0})

    def test_a_printed_opening_is_not_overwritten(self):
        out = balance_figures([{"kind": "opening", "amount": 10.0},
                               {"kind": "closing", "amount": 30.0}], D("5"))
        self.assertEqual((out["opening"], out["opening_derived"]), (10.0, False))


# ── netting per ticket ───────────────────────────────────────────────────────
class TestNetting(unittest.TestCase):

    def test_issue_and_cancellation_net_to_one_ticket(self):
        groups = group_rows([
            row(1, net_amount="1318"),
            row(2, ticket_status="CANCELLED", base_fare="-1000", other_taxes="-200",
                total_fare="-1200.00", net_amount="-1082"),
        ])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].amount("net"), D("236"))
        self.assertEqual(groups[0].row_ids, [1, 2])
        self.assertTrue(any("net of 2 rows" in n for n in groups[0].notes("vendor")))

    def test_rows_with_no_ticket_and_no_pnr_are_never_pooled(self):
        groups = group_rows([row(1, ticket=None, prefix=None), row(2, ticket=None, prefix=None)])
        self.assertEqual(len(groups), 2)

    def test_pnr_and_passenger_group_a_booking_with_no_ticket_number(self):
        groups = group_rows([row(1, ticket=None, prefix=None, airline_pnr="ABC123"),
                             row(2, ticket=None, prefix=None, airline_pnr="abc123",
                                 passenger_name="Mr Danial Nahar")])
        self.assertEqual(len(groups), 1)


# ── pairing and comparing ────────────────────────────────────────────────────
class TestPairing(unittest.TestCase):

    def test_the_same_ticket_on_both_sides_is_matched(self):
        r = one(reconcile([row(1)], [row(9)], {}, commission_ran=False), STATUS_MATCHED)
        self.assertEqual(r["match_method"], "ticket_number")
        self.assertEqual(r["net_variance"], 0.0)
        self.assertEqual((r["vendor_row_ids"], r["mo_row_ids"]), ([1], [9]))

    def test_variance_is_vendor_minus_mo(self):
        r = one(reconcile([row(1, net_amount="1500")], [row(9)], {}, commission_ran=False),
                STATUS_MISMATCH)
        self.assertEqual(r["net_variance"], 182.0)
        net = next(f for f in r["field_diffs"] if f["key"] == "net")
        self.assertEqual((net["vendor"], net["mo"], net["variance"]), (1500.0, 1318.0, 182.0))

    def test_a_rupee_is_inside_tolerance_and_two_are_not(self):
        ok = reconcile([row(1, net_amount="1319")], [row(9)], {}, commission_ran=False)
        self.assertEqual(ok[0]["match_status"], STATUS_MATCHED)
        bad = reconcile([row(1, net_amount="1320")], [row(9)], {}, commission_ran=False)
        self.assertEqual(bad[0]["match_status"], STATUS_MISMATCH)

    def test_no_percentage_allowance_on_a_large_fare(self):
        # 0.5% of 1,00,000 would hide ₹500 — there is no markup between two copies of a bill.
        out = reconcile([row(1, base_fare="100500", net_amount="101818")],
                        [row(9, base_fare="100000", net_amount="101318")], {},
                        commission_ran=False)
        self.assertEqual(out[0]["match_status"], STATUS_MISMATCH)

    def test_a_warning_field_alone_is_a_minor_difference(self):
        out = reconcile([row(1, tds="5", net_amount="1323")],
                        [row(9, tds="0", net_amount="1323")], {}, commission_ran=False)
        self.assertEqual(out[0]["match_status"], STATUS_MINOR_DIFF)
        self.assertEqual([i["field"] for i in out[0]["issues"]], ["tds"])

    def test_one_serial_under_two_airlines_is_only_a_suggestion(self):
        out = reconcile([row(1, prefix="075")], [row(9, prefix="125")], {},
                        commission_ran=False)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["match_status"], STATUS_POSSIBLE)
        self.assertIsNone(r["net_variance"])
        self.assertIsNone(r["abs_net_variance"])

    def test_pnr_and_passenger_pair_only_when_one_side_prints_no_ticket(self):
        v = row(1, airline_pnr="HNVTK1")
        m = row(9, ticket=None, prefix=None, airline_pnr="HNVTK1",
                passenger_name="NAHAR/DANIAL")
        r = one(reconcile([v], [m], {}, commission_ran=False), STATUS_MATCHED)
        self.assertEqual(r["match_method"], "pnr_pax")

    def test_two_tickets_on_one_pnr_are_never_paired_by_guesswork(self):
        # An outbound and a return issued separately to one passenger on one PNR.
        v = row(1, ticket=None, prefix=None, airline_pnr="HNVTK1")
        m1 = row(8, ticket="5808758786", airline_pnr="HNVTK1")
        m2 = row(9, ticket="5808758787", airline_pnr="HNVTK1")
        out = reconcile([v], [m1, m2], {}, commission_ran=False)
        self.assertEqual(sorted(r["match_status"] for r in out),
                         [STATUS_MO_ONLY, STATUS_MO_ONLY, STATUS_VENDOR_ONLY])

    def test_leftovers_are_one_sided_and_are_not_compared(self):
        out = reconcile([row(1, ticket="1111111111")], [row(9, ticket="2222222222")], {},
                        commission_ran=False)
        v, m = one(out, STATUS_VENDOR_ONLY), one(out, STATUS_MO_ONLY)
        self.assertEqual((v["severity"], m["severity"]), ("critical", "warning"))
        self.assertTrue(all(f["variance"] is None for f in v["field_diffs"]))
        # Sorted by the money nobody can account for.
        self.assertEqual((v["abs_net_variance"], m["abs_net_variance"]), (1318.0, 1318.0))
        self.assertIsNone(v["net_variance"])


# ── commission and the payable ───────────────────────────────────────────────
class TestCommission(unittest.TestCase):

    # Declared 10 + 5; the deal says IATA 20 + incentive 40 → shortfall (20-10)+(40-5) = 45.
    # Net = 1000 + 200 - 10 - 5 + 100 + 18 = 1303.
    PRICED = dict(commission_amount="10", incentive_amount="5", net_amount="1303")

    def _single(self, calcs, *, ran=True, **over):
        out = reconcile([row(1, **{**self.PRICED, **over})], [row(9, **{**self.PRICED, **over})],
                        calcs, commission_ran=ran)
        return one(out, STATUS_MATCHED)

    def test_not_run_leaves_the_bill_alone(self):
        r = self._single({}, ran=False)
        self.assertEqual(r["commission_status"], COMMISSION_NOT_RUN)
        self.assertIsNone(r["calc_commission"])
        self.assertEqual(r["payable_after_commission"], 1303.0)
        self.assertEqual(r["vendor_commission"], 15.0)

    def test_a_priced_row_reduces_the_payable_by_the_shortfall(self):
        calcs = {1: CalcFigure("calculated", incentive=D("40"), iata=D("20"),
                               variance_total=D("45"), net_ok=True, deal_no="B2B-000001")}
        r = self._single(calcs)
        self.assertEqual(r["commission_status"], COMMISSION_PRICED)
        self.assertEqual(r["calc_commission"], 60.0)
        self.assertEqual(r["commission_shortfall"], 45.0)
        self.assertEqual(r["payable_after_commission"], 1258.0)
        self.assertEqual(r["commission_detail"][0]["deal_no"], "B2B-000001")

    def test_a_skipped_cancellation_claws_back_nothing_from_us(self):
        # The real 16-22 Aug row 607 5808583279: CANCELLED, Agent Commission -205.81. The
        # engine skips it, yet stores variance +205.81 against its calculated zero.
        cancel = dict(ticket="5808583279", prefix="607", ticket_status="CANCELLED",
                      base_fare="-33465", yq=None, other_taxes="-21604",
                      total_fare="-55069.00", commission_amount="-205.81", tds="-4.1162",
                      cancellation_markup="26481.59", net_amount="-28267.7162",
                      incentive_amount=None)
        calcs = {1: CalcFigure("skipped", reason="Cancelled booking — not a sale",
                               variance_total=D("205.81"), net_ok=True)}
        out = reconcile([row(1, **cancel)], [row(9, **cancel)], calcs, commission_ran=True)
        r = one(out, STATUS_MATCHED)
        self.assertEqual(r["commission_status"], COMMISSION_SKIPPED)
        self.assertIsNone(r["commission_shortfall"])
        self.assertEqual(r["payable_after_commission"], -28267.72)

    def test_no_deal_is_not_a_reason_to_pay_more(self):
        calcs = {1: CalcFigure("unmatched", reason="No matching approved B2B deal found",
                               variance_total=D("-15"), net_ok=True)}
        r = self._single(calcs)
        self.assertEqual(r["commission_status"], COMMISSION_UNPRICED)
        self.assertIsNone(r["commission_shortfall"])
        self.assertEqual(r["payable_after_commission"], 1303.0)

    def test_arithmetic_that_does_not_close_claims_no_shortfall(self):
        calcs = {1: CalcFigure("calculated", incentive=D("40"), iata=D("20"),
                               variance_total=None, net_ok=False)}
        r = self._single(calcs)
        self.assertEqual(r["commission_status"], COMMISSION_PARTIAL)
        self.assertEqual(r["calc_commission"], 60.0)
        self.assertIsNone(r["commission_shortfall"])
        self.assertIn("note", r["commission_detail"][0])

    def test_issue_priced_and_cancellation_skipped_is_fully_priced(self):
        rows_ = [row(1, **self.PRICED),
                 row(2, ticket_status="CANCELLED", base_fare="-1000", other_taxes="-200",
                     total_fare="-1200.00", commission_amount="-10", incentive_amount="-5",
                     net_amount="-1067")]
        calcs = {1: CalcFigure("calculated", incentive=D("40"), iata=D("20"),
                               variance_total=D("45"), net_ok=True),
                 2: CalcFigure("skipped", variance_total=D("15"), net_ok=True)}
        r = reconcile(rows_, [], calcs, commission_ran=True)[0]
        self.assertEqual(r["commission_status"], COMMISSION_PRICED)
        self.assertEqual(r["commission_shortfall"], 45.0)
        self.assertEqual(r["payable_after_commission"], 236.0 - 45.0)

    def test_a_row_added_after_the_commission_run_is_called_out(self):
        r = self._single({}, ran=True)
        self.assertEqual(r["commission_status"], COMMISSION_UNPRICED)
        self.assertEqual(r["commission_detail"][0]["status"], "missing")

    def test_an_mo_only_ticket_has_no_commission(self):
        r = one(reconcile([], [row(9)], {}, commission_ran=True), STATUS_MO_ONLY)
        self.assertEqual(r["commission_status"], "none")
        self.assertIsNone(r["payable_after_commission"])


# ── roll-up ──────────────────────────────────────────────────────────────────
class TestTally(unittest.TestCase):

    def test_totals_follow_the_rows(self):
        out = reconcile(
            [row(1, ticket="1000000001"), row(2, ticket="1000000002", net_amount="1500"),
             row(3, ticket="1000000003", net_amount="500")],
            [row(7, ticket="1000000001"), row(8, ticket="1000000002"),
             row(9, ticket="1000000009", net_amount="700")],
            {}, commission_ran=False)
        t = tally(out)
        self.assertEqual(t["counts"][STATUS_MATCHED], 1)
        self.assertEqual(t["counts"][STATUS_MISMATCH], 1)
        self.assertEqual(t["counts"][STATUS_VENDOR_ONLY], 1)
        self.assertEqual(t["counts"][STATUS_MO_ONLY], 1)
        self.assertEqual(t["vendor_net"], 1318.0 + 1500.0 + 500.0)     # the whole bill
        self.assertEqual(t["mo_net"], 1318.0 + 1318.0 + 700.0)
        self.assertEqual(t["net_variance"], 182.0)                     # paired rows only
        self.assertEqual((t["vendor_only"], t["mo_only"]), (500.0, 700.0))
        self.assertEqual(t["payable"], t["vendor_net"])                # no commission run


# ── steps 6A–6E ──────────────────────────────────────────────────────────────
def mo_row(rid: int, *, batch="mo1", supplier_id=751, supplier_name="Globe Air Travels",
           vendor_status="ok", corrected_from=None, **kw):
    origin = {"batch_id": batch, "source_file": f"{batch}.xlsx", "supplier_id": supplier_id,
              "supplier_name": supplier_name, "vendor_status": vendor_status}
    if corrected_from:
        origin["corrected_from"] = corrected_from
    return build_pay_row(rid, data(**kw), origin=origin)


class TestDuplicates(unittest.TestCase):
    """6A/6B: a sale billed again is a duplicate; an issue + cancellation never is."""

    PRIOR = {_norm("5808758786"): {"batch_id": "old", "source_file": "08-15.xlsx",
                                   "uploaded_at": "2026-09-20T10:00:00", "prefix": "157",
                                   "paid": True}}

    def test_a_sale_billed_on_an_earlier_statement_is_a_duplicate(self):
        r = reconcile([row(1)], [row(9)], {}, commission_ran=False, prior_sales=self.PRIOR)[0]
        self.assertTrue(r["is_duplicate"])
        self.assertEqual(r["duplicate_info"]["kind"], "earlier")
        self.assertTrue(r["duplicate_info"]["paid"])
        self.assertTrue(any("Billed before" in i["message"] for i in r["issues"]))
        # The money verdict is untouched — the duplicate's amounts still agree with MO.
        self.assertEqual(r["match_status"], STATUS_MATCHED)

    def test_a_later_cancellation_of_an_earlier_sale_is_not(self):
        # The real 607 5808675862: CONFIRMED on 08-15, CANCELLED on 16-22.
        cancel = row(1, ticket_status="CANCELLED", net_amount="-1082")
        r = reconcile([cancel], [], {}, commission_ran=False, prior_sales=self.PRIOR)[0]
        self.assertFalse(r["is_duplicate"])

    def test_the_same_serial_under_another_airline_is_not(self):
        prior = {_norm("5808758786"): {**self.PRIOR[_norm("5808758786")], "prefix": "075"}}
        r = reconcile([row(1)], [], {}, commission_ran=False, prior_sales=prior)[0]
        self.assertFalse(r["is_duplicate"])

    def test_two_sale_rows_in_one_statement_is_a_duplicate(self):
        r = reconcile([row(1), row(2)], [], {}, commission_ran=False)[0]
        self.assertTrue(r["is_duplicate"])
        self.assertEqual(r["duplicate_info"], {"kind": "within", "sale_rows": 2})

    def test_issue_and_cancellation_in_one_statement_is_not(self):
        rows_ = [row(1), row(2, ticket_status="CANCELLED", net_amount="-1082")]
        self.assertFalse(reconcile(rows_, [], {}, commission_ran=False)[0]["is_duplicate"])


class TestMoVendor(unittest.TestCase):
    """6C: a ticket missing from this vendor's MO file but present in another vendor's."""

    def test_found_in_another_vendors_mo_is_paired_and_flagged(self):
        other = mo_row(50, batch="moX", supplier_id=12, supplier_name="Riya Travels")
        out = reconcile([row(1)], [], {}, commission_ran=False, other_mo_rows=[other])
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual((r["match_method"], r["mo_vendor_status"]), ("other_vendor", "other_vendor"))
        self.assertEqual(r["mo_vendor_info"]["supplier_name"], "Riya Travels")
        self.assertEqual(r["match_status"], STATUS_MATCHED)          # figures still compared
        self.assertTrue(any("Riya Travels" in i["message"] for i in r["issues"]))

    def test_ambiguous_across_two_other_uploads_is_left_alone(self):
        others = [mo_row(50, batch="moX", supplier_id=12), mo_row(60, batch="moY", supplier_id=13)]
        r = reconcile([row(1)], [], {}, commission_ran=False, other_mo_rows=others)[0]
        self.assertEqual(r["match_status"], STATUS_VENDOR_ONLY)

    def test_a_corrected_ticket_reads_corrected(self):
        corrected = mo_row(9, batch="moX", vendor_status="corrected", corrected_from="Riya Travels")
        r = reconcile([row(1)], [corrected], {}, commission_ran=False)[0]
        self.assertEqual(r["mo_vendor_status"], "corrected")
        self.assertTrue(any("correction" in n for n in r["notes"]))

    def test_a_corrected_in_ticket_this_statement_does_not_bill_is_not_mo_only(self):
        # Corrected to this vendor while reconciling 16-22; reconciling 08-15 must not list
        # it as "in MO, not billed" — it belongs to the vendor, not to every statement.
        corrected = mo_row(10, ticket="5808758787", batch="moX", vendor_status="corrected",
                           corrected_from="Riya Travels")
        out = reconcile([row(1)], [mo_row(9), corrected], {}, commission_ran=False)
        self.assertEqual([r["match_status"] for r in out], [STATUS_MATCHED])
        own = reconcile([row(1)], [mo_row(9), mo_row(10, ticket="5808758787")], {},
                        commission_ran=False)
        self.assertIn(STATUS_MO_ONLY, [r["match_status"] for r in own],
                      "the chosen MO file's own unbilled ticket is still MO only")

    def test_a_normal_pair_carries_the_vendor_it_was_mapped_to(self):
        vendor = {"supplier_id": 751, "supplier_name": "Globe Air Travels", "supplier_code": "SUPP-0751"}
        r = reconcile([row(1)], [mo_row(9)], {}, commission_ran=False, vendor_supplier=vendor)[0]
        self.assertEqual(r["mo_vendor_status"], "ok")
        self.assertEqual(r["mo_vendor_info"]["supplier_code"], "SUPP-0751")


class TestBookingAndEnrichment(unittest.TestCase):

    def test_the_mo_booking_id_is_mapped_onto_the_ticket(self):
        r = reconcile([row(1)], [mo_row(9, booking_id="IS26/1067")], {}, commission_ran=False)[0]
        self.assertEqual(r["booking_id"], "IS26/1067")
        self.assertFalse(r["not_billed"])

    def test_no_booking_id_is_flagged_only_when_the_mo_carries_them(self):
        mo = [mo_row(9), mo_row(10, ticket="5808758787", booking_id="IS26/1")]
        out = reconcile([row(1)], mo, {}, commission_ran=False)
        self.assertTrue(one(out, STATUS_MATCHED)["not_billed"])
        r = reconcile([row(1)], [mo_row(9)], {}, commission_ran=False)[0]
        self.assertFalse(r["not_billed"])                # an MO file with no booking ids at all

    def test_another_uploads_booking_ids_say_nothing_about_this_one(self):
        # The pool can mix uploads (a ticket corrected in from another file). Only the file a
        # ticket came from decides whether its blank booking ID means "not billed".
        corrected = mo_row(10, ticket="5808758787", batch="moX", vendor_status="corrected",
                           booking_id="BK-1")
        out = reconcile([row(1), row(2, ticket="5808758787")], [mo_row(9), corrected], {},
                        commission_ran=False)
        by = {r["ticket_number"]: r for r in out}
        self.assertFalse(by[_norm("5808758786")]["not_billed"])
        self.assertEqual(by[_norm("5808758787")]["booking_id"], "BK-1")

    def test_class_the_vendor_does_not_print_comes_from_mo(self):
        r = reconcile([row(1)], [mo_row(9, booking_class="V", travel_date="2026-08-17")], {},
                      commission_ran=False)[0]
        self.assertEqual(r["enrichment"]["booking_class"], {"value": "V", "source": "mo"})
        self.assertEqual(r["enrichment"]["travel_date"], {"value": "2026-08-17", "source": "mo"})

    def test_a_disagreement_is_a_warning_not_an_override(self):
        r = reconcile([row(1, booking_class="Y")], [mo_row(9, booking_class="V")], {},
                      commission_ran=False)[0]
        self.assertIsNone(r["enrichment"])
        self.assertTrue(any("Class differs" in i["message"] for i in r["issues"]))

    def test_sectors_written_differently_agree(self):
        r = reconcile([row(1, sector="DEL/IST")], [mo_row(9, sector="del - ist")], {},
                      commission_ran=False)[0]
        self.assertFalse(any("Sector differs" in i["message"] for i in r["issues"]))

    def test_a_possible_match_maps_nothing(self):
        r = reconcile([row(1, prefix="075")], [mo_row(9, prefix="125", booking_id="X", booking_class="V")],
                      {}, commission_ran=False)[0]
        self.assertEqual(r["match_status"], STATUS_POSSIBLE)
        self.assertIsNone(r["booking_id"])
        self.assertIsNone(r["enrichment"])


# ── the real consolidator export ─────────────────────────────────────────────
@unittest.skipUnless(os.path.exists(REAL_STATEMENT), "real TRIUMPHH sample not on this machine")
class TestRealStatement(unittest.TestCase):
    """Parsed by the upload path itself, so this is the file exactly as it would load."""

    @classmethod
    def setUpClass(cls):
        from app.api.v1.statements import _detect_df
        from app.services import flat_statement

        content = open(REAL_STATEMENT, "rb").read()
        b = flat_statement.get("tp-gds")
        df = _detect_df(content, REAL_STATEMENT, lambda cols: len(b.build_col_map(cols)))
        cols = [str(c) for c in df.columns]
        built = [b.build_row(r, cols)["data"] for _, r in df.iterrows()]
        cls.rows = [(i + 1, d) for i, d in enumerate(d for d in built if d)]

    def test_the_file_loads_as_tickets_plus_one_closing_balance(self):
        tickets, lines = split_rows(self.rows)
        self.assertEqual(len(self.rows), 38)          # what the Statements screen shows
        self.assertEqual(len(tickets), 37)
        self.assertEqual([ln["kind"] for ln in lines], ["closing"])
        self.assertAlmostEqual(lines[0]["amount"], 960428.43, places=2)

    def test_the_same_file_on_both_sides_reconciles_exactly(self):
        tickets, lines = split_rows(self.rows)
        out = reconcile(tickets, [build_pay_row(i + 1000, d) for i, d in self.rows
                                  if balance_kind(d) is None], {}, commission_ran=False)
        t = tally(out)
        self.assertEqual(t["counts"][STATUS_MATCHED], len(out))
        self.assertEqual(t["net_variance"], 0.0)
        # OLD 627,257 + Σ net = BALANCE 960,428.43 — the statement's own identity, to the
        # paisa, because the opening is derived from unrounded figures.
        bal = balance_figures(lines, exact_net(tickets))
        self.assertEqual(bal["opening"], 627257.0)

    def test_an_edited_copy_shows_exactly_what_was_changed(self):
        tickets, _ = split_rows(self.rows)
        counts: dict[str, int] = {}
        for t in tickets:
            counts[t.ticket_key] = counts.get(t.ticket_key, 0) + 1
        single = [k for k, n in counts.items() if n == 1 and k]
        changed, dropped = single[0], single[1]

        mo = []
        for rid, d in self.rows:
            if balance_kind(d) is not None:
                continue
            pr = build_pay_row(rid + 1000, d)
            if pr.ticket_key == dropped:
                continue
            if pr.ticket_key == changed:
                d = {**d, "net_amount": str(D(d["net_amount"]) + 500)}
            mo.append(build_pay_row(rid + 1000, d))

        out = reconcile(tickets, mo, {}, commission_ran=False)
        self.assertEqual(one(out, STATUS_MISMATCH)["net_variance"], -500.0)
        self.assertEqual(_norm(one(out, STATUS_VENDOR_ONLY)["ticket_number"]), dropped)
        self.assertEqual(tally(out)["counts"][STATUS_MO_ONLY], 0)


if __name__ == "__main__":
    unittest.main()
