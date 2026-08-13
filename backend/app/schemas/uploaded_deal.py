from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


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
    iata_commission:  Optional[str] = None   # IATA commission % (contract-level, per row)
    base_type:        str        = ""
    valid_on:         str        = ""
    valid_from:       Optional[str] = None
    valid_to:         Optional[str] = None
    validity_raw:     str        = ""
    remarks:          str        = ""
    # Per-row deal-header fields. Used by the multi-tab workbook upload, where every
    # deal (joined by "Deal No" across sheets) carries its own header. All default to
    # None so the single-sheet / AI / manual paths fall back to the deal-level payload.
    incentive_types:  list       = []
    airline_type:     Optional[str] = None
    business_type:    Optional[str] = None
    entity_lcc:       Optional[str] = None
    login_id:         Optional[str] = None
    deal_maker_name:  Optional[str] = None
    supplier_name:    Optional[str] = None
    contract_year:    Optional[str] = None
    trigger_type:     Optional[str] = None
    payout_type:      Optional[str] = None
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
    entity:           Optional[str]  = None  # agency / user-master entity (B2B Standard)
    entity_lcc:       Optional[str]  = None
    login_id:         Optional[str]  = None  # joined display string
    login_ids:        Optional[list] = None
    remark:           Optional[str]  = None
    deal_maker_name:  Optional[str]  = None
    incentive_types:  Optional[list] = None
    incentive_data:   Optional[dict] = None
    incl_excl_types:  Optional[list] = None
    incl_excl_data:   Optional[dict] = None
    deal_tag:             Optional[str]  = "standard"
    direction:            Optional[str]  = "inbound"   # 'inbound' (received) | 'outbound' (floated)
    status:               str
    deal_lifecycle_status: Optional[str] = None
    created_at:           datetime
    # upload-table only
    file_type:            Optional[str]  = None  # pdf/excel/word/image/manual
    # grouping/context fields (statement-wise + agency-wise repository views)
    batch_id:             Optional[str]  = None
    supplier_name:        Optional[str]  = None


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
    # Header fields needed for a full edit round-trip from the Create Deal form.
    entity:          Optional[str] = None
    login_id:        Optional[str] = None
    login_ids:       Optional[list] = None
    iata_number:     Optional[str] = None
    iata_commission: Optional[str] = None
    supplier_name:   Optional[str] = None
    incentive_types: Optional[list] = None
    incentive_data:  Optional[dict] = None
    incl_excl_types: Optional[list] = None
    incl_excl_data:  Optional[dict] = None
    vice_versa:      Optional[dict] = None


class AIDeal(BaseModel):
    airline_type: str = "GDS"
    airline_name: str = ""
    # The extraction prompt has always asked for this and the review table has
    # always had a column for it, but the field was missing here — so Pydantic
    # dropped it on every AI upload and the column arrived blank.
    iata_commission: Optional[float] = None
    contract_valid_from: Optional[str] = None
    contract_valid_to: Optional[str] = None
    incentive_types: list[str] = ["PLB"]
    incentive_data: dict = {}
    remark: Optional[str] = None
    # Provenance — which physical table row this deal came from. Feeds the
    # read-only Source column, the only practical way to spot-check a 350-row
    # extraction against the printed PDF.
    src_n: Optional[int] = None
    src_page: Optional[int] = None
    src_text: Optional[str] = None
    # Set when a row survived every retry without yielding usable cells. It
    # still occupies a review row so the user can fill it in by hand: a source
    # row must never vanish silently.
    needs_manual: bool = False


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
    file_url:         Optional[str] = None
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
    direction:       str            = "inbound"   # "inbound" (received) | "outbound" (floated to a sub-agency)
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
    iata_commission: Optional[str]  = None   # IATA commission % (deal-level fallback)
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
