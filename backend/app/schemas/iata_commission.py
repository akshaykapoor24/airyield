from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, computed_field, field_validator
from typing import Optional


class IataCommissionCreate(BaseModel):
    airline_name: str
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    iata_commission_pct: Optional[float] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: Optional[bool] = True
    # Same submit-for-approval contract as the other System Masters: a tenant
    # user either proposes a brand-new row or an update to an existing one.
    request_type: str = "new"
    target_id: Optional[int] = None


class IataCommissionUpdate(BaseModel):
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    iata_commission_pct: Optional[float] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: Optional[bool] = None


class IataCommissionRead(BaseModel):
    id: int
    airline_name: str
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    iata_commission_pct: Optional[float] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: bool

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]


# ── approval queue ─────────────────────────────────────────────────────────

class IataCommissionSubmitterInfo(BaseModel):
    id: int
    full_name: str
    email: str

    model_config = {"from_attributes": True}


class IataCommissionApprovalRead(BaseModel):
    id: int
    airline_name: str
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    iata_commission_pct: Optional[float] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    status: str
    submitted_by: IataCommissionSubmitterInfo
    submitted_at: datetime
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    request_type: str = "new"
    target_id: Optional[int] = Field(default=None, validation_alias="target_iata_commission_id")

    # ── platform-admin edit state ──────────────────────────────────────────
    original_payload: Optional[dict] = None
    edited_by: Optional[IataCommissionSubmitterInfo] = None
    edited_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}

    @computed_field
    @property
    def edited(self) -> bool:
        """True only when an admin changed something the submitter should see."""
        return self.original_payload is not None


class IataCommissionApprovalEdit(BaseModel):
    """What a platform admin may change on a pending IATA commission request.

    Length bounds match the columns (String(255)/(20)/(10)) so an oversized
    value is a 422 rather than a psycopg 500. `iata_commission_pct` arrives as
    a Decimal so it compares cleanly against the Numeric column — a float would
    make 0.7 differ from Decimal("0.70") and stamp a spurious admin edit.
    """
    airline_name:        Optional[str] = Field(default=None, max_length=255)
    airline_code:        Optional[str] = Field(default=None, max_length=20)
    iata_numeric_code:   Optional[str] = Field(default=None, max_length=10)
    iata_commission_pct: Optional[Decimal] = None
    valid_from:          Optional[date] = None
    valid_to:            Optional[date] = None

    @field_validator("airline_name")
    @classmethod
    def airline_name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        # The column is NOT NULL, so refuse an explicit blank.
        if v is not None and not v.strip():
            raise ValueError("Airline name cannot be blank.")
        return v.strip() if v else v

    @field_validator("airline_code", "iata_numeric_code")
    @classmethod
    def blank_to_none(cls, v: Optional[str]) -> Optional[str]:
        return (v.strip() or None) if v else None

    @field_validator("iata_commission_pct", mode="before")
    @classmethod
    def pct_via_str(cls, v):
        # Decimal(0.7) is 0.6999…; Decimal("0.7") is exact and equals the
        # Decimal("0.70") the column round-trips.
        return Decimal(str(v)) if isinstance(v, float) else v


class IataCommissionApprovalAction(BaseModel):
    rejection_reason: Optional[str] = None
