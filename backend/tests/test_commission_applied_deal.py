"""The popup behind the Matched deal chip (services/commission/applied_deal.py) — no DB.

It narrows the engine's trace to the one deal that applied, adds IATA on the BASIC FARE
only, sets the vendor's figure against the expected one, and says when the deal has changed
since the line was calculated.

Run:  python -m unittest discover backend/tests
"""

import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.commission import applied_deal as ad  # noqa: E402


def step(name, passed=True, ticket="x", deal="x"):
    return NS(step=name, passed=passed, ticket_value=ticket, deal_value=deal, detail=f"{name} detail")


def plb(key, applied=True, result=700.0):
    return NS(plb_key=key, plb_overall_match=applied, steps=[step("Flight Type"), step("Booking Class", ticket="not printed")],
              incentive_breakdown={"targetCalcCols": "Basic + YQ", "sell_fare": 10000.0,
                                   "sell_tax_yq_added": True, "sell_tax_yq_value": 4000.0,
                                   "sale_yr_added": False, "sale_yr_value": 500.0,
                                   "base_total": 14000.0, "incentiveAmtPct": "5", "incentive_num_pct": "Percentage",
                                   "formula": "14000.0 × 5% = 700.0", "result": result})


def calc(**kw):
    base = dict(id=1, status="calculated", reason=None, incentive=700.0, iata_commission=300.0,
                fare_amount=10000.0, yq=4000.0, yr=500.0, incentive_breakdown={"PLB": 700.0},
                matched_deal_no="B2B-000007", supplier_match_by="id", ticket_number="123", pnr="ABC",
                passenger_name="DOE/J", airline_name="LUFTHANSA", issue_date=date(2026, 10, 7),
                travel_date=date(2026, 10, 11), segment_type="INT", booking_class="C", sector="BOM/FRA",
                transaction_type="Sales")
    base.update(kw)
    return NS(**base)


DEAL = NS(id=7, supplier_name="Brightsun", airline_name="LUFTHANSA", valid_from=date(2026, 10, 1),
          valid_to=date(2026, 10, 7), iata_commission="3")
DIAG = NS(deal_id=7, deal_validity_step=step("Deal Validity"), plbs=[plb("PLB"), plb("Super PLB", applied=False, result=0)],
          inclusion_diagnostic=None,
          exclusion_diagnostic=NS(is_excluded=False, reason="not excluded",
                                  steps=[NS(field="Origin Country", rule_value="USA", ticket_value="India", matched=False)]))


class TestAppliedDeal(unittest.TestCase):
    def setUp(self):
        self.out = ad.build(calc(), DEAL, DIAG, statement=800.0)

    def test_iata_is_the_deals_percent_on_the_basic_fare_only(self):
        iata = self.out["iata"]
        self.assertEqual((iata["pct"], iata["basic_fare"], iata["amount"]), (3.0, 10000.0, 300.0))
        self.assertEqual(iata["formula"], "10,000.00 × 3% = 300.00")       # not on Basic + YQ

    def test_expected_against_the_statement(self):
        self.assertEqual((self.out["expected"], self.out["statement"], self.out["difference"]),
                         (1000.0, 800.0, 200.0))

    def test_only_the_configs_that_applied(self):
        self.assertEqual([i["incentive_type"] for i in self.out["incentives"]], ["PLB"])
        inc = self.out["incentives"][0]
        self.assertEqual((inc["calc_on"], inc["basic"], inc["yq"], inc["yr"], inc["base"], inc["amount"], inc["stored"]),
                         ("Basic + YQ", 10000.0, 4000.0, None, 14000.0, 700.0, 700.0))

    def test_criteria_and_rules(self):
        steps = [(c["group"], c["step"]) for c in self.out["criteria"]]
        self.assertEqual(steps[:2], [("Deal", "Airline"), ("Deal", "Deal Validity")])
        self.assertIn(("PLB", "Flight Type"), steps)
        self.assertTrue(next(c for c in self.out["criteria"] if c["step"] == "Booking Class")["skipped"])
        self.assertEqual(self.out["rules"][0]["kind"], "Exclusion")
        self.assertTrue(self.out["rules"][0]["passed"])
        self.assertFalse(self.out["stale"])

    def test_a_deal_changed_since_the_run_is_flagged(self):
        out = ad.build(calc(incentive=650.0), DEAL, DIAG, statement=None)
        self.assertTrue(out["stale"])
        self.assertIsNone(out["difference"])

    def test_no_iata_percent_no_iata(self):
        out = ad.build(calc(iata_commission=0), NS(**{**vars(DEAL), "iata_commission": None}), DIAG, 0.0)
        self.assertEqual((out["iata"]["pct"], out["iata"]["formula"], out["iata"]["amount"]), (None, None, 0.0))

    def test_without_a_trace_the_figures_still_show(self):
        out = ad.build(calc(), DEAL, None, 800.0)
        self.assertFalse(out["traced"])
        self.assertEqual([c["step"] for c in out["criteria"]], ["Airline"])
        self.assertEqual(out["expected"], 1000.0)


if __name__ == "__main__":
    unittest.main()
