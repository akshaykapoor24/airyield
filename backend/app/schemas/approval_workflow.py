from datetime import datetime, date
from typing import Optional

from pydantic import BaseModel, Field


class WorkflowStepCreate(BaseModel):
    step_order: int = Field(ge=1)
    role: str
    approver_user_ids: list[int] = Field(min_length=1)
    reviewer_user_id: Optional[int] = None


class WorkflowCreate(BaseModel):
    module: str
    steps: list[WorkflowStepCreate]


class WorkflowStepRead(BaseModel):
    id: int
    step_order: int
    role: str
    approver_user_ids: list[int]
    reviewer_user_id: Optional[int]

    model_config = {"from_attributes": True}


class WorkflowRead(BaseModel):
    id: int
    tenant_id: int
    module: str
    is_active: bool
    created_by_id: int
    created_at: datetime
    updated_at: datetime
    steps: list[WorkflowStepRead]

    model_config = {"from_attributes": True}


class WorkflowUserRead(BaseModel):
    id: int
    full_name: str
    email: str
    role: str


class DealApprovalStepRead(BaseModel):
    id: int
    step_order: int
    role: str
    assigned_user_id: int
    status: str
    acted_by_id: Optional[int]
    acted_at: Optional[datetime]
    reason: Optional[str]

    model_config = {"from_attributes": True}


class DealApprovalRead(BaseModel):
    id: int
    deal_id: int
    workflow_id: int
    current_step_order: int
    status: str
    submitted_by_id: int
    submitted_at: datetime
    updated_at: datetime
    steps: list[DealApprovalStepRead]

    model_config = {"from_attributes": True}


class ApprovalDecisionPayload(BaseModel):
    reason: Optional[str] = None


class ApprovalInboxItem(BaseModel):
    id:              int             # DealApproval.id — used for approve/reject/bulk-approve routing
    deal_id:         int             # actual deal ID in its table — used for history lookup
    deal_type:       str             # 'upload' | 'airline' | 'b2b'
    source_agent:    str
    airline_name:    Optional[str]
    airline_type:    Optional[str]
    status:          str
    created_at:      datetime
    valid_from:      Optional[date] = None
    valid_to:        Optional[date] = None
    business_type:   Optional[str] = None
    incentive_types: Optional[list[str]] = None
    incentive_data:  Optional[dict] = None
    incl_excl_types: Optional[list[str]] = None
    incl_excl_data:  Optional[dict] = None
    deal_maker_name: Optional[str] = None
    contract_year:   Optional[str] = None
    trigger_type:    Optional[str] = None
    payout_type:     Optional[str] = None
    entity_lcc:      Optional[str] = None
    remark:          Optional[str] = None
    deal_no:         Optional[str] = None


class BulkApprovePayload(BaseModel):
    deal_ids: list[int] = Field(min_length=1)   # list of DealApproval.id values
    reason: Optional[str] = None


class BulkApproveResult(BaseModel):
    approved: list[int]
    failed: list[dict]


class WorkflowPreviewApproverRead(BaseModel):
    id: int
    full_name: str
    email: str


class WorkflowPreviewStepRead(BaseModel):
    step_order: int
    role: str
    approvers: list[WorkflowPreviewApproverRead]


class DealHistoryStepRead(BaseModel):
    step_order: int
    role: str
    assigned_user_name: str
    status: str
    acted_by_name: Optional[str]
    acted_at: Optional[datetime]
    reason: Optional[str]


class DealHistoryResponse(BaseModel):
    deal_id: int
    created_by_name: str
    created_at: datetime
    source_type: str
    status: str
    steps: list[DealHistoryStepRead]

