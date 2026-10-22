"""Vendor ↔ Internal reconciliation — /reconciliation/vendor-internal.

A Third Party GDS vendor statement (third_party_gds) against Internal Statement
(internal_uploaded_tickets), sale with sale and refund with refund. The matching
and every hint are in services/vendor_internal_recon.py; this only scopes the
request to the user and lets them pick which uploads go into it.

Computed on request and never stored: both sides are small (a month is a few
hundred lines), and a stored result would go stale the moment either statement is
re-uploaded or a ticket is punched. What IS stored is the user's decision on a line
that disagrees (/resolutions) — see models/vendor_internal_recon.py.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.internal_ticket import InternalTicketStatement, InternalUploadedTicket
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import ThirdPartyGds
from app.models.user import User
from app.models.vendor_internal_recon import VendorInternalResolution
from app.services.vendor_internal_recon import reconcile, resolve

router = APIRouter()


class _Selection(BaseModel):
    # The uploads on screen, so the answer sent back is the one the user is looking at.
    vendor_batch: Optional[list[str]] = None
    internal_batch: Optional[list[str]] = None


class ResolveBody(_Selection):
    keys: list[str] = Field(..., min_length=1, max_length=5000)
    decision: Literal["vendor_wrong", "internal_wrong", "accepted"]
    note: Optional[str] = Field(None, max_length=2000)


class ReopenBody(_Selection):
    keys: list[str] = Field(..., min_length=1, max_length=5000)

_TP_GDS_SLUG = "tp-gds"


@router.get("/sources")
async def list_sources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The uploads either side can be drawn from: vendor Third Party GDS batches
    (with the vendor they were filed under) and Internal Statement statements."""
    vq = (
        select(
            ThirdPartyGds.batch_id,
            func.min(ThirdPartyGds.source_file),
            func.min(ThirdPartyGds.uploaded_at),
            func.count(ThirdPartyGds.id),
            StatementBatchSupplier.supplier_name,
            StatementBatchSupplier.supplier_code,
        )
        .join(StatementBatchSupplier, and_(
            StatementBatchSupplier.batch_id == ThirdPartyGds.batch_id,
            StatementBatchSupplier.slug == _TP_GDS_SLUG,
        ), isouter=True)
        .where(ThirdPartyGds.tenant_id == current_user.tenant_id,
               ThirdPartyGds.created_by_id == current_user.id)
        .group_by(ThirdPartyGds.batch_id, StatementBatchSupplier.supplier_name, StatementBatchSupplier.supplier_code)
        .order_by(func.min(ThirdPartyGds.uploaded_at).desc())
    )
    vendor = [
        {"batch_id": b, "file_name": f, "uploaded_at": u, "rows": n,
         "supplier_name": sn, "supplier_code": sc}
        for b, f, u, n, sn, sc in (await db.execute(vq)).all()
    ]

    iq = (
        select(InternalTicketStatement, func.count(InternalUploadedTicket.id))
        .join(InternalUploadedTicket, InternalUploadedTicket.batch_id == InternalTicketStatement.batch_id, isouter=True)
        .where(InternalTicketStatement.tenant_id == current_user.tenant_id,
               InternalTicketStatement.created_by_id == current_user.id)
        .group_by(InternalTicketStatement.batch_id)
        .order_by(InternalTicketStatement.created_at.desc())
    )
    internal = [
        {"batch_id": s.batch_id, "statement_name": s.statement_name, "agency": s.agency,
         "file_name": s.file_name, "valid_from": s.valid_from, "valid_to": s.valid_to, "tickets": n}
        for s, n in (await db.execute(iq)).all()
        if n
    ]
    return {"vendor": vendor, "internal": internal}


@router.get("")
async def run_reconciliation(
    vendor_batch: Optional[list[str]] = Query(None, description="Vendor batches to include; all when omitted"),
    internal_batch: Optional[list[str]] = Query(None, description="Internal statements to include; all when omitted"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await reconcile(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        vendor_batches=vendor_batch or None, internal_batches=internal_batch or None,
    )


@router.post("/resolutions")
async def resolve_lines(
    body: ResolveBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Close lines that disagree with one decision — the GDS statement is wrong, the
    internal statement is wrong, or the difference is accepted. Returns the
    reconciliation as it now stands."""
    try:
        return await resolve(
            db, tenant_id=current_user.tenant_id, user_id=current_user.id,
            keys=body.keys, decision=body.decision, note=body.note,
            vendor_batches=body.vendor_batch or None, internal_batches=body.internal_batch or None,
        )
    except LookupError:
        raise HTTPException(409, "Some of these lines have changed since the screen was loaded — "
                                 "reconcile again and retry.")


@router.post("/resolutions/reopen")
async def reopen_lines(
    body: ReopenBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Withdraw the decision on these lines, putting them back with the open ones."""
    await db.execute(delete(VendorInternalResolution).where(
        VendorInternalResolution.tenant_id == current_user.tenant_id,
        VendorInternalResolution.created_by_id == current_user.id,
        VendorInternalResolution.item_key.in_(body.keys),
    ))
    await db.commit()
    return await reconcile(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        vendor_batches=body.vendor_batch or None, internal_batches=body.internal_batch or None,
    )
