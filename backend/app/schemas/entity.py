from pydantic import BaseModel
from typing import Optional


class EntityCreate(BaseModel):
    name: str
    code: str
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    is_active: Optional[bool] = True


class EntityUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    is_active: Optional[bool] = None


class EntityRead(BaseModel):
    id: int
    name: str
    code: str
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
