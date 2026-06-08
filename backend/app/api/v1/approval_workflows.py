from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import ProgrammingError

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.approval_workflow import (
    ApprovalWorkflow,
    ApprovalWorkflowStep,
    ApprovalWorkflowStepApprover,
    WorkflowModule,
)
from app.schemas.approval_workflow import WorkflowCreate, WorkflowRead, WorkflowUserRead, WorkflowPreviewStepRead, WorkflowPreviewApproverRead

router = APIRouter()


def _parse_module(module: str) -> WorkflowModule:
    raw = module.lower().strip()
    try:
        return WorkflowModule(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported module") from exc


def _handle_missing_table(exc: Exception) -> None:
    msg = str(exc).lower()
    if "approval_workflows" in msg and "does not exist" in msg:
        raise HTTPException(
            status_code=503,
            detail="Approval workflow tables are not initialized. Run backend migration: alembic upgrade head",
        )


def _require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return current_user


@router.get("/deals-preview", response_model=list[WorkflowPreviewStepRead])
async def deals_workflow_preview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the active deals approval workflow steps with approver names.
    Accessible to any authenticated user so they can see who will review their deal.
    """
    result = await db.execute(
        select(ApprovalWorkflow)
        .options(
            selectinload(ApprovalWorkflow.steps).selectinload(ApprovalWorkflowStep.approvers)
        )
        .where(
            ApprovalWorkflow.tenant_id == current_user.tenant_id,
            ApprovalWorkflow.module == WorkflowModule.DEALS,
            ApprovalWorkflow.is_active == True,  # noqa: E712
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow or not workflow.steps:
        return []

    user_ids: set[int] = set()
    for step in workflow.steps:
        for approver in step.approvers or []:
            user_ids.add(approver.user_id)

    users_result = await db.execute(
        select(User).where(User.id.in_(user_ids))
    )
    users_by_id = {u.id: u for u in users_result.scalars().all()}

    preview: list[WorkflowPreviewStepRead] = []
    for step in sorted(workflow.steps, key=lambda s: s.step_order):
        approvers = [
            WorkflowPreviewApproverRead(id=usr.id, full_name=usr.full_name, email=usr.email)
            for a in (step.approvers or [])
            if (usr := users_by_id.get(a.user_id)) is not None
        ]
        preview.append(WorkflowPreviewStepRead(
            step_order=step.step_order,
            role=step.role,
            approvers=approvers,
        ))
    return preview


@router.get("/", response_model=list[WorkflowRead])
async def list_workflows(
    module: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_super_admin),
):
    parsed_module = _parse_module(module) if module else None
    stmt = (
        select(ApprovalWorkflow)
        .options(selectinload(ApprovalWorkflow.steps).selectinload(ApprovalWorkflowStep.approvers))
        .where(ApprovalWorkflow.tenant_id == current_user.tenant_id)
        .order_by(ApprovalWorkflow.created_at.desc())
    )
    if parsed_module:
        stmt = stmt.where(ApprovalWorkflow.module == parsed_module)
    try:
        result = await db.execute(stmt)
    except ProgrammingError as exc:
        _handle_missing_table(exc)
        raise
    return result.scalars().all()


@router.post("/", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_or_replace_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_super_admin),
):
    module = _parse_module(payload.module)
    is_proprietary = payload.deal_category == "proprietary" and module == WorkflowModule.DEALS
    if not is_proprietary and not payload.steps:
        raise HTTPException(status_code=400, detail="At least one step is required")

    # enforce unique step ordering
    orders = [s.step_order for s in payload.steps]
    if len(set(orders)) != len(orders):
        raise HTTPException(status_code=400, detail="Duplicate step order is not allowed")

    try:
        existing_result = await db.execute(
            select(ApprovalWorkflow)
            .options(selectinload(ApprovalWorkflow.steps).selectinload(ApprovalWorkflowStep.approvers))
            .where(
                ApprovalWorkflow.tenant_id == current_user.tenant_id,
                ApprovalWorkflow.module == module,
            )
        )
    except ProgrammingError as exc:
        _handle_missing_table(exc)
        raise
    existing = existing_result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()

    workflow = ApprovalWorkflow(
        tenant_id=current_user.tenant_id,
        module=module,
        is_active=True,
        deal_category=payload.deal_category,
        created_by_id=current_user.id,
    )
    db.add(workflow)
    await db.flush()

    for s in sorted(payload.steps, key=lambda x: x.step_order):
        step = ApprovalWorkflowStep(
            workflow_id=workflow.id,
            step_order=s.step_order,
            role=s.role,
            reviewer_user_id=s.reviewer_user_id,
        )
        db.add(step)
        await db.flush()
        for user_id in s.approver_user_ids:
            db.add(ApprovalWorkflowStepApprover(workflow_step_id=step.id, user_id=user_id))

    await db.commit()
    result = await db.execute(
        select(ApprovalWorkflow)
        .options(selectinload(ApprovalWorkflow.steps).selectinload(ApprovalWorkflowStep.approvers))
        .where(ApprovalWorkflow.id == workflow.id)
    )
    return result.scalar_one()


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: int,
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_super_admin),
):
    result = await db.execute(
        select(ApprovalWorkflow)
        .options(selectinload(ApprovalWorkflow.steps).selectinload(ApprovalWorkflowStep.approvers))
        .where(
            ApprovalWorkflow.id == workflow_id,
            ApprovalWorkflow.tenant_id == current_user.tenant_id,
        )
    )
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if _parse_module(payload.module) != workflow.module:
        raise HTTPException(status_code=400, detail="Module cannot be changed")

    is_proprietary = payload.deal_category == "proprietary" and workflow.module == WorkflowModule.DEALS
    if not is_proprietary and not payload.steps:
        raise HTTPException(status_code=400, detail="At least one step is required")

    workflow.deal_category = payload.deal_category

    for step in list(workflow.steps):
        await db.delete(step)
    await db.flush()
    for s in sorted(payload.steps, key=lambda x: x.step_order):
        step = ApprovalWorkflowStep(
            workflow_id=workflow.id,
            step_order=s.step_order,
            role=s.role,
            reviewer_user_id=s.reviewer_user_id,
        )
        db.add(step)
        await db.flush()
        for user_id in s.approver_user_ids:
            db.add(ApprovalWorkflowStepApprover(workflow_step_id=step.id, user_id=user_id))
    await db.commit()

    result = await db.execute(
        select(ApprovalWorkflow)
        .options(selectinload(ApprovalWorkflow.steps).selectinload(ApprovalWorkflowStep.approvers))
        .where(ApprovalWorkflow.id == workflow.id)
    )
    return result.scalar_one()


@router.get("/roles/{role}/users", response_model=list[WorkflowUserRead])
async def users_by_role(
    role: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_super_admin),
):
    role = role.lower().strip()
    result = await db.execute(
        select(User).where(
            User.tenant_id == current_user.tenant_id,
            User.role == role,
            User.is_active == True,
        )
    )
    users = result.scalars().all()
    return [
        WorkflowUserRead(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            role=str(u.role.value if hasattr(u.role, "value") else u.role),
        )
        for u in users
    ]

