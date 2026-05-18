from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class TicketRow(BaseModel):
    """A single parsed row from the XLS preview (before DB save)."""
    row_order:           int           = 0
    booking_ref:         Optional[str] = None
    segment_type:        Optional[str] = None
    invoice_type:        Optional[str] = None
    invoice_no:          Optional[str] = None
    ticket_date:         Optional[str] = None
    last_name:           Optional[str] = None
    first_name:          Optional[str] = None
    sector:              Optional[str] = None
    booking_class:       Optional[str] = None
    departure_datetime:  Optional[str] = None
    gds_pnr:             Optional[str] = None
    airlines_code:       Optional[str] = None
    ticket_number:       Optional[str] = None
    sell_fare:           Optional[float] = None
    sell_tax:            Optional[float] = None
    sell_tax_yq:         Optional[float] = None
    sale_yr:             Optional[float] = None
    sale_k3:             Optional[float] = None
    rei_sell:            Optional[float] = None
    seat_selection:      Optional[float] = None
    excess_baggage:      Optional[float] = None
    meals:               Optional[float] = None
    rfd_sell:            Optional[float] = None
    can_charge:          Optional[float] = None
    booking_fee_sell:    Optional[float] = None
    cgst_sell:           Optional[float] = None
    sgst_sell:           Optional[float] = None
    igst_sell:           Optional[float] = None
    comm_sell:           Optional[float] = None
    adm:                 Optional[float] = None
    incentive_sell:      Optional[float] = None
    dis_sell:            Optional[float] = None
    tds_sell:            Optional[float] = None
    total_amt:           Optional[float] = None
    paid_by_credit_card: Optional[float] = None
    net_amt:             Optional[float] = None
    cc:                  Optional[str]   = None
    acc_code:            Optional[str]   = None
    sold_to:             Optional[str]   = None   # 'customer' | 'agency'
    customer_name:       Optional[str]   = None
    # derived / calculation fields
    airline_name:          Optional[str]   = None
    matched_deal_id:       Optional[int]   = None
    matched_deal_type:     Optional[str]   = None
    matched_deal_name:     Optional[str]   = None
    calculated_incentive:  Optional[float] = None


class TicketExtractionPreview(BaseModel):
    """Returned by POST /tickets/upload/extract."""
    file_name:         str
    total_rows:        int
    rows:              list[TicketRow]
    warnings:          list[str]       = []
    xls_columns:       list[str]       = []
    suggested_mapping: dict[str, str]  = {}   # canonical → xls_col
    is_template_match: bool            = True


class ConfirmTicketUploadPayload(BaseModel):
    file_name: str
    rows:      list[TicketRow]


class UploadedTicketRead(TicketRow):
    """Full record as stored in DB — used for both list and detail responses."""
    id:              int
    batch_id:        str
    file_name:       str
    tenant_id:       int
    created_by_id:   int
    created_at:      datetime

    model_config = {"from_attributes": True}


class ConfirmTicketUploadResult(BaseModel):
    batch_id:      str
    created_count: int


class RunCalculationResult(BaseModel):
    ticket_id:            int
    matched:              bool
    matched_deal_id:      Optional[int]
    matched_deal_type:    Optional[str]
    matched_deal_name:    Optional[str]
    calculated_incentive: Optional[float]
    message:              str


class BatchRunCalculationResult(BaseModel):
    processed:   int
    matched:     int
    unmatched:   int
    errors:      int


class UploadedTicketUpdate(BaseModel):
    """Partial update payload — all fields optional."""
    ticket_number:       Optional[str]   = None
    booking_ref:         Optional[str]   = None
    last_name:           Optional[str]   = None
    first_name:          Optional[str]   = None
    sector:              Optional[str]   = None
    booking_class:       Optional[str]   = None
    airline_name:        Optional[str]   = None
    airlines_code:       Optional[str]   = None
    gds_pnr:             Optional[str]   = None
    ticket_date:         Optional[str]   = None
    departure_datetime:  Optional[str]   = None
    segment_type:        Optional[str]   = None
    invoice_type:        Optional[str]   = None
    invoice_no:          Optional[str]   = None
    sell_fare:           Optional[float] = None
    sell_tax:            Optional[float] = None
    sell_tax_yq:         Optional[float] = None
    sale_yr:             Optional[float] = None
    sale_k3:             Optional[float] = None
    rei_sell:            Optional[float] = None
    seat_selection:      Optional[float] = None
    excess_baggage:      Optional[float] = None
    meals:               Optional[float] = None
    rfd_sell:            Optional[float] = None
    can_charge:          Optional[float] = None
    booking_fee_sell:    Optional[float] = None
    cgst_sell:           Optional[float] = None
    sgst_sell:           Optional[float] = None
    igst_sell:           Optional[float] = None
    comm_sell:           Optional[float] = None
    adm:                 Optional[float] = None
    incentive_sell:      Optional[float] = None
    dis_sell:            Optional[float] = None
    tds_sell:            Optional[float] = None
    total_amt:           Optional[float] = None
    paid_by_credit_card: Optional[float] = None
    net_amt:             Optional[float] = None
    cc:                  Optional[str]   = None
    acc_code:            Optional[str]   = None
    sold_to:             Optional[str]   = None
    customer_name:       Optional[str]   = None

    model_config = ConfigDict(extra="ignore")
