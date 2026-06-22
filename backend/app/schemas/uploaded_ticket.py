from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class TicketRow(BaseModel):
    """A single parsed row from the XLS preview (before DB save)."""
    row_order:           int           = 0

    # ── Shared / B2B columns ──────────────────────────────────────────────
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
    sold_to:             Optional[str]   = None
    customer_name:       Optional[str]   = None
    tour_code:           Optional[str]   = None
    split_type:          Optional[str]   = None
    adm_acm_ra:          Optional[str]   = None

    # ── Airline-specific columns ──────────────────────────────────────────
    statement_type:       Optional[str]   = None
    pax_name:             Optional[str]   = None
    air_pnr:              Optional[str]   = None
    pcc:                  Optional[str]   = None
    booking_signon:       Optional[str]   = None
    booking_pcc:          Optional[str]   = None
    booking_agency_name:  Optional[str]   = None
    ticketing_signon:     Optional[str]   = None
    document_type:        Optional[str]   = None
    fare_basis:           Optional[str]   = None
    fare_const_type:      Optional[str]   = None
    base_fare_currency:   Optional[str]   = None
    transaction_type:     Optional[str]   = None
    exchanged_for:        Optional[str]   = None
    stock_control_no:     Optional[str]   = None
    stp_no:               Optional[str]   = None
    void_date:            Optional[str]   = None
    coupon_status:        Optional[str]   = None
    refund_type:          Optional[str]   = None
    trip_id:              Optional[str]   = None
    ai_code:              Optional[str]   = None
    value_code:           Optional[str]   = None
    multiple_receivables: Optional[str]   = None
    wo_tax:               Optional[float] = None
    other_tax:            Optional[float] = None
    comm_percent:         Optional[float] = None
    net_remit:            Optional[float] = None
    net_fare:             Optional[float] = None
    invoice_fare:         Optional[float] = None
    total_refund_amount:  Optional[float] = None
    roe:                  Optional[float] = None
    nuc:                  Optional[float] = None
    fop:                  Optional[str]   = None
    fop_details:          Optional[str]   = None
    cc_auth:              Optional[str]   = None
    cc_do_expiry:         Optional[str]   = None
    flight_no:            Optional[str]   = None
    travel_dt:            Optional[str]   = None
    fare_ladder:          Optional[str]   = None
    gstn:                 Optional[str]   = None
    business_phone:       Optional[str]   = None
    business_email:       Optional[str]   = None
    entity_address:       Optional[str]   = None
    tax_breakup:          Optional[Dict[str, float]]     = None
    segments:             Optional[List[Dict[str, Any]]] = None

    # ── Derived / calculation fields ──────────────────────────────────────
    airline_name:          Optional[str]   = None
    matched_deal_id:       Optional[int]   = None
    matched_deal_type:     Optional[str]   = None
    matched_deal_name:     Optional[str]   = None
    calculated_incentive:  Optional[float] = None
    incentive_breakdown:   Optional[Dict[str, float]] = None
    exclusion_reason:      Optional[str]   = None


class TicketExtractionPreview(BaseModel):
    """Returned by POST /tickets/upload/extract."""
    file_name:         str
    total_rows:        int
    rows:              list[TicketRow]
    warnings:          list[str]       = []
    xls_columns:       list[str]       = []
    suggested_mapping: dict[str, str]  = {}
    is_template_match: bool            = True
    sample_row:        dict[str, str]  = {}


class ConfirmTicketUploadPayload(BaseModel):
    file_name:      str
    rows:           list[TicketRow]
    statement_type: str = "B2B"
    agency:         str
    valid_from:     date
    valid_to:       date


class TicketStatementRead(BaseModel):
    batch_id:         str
    statement_type:   str = "B2B"
    statement_name:   Optional[str] = None
    agency:           str
    valid_from:       date
    valid_to:         date
    file_name:        str
    file_url:         Optional[str] = None
    ticket_count:     int
    created_by_name:  Optional[str] = None
    created_at:       datetime

    model_config = {"from_attributes": True}


class UploadedTicketRead(TicketRow):
    """Full record as stored in DB — used for both list and detail responses."""
    id:              int
    batch_id:        str
    file_name:       str
    tenant_id:       int
    created_by_id:   int
    created_at:      datetime
    ticket_status:   str = "draft"

    model_config = {"from_attributes": True}


class ConfirmTicketUploadResult(BaseModel):
    batch_id:      str
    created_count: int


class RunCalculationResult(BaseModel):
    ticket_id:            int
    matched:              bool
    excluded:             bool = False
    cancelled:            bool = False
    included:             bool = False
    reversed:             bool = False
    matched_deal_id:      Optional[int]
    matched_deal_type:    Optional[str]
    matched_deal_name:    Optional[str]
    calculated_incentive: Optional[float]
    incentive_breakdown:  Optional[Dict[str, float]] = None
    message:              str


class BatchRunCalculationResult(BaseModel):
    processed:   int
    matched:     int
    unmatched:   int
    errors:      int
    excluded:    int = 0
    cancelled:   int = 0
    reversed:    int = 0


class UploadedTicketUpdate(BaseModel):
    """Partial update payload — all fields optional."""
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
    ticket_status:        Optional[str]   = None
    split_type:           Optional[str]   = None
    exclusion_reason:     Optional[str]   = None
    adm_acm_ra:           Optional[str]   = None
    # Airline-specific editable fields
    pax_name:             Optional[str]   = None
    air_pnr:              Optional[str]   = None
    pcc:                  Optional[str]   = None
    fare_basis:           Optional[str]   = None
    transaction_type:     Optional[str]   = None
    fop:                  Optional[str]   = None
    flight_no:            Optional[str]   = None
    travel_dt:            Optional[str]   = None
    gstn:                 Optional[str]   = None
    business_phone:       Optional[str]   = None
    business_email:       Optional[str]   = None

    model_config = ConfigDict(extra="ignore")


# ── Match Diagnosis schemas ────────────────────────────────────────────────

class MatchStepResult(BaseModel):
    step:         str
    passed:       bool
    ticket_value: str
    deal_value:   str
    detail:       str


class PLBDiagnostic(BaseModel):
    plb_key:            str
    raw_plb:            dict[str, Any]
    steps:              list[MatchStepResult]
    incentive_breakdown: Optional[dict[str, Any]]
    plb_overall_match:  bool


class ExclusionRuleStep(BaseModel):
    field:        str
    rule_value:   str
    ticket_value: str
    matched:      bool


class ExclusionRuleDiagnostic(BaseModel):
    rule_name:   str
    is_excluded: bool
    reason:      str
    steps:       list[ExclusionRuleStep]


class DealDiagnostic(BaseModel):
    deal_id:              int
    deal_type:            str
    deal_name:            str
    deal_no:              str
    valid_from:           Optional[date]
    valid_to:             Optional[date]
    trigger_type:         Optional[str]
    supplier_name:        Optional[str]  = None
    deal_validity_step:   MatchStepResult
    plbs:                 list[PLBDiagnostic]
    overall_match:        bool
    best_incentive:       Optional[float]
    deal_lifecycle_status:    Optional[str] = None
    exclusion_diagnostic: Optional[ExclusionRuleDiagnostic] = None
    inclusion_diagnostic: Optional[ExclusionRuleDiagnostic] = None


class MatchDiagnosisResponse(BaseModel):
    ticket_id:               int
    raw_airline_code:        str
    normalized_codes:        list[str]
    airline_resolved:        Optional[str]
    airline_resolution_detail: str
    raw_departure:           Optional[str]
    raw_ticket_date:         Optional[str]
    travel_date:             Optional[str]
    travel_date_detail:      str
    segment_type:            Optional[str]
    booking_class:           Optional[str]
    cabin_groups_resolved:   list[str]
    cabin_resolution_detail: str
    invoice_type:            Optional[str]
    sell_fare:               Optional[float]
    sell_tax_yq:             Optional[float]
    sale_yr:                 Optional[float]
    total_deals_checked:     int
    matched_count:           int
    deals:                   list[DealDiagnostic]
