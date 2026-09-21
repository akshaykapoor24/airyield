"""Response shapes for the income board.

Every money field that can be NULL is typed `float | None`, and that is deliberate
rather than defensive. `incentive` is NULL when a deal matched but pays on something
the statement does not print, so nothing is claimed — and a board that renders that as
0 has told the reader "you are owed nothing" when the truth is "we could not confirm
what you are owed". The type carries the distinction all the way to the screen, where
`lib/incomeBoard.ts` mirrors it and the tile renders an em dash with the affected row
count beside it.
"""
from __future__ import annotations

from pydantic import BaseModel


class IncomeTotals(BaseModel):
    """The KPI band."""
    # What the airlines and consolidators owe us, over claimable rows only.
    vendor_income: float | None
    # Kept apart from the incentive everywhere in this codebase. Never add the two.
    iata_commission: float | None
    # Sales and refunds only — never memos, which carry no fare.
    gross_revenue: float | None
    # Phase 2. Present now so the shape does not change under the frontend later.
    commission_paid: float | None
    markup_income: float | None
    spread: float | None
    # The honesty counters that must travel with the money.
    rows: int
    needs_data_rows: int
    unmatched_rows: int
    unattributed_airline_rows: int
    unattributed_supplier_rows: int
    # ADM is money going out; ACM is money coming back. Never netted together.
    debit_memo_amount: float | None
    credit_memo_amount: float | None
    slab_dependent_rows: int


class AirlinePoint(BaseModel):
    airline_id: int | None
    airline: str
    incentive: float | None
    iata_commission: float | None
    gross: float | None
    rows: int
    needs_data_rows: int
    share_pct: float
    cumulative_pct: float


class SupplierPoint(BaseModel):
    supplier_id: int | None
    supplier: str
    # A branch, not a company: supplier names repeat across branches that bill
    # separately, so the label carries the code and the grouping is on the id.
    supplier_code: str | None
    branch: str | None
    incentive: float | None
    iata_commission: float | None
    gross: float | None
    rows: int
    needs_data_rows: int
    share_pct: float
    cumulative_pct: float
    # 'id' | 'name' | 'unrestricted'. A name match cannot tell two branches apart.
    match_quality: str | None


class MonthPoint(BaseModel):
    ym: str
    label: str
    incentive: float | None
    gross: float | None
    rows: int
    # True when any line in the bucket pays on a slab, so the figure may restate.
    has_slab_dependent: bool


class SourcePoint(BaseModel):
    source: str
    label: str
    incentive: float | None
    rows: int
    needs_data_rows: int


class IncomeSummaryResponse(BaseModel):
    scope: str
    basis: str
    date_from: str | None
    date_to: str | None
    totals: IncomeTotals
    by_month: list[MonthPoint]
    by_airline: list[AirlinePoint]
    by_supplier: list[SupplierPoint]
    by_source: list[SourcePoint]


class FilterOptions(BaseModel):
    airlines: list[dict]
    suppliers: list[dict]
    sources: list[str]
    months: list[str]
    can_view_agency: bool


class SourceFreshness(BaseModel):
    source: str
    batches: int
    projected: int
    stale: int
    never: int
    last_projected_at: str | None


class FreshnessResponse(BaseModel):
    """Whether the board is telling the truth about the statements that exist.

    A wrong income board is worse than no income board, so this is rendered as a
    blocking banner rather than a quiet footnote. `stale` counts batches whose
    commission run finished after the last projection; `never` counts priced batches
    with no projected rows at all — which is every existing batch on day one, because
    the migration deliberately ships the table empty.
    """
    by_source: list[SourceFreshness]
    stale_total: int
    never_total: int
    ok: bool
