"""Platform-admin console for workspace subscriptions.

The only cross-tenant surface in the app. Every other router scopes its queries
to current_user.tenant_id; this one deliberately does not, because the platform
admin belongs to no tenant and its whole job is to look across them. That is why
require_role(PLATFORM_ADMIN) guards every route here rather than a per-query
filter doing the work.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.models.tenant import PlanStatus, Tenant
from app.models.user import User, UserRole
from app.schemas.subscription import (
    DeletionGroupRead, DeletionLine, DeletionPreview, DeletionResult,
    PlanStats, TenantPlanRead, TenantPlanUpdate,
)
from app.services.tenant_deletion import (
    DELETION_GROUPS, GROUPS_BY_KEY, GROUP_REQUIREMENTS,
    delete_groups, group_counts, validate_groups,
)
from app.services.tenant_usage import to_breakdown, usage_counts

router = APIRouter()

_admin = Depends(require_role(UserRole.PLATFORM_ADMIN))


async def _owner_map(db: AsyncSession, tenant_ids: list[int]) -> dict[int, User]:
    """{tenant_id: its super_admin} in one query.

    Signup makes the first user of a workspace its SUPER_ADMIN and refuses a
    second one on the same domain, so there is normally exactly one. If a
    database has more, the lowest id wins — deterministic beats arbitrary.
    """
    if not tenant_ids:
        return {}
    rows = (await db.execute(
        select(User)
        .where(User.tenant_id.in_(tenant_ids), User.role == UserRole.SUPER_ADMIN)
        .order_by(User.tenant_id, User.id)
    )).scalars().all()
    out: dict[int, User] = {}
    for u in rows:
        out.setdefault(u.tenant_id, u)
    return out


async def _user_counts(db: AsyncSession, tenant_ids: list[int]) -> dict[int, int]:
    if not tenant_ids:
        return {}
    rows = (await db.execute(
        select(User.tenant_id, func.count(User.id))
        .where(User.tenant_id.in_(tenant_ids))
        .group_by(User.tenant_id)
    )).all()
    return {tid: n for tid, n in rows}


def _to_read(
    t: Tenant,
    owner: Optional[User],
    user_count: int,
    usage: Optional[dict[str, int]] = None,
) -> TenantPlanRead:
    """`usage` is {source_key: rows} for this tenant, straight from usage_counts.

    Counts the whole workspace rather than one member's rows: the console lists
    workspaces, and a tenant's records may have been created by any of its
    members. (dashboard.py deliberately does the opposite — it also filters on
    created_by_id, because it is a per-user view. Do not reconcile the two.)
    """
    counts = usage or {}
    read = TenantPlanRead.model_validate(t)
    read.has_active_plan = t.has_active_plan
    read.user_count = user_count
    read.record_count = sum(counts.values())
    read.record_breakdown = to_breakdown(counts)
    read.owner_email = owner.email if owner else None
    read.owner_name = owner.full_name if owner else None
    return read


@router.get("/", response_model=list[TenantPlanRead])
async def list_tenant_plans(
    q: Optional[str] = Query(None, description="Search workspace name, domain or owner email"),
    plan_status: Optional[PlanStatus] = Query(None, description="Filter by exact stored status"),
    skip: int = 0,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    _: User = _admin,
):
    stmt = select(Tenant)
    if plan_status is not None:
        stmt = stmt.where(Tenant.plan_status == plan_status)
    if q:
        like = f"%{q.strip()}%"
        # Owner email is on users, so match it through a correlated EXISTS rather
        # than a join that would multiply rows per member.
        owner_match = select(User.id).where(
            User.tenant_id == Tenant.id, User.email.ilike(like)
        ).exists()
        stmt = stmt.where(or_(Tenant.name.ilike(like), Tenant.domain.ilike(like), owner_match))

    tenants = (await db.execute(
        stmt.order_by(Tenant.created_at.desc(), Tenant.id.desc()).offset(skip).limit(limit)
    )).scalars().all()

    ids = [t.id for t in tenants]
    owners = await _owner_map(db, ids)
    counts = await _user_counts(db, ids)
    usage = await usage_counts(db, ids)
    return [
        _to_read(t, owners.get(t.id), counts.get(t.id, 0), usage.get(t.id))
        for t in tenants
    ]


@router.get("/stats", response_model=PlanStats)
async def plan_stats(db: AsyncSession = Depends(get_db), _: User = _admin):
    rows = (await db.execute(
        select(Tenant.plan_status, func.count(Tenant.id)).group_by(Tenant.plan_status)
    )).all()
    stats = PlanStats()
    for stored, n in rows:
        stats.total += n
        key = getattr(stored, "value", stored)
        if hasattr(stats, key):
            setattr(stats, key, getattr(stats, key) + n)
    return stats


@router.get("/{tenant_id}", response_model=TenantPlanRead)
async def get_tenant_plan(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = _admin,
):
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    owners = await _owner_map(db, [tenant.id])
    counts = await _user_counts(db, [tenant.id])
    usage = await usage_counts(db, [tenant.id])
    return _to_read(
        tenant, owners.get(tenant.id), counts.get(tenant.id, 0), usage.get(tenant.id),
    )


def _confirm_phrase(tenant: Tenant) -> str:
    """What the operator must type to delete this workspace.

    Its own name, so the phrase is different for every workspace and cannot be
    muscle-memoried; workspaces created without one fall back to their domain,
    then to the id, which is always present.
    """
    return (tenant.name or "").strip() or (tenant.domain or "").strip() or f"workspace-{tenant.id}"


async def _get_tenant(tenant_id: int, db: AsyncSession) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return tenant


@router.get("/{tenant_id}/deletion-preview", response_model=DeletionPreview)
async def preview_tenant_deletion(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = _admin,
):
    """Everything that could be deleted for this workspace, counted per group.

    Counted with the same predicates the delete uses, so the operator confirms
    against the real numbers rather than an estimate made somewhere else. Every
    group is returned, including the empty ones — "Deals: 0" is the answer to
    "is there anything here?", and hiding it would leave the question open.
    """
    tenant = await _get_tenant(tenant_id, db)
    counts = await group_counts(db, tenant_id)

    emails = (await db.execute(
        select(User.email).where(User.tenant_id == tenant_id).order_by(User.id)
    )).scalars().all()
    owners = await _owner_map(db, [tenant_id])

    return DeletionPreview(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        tenant_type=tenant.tenant_type,
        owner_email=owners[tenant_id].email if tenant_id in owners else None,
        user_emails=list(emails),
        confirm_phrase=_confirm_phrase(tenant),
        groups=[
            DeletionGroupRead(
                key=g.key,
                label=g.label,
                blurb=g.blurb,
                category=g.category.value,
                # The workspace row is not a record; its line is the tenant
                # itself, and counting it as 1 would inflate the headline.
                rows=counts.get(g.key, 0),
                requires=sorted(GROUP_REQUIREMENTS.get(g.key, ())),
            )
            for g in DELETION_GROUPS
        ],
    )


@router.delete("/{tenant_id}", response_model=DeletionResult)
async def delete_tenant_records(
    tenant_id: int,
    groups: list[str] = Query(..., description="Group keys to delete, from /deletion-preview"),
    confirm: str = Query(..., description="Must equal the confirm_phrase from /deletion-preview"),
    db: AsyncSession = Depends(get_db),
    _: User = _admin,
):
    """Delete the selected parts of a workspace. Irreversible.

    The selection is expanded over GROUP_REQUIREMENTS before anything is
    touched, so a tick whose schema forces others along takes them rather than
    aborting half way. The response reports both what was asked for and what
    that became.

    `confirm` is checked here and not only in the browser: this endpoint can
    empty any workspace on the platform, and a mistyped id in a curl call
    should not be enough to do it.
    """
    tenant = await _get_tenant(tenant_id, db)

    expected = _confirm_phrase(tenant)
    if (confirm or "").strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmation does not match. Type '{expected}' exactly to confirm.",
        )

    try:
        chosen = validate_groups(groups)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Read the name before the row goes; the response still has to say what was
    # deleted, and removing the workspace takes the tenant row with it.
    name = tenant.name

    deleted = await delete_groups(db, tenant_id, chosen)
    return DeletionResult(
        tenant_id=tenant_id,
        tenant_name=name,
        requested=sorted(set(groups)),
        deleted_groups=sorted(chosen),
        deleted=[
            DeletionLine(key=key, label=GROUPS_BY_KEY[key].label, rows=rows)
            for key, rows in deleted.items()
            if key != "workspace"
        ],
        total=sum(rows for key, rows in deleted.items() if key != "workspace"),
        workspace_removed="workspace" in chosen,
    )


@router.patch("/{tenant_id}", response_model=TenantPlanRead)
async def update_tenant_plan(
    tenant_id: int,
    payload: TenantPlanUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = _admin,
):
    """Switch a workspace on or off.

    Takes effect on the workspace's very next request — the plan is read from the
    database in get_current_user, not baked into the JWT — so nobody has to sign
    out and back in after being activated.
    """
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")

    was_active = tenant.has_active_plan
    tenant.plan_status = payload.plan_status
    tenant.plan_expires_at = payload.plan_expires_at
    if payload.plan_note is not None:
        tenant.plan_note = payload.plan_note or None
    if not was_active and tenant.has_active_plan:
        tenant.plan_activated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(tenant)

    owners = await _owner_map(db, [tenant.id])
    counts = await _user_counts(db, [tenant.id])
    usage = await usage_counts(db, [tenant.id])
    return _to_read(
        tenant, owners.get(tenant.id), counts.get(tenant.id, 0), usage.get(tenant.id),
    )
