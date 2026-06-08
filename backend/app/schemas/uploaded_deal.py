from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from app.models.uploaded_deal import UploadedDealStatus, UploadedDealSourceType


# ── UploadedDeal ───────────────────────────────────────────────────────────

class UploadedDealCreate(BaseModel):
    source_agent: str
    issue_date:   Optional[date] = None
    notes:        Optional[str]  = None


class UploadedDealRead(BaseModel):
    id:            int
    source_type:   UploadedDealSourceType
    source_agent:  str
    issue_date:    Optional[date]
    file_name:     str
    file_type:     str
    status:        UploadedDealStatus
    notes:         Optional[str]
    # deal header fields
    airline_type:     Optional[str]  = None
    airline_name:     Optional[str]  = None
    contract_year:    Optional[str]  = None
    valid_from:       Optional[date] = None
    valid_to:         Optional[date] = None
    trigger_type:     Optional[str]  = None
    payout_type:      Optional[str]  = None
    entity:           Optional[str]  = None
    remark:           Optional[str]  = None
    iata_number:      Optional[str]  = None
    business_type:    Optional[str]  = None
    entity_lcc:       Optional[str]  = None
    login_id:         Optional[str]  = None
    variant:          Optional[str]  = None
    eco_commission:   Optional[str]  = None
    peco_commission:  Optional[str]  = None
    bus_commission:   Optional[str]  = None
    base_type:        Optional[str]  = None
    valid_on:         Optional[str]  = None
    validity_raw:     Optional[str]  = None
    deal_maker_name:  Optional[str]  = None
    # incentives & inclusions/exclusions (stored as JSON)
    incentive_types:  Optional[list] = None
    incentive_data:   Optional[dict] = None
    incl_excl_types:  Optional[list] = None
    incl_excl_data:   Optional[dict] = None
    vice_versa:       Optional[dict] = None
    # metadata
    tenant_id:     Optional[int]
    created_by_id: int
    created_at:    datetime

    model_config = {"from_attributes": True}


class UploadedDealSummary(BaseModel):
    """Light version for list views — no rows."""
    id:            int
    source_type:   UploadedDealSourceType
    source_agent:  str
    issue_date:    Optional[date]
    file_name:     str
    file_type:     str
    status:        UploadedDealStatus
    notes:         Optional[str]
    created_at:    datetime
    row_count:     int = 0
    # contract fields
    airline_type:     Optional[str]  = None
    airline_name:     Optional[str]  = None
    contract_year:    Optional[str]  = None
    valid_from:       Optional[date] = None
    valid_to:         Optional[date] = None
    trigger_type:     Optional[str]  = None
    payout_type:      Optional[str]  = None
    business_type:    Optional[str]  = None
    entity_lcc:       Optional[str]  = None
    remark:           Optional[str]  = None
    deal_maker_name:  Optional[str]  = None
    incentive_types:  Optional[list] = None
    incentive_data:   Optional[dict] = None
    incl_excl_types:  Optional[list] = None
    incl_excl_data:   Optional[dict] = None

    model_config = {"from_attributes": True}


# ── Extraction preview (returned before DB save) ───────────────────────────

class ExtractedRow(BaseModel):
    """Single row returned from the extraction step — no DB IDs yet."""
    row_order:        int        = 0
    airline_name:     str        = ""
    iata_code:        str        = ""
    variant:          str        = ""
    eco_commission:   str        = ""
    peco_commission:  str        = ""
    bus_commission:   str        = ""
    base_type:        str        = ""
    valid_on:         str        = ""
    valid_from:       Optional[str] = None
    valid_to:         Optional[str] = None
    validity_raw:     str        = ""
    remarks:          str        = ""
    # per-row incentive data (each deal row has its own class, %, dates etc.)
    incentive_data:   dict       = {}
    # per-row inclusions / exclusions (set by user in review step)
    incl_excl_types:  list       = []
    incl_excl_data:   dict       = {}
    vice_versa:       dict       = {}


class ExtractionPreview(BaseModel):
    """Returned by POST /deals/upload/extract — data for user review step."""
    source_type:  str
    file_name:    str
    confidence:   float
    warning:      Optional[str] = None
    rows:         list[ExtractedRow] = []
    # Original column headers from the document (as-is, e.g. "AIRLINE", "ECO", "P.ECOM")
    doc_columns:  list[str] = []
    # Raw rows keyed by original column headers (for user-driven mapping lookup)
    raw_rows:     list[dict] = []


class DealRepositoryItem(BaseModel):
    """Unified view of all deal types (upload, airline, b2b) for the repository list."""
    id:               int
    deal_no:          str           # e.g. "AIR-0014", "B2B-0001", "UPL-0005"
    deal_type:        str           # 'upload' | 'airline' | 'b2b'
    source_agent:     str
    airline_type:     Optional[str]  = None
    airline_name:     Optional[str]  = None
    contract_year:    Optional[str]  = None  # null for b2b
    valid_from:       Optional[date] = None
    valid_to:         Optional[date] = None
    trigger_type:     Optional[str]  = None  # null for b2b
    payout_type:      Optional[str]  = None  # null for b2b
    business_type:    Optional[str]  = None
    entity_lcc:       Optional[str]  = None
    remark:           Optional[str]  = None
    deal_maker_name:  Optional[str]  = None
    incentive_types:  Optional[list] = None
    incentive_data:   Optional[dict] = None
    incl_excl_types:  Optional[list] = None
    incl_excl_data:   Optional[dict] = None
    deal_tag:             Optional[str]  = "standard"
    status:               str
    deal_lifecycle_status: Optional[str] = None
    created_at:           datetime
    # upload-table only
    file_type:            Optional[str]  = None  # pdf/excel/word/image/manual


# ── AI Extraction schemas ──────────────────────────────────────────────────────

class DealUpdatePayload(BaseModel):
    airline_type:    Optional[str] = None
    airline_name:    Optional[str] = None
    contract_year:   Optional[str] = None
    valid_from:      Optional[str] = None
    valid_to:        Optional[str] = None
    trigger_type:    Optional[str] = None
    payout_type:     Optional[str] = None
    business_type:   Optional[str] = None
    entity_lcc:      Optional[str] = None
    remark:          Optional[str] = None
    deal_maker_name: Optional[str] = None
    incentive_types: Optional[list] = None
    incentive_data:  Optional[dict] = None
    incl_excl_types: Optional[list] = None
    incl_excl_data:  Optional[dict] = None
    vice_versa:      Optional[dict] = None


class AIDeal(BaseModel):
    airline_type: str = "GDS"
    airline_name: str = ""
    contract_valid_from: Optional[str] = None
    contract_valid_to: Optional[str] = None
    incentive_types: list[str] = ["PLB"]
    incentive_data: dict = {}
    remark: Optional[str] = None


class AIExtractResponse(BaseModel):
    deals: list[AIDeal] = []
    file_name: str
    confidence: float
    warning: Optional[str] = None


class DealBatchRead(BaseModel):
    batch_id:         str
    deal_type:        str
    deal_tag:         str = "standard"
    supplier_name:    Optional[str]
    file_name:        Optional[str]
    file_type:        Optional[str]
    incentive_types:  list[str]
    valid_from:       Optional[date]
    valid_to:         Optional[date]
    deal_count:       int
    lifecycle_counts: dict[str, int] = {}
    created_by_name:  Optional[str]
    created_at:       datetime

    model_config = {"from_attributes": True}


class AIConfirmPayload(BaseModel):
    deals: list[AIDeal]
    batch_id: Optional[str] = None
    deal_tag: Optional[str] = "standard"
    supplier_name: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = "pdf"


class ConfirmUploadPayload(BaseModel):
    """Sent by frontend after user edits/approves the extracted rows.
    Mirrors the manual New Deal form — same fields, different entry path.
    Used for both file-upload flow (source_type=upload) and manual entry (source_type=manual).
    """
    source_type:     str            = "upload"   # "upload" | "manual"
    source_agent:    Optional[str]  = None  # auto-set from filename if omitted
    deal_tag:        Optional[str]  = "standard"  # "standard" | "adhoc"
    issue_date:      Optional[str]  = None   # ISO string "2026-03-18"
    notes:           Optional[str]  = None
    # deal header (same as new deal form)
    airline_type:    Optional[str]  = None   # GDS / LCC
    airline_name:    Optional[str]  = None
    contract_year:   Optional[str]  = None
    valid_from:      Optional[str]  = None
    valid_to:        Optional[str]  = None
    trigger_type:    Optional[str]  = None
    payout_type:     Optional[str]  = None
    entity:          Optional[str]  = None
    remark:          Optional[str]  = None
    # GDS-specific
    iata_number:     Optional[str]  = None
    # LCC-specific
    business_type:   Optional[str]  = None
    entity_lcc:      Optional[str]  = None
    login_id:        Optional[str]  = None
    # deal maker
    deal_maker_name: Optional[str]  = None
    # incentives (same as new deal form)
    incentive_types: list[str]      = []     # ["PLB", "Super PLB"]
    incentive_data:  dict           = {}     # {PLB: {validFrom: ..., frequency: ...}}
    # inclusions / exclusions (same as new deal form)
    incl_excl_types: list[str]      = []     # ["Inclusion For Trigger", ...]
    incl_excl_data:  dict           = {}     # {Inclusion For Trigger: {continents:..., ...}}
    vice_versa:      dict           = {}     # {Inclusion For Trigger: true}
    # column map used during extraction (stored for audit)
    column_map:      dict           = {}     # {our_col: doc_col}
    rows:            list[ExtractedRow] = []
    # toggle: auto-copy incl/excl from previous deal with same airline+supplier+segment
    copy_prev_incl_excl: bool       = True
