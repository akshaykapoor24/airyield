from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


# ── Legacy Excel/CSV extract → confirm flow (kept for spreadsheet uploads) ───
class BspRow(BaseModel):
    ticket_number:    Optional[str]   = None
    airline_code:     Optional[str]   = None
    gross:            Optional[float] = None
    commission:       Optional[float] = None
    adm:              Optional[float] = None
    acm:              Optional[float] = None
    refund:           Optional[float] = None
    net_due:          Optional[float] = None
    transaction_type: Optional[str]   = None
    raw_data:         dict            = {}


class BspExtractionPreview(BaseModel):
    """Returned by POST /bsp/upload/extract — nothing is saved yet."""
    file_name:         str
    total_rows:        int
    rows:              list[BspRow] = []
    warnings:          list[str]    = []
    xls_columns:       list[str]    = []
    suggested_mapping: dict         = {}


class ConfirmBspPayload(BaseModel):
    file_name:    Optional[str]  = None
    airline_code: Optional[str]  = None
    airline_name: Optional[str]  = None
    period_from:  Optional[date] = None
    period_to:    Optional[date] = None
    rows:         list[BspRow]   = []


# ── Async PDF upload ─────────────────────────────────────────────────────────
class BspUploadResponse(BaseModel):
    """202 response from POST /bsp/upload — parsing continues in the background."""
    batch_id: str
    status:   str


# ── Reads ────────────────────────────────────────────────────────────────────
class BspStatementRead(BaseModel):
    batch_id:        str
    statement_name:  Optional[str]
    airline_code:    Optional[str]
    airline_name:    Optional[str]
    period_from:     Optional[date]
    period_to:       Optional[date]
    file_name:       Optional[str]
    file_url:        Optional[str]
    row_count:       int
    # async processing state
    status:          str = "pending"
    total_pages:     int = 0
    processed_pages: int = 0
    total_rows:      int = 0
    processed_rows:  int = 0
    progress_pct:    int = 0
    error:           Optional[str] = None
    created_by_name: Optional[str] = None
    created_at:      datetime

    model_config = {"from_attributes": True}


class BspTaxComponentRead(BaseModel):
    component_type: Optional[str]
    component_code: Optional[str]
    amount:         Optional[float]

    model_config = {"from_attributes": True}


class BspStatementRowRead(BaseModel):
    id:                int
    statement_id:      str
    ticket_number:     Optional[str]
    document_number:   Optional[str] = None
    spdr_no:           Optional[str] = None
    airline_code:      Optional[str]
    airline_accounting_code: Optional[str] = None
    transaction_type:  Optional[str]
    issue_date:        Optional[date] = None
    cpui:              Optional[str] = None
    nr_code:           Optional[str] = None
    stat:              Optional[str] = None
    form_of_payment:   Optional[str] = None
    transaction_amount: Optional[float] = None
    fare_amount:       Optional[float] = None
    penalty_amount:    Optional[float] = None
    net_sales:         Optional[float] = None
    standard_commission_rate:   Optional[float] = None
    standard_commission_amount: Optional[float] = None
    supplier_discount_rate:     Optional[float] = None
    supplier_discount_amount:   Optional[float] = None
    tax_on_commission: Optional[float] = None
    balance_payable:   Optional[float] = None
    # detailed-PDF enrichment
    airline_name:         Optional[str] = None
    tour:                 Optional[list[str]] = None
    alt_document_numbers: Optional[list[str]] = None
    rtdn:                 Optional[str] = None
    esac:                 Optional[str] = None
    wavr:                 Optional[str] = None
    associated_docs:      Optional[dict] = None   # {"rtdn": {...}, "conjunctions": [...]}
    # legacy Excel columns
    gross:             Optional[float] = None
    commission:        Optional[float] = None
    adm:               Optional[float] = None
    acm:               Optional[float] = None
    refund:            Optional[float] = None
    net_due:           Optional[float] = None
    # matching (Phase 2)
    matched_ticket_id: Optional[int]
    match_status:      str
    taxes:             list[BspTaxComponentRead] = []
    created_at:        datetime

    model_config = {"from_attributes": True}


class BspRowsPage(BaseModel):
    """Paginated rows — BSP statements can hold ~50k rows, so /rows is server-paged."""
    total:  int
    offset: int
    limit:  int
    rows:   list[BspStatementRowRead] = []


class BspParseErrorRead(BaseModel):
    id:          int
    page_number: Optional[int]
    error:       Optional[str]
    created_at:  datetime

    model_config = {"from_attributes": True}


class BspParseErrorsPage(BaseModel):
    total:  int
    offset: int
    limit:  int
    errors: list[BspParseErrorRead] = []
