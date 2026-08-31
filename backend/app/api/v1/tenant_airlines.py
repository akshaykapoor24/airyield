"""User Master → Airline Master.

The airlines a tenant works with, each carrying the tenant's own id for it. That id is
what a user selects when uploading an LCC Detailed statement, which is the only way the
carrier can be known for LCC data — see models/tenant_airline.py for why.

The airline dropdown needs no endpoint here: GET /airlines/ already returns name,
iata_code, iata_numeric_code and contract_year (schemas/airline.py::AirlineRead).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.airline import Airline
from app.models.lcc_detailed import LccDetailedBatch
from app.models.tenant_airline import TenantAirline
from app.models.user import User
from app.schemas.tenant_airline import (
    TenantAirlineCreate, TenantAirlineRead, TenantAirlineUpdate,
)

router = APIRouter()


def _scope(current_user: User):
    """Tenant scope — the airline master is shared across the tenant's users,
    matching login_ids.py rather than the per-user scoping the statements use."""
    return TenantAirline.tenant_id == current_user.tenant_id


async def _load(pk: int, db: AsyncSession, current_user: User) -> TenantAirline:
    obj = (await db.execute(
        select(TenantAirline)
        .options(selectinload(TenantAirline.airline))
        .where(TenantAirline.id == pk, _scope(current_user))
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Airline not found in your Airline Master.")
    return obj


async def _airline_or_400(db: AsyncSession, airline_id: int) -> Airline:
    airline = (await db.execute(select(Airline).where(Airline.id == airline_id))).scalar_one_or_none()
    if not airline:
        raise HTTPException(status_code=400, detail=f"Airline id {airline_id} not found in the airline master.")
    return airline


async def _guard_duplicate_ref(
    db: AsyncSession, current_user: User, ref_id: str, exclude_pk: int | None = None
) -> None:
    """The ref id is the selection key at LCC upload, so it must be unique per tenant.
    Checked here so the user gets a readable 409 instead of a unique-violation 500."""
    q = select(TenantAirline.id).where(
        _scope(current_user), func.lower(TenantAirline.ref_id) == ref_id.lower()
    )
    if exclude_pk is not None:
        q = q.where(TenantAirline.id != exclude_pk)
    if (await db.execute(q)).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"The id '{ref_id}' is already used by another airline.")


@router.get("/", response_model=list[TenantAirlineRead])
async def list_tenant_airlines(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(TenantAirline).options(selectinload(TenantAirline.airline)).where(_scope(current_user))
    if active is not None:
        q = q.where(TenantAirline.is_active.is_(active))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            TenantAirline.ref_id.ilike(term),
            TenantAirline.airline_name.ilike(term),
            TenantAirline.airline_code.ilike(term),
            TenantAirline.iata_numeric_code.ilike(term),
        ))
    q = q.order_by(TenantAirline.airline_name, TenantAirline.ref_id).offset(skip).limit(limit)
    return (await db.execute(q)).scalars().all()


@router.post("/", response_model=TenantAirlineRead, status_code=status.HTTP_201_CREATED)
async def create_tenant_airline(
    payload: TenantAirlineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ref_id = (payload.ref_id or "").strip()
    if not ref_id:
        raise HTTPException(status_code=400, detail="An id for this airline is required.")
    airline = await _airline_or_400(db, payload.airline_id)
    await _guard_duplicate_ref(db, current_user, ref_id)

    obj = TenantAirline(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        ref_id=ref_id,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    obj.apply_master(airline)
    db.add(obj)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.get("/{pk}", response_model=TenantAirlineRead)
async def get_tenant_airline(
    pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load(pk, db, current_user)


@router.patch("/{pk}", response_model=TenantAirlineRead)
async def update_tenant_airline(
    pk: int,
    payload: TenantAirlineUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(pk, db, current_user)
    data = payload.model_dump(exclude_unset=True)

    if "ref_id" in data:
        ref_id = (data["ref_id"] or "").strip()
        if not ref_id:
            raise HTTPException(status_code=400, detail="An id for this airline is required.")
        await _guard_duplicate_ref(db, current_user, ref_id, exclude_pk=pk)
        obj.ref_id = ref_id

    if "airline_id" in data and data["airline_id"] is not None:
        # Re-point at a different master row: re-snapshot everything with it.
        obj.apply_master(await _airline_or_400(db, data["airline_id"]))

    if "is_active" in data and data["is_active"] is not None:
        obj.is_active = data["is_active"]

    await db.commit()
    return await _load(obj.id, db, current_user)


@router.delete("/{pk}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_airline(
    pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(pk, db, current_user)

    # The FK is ON DELETE SET NULL, so deleting would silently strip the airline from
    # statements already uploaded against it. Refuse instead and say how many.
    in_use = (await db.execute(
        select(func.count()).select_from(LccDetailedBatch)
        .where(LccDetailedBatch.tenant_airline_id == pk)
    )).scalar_one()
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{obj.ref_id}' is used by {in_use} uploaded statement(s). "
                "Mark it inactive instead — that hides it from new uploads and keeps "
                "the airline on the statements already imported."
            ),
        )

    await db.delete(obj)
    await db.commit()
