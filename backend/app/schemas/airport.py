from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


class AirportCreate(BaseModel):
    iata_code:         str
    country:           str
    categorization:    Optional[str] = None
    continent:         Optional[str] = None
    city_airport_name: str
    request_type:      str = "new"
    target_id:         Optional[int] = None

    @field_validator("iata_code")
    @classmethod
    def iata_upper(cls, v: str) -> str:
        return v.strip().upper()


class AirportUpdate(BaseModel):
    country:           Optional[str] = None
    categorization:    Optional[str] = None
    continent:         Optional[str] = None
    city_airport_name: Optional[str] = None
    is_active:         Optional[bool] = None


class AirportRead(BaseModel):
    id:               int
    apt_id:           Optional[str]
    iata_code:        str
    country:          str
    categorization:   Optional[str]
    continent:        Optional[str]
    city_airport_name:str
    is_active:        bool
    created_at:       datetime

    model_config = {"from_attributes": True}


# ── Approval schemas ───────────────────────────────────────────────────────

class AirportApprovalCreate(BaseModel):
    iata_code:         str
    country:           str
    categorization:    Optional[str] = None
    continent:         Optional[str] = None
    city_airport_name: str

    @field_validator("iata_code")
    @classmethod
    def iata_upper(cls, v: str) -> str:
        return v.strip().upper()


class SubmitterInfo(BaseModel):
    id:        int
    full_name: str
    email:     str
    model_config = {"from_attributes": True}


class AirportApprovalRead(BaseModel):
    id:               int
    iata_code:        str
    country:          str
    categorization:   Optional[str]
    continent:        Optional[str]
    city_airport_name:str
    status:           str
    submitted_by:     SubmitterInfo
    submitted_at:     datetime
    reviewed_at:      Optional[datetime]
    rejection_reason: Optional[str]
    request_type:     str = "new"
    target_id:        Optional[int] = Field(default=None, validation_alias="target_airport_id")

    model_config = {"from_attributes": True, "populate_by_name": True}


class ApprovalAction(BaseModel):
    rejection_reason: Optional[str] = None


class BulkUploadResult(BaseModel):
    total:    int
    success:  int
    failed:   int
    errors:   list[str] = []
