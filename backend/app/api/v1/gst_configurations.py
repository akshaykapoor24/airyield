"""Master Governance → GST Configuration.

The rules that say what GST is charged on and at what rates, held as data so no
screen or service has to hardcode a formula. Three seeded rules cover the whole
business today:

    ABD  Abatement · Domestic       Basic Fare × 5%   → 9 / 9 / 18
    ABI  Abatement · International  Basic Fare × 10%  → 9 / 9 / 18
    NA   Normal · Agency            Service Charge    → 9 / 9 / 18
    NR   Normal · Reseller          Total Cost        → 9 / 9 / 18

READS ARE OPEN, WRITES ARE PLATFORM-ADMIN ONLY. Unlike the other Master
Governance masters this one has no submit-for-approval queue: a tenant cannot
propose a tax rate, so there is nothing for Master Governance to review. Tenant
users read the master so their own screens can show which rule applies to them.

The arithmetic lives in services/gst_calc.py, never here.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_, true as sa_true
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, is_platform_admin, require_role
from app.models.gst_configuration import (
    GstConfiguration, SUB_CATEGORIES_BY_CATEGORY,
)
from app.models.user import User, UserRole
from app.schemas.gst_configuration import (
    GstConfigurationCreate, GstConfigurationUpdate, GstConfigurationRead,
    GstPreviewRequest, GstPreviewResponse,
)
from app.services import gst_calc

router = APIRouter()

# Writes carry this as a dependency rather than an in-handler check, so the guard
# shows up in the OpenAPI signature and returns the same 403 body as every other
# master. Reads deliberately do NOT carry it — see the module docstring.
# Never compare user.role to the enum directly: users.role stores the NAME, which
# is why require_role goes through role_matches (models/user.py).
PLATFORM = UserRole.PLATFORM_ADMIN


def _scope(current_user: User):
    """Which rows this caller may see.

    The platform admin's rules are global (tenant_id NULL) and everyone reads
    them. The nullable tenant_id exists so a per-tenant override stays possible
    without a migration; until one is created this reduces to "the global set".
    Mirrors api/v1/iata_commissions._scope.
    """
    if is_platform_admin(current_user):
        return sa_true()
    return or_(
        GstConfiguration.tenant_id.is_(None),
        GstConfiguration.tenant_id == current_user.tenant_id,
    )


def _read(obj: GstConfiguration) -> GstConfigurationRead:
    """Serialise a row with its formula sentence attached."""
    out = GstConfigurationRead.model_validate(obj)
    out.formula = gst_calc.formula_text(obj)
    return out


async def _load(pk: int, db: AsyncSession, current_user: User) -> GstConfiguration:
    result = await db.execute(
        select(GstConfiguration).where(GstConfiguration.id == pk, _scope(current_user))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="GST configuration not found")
    return obj


def _check_sub_category(category: str, sub_category: Optional[str]) -> Optional[str]:
    """Both categories are subdivided, each along its own axis.

    abatement → domestic | international · normal → agency | reseller.

    Enforced here as well as in the create schema because PATCH can change the
    category on an existing row, which the schema alone cannot see: a row moved
    from normal to abatement would otherwise keep a sub_category of 'agency'.
    """
    allowed = SUB_CATEGORIES_BY_CATEGORY.get(category)
    if allowed is None:
        raise HTTPException(
            status_code=400,
            detail=f"category must be one of: {', '.join(SUB_CATEGORIES_BY_CATEGORY)}",
        )
    if sub_category not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The '{category}' category needs a sub_category of "
                f"{' or '.join(allowed)}."
            ),
        )
    return sub_category


# ── read ───────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[GstConfigurationRead])
async def list_gst_configurations(
    category: Optional[str] = None,
    sub_category: Optional[str] = None,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(GstConfiguration).where(_scope(current_user))
    if category:
        q = q.where(GstConfiguration.category == category.strip().lower())
    if sub_category:
        q = q.where(GstConfiguration.sub_category == sub_category.strip().lower())
    if active_only:
        q = q.where(GstConfiguration.is_active.is_(True))
    # Abatement before normal, then agency before reseller — the order the screen
    # lays the tabs out in, so it needs no client-side sort.
    q = q.order_by(
        GstConfiguration.category,
        GstConfiguration.sub_category.nulls_first(),
        GstConfiguration.valid_from.nulls_first(),
    )
    result = await db.execute(q)
    return [_read(r) for r in result.scalars().all()]


@router.get("/resolve", response_model=GstConfigurationRead)
async def resolve_gst_configuration(
    category: str,
    sub_category: Optional[str] = None,
    on_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The ONE rule in force for a category on a date.

    Exists so a caller never has to reimplement the "latest valid_from that has
    started and not expired" pick — services/gst_calc.resolve_config owns it.
    """
    result = await db.execute(select(GstConfiguration).where(_scope(current_user)))
    match = gst_calc.resolve_config(
        result.scalars().all(),
        category=category.strip().lower(),
        sub_category=(sub_category or "").strip().lower() or None,
        on_date=on_date,
    )
    if not match:
        raise HTTPException(
            status_code=404,
            detail="No active GST configuration for that category on that date.",
        )
    return _read(match)


@router.get("/{pk}", response_model=GstConfigurationRead)
async def get_gst_configuration(
    pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _read(await _load(pk, db, current_user))


# ── the preview calculator ─────────────────────────────────────────────────────

@router.post("/{pk}/preview", response_model=GstPreviewResponse)
async def preview_gst(
    pk: int,
    payload: GstPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run a rule against sample amounts, both place-of-supply ways.

    Returns intra-state and inter-state as SEPARATE results. Only one of them is
    ever billed on a real transaction — showing both is what makes it obvious
    that CGST + SGST and IGST are alternatives, not additions.
    """
    obj = await _load(pk, db, current_user)
    amounts = dict(
        basic_fare=payload.basic_fare,
        taxes=payload.taxes,
        service_charge=payload.service_charge,
    )
    return GstPreviewResponse(
        formula=gst_calc.formula_text(obj),
        intrastate=gst_calc.compute_gst(obj, interstate=False, **amounts),
        interstate=gst_calc.compute_gst(obj, interstate=True, **amounts),
    )


# ── write (platform admin only) ────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED, response_model=GstConfigurationRead)
async def create_gst_configuration(
    payload: GstConfigurationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    sub = _check_sub_category(payload.category, payload.sub_category)

    # The unique constraint is (tenant_id, code, valid_from); say which row
    # collides rather than letting psycopg raise a 500 on the index.
    clash = (await db.execute(
        select(GstConfiguration).where(
            GstConfiguration.tenant_id.is_(None),
            GstConfiguration.code == payload.code,
            GstConfiguration.valid_from.is_(payload.valid_from)
            if payload.valid_from is None
            else GstConfiguration.valid_from == payload.valid_from,
        )
    )).scalar_one_or_none()
    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"A GST configuration with code '{payload.code}' and that valid-from date already exists.",
        )

    obj = GstConfiguration(
        # Master Governance data is global — see _scope.
        tenant_id=None,
        created_by_id=current_user.id,
        code=payload.code,
        name=payload.name,
        category=payload.category,
        sub_category=sub,
        basis=payload.basis,
        taxable_value_pct=payload.taxable_value_pct,
        cgst_pct=payload.cgst_pct,
        sgst_pct=payload.sgst_pct,
        igst_pct=payload.igst_pct,
        sac_code=payload.sac_code,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        notes=payload.notes,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _read(obj)


@router.patch("/{pk}", response_model=GstConfigurationRead)
async def update_gst_configuration(
    pk: int,
    payload: GstConfigurationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    obj = await _load(pk, db, current_user)

    data = payload.model_dump(exclude_unset=True)

    # Category and sub-category have to be validated together against the values
    # the row will END UP with, not the ones that arrived — a PATCH that sets
    # only one of the two is legitimate.
    if "category" in data or "sub_category" in data:
        new_category = data.get("category", obj.category)
        new_sub = data.get("sub_category", obj.sub_category)
        data["category"] = new_category
        data["sub_category"] = _check_sub_category(new_category, new_sub)

    for field, value in data.items():
        setattr(obj, field, value)

    await db.commit()
    await db.refresh(obj)
    return _read(obj)


@router.delete("/{pk}")
async def delete_gst_configuration(
    pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    obj = await _load(pk, db, current_user)
    await db.delete(obj)
    await db.commit()
    return {"status": "deleted", "id": pk}
