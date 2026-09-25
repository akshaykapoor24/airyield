"""Response shapes for the Sales vs Flown board.

A sale is counted on the day it is ISSUED; it earns a flown-based incentive (PLB) only
on the day it FLIES. This board is the bridge between the two: every sale month, and
how much of it has flown in each later month — the cohort grid finance keeps in Excel.

`None` is not 0 here either. `deflator_pct` is None when no flown line printed a fare
breakdown, which means "cannot say what share is commissionable", not "none of it is".
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class FlownTotals(BaseModel):
    # Everything below is over the SALE window (issue date), same predicate as the
    # Total Revenue board's sale — so the two boards' sale figures agree.
    sold: float | None
    rows: int
    # travel_date <= as_of
    flown: float | None
    # travel_date > as_of: sold, not yet flown, so not yet earning a flown incentive.
    unflown: float | None
    # No readable travel date. Neither flown nor unflown — it cannot be placed.
    no_travel_date: float | None
    no_travel_date_rows: int
    # Refund lines inside `sold`, already signed negative.
    refunds: float | None
    # The observed commissionable share of flown gross, Basic fare only.
    # None when no flown line carries a fare breakdown.
    deflator_pct: float | None
    deflator_coverage_pct: float | None


class CohortCell(BaseModel):
    flown_ym: str | None    # None = no travel date
    amount: float
    rows: int


class CohortRow(BaseModel):
    sale_ym: str
    label: str
    sold: float
    flown: float
    unflown: float
    no_travel_date: float
    rows: int
    cells: list[CohortCell]


class FlownMonthPoint(BaseModel):
    """What flew in a travel month, whatever month it was sold in."""
    ym: str
    label: str
    flown: float
    rows: int
    future: bool


class FlownAirlinePoint(BaseModel):
    airline_id: int | None
    airline: str
    sold: float | None
    flown: float | None
    unflown: float | None
    no_travel_date: float | None
    flown_pct: float
    deflator_pct: float | None
    rows: int


class SlabBand(BaseModel):
    threshold: float
    rate_pct: float | None


class PlbDealLine(BaseModel):
    """One PLB deal line for the selected airline, measured against flown revenue."""
    deal_id: int
    deal_no: str
    entity: str | None
    channel: str
    segment: str            # Domestic | International | Both
    period_start: date | None
    period_end: date | None
    basis_label: str
    target_based: str       # Fixed | Slab
    bands: list[SlabBand]
    # Flown inside the deal's PLB period, up to as_of, on the deal's segment.
    flown: float
    deflator_pct: float | None
    # flown × deflator: the commissionable base the slab is measured on.
    achieved: float | None
    rate_pct: float
    rate_explain: str
    payout: float | None
    next_band: SlabBand | None
    gap_to_next: float | None
    achieved_pct_of_next: float | None


class SalesFlownResponse(BaseModel):
    scope: str
    currency: str | None
    as_of: date
    date_from: str | None
    date_to: str | None
    totals: FlownTotals
    cohorts: list[CohortRow]
    flown_months: list[str]
    flown_by_month: list[FlownMonthPoint]
    by_airline: list[FlownAirlinePoint]
    plb_lines: list[PlbDealLine]
    # Set when exactly one airline is selected — the PLB panel needs one carrier.
    plb_airline: str | None
    other_currencies: dict[str, int]
