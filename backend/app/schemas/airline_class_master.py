from pydantic import BaseModel, Field, computed_field, field_validator
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

    # ── platform-admin edit state ──────────────────────────────────────────
    original_payload: Optional[dict] = None
    edited_by: Optional[ClassSubmitterInfo] = None
    edited_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}

    @computed_field
    @property
    def edited(self) -> bool:
        """True only when an admin changed something the submitter should see."""
        return self.original_payload is not None


class ClassApprovalEdit(BaseModel):
    """What a platform admin may change on a pending class/RBD request.

    The three identifying columns are NOT NULL, so an explicit blank is refused
    rather than written. Values are upper-cased to match _normalize_value_payload
    on the create path.
    """
    airline_name: Optional[str] = Field(default=None, max_length=255)
    class_type:   Optional[str] = Field(default=None, max_length=50)
    class_code:   Optional[str] = Field(default=None, max_length=10)
    airline_type: Optional[str] = Field(default=None, max_length=20)
    class_note:   Optional[str] = None

    @field_validator("airline_name", "class_type", "class_code")
    @classmethod
    def required_upper(cls, v: Optional[str], info) -> Optional[str]:
        if v is None:
            return v
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError(f"{info.field_name.replace('_', ' ').title()} cannot be blank.")
        return cleaned

    @field_validator("airline_type")
    @classmethod
    def optional_upper(cls, v: Optional[str]) -> Optional[str]:
        return (v.strip().upper() or None) if v else None

    @field_validator("class_note")
    @classmethod
    def note_or_none(cls, v: Optional[str]) -> Optional[str]:
        return (v.strip() or None) if v else None


class ClassApprovalAction(BaseModel):
    rejection_reason: Optional[str] = None

