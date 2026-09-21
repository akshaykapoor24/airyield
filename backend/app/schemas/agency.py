from datetime import date
from typing import List, Optional

from pydantic import BaseModel, field_validator

from app.services.service_fee import GST_TREATMENTS, SERVICE_FEE_TYPES

# How the agency pays, and how often. Lower-case, unlike the GDS/LCC channel
# vocabulary in app.models.agency — these predate it and are stored lower-case.
AGENCY_TYPES   = {"cash", "credit"}
BILLING_CYCLES = {"weekly", "fortnightly", "monthly"}


def _one_of(value: Optional[str], allowed, label: str) -> Optional[str]:
    """Normalise a choice column to its canonical lowercase slug, or 422.

    RAISES RATHER THAN COERCING, unlike `_norm_choice` in api/v1/customers.py. That
    one serves a spreadsheet import, where "a miss here is a blank the user fills in
    at review, never a wrong value that gets saved". These four fields come from
    <select> boxes, so an unrecognised value is a client bug rather than a typo, and
    silently blanking it would drop a rate somebody believes they just saved. Same
    call, and the same helper, as schemas/gst_configuration.py.
    """
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    if v not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(sorted(allowed))}")
    return v


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
    # ── Service charge / service fee, one triple per DIRECTION ────────────────
    # An agency is a vendor on the Vendors data screens and a customer on the
    # Customer data ones, and the same money means opposite things there: what they
    # charge us is a COST, what we charge them is INCOME. See models/agency.py and
    # services/service_fee.py — the rate we pay Lords is not the rate we charge
    # Lords, so neither field may stand in for the other.
    #
    # Declared on the BASE so create, update AND read all carry them: unlike
    # `channels` or the terms, a fee rate IS an ordinary field edit (it opens no
    # commercial period and settles no balance), so PATCH accepts it.
    vendor_service_charge_type: Optional[str] = None      # percentage | fixed
    vendor_service_charge_value: Optional[float] = None
    vendor_service_charge_gst: Optional[str] = None       # inclusive | exclusive

    customer_service_fee_type: Optional[str] = None       # percentage | fixed
    customer_service_fee_value: Optional[float] = None
    customer_service_fee_gst: Optional[str] = None        # inclusive | exclusive

    is_active: Optional[bool] = True

    @field_validator("vendor_service_charge_type", "customer_service_fee_type")
    @classmethod
    def _fee_type(cls, v):
        return _one_of(v, SERVICE_FEE_TYPES, "service charge/fee type")

    @field_validator("vendor_service_charge_gst", "customer_service_fee_gst")
    @classmethod
    def _fee_gst(cls, v):
        return _one_of(v, GST_TREATMENTS, "GST treatment")

    @field_validator("vendor_service_charge_value", "customer_service_fee_value")
    @classmethod
    def _fee_value(cls, v):
        """Non-negative, and that is the only bound.

        A negative service charge is a discount wearing the wrong name, and neither
        side of the business would read it as one. Deliberately NOT capped at 100 for
        a percentage: `markup_value`, the closest thing this schema already has, is
        uncapped, and `agency_terms.usage_percent` documents that a percentage here
        "may exceed 100 by design". Inventing a ceiling nobody asked for would refuse
        a real arrangement at the form.
        """
        if v is not None and v < 0:
            raise ValueError("Service charge/fee cannot be negative.")
        return v


class AgencyCreate(AgencyBase):
    name: str
    # Which branch of this vendor. `branch_code` is copied from suppliers.code and
    # is part of the uniqueness key, so two branches of one vendor can coexist;
    # it falls back to "MAIN" for an agency typed in by hand.
    supplier_id: Optional[int] = None
    branch_code: Optional[str] = None
    branch_name: Optional[str] = None
    # Typed in rather than picked from the master: file a supplier-master request
    # so the platform admin can add the vendor for everybody. Ignored when
    # `supplier_id` is set — that agency is already in the master.
    request_master_entry: Optional[bool] = False
    # Reuse a request that already exists instead of filing a second one. Set when
    # the same vendor is onboarded on its other channel: one vendor, one request,
    # two agency rows sharing it.
    supplier_request_id: Optional[int] = None
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
    # Where this agency stands with the shared supplier master.
    #   supplier_id set                    → it is in the master
    #   status "pending"                   → typed in, waiting on the platform admin
    #   status "rejected" + reason         → declined; the agency still works, and
    #                                        can be corrected and resubmitted
    #   both None                          → typed in before this existed, or via
    #                                        XLS; offered a "Request master entry"
    supplier_request_id: Optional[int] = None
    supplier_request_status: Optional[str] = None
    supplier_request_reason: Optional[str] = None
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
