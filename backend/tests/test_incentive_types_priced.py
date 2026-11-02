"""One deal carrying every incentive type, through the real engine and the real runner — no DB.

Commission income shows a column per incentive type and an Expected that is their total, so
this pins what that total is made of: each type is built from what the deal form saves
(deals._build_inc_config) and priced by DealMatchingService.find_all_deals, then
CommissionRunner.calculate_row.

Run:  python -m unittest discover backend/tests
"""

import asyncio
import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.v1.deals import _build_inc_config  # noqa: E402
from app.api.v1.tickets import INCENTIVE_TYPE_KEYS  # noqa: E402
from app.models.deal import DealKind  # noqa: E402
from app.services.commission.calc_row import CalcRow  # noqa: E402
from app.services.commission.runner import CommissionRunner  # noqa: E402
from app.services.deal_matching import SKIP_CLASS, DealMatchingService  # noqa: E402

# The standard shape: the deal form's fields for PLB, and for each type that copies it.
STANDARD = {
    "validFrom": "2026-10-01", "validTo": "2027-03-31", "flightType": "Both", "class": "All",
    "targetCalcCols": "Basic", "payoutCalcCols": "Basic", "targetBased": "Amount Based",
    "amountBasedType": "Fixed", "incentiveNumPct": "Percentage", "incentiveAmtPct": "2",
    "gstMode": "exclusive",
}
STANDARD_TYPES = ["PLB", "Super PLB", "Transaction Fee", "Marketing Fund", "Frontend",
                  "Backend", "Push Action", "NDC"]

# The other shapes, as their tabs on the form save them.
ANCILLARY = {"baggageType": "With Baggage", "baggageNumPct": "Percentage", "baggageAmt": "10",
             "baggageAmtGst": "exclusive"}
DEPOSIT = {"diType": "Bulk Deposit", "bulkDepositType": "Single Deposit",
           "depositAmount": "100000", "bulkSingleNumPct": "Percentage", "bulkSingleAmt": "1"}
CASHBACK = {"cashbackPeriodFrom": "2026-10-01", "cashbackPeriodTo": "2027-03-31",
            "cashbackTargetType": "Percentage", "cashbackTargetValue": "1"}
SEGMENT = {"siPeriodFrom": "2026-10-01", "siPeriodTo": "2027-03-31", "siTargetType": "Amount",
           "siTargetValue": "100", "siClass": "All", "siFlightType": "All",
           "siSlabs": [{"numberOfSegments": "10", "targetFrom": "0", "targetTo": "100",
                        "domEconomy": "50", "intlEconomy": "50"}]}

PAYLOAD = {**{t: STANDARD for t in STANDARD_TYPES}, "Ancillary": ANCILLARY,
           "Deposit Incentive (DI)": DEPOSIT, "Cashback": CASHBACK, "Segment Incentive": SEGMENT}

FARE, BAGGAGE = 10000.0, 500.0


class FakeResult:
    def __init__(self, deals):
        self.deals = deals

    def scalars(self):
        return SimpleNamespace(all=lambda: self.deals)


class FakeDb:
    """The one query the engine sends here is the deal search, which returns `deals`. Rules are
    read through per-session caches — prefilled empty, so nothing else reaches the database."""
    def __init__(self, deals):
        self.deals = deals
        ids = [c.id for d in deals for c in d.incentives]
        self.info = {"_trigger_rule_cache": dict.fromkeys(ids),
                     "_payout_rule_cache": {d.id: [] for d in deals}}

    async def execute(self, _stmt):
        return FakeResult(self.deals)


def deal_with(*types):
    configs = []
    for i, t in enumerate(types):
        config = _build_inc_config(7, t, PAYLOAD[t], i)
        config.id = 100 + i
        configs.append(config)
    return SimpleNamespace(
        id=7, deal_type=DealKind.B2B, airline_name="AIR ASTANA", contract_year=None,
        valid_from=date(2026, 10, 1), valid_to=date(2027, 3, 31), deal_maker_name=None,
        iata_commission="3", incentives=configs)


def price(*types):
    return asyncio.run(DealMatchingService.find_all_deals(
        db=FakeDb([deal_with(*types)]), airline_name="AIR ASTANA", travel_date=date(2026, 10, 5),
        tenant_id=1, created_by_id=1, issue_date=date(2026, 10, 1), segment_type="International",
        sell_fare=FARE, sell_tax_yq=0.0, sale_yr=0.0, excess_baggage=BAGGAGE,
        statement_type="B2B", skip_criteria={SKIP_CLASS}))


class TestEveryTypeOnOneDeal(unittest.TestCase):
    def test_the_lists_cover_every_type(self):
        self.assertEqual(set(PAYLOAD), set(INCENTIVE_TYPE_KEYS))

    def test_each_standard_type_is_priced_on_the_fare(self):
        for t in STANDARD_TYPES:
            with self.subTest(t):
                self.assertEqual(price(t)[0].incentive_breakdown, {t: 200.0})

    def test_ancillary_is_priced_on_its_fee_not_the_fare(self):
        self.assertEqual(price("Ancillary")[0].incentive_breakdown, {"Ancillary": 50.0})

    def test_the_deal_total_is_every_type_added_up(self):
        m = price(*STANDARD_TYPES, "Ancillary")[0]
        self.assertEqual(len(m.incentive_breakdown), 9)
        self.assertEqual(m.calculated_incentive, 8 * 200.0 + 50.0)


class TestTypesWithNoPerTicketAmount(unittest.TestCase):
    """These three save, but pay nothing on a ticket: the form records a deposit, or a period
    target, and no rate the engine can apply to one fare. The Commission income columns say so
    (lib/incentives.ts NOT_PRICED_PER_TICKET). When they get rules, this test is the one to
    change — along with that list."""

    def test_they_add_nothing_beside_a_type_that_pays(self):
        for t in ("Deposit Incentive (DI)", "Cashback", "Segment Incentive"):
            with self.subTest(t):
                self.assertEqual(price("PLB", t)[0].incentive_breakdown, {"PLB": 200.0})

    def test_a_deal_with_only_those_finds_no_match(self):
        for t in ("Deposit Incentive (DI)", "Cashback", "Segment Incentive"):
            with self.subTest(t):
                self.assertEqual(price(t), [])


class TestTheRunner(unittest.TestCase):
    def test_a_calculated_line_stores_each_type_and_their_total(self):
        d = deal_with("PLB", "Super PLB", "NDC")
        row = CalcRow(source_row_id=1, airline_name="AIR ASTANA", issue_date=date(2026, 10, 1),
                      travel_date=date(2026, 10, 5), fare_amount=FARE, yq=0.0, yr=0.0,
                      segment_type="International", statement_type="B2B",
                      skip_criteria={SKIP_CLASS})
        runner = CommissionRunner(adapter=object())
        with mock.patch("app.services.commission.runner.load_facts",
                        new=mock.AsyncMock(return_value=None)):
            res = asyncio.run(runner.calculate_row(FakeDb([d]), row, 1, 1))
        self.assertEqual(res.status, "calculated")
        self.assertEqual(res.breakdown, {"PLB": 200.0, "Super PLB": 200.0, "NDC": 200.0})
        self.assertEqual(res.incentive, 600.0)
        self.assertEqual(res.iata_commission, 300.0)       # 3% of the fare, beside the incentive


if __name__ == "__main__":
    unittest.main()
