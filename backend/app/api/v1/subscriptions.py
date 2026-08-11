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
from app.schemas.subscription import PlanStats, TenantPlanRead, TenantPlanUpdate

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


def _to_read(t: Tenant, owner: Optional[User], user_count: int) -> TenantPlanRead:
    read = TenantPlanRead.model_validate(t)
    read.has_active_plan = t.has_active_plan
    read.user_count = user_count
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
    return [_to_read(t, owners.get(t.id), counts.get(t.id, 0)) for t in tenants]


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
    return _to_read(tenant, owners.get(tenant.id), counts.get(tenant.id, 0))


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
    return _to_read(tenant, owners.get(tenant.id), counts.get(tenant.id, 0))
