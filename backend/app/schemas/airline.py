from datetime import datetime
from pydantic import BaseModel, Field
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

    model_config = {"from_attributes": True, "populate_by_name": True}


class AirlineApprovalAction(BaseModel):
    rejection_reason: Optional[str] = None
