from pydantic import BaseModel
from typing import Optional


class AgencyEntityCreate(BaseModel):
    agency_id: int
    name: str
    code: str
    # GDS | LCC | BOTH. Defaults to the agency's own scope when omitted, and
    # must sit inside it — see _validate_scope.
    channels: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    is_active: Optional[bool] = True


class AgencyEntityUpdate(BaseModel):
    agency_id: Optional[int] = None
    name: Optional[str] = None
    code: Optional[str] = None
    channels: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    is_active: Optional[bool] = None


class AgencyEntityRead(BaseModel):
    id: int
    agency_id: int
    agency_name: Optional[str] = None       # resolved from the user's agencies
    name: str
    code: str
    channels: str
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    is_active: bool
    login_id_count: Optional[int] = None    # populated in overview / drill-down queries

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
