"""Vendors data → Payment Module → Reconciliation: run it, list it, drill in, price it.

Mounted at `/payment-module/reconciliation`. One pair at a time — a vendor upload
(`tp-gds`) against an MO upload (`mo-gds`) — because a payment is made per statement. The
upload pickers read the existing `/statements/{slug}/batches`, so there is no listing
endpoint here. Endpoint shapes follow `/reconciliation/vendor` (run · list · facets ·
detail), scoped per user exactly like every statement and reconciliation router.

Each row carries its payment item's decision (services/payment_ledger.py), joined on the
ticket key, so the grid shows what Operations decided without a second request.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.commission_run import ENGINE_VERSION, CommissionRun
from app.models.payment_ledger import (
    DECISION_APPROVED, DECISION_EXCLUDED, DECISION_HELD, DECISION_PENDING, PaymentItem,
)
from app.models.payment_reconciliation import (
    MO_VENDOR_OTHER, PAYMENT_RECON_STATUSES, STATUS_MO_ONLY, STATUS_VENDOR_ONLY,
    PaymentReconciliation,
)
from app.models.statement_row import STATEMENT_MODELS
from app.models.user import User
from app.schemas.payment_reconciliation import (
    PaymentCommissionState, PaymentFieldDiff, PaymentIssue, PaymentReconciliationDetail,
    PaymentReconciliationFacets, PaymentReconciliationPage, PaymentReconciliationRowRead,
    PaymentReconciliationRunResult, PaymentRunInfo, PaymentTotals,
    RunPaymentReconciliationPayload,
)
from app.services import commission_core as core
from app.services.commission import CommissionRunner, get_adapter
from app.services.payment_reconciliation import (
    MO_SLUG, PAIRED_STATUSES, VENDOR_SLUG, PaymentReconciliationService, StatementNotFound,
    latest_commission_run, latest_run,
)

router = APIRouter()

R = PaymentReconciliation
I = PaymentItem

# Same cap as the commission API's inline path (api/v1/commission.py MAX_INLINE_ROWS).
MAX_INLINE_ROWS = 500

DECISION_FILTERS = ("approved", "pending", "held", "excluded", "paid", "none")
FLAG_FILTERS = ("duplicate", "not_billed", "other_vendor", "enriched")


def _pair(user: User, vendor_batch_id: str, mo_batch_id: str):
    return (
        R.tenant_id == user.tenant_id,
        R.created_by_id == user.id,
        R.vendor_batch_id == vendor_batch_id,
        R.mo_batch_id == mo_batch_id,
    )


def _item_join():
    return and_(I.tenant_id == R.tenant_id, I.created_by_id == R.created_by_id,
                I.vendor_batch_id == R.vendor_batch_id, I.ticket_key == R.ticket_key)


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _enriched():
    """Rows whose enrichment holds something. By content rather than IS NOT NULL: rows
    written before the column stored absence as SQL NULL hold a JSON `null` instead."""
    return func.jsonb_typeof(R.enrichment) == "object"


def _row_read(r: PaymentReconciliation, item: PaymentItem | None = None) -> dict:
    return dict(
        id=r.id, vendor_batch_id=r.vendor_batch_id, mo_batch_id=r.mo_batch_id,
        ticket_number=r.ticket_number, ticket_prefix=r.ticket_prefix,
        airline_name=r.airline_name, airline_code=r.airline_code, issue_date=r.issue_date,
        pax_name=r.pax_name, sector=r.sector, pnr=r.pnr,
        match_status=r.match_status, severity=r.severity, match_method=r.match_method,
        vendor_rows=r.vendor_rows, mo_rows=r.mo_rows,
        vendor_gross=_f(r.vendor_gross), mo_gross=_f(r.mo_gross),
        vendor_net=_f(r.vendor_net), mo_net=_f(r.mo_net), net_variance=_f(r.net_variance),
        vendor_commission=_f(r.vendor_commission), mo_commission=_f(r.mo_commission),
        calc_commission=_f(r.calc_commission),
        commission_shortfall=_f(r.commission_shortfall),
        payable_after_commission=_f(r.payable_after_commission),
        commission_status=r.commission_status,
        issue_count=len(r.issues or []),
        ticket_key=r.ticket_key, booking_id=r.booking_id, not_billed=bool(r.not_billed),
        is_duplicate=bool(r.is_duplicate), mo_vendor_status=r.mo_vendor_status or "none",
        mo_vendor_name=(r.mo_vendor_info or {}).get("supplier_name"),
        enriched_fields=sorted((r.enrichment or {}).keys()),
        item_id=item.id if item else None,
        decision_status=item.decision_status if item else None,
        decision_source=item.decision_source if item else None,
        decision_action=item.decision_action if item else None,
        approved_amount=_f(item.approved_amount) if item else None,
        decision_reason=item.decision_reason if item else None,
        paid=bool(item and item.payment_id is not None),
    )


@router.post("/run", response_model=PaymentReconciliationRunResult)
async def run_payment_reconciliation(
    payload: RunPaymentReconciliationPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recompute the pair and persist it. Synchronous: two indexed reads and a set-based
    match over a few hundred lines, like `/reconciliation/vendor/{source}/run`."""
    try:
        s = await PaymentReconciliationService.run(
            db, tenant_id=current_user.tenant_id, created_by_id=current_user.id,
            vendor_batch_id=payload.vendor_batch_id, mo_batch_id=payload.mo_batch_id,
        )
    except StatementNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _run_result(s)


def _run_result(s) -> PaymentReconciliationRunResult:
    t = s.totals
    return PaymentReconciliationRunResult(
        run_id=s.run_id, reconciled_at=s.reconciled_at, total=s.total,
        matched=s.counts.get("matched", 0), minor_diff=s.counts.get("minor_diff", 0),
        mismatch=s.counts.get("mismatch", 0),
        possible_match=s.counts.get("possible_match", 0),
        vendor_only=s.counts.get("vendor_only", 0), mo_only=s.counts.get("mo_only", 0),
        vendor_net_total=t["vendor_net"] or 0.0, mo_net_total=t["mo_net"] or 0.0,
        net_variance_total=t["net_variance"] or 0.0,
        vendor_only_total=t["vendor_only"] or 0.0, mo_only_total=t["mo_only"] or 0.0,
        calc_commission_total=t["calc"] or 0.0,
        vendor_commission_total=t["vendor_comm"] or 0.0,
        shortfall_total=t["shortfall"] or 0.0, payable_total=t["payable"] or 0.0,
        vendor_closing_balance=s.vendor_closing_balance,
        mo_closing_balance=s.mo_closing_balance,
    )


@router.post("/calculate-income")
async def calculate_income(
    payload: RunPaymentReconciliationPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Step 8: price every ticket of the vendor statement against your B2B deals, with the
    MO statement's class / sector / travel date filling what the vendor does not print
    (services/commission/mo_index.py), then re-reconcile.

    The same guards as `POST /commission/vendor/tp-gds/statements/{batch}/run` — they live
    in that router, not in the runner, so they are repeated here: no consolidator → 409
    (without one any consolidator's B2B deal could match), a live run → 409. Small uploads
    run inline and come back reconciled; large ones are queued, and the screen's commission
    banner says when to re-run.
    """
    adapter = get_adapter(VENDOR_SLUG)
    V = STATEMENT_MODELS[VENDOR_SLUG]
    rows = await db.scalar(select(func.count()).select_from(V).where(
        V.batch_id == payload.vendor_batch_id, V.tenant_id == current_user.tenant_id,
        V.created_by_id == current_user.id)) or 0
    if not rows:
        raise HTTPException(status_code=404, detail="Vendor statement not found.")
    link = await adapter.supplier_for_batch(db, current_user.tenant_id, payload.vendor_batch_id)
    if link is None:
        raise HTTPException(
            status_code=409,
            detail="This vendor statement has no consolidator, so there is no B2B deal to "
                   "price it against. Delete it and upload again, naming the agency.")
    current = await latest_commission_run(db, current_user.tenant_id, current_user.id,
                                          payload.vendor_batch_id)
    if current and current.status in ("queued", "processing") \
            and not core.is_stale(current.status, current.heartbeat_at):
        raise HTTPException(status_code=409,
                            detail="Income is already being calculated for this statement.")

    inline = rows <= MAX_INLINE_ROWS
    run = CommissionRun(
        tenant_id=current_user.tenant_id, created_by_id=current_user.id,
        source=VENDOR_SLUG, batch_id=payload.vendor_batch_id, direction="inbound",
        engine_version=ENGINE_VERSION, status="queued",
        mode="inline" if inline else "queued",
        started_at=datetime.utcnow(), heartbeat_at=datetime.utcnow(),
        params={"supplier_id": link.supplier_id, "supplier_name": link.supplier_name,
                "supplier_code": link.supplier_code, "statement_type": adapter.statement_type,
                "row_ids": None, "requested_from": "payment-module",
                "mo_batch_id": payload.mo_batch_id},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    if not inline:
        try:
            from app.workers.commission_tasks import run_commission as task
            task.delay(run.id)
        except Exception as exc:  # noqa: BLE001 — broker unreachable
            run.status = "failed"
            run.error = f"Could not queue the run: {exc}"[:2000]
            await db.commit()
            raise HTTPException(
                status_code=503,
                detail="The background worker is unreachable, so income could not be "
                       "calculated. Start the Celery worker and try again.")
        return {"mode": "queued", "commission_run_id": run.id, "status": run.status}

    try:
        await CommissionRunner(adapter).run(db, run)
    except Exception as exc:  # noqa: BLE001 — the runner has marked the run failed
        raise HTTPException(status_code=500, detail=f"Income calculation failed: {exc}")
    try:
        s = await PaymentReconciliationService.run(
            db, tenant_id=current_user.tenant_id, created_by_id=current_user.id,
            vendor_batch_id=payload.vendor_batch_id, mo_batch_id=payload.mo_batch_id)
    except StatementNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "mode": "inline", "commission_run_id": run.id, "status": run.status,
        "calculated": run.calculated_rows, "reversed": run.reversed_rows,
        "needs_data": run.needs_data_rows, "unmatched": run.unmatched_rows,
        "skipped": run.skipped_rows,
        "reconciliation": _run_result(s).model_dump(mode="json"),
    }


@router.get("/", response_model=PaymentReconciliationPage)
async def list_payment_reconciliation(
    vendor_batch_id: str = Query(..., description="The vendor (tp-gds) upload"),
    mo_batch_id: str = Query(..., description="The MO (mo-gds) upload"),
    status: str | None = Query(None, description="match_status filter"),
    airline: str | None = Query(None, description="airline_name contains"),
    search: str | None = Query(None, description="ticket number, PNR or passenger contains"),
    decision: str | None = Query(None, description="approved | pending | held | excluded | paid"),
    flag: str | None = Query(None, description="duplicate | not_billed | other_vendor | enriched"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = []
    if status and status.strip() and status.lower() != "all":
        if status not in PAYMENT_RECON_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Allowed: {list(PAYMENT_RECON_STATUSES)}")
        filters.append(R.match_status == status)
    if airline and airline.strip() and airline.lower() != "all":
        filters.append(R.airline_name.ilike(f"%{airline.strip()}%"))
    if search and search.strip():
        like = f"%{search.strip()}%"
        filters.append(or_(
            R.ticket_number.ilike(like),
            # The whole number as printed on the coupon — the two halves are stored apart.
            (func.coalesce(R.ticket_prefix, "") + func.coalesce(R.ticket_number, "")).ilike(like),
            R.pnr.ilike(like),
            R.pax_name.ilike(like),
            R.booking_id.ilike(like),
        ))
    if decision and decision.strip() and decision.lower() != "all":
        d = decision.lower()
        if d not in DECISION_FILTERS:
            raise HTTPException(status_code=400,
                                detail=f"Invalid decision. Allowed: {list(DECISION_FILTERS)}")
        if d == "paid":
            filters.append(I.payment_id.isnot(None))
        elif d == "none":
            filters.append(I.id.is_(None))
        else:
            filters.extend([I.decision_status == d, I.payment_id.is_(None)])
    if flag and flag.strip() and flag.lower() != "all":
        fl = flag.lower()
        if fl not in FLAG_FILTERS:
            raise HTTPException(status_code=400,
                                detail=f"Invalid flag. Allowed: {list(FLAG_FILTERS)}")
        filters.append({
            "duplicate": R.is_duplicate.is_(True),
            "not_billed": R.not_billed.is_(True),
            "other_vendor": R.mo_vendor_status == MO_VENDOR_OTHER,
            "enriched": _enriched(),
        }[fl])
    where = (*_pair(current_user, vendor_batch_id, mo_batch_id), *filters)

    # Summary over the FILTERED set, so the tiles can never disagree with the grid — the
    # same rules `services/payment_reconciliation.tally` applies to the run header.
    grp = (await db.execute(
        select(
            R.match_status,
            func.count(),
            func.sum(R.vendor_net).filter(R.vendor_rows > 0),
            func.sum(R.mo_net).filter(R.mo_rows > 0),
            func.sum(R.net_variance),
            func.sum(R.calc_commission),
            func.sum(R.vendor_commission),
            func.sum(R.commission_shortfall),
            func.sum(R.payable_after_commission),
        ).select_from(R).outerjoin(I, _item_join()).where(*where).group_by(R.match_status)
    )).all()

    counts = {s: 0 for s in PAYMENT_RECON_STATUSES}
    money = {k: Decimal("0") for k in ("vendor_net", "mo_net", "net_variance", "vendor_only",
                                       "mo_only", "calc", "vendor_comm", "shortfall",
                                       "payable")}
    total = 0
    for st, cnt, vn, mn, nv, calc, vcomm, short, pay in grp:
        total += cnt
        counts[st] = counts.get(st, 0) + cnt
        vn, mn = Decimal(vn or 0), Decimal(mn or 0)
        money["vendor_net"] += vn
        money["mo_net"] += mn
        if st in PAIRED_STATUSES:
            money["net_variance"] += Decimal(nv or 0)
        elif st == STATUS_VENDOR_ONLY:
            money["vendor_only"] += vn
        elif st == STATUS_MO_ONLY:
            money["mo_only"] += mn
        money["calc"] += Decimal(calc or 0)
        money["vendor_comm"] += Decimal(vcomm or 0)
        money["shortfall"] += Decimal(short or 0)
        money["payable"] += Decimal(pay or 0)

    summary = PaymentTotals(
        total=total, **counts,
        vendor_net_total=float(money["vendor_net"]), mo_net_total=float(money["mo_net"]),
        net_variance_total=float(money["net_variance"]),
        vendor_only_total=float(money["vendor_only"]),
        mo_only_total=float(money["mo_only"]),
        calc_commission_total=float(money["calc"]),
        vendor_commission_total=float(money["vendor_comm"]),
        shortfall_total=float(money["shortfall"]), payable_total=float(money["payable"]),
    )

    flag_row = (await db.execute(
        select(
            func.count().filter(R.is_duplicate.is_(True)),
            func.count().filter(R.not_billed.is_(True)),
            func.count().filter(R.mo_vendor_status == MO_VENDOR_OTHER),
            func.count().filter(_enriched()),
            func.count().filter(and_(I.decision_status == DECISION_APPROVED, I.payment_id.is_(None))),
            func.count().filter(and_(I.decision_status == DECISION_PENDING, I.payment_id.is_(None))),
            func.count().filter(and_(I.decision_status == DECISION_HELD, I.payment_id.is_(None))),
            func.count().filter(and_(I.decision_status == DECISION_EXCLUDED, I.payment_id.is_(None))),
            func.count().filter(I.payment_id.isnot(None)),
            func.sum(case((and_(I.decision_status == DECISION_APPROVED, I.payment_id.is_(None)),
                           I.approved_amount), else_=0)),
        ).select_from(R).outerjoin(I, _item_join()).where(*where)
    )).one()
    flags = {"duplicates": flag_row[0], "not_billed": flag_row[1],
             "other_vendor": flag_row[2], "enriched": flag_row[3]}
    decisions = {"approved": flag_row[4], "pending": flag_row[5], "held": flag_row[6],
                 "excluded": flag_row[7], "paid": flag_row[8],
                 "approved_amount": float(flag_row[9] or 0)}

    run = await latest_run(db, current_user.tenant_id, current_user.id,
                           vendor_batch_id, mo_batch_id)
    run_info = None
    if run is not None:
        p = run.params or {}
        vb, mb = p.get("vendor_balance") or {}, p.get("mo_balance") or {}
        run_info = PaymentRunInfo(
            run_id=run.id, completed_at=run.completed_at,
            vendor_source_file=p.get("vendor_source_file"),
            mo_source_file=p.get("mo_source_file"),
            vendor_closing_balance=_f(run.vendor_closing_balance),
            mo_closing_balance=_f(run.mo_closing_balance),
            vendor_opening_balance=vb.get("opening"),
            vendor_opening_derived=bool(vb.get("opening_derived")),
            mo_opening_balance=mb.get("opening"),
            mo_opening_derived=bool(mb.get("opening_derived")),
            vendor_balance_lines=p.get("vendor_balance_lines") or [],
            mo_balance_lines=p.get("mo_balance_lines") or [],
            commission_run_id=run.commission_run_id,
            commission_completed_at=run.commission_completed_at,
            commission_priced_rows=run.commission_priced_rows,
            commission_unpriced_rows=run.commission_unpriced_rows,
        )

    comm = await latest_commission_run(db, current_user.tenant_id, current_user.id,
                                       vendor_batch_id)
    commission = PaymentCommissionState()
    if comm is not None:
        commission = PaymentCommissionState(
            run_id=comm.id, status=comm.status, completed_at=comm.completed_at,
            total_rows=comm.total_rows or 0,
            priced_rows=(comm.calculated_rows or 0) + (comm.reversed_rows or 0),
            pending_rows=comm.pending_rows or 0,
            # Re-run after this reconciliation read it — the figures on screen are older.
            stale=bool(
                run is not None and comm.completed_at is not None and (
                    run.commission_completed_at is None
                    or run.commission_run_id != comm.id
                    or comm.completed_at > run.commission_completed_at)),
        )

    rows = (await db.execute(
        select(R, I).select_from(R).outerjoin(I, _item_join()).where(*where)
        # Worst first: the biggest difference, or the biggest unaccounted amount.
        .order_by(R.abs_net_variance.desc().nullslast(), R.id.asc())
        .offset(offset).limit(limit)
    )).all()

    return PaymentReconciliationPage(
        summary=summary, run=run_info, commission=commission, flags=flags,
        decisions=decisions, total=total, offset=offset, limit=limit,
        rows=[PaymentReconciliationRowRead(**_row_read(r, item)) for r, item in rows],
    )


@router.get("/facets", response_model=PaymentReconciliationFacets)
async def payment_reconciliation_facets(
    vendor_batch_id: str = Query(...),
    mo_batch_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    airlines = (await db.execute(
        select(R.airline_name)
        .where(*_pair(current_user, vendor_batch_id, mo_batch_id), R.airline_name.isnot(None))
        .distinct().order_by(R.airline_name)
    )).scalars().all()
    return PaymentReconciliationFacets(
        airlines=list(airlines), statuses=list(PAYMENT_RECON_STATUSES))


@router.get("/rows/{recon_id}", response_model=PaymentReconciliationDetail)
async def payment_reconciliation_detail(
    recon_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    found = (await db.execute(
        select(R, I).select_from(R).outerjoin(I, _item_join())
        .where(R.id == recon_id, R.tenant_id == current_user.tenant_id,
               R.created_by_id == current_user.id)
    )).one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="Reconciliation row not found.")
    r, item = found

    async def records(slug: str, ids: list | None) -> list[dict]:
        if not ids:
            return []
        m = STATEMENT_MODELS[slug]
        rows = (await db.execute(
            select(m).where(m.id.in_([int(i) for i in ids]),
                            m.tenant_id == current_user.tenant_id,
                            m.created_by_id == current_user.id)
            .order_by(m.id.asc())
        )).scalars().all()
        return [{**(row.data or {}), "_id": row.id, "_batch_id": row.batch_id,
                 "_source_file": row.source_file} for row in rows]

    vendor_records = await records(VENDOR_SLUG, r.vendor_row_ids)
    mo_records = await records(MO_SLUG, r.mo_row_ids)
    missing = (len(vendor_records) != len(r.vendor_row_ids or [])
               or len(mo_records) != len(r.mo_row_ids or []))

    decided_by = None
    if item is not None and item.decided_by_id:
        decided_by = await db.scalar(select(User.full_name).where(User.id == item.decided_by_id))

    return PaymentReconciliationDetail(
        **_row_read(r, item),
        reconciled_at=r.reconciled_at,
        fields=[PaymentFieldDiff(**d) for d in (r.field_diffs or [])],
        issues=[PaymentIssue(**i) for i in (r.issues or [])],
        notes=list(r.notes or []),
        commission_detail=list(r.commission_detail or []),
        vendor_records=vendor_records,
        mo_records=mo_records,
        records_missing=missing,
        duplicate_info=r.duplicate_info,
        mo_vendor_info=r.mo_vendor_info,
        enrichment=r.enrichment,
        remarks=item.remarks if item else None,
        ops_reference=item.ops_reference if item else None,
        decided_by_name=decided_by,
        decided_at=item.decided_at if item else None,
        paid_amount=_f(item.paid_amount) if item else None,
        paid_at=item.paid_at if item else None,
        payment_id=item.payment_id if item else None,
        suggested_payable=_f(item.suggested_payable) if item else None,
    )
