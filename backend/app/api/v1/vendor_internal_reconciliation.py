"""Vendor ↔ Internal reconciliation — /reconciliation/vendor-internal.

Reconciliation → Vendor Reconciliation → Third Party GDS: every vendor's Third Party GDS
statements (third_party_gds) against Internal Statement (internal_uploaded_tickets), sale with
sale and refund with refund. The matching, the eight cases, the balances and every hint are in
services/vendor_internal_recon.py; this only scopes the request to the user, reads the filters
— a vendor, one of its statements, a booking period — and records decisions.

Computed on request and never stored: a stored result would go stale the moment either
statement is re-uploaded or a ticket is punched. Everything loaded is matched on every request
and the filters only narrow what is returned, so a line is paired wherever its partner is.
What IS stored is the user's decision on a line that disagrees (/resolutions) — see
models/vendor_internal_recon.py.
"""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.vendor_internal_recon import VendorInternalResolution
from app.services.vendor_internal_recon import VIEWS, Scope, reconcile, resolve

router = APIRouter()


class _Filters(BaseModel):
    # What is on screen, so the answer sent back is the one the user is looking at.
    vendor: Optional[str] = Field(None, max_length=600)
    statement: Optional[str] = Field(None, max_length=100)
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    view: str = "all"


class ResolveBody(_Filters):
    keys: list[str] = Field(..., min_length=1, max_length=5000)
    decision: Literal["vendor_wrong", "internal_wrong", "accepted"]
    note: Optional[str] = Field(None, max_length=2000)


class ReopenBody(_Filters):
    keys: list[str] = Field(..., min_length=1, max_length=5000)


def _scope(vendor: Optional[str], statement: Optional[str], date_from: Optional[date],
           date_to: Optional[date], view: str) -> Scope:
    if view not in VIEWS:
        raise HTTPException(400, f"Unknown view “{view}”.")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "The booking period ends before it starts.")
    return Scope(vendor=vendor or None, statement=statement or None,
                 date_from=date_from.isoformat() if date_from else None,
                 date_to=date_to.isoformat() if date_to else None)


@router.get("")
async def run_reconciliation(
    vendor: Optional[str] = Query(None, description="A vendor id from `options.vendors`; every vendor when omitted"),
    statement: Optional[str] = Query(None, description="One Third Party GDS statement (batch id)"),
    date_from: Optional[date] = Query(None, description="Booking period, first day"),
    date_to: Optional[date] = Query(None, description="Booking period, last day"),
    view: str = Query("all", description="summary | all | matched | resolved | one of the eight cases"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await reconcile(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id,
        scope=_scope(vendor, statement, date_from, date_to, view), view=view,
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
    scope = _scope(body.vendor, body.statement, body.date_from, body.date_to, body.view)
    try:
        return await resolve(
            db, tenant_id=current_user.tenant_id, user_id=current_user.id,
            keys=body.keys, decision=body.decision, note=body.note, scope=scope, view=body.view,
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
    scope = _scope(body.vendor, body.statement, body.date_from, body.date_to, body.view)
    await db.execute(delete(VendorInternalResolution).where(
        VendorInternalResolution.tenant_id == current_user.tenant_id,
        VendorInternalResolution.created_by_id == current_user.id,
        VendorInternalResolution.item_key.in_(body.keys),
    ))
    await db.commit()
    return await reconcile(
        db, tenant_id=current_user.tenant_id, user_id=current_user.id, scope=scope, view=body.view,
    )
