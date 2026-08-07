from datetime import datetime
from pydantic import BaseModel, Field, computed_field, field_validator
from typing import Optional


class AirlineCreate(BaseModel):
    name: str
    iata_code: str
    icao_code: Optional[str] = None
    logo_url: Optional[str] = None
    contract_year: Optional[str] = None
    request_type: str = "new"
    target_id: Optional[int] = None


class AirlineUpdate(BaseModel):
    name: Optional[str] = None
    iata_code: Optional[str] = None
    icao_code: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: Optional[bool] = None
    contract_year: Optional[str] = None


class AirlineRead(BaseModel):
    id: int
    name: str
    iata_code: str
    icao_code: Optional[str]
    iata_numeric_code: Optional[str] = None
    logo_url: Optional[str]
    is_active: bool
    contract_year: Optional[str] = None

    model_config = {"from_attributes": True}


class AirlineBulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]


class AirlineSubmitterInfo(BaseModel):
    id: int
    full_name: str
    email: str

    model_config = {"from_attributes": True}


class AirlineApprovalRead(BaseModel):
    id: int
    name: str
    iata_code: str
    icao_code: Optional[str]
    contract_year: Optional[str] = None
    status: str
    submitted_by: AirlineSubmitterInfo
    submitted_at: datetime
    reviewed_at: Optional[datetime]
    rejection_reason: Optional[str]
    request_type: str = "new"
    target_id: Optional[int] = Field(default=None, validation_alias="target_airline_id")

    # ── platform-admin edit state ──────────────────────────────────────────
    original_payload: Optional[dict] = None
    edited_by: Optional[AirlineSubmitterInfo] = None
    edited_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}

    @computed_field
    @property
    def edited(self) -> bool:
        """True only when an admin changed something the submitter should see."""
        return self.original_payload is not None


class AirlineApprovalEdit(BaseModel):
    """What a platform admin may change on a pending airline request.

    Normalisation mirrors what the create endpoint does by hand, and the length
    bounds match the columns (String(3)/(4)/(2)) — the create schema omits them,
    so an oversized value there is a psycopg 500 rather than a 422.
    """
    name:          Optional[str] = Field(default=None, max_length=255)
    iata_code:     Optional[str] = Field(default=None, min_length=2, max_length=3)
    icao_code:     Optional[str] = Field(default=None, max_length=4)
    contract_year: Optional[str] = Field(default=None, max_length=2)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        # The column is NOT NULL, so refuse an explicit blank.
        if v is not None and not v.strip():
            raise ValueError("Airline name cannot be blank.")
        return v.strip() if v else v

    @field_validator("iata_code")
    @classmethod
    def iata_upper(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().upper() if v else v

    @field_validator("icao_code", "contract_year")
    @classmethod
    def upper_or_none(cls, v: Optional[str]) -> Optional[str]:
        return (v.strip().upper() or None) if v else None


class AirlineApprovalAction(BaseModel):
    rejection_reason: Optional[str] = None
