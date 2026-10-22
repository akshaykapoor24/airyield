from typing import Optional

from pydantic import BaseModel, Field, field_validator


# The deal form's Business Type list (frontend deals/new/page.tsx BUSINESS_TYPES).
# An airline id is an agent login opened for one of these lines of business.
BUSINESS_TYPES = ("B2B", "B2C", "B2E", "MICE")


def normalize_business_type(value: Optional[str]) -> Optional[str]:
    """The canonical spelling of a business type, or None when blank.

    Case- and padding-blind, so a sheet saying " b2c " imports as "B2C". Anything
    outside BUSINESS_TYPES raises ValueError, which pydantic reports as a 422.
    """
    v = (value or "").strip().upper()
    if not v:
        return None
    if v not in BUSINESS_TYPES:
        raise ValueError(f"Business type must be one of {', '.join(BUSINESS_TYPES)}.")
    return v


def _required_business_type(value: Optional[str]) -> str:
    v = normalize_business_type(value)
    if v is None:
        raise ValueError(f"Pick a business type for this id — {', '.join(BUSINESS_TYPES)}.")
    return v


class TenantAirlineCreate(BaseModel):
    airline_id: int
    ref_id: str = Field(min_length=1, max_length=100)
    business_type: str
    is_active: Optional[bool] = True

    _business_type = field_validator("business_type", mode="before")(_required_business_type)


class TenantAirlineUpdate(BaseModel):
    # Changing airline_id re-snapshots name/code/numeric/contract year from the master.
    airline_id: Optional[int] = None
    ref_id: Optional[str] = Field(default=None, max_length=100)
    # Settable on ids saved before the type was asked for; never cleared once set.
    business_type: Optional[str] = None
    is_active: Optional[bool] = None

    _business_type = field_validator("business_type", mode="before")(_required_business_type)


class TenantAirlineRead(BaseModel):
    id: int
    airline_id: int
    ref_id: str
    business_type: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    contract_year: Optional[str] = None
    is_active: bool
    # The master's current name, when it has drifted from the snapshot taken at add time.
    live_airline_name: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Airline Master screen: the platform master with this tenant's ids on it ──
# See services/tenant_airline_catalog.py for why this is a live view rather than
# a per-tenant copy of the airline master.

class TenantAirlineIdRead(BaseModel):
    """One id the tenant holds for an airline. A tenant normally has several."""
    id: int
    ref_id: str
    # None on ids added before the business type was asked for.
    business_type: Optional[str] = None
    is_active: bool
    # Number of LCC batches uploaded against this id; delete is refused above zero.
    in_use_count: int = 0
    # The master has been renamed since this id was added, so the snapshot on the
    # statements it stamped no longer matches what the master says today.
    snapshot_name_drifted: bool = False


class TenantAirlineCatalogEntry(BaseModel):
    """One platform airline, with the tenant's ids for it (possibly none)."""
    airline_id: int
    name: str
    iata_code: str
    iata_numeric_code: Optional[str] = None
    contract_year: Optional[str] = None
    master_is_active: bool = True
    ids: list[TenantAirlineIdRead] = []
    id_count: int = 0
    active_id_count: int = 0


class TenantAirlineCatalogPage(BaseModel):
    items: list[TenantAirlineCatalogEntry]
    total: int
    # Counts for the scope tabs, so the UI does not need a second round trip:
    # airlines this tenant has at least one id for, and the whole master.
    mine_count: int
    all_count: int


# ── Adding several ids for one airline in a single save ──────────────────────

class TenantAirlineIdInput(BaseModel):
    ref_id: str = Field(min_length=1, max_length=100)
    business_type: str
    is_active: Optional[bool] = True

    _business_type = field_validator("business_type", mode="before")(_required_business_type)


class TenantAirlineBulkCreate(BaseModel):
    airline_id: int
    ids: list[TenantAirlineIdInput] = Field(min_length=1)


class TenantAirlineBulkError(BaseModel):
    ref_id: str
    error: str


class TenantAirlineBulkResult(BaseModel):
    """Partial success is normal here — one duplicate id should not throw away the
    other four the user typed, so failures come back per id to be corrected."""
    created: list[TenantAirlineRead] = []
    errors: list[TenantAirlineBulkError] = []


class TenantAirlineBulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
