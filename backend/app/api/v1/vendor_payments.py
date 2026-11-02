"""Payment Module → Vendor Mapping and Vendor Payments — mounted under /payment-module.

  GET  /vendor-mapping                      a vendor's statement against the MO, line by line
  POST /vendor-mapping/decisions            vendor wrong (claim) · MO wrong · accepted
  POST /vendor-mapping/decisions/reopen     withdraw those decisions
  GET  /vendor-accounts                     every vendor's account in one line
  GET  /vendor-accounts/detail              one vendor: statements, payments, ledger, ageing
  POST /vendor-accounts/payments            a payment made to a vendor's account

Voiding a payment is the module's existing POST /payments/{id}/void (api/v1/payment_module.py).

The matching, the payable rules and the accounts are services/vendor_mapping.py; this scopes
every request to the user and checks what it is sent. Nothing but decisions and payments is
stored: the mapping is computed on request, so it never goes stale behind a re-upload.
"""
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import vendor_internal_recon as recon
from app.services import vendor_mapping as vm

router = APIRouter()


class _Scope(BaseModel):
    # What is on screen, so the answer sent back is the one the user is looking at.
    vendor: Optional[str] = Field(None, max_length=600)
    statement: Optional[str] = Field(None, max_length=100)
    view: str = "all"
    q: Optional[str] = Field(None, max_length=200)
    offset: int = Field(0, ge=0)
    limit: int = Field(500, ge=1, le=5000)


class DecideBody(_Scope):
    keys: list[str] = Field(..., min_length=1, max_length=5000)
    decision: Literal["vendor_wrong", "mo_wrong", "accepted"]
    note: Optional[str] = Field(None, max_length=2000)


class ReopenBody(_Scope):
    keys: list[str] = Field(..., min_length=1, max_length=5000)


class PaymentBody(BaseModel):
    vendor: str = Field(..., min_length=1, max_length=600)
    payment_date: date
    amount: Decimal = Field(..., gt=0, max_digits=16, decimal_places=2)
    mode: str = Field(..., max_length=20)
    reference: Optional[str] = Field(None, max_length=100)
    remarks: Optional[str] = Field(None, max_length=2000)
    # The statement it pays; none — a payment on account, applied oldest statement first.
    statement: Optional[str] = Field(None, max_length=100)


def _view(m: vm.Mapping, s: _Scope) -> dict:
    if s.view not in vm.VIEWS:
        raise HTTPException(400, f"Unknown view “{s.view}”.")
    try:
        return vm.mapping_view(m, vendor=s.vendor, statement=s.statement, view=s.view, q=s.q,
                               offset=s.offset, limit=s.limit)
    except LookupError:
        raise HTTPException(404, "That statement is not loaded — it may have been deleted.")


@router.get("/vendor-mapping")
async def vendor_mapping(
    vendor: Optional[str] = Query(None, max_length=600, description="A vendor id from `options.vendors`"),
    statement: Optional[str] = Query(None, max_length=100, description="One vendor statement (batch id)"),
    view: str = Query("all", description="all | matched | fare_diff | not_in_mo | other_vendor | open | "
                                         "on_hold | claims | resolved"),
    q: Optional[str] = Query(None, max_length=200, description="Ticket, passenger, PNR or reference"),
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=5000),
    refresh: bool = Query(False, description="Build the mapping afresh rather than reuse the one kept"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = await vm.load(db, current_user.tenant_id, current_user.id, fresh=refresh)
    return _view(m, _Scope(vendor=vendor, statement=statement, view=view, q=q, offset=offset, limit=limit))


@router.post("/vendor-mapping/decisions")
async def decide_lines(
    body: DecideBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Close lines with one decision. Returns the mapping as it now stands."""
    try:
        m = await vm.decide(db, tenant_id=current_user.tenant_id, user_id=current_user.id,
                            keys=body.keys, decision=body.decision, note=body.note)
    except vm.MappingError as e:
        raise HTTPException(400, str(e))
    except LookupError:
        raise HTTPException(409, "Some of these lines have changed since the screen was loaded — "
                                 "refresh and try again.")
    return _view(m, body)


@router.post("/vendor-mapping/decisions/reopen")
async def reopen_lines(
    body: ReopenBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Withdraw the decision on these lines, putting them back with the open ones."""
    m = await vm.reopen(db, tenant_id=current_user.tenant_id, user_id=current_user.id, keys=body.keys)
    return _view(m, body)


@router.get("/vendor-accounts")
async def vendor_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = await vm.load(db, current_user.tenant_id, current_user.id)
    payments = await vm.payments_of(db, current_user.tenant_id, current_user.id)
    return vm.accounts(m, payments, date.today())


@router.get("/vendor-accounts/detail")
async def vendor_account(
    vendor: str = Query(..., min_length=1, max_length=600),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = await vm.load(db, current_user.tenant_id, current_user.id)
    payments = await vm.payments_of(db, current_user.tenant_id, current_user.id, vendor)
    if vendor not in m.book.vendors and not payments and not any(
            s.vendor_key == vendor for s in m.book.stmts.values()):
        raise HTTPException(404, "Vendor not found.")
    return vm.account(m, vendor, payments, date.today())


@router.post("/vendor-accounts/payments")
async def record_payment(
    body: PaymentBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record a payment made to a vendor. Returns the vendor's account as it now stands."""
    book = await recon.load_book(db, current_user.tenant_id, current_user.id,
                                 vendor_slugs=vm.VENDOR_SLUGS, internal_category=vm.MO_CATEGORY)
    try:
        await vm.record_payment(
            db, tenant_id=current_user.tenant_id, user_id=current_user.id, book=book,
            vendor_key=body.vendor, payment_date=body.payment_date, amount=body.amount, mode=body.mode,
            reference=body.reference, remarks=body.remarks, statement=body.statement, today=date.today(),
        )
    except vm.MappingError as e:
        raise HTTPException(400, str(e))
    m = await vm.load(db, current_user.tenant_id, current_user.id)
    payments = await vm.payments_of(db, current_user.tenant_id, current_user.id, body.vendor)
    return vm.account(m, body.vendor, payments, date.today())
