from datetime import date
from typing import List, Optional

from pydantic import BaseModel

# How the agency pays, and how often. Lower-case, unlike the GDS/LCC channel
# vocabulary in app.models.agency — these predate it and are stored lower-case.
AGENCY_TYPES   = {"cash", "credit"}
BILLING_CYCLES = {"weekly", "fortnightly", "monthly"}


class AgencyTermsInput(BaseModel):
    """One channel's commercial arrangement, as entered on the add form.

    `deposit_amount` is not a terms column — it is the first `topup` on the
    ledger, and a cash agency's limit is derived from the ledger thereafter. It
    is carried here because the person filling the form thinks of it as part of
    the arrangement, and create_agency posts it.
    """
    channel: str                          # GDS | LCC
    agency_type: str                      # cash | credit
    billing_cycle: str                    # weekly | fortnightly | monthly
    credit_limit: Optional[float] = None    # credit only, required then
    deposit_amount: Optional[float] = None  # cash only, required then
    usage_percent: Optional[float] = None   # cash only; may exceed 100 by design


class AgencyTermsSummary(BaseModel):
    """A channel's current arrangement as the list and detail screens read it."""
    channel: str
    agency_type: str
    billing_cycle: str
    credit_limit: Optional[float] = None
    usage_percent: Optional[float] = None
    terms_id: int
    effective_from: date
    cycle_anchor_date: date
    # Money in on this channel under the current terms. Deposits live in the
    # ledger, so this is the only place a cash agency's limit comes from.
    deposit_paid: float = 0


class AgencyBase(BaseModel):
    """Identity only. Terms are per channel and live in AgencyTermsInput."""
    # The branch's postal address. Entities default to it, so filling it once
    # here saves retyping it on every entity under this branch.
    address: Optional[str] = None
    # REQUIRED wherever a human types it, though typed Optional so a PATCH that
    # does not mention it stays a no-op. The handlers enforce it, because state is
    # what a GSTIN's first two characters are checked against — see
    # app.core.india_tax and _validated_tax_ids in api/v1/agencies.py.
    state: Optional[str] = None
    city: Optional[str] = None
    region_chapter: Optional[str] = None
    # Tax ids, in the order the form collects them and the checks need them:
    # PAN fixes characters 3-12 of the GSTIN, state fixes 1-2. `gst_number` is
    # stored ONLY when `gst_registered` — an unregistered agency has no GSTIN, and
    # sending one alongside gst_registered=false clears it rather than saving it.
    gst_registered: Optional[bool] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = True


class AgencyCreate(AgencyBase):
    name: str
    # Which branch of this vendor. `branch_code` is copied from suppliers.code and
    # is part of the uniqueness key, so two branches of one vendor can coexist;
    # it falls back to "MAIN" for an agency typed in by hand.
    supplier_id: Optional[int] = None
    branch_code: Optional[str] = None
    branch_name: Optional[str] = None
    # GDS or LCC — never BOTH on a create. An agency that works both channels is
    # onboarded twice, so each channel gets its own terms, deposit, ledger and row.
    channels: str
    # Exactly one entry, for the declared channel — enforced in create_agency,
    # because an agency without a complete arrangement is the state that produced
    # three separate bugs in the version this replaces.
    terms: List[AgencyTermsInput]


class AgencyUpdate(AgencyBase):
    """Identity only, deliberately.

    Terms move through POST /agencies/{id}/switch and /channels/open|close, and
    `channels` / `branch_code` with them: adding a channel opens a commercial
    arrangement, removing one has to close it at a settled balance, and changing
    a branch would rewrite which account a ticket belongs to. None of that is a
    field edit.

    The three refused fields ARE declared, and that is the point. Pydantic drops
    unknown keys, so leaving them out would make a PATCH carrying `channels`
    return 200 with the change silently discarded — the caller believes it worked.
    Declaring them lets update_agency answer 409 naming the endpoint to use
    instead. `agency_type` is here because it was a real column until recently and
    older clients still send it.
    """
    name: Optional[str] = None
    channels: Optional[str] = None       # refused — see update_agency
    branch_code: Optional[str] = None    # refused
    agency_type: Optional[str] = None    # refused; no longer a column at all


class AgencyRead(AgencyBase):
    id: int
    name: str
    supplier_id: Optional[int] = None
    branch_code: str
    branch_name: Optional[str] = None
    channels: str
    # Non-optional on the way out, unlike on AgencyBase — every stored row has an
    # answer, so a screen can show "Unregistered" rather than an empty GST cell.
    gst_registered: bool = False
    is_active: bool
    # The current arrangement per channel — 0 entries for an agency whose terms
    # were all closed, 1 or 2 otherwise.
    terms: List[AgencyTermsSummary] = []

    model_config = {"from_attributes": True}


class AgencyOverviewRow(BaseModel):
    id: int
    name: str
    branch_name: Optional[str] = None
    channels: str
    entity_count: int
    login_id_count: int


class AgencyFromSuppliers(BaseModel):
    """Bulk-onboard several supplier branches on identical terms.

    `channels` + `terms` are required for the same reason as on AgencyCreate —
    you cannot onboard forty agencies without saying how they pay. Each created
    agency gets its own branch fields from the supplier row it came from.

    STATE, PAN AND GST ARE NOT SET HERE and cannot be. The supplier master holds
    `region_chapter` ("WESTERN REGION"), which is an IATA chapter rather than a
    state, and its gst/pan columns are empty across the whole file. So agencies
    created this way land without the three fields the Add Agency form insists on,
    and have to be edited afterwards — one form cannot honestly collect a
    different state for each of forty vendors.
    """
    supplier_ids: List[int]
    channels: str                          # GDS | LCC — never BOTH, as on AgencyCreate
    terms: List[AgencyTermsInput]


class AgencyFromSuppliersResult(BaseModel):
    created: int
    skipped: int
    agencies: List[AgencyRead]


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
