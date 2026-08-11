import re
from pydantic import BaseModel, EmailStr, Field, model_validator
from pydantic.functional_validators import AfterValidator
from typing import Annotated, Optional, Literal
from datetime import datetime
from app.models.user import UserRole
from app.core.email_domains import is_public_domain
from app.core.password_policy import validate_password

# Enforces the shared policy at parse time (422). The two password-management
# endpoints deliberately do NOT use this — they call validate_password inside
# the service so the failure is a 400 with a clean sentence, rather than a 422
# that Pydantic prefixes with "Value error, ".
PasswordStr = Annotated[str, AfterValidator(validate_password)]

# Indian tax identifiers
PAN_RE   = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")                            # 10 chars
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")  # 15 chars


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: PasswordStr
    role: UserRole = UserRole.VIEWER
    department: Optional[str] = None
    # Entities (from the admin's own My Profile → Entities list) this member works
    # on. Optional — a member can be assigned entities later.
    entity_ids: list[int] = []


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    # `password` deliberately absent. It used to be here, but User has no
    # `password` column, so crud.user.update just set a throwaway instance
    # attribute and returned 200 — telling the caller their password had changed
    # when nothing was written or hashed. Password changes go through
    # POST /auth/change-password.


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserEntitiesUpdate(BaseModel):
    """Replace a member's entity assignments with exactly this set."""
    entity_ids: list[int] = []


class UserRead(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    department: Optional[str]
    is_active: bool
    is_verified: bool = False
    onboarding_complete: bool = False
    created_at: datetime
    tenant_id: Optional[int] = None
    tenant_type: Optional[str] = None   # "corporate" | "individual" (derived from tenant)
    # Subscription state of this user's workspace, derived from the tenant. The
    # browser gates the whole dashboard on plan_active; the real enforcement is
    # the 402 in get_current_user. Defaults to True so an endpoint that
    # serializes users without eager-loading the tenant can't render a false
    # "frozen" — see User.plan_active.
    plan_active: bool = True
    plan_status: Optional[str] = None   # "free" | "trial" | "active" | "expired" | "suspended"
    plan_expires_at: Optional[datetime] = None
    # Entities this member is assigned to. Populated by the admin user endpoints;
    # empty elsewhere (e.g. /users/me) since it needs a separate lookup.
    entity_ids: list[int] = []
    entity_names: list[str] = []

    model_config = {"from_attributes": True}


# ── Auth payloads ──────────────────────────────────────────────────────────
class SignupPayload(BaseModel):
    account_type: Literal["corporate", "individual"] = "corporate"
    email: EmailStr
    full_name: str
    password: PasswordStr
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
    # The policy is deliberately NOT applied here. Applying it would lock out
    # every user whose password predates the rule, and would turn login into an
    # oracle telling an attacker which candidate passwords are worth trying. The
    # cap only keeps a megabyte body away from bcrypt.
    password: str = Field(max_length=1024)


class TokenWithUser(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Email verification ──────────────────────────────────────────────────────
class SignupResult(BaseModel):
    """Signup no longer issues a session — the account must be verified first."""
    email: str
    is_verified: bool = False
    message: str


class VerifyEmailPayload(BaseModel):
    token: str


class ResendVerificationPayload(BaseModel):
    email: EmailStr


class SimpleMessage(BaseModel):
    message: str


# ── Password management ─────────────────────────────────────────────────────
# `new_password` is a plain str on both payloads, not PasswordStr: the service
# validates it so a policy failure is a 400 carrying the policy sentence, rather
# than a 422 that Pydantic prefixes with "Value error, ".

class ChangePasswordPayload(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class ForgotPasswordPayload(BaseModel):
    email: EmailStr


class ResetPasswordPayload(BaseModel):
    token: str
    new_password: str = Field(max_length=1024)


class RefreshPayload(BaseModel):
    """Body, not a query param — a token in a URL lands in access logs and Referer."""
    refresh_token: str


# ── Profile (My Profile / onboarding step 1) ────────────────────────────────
class ProfileRead(BaseModel):
    """Combined user + tenant view for the profile screens."""
    id: int
    email: str
    full_name: str
    role: UserRole
    tenant_type: Optional[str] = None
    is_verified: bool = False
    onboarding_complete: bool = False
    company_name: Optional[str] = None   # tenant.name
    pan_number: Optional[str] = None     # tenant.pan_number
    gst_number: Optional[str] = None     # tenant.gst_number


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    company_name: Optional[str] = None
    pan_number: Optional[str] = None
    gst_number: Optional[str] = None

    @model_validator(mode="after")
    def _validate(self) -> "ProfileUpdate":
        if self.pan_number is not None:
            self.pan_number = self.pan_number.strip().upper() or None
            if self.pan_number and not PAN_RE.match(self.pan_number):
                raise ValueError("Invalid PAN format. Expected 10 characters, e.g. ABCDE1234F.")
        if self.gst_number is not None:
            self.gst_number = self.gst_number.strip().upper() or None
            if self.gst_number and not GSTIN_RE.match(self.gst_number):
                raise ValueError("Invalid GSTIN format. Expected 15 characters, e.g. 22ABCDE1234F1Z5.")
        return self
