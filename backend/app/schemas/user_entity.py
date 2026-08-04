import re
from pydantic import BaseModel, model_validator
from typing import Optional

# Same formats the signup flow enforces (app/schemas/user.py) — an entity's tax
# ids are validated identically so the two paths can never disagree.
PAN_RE   = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")                            # 10 chars
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")   # 15 chars


def _norm(v: Optional[str]) -> Optional[str]:
    return (v or "").strip().upper() or None


def tax_id_error(gst: Optional[str], pan: Optional[str]) -> Optional[str]:
    """Return a readable problem with these tax ids, or None if they are fine.

    Deliberately NOT a pydantic validator: bulk create needs to attribute a bad
    value to one row and still save the others, which a schema-level raise makes
    impossible (pydantic rejects the whole list before the handler runs).
    Both fields are optional.
    """
    if gst and not GSTIN_RE.match(gst):
        return f"Invalid GSTIN '{gst}' — expected 15 characters, e.g. 22ABCDE1234F1Z5."
    if pan and not PAN_RE.match(pan):
        return f"Invalid PAN '{pan}' — expected 10 characters, e.g. ABCDE1234F."
    return None


class UserEntityCreate(BaseModel):
    name: str
    code: str
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    is_active: Optional[bool] = True

    @model_validator(mode="after")
    def _normalise(self) -> "UserEntityCreate":
        # Normalise only — format checking happens in the endpoint so the error
        # can name the row it came from.
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
        # Only touch what was actually sent, so a PATCH that omits them is a no-op
        # and one that clears them ("") still stores NULL.
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
