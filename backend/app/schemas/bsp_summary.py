from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel


class BspSummaryUploadResponse(BaseModel):
    batch_id: str
    group_id: str
    status: str


class BspSummaryRead(BaseModel):
    batch_id: str
    group_id: str
    agent_code: Optional[str] = None
    agent_name: Optional[str] = None
    reference: Optional[str] = None
    billing_period_code: Optional[str] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    currency: Optional[str] = None
    file_name: Optional[str] = None
    status: str
    total_pages: int
    processed_pages: int
    error: Optional[str] = None
    gt_issues: Optional[Decimal] = None
    gt_refunds: Optional[Decimal] = None
    gt_debit_memos: Optional[Decimal] = None
    gt_credit_memos: Optional[Decimal] = None
    gt_std_comm: Optional[Decimal] = None
    gt_sup_comm: Optional[Decimal] = None
    gt_tax_on_comm: Optional[Decimal] = None
    gt_balance_payable: Optional[Decimal] = None
    gt_doc_count: Optional[int] = None
    match_status: str
    match_detail: Optional[dict] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BspSummaryRowRead(BaseModel):
    id: int
    category: Optional[str] = None
    airline_code: Optional[str] = None
    airline_iata: Optional[str] = None
    airline_name: Optional[str] = None
    fop: Optional[str] = None
    issues: Optional[Decimal] = None
    refunds: Optional[Decimal] = None
    debit_memos: Optional[Decimal] = None
    credit_memos: Optional[Decimal] = None
    std_comm: Optional[Decimal] = None
    sup_comm: Optional[Decimal] = None
    tax_on_comm: Optional[Decimal] = None
    balance_payable: Optional[Decimal] = None
    doc_count: Optional[int] = None

    model_config = {"from_attributes": True}


class BspComparisonLine(BaseModel):
    line: str                       # issues | refunds | ... | balance_payable
    summary: Optional[Decimal] = None
    detail: Optional[Decimal] = None
    variance: Optional[Decimal] = None
    ok: bool = False


class BspGroupRead(BaseModel):
    """The paired view for the BSP repository list (one summary + one detailed)."""
    group_id: str
    agent_code: Optional[str] = None
    agent_name: Optional[str] = None
    reference: Optional[str] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    # summary leg
    summary_batch_id: Optional[str] = None
    summary_status: Optional[str] = None
    summary_balance: Optional[Decimal] = None
    summary_file_name: Optional[str] = None
    # detailed leg
    detail_batch_id: Optional[str] = None
    detail_status: Optional[str] = None
    detail_balance: Optional[Decimal] = None
    detail_progress_pct: Optional[int] = None
    detail_file_name: Optional[str] = None
    # reconciliation
    match_status: str = "pending"     # pending | matched | mismatch
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


class BspGroupComparison(BaseModel):
    group_id: str
    match_status: str
    matched_at: Optional[datetime] = None
    lines: List[BspComparisonLine] = []
    summary: Optional[BspSummaryRead] = None
