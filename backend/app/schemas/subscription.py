from datetime import datetime
from typing import Optional

from pydantic import BaseModel, model_validator

from app.models.tenant import PlanStatus, TenantType


class TenantPlanRead(BaseModel):
    """One workspace as the platform admin sees it in /admin/subscriptions."""
    id: int
    name: Optional[str] = None
    domain: Optional[str] = None
    tenant_type: TenantType
    plan_status: PlanStatus
    plan_expires_at: Optional[datetime] = None
    plan_activated_at: Optional[datetime] = None
    plan_note: Optional[str] = None
    created_at: datetime
    # Derived, so the console can show "active but lapsed" without repeating the
    # expiry arithmetic in the browser.
    has_active_plan: bool = False
    user_count: int = 0
    owner_email: Optional[str] = None      # the tenant's super_admin
    owner_name: Optional[str] = None

    model_config = {"from_attributes": True}


class TenantPlanUpdate(BaseModel):
    plan_status: PlanStatus
    plan_expires_at: Optional[datetime] = None
    plan_note: Optional[str] = None

    @model_validator(mode="after")
    def _validate(self) -> "TenantPlanUpdate":
        if self.plan_note:
            self.plan_note = self.plan_note.strip()[:255] or None
        # An expiry already in the past would freeze the workspace the instant it
        # was activated, which is never what the operator meant to click.
        if (
            self.plan_status in (PlanStatus.ACTIVE, PlanStatus.TRIAL)
            and self.plan_expires_at is not None
            and self.plan_expires_at <= datetime.utcnow()
        ):
            raise ValueError("Expiry date must be in the future. Leave it empty for no expiry.")
        return self


class PlanStats(BaseModel):
    total: int = 0
    active: int = 0
    free: int = 0
    trial: int = 0
    expired: int = 0
    suspended: int = 0
