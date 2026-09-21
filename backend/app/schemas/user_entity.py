from pydantic import BaseModel, model_validator
from typing import Optional

# Same normalisation the signup flow and Agency Master use — app.core.india_tax is the one
# definition, so the three paths cannot disagree about what a PAN or GSTIN looks like.
from app.core.india_tax import normalise as _norm

# VALIDATION IS NOT HERE, deliberately. State, PAN and GSTIN are required and checked
# against each other in api/v1/user_entities.py::entity_problem, because the bulk paths
# ("+ Add another", XLS) must attribute a bad value to ONE row and still save the others —
# a schema-level raise would reject the whole list before the handler runs. These schemas
# only normalise.


class UserEntityCreate(BaseModel):
    name: str
    code: str
    address: Optional[str] = None
    # Required, but typed Optional so a missing one reaches entity_problem and is reported
    # against its row rather than failing the request as a 422.
    state: Optional[str] = None
    city: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    is_active: Optional[bool] = True

    @model_validator(mode="after")
    def _normalise(self) -> "UserEntityCreate":
        self.gst_number = _norm(self.gst_number)
        self.pan_number = _norm(self.pan_number)
        return self


class UserEntityUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def _normalise(self) -> "UserEntityUpdate":
        # Only touch what was actually sent, so a PATCH that omits them is a no-op.
        fields = self.model_fields_set
        if "gst_number" in fields:
            self.gst_number = _norm(self.gst_number)
        if "pan_number" in fields:
            self.pan_number = _norm(self.pan_number)
        return self


class UserEntityRead(BaseModel):
    id: int
    name: str
    code: str
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class UserEntityBulkCreate(BaseModel):
    """Several entities added in one go from the Add Entity form's '+ Add another'."""
    entities: list[UserEntityCreate]


class BulkCreateResult(BaseModel):
    """Per-row outcome of a bulk create — valid rows are saved even when others fail."""
    total: int
    success: int
    failed: int
    errors: list[str]
    created: list[UserEntityRead] = []


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
