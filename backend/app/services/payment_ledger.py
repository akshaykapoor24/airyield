"""Payment Module steps 10–13: decide each billed ticket, pay the approved ones, carry the rest.

`payment_items` is the ledger — one row per billed vendor ticket per vendor upload. Every
reconciliation run refreshes its SNAPSHOT (figures, flags); the DECISION and PAYMENT on it
are never overwritten by a run:

  * While `decision_source = auto`, the system decides (`auto_decision`): a duplicate is
    excluded (step 6B), a clean match is approved at the payable after commission, anything
    else waits for Operations with the reason spelled out.
  * Once a person decides (`decide`), the item keeps that decision across re-runs. For the
    rule-based actions (pay suggested / vendor / MO amount) the amount follows the latest
    figures; a custom amount is fixed.
  * A paid item is frozen. Voiding its payment returns it to unpaid.

Final payable for a statement (step 11) = its approved, unpaid items + the approved, unpaid
items of the same vendor's EARLIER statements (brought forward, step 13). Anything held or
pending stays outstanding and is offered again with the next statement — or released on
its own, on any date, from the Outstanding list.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_ledger import (
    ACTION_AUTO_CLEAN, ACTION_AUTO_DUPLICATE, ACTION_EXCLUDE, ACTION_HOLD, ACTION_PAY_CUSTOM,
    ACTION_PAY_MO, ACTION_PAY_SUGGESTED, ACTION_PAY_VENDOR, DECISION_APPROVED,
    DECISION_EXCLUDED, DECISION_HELD, DECISION_PENDING, PAYMENT_COMPLETED, PAYMENT_MODES,
    PAYMENT_VOIDED, SOURCE_AUTO, SOURCE_USER, USER_ACTIONS, MoVendorCorrection, PaymentItem,
    VendorPayment,
)
from app.models.payment_reconciliation import (
    MO_VENDOR_CORRECTED, MO_VENDOR_OK, MO_VENDOR_OTHER, STATUS_MATCHED, STATUS_MINOR_DIFF,
    STATUS_MISMATCH, STATUS_POSSIBLE, STATUS_VENDOR_ONLY,
    PaymentReconciliation, PaymentReconciliationRun,
)

VENDOR_SLUG = "tp-gds"
MO_SLUG = "mo-gds"
ACTION_AUTO = "auto"            # "let the system decide again"
_REQUIRES_REMARKS = (ACTION_PAY_CUSTOM, ACTION_HOLD, ACTION_EXCLUDE)


class LedgerError(ValueError):
    """A request the ledger refuses; the message is written for the user."""


def _dec(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def _money(v) -> str:
    d = _dec(v)
    return "—" if d is None else f"₹{d.quantize(Decimal('0.01')):,}"


# ── the automatic decision ───────────────────────────────────────────────────
def auto_decision(snap: dict) -> tuple[str, str | None, Decimal | None, str]:
    """(decision_status, action, approved_amount, reason) from a ticket's snapshot.

    `snap` carries: is_duplicate, duplicate_info, commission_ran, income_needs_data,
    match_status, not_billed, mo_vendor_status, mo_vendor_info, net_variance, vendor_net,
    suggested_payable. Pure — the same answer for a sync and for "revert to automatic".
    """
    if snap.get("is_duplicate"):
        info = snap.get("duplicate_info") or {}
        if info.get("kind") == "within":
            why = f"billed {info.get('sale_rows')} times in this statement"
        else:
            why = f"already billed on {info.get('source_file') or 'an earlier statement'}"
            if info.get("paid"):
                why += " and paid"
        return DECISION_EXCLUDED, ACTION_AUTO_DUPLICATE, None, \
            f"Duplicate — {why}. Ignored for payout."
    if not snap.get("commission_ran"):
        return DECISION_PENDING, None, None, \
            "Income not calculated yet — press Calculate income first."
    if snap.get("income_needs_data"):
        return DECISION_PENDING, None, None, \
            "Income needs data — a deal may apply but the row lacks what it depends on."

    status = snap.get("match_status")
    problems: list[str] = []
    if status == STATUS_VENDOR_ONLY:
        problems.append("Billed by the vendor but not in the MO statement")
    elif status == STATUS_POSSIBLE:
        problems.append("Same serial, different airline in MO — check the ticket")
    elif status in (STATUS_MISMATCH, STATUS_MINOR_DIFF):
        nv = _dec(snap.get("net_variance"))
        if nv is not None and abs(nv) >= Decimal("0.01"):
            problems.append(f"Net differs from MO by {_money(nv)}")
        else:
            problems.append("Figures differ from MO" if status == STATUS_MISMATCH
                            else "Minor differences from MO (tax, commission or fees)")
    if snap.get("mo_vendor_status") == MO_VENDOR_OTHER:
        other = (snap.get("mo_vendor_info") or {}).get("supplier_name") or "another vendor"
        problems.append(f"In {other}'s MO file — correct the vendor in MO")
    if snap.get("not_billed"):
        problems.append("No booking ID in MO — confirm it was billed")
    if problems:
        return DECISION_PENDING, None, None, "; ".join(problems) + "."

    if status == STATUS_MATCHED and snap.get("mo_vendor_status") in (MO_VENDOR_OK, MO_VENDOR_CORRECTED):
        amount = _dec(snap.get("suggested_payable"))
        if amount is None:
            amount = _dec(snap.get("vendor_net"))
        return DECISION_APPROVED, ACTION_AUTO_CLEAN, amount, \
            "Matched the MO statement — approved at the payable after commission."
    return DECISION_PENDING, None, None, "Needs a decision."


def amount_for(item: PaymentItem, action: str, custom: Decimal | None = None) -> Decimal | None:
    """The approved amount an action implies, from the item's current figures."""
    if action == ACTION_PAY_SUGGESTED:
        v = _dec(item.suggested_payable)
        return v if v is not None else _dec(item.vendor_net)
    if action == ACTION_PAY_VENDOR:
        return _dec(item.vendor_net)
    if action == ACTION_PAY_MO:
        return _dec(item.mo_net)
    if action == ACTION_PAY_CUSTOM:
        return custom if custom is not None else _dec(item.approved_amount)
    return None


def _status_for(action: str) -> str:
    if action == ACTION_HOLD:
        return DECISION_HELD
    if action == ACTION_EXCLUDE:
        return DECISION_EXCLUDED
    return DECISION_APPROVED


def _snapshot_of(item: PaymentItem) -> dict:
    return {
        "is_duplicate": item.is_duplicate, "duplicate_info": None,
        "commission_ran": item.commission_ran, "income_needs_data": item.income_needs_data,
        "match_status": item.match_status, "not_billed": item.not_billed,
        "mo_vendor_status": item.mo_vendor_status, "mo_vendor_info": None,
        "net_variance": item.net_variance, "vendor_net": item.vendor_net,
        "suggested_payable": item.suggested_payable,
    }


def _apply_auto(item: PaymentItem, snap: dict) -> None:
    status, action, amount, reason = auto_decision(snap)
    item.decision_status, item.decision_action = status, action
    item.approved_amount, item.decision_reason = amount, reason


# ── sync after a reconciliation run ──────────────────────────────────────────
async def sync_items(db: AsyncSession, *, tenant_id: int, user_id: int, vendor_batch_id: str,
                     mo_batch_id: str, vendor_supplier: dict | None, vendor_file: str | None,
                     vendor_uploaded_at: datetime | None, results: list[dict],
                     commission_ran: bool, now: datetime) -> None:
    """Refresh every billed ticket's item from this run's results. Decisions survive."""
    existing = {i.ticket_key: i for i in (await db.execute(
        select(PaymentItem).where(PaymentItem.tenant_id == tenant_id,
                                  PaymentItem.created_by_id == user_id,
                                  PaymentItem.vendor_batch_id == vendor_batch_id)
    )).scalars().all()}
    seen: set[str] = set()
    for r in results:
        if not r.get("vendor_row_ids") or not r.get("ticket_key"):
            continue                    # an MO-only ticket: nothing was billed
        key = r["ticket_key"]
        seen.add(key)
        item = existing.get(key)
        if item is None:
            item = PaymentItem(tenant_id=tenant_id, created_by_id=user_id,
                               vendor_batch_id=vendor_batch_id, ticket_key=key,
                               decision_status=DECISION_PENDING, decision_source=SOURCE_AUTO)
            db.add(item)
            existing[key] = item
        item.stale = False
        item.synced_at = now
        if item.payment_id is not None:
            continue                    # paid: the snapshot it was paid on stays as it was
        needs_data = any(d.get("status") == "needs_data"
                         for d in (r.get("commission_detail") or []))
        item.supplier_id = (vendor_supplier or {}).get("supplier_id")
        item.supplier_name = (vendor_supplier or {}).get("supplier_name")
        item.vendor_source_file = vendor_file
        item.statement_uploaded_at = vendor_uploaded_at
        item.mo_batch_id = mo_batch_id
        for attr in ("ticket_number", "ticket_prefix", "pax_name", "airline_name",
                     "issue_date", "sector", "booking_id", "vendor_row_ids", "match_status",
                     "mo_vendor_status", "commission_status", "vendor_net", "mo_net",
                     "net_variance", "calc_commission", "commission_shortfall"):
            setattr(item, attr, r.get(attr))
        item.is_duplicate = bool(r.get("is_duplicate"))
        item.not_billed = bool(r.get("not_billed"))
        item.income_needs_data = needs_data
        item.commission_ran = commission_ran
        item.suggested_payable = r.get("payable_after_commission")
        if item.decision_source == SOURCE_AUTO:
            _apply_auto(item, {**r, "commission_ran": commission_ran,
                               "income_needs_data": needs_data,
                               "suggested_payable": r.get("payable_after_commission")})
        elif item.decision_action in (ACTION_PAY_SUGGESTED, ACTION_PAY_VENDOR, ACTION_PAY_MO):
            item.approved_amount = amount_for(item, item.decision_action)
    for key, item in existing.items():
        if key in seen:
            continue
        if item.payment_id is None and item.decision_source == SOURCE_AUTO:
            await db.delete(item)
        else:
            item.stale = True
    await db.flush()


# ── a person's decision ──────────────────────────────────────────────────────
def decide(item: PaymentItem, *, action: str, user_id: int, amount: Decimal | None = None,
           remarks: str | None = None, ops_reference: str | None = None,
           now: datetime | None = None) -> None:
    """Record Operations' decision on one item. Raises LedgerError on a refused request."""
    if item.payment_id is not None:
        raise LedgerError("This ticket is already paid. Void the payment to change it.")
    remarks = (remarks or "").strip() or None
    ops_reference = (ops_reference or "").strip() or None
    if action == ACTION_AUTO:
        item.decision_source = SOURCE_AUTO
        item.remarks, item.ops_reference = remarks, ops_reference
        item.decided_by_id, item.decided_at = user_id, now or datetime.utcnow()
        _apply_auto(item, _snapshot_of(item))
        return
    if action not in USER_ACTIONS:
        raise LedgerError(f"Unknown action '{action}'.")
    if action in _REQUIRES_REMARKS and not remarks:
        raise LedgerError("Add a remark saying why — it is what Operations' decision rests on.")
    if action == ACTION_PAY_CUSTOM and amount is None:
        raise LedgerError("Enter the amount Operations agreed.")
    if action == ACTION_PAY_MO and item.mo_net is None:
        raise LedgerError("There is no MO amount for this ticket.")
    if action == ACTION_PAY_VENDOR and item.vendor_net is None:
        raise LedgerError("There is no vendor amount for this ticket.")
    item.decision_source = SOURCE_USER
    item.decision_action = action
    item.decision_status = _status_for(action)
    item.approved_amount = amount_for(item, action, amount) if item.decision_status == DECISION_APPROVED else None
    item.decision_reason = None
    item.remarks, item.ops_reference = remarks, ops_reference
    item.decided_by_id, item.decided_at = user_id, now or datetime.utcnow()


# ── payable, payments, outstanding ───────────────────────────────────────────
def _scope(tenant_id: int, user_id: int):
    return (PaymentItem.tenant_id == tenant_id, PaymentItem.created_by_id == user_id)


async def payable_summary(db: AsyncSession, tenant_id: int, user_id: int,
                          vendor_batch_id: str) -> dict:
    """Step 11: what this statement asks for, what was decided, and what is payable now."""
    items = list((await db.execute(
        select(PaymentItem).where(*_scope(tenant_id, user_id),
                                  PaymentItem.vendor_batch_id == vendor_batch_id)
    )).scalars().all())
    supplier_id = next((i.supplier_id for i in items if i.supplier_id is not None), None)
    uploaded = next((i.statement_uploaded_at for i in items if i.statement_uploaded_at), None)

    brought: list[PaymentItem] = []
    if supplier_id is not None:
        q = select(PaymentItem).where(
            *_scope(tenant_id, user_id), PaymentItem.supplier_id == supplier_id,
            PaymentItem.vendor_batch_id != vendor_batch_id,
            PaymentItem.payment_id.is_(None), PaymentItem.stale.is_(False),
            PaymentItem.decision_status == DECISION_APPROVED)
        if uploaded is not None:
            q = q.where(PaymentItem.statement_uploaded_at < uploaded)
        brought = list((await db.execute(q)).scalars().all())

    def total(rows, attr):
        return sum((_dec(getattr(r, attr)) or Decimal("0") for r in rows), Decimal("0"))

    live = [i for i in items if not i.stale]
    by = {s: [i for i in live if i.decision_status == s and i.payment_id is None]
          for s in (DECISION_APPROVED, DECISION_PENDING, DECISION_HELD, DECISION_EXCLUDED)}
    paid = [i for i in items if i.payment_id is not None]
    approved_now = total(by[DECISION_APPROVED], "approved_amount")
    brought_total = total(brought, "approved_amount")
    return {
        "vendor_batch_id": vendor_batch_id,
        "supplier_id": supplier_id,
        "supplier_name": next((i.supplier_name for i in items if i.supplier_name), None),
        "source_file": next((i.vendor_source_file for i in items if i.vendor_source_file), None),
        "tickets": len(live),
        "billed": str(total(live, "vendor_net")),
        "commission_shortfall": str(total(live, "commission_shortfall")),
        "suggested": str(total(live, "suggested_payable")),
        "counts": {k: len(v) for k, v in by.items()} | {"paid": len(paid),
                                                         "brought_forward": len(brought)},
        "excluded": str(total(by[DECISION_EXCLUDED], "suggested_payable")),
        "pending": str(total(by[DECISION_PENDING], "suggested_payable")),
        "held": str(total(by[DECISION_HELD], "suggested_payable")),
        "approved": str(approved_now),
        "brought_forward": str(brought_total),
        "paid": str(total(paid, "paid_amount")),
        "final_payable": str(approved_now + brought_total),
        "payable_item_ids": [i.id for i in by[DECISION_APPROVED]] + [i.id for i in brought],
        "items": by[DECISION_APPROVED] + brought,
    }


def payment_total(items: list[PaymentItem], supplier_id: int | None = None) -> Decimal:
    """What paying these tickets in full comes to. LedgerError when they cannot be paid
    together: one is paid already or not approved, they span vendors, or they come to
    nothing — refunds outweighing sales are a credit to carry, not a payment to record."""
    for i in items:
        if i.payment_id is not None:
            raise LedgerError(f"Ticket {i.ticket_number or i.ticket_key} is already paid.")
        if i.decision_status != DECISION_APPROVED or i.approved_amount is None:
            raise LedgerError(f"Ticket {i.ticket_number or i.ticket_key} is not approved for payment.")
        if supplier_id is not None and i.supplier_id != supplier_id:
            raise LedgerError("All tickets in one payment must be from the same vendor.")
    if len({i.supplier_id for i in items}) > 1:
        raise LedgerError("All tickets in one payment must be from the same vendor.")
    amount = sum((_dec(i.approved_amount) for i in items), Decimal("0"))
    if amount <= 0:
        raise LedgerError(f"The selected tickets come to {_money(amount)} — refunds and "
                          f"cancellations outweigh the sales, so there is nothing to pay. "
                          f"Pay them together with tickets that bring the total above zero.")
    return amount


async def create_payment(db: AsyncSession, *, tenant_id: int, user_id: int,
                         supplier_id: int | None, vendor_batch_id: str | None,
                         item_ids: list[int], payment_date: date, mode: str | None,
                         reference: str | None, remarks: str | None) -> VendorPayment:
    """Step 12: pay the chosen approved items in full and mark them paid."""
    if not item_ids:
        raise LedgerError("Select at least one approved ticket to pay.")
    if mode and mode not in PAYMENT_MODES:
        raise LedgerError(f"Payment mode must be one of {', '.join(PAYMENT_MODES)}.")
    items = list((await db.execute(
        select(PaymentItem).where(*_scope(tenant_id, user_id), PaymentItem.id.in_(item_ids))
    )).scalars().all())
    if len(items) != len(set(item_ids)):
        raise LedgerError("Some of the selected tickets no longer exist — refresh and try again.")
    amount = payment_total(items, supplier_id)
    suppliers = {i.supplier_id for i in items}
    now = datetime.utcnow()
    payment = VendorPayment(
        tenant_id=tenant_id, created_by_id=user_id,
        supplier_id=next(iter(suppliers)), supplier_name=items[0].supplier_name,
        vendor_batch_id=vendor_batch_id, payment_date=payment_date, amount=amount,
        mode=mode, reference=(reference or "").strip() or None,
        remarks=(remarks or "").strip() or None, items_count=len(items),
        status=PAYMENT_COMPLETED, created_at=now,
    )
    db.add(payment)
    await db.flush()
    for i in items:
        i.payment_id = payment.id
        i.paid_amount = i.approved_amount
        i.paid_at = now
    await db.flush()
    return payment


async def void_payment(db: AsyncSession, *, tenant_id: int, user_id: int, payment_id: int,
                       reason: str | None) -> VendorPayment:
    """Undo a payment: its items return to unpaid with their decisions intact."""
    payment = (await db.execute(
        select(VendorPayment).where(VendorPayment.id == payment_id,
                                    VendorPayment.tenant_id == tenant_id,
                                    VendorPayment.created_by_id == user_id)
    )).scalar_one_or_none()
    if payment is None:
        raise LookupError("Payment not found.")
    if payment.status == PAYMENT_VOIDED:
        raise LedgerError("This payment is already void.")
    if not (reason or "").strip():
        raise LedgerError("Say why the payment is being voided.")
    payment.status = PAYMENT_VOIDED
    payment.void_reason = reason.strip()
    payment.voided_by_id = user_id
    payment.voided_at = datetime.utcnow()
    await db.execute(update(PaymentItem).where(
        PaymentItem.payment_id == payment.id, *_scope(tenant_id, user_id)
    ).values(payment_id=None, paid_amount=None, paid_at=None))
    await db.flush()
    return payment


async def outstanding(db: AsyncSession, tenant_id: int, user_id: int,
                      supplier_id: int | None) -> list[PaymentItem]:
    """Step 13: every unpaid ticket still owed or in question, oldest statement first."""
    q = select(PaymentItem).where(
        *_scope(tenant_id, user_id), PaymentItem.payment_id.is_(None),
        PaymentItem.stale.is_(False), PaymentItem.decision_status != DECISION_EXCLUDED)
    if supplier_id is not None:
        q = q.where(PaymentItem.supplier_id == supplier_id)
    return list((await db.execute(
        q.order_by(PaymentItem.statement_uploaded_at.asc().nullslast(), PaymentItem.id.asc())
    )).scalars().all())


# ── cleanup when an upload is deleted ────────────────────────────────────────
async def forget_batch(db: AsyncSession, *, slug: str, tenant_id: int, user_id: int,
                       batch_id: str) -> None:
    """Called from the statements router's delete. A no-op for other statement types.

    A deleted VENDOR upload takes its unpaid items and its reconciliations with it; paid
    items stay — a payment that was made does not un-happen. A deleted MO upload takes its
    corrections and the reconciliations that used it.
    """
    R, RR = PaymentReconciliation, PaymentReconciliationRun
    if slug == VENDOR_SLUG:
        await db.execute(delete(PaymentItem).where(
            *_scope(tenant_id, user_id), PaymentItem.vendor_batch_id == batch_id,
            PaymentItem.payment_id.is_(None)))
        await db.execute(update(PaymentItem).where(
            *_scope(tenant_id, user_id), PaymentItem.vendor_batch_id == batch_id
        ).values(stale=True))
        await db.execute(delete(R).where(R.tenant_id == tenant_id, R.created_by_id == user_id,
                                         R.vendor_batch_id == batch_id))
        await db.execute(delete(RR).where(RR.tenant_id == tenant_id, RR.created_by_id == user_id,
                                          RR.vendor_batch_id == batch_id))
    elif slug == MO_SLUG:
        await db.execute(delete(MoVendorCorrection).where(
            MoVendorCorrection.tenant_id == tenant_id,
            MoVendorCorrection.created_by_id == user_id,
            MoVendorCorrection.mo_batch_id == batch_id))
        await db.execute(delete(R).where(R.tenant_id == tenant_id, R.created_by_id == user_id,
                                         R.mo_batch_id == batch_id))
        await db.execute(delete(RR).where(RR.tenant_id == tenant_id, RR.created_by_id == user_id,
                                          RR.mo_batch_id == batch_id))
