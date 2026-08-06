"""Series / SIT / MICE contracts — block bookings and how much of each has ticketed.

CRUD over `series_contracts`, plus the matching run that reconciles each contract
against the tickets actually issued on its PNR (see
`app.services.series_contract_matching`). Scoped per user like corporates and
customers: a contract belongs to its creator within their tenant.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.series_contract import SeriesContract
from app.models.user import User
from app.schemas.series_contract import (
    SeriesContractCreate, SeriesContractUpdate, SeriesContractRead, ContractMatchResult,
)
from app.services.series_contract_matching import SeriesContractMatchingService

router = APIRouter()

_CONTRACT_TYPES = {"series", "sit", "mice"}
_AGENT_TYPES = {"airline", "b2b"}
_TRIP_TYPES = {"one_way", "return"}


def _scope(current_user: User):
    """Ownership filter: contract must belong to the current user + tenant."""
    return and_(
        SeriesContract.tenant_id == current_user.tenant_id,
        SeriesContract.created_by_id == current_user.id,
    )


async def _get_owned_contract(contract_id: int, db: AsyncSession, current_user: User) -> SeriesContract:
    result = await db.execute(
        select(SeriesContract).where(SeriesContract.id == contract_id, _scope(current_user))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Contract not found")
    return obj


def _norm_choice(value: Optional[str], allowed: set[str]) -> Optional[str]:
    """Keep a free-text choice inside its vocabulary, or drop it."""
    if not value:
        return None
    v = value.strip()
    return v if v.lower() in allowed else None


def _sync_agent_name(contract: SeriesContract) -> None:
    """On an AIRLINE contract the airline IS the counterparty.

    The form drops the agent field entirely in that case, so mirror the airline
    into `agent_name` here — that keeps the Agent column populated and lets
    reporting group by agent uniformly across both kinds of contract. Applied to
    the built object rather than the payload so a PATCH that only touches the
    airline still keeps the two in step.
    """
    if (contract.agent_type or "").upper() == "AIRLINE":
        contract.agent_name = contract.airline_name


def _payload_fields(payload) -> dict:
    """Shared normalisation for create and update."""
    data = payload.model_dump(exclude_unset=True)
    if "contract_type" in data:
        data["contract_type"] = _norm_choice(data["contract_type"], _CONTRACT_TYPES)
    if "agent_type" in data:
        data["agent_type"] = (_norm_choice(data["agent_type"], _AGENT_TYPES) or "").upper() or None
    if "trip_type" in data:
        data["trip_type"] = (_norm_choice(data["trip_type"], _TRIP_TYPES) or "").upper() or None
    for key in ("agent_name", "airline_name", "pnr_no", "airline_code"):
        if key in data and isinstance(data[key], str):
            data[key] = data[key].strip() or None
    # The PNR is a join key, so it is stored the way it will be matched.
    if data.get("pnr_no"):
        data["pnr_no"] = data["pnr_no"].upper()
    if data.get("airline_code"):
        data["airline_code"] = data["airline_code"].upper()
    if "payment_terms" in data and data["payment_terms"] is not None:
        data["payment_terms"] = [
            t if isinstance(t, dict) else t.model_dump() for t in data["payment_terms"]
        ] or None
    return data


@router.get("/", response_model=list[SeriesContractRead])
async def list_contracts(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    contract_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(SeriesContract).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            SeriesContract.pnr_no.ilike(term),
            SeriesContract.agent_name.ilike(term),
            SeriesContract.airline_name.ilike(term),
            SeriesContract.airline_code.ilike(term),
        ))
    if contract_type and contract_type.strip():
        q = q.where(SeriesContract.contract_type == contract_type.strip())
    q = q.order_by(SeriesContract.id.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=SeriesContractRead, status_code=status.HTTP_201_CREATED)
async def create_contract(
    payload: SeriesContractCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = _payload_fields(payload)
    if not data.get("pnr_no"):
        raise HTTPException(status_code=400, detail="PNR No is required — it is how tickets are matched to this contract.")

    contract = SeriesContract(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        **data,
    )
    _sync_agent_name(contract)
    db.add(contract)
    await db.flush()  # assign contract.id before the matching run reads it

    # A contract is very often written after its tickets already exist, so match
    # immediately rather than showing a zeroed rollup until someone presses the
    # button. Best-effort: a matching failure must not lose the contract.
    try:
        await SeriesContractMatchingService.run(
            db, tenant_id=current_user.tenant_id, created_by_id=current_user.id,
            contract_id=contract.id,
        )
    except Exception:  # noqa: BLE001
        pass

    await db.commit()
    await db.refresh(contract)
    return contract


# Must stay above /{contract_id} — declared after it, "match" would be captured
# as a contract_id and fail int validation.
@router.post("/match", response_model=ContractMatchResult)
async def match_contracts(
    contract_id: Optional[int] = Query(None, description="Limit to one contract; omit for all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recompute the issuance rollup from the tickets issued on each contract's PNR."""
    s = await SeriesContractMatchingService.run(
        db,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        contract_id=contract_id,
    )
    await db.commit()
    return ContractMatchResult(
        contracts=s.contracts, pending=s.pending, partial=s.partial,
        complete=s.complete, over_issued=s.over_issued,
        tickets_matched=s.tickets_matched, amount_matched=s.amount_matched,
    )


@router.get("/{contract_id}", response_model=SeriesContractRead)
async def get_contract(
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_owned_contract(contract_id, db, current_user)


@router.patch("/{contract_id}", response_model=SeriesContractRead)
async def update_contract(
    contract_id: int,
    payload: SeriesContractUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_owned_contract(contract_id, db, current_user)
    data = _payload_fields(payload)
    for field, value in data.items():
        setattr(obj, field, value)
    _sync_agent_name(obj)

    # Editing the PNR or the pax count changes what this contract matches and
    # where it stands, so re-derive rather than leaving a stale rollup behind.
    try:
        await SeriesContractMatchingService.run(
            db, tenant_id=current_user.tenant_id, created_by_id=current_user.id,
            contract_id=obj.id,
        )
    except Exception:  # noqa: BLE001
        pass

    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_owned_contract(contract_id, db, current_user)
    await db.delete(obj)
    await db.commit()
