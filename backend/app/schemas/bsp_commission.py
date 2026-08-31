from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class BspCommissionStatementRead(BaseModel):
    """One BSP detailed statement in the Commission income picker."""
    batch_id:        str
    statement_name:  Optional[str] = None
    airline_code:    Optional[str] = None
    airline_name:    Optional[str] = None
    period_from:     Optional[date] = None
    period_to:       Optional[date] = None
    row_count:       int = 0
    parse_status:    str = "pending"          # the PDF parse; rows only exist once completed

    status:          str = "idle"             # idle|queued|processing|completed|failed
    total_rows:      int = 0
    processed_rows:  int = 0
    progress_pct:    int = 0
    error:           Optional[str] = None
    heartbeat_at:    Optional[datetime] = None
    is_stale:        bool = False          # queued/processing but its worker went quiet
    calculated_at:   Optional[datetime] = None

    total_incentive: Optional[float] = None
    iata_total:      Optional[float] = None
    matched_rows:    int = 0
    unmatched_rows:  int = 0
    excluded_rows:   int = 0
    skipped_rows:    int = 0
    # A deal matched but pays only on a criterion this statement does not print
    # (cabin class, travel window, route) — the amount is withheld, not zero.
    needs_data_rows: int = 0
    # Rows no run has touched. Without this a never-run statement is
    # indistinguishable from a fully-run one that matched almost nothing.
    pending_rows:    int = 0
    enriched_rows:   int = 0   # rows where TGQ actually recovered a field
    # A TGQ HMPR statement has been uploaded since this was last calculated.
    # Enrichment only ever runs inside a commission run, so new TGQ data changes
    # nothing at all until the statement is re-run — silently, without this flag.
    tgq_stale:       bool = False

    created_at:      datetime


class BspCommissionRunResponse(BaseModel):
    """Result of POST /run.

    mode="queued" → the whole statement went to the worker; poll the statement.
    mode="inline" → a hand-picked selection was calculated in the request and the
    counts below are final.
    """
    batch_id: str
    status:   str
    mode:     str = "queued"          # queued | inline

    processed:  int = 0
    calculated: int = 0
    reversed:   int = 0
    excluded:   int = 0
    skipped:    int = 0
    unmatched:  int = 0
    errors:     int = 0
    total_incentive: float = 0.0


class BspCommissionRowRead(BaseModel):
    id:                int
    document_number:   Optional[str] = None
    ticket_number:     Optional[str] = None
    transaction_type:  Optional[str] = None
    airline_code:      Optional[str] = None
    airline_accounting_code: Optional[str] = None
    airline_name:      Optional[str] = None
    issue_date:        Optional[date] = None
    stat:              Optional[str] = None
    form_of_payment:   Optional[str] = None

    fare_amount:       Optional[float] = None
    yq:                Optional[float] = None
    yr:                Optional[float] = None
    transaction_amount: Optional[float] = None
    standard_commission_amount: Optional[float] = None

    matched_deal_id:      Optional[int] = None
    matched_deal_type:    Optional[str] = None
    matched_deal_name:    Optional[str] = None
    calculated_incentive: Optional[float] = None
    iata_commission:      Optional[float] = None
    incentive_breakdown:  Optional[dict] = None
    commission_status:    str = "pending"
    commission_reason:    Optional[str] = None
    skipped_criteria:     Optional[list[str]] = None
    # From the TGQ HMPR counterpart — what the class/sector/travel-date match used.
    enriched_sector:             Optional[str] = None
    enriched_booking_class:      Optional[str] = None
    enriched_travel_date:        Optional[date] = None
    enriched_travel_date_source: Optional[str] = None
    enriched_leg_count:          Optional[int] = None
    enrichment_source:           Optional[str] = None


class BspCommissionRowsPage(BaseModel):
    total:  int
    offset: int
    limit:  int
    rows:   list[BspCommissionRowRead] = []


class BspCommissionAirlineSummary(BaseModel):
    airline:         str
    rows:            int
    incentives:      dict           # {incentive_type: amount}
    total_incentive: float
    iata_commission: float


class BspCommissionTotals(BaseModel):
    incentives:      dict
    total_incentive: float
    iata_commission: float


class BspCommissionSummary(BaseModel):
    airlines: list[BspCommissionAirlineSummary] = []
    totals:   BspCommissionTotals


class BspCommissionReasonGroup(BaseModel):
    """One bucket of the Unmatched / Skipped tab."""
    status: str
    reason: str
    count:  int
    sample_documents: list[str] = []
