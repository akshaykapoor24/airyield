from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.ticket_adjustment import TicketAdjustment
from app.models.uploaded_ticket import UploadedTicket
from app.schemas.ticket_adjustment import (
    TicketAdjustmentCreate,
    TicketAdjustmentUpdate,
    TicketAdjustmentRead,
    ADJUSTMENT_TYPES,
    ADJUSTMENT_STATUSES,
)

router = APIRouter()


def _scope(current_user: User):
    """Per-user scope — adjustments are private to their creator within the tenant."""
    return (
        TicketAdjustment.tenant_id == current_user.tenant_id,
        TicketAdjustment.created_by_id == current_user.id,
    )


async def _resolve_ticket_id(db: AsyncSession, current_user: User, ticket_number: Optional[str]) -> Optional[int]:
    """Best-effort resolve a ticket_number to an uploaded ticket (same user/tenant).
    Heuristic — an adjustment can exist without a matched ticket, so returns None if
    the number is blank or has no match."""
    tn = (ticket_number or "").strip()
    if not tn:
        return None
    res = await db.execute(
        select(UploadedTicket.id)
        .where(
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
            UploadedTicket.ticket_number == tn,
        )
        .order_by(UploadedTicket.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _get_owned(adj_id: int, db: AsyncSession, current_user: User) -> TicketAdjustment:
    res = await db.execute(select(TicketAdjustment).where(TicketAdjustment.id == adj_id, *_scope(current_user)))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    return obj


@router.get("/", response_model=list[TicketAdjustmentRead])
async def list_adjustments(
    type: Optional[str] = Query(None, description="Filter by type (ADM/ACM/Refund/RA/DebitNote/CreditNote)"),
    ticket_number: Optional[str] = Query(None),
    ticket_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(TicketAdjustment).where(*_scope(current_user))
    if type:
        q = q.where(TicketAdjustment.type == type)
    if ticket_number:
        q = q.where(TicketAdjustment.ticket_number == ticket_number.strip())
    if ticket_id is not None:
        q = q.where(TicketAdjustment.ticket_id == ticket_id)
    q = q.order_by(TicketAdjustment.adjustment_date.desc().nullslast(), TicketAdjustment.created_at.desc())
    return (await db.execute(q)).scalars().all()


@router.post("/", response_model=TicketAdjustmentRead, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    payload: TicketAdjustmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.type not in ADJUSTMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Allowed: {sorted(ADJUSTMENT_TYPES)}")
    if payload.status not in ADJUSTMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {sorted(ADJUSTMENT_STATUSES)}")

    ticket_id = payload.ticket_id
    if ticket_id is None:
        ticket_id = await _resolve_ticket_id(db, current_user, payload.ticket_number)

    adj = TicketAdjustment(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        ticket_id=ticket_id,
        ticket_number=(payload.ticket_number or "").strip() or None,
        type=payload.type,
        reference_no=payload.reference_no or None,
        amount=payload.amount or 0,
        reason=payload.reason or None,
        adjustment_date=payload.adjustment_date,
        remarks=payload.remarks or None,
        status=payload.status,
        source="manual",
    )
    db.add(adj)
    await db.commit()
    await db.refresh(adj)
    return adj


@router.get("/{adj_id}", response_model=TicketAdjustmentRead)
async def get_adjustment(
    adj_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_owned(adj_id, db, current_user)


@router.patch("/{adj_id}", response_model=TicketAdjustmentRead)
async def update_adjustment(
    adj_id: int,
    payload: TicketAdjustmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    adj = await _get_owned(adj_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "type" in data and data["type"] not in ADJUSTMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type. Allowed: {sorted(ADJUSTMENT_TYPES)}")
    if "status" in data and data["status"] is not None and data["status"] not in ADJUSTMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {sorted(ADJUSTMENT_STATUSES)}")
    if "ticket_number" in data and data["ticket_number"] is not None:
        data["ticket_number"] = data["ticket_number"].strip() or None

    for k, v in data.items():
        setattr(adj, k, v)

    # Re-resolve the ticket link if the number changed and no explicit ticket_id was given.
    if "ticket_number" in data and "ticket_id" not in data:
        adj.ticket_id = await _resolve_ticket_id(db, current_user, adj.ticket_number)

    await db.commit()
    await db.refresh(adj)
    return adj


@router.delete("/{adj_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_adjustment(
    adj_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    adj = await _get_owned(adj_id, db, current_user)
    await db.delete(adj)
    await db.commit()
