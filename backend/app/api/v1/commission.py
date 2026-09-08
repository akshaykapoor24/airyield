"""Vendor commission income for the non-BSP statement sources.

Mounted at `/commission/vendor`. `/bsp-commission/*` is NOT touched and NOT aliased: BSP
keeps its own router, its own schemas and its own storage, so nothing about the flagship
screen depends on this file being correct on day one. The frontend picks a base URL per
source tab, which is the whole coupling between them.

The endpoint set mirrors `/bsp-commission/*` deliberately — statements, run, reset, rows,
facets, summary, gaps, diagnosis, xlsx — so one frontend component serves every tab. The
one addition is `/variance`, which only a source with declared vendor figures can answer.
"""
from __future__ import annotations

import io
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import String, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.commission_calculation import CommissionCalculation as Calc
from app.models.commission_run import ENGINE_VERSION, CommissionRun
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.user import User
from app.schemas.commission import (
    CommissionAirlineSummary,
    CommissionReasonGroup,
    CommissionRowRead,
    CommissionRowsPage,
    CommissionRunResponse,
    CommissionStatementRead,
    CommissionSummary,
    CommissionTotals,
    CommissionVarianceGroup,
    CommissionVarianceReport,
)
from app.services import commission_core as core
from app.services import statement_spec as spec
from app.services.commission import CommissionRunner, get_adapter

router = APIRouter()

# A hand-picked selection runs inside the request; past this it belongs to the worker.
# Matches api/v1/bsp_commission.MAX_INLINE_ROWS.
MAX_INLINE_ROWS = 500
# The gaps tab is for working through causes, not for reading ten thousand of them.
MAX_GAP_GROUPS = 50


def _resolve(source: str):
    """(adapter, normalized source) or 404 — same discipline as statements._resolve."""
    adapter = get_adapter(source)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"Unknown commission source '{source}'.")
    return adapter, adapter.source


def _scope(user: User):
    return (Calc.tenant_id == user.tenant_id, Calc.created_by_id == user.id)


def _run_scope(user: User):
    return (CommissionRun.tenant_id == user.tenant_id, CommissionRun.created_by_id == user.id)


async def _latest_run(db: AsyncSession, user: User, source: str, batch_id: str):
    return (await db.execute(
        select(CommissionRun)
        .where(*_run_scope(user), CommissionRun.source == source,
               CommissionRun.batch_id == batch_id)
        .order_by(CommissionRun.started_at.desc().nullslast(), CommissionRun.id.desc())
        .limit(1)
    )).scalar_one_or_none()


def _progress_pct(run: CommissionRun | None) -> int:
    if run is None or not run.total_rows:
        return 0
    if run.status == "completed":
        return 100
    return min(100, int(round(100.0 * (run.processed_rows or 0) / run.total_rows)))


def _statement_read(source: str, batch, run, link, pending: int,
                    adapter) -> CommissionStatementRead:
    # Only the sources that DECLARE a consolidator can be blocked for not having one —
    # an LCC Detailed statement comes from the carrier and needs no supplier at all.
    blocked = None
    if getattr(adapter, "requires_supplier", False) and getattr(link, "supplier_id", None) is None:
        blocked = ("No consolidator on this upload — the file does not name its sender, so "
                   "there is no B2B deal to price it against. Re-upload it, naming the "
                   "consolidator from the Supplier master.")
    elif getattr(batch, "parse_status", "completed") not in ("completed", None):
        blocked = ("This upload is still being read. Wait for it to finish, then run the "
                   "commission.")
    return CommissionStatementRead(
        source=source,
        batch_id=batch.batch_id,
        statement_name=batch.source_file,
        row_count=batch.row_count or 0,
        uploaded_at=batch.uploaded_at,
        period_from=batch.period_from,
        period_to=batch.period_to,
        airline_name=getattr(batch, "airline_name", None),
        airline_code=getattr(batch, "airline_code", None),
        parse_status=getattr(batch, "parse_status", "completed") or "completed",
        status=(run.status if run else "idle"),
        total_rows=(run.total_rows if run else 0),
        processed_rows=(run.processed_rows if run else 0),
        progress_pct=_progress_pct(run),
        error=(run.error if run else None),
        heartbeat_at=(run.heartbeat_at if run else None),
        is_stale=core.is_stale(run.status if run else None, run.heartbeat_at if run else None),
        calculated_at=(run.completed_at if run else None),
        total_incentive=(float(run.total_incentive) if run and run.total_incentive is not None else None),
        iata_total=(float(run.total_iata) if run and run.total_iata is not None else None),
        matched_rows=((run.calculated_rows + run.reversed_rows) if run else 0),
        unmatched_rows=(run.unmatched_rows if run else 0),
        excluded_rows=(run.excluded_rows if run else 0),
        skipped_rows=(run.skipped_rows if run else 0),
        needs_data_rows=(run.needs_data_rows if run else 0),
        pending_rows=pending,
        supplier_id=getattr(link, "supplier_id", None),
        supplier_name=getattr(link, "supplier_name", None),
        supplier_branch=getattr(link, "supplier_branch", None),
        supplier_code=getattr(link, "supplier_code", None),
        can_run=blocked is None,
        blocked_reason=blocked,
        declared_commission_total=(float(run.declared_commission_total)
                                   if run and run.declared_commission_total is not None else None),
        declared_incentive_total=(float(run.declared_incentive_total)
                                  if run and run.declared_incentive_total is not None else None),
        variance_total=(float(run.variance_total) if run and run.variance_total is not None else None),
        variance_unverified_rows=(run.variance_unverified_rows if run else 0),
    )


@router.get("/{source}/statements", response_model=list[CommissionStatementRead])
async def list_statements(
    source: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every upload of this source, with the state of its latest run.

    HOW a source finds its batches is the adapter's business: the spec-driven types derive
    one with a GROUP BY because they keep no header row, while LCC Detailed reads a real
    `lcc_detailed_batch`. Both answer with a BatchInfo, so nothing here branches per source.
    """
    adapter, source = _resolve(source)
    batches = await adapter.list_batches(db, current_user.tenant_id, current_user.id)
    if not batches:
        return []
    ids = [b.batch_id for b in batches]

    runs = {r.batch_id: r for r in (await db.execute(
        select(CommissionRun)
        .where(*_run_scope(current_user), CommissionRun.source == source,
               CommissionRun.batch_id.in_(ids))
        .order_by(CommissionRun.started_at.asc().nullsfirst(), CommissionRun.id.asc())
    )).scalars().all()}   # ascending, so the last write per batch is the latest run

    links = {l.batch_id: l for l in (await db.execute(
        select(StatementBatchSupplier).where(
            StatementBatchSupplier.slug == source,
            StatementBatchSupplier.tenant_id == current_user.tenant_id,
            StatementBatchSupplier.batch_id.in_(ids),
        )
    )).scalars().all()}

    priced = dict((await db.execute(
        select(Calc.batch_id, func.count())
        .where(*_scope(current_user), Calc.source == source, Calc.batch_id.in_(ids))
        .group_by(Calc.batch_id)
    )).all())

    out = []
    for b in batches:
        # Rows no run has touched. A never-run statement must not look like a fully-run
        # one that matched almost nothing.
        pending = max(0, (b.row_count or 0) - priced.get(b.batch_id, 0))
        out.append(_statement_read(source, b, runs.get(b.batch_id),
                                   links.get(b.batch_id), pending, adapter))
    return out


@router.get("/{source}/statements/{batch_id}", response_model=CommissionStatementRead)
async def get_statement(
    source: str, batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    adapter, source = _resolve(source)
    batches = await adapter.list_batches(db, current_user.tenant_id, current_user.id)
    b = next((x for x in batches if x.batch_id == batch_id), None)
    if b is None:
        raise HTTPException(status_code=404, detail="Statement not found.")
    run = await _latest_run(db, current_user, source, batch_id)
    link = await adapter.supplier_for_batch(db, current_user.tenant_id, batch_id)
    priced = await db.scalar(select(func.count()).select_from(Calc).where(
        *_scope(current_user), Calc.source == source, Calc.batch_id == batch_id)) or 0
    return _statement_read(source, b, run, link,
                           max(0, (b.row_count or 0) - priced), adapter)


@router.post("/{source}/statements/{batch_id}/run", response_model=CommissionRunResponse,
             status_code=status.HTTP_202_ACCEPTED)
async def run_commission(
    source: str, batch_id: str,
    payload: dict = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Price this statement. Empty body → the worker; `row_ids` → inline, capped.

    The run row is created and COMMITTED before the task is enqueued, so a broker that
    never delivers leaves a visible queued run rather than silence — same order as
    /bsp-commission/.../run.
    """
    adapter, source = _resolve(source)
    row_ids = payload.get("row_ids") or None
    if row_ids and len(row_ids) > MAX_INLINE_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Select at most {MAX_INLINE_ROWS} rows to run inline, or run the whole statement.")

    exists = await db.scalar(select(func.count()).select_from(adapter.model).where(
        adapter.model.batch_id == batch_id,
        adapter.model.tenant_id == current_user.tenant_id,
        adapter.model.created_by_id == current_user.id))
    if not exists:
        raise HTTPException(status_code=404, detail="Statement not found.")

    link = await adapter.supplier_for_batch(db, current_user.tenant_id, batch_id)
    if getattr(adapter, "requires_supplier", False) and link is None:
        raise HTTPException(
            status_code=409,
            detail=("This upload has no consolidator, so there is no B2B deal to price it "
                    "against. Delete it and upload again, naming the consolidator from "
                    "the Supplier master."))

    current = await _latest_run(db, current_user, source, batch_id)
    if current and current.status in ("queued", "processing") \
            and not core.is_stale(current.status, current.heartbeat_at):
        raise HTTPException(status_code=409,
                            detail="A run is already in progress for this statement.")

    run = CommissionRun(
        tenant_id=current_user.tenant_id, created_by_id=current_user.id,
        source=source, batch_id=batch_id, direction="inbound",
        engine_version=ENGINE_VERSION,
        status="queued", mode="inline" if row_ids else "queued",
        started_at=datetime.utcnow(), heartbeat_at=datetime.utcnow(),
        params={
            "supplier_id": getattr(link, "supplier_id", None),
            "supplier_name": getattr(link, "supplier_name", None),
            "supplier_code": getattr(link, "supplier_code", None),
            "statement_type": adapter.statement_type,
            "row_ids": row_ids,
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    if row_ids:
        await CommissionRunner(adapter).run(db, run, row_ids=row_ids)
        return _run_response(run)

    try:
        from app.workers.commission_tasks import run_commission as task
        task.delay(run.id)
    except Exception as exc:  # noqa: BLE001 — broker unreachable
        run.status = "failed"
        run.error = f"Could not queue the run: {exc}"[:2000]
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail="The background worker is unreachable, so this statement could not be "
                   "queued. Start the Celery worker and try again.")
    return _run_response(run)


def _run_response(run: CommissionRun) -> CommissionRunResponse:
    return CommissionRunResponse(
        run_id=run.id, source=run.source, batch_id=run.batch_id, status=run.status,
        mode=run.mode, processed=run.processed_rows, calculated=run.calculated_rows,
        reversed=run.reversed_rows, excluded=run.excluded_rows,
        needs_data=run.needs_data_rows, skipped=run.skipped_rows,
        unmatched=run.unmatched_rows,
        total_incentive=float(run.total_incentive or 0),
        variance_total=float(run.variance_total or 0),
    )


@router.post("/{source}/statements/{batch_id}/reset", response_model=CommissionRunResponse)
async def reset_run(
    source: str, batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Release a run whose worker died, so the statement can be run again.

    Only a STALE run — one still claiming to be alive with a heartbeat older than five
    minutes. Releasing a live run would leave two workers writing the same ledger rows.
    """
    _adapter, source = _resolve(source)
    run = await _latest_run(db, current_user, source, batch_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No run to reset.")
    if run.status in ("queued", "processing") and not core.is_stale(run.status, run.heartbeat_at):
        raise HTTPException(
            status_code=409,
            detail="This run is still active. Wait for it to finish, or try again in a few minutes.")
    run.status = "failed"
    run.error = "Released by the user after the worker stopped reporting progress."
    run.completed_at = datetime.utcnow()
    await db.commit()
    return _run_response(run)


def _row_conditions(source: str, batch_id: str, user: User, request: Request | None) -> list:
    conds = [*_scope(user), Calc.source == source, Calc.batch_id == batch_id]
    if request is None:
        return conds
    q = request.query_params
    if (v := (q.get("search") or "").strip()):
        like = f"%{v}%"
        conds.append(
            Calc.ticket_number.ilike(like) | Calc.pnr.ilike(like)
            | Calc.passenger_name.ilike(like) | Calc.matched_deal_name.ilike(like)
        )
    if (v := (q.get("air") or "").strip()):
        conds.append(Calc.airline_name == v)
    if (v := (q.get("comm_status") or "").strip()):
        conds.append(Calc.status == v)
    if (v := (q.get("txn_type") or "").strip()):
        conds.append(Calc.transaction_type == v)
    # short | over | matched | unverified — the four questions worth asking of a variance.
    if (v := (q.get("variance") or "").strip()):
        if v == "short":
            conds.append(Calc.variance_total > 0)
        elif v == "over":
            conds.append(Calc.variance_total < 0)
        elif v == "matched":
            conds.append(Calc.variance_total == 0)
        elif v == "unverified":
            conds.append(Calc.declared_net_ok.is_(False))
    return conds


@router.get("/{source}/statements/{batch_id}/rows", response_model=CommissionRowsPage)
async def list_rows(
    source: str, batch_id: str, request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _adapter, source = _resolve(source)
    conds = _row_conditions(source, batch_id, current_user, request)
    total = await db.scalar(select(func.count()).select_from(Calc).where(*conds)) or 0
    rows = (await db.execute(
        select(Calc).where(*conds)
        .order_by(Calc.issue_date.asc().nullslast(), Calc.id.asc())
        .limit(limit).offset(offset)
    )).scalars().all()
    return CommissionRowsPage(
        total=total, offset=offset, limit=limit,
        rows=[_row_read(r) for r in rows],
    )


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _row_read(r: Calc) -> CommissionRowRead:
    return CommissionRowRead(
        id=r.id, source_row_id=r.source_row_id,
        document_number=r.document_number, ticket_number=r.ticket_number, pnr=r.pnr,
        passenger_name=r.passenger_name, transaction_type=r.transaction_type,
        airline_name=r.airline_name, issue_date=r.issue_date, travel_date=r.travel_date,
        segment_type=r.segment_type, booking_class=r.booking_class, sector=r.sector,
        fare_amount=_f(r.fare_amount), yq=_f(r.yq), yr=_f(r.yr),
        ancillary_amount=_f(r.ancillary_amount),
        matched_deal_id=r.matched_deal_id, matched_deal_type=r.matched_deal_type,
        matched_deal_name=r.matched_deal_name, matched_deal_no=r.matched_deal_no,
        supplier_match_by=r.supplier_match_by,
        calculated_incentive=_f(r.incentive), iata_commission=_f(r.iata_commission),
        incentive_breakdown=r.incentive_breakdown or {},
        commission_status=r.status, commission_reason=r.reason,
        skipped_criteria=r.skipped_criteria or [], notes=r.notes or [],
        declared_commission=_f(r.declared_commission),
        declared_incentive=_f(r.declared_incentive),
        declared_tds=_f(r.declared_tds), declared_net=_f(r.declared_net),
        declared_net_ok=r.declared_net_ok,
        variance_commission=_f(r.variance_commission),
        variance_incentive=_f(r.variance_incentive),
        variance_total=_f(r.variance_total),
    )


@router.get("/{source}/statements/{batch_id}/rows/facets")
async def row_facets(
    source: str, batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct values for the grid's dropdowns, over the whole batch — not the filtered
    set, so narrowing one filter never empties another."""
    _adapter, source = _resolve(source)
    base = [*_scope(current_user), Calc.source == source, Calc.batch_id == batch_id]
    out: dict[str, list[str]] = {}
    for key, col in (("air", Calc.airline_name), ("comm_status", Calc.status),
                     ("txn_type", Calc.transaction_type)):
        vals = (await db.execute(
            select(col).where(*base, col.is_not(None)).distinct().order_by(col.asc()).limit(200)
        )).scalars().all()
        out[key] = [v for v in vals if v]
    return out


@router.get("/{source}/statements/{batch_id}/summary", response_model=CommissionSummary)
async def summary(
    source: str, batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per airline × incentive type, over the rows a deal actually applied to."""
    _adapter, source = _resolve(source)
    rows = (await db.execute(
        select(Calc.airline_name, Calc.incentive_breakdown, Calc.incentive, Calc.iata_commission)
        .where(*_scope(current_user), Calc.source == source, Calc.batch_id == batch_id,
               Calc.status.in_(("calculated", "reversed")))
    )).all()

    per: dict[str, dict] = {}
    totals: dict[str, float] = {}
    grand_inc = grand_iata = 0.0
    for airline, breakdown, incentive, iata in rows:
        key = airline or "—"
        slot = per.setdefault(key, {"rows": 0, "incentives": {}, "total": 0.0, "iata": 0.0})
        slot["rows"] += 1
        for k, v in (breakdown or {}).items():
            slot["incentives"][k] = round(slot["incentives"].get(k, 0.0) + float(v), 2)
            totals[k] = round(totals.get(k, 0.0) + float(v), 2)
        slot["total"] = round(slot["total"] + float(incentive or 0), 2)
        slot["iata"] = round(slot["iata"] + float(iata or 0), 2)
        grand_inc += float(incentive or 0)
        grand_iata += float(iata or 0)

    return CommissionSummary(
        airlines=[
            CommissionAirlineSummary(
                airline=a, rows=v["rows"], incentives=v["incentives"],
                total_incentive=v["total"], iata_commission=v["iata"])
            for a, v in sorted(per.items())
        ],
        totals=CommissionTotals(incentives=totals,
                                total_incentive=round(grand_inc, 2),
                                iata_commission=round(grand_iata, 2)),
    )


@router.get("/{source}/statements/{batch_id}/variance", response_model=CommissionVarianceReport)
async def variance(
    source: str, batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What the consolidator paid against what your deals say — the report you send them.

    404 for a source that prints no figures of its own: an empty variance report reads as
    "nothing owed", which is a different and wrong claim.
    """
    adapter, source = _resolve(source)
    if not getattr(adapter, "has_declared_amounts", False):
        raise HTTPException(
            status_code=404,
            detail=f"{adapter.label} statements do not declare their own commission, so "
                   f"there is nothing to compare against.")

    rows = (await db.execute(
        select(Calc.airline_name, Calc.matched_deal_no, Calc.matched_deal_name,
               Calc.declared_commission, Calc.iata_commission,
               Calc.declared_incentive, Calc.incentive,
               Calc.variance_total, Calc.declared_net_ok)
        .where(*_scope(current_user), Calc.source == source, Calc.batch_id == batch_id)
    )).all()

    groups: dict[tuple, dict] = {}
    under = over = 0.0
    unverified = 0
    for airline, deal_no, deal_name, d_comm, c_comm, d_inc, c_inc, var, ok in rows:
        if ok is False:
            unverified += 1
            continue
        if var is None:
            continue
        key = (airline or "—", deal_no)
        g = groups.setdefault(key, {
            "airline": airline or "—", "deal_no": deal_no, "deal_name": deal_name,
            "rows": 0, "dc": 0.0, "cc": 0.0, "di": 0.0, "ci": 0.0, "var": 0.0})
        g["rows"] += 1
        g["dc"] += float(d_comm or 0)
        g["cc"] += float(c_comm or 0)
        g["di"] += float(d_inc or 0)
        g["ci"] += float(c_inc or 0)
        g["var"] += float(var or 0)
        if float(var) > 0:
            under += float(var)
        elif float(var) < 0:
            over += float(var)

    return CommissionVarianceReport(
        groups=sorted(
            (CommissionVarianceGroup(
                airline=g["airline"], deal_no=g["deal_no"], deal_name=g["deal_name"],
                rows=g["rows"],
                declared_commission=round(g["dc"], 2), computed_commission=round(g["cc"], 2),
                declared_incentive=round(g["di"], 2), computed_incentive=round(g["ci"], 2),
                variance_total=round(g["var"], 2))
             for g in groups.values()),
            key=lambda g: g.variance_total, reverse=True),
        under_recovery=round(under, 2), over_paid=round(over, 2),
        net_variance=round(under + over, 2), unverified_rows=unverified,
    )


@router.get("/{source}/statements/{batch_id}/gaps", response_model=list[CommissionReasonGroup])
async def gaps(
    source: str, batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rows that earned nothing, grouped by WHY — the tab you work through.

    Grouped by (status, reason), which is why `needs_data_reason` is deliberately identical
    for every row with the same gap: naming the ticket in the reason would turn one
    actionable bucket into thousands of singletons.
    """
    _adapter, source = _resolve(source)
    rows = (await db.execute(
        select(Calc.status, Calc.reason, func.count().label("n"),
               func.array_agg(func.cast(Calc.ticket_number, String)).label("docs"))
        .where(*_scope(current_user), Calc.source == source, Calc.batch_id == batch_id,
               Calc.status.in_(("unmatched", "needs_data", "excluded", "skipped")))
        .group_by(Calc.status, Calc.reason)
        .order_by(func.count().desc())
        .limit(MAX_GAP_GROUPS)
    )).all()
    return [
        CommissionReasonGroup(
            status=s, reason=(r or "—"), count=n,
            sample_documents=[d for d in (docs or [])[:5] if d],
        )
        for s, r, n, docs in rows
    ]


@router.get("/{source}/rows/{calc_id}/match-diagnosis")
async def match_diagnosis(
    source: str, calc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Why this row got the answer it got — every deal considered, step by step.

    Rebuilt from the calculation's own INPUT SNAPSHOT, not from the source row: the row may
    have been reprocessed since, and a popup explaining today's inputs against last week's
    figure would be worse than none.
    """
    adapter, source = _resolve(source)
    calc = (await db.execute(
        select(Calc).where(Calc.id == calc_id, *_scope(current_user), Calc.source == source)
    )).scalar_one_or_none()
    if calc is None:
        raise HTTPException(status_code=404, detail="Row not found.")

    from app.services.deal_matching import DealMatchingService

    link = await adapter.supplier_for_batch(db, current_user.tenant_id, calc.batch_id)
    skipped = list(calc.skipped_criteria or [])
    # Only the two the matcher understands; "sector" is a display label, not a filter.
    skips = set(skipped) & {"class", "travel_date"}

    # SAME KEYS AS /bsp-commission/rows/{id}/match-diagnosis, so one modal component serves
    # every source tab. The third-party extras are additional keys, never renamed ones.
    base = {
        "row_id": calc.id,
        "document_number": calc.ticket_number,
        "transaction_type": calc.transaction_type,
        "raw_airline_code": None,
        "airline_resolved": calc.airline_name,
        "issue_date": calc.issue_date,
        "stat": calc.segment_type,
        "segment_type": calc.segment_type,
        "fare_amount": _f(calc.fare_amount),
        "sell_tax_yq": _f(calc.yq),
        "sale_yr": _f(calc.yr),
        "tour_code": None,
        "skipped_criteria": skipped,
        "sector": calc.sector,
        "booking_class": calc.booking_class,
        "travel_date": calc.travel_date,
        "travel_date_source": None,
        "leg_count": None,
        "enrichment_source": None,
        "enrichment_ref": None,
        "commission_status": calc.status,
        "commission_reason": calc.reason,
        # Third-party only. The modal shows them when present and ignores them otherwise.
        "supplier_agency": getattr(link, "supplier_name", None),
        "supplier_agency_id": getattr(link, "supplier_id", None),
        "supplier_match_by": calc.supplier_match_by,
        "notes": calc.notes or [],
        "declared_commission": _f(calc.declared_commission),
        "declared_incentive": _f(calc.declared_incentive),
        "variance_total": _f(calc.variance_total),
    }

    if not calc.airline_name:
        return {**base, "deals": [], "total_deals_checked": 0, "matched_count": 0,
                "note": "The carrier on this row is not in the airline master — no deal can match."}
    if calc.issue_date is None:
        return {**base, "deals": [], "total_deals_checked": 0, "matched_count": 0,
                "note": "Row has no issue date — deal validity cannot be checked."}

    # Every one of these feeds the incl/excl rule trace. Omitting them (as an earlier
    # version did) makes a route or date rule evaluate against nulls, so the popup can
    # report a rule as failing that the run itself passed.
    deals = await DealMatchingService.diagnose_match(
        db=db,
        airline_name=calc.airline_name,
        travel_date=calc.travel_date or calc.issue_date,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        issue_date=calc.issue_date,
        segment_type=calc.segment_type,
        booking_class=calc.booking_class,
        invoice_type="Sales",
        sell_fare=_f(calc.fare_amount),
        sell_tax_yq=_f(calc.yq),
        sale_yr=_f(calc.yr),
        ticket_sector=calc.sector,
        ticket_date_raw=calc.issue_date.isoformat(),
        ticket_departure_raw=calc.travel_date.isoformat() if calc.travel_date else None,
        ticket_airline_name=calc.airline_name,
        supplier_agency=getattr(link, "supplier_name", None),
        supplier_agency_id=getattr(link, "supplier_id", None),
        statement_type=adapter.statement_type,
        skip_criteria=skips,
        rule_skip_fields={"class"} if "class" in skipped else set(),
    )
    return {
        **base,
        "deals": deals,
        "total_deals_checked": len(deals),
        "matched_count": sum(1 for d in deals if getattr(d, "overall_match", False)),
    }


@router.get("/{source}/statements/{batch_id}/xlsx")
async def export_xlsx(
    source: str, batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every priced row as a spreadsheet, declared and variance columns included."""
    adapter, source = _resolve(source)
    from openpyxl import Workbook

    rows = (await db.execute(
        select(Calc).where(*_scope(current_user), Calc.source == source,
                           Calc.batch_id == batch_id)
        .order_by(Calc.issue_date.asc().nullslast(), Calc.id.asc())
    )).scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Commission"
    headers = ["Ticket No", "PNR", "Passenger", "Airline", "Issue Date", "Travel Date",
               "Category", "Class", "Sector", "Basic Fare", "YQ", "Status", "Deal",
               "Deal No", "Matched by", "Estimated Incentive", "IATA Commission"]
    if adapter.has_declared_amounts:
        headers += ["Declared Commission", "Declared Incentive", "Declared TDS",
                    "Net adds up?", "Variance (Commission)", "Variance (Incentive)",
                    "Variance (Total)"]
    headers += ["Reason", "Notes"]
    ws.append(headers)

    for r in rows:
        line = [r.ticket_number, r.pnr, r.passenger_name, r.airline_name, r.issue_date,
                r.travel_date, r.segment_type, r.booking_class, r.sector,
                _f(r.fare_amount), _f(r.yq), r.status, r.matched_deal_name, r.matched_deal_no,
                r.supplier_match_by, _f(r.incentive), _f(r.iata_commission)]
        if adapter.has_declared_amounts:
            line += [_f(r.declared_commission), _f(r.declared_incentive), _f(r.declared_tds),
                     ("yes" if r.declared_net_ok is True
                      else "no" if r.declared_net_ok is False else "unknown"),
                     _f(r.variance_commission), _f(r.variance_incentive), _f(r.variance_total)]
        line += [r.reason, "; ".join(r.notes or [])]
        ws.append(line)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    label = (spec.spec_for(source) or {}).get("label", source)
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="commission_{label}_{batch_id[:8]}.xlsx"'},
    )


@router.delete("/{source}/statements/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_calculations(
    source: str, batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Throw away this statement's figures without touching the statement itself.

    The statement rows stay; only what we derived from them goes. Useful after editing a
    deal, when the honest state is "not yet priced" rather than "priced under the old terms".
    """
    _adapter, source = _resolve(source)
    await db.execute(delete(Calc).where(*_scope(current_user), Calc.source == source,
                                        Calc.batch_id == batch_id))
    await db.execute(delete(CommissionRun).where(*_run_scope(current_user),
                                                 CommissionRun.source == source,
                                                 CommissionRun.batch_id == batch_id))
    await db.commit()
