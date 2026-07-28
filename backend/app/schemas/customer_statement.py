from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict

from app.schemas.uploaded_ticket import TicketRow


# ── Directory selection snapshots (stored as JSONB on the statement) ──────────
class EntitySnap(BaseModel):
    id:   int
    name: Optional[str] = None
    code: Optional[str] = None


class LoginIdSnap(BaseModel):
    id:           int
    login_id:     Optional[str] = None
    airline_name: Optional[str] = None
    entity_id:    Optional[int] = None
    entity_name:  Optional[str] = None


# ── Upload confirm ────────────────────────────────────────────────────────────
class ConfirmCustomerStatementPayload(BaseModel):
    file_name:  str
    rows:       list[TicketRow]
    agency_id:  Optional[int] = None
    agency:     str
    entities:   List[EntitySnap]  = []
    login_ids:  List[LoginIdSnap] = []
    valid_from: date
    valid_to:   date


class ConfirmCustomerStatementResult(BaseModel):
    batch_id:      str
    created_count: int


# ── Statement (batch) read ────────────────────────────────────────────────────
class CustomerStatementRead(BaseModel):
    batch_id:        str
    statement_type:  str = "B2B"
    statement_name:  Optional[str] = None
    agency:          str
    agency_id:       Optional[int] = None
    entities:        Optional[List[Any]] = None
    login_ids:       Optional[List[Any]] = None
    valid_from:      date
    valid_to:        date
    file_name:       str
    file_url:        Optional[str] = None
    ticket_count:    int
    created_by_name: Optional[str] = None
    created_at:      datetime

    model_config = {"from_attributes": True}


# ── Ticket row read (B2B subset — TicketRow provides defaults for absent cols) ─
class CustomerStatementTicketRead(TicketRow):
    id:            int
    batch_id:      str
    file_name:     str
    tenant_id:     int
    created_by_id: int
    created_at:    datetime
    ticket_status: str = "draft"

    model_config = {"from_attributes": True}


# ── Ticket row update (B2B editable fields only) ──────────────────────────────
class CustomerStatementTicketUpdate(BaseModel):
    ticket_number:        Optional[str]   = None
    booking_ref:          Optional[str]   = None
    last_name:            Optional[str]   = None
    first_name:           Optional[str]   = None
    sector:               Optional[str]   = None
    booking_class:        Optional[str]   = None
    airline_name:         Optional[str]   = None
    airlines_code:        Optional[str]   = None
    gds_pnr:              Optional[str]   = None
    ticket_date:          Optional[str]   = None
    departure_datetime:   Optional[str]   = None
    segment_type:         Optional[str]   = None
    invoice_type:         Optional[str]   = None
    invoice_no:           Optional[str]   = None
    sell_fare:            Optional[float] = None
    sell_tax:             Optional[float] = None
    sell_tax_yq:          Optional[float] = None
    sale_yr:              Optional[float] = None
    sale_k3:              Optional[float] = None
    rei_sell:             Optional[float] = None
    seat_selection:       Optional[float] = None
    excess_baggage:       Optional[float] = None
    meals:                Optional[float] = None
    rfd_sell:             Optional[float] = None
    can_charge:           Optional[float] = None
    booking_fee_sell:     Optional[float] = None
    cgst_sell:            Optional[float] = None
    sgst_sell:            Optional[float] = None
    igst_sell:            Optional[float] = None
    comm_sell:            Optional[float] = None
    adm:                  Optional[float] = None
    incentive_sell:       Optional[float] = None
    dis_sell:             Optional[float] = None
    tds_sell:             Optional[float] = None
    total_amt:            Optional[float] = None
    paid_by_credit_card:  Optional[float] = None
    net_amt:              Optional[float] = None
    cc:                   Optional[str]   = None
    acc_code:             Optional[str]   = None
    sold_to:              Optional[str]   = None
    customer_name:        Optional[str]   = None
    tour_code:            Optional[str]   = None
    ticket_status:        Optional[str]   = None
    split_type:           Optional[str]   = None

    model_config = ConfigDict(extra="ignore")
