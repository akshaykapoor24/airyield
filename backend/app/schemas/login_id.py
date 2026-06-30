from pydantic import BaseModel
from typing import Optional


class LoginIdCreate(BaseModel):
    login_id: str
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    is_active: Optional[bool] = True


class LoginIdUpdate(BaseModel):
    login_id: Optional[str] = None
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    is_active: Optional[bool] = None


class LoginIdRead(BaseModel):
    id: int
    login_id: str
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    lob: Optional[str] = None
    vendor_id: Optional[int] = None
    vendor_name: Optional[str] = None   # resolved from the suppliers master
    is_active: bool

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
