from pydantic import BaseModel
from typing import Optional


class SupplierCreate(BaseModel):
    name: str
    code: str
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class SupplierRead(BaseModel):
    id: int
    name: str
    code: str
    contact_email: Optional[str]
    contact_phone: Optional[str]
    is_active: bool

    model_config = {"from_attributes": True}
