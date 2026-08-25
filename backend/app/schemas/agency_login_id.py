from pydantic import BaseModel
from typing import Optional


class AgencyLoginIdCreate(BaseModel):
    agency_id: int
    # GDS | LCC, never BOTH. `login_id` then holds the mirror ID (GDS) or the
    # portal login / airline ID (LCC) — one column, relabelled per channel.
    channel: str
    login_id: str
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    entity_id: Optional[int] = None     # one of the chosen agency's entities
    is_active: Optional[bool] = True


class AgencyLoginIdUpdate(BaseModel):
    agency_id: Optional[int] = None
    channel: Optional[str] = None
    login_id: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    entity_id: Optional[int] = None
    is_active: Optional[bool] = None


class AgencyLoginIdRead(BaseModel):
    id: int
    channel: str
    login_id: str
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    vendor_name: Optional[str] = None   # resolved from the suppliers master
    agency_id: int
    agency_name: Optional[str] = None   # resolved from the user's agencies
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None   # resolved from the agency's entities
    entity_code: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
