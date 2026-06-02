from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
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
    split_type:            Optional[str]   = None   # "normal" | "split"
    # derived / calculation fields
    airline_name:          Optional[str]   = None
    matched_deal_id:       Optional[int]   = None
    matched_deal_type:     Optional[str]   = None
    matched_deal_name:     Optional[str]   = None
    calculated_incentive:  Optional[float] = None
    exclusion_reason:      Optional[str]   = None


class TicketExtractionPreview(BaseModel):
    """Returned by POST /tickets/upload/extract."""
    file_name:         str
    total_rows:        int
    rows:              list[TicketRow]
    warnings:          list[str]       = []
    xls_columns:       list[str]       = []
    suggested_mapping: dict[str, str]  = {}   # canonical → xls_col
    is_template_match: bool            = True
    sample_row:        dict[str, str]  = {}   # xls_col → first-row raw value (for mapping preview)


class ConfirmTicketUploadPayload(BaseModel):
    file_name:      str
    rows:           list[TicketRow]
    statement_name: str
    agency:         str
    valid_from:     date
    valid_to:       date


class TicketStatementRead(BaseModel):
    batch_id:         str
    statement_name:   str
    agency:           str
    valid_from:       date
    valid_to:         date
    file_name:        str
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
    excluded:    int = 0
    cancelled:   int = 0


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
    ticket_status:       Optional[str]   = None
    split_type:          Optional[str]   = None
    exclusion_reason:    Optional[str]   = None

    model_config = ConfigDict(extra="ignore")


# ── Match Diagnosis schemas ────────────────────────────────────────────────

class MatchStepResult(BaseModel):
    step:         str            # "Deal Validity" | "Flight Type" | "Booking Class" | "Trigger Type" | "PLB Sub-Validity"
    passed:       bool
    ticket_value: str            # exact value from ticket
    deal_value:   str            # exact value from deal / PLB
    detail:       str            # full trace sentence


class PLBDiagnostic(BaseModel):
    plb_key:            str
    raw_plb:            dict[str, Any]
    steps:              list[MatchStepResult]
    incentive_breakdown: Optional[dict[str, Any]]  # always computed even if steps failed
    plb_overall_match:  bool


class ExclusionRuleStep(BaseModel):
    field:        str   # e.g. "validFrom", "class", "originAirport"
    rule_value:   str   # what the rule requires
    ticket_value: str   # resolved value from the ticket
    matched:      bool  # did this field match?


class ExclusionRuleDiagnostic(BaseModel):
    rule_name:   str                    # "Exclusion For Payout"
    is_excluded: bool                   # final AND verdict
    reason:      str                    # human-readable summary
    steps:       list[ExclusionRuleStep]


class DealDiagnostic(BaseModel):
    deal_id:              int
    deal_type:            str            # "airline" | "b2b"
    deal_name:            str
    deal_no:              str            # e.g. "AIR-0014", "B2B-0001"
    valid_from:           Optional[date]
    valid_to:             Optional[date]
    trigger_type:         Optional[str]  # airline deals only
    deal_validity_step:   MatchStepResult
    plbs:                 list[PLBDiagnostic]
    overall_match:        bool
    best_incentive:       Optional[float]
    deal_lifecycle_status:   Optional[str] = None
    exclusion_diagnostic: Optional[ExclusionRuleDiagnostic] = None


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
