from __future__ import annotations
from pydantic import BaseModel, model_validator
from typing import Literal, Optional
from datetime import date, datetime


# ── Outgoing-deal scope ────────────────────────────────────────────────────

DealScopeLiteral = Literal["agency", "corporate", "all"]


class DealScopeFields(BaseModel):
    """WHO an outgoing deal is for. Mixed into every payload that writes a deal.

    Inbound deals never send these — the endpoint forces `all`, because income
    received from an airline has no customer.

    The Literal is load-bearing: an unrecognised scope becomes a field-level 422
    here rather than reaching the database and surfacing as a 500 from
    ck_deals_scope_type.
    """
    scope_type:       Optional[DealScopeLiteral] = None
    agency_id:        Optional[int] = None
    corporate_id:     Optional[int] = None
    agency_entity_id: Optional[int] = None

    @model_validator(mode="after")
    def _check_scope(self):
        # None = "not sent" (a PATCH that leaves the scope alone). Only validate
        # the pairing when the caller actually named a scope.
        if self.scope_type is None:
            return self
        if self.scope_type == "agency" and self.agency_id is None:
            raise ValueError("scope_type 'agency' requires agency_id")
        if self.scope_type != "agency" and self.agency_id is not None:
            raise ValueError("agency_id is only allowed when scope_type is 'agency'")
        if self.scope_type == "corporate" and self.corporate_id is None:
            raise ValueError("scope_type 'corporate' requires corporate_id")
        if self.scope_type != "corporate" and self.corporate_id is not None:
            raise ValueError("corporate_id is only allowed when scope_type is 'corporate'")
        if self.agency_entity_id is not None and self.scope_type != "agency":
            raise ValueError("agency_entity_id is only allowed when scope_type is 'agency'")
        return self


# ── Extraction preview (returned before DB save) ───────────────────────────

class ExtractedRow(BaseModel):
    """Single row returned from the extraction step — no DB IDs yet."""
    row_order:        int        = 0
    airline_name:     str        = ""
    iata_code:        str        = ""
    # The CARRIER designator (AI, VS, 6E) used to resolve — and if absent, to
    # create — the airline master row. Transport only: it is never written to the
    # deal. `iata_code` above is a different thing entirely; confirm_upload maps
    # that one onto Deal.iata_number, the agency's IATA number.
    airline_code:     Optional[str] = None
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
    # Outgoing-deal scope. `scope_party_name` is the snapshot taken at save time,
    # so the row still reads correctly after the agency or corporate is renamed.
    scope_type:           Optional[str]  = "all"
    agency_id:            Optional[int]  = None
    corporate_id:         Optional[int]  = None
    agency_entity_id:     Optional[int]  = None
    scope_party_name:     Optional[str]  = None
    status:               str
    deal_lifecycle_status: Optional[str] = None
    created_at:           datetime
    # upload-table only
    file_type:            Optional[str]  = None  # pdf/excel/word/image/manual
    # grouping/context fields (statement-wise + agency-wise repository views)
    batch_id:             Optional[str]  = None
    supplier_name:        Optional[str]  = None


# ── AI Extraction schemas ──────────────────────────────────────────────────────

class DealUpdatePayload(DealScopeFields):
    # NOTE: `direction` and `deal_tag` are deliberately NOT accepted here. Both are
    # fixed at creation by the repository the deal was made in, and a PATCH that
    # could flip `direction` would move a deal between the Incoming and Outgoing
    # repositories — and, worse, make a floated deal start matching your own
    # tickets as income. The Create Deal form sends both on edit; Pydantic drops
    # them, which is the intended behaviour.
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
    # ── Airline-master resolution ────────────────────────────────────────────
    # All four are TRANSPORT ONLY — none is persisted on the deal. The code
    # travels extract -> review -> confirm because `airlines.iata_code` is NOT
    # NULL UNIQUE, so it is the only way confirm can create a missing master row.
    # It must never be confused with `Deal.iata_number`, the AGENCY IATA number.
    airline_code: Optional[str] = None
    # resolved | new | conflict | multi_carrier | ambiguous | unresolved
    airline_status: Optional[str] = None
    airline_master_name: Optional[str] = None
    airline_note: Optional[str] = None
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
    # {resolved: 177, conflict: 12, new: 12, ...} — counted over DISTINCT
    # (name, code) pairs, not deal rows, so it reads as "12 airlines" and not
    # "36 rows". Drives the review-table banner.
    airline_summary: dict[str, int] = {}


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


class ConfirmUploadPayload(DealScopeFields):
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
    # The structured form of `login_id` (which is only a ", "-joined display copy).
    # The upload path never sent this, so the repository's Login IDs column was
    # permanently blank for uploaded deals; the outgoing form now selects real
    # credentials, so it has something true to carry.
    login_ids:       Optional[list] = None
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
