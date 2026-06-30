import re
from pydantic import BaseModel, EmailStr, model_validator
from typing import Optional, Literal
from datetime import datetime
from app.models.user import UserRole
from app.core.email_domains import is_public_domain

# Indian tax identifiers
PAN_RE   = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")                            # 10 chars
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")  # 15 chars


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    role: UserRole = UserRole.VIEWER
    department: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    department: Optional[str] = None


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserRead(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    department: Optional[str]
    is_active: bool
    created_at: datetime
    tenant_id: Optional[int] = None
    tenant_type: Optional[str] = None   # "corporate" | "individual" (derived from tenant)

    model_config = {"from_attributes": True}


# ── Auth payloads ──────────────────────────────────────────────────────────
class SignupPayload(BaseModel):
    account_type: Literal["corporate", "individual"] = "corporate"
    email: EmailStr
    full_name: str
    password: str
    company_name: Optional[str] = None       # corporate: optional company name
    pan_number: Optional[str] = None         # required for individual, optional for corporate
    gst_registered: bool = False
    gst_number: Optional[str] = None         # required iff gst_registered

    @model_validator(mode="after")
    def _validate(self) -> "SignupPayload":
        # normalise tax ids
        if self.pan_number:
            self.pan_number = self.pan_number.strip().upper() or None
        if self.gst_number:
            self.gst_number = self.gst_number.strip().upper() or None

        if self.account_type == "corporate":
            if is_public_domain(self.email):
                raise ValueError(
                    "Corporate signup requires a work email. Public providers "
                    "(Gmail, Yahoo, etc.) are not allowed — choose 'Individual' "
                    "to sign up with a personal email."
                )
            # PAN optional for corporate, but validate format when provided
            if self.pan_number and not PAN_RE.match(self.pan_number):
                raise ValueError("Invalid PAN format. Expected 10 characters, e.g. ABCDE1234F.")
        else:  # individual
            if not self.pan_number:
                raise ValueError("PAN number is required for individual accounts.")
            if not PAN_RE.match(self.pan_number):
                raise ValueError("Invalid PAN format. Expected 10 characters, e.g. ABCDE1234F.")

        # GST applies to both flows
        if self.gst_registered:
            if not self.gst_number:
                raise ValueError("GST number is required when GST registered.")
            if not GSTIN_RE.match(self.gst_number):
                raise ValueError("Invalid GSTIN format. Expected 15 characters, e.g. 22ABCDE1234F1Z5.")
        else:
            self.gst_number = None  # ignore any stray value when not registered

        return self


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class TokenWithUser(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
