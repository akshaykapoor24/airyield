"""Wire shapes for buy-vs-sell reconciliation.

A deliberate SUPERSET of `schemas/ticket_reconciliation.py`, exactly as
`schemas/commission.py` is a superset of `schemas/bsp_commission.py`: one frontend
component serves every source tab, so the two routers must agree on the keys they share
and differ only by adding. What is added here is the buy/sell vocabulary and `margin`;
what is dropped is BSP's `txn_type`, `commission_source` and `related_bsp`, none of which
exist outside a settlement file.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.uploaded_ticket import UploadedTicketRead


# ── request ──────────────────────────────────────────────────────────────────
class RunSellReconciliationPayload(BaseModel):
    # None = every batch of this source, which is the normal case: the screen is a flat
    # list across statements, so narrowing to one is the exception.
    batch_id: Optional[str] = None


# ── run result ───────────────────────────────────────────────────────────────
class SellReconciliationRunResult(BaseModel):
    run_id: int
    reconciled_at: datetime
    total: int
    matched: int
    minor_diff: int
    mismatch: int
    buy_only: int
    sell_only: int
    possible_match: int
    total_buy: float
    total_sell: float
    total_margin: float


# ── read ─────────────────────────────────────────────────────────────────────
class SellReconciliationSummary(BaseModel):
    total: int
    matched: int
    minor_diff: int
    mismatch: int
    buy_only: int
    sell_only: int
    possible_match: int
    # Summed over rows that actually pair the two sides. A buy_only has no sale to compare
    # and a possible_match is explicitly not reconciled, so folding either in would make
    # the tiles disagree with the grid.
    total_buy: float
    total_sell: float
    total_margin: float
    last_run_at: Optional[datetime] = None


class BuySellFieldDiff(BaseModel):
    key: str
    label: str
    buy: Optional[float] = None
    sell: Optional[float] = None
    variance: Optional[float] = None
    match: Optional[bool] = None
    severity: Optional[str] = None


class SellReconciliationIssue(BaseModel):
    field: Optional[str] = None
    label: Optional[str] = None
    severity: str
    message: str
    buy: Optional[float] = None
    sell: Optional[float] = None
    variance: Optional[float] = None


class SellReconciliationRowRead(BaseModel):
    id: int
    source: str
    batch_id: Optional[str] = None
    source_row_id: Optional[int] = None
    ticket_id: Optional[int] = None
    ticket_number: Optional[str] = None
    ticket_prefix: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    issue_date: Optional[date] = None
    sector: Optional[str] = None
    pax_name: Optional[str] = None
    match_status: str
    severity: str
    match_method: str = "none"
    buy_net: Optional[float] = None
    sell_net: Optional[float] = None
    margin: Optional[float] = None
    abs_margin: Optional[float] = None
    # How many rows each side summed — a figure built from several rows needs to say so.
    sell_legs: int = 0
    buy_rows: int = 0
    issue_count: int = 0

    model_config = {"from_attributes": True}


class SellReconciliationDetail(SellReconciliationRowRead):
    reconciled_at: Optional[datetime] = None
    remarks: Optional[str] = None
    fields: list[BuySellFieldDiff] = []
    issues: list[SellReconciliationIssue] = []
    notes: list[str] = []
    # The full records behind the two columns, for the side-by-side popup.
    buy_row: Optional[dict] = None
    ticket: Optional[UploadedTicketRead] = None


class SellReconciliationPage(BaseModel):
    summary: SellReconciliationSummary
    total: int
    offset: int
    limit: int
    rows: list[SellReconciliationRowRead] = []


class SellReconciliationFacets(BaseModel):
    airlines: list[str] = []
    batches: list[dict] = []
    statuses: list[str] = []
