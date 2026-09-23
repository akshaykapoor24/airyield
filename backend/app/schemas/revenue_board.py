"""Response shapes for the revenue board — what the loaded statements SOLD.

Every money field that can be NULL is typed `float | None`, and that is deliberate
rather than defensive, for the reason schemas/income_board.py gives: `incentive` is NULL
when a deal matched but pays on something the statement does not print, so nothing is
claimed, and a board that renders that as 0 has told the reader "you are owed nothing"
when the truth is "we could not confirm what you are owed".

THIS BOARD ADDS A THIRD STATE and it needs the same care. `unpriced_rows` counts lines
that carry sale and have never been through the commission engine. Their incentive is
also NULL, but for a reason that has nothing to do with the deal — the remedy is to
press Run, not to find a missing column — so the two are counted separately and shown
separately, never added.

AND A FOURTH FIGURE THAT IS NOT REVENUE. `not_counted_sale` is the value of the lines
this board deliberately leaves out of the total: a cancelled aggregator booking, an LCC
payment movement, an NDC ticket already settled through BSP, a statement's own footer
line. It is reported so that "the total is smaller than my statement's total" has an
answer on screen, and it is never added to `sale`.
"""
from __future__ import annotations

from pydantic import BaseModel


class RevenueTotals(BaseModel):
    """The KPI band."""
    # Gross as printed, signed, over the lines that count. Never the sum of every
    # statement: twelve types cover six businesses, and adding them all roughly
    # double-counts the BSP and LCC families.
    sale: float | None
    sale_rows: int
    # What those lines earned. NULL-safe by construction — see measures.incentive_sum.
    incentive: float | None
    # A separate entitlement, never folded into the incentive. The separation is
    # deliberate in services/commission/runner.py and models/bsp_statement.py.
    iata_commission: float | None

    # The honesty counters that must travel with the money.
    unpriced_rows: int
    needs_data_rows: int
    unmatched_rows: int
    # Lines whose carrier could not be resolved. Excludes Third Party API, which has no
    # carrier BY NATURE rather than by failure — see `not_carrier_attributed_rows`.
    unattributed_airline_rows: int
    not_carrier_attributed_rows: int
    # A date the vendor printed that no pattern could read. The row is real and its sale
    # counts; it simply has no month, and a blank month bucket must not read as no sales.
    undated_rows: int

    # Deliberately out of `sale`, and reported so the difference has an explanation.
    not_counted_rows: int
    not_counted_sale: float | None


class SourcePoint(BaseModel):
    """One statement type: BSP, NDC, LCC Detailed, or one of the three third-party ones."""
    source: str
    category: str          # BSP | LCC | Third Party
    label: str
    sale: float | None
    rows: int
    incentive: float | None
    priced_rows: int
    unpriced_rows: int
    not_counted_rows: int
    share_pct: float


class CategoryPoint(BaseModel):
    """BSP / LCC / Third Party, folded from `by_source` rather than grouped again."""
    category: str
    sale: float | None
    rows: int
    incentive: float | None
    share_pct: float
    sources: list[str]


class MonthPoint(BaseModel):
    ym: str
    label: str
    sale: float | None
    incentive: float | None
    rows: int
    #: source -> sale, for the stacked column. Absent keys are zero months, not gaps.
    by_source: dict[str, float]


class AirlineRevenuePoint(BaseModel):
    """One carrier, across every statement type it appears in.

    `airline_id` NULL is the unattributed bucket. `by_source` is what makes the row
    answer the question the board exists for — the same carrier's BSP, NDC and
    consolidator business side by side instead of on three screens.
    """
    airline_id: int | None
    airline: str
    sale: float | None
    incentive: float | None
    rows: int
    share_pct: float
    by_source: dict[str, float]
    by_incentive_type: dict[str, float]


class SupplierPoint(BaseModel):
    supplier_id: int | None
    supplier: str
    supplier_code: str | None
    branch: str | None
    sale: float | None
    incentive: float | None
    rows: int
    share_pct: float


class ProductPoint(BaseModel):
    """Third Party API only — the one multi-product source.

    An aggregator file carries hotel, flight, train, bus and car bookings side by side,
    and only the flight rows have a carrier at all. Reporting this source by product
    rather than by airline is what keeps a hotel night out of an airline's total.
    """
    product: str | None
    sale: float | None
    rows: int
    share_pct: float


class IncentiveTypePoint(BaseModel):
    """PLB, Super PLB, Transaction Fee, and the eight others.

    Read out of `incentive_breakdown` rather than from a fixed column list, so an
    incentive type added to a deal shows up without a code change — `incentive_type` is
    a String on `deal_incentives`, and the canonical eleven in api/v1/tickets.py are a
    convention, not a constraint.
    """
    incentive_type: str
    amount: float | None
    rows: int
    share_pct: float


class NotCountedPoint(BaseModel):
    """One reason a line was held out of the sale total, with what it was worth.

    The wording is `report_download/columns.py`'s own NET_* vocabulary, not a phrasing
    invented here, so the answer to "why is this smaller than my statement's total" is
    the same sentence on this board and in the downloadable workbook.
    """
    reason: str
    rows: int
    amount: float | None
    sources: list[str]


class RevenueSummaryResponse(BaseModel):
    scope: str
    basis: str
    currency: str | None
    date_from: str | None
    date_to: str | None
    totals: RevenueTotals
    by_category: list[CategoryPoint]
    by_source: list[SourcePoint]
    by_month: list[MonthPoint]
    by_airline: list[AirlineRevenuePoint]
    by_supplier: list[SupplierPoint]
    by_product: list[ProductPoint]
    #: Why the board's total is smaller than the sum of the statements, line by reason.
    not_counted: list[NotCountedPoint]
    #: Currencies present in scope beyond the one selected, with their row counts.
    #: Totals are never converted or added across currencies, so the board scopes to one
    #: and says what it left out rather than silently dropping it.
    other_currencies: dict[str, int]


class AirlineDetailResponse(BaseModel):
    """One carrier's whole picture — the drill-down behind a row of the matrix."""
    airline_id: int | None
    airline: str
    totals: RevenueTotals
    by_source: list[SourcePoint]
    by_month: list[MonthPoint]
    by_incentive_type: list[IncentiveTypePoint]
    #: The statements that restate this carrier's business rather than adding to it —
    #: TGQ HMPR, the memos, the LCC ledgers. Counts and their own measures, never summed
    #: into sale.
    linked: list[LinkedStatementPoint]


class LinkedStatementPoint(BaseModel):
    source: str
    label: str
    category: str
    rows: int
    #: The measure that type is actually about: ADM exposure, flown revenue, deposits.
    #: Named rather than called "sale", because it is not sale.
    measure_label: str
    measure: float | None
    #: True where the statement's layout was built without a real sample
    #: (`registry.schema_unverified`), so the figure carries that caveat on screen.
    schema_unverified: bool


class RevenueFilterOptions(BaseModel):
    airlines: list[dict]
    suppliers: list[dict]
    sources: list[str]
    categories: list[str]
    months: list[str]
    currencies: list[str]
    incentive_types: list[str]
    can_view_agency: bool
    default_scope: str


AirlineDetailResponse.model_rebuild()
