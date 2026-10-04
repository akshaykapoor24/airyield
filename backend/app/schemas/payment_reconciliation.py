"""Wire shapes for Vendors data → Payment Module → Reconciliation.

Vendor vs MO vocabulary throughout — `vendor_*` is the consolidator's bill (`tp-gds`),
`mo_*` our own mid-office record (`mo-gds`). `variance` is always vendor − MO.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


# ── request ──────────────────────────────────────────────────────────────────
class RunPaymentReconciliationPayload(BaseModel):
    vendor_batch_id: str
    mo_batch_id: str


# ── shared roll-up ───────────────────────────────────────────────────────────
class PaymentTotals(BaseModel):
    total: int = 0
    matched: int = 0
    minor_diff: int = 0
    mismatch: int = 0
    possible_match: int = 0
    vendor_only: int = 0
    mo_only: int = 0
    # Every vendor ticket's net — the bill. Balance lines are never in it.
    vendor_net_total: float = 0.0
    mo_net_total: float = 0.0
    # Paired rows only (matched / minor_diff / mismatch): vendor − MO.
    net_variance_total: float = 0.0
    vendor_only_total: float = 0.0
    mo_only_total: float = 0.0
    calc_commission_total: float = 0.0
    vendor_commission_total: float = 0.0
    # Positive = the vendor under-paid commission against our deals.
    shortfall_total: float = 0.0
    payable_total: float = 0.0


class PaymentReconciliationRunResult(PaymentTotals):
    run_id: int
    reconciled_at: datetime
    vendor_closing_balance: Optional[float] = None
    mo_closing_balance: Optional[float] = None


class PaymentRunInfo(BaseModel):
    """The last completed reconciliation of the pair on screen."""
    run_id: int
    completed_at: Optional[datetime] = None
    vendor_source_file: Optional[str] = None
    mo_source_file: Optional[str] = None
    vendor_closing_balance: Optional[float] = None
    mo_closing_balance: Optional[float] = None
    vendor_opening_balance: Optional[float] = None
    # True when the opening is closing − Σ net rather than a printed OLD line.
    vendor_opening_derived: bool = False
    mo_opening_balance: Optional[float] = None
    mo_opening_derived: bool = False
    vendor_balance_lines: list[dict] = []
    mo_balance_lines: list[dict] = []
    commission_run_id: Optional[int] = None
    commission_completed_at: Optional[datetime] = None
    commission_priced_rows: int = 0
    commission_unpriced_rows: int = 0


class PaymentCommissionState(BaseModel):
    """Commission income's CURRENT state for the vendor upload — read live, so the screen
    can say the reconciliation is out of date when commission was re-run after it."""
    run_id: Optional[int] = None
    status: str = "none"          # none | queued | processing | completed | failed
    completed_at: Optional[datetime] = None
    total_rows: int = 0
    priced_rows: int = 0
    pending_rows: int = 0
    stale: bool = False


# ── rows ─────────────────────────────────────────────────────────────────────
class PaymentFieldDiff(BaseModel):
    key: str
    label: str
    vendor: Optional[float] = None
    mo: Optional[float] = None
    variance: Optional[float] = None
    match: Optional[bool] = None
    severity: Optional[str] = None


class PaymentIssue(BaseModel):
    field: Optional[str] = None
    label: Optional[str] = None
    severity: str
    message: str
    vendor: Optional[float] = None
    mo: Optional[float] = None
    variance: Optional[float] = None


class PaymentReconciliationRowRead(BaseModel):
    id: int
    vendor_batch_id: str
    mo_batch_id: str
    ticket_number: Optional[str] = None
    ticket_prefix: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    issue_date: Optional[date] = None
    pax_name: Optional[str] = None
    sector: Optional[str] = None
    pnr: Optional[str] = None
    match_status: str
    severity: str
    match_method: str = "none"
    # How many statement rows each side netted into this ticket.
    vendor_rows: int = 0
    mo_rows: int = 0
    vendor_gross: Optional[float] = None
    mo_gross: Optional[float] = None
    vendor_net: Optional[float] = None
    mo_net: Optional[float] = None
    net_variance: Optional[float] = None
    vendor_commission: Optional[float] = None
    mo_commission: Optional[float] = None
    calc_commission: Optional[float] = None
    commission_shortfall: Optional[float] = None
    payable_after_commission: Optional[float] = None
    commission_status: str = "none"
    issue_count: int = 0
    # ── process checks (steps 6A–6E) ──
    ticket_key: Optional[str] = None
    booking_id: Optional[str] = None
    not_billed: bool = False
    is_duplicate: bool = False
    mo_vendor_status: str = "none"
    mo_vendor_name: Optional[str] = None
    enriched_fields: list[str] = []
    # ── the payment item's decision (step 10) and payment (step 12) ──
    item_id: Optional[int] = None
    decision_status: Optional[str] = None
    decision_source: Optional[str] = None
    decision_action: Optional[str] = None
    approved_amount: Optional[float] = None
    decision_reason: Optional[str] = None
    paid: bool = False


class PaymentReconciliationDetail(PaymentReconciliationRowRead):
    reconciled_at: Optional[datetime] = None
    fields: list[PaymentFieldDiff] = []
    issues: list[PaymentIssue] = []
    notes: list[str] = []
    commission_detail: list[dict] = []
    duplicate_info: Optional[dict] = None
    mo_vendor_info: Optional[dict] = None
    enrichment: Optional[dict] = None
    remarks: Optional[str] = None
    ops_reference: Optional[str] = None
    decided_by_name: Optional[str] = None
    decided_at: Optional[datetime] = None
    paid_amount: Optional[float] = None
    paid_at: Optional[datetime] = None
    payment_id: Optional[int] = None
    suggested_payable: Optional[float] = None
    # The statement rows behind each side: their `data`, plus `_id`. A row that has since
    # been re-processed or deleted is simply absent — `records_missing` says so.
    vendor_records: list[dict] = []
    mo_records: list[dict] = []
    records_missing: bool = False


class PaymentReconciliationPage(BaseModel):
    summary: PaymentTotals
    run: Optional[PaymentRunInfo] = None
    commission: PaymentCommissionState
    # Steps 6A–6E and 10, over the FILTERED set: flag counts and decision counts.
    flags: dict = {}
    decisions: dict = {}
    total: int
    offset: int
    limit: int
    rows: list[PaymentReconciliationRowRead] = []


class PaymentReconciliationFacets(BaseModel):
    airlines: list[str] = []
    statuses: list[str] = []


# ── Payment Module: checks, decisions, payments ──────────────────────────────
class ControlsPayload(BaseModel):
    expected_count: Optional[int] = None
    expected_amount: Optional[str] = None
    opening_balance: Optional[str] = None
    # Explicit clears — an omitted field is left as it is.
    clear: list[str] = []


class ConfirmAccountPayload(BaseModel):
    account_id: Optional[str] = None


class DecisionPayload(BaseModel):
    action: str
    amount: Optional[str] = None
    remarks: Optional[str] = None
    ops_reference: Optional[str] = None


class BulkDecisionPayload(DecisionPayload):
    item_ids: list[int]


class CorrectionPayload(BaseModel):
    reconciliation_id: int
    remarks: Optional[str] = None


class PaymentItemRead(BaseModel):
    id: int
    vendor_batch_id: str
    vendor_source_file: Optional[str] = None
    statement_uploaded_at: Optional[datetime] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    ticket_key: str
    ticket_number: Optional[str] = None
    ticket_prefix: Optional[str] = None
    pax_name: Optional[str] = None
    airline_name: Optional[str] = None
    issue_date: Optional[date] = None
    sector: Optional[str] = None
    booking_id: Optional[str] = None
    match_status: Optional[str] = None
    is_duplicate: bool = False
    not_billed: bool = False
    mo_vendor_status: Optional[str] = None
    vendor_net: Optional[float] = None
    mo_net: Optional[float] = None
    net_variance: Optional[float] = None
    commission_shortfall: Optional[float] = None
    suggested_payable: Optional[float] = None
    decision_status: str
    decision_source: str
    decision_action: Optional[str] = None
    approved_amount: Optional[float] = None
    decision_reason: Optional[str] = None
    remarks: Optional[str] = None
    ops_reference: Optional[str] = None
    payment_id: Optional[int] = None
    paid_amount: Optional[float] = None
    paid_at: Optional[datetime] = None
    stale: bool = False
    age_days: Optional[int] = None


class PayableSummary(BaseModel):
    vendor_batch_id: str
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    source_file: Optional[str] = None
    tickets: int = 0
    billed: float = 0.0
    commission_shortfall: float = 0.0
    suggested: float = 0.0
    counts: dict = {}
    excluded: float = 0.0
    pending: float = 0.0
    held: float = 0.0
    approved: float = 0.0
    brought_forward: float = 0.0
    paid: float = 0.0
    final_payable: float = 0.0
    items: list[PaymentItemRead] = []


class PaymentCreatePayload(BaseModel):
    supplier_id: Optional[int] = None
    vendor_batch_id: Optional[str] = None
    item_ids: list[int]
    payment_date: date
    mode: Optional[str] = None
    reference: Optional[str] = None
    remarks: Optional[str] = None


class VoidPayload(BaseModel):
    reason: str


class VendorPaymentRead(BaseModel):
    id: int
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    vendor_batch_id: Optional[str] = None
    vendor_source_file: Optional[str] = None
    payment_date: date
    amount: float
    mode: Optional[str] = None
    reference: Optional[str] = None
    remarks: Optional[str] = None
    items_count: int = 0
    status: str
    void_reason: Optional[str] = None
    voided_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class VendorPaymentDetail(VendorPaymentRead):
    items: list[PaymentItemRead] = []


class OutstandingPage(BaseModel):
    supplier_id: Optional[int] = None
    totals: dict = {}
    items: list[PaymentItemRead] = []
