from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.models.user import UserRole


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

    model_config = {"from_attributes": True}


# ── Auth payloads ──────────────────────────────────────────────────────────
class SignupPayload(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    company_name: Optional[str] = None   # optional, stored as department


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
