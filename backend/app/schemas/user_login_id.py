from pydantic import BaseModel
from typing import Optional


class UserLoginIdCreate(BaseModel):
    login_id: str
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    entity_id: Optional[int] = None     # one of the user's own entities
    is_active: Optional[bool] = True


class UserLoginIdUpdate(BaseModel):
    login_id: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    entity_id: Optional[int] = None
    is_active: Optional[bool] = None


class UserLoginIdRead(BaseModel):
    id: int
    login_id: str
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    vendor_name: Optional[str] = None   # resolved from the suppliers master
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None   # resolved from the user's own entities
    entity_code: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
