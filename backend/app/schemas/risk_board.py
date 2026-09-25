"""Response shapes for the Risk analysis board.

Every factor is a ratio of an amount to the sale it sits on (net sale for unflown,
issued sale for the rest), and every threshold that
turns a ratio into a level is sent WITH the response. The page prints them, so a reader
can see why an airline is flagged rather than trusting a colour.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class RiskFactorDef(BaseModel):
    key: str
    label: str
    explain: str
    medium: float     # ratio in % at which the factor turns medium
    high: float       # ... and high


class RiskTotals(BaseModel):
    sold: float | None                    # net: issues less refunds
    issued: float | None                  # issues only — the status factors' base
    rows: int
    unflown: float | None
    no_travel_date: float | None
    refunds: float | None                 # signed negative, as the sale carries it
    unmatched_sale: float | None          # a deal ran and none matched — no incentive
    needs_data_sale: float | None         # matched, but cannot be confirmed
    unpriced_sale: float | None           # commission never run
    incentive: float | None               # claimable, counted
    slab_dependent_incentive: float | None
    adm_exposure: float | None            # |debit memos|
    adm_count: int
    acm_credit: float | None
    under_recovery: float | None          # vendor declared less than computed
    declared_mismatch_rows: int
    top_airline: str | None
    top_airline_share_pct: float
    top3_share_pct: float
    hhi: float                            # 0–10,000


class AgingBucket(BaseModel):
    key: str
    label: str
    amount: float
    rows: int


class RiskAirlineRow(BaseModel):
    airline_id: int | None
    airline: str
    sold: float | None
    share_pct: float
    rows: int
    # Each factor as % of this airline's sale.
    factors: dict[str, float]
    levels: dict[str, str]                # key -> low | medium | high
    level: str                            # worst of the above
    score: int                            # 2 per high, 1 per medium — the sort key
    unflown: float | None
    incentive: float | None
    slab_dependent_incentive: float | None
    adm_exposure: float | None


class RiskSummaryResponse(BaseModel):
    scope: str
    currency: str | None
    as_of: date
    date_from: str | None
    date_to: str | None
    factors: list[RiskFactorDef]
    totals: RiskTotals
    overall_levels: dict[str, str]
    overall_factors: dict[str, float]
    concentration_level: str
    unflown_aging: list[AgingBucket]
    by_airline: list[RiskAirlineRow]
    level_counts: dict[str, int]
    other_currencies: dict[str, int]
