"""Vendors data → Payment Module: statement checks, decisions, payments, outstanding.

Mounted at `/payment-module`, beside `/payment-module/reconciliation`:

  /checks …                 steps 2, 3, 5 — completeness and vendor check per upload
  /items/{id}/decision      step 10 — record Operations' decision on one billed ticket
  /items/bulk-decision      the same for many
  /payable                  step 11 — what a statement asks, what is approved, what is due
  /payments …               step 12 — record, list, open and void payments
  /outstanding              step 13 — every unpaid ticket still owed or in question
  /mo-vendor-corrections …  step 6C — file an MO ticket under the vendor that billed it

Scoped (tenant, user) like every statement and reconciliation router.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.payment_ledger import (
    MoVendorCorrection, PaymentItem, VendorAccount, VendorPayment,
)
from app.models.payment_reconciliation import MO_VENDOR_OTHER, PaymentReconciliation
from app.models.statement_batch_control import StatementBatchControl
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import STATEMENT_MODELS
from app.models.user import User
from app.schemas.payment_reconciliation import (
    BulkDecisionPayload, ConfirmAccountPayload, ControlsPayload, CorrectionPayload,
    DecisionPayload, OutstandingPage, PayableSummary, PaymentCreatePayload, PaymentItemRead,
    VendorPaymentDetail, VendorPaymentRead, VoidPayload,
)
from app.services import payment_ledger, statement_balance, statement_checks
from app.services import statement_spec as spec

router = APIRouter()

VENDOR_SLUG = "tp-gds"


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _dec(value: str | None, label: str) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    d = statement_balance.to_decimal(value)
    if d is None:
        raise HTTPException(status_code=400, detail=f"{label} must be a number.")
    return d


def _item_read(i: PaymentItem, now: datetime | None = None) -> PaymentItemRead:
    now = now or datetime.utcnow()
    age = (now - i.statement_uploaded_at).days if i.statement_uploaded_at else None
    return PaymentItemRead(
        id=i.id, vendor_batch_id=i.vendor_batch_id, vendor_source_file=i.vendor_source_file,
        statement_uploaded_at=i.statement_uploaded_at, supplier_id=i.supplier_id,
        supplier_name=i.supplier_name, ticket_key=i.ticket_key,
        ticket_number=i.ticket_number, ticket_prefix=i.ticket_prefix, pax_name=i.pax_name,
        airline_name=i.airline_name, issue_date=i.issue_date, sector=i.sector,
        booking_id=i.booking_id, match_status=i.match_status,
        is_duplicate=bool(i.is_duplicate), not_billed=bool(i.not_billed),
        mo_vendor_status=i.mo_vendor_status, vendor_net=_f(i.vendor_net), mo_net=_f(i.mo_net),
        net_variance=_f(i.net_variance), commission_shortfall=_f(i.commission_shortfall),
        suggested_payable=_f(i.suggested_payable), decision_status=i.decision_status,
        decision_source=i.decision_source, decision_action=i.decision_action,
        approved_amount=_f(i.approved_amount), decision_reason=i.decision_reason,
        remarks=i.remarks, ops_reference=i.ops_reference, payment_id=i.payment_id,
        paid_amount=_f(i.paid_amount), paid_at=i.paid_at, stale=bool(i.stale), age_days=age,
    )


# ── steps 2, 3, 5: checks ────────────────────────────────────────────────────
def _controls_slug(slug: str) -> str:
    s = (slug or "").lower()
    if s not in STATEMENT_MODELS or not spec.captures_controls(s):
        raise HTTPException(status_code=404,
                            detail=f"'{slug}' statements do not carry completeness checks.")
    return s


async def _upload_exists(db: AsyncSession, slug: str, user: User, batch_id: str) -> bool:
    m = STATEMENT_MODELS[slug]
    found = await db.scalar(select(m.id).where(
        m.batch_id == batch_id, m.tenant_id == user.tenant_id,
        m.created_by_id == user.id).limit(1))
    return found is not None


@router.get("/checks")
async def list_checks(
    slug: str = Query(..., description="tp-gds or mo-gds"),
    batch_id: list[str] | None = Query(None, description="Uploads to check; all when absent"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per upload: verdict (complete | attention | incomplete | unverified), each check
    with its reason, and the figures behind them."""
    slug = _controls_slug(slug)
    return await statement_checks.check_uploads(
        db, slug, current_user.tenant_id, current_user.id, batch_id or None)


@router.put("/checks/{slug}/{batch_id}")
async def set_controls(
    slug: str, batch_id: str, payload: ControlsPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enter or correct an upload's control totals, or the opening balance a file did not
    print. Works for uploads made before control figures were captured, too."""
    slug = _controls_slug(slug)
    if not await _upload_exists(db, slug, current_user, batch_id):
        raise HTTPException(status_code=404, detail="Upload not found.")
    ctl = (await db.execute(select(StatementBatchControl).where(
        StatementBatchControl.slug == slug, StatementBatchControl.batch_id == batch_id,
        StatementBatchControl.tenant_id == current_user.tenant_id))).scalar_one_or_none()
    if ctl is None:
        ctl = StatementBatchControl(tenant_id=current_user.tenant_id,
                                    created_by_id=current_user.id, slug=slug, batch_id=batch_id)
        db.add(ctl)
    if payload.expected_count is not None:
        if payload.expected_count < 0:
            raise HTTPException(status_code=400, detail="Expected records cannot be negative.")
        ctl.expected_count = payload.expected_count or None
    if payload.expected_amount is not None:
        ctl.expected_amount = _dec(payload.expected_amount, "Expected net amount")
    if payload.opening_balance is not None:
        ctl.opening_balance = _dec(payload.opening_balance, "Opening balance")
        ctl.opening_source = "user" if ctl.opening_balance is not None else None
    for name in payload.clear:
        if name == "expected_count":
            ctl.expected_count = None
        elif name == "expected_amount":
            ctl.expected_amount = None
        elif name == "opening_balance":
            ctl.opening_balance, ctl.opening_source = None, None
    await db.commit()
    result = await statement_checks.check_uploads(
        db, slug, current_user.tenant_id, current_user.id, [batch_id])
    return result.get(batch_id)


@router.post("/checks/{slug}/{batch_id}/confirm-account")
async def confirm_account(
    slug: str, batch_id: str, payload: ConfirmAccountPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remember this statement's Customer ID as your account with its vendor (step 3)."""
    slug = _controls_slug(slug)
    if slug != VENDOR_SLUG:
        raise HTTPException(status_code=400, detail="Only vendor statements carry a vendor account.")
    if not await _upload_exists(db, slug, current_user, batch_id):
        raise HTTPException(status_code=404, detail="Upload not found.")
    link = (await db.execute(select(StatementBatchSupplier).where(
        StatementBatchSupplier.slug == slug, StatementBatchSupplier.batch_id == batch_id,
        StatementBatchSupplier.tenant_id == current_user.tenant_id))).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=409,
                            detail="This upload has no vendor, so there is nothing to confirm against.")
    facts = (await statement_checks.load_facts(
        db, slug, current_user.tenant_id, current_user.id, [batch_id])).get(batch_id)
    accounts = facts.accounts if facts else {}
    account = statement_checks.normalize_account(payload.account_id)
    if account is None:
        if len(accounts) != 1:
            raise HTTPException(status_code=400,
                                detail="Say which Customer ID is your account with this vendor.")
        account = next(iter(accounts))
    name = (accounts.get(account) or (None, 0))[0]
    exists = await db.scalar(select(VendorAccount.id).where(
        VendorAccount.tenant_id == current_user.tenant_id,
        VendorAccount.created_by_id == current_user.id,
        VendorAccount.supplier_id == link.supplier_id, VendorAccount.account_id == account))
    if exists is None:
        db.add(VendorAccount(tenant_id=current_user.tenant_id, created_by_id=current_user.id,
                             supplier_id=link.supplier_id, account_id=account,
                             account_name=name))
        await db.commit()
    result = await statement_checks.check_uploads(
        db, slug, current_user.tenant_id, current_user.id, [batch_id])
    return result.get(batch_id)


# ── step 10: decisions ───────────────────────────────────────────────────────
async def _item(db: AsyncSession, user: User, item_id: int) -> PaymentItem:
    item = (await db.execute(select(PaymentItem).where(
        PaymentItem.id == item_id, PaymentItem.tenant_id == user.tenant_id,
        PaymentItem.created_by_id == user.id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return item


@router.put("/items/{item_id}/decision", response_model=PaymentItemRead)
async def set_decision(
    item_id: int, payload: DecisionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await _item(db, current_user, item_id)
    try:
        payment_ledger.decide(
            item, action=payload.action, user_id=current_user.id,
            amount=_dec(payload.amount, "Amount"), remarks=payload.remarks,
            ops_reference=payload.ops_reference)
    except payment_ledger.LedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    await db.refresh(item)
    return _item_read(item)


@router.post("/items/bulk-decision")
async def bulk_decision(
    payload: BulkDecisionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The same decision on many tickets. Paid or refused tickets are reported, not failed."""
    if not payload.item_ids:
        raise HTTPException(status_code=400, detail="Select at least one ticket.")
    items = (await db.execute(select(PaymentItem).where(
        PaymentItem.id.in_(payload.item_ids), PaymentItem.tenant_id == current_user.tenant_id,
        PaymentItem.created_by_id == current_user.id))).scalars().all()
    amount = _dec(payload.amount, "Amount")
    updated, refused = 0, []
    for item in items:
        try:
            payment_ledger.decide(item, action=payload.action, user_id=current_user.id,
                                  amount=amount, remarks=payload.remarks,
                                  ops_reference=payload.ops_reference)
            updated += 1
        except payment_ledger.LedgerError as exc:
            refused.append({"id": item.id, "ticket": item.ticket_number, "reason": str(exc)})
    await db.commit()
    return {"updated": updated, "refused": refused}


# ── step 11: payable ─────────────────────────────────────────────────────────
@router.get("/payable", response_model=PayableSummary)
async def payable(
    vendor_batch_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = await payment_ledger.payable_summary(db, current_user.tenant_id, current_user.id,
                                             vendor_batch_id)
    now = datetime.utcnow()
    return PayableSummary(**{
        **{k: v for k, v in s.items() if k not in ("items", "payable_item_ids")},
        **{k: float(s[k]) for k in ("billed", "commission_shortfall", "suggested", "excluded",
                                    "pending", "held", "approved", "brought_forward", "paid",
                                    "final_payable")},
        "items": [_item_read(i, now) for i in s["items"]],
    })


# ── step 12: payments ────────────────────────────────────────────────────────
async def _payment_read(db: AsyncSession, p: VendorPayment) -> VendorPaymentRead:
    source_file = None
    if p.vendor_batch_id:
        m = STATEMENT_MODELS[VENDOR_SLUG]
        source_file = await db.scalar(select(m.source_file).where(
            m.batch_id == p.vendor_batch_id, m.tenant_id == p.tenant_id).limit(1))
    return VendorPaymentRead(
        id=p.id, supplier_id=p.supplier_id, supplier_name=p.supplier_name,
        vendor_batch_id=p.vendor_batch_id, vendor_source_file=source_file,
        payment_date=p.payment_date, amount=float(p.amount), mode=p.mode,
        reference=p.reference, remarks=p.remarks, items_count=p.items_count,
        status=p.status, void_reason=p.void_reason, voided_at=p.voided_at,
        created_at=p.created_at)


@router.post("/payments", response_model=VendorPaymentRead)
async def record_payment(
    payload: PaymentCreatePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        p = await payment_ledger.create_payment(
            db, tenant_id=current_user.tenant_id, user_id=current_user.id,
            supplier_id=payload.supplier_id, vendor_batch_id=payload.vendor_batch_id,
            item_ids=payload.item_ids, payment_date=payload.payment_date, mode=payload.mode,
            reference=payload.reference, remarks=payload.remarks)
    except payment_ledger.LedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return await _payment_read(db, p)


@router.get("/payments", response_model=list[VendorPaymentRead])
async def list_payments(
    supplier_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(VendorPayment).where(VendorPayment.tenant_id == current_user.tenant_id,
                                    VendorPayment.created_by_id == current_user.id)
    if supplier_id is not None:
        q = q.where(VendorPayment.supplier_id == supplier_id)
    rows = (await db.execute(q.order_by(VendorPayment.payment_date.desc(),
                                        VendorPayment.id.desc()))).scalars().all()
    return [await _payment_read(db, p) for p in rows]


@router.get("/payments/{payment_id}", response_model=VendorPaymentDetail)
async def payment_detail(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = (await db.execute(select(VendorPayment).where(
        VendorPayment.id == payment_id, VendorPayment.tenant_id == current_user.tenant_id,
        VendorPayment.created_by_id == current_user.id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    items = (await db.execute(select(PaymentItem).where(
        PaymentItem.payment_id == p.id, PaymentItem.tenant_id == current_user.tenant_id,
        PaymentItem.created_by_id == current_user.id).order_by(PaymentItem.id))).scalars().all()
    base = await _payment_read(db, p)
    return VendorPaymentDetail(**base.model_dump(), items=[_item_read(i) for i in items])


@router.post("/payments/{payment_id}/void", response_model=VendorPaymentRead)
async def void_payment(
    payment_id: int, payload: VoidPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        p = await payment_ledger.void_payment(
            db, tenant_id=current_user.tenant_id, user_id=current_user.id,
            payment_id=payment_id, reason=payload.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except payment_ledger.LedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return await _payment_read(db, p)


# ── step 13: outstanding ─────────────────────────────────────────────────────
@router.get("/outstanding", response_model=OutstandingPage)
async def outstanding(
    supplier_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = await payment_ledger.outstanding(db, current_user.tenant_id, current_user.id,
                                             supplier_id)
    now = datetime.utcnow()
    totals: dict = {}
    for i in items:
        t = totals.setdefault(i.decision_status, {"count": 0, "amount": 0.0})
        t["count"] += 1
        amount = i.approved_amount if i.decision_status == "approved" else i.suggested_payable
        t["amount"] = round(t["amount"] + float(amount or 0), 2)
    return OutstandingPage(supplier_id=supplier_id, totals=totals,
                           items=[_item_read(i, now) for i in items])


# ── step 6C: correct the vendor of an MO ticket ──────────────────────────────
@router.post("/mo-vendor-corrections")
async def correct_mo_vendor(
    payload: CorrectionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """File an MO ticket that sits in another vendor's MO file under the vendor whose
    statement billed it. The next reconciliation pairs it here; commission income uses it."""
    r = (await db.execute(select(PaymentReconciliation).where(
        PaymentReconciliation.id == payload.reconciliation_id,
        PaymentReconciliation.tenant_id == current_user.tenant_id,
        PaymentReconciliation.created_by_id == current_user.id))).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Reconciliation row not found.")
    info = r.mo_vendor_info or {}
    if r.mo_vendor_status != MO_VENDOR_OTHER or not info.get("batch_id") or not r.ticket_key:
        raise HTTPException(status_code=400,
                            detail="Only a ticket found in another vendor's MO file can be corrected.")
    to = (await db.execute(select(StatementBatchSupplier).where(
        StatementBatchSupplier.slug == VENDOR_SLUG,
        StatementBatchSupplier.batch_id == r.vendor_batch_id,
        StatementBatchSupplier.tenant_id == current_user.tenant_id))).scalar_one_or_none()
    if to is None:
        raise HTTPException(status_code=409, detail="The vendor statement has no vendor.")
    existing = (await db.execute(select(MoVendorCorrection).where(
        MoVendorCorrection.tenant_id == current_user.tenant_id,
        MoVendorCorrection.created_by_id == current_user.id,
        MoVendorCorrection.mo_batch_id == info["batch_id"],
        MoVendorCorrection.ticket_key == r.ticket_key))).scalar_one_or_none()
    c = existing or MoVendorCorrection(
        tenant_id=current_user.tenant_id, created_by_id=current_user.id,
        mo_batch_id=info["batch_id"], ticket_key=r.ticket_key)
    c.ticket_number = r.ticket_number
    c.from_supplier_id = info.get("supplier_id")
    c.from_supplier_name = info.get("supplier_name")
    c.to_supplier_id, c.to_supplier_name, c.to_supplier_code = (
        to.supplier_id, to.supplier_name, to.supplier_code)
    c.vendor_batch_id = r.vendor_batch_id
    c.remarks = (payload.remarks or "").strip() or None
    if existing is None:
        db.add(c)
    await db.commit()
    return {"id": c.id, "mo_batch_id": c.mo_batch_id, "ticket_key": c.ticket_key,
            "from_supplier_name": c.from_supplier_name, "to_supplier_name": c.to_supplier_name}


@router.get("/mo-vendor-corrections")
async def list_corrections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (await db.execute(select(MoVendorCorrection).where(
        MoVendorCorrection.tenant_id == current_user.tenant_id,
        MoVendorCorrection.created_by_id == current_user.id
    ).order_by(MoVendorCorrection.created_at.desc()))).scalars().all()
    return [{"id": c.id, "mo_batch_id": c.mo_batch_id, "ticket_key": c.ticket_key,
             "ticket_number": c.ticket_number, "from_supplier_name": c.from_supplier_name,
             "to_supplier_name": c.to_supplier_name, "vendor_batch_id": c.vendor_batch_id,
             "remarks": c.remarks, "created_at": c.created_at} for c in rows]


@router.delete("/mo-vendor-corrections/{correction_id}")
async def delete_correction(
    correction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    c = (await db.execute(select(MoVendorCorrection).where(
        MoVendorCorrection.id == correction_id,
        MoVendorCorrection.tenant_id == current_user.tenant_id,
        MoVendorCorrection.created_by_id == current_user.id))).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Correction not found.")
    await db.delete(c)
    await db.commit()
    return {"deleted": correction_id}
