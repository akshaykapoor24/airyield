"""Vendor ↔ Internal reconciliation — /reconciliation/vendor-internal.

A Third Party GDS vendor statement (third_party_gds) against Internal Statement
(internal_uploaded_tickets), sale with sale and refund with refund. The matching
and every hint are in services/vendor_internal_recon.py; this only scopes the
request to the user and lets them pick which uploads go into it.

Computed on request and never stored: both sides are small (a month is a few
hundred lines), and a stored result would go stale the moment either statement is
re-uploaded or a ticket is punched.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.internal_ticket import InternalTicketStatement, InternalUploadedTicket
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import ThirdPartyGds
from app.models.user import User
from app.services.vendor_internal_recon import reconcile

router = APIRouter()

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
