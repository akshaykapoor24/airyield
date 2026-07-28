from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel

from app.schemas.bsp_statement import BspStatementRowRead
from app.schemas.uploaded_ticket import UploadedTicketRead


# Allowed values (validated in the API / engine).
RECON_STATUSES = {"matched", "minor_diff", "mismatch", "missing_bsp", "extra_bsp", "possible_match"}
TXN_TYPES = {"TKTT", "ADM", "ACM", "RA", "RFND", "EMD", "EXCH"}


# ── request ──────────────────────────────────────────────────────────────────
class RunReconciliationPayload(BaseModel):
    statement_id:      Optional[str]  = None   # scope to one BSP statement; None = all the user's BSP rows
    date_from:         Optional[date] = None   # filter BSP rows by issue_date
    date_to:           Optional[date] = None
    commission_source: Literal["reported", "iata"] = "reported"


# ── run result ───────────────────────────────────────────────────────────────
class ReconciliationRunResult(BaseModel):
    run_id:             str
    reconciled_at:      datetime
    total:              int
    matched:            int
    minor_diff:         int
    mismatch:           int
    missing_bsp:        int
    extra_bsp:          int
    possible_match:     int
    total_abs_variance: float


# ── read (list + detail) ─────────────────────────────────────────────────────
class ReconciliationSummary(BaseModel):
    total:          int   # every reconciliation row in the filtered scope
    matched:        int
    minor_diff:     int
    mismatch:       int
    missing_bsp:    int
    extra_bsp:      int
    possible_match: int
    total_variance: float                      # sum of abs_variance over the filtered set
    last_run_at:    Optional[datetime] = None


class FieldDiff(BaseModel):
    field:    str
    label:    str
    expected: Optional[float] = None
    actual:   Optional[float] = None
    variance: Optional[float] = None
    match:    Optional[bool]  = None
    severity: Optional[str]   = None


class ReconciliationIssue(BaseModel):
    rule_id:  str
    field:    str
    severity: str
    message:  str
    expected: Optional[float] = None
    actual:   Optional[float] = None
    variance: Optional[float] = None


class ReconciliationRowRead(BaseModel):
    id:            int
    ticket_id:     Optional[int]
    bsp_row_id:    Optional[int]
    ticket_number: Optional[str]
    airline_name:  Optional[str]
    airline_code:  Optional[str]
    issue_date:    Optional[date]
    txn_type:      Optional[str]
    match_status:  str
    severity:      str
    net_variance:  Optional[float]
    abs_variance:  Optional[float]
    issue_count:   int = 0

    model_config = {"from_attributes": True}


class ReconciliationDetail(ReconciliationRowRead):
    pax_name:          Optional[str] = None
    match_method:      str = "none"
    commission_source: Optional[str] = None
    reconciled_at:     Optional[datetime] = None
    remarks:           Optional[str] = None
    fields:            list[FieldDiff] = []
    issues:            list[ReconciliationIssue] = []
    related_bsp:       list[dict] = []
    # Full records for the side-by-side popup (this is the BSP statement / this is the ticket).
    bsp_row:           Optional[BspStatementRowRead] = None   # ACTUAL settlement row (+ taxes)
    ticket:            Optional[UploadedTicketRead]  = None    # EXPECTED internal ticket


class ReconciliationPage(BaseModel):
    summary: ReconciliationSummary
    total:   int
    offset:  int
    limit:   int
    rows:    list[ReconciliationRowRead] = []
