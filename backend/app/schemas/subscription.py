from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, model_validator

from app.models.tenant import PlanStatus, TenantType
from app.schemas.platform_invoice import InvoiceSummary


class AiUsageLine(BaseModel):
    label: str
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0


class AiUsage(BaseModel):
    """OpenAI calls billed to this workspace. See services/tenant_resources.py."""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # The priced calls only. `unpriced_calls` > 0 means some model has no entry in
    # services/ai_pricing.py, so the real figure is higher — the console says so rather
    # than letting an unknown cost read as $0.
    cost_usd: float = 0.0
    unpriced_calls: int = 0
    # This calendar month (UTC) — the slice an invoice is raised against.
    month_calls: int = 0
    month_cost_usd: float = 0.0
    by_feature: list[AiUsageLine] = []
    by_member: list[AiUsageLine] = []


class StorageLine(BaseModel):
    label: str
    files: int = 0
    bytes: int = 0


class FileUsage(BaseModel):
    """What this workspace keeps in object storage. See services/usage_meter.py."""
    # Every file a member uploaded, including ones since deleted — the activity.
    uploads: int = 0
    # What is stored right now, uploads and generated reports alike — the cost.
    files: int = 0
    bytes: int = 0
    gcs_bytes: int = 0
    # The local-disk fallback, used when GCS was unreachable at upload time.
    local_bytes: int = 0
    by_source: list[StorageLine] = []
    # files = uploads by that member; bytes = what of theirs is still stored.
    by_member: list[StorageLine] = []


class DbAreaLine(BaseModel):
    label: str
    bytes: int = 0


class DbUsage(BaseModel):
    """Estimated share of Postgres — each table's on-disk size split by row share. See
    the docstring of services/tenant_resources.py for exactly what is estimated."""
    bytes: int = 0
    share: float = 0.0          # of the whole database, 0..1
    by_area: list[DbAreaLine] = []
    measured_at: Optional[datetime] = None


class ResourceUsage(BaseModel):
    ai: AiUsage = AiUsage()
    files: FileUsage = FileUsage()
    database: Optional[DbUsage] = None


class PlatformUsage(BaseModel):
    """The stats tiles: every workspace plus the unattributed remainder."""
    ai_calls: int = 0
    ai_cost_usd: float = 0.0
    ai_unpriced_calls: int = 0
    ai_month_calls: int = 0
    ai_month_cost_usd: float = 0.0
    uploads: int = 0
    files: int = 0
    gcs_bytes: int = 0
    local_bytes: int = 0
    # Stored bytes no workspace owns — mostly files left behind by deleted workspaces.
    unattributed_bytes: int = 0
    database_bytes: int = 0
    database_attributed_bytes: int = 0
    database_measured_at: Optional[datetime] = None


class VerificationState(BaseModel):
    """Whether the workspace's accounts have confirmed their email — an unverified owner
    cannot sign in at all. See services/workspace_verification.py."""
    status: Literal["verified", "unverified", "no_users"] = "no_users"
    unverified_emails: list[str] = []
    # The owner's. None when verified before this was recorded.
    verified_at: Optional[datetime] = None
    # The platform admin who verified by hand; None when the emailed link did it.
    verified_by: Optional[str] = None


class VerificationResent(BaseModel):
    sent_to: list[str] = []


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
    # What the workspace costs to run: OpenAI spend, stored files, share of Postgres. None
    # when it could not be read (metering tables not migrated yet) — the console says
    # "unavailable" rather than showing zeros that look like a real answer.
    resources: Optional[ResourceUsage] = None
    # The Invoice column: how many, what is unpaid, the latest. None = could not be read.
    invoices: Optional[InvoiceSummary] = None
    verification: Optional[VerificationState] = None

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
    # None when it could not be read — see TenantPlanRead.resources.
    usage: Optional[PlatformUsage] = None
