from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AirlineClassMasterCreate(BaseModel):
    airline_name: str
    class_type: str
    class_code: str
    airline_type: Optional[str] = None
    class_note: Optional[str] = None
    is_active: Optional[bool] = True
    request_type: str = "new"
    target_id: Optional[int] = None


class AirlineClassMasterUpdate(BaseModel):
    airline_name: Optional[str] = None
    class_type: Optional[str] = None
    class_code: Optional[str] = None
    airline_type: Optional[str] = None
    class_note: Optional[str] = None
    is_active: Optional[bool] = None


class AirlineClassMasterRead(BaseModel):
    id: int
    airline_name: str
    class_type: str
    class_code: str
    airline_type: Optional[str]
    class_note: Optional[str]
    is_active: bool

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]


class ClassSubmitterInfo(BaseModel):
    id: int
    full_name: str
    email: str

    model_config = {"from_attributes": True}


class ClassApprovalRead(BaseModel):
    id: int
    airline_name: str
    class_type: str
    class_code: str
    airline_type: Optional[str]
    class_note: Optional[str]
    status: str
    submitted_by: ClassSubmitterInfo
    submitted_at: datetime
    reviewed_at: Optional[datetime]
    rejection_reason: Optional[str]
    request_type: str = "new"
    target_id: Optional[int] = Field(default=None, validation_alias="target_class_id")

    model_config = {"from_attributes": True, "populate_by_name": True}


class ClassApprovalAction(BaseModel):
    rejection_reason: Optional[str] = None

