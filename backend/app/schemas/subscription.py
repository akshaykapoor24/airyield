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
    # Usage, so the console can see at a glance whether a workspace is actually
    # being used before deciding what to do with its plan. Deals and tickets
    # alone said too little: a workspace living in BSP and vendor statements but
    # never uploading a deal sheet read as 0, exactly like one that never came
    # back. This totals every table a workspace fills — see
    # app/services/tenant_usage.py for what is counted and what is not.
    record_count: int = 0
    # {label: rows} for the console's hover panel. Zero-valued entries are
    # omitted: ~22 keys per workspace, almost all zero, for a panel that only
    # ever renders the non-zero lines.
    record_breakdown: dict[str, int] = {}
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


class DeletionGroupRead(BaseModel):
    """One tickable line in the delete dialog."""
    key: str
    label: str
    blurb: str
    category: str          # "records" | "setup"
    rows: int
    # Groups the API will add if this one is ticked, because the schema leaves
    # no choice — a RESTRICT would abort the delete, a CASCADE would widen it
    # silently. The dialog ticks these itself so the preview never lies.
    requires: list[str] = []


class DeletionPreview(BaseModel):
    """Everything that could be deleted, counted, for the confirm dialog."""
    tenant_id: int
    tenant_name: Optional[str] = None
    tenant_type: TenantType
    owner_email: Optional[str] = None
    user_emails: list[str] = []
    # What the operator must type to confirm. Served rather than assembled in
    # the browser so the UI can never ask for a phrase the API would reject.
    confirm_phrase: str
    groups: list[DeletionGroupRead] = []


class DeletionLine(BaseModel):
    key: str
    label: str
    rows: int


class DeletionResult(BaseModel):
    tenant_id: int
    tenant_name: Optional[str] = None
    # What was asked for, and what that had to become. When they differ the
    # console says so rather than quietly reporting more than was ticked.
    requested: list[str] = []
    deleted_groups: list[str] = []
    deleted: list[DeletionLine] = []
    total: int = 0
    workspace_removed: bool = False


class PlanStats(BaseModel):
    total: int = 0
    active: int = 0
    free: int = 0
    trial: int = 0
    expired: int = 0
    suspended: int = 0
