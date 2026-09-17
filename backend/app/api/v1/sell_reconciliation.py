"""Buy-vs-sell reconciliation for every non-BSP source — run it, list it, drill in.

Mounted at `/reconciliation/vendor`, alongside `/bsp-reconciliation` and NEVER aliased onto
it. BSP keeps its own router, its own storage and its own question; the frontend picks a
base URL per source tab, which is the whole coupling between the two. The same arrangement
`/bsp-commission` has with `/commission/vendor`, for the same reasons.

The endpoint set mirrors `/bsp-reconciliation` deliberately — run, list, detail — so one
frontend component serves every tab. The additions are `/facets` (the grid is flat across
every statement of a source, so it needs a statement filter) and the buy/sell vocabulary.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.sell_reconciliation import (
    SELL_RECON_STATUSES, SellReconciliation, SellReconciliationRun,
)
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User
from app.schemas.sell_reconciliation import (
    BuySellFieldDiff, RunSellReconciliationPayload, SellReconciliationDetail,
    SellReconciliationFacets, SellReconciliationIssue, SellReconciliationPage,
    SellReconciliationRowRead, SellReconciliationRunResult, SellReconciliationSummary,
)
from app.schemas.uploaded_ticket import UploadedTicketRead
from app.services.reconciliation import get_adapter
from app.services.sell_reconciliation import SellReconciliationService

router = APIRouter()

_COUNT_KEYS = ["matched", "minor_diff", "mismatch", "buy_only", "sell_only", "possible_match"]
# Only these pair the two sides, so only these carry a meaningful buy, sell or margin.
_PAIRED = ("matched", "minor_diff", "mismatch")


def _resolve(source: str):
    """(adapter, normalized source) or 404 — same discipline as commission._resolve.

    The adapter's OWN slug is returned, so a URL casing variant can never fork the ledger.
    """
    adapter = get_adapter(source)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"Unknown reconciliation source '{source}'.")
    return adapter, adapter.source


def _scope(user: User, source: str):
    return (
        SellReconciliation.tenant_id == user.tenant_id,
        SellReconciliation.created_by_id == user.id,
        SellReconciliation.source == source,
    )


def _f(v) -> float | None:
    return float(v) if v is not None else None


@router.post("/{source}/run", response_model=SellReconciliationRunResult)
async def run_sell_reconciliation(
    source: str,
    payload: RunSellReconciliationPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recompute this source's buy-vs-sell answer and persist it.

    Synchronous, like `/bsp-reconciliation/run`: the work is two indexed reads and a
    set-based match, not a page-by-page parse.
    """
    _adapter, source = _resolve(source)
    s = await SellReconciliationService.run(
        db, source=source, tenant_id=current_user.tenant_id,
        created_by_id=current_user.id, batch_id=payload.batch_id,
    )
    return SellReconciliationRunResult(
        run_id=s.run_id, reconciled_at=s.reconciled_at, total=s.total,
        matched=s.matched, minor_diff=s.minor_diff, mismatch=s.mismatch,
        buy_only=s.buy_only, sell_only=s.sell_only, possible_match=s.possible_match,
        total_buy=s.total_buy, total_sell=s.total_sell, total_margin=s.total_margin,
    )


@router.get("/{source}/", response_model=SellReconciliationPage)
async def list_sell_reconciliation(
    source: str,
    batch_id: str | None = Query(None, description="One statement, or all when absent"),
    date_from: date | None = Query(None, description="Filter by issue_date >="),
    date_to: date | None = Query(None, description="Filter by issue_date <="),
    airline: str | None = Query(None, description="airline_name match"),
    status: str | None = Query(None, description="match_status filter"),
    search: str | None = Query(None, description="ticket_number contains"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _adapter, source = _resolve(source)

    filters = []
    if batch_id and batch_id.strip() and batch_id.lower() != "all":
        filters.append(SellReconciliation.batch_id == batch_id.strip())
    if date_from:
        filters.append(SellReconciliation.issue_date >= date_from)
    if date_to:
        filters.append(SellReconciliation.issue_date <= date_to)
    if airline and airline.strip() and airline.lower() != "all":
        filters.append(SellReconciliation.airline_name.ilike(f"%{airline.strip()}%"))
    if status and status.strip() and status.lower() != "all":
        if status not in SELL_RECON_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Allowed: {sorted(SELL_RECON_STATUSES)}")
        filters.append(SellReconciliation.match_status == status)
    if search and search.strip():
        like = f"%{search.strip()}%"
        # Either half, or the whole number as printed on the coupon — the two are stored
        # apart but read as one.
        filters.append(or_(
            SellReconciliation.ticket_number.ilike(like),
            (func.coalesce(SellReconciliation.ticket_prefix, "")
             + func.coalesce(SellReconciliation.ticket_number, "")).ilike(like),
        ))

    where = (*_scope(current_user, source), *filters)

    # Summary over the FILTERED set, so the tiles can never disagree with the grid.
    grp = (await db.execute(
        select(
            SellReconciliation.match_status,
            func.count(),
            func.coalesce(func.sum(SellReconciliation.buy_net), 0),
            func.coalesce(func.sum(SellReconciliation.sell_net), 0),
            func.coalesce(func.sum(SellReconciliation.margin), 0),
        ).where(*where).group_by(SellReconciliation.match_status)
    )).all()

    counts = {k: 0 for k in _COUNT_KEYS}
    total = 0
    total_buy = total_sell = total_margin = 0.0
    for st, cnt, buy, sell, margin in grp:
        total += cnt
        if st in counts:
            counts[st] = cnt
        if st in _PAIRED:
            total_buy += float(buy or 0)
            total_sell += float(sell or 0)
            total_margin += float(margin or 0)

    last_run = await db.scalar(
        select(func.max(SellReconciliation.reconciled_at))
        .where(*_scope(current_user, source)))

    summary = SellReconciliationSummary(
        total=total, total_buy=round(total_buy, 2), total_sell=round(total_sell, 2),
        total_margin=round(total_margin, 2), last_run_at=last_run, **counts,
    )

    rows = (await db.execute(
        select(SellReconciliation).where(*where)
        # Worst first: the point of the screen is the tickets that lost money, and a row
        # that reconciled exactly needs no attention.
        .order_by(SellReconciliation.abs_margin.desc().nullslast(),
                  SellReconciliation.id.desc())
        .offset(offset).limit(limit)
    )).scalars().all()

    return SellReconciliationPage(
        summary=summary, total=total, offset=offset, limit=limit,
        rows=[
            SellReconciliationRowRead(
                id=r.id, source=r.source, batch_id=r.batch_id,
                source_row_id=r.source_row_id, ticket_id=r.ticket_id,
                ticket_number=r.ticket_number, ticket_prefix=r.ticket_prefix,
                airline_name=r.airline_name,
                airline_code=r.airline_code, issue_date=r.issue_date,
                sector=r.sector, pax_name=r.pax_name,
                match_status=r.match_status, severity=r.severity,
                match_method=r.match_method,
                buy_net=_f(r.buy_net), sell_net=_f(r.sell_net),
                margin=_f(r.margin), abs_margin=_f(r.abs_margin),
                sell_legs=r.sell_legs, buy_rows=r.buy_rows,
                issue_count=len(r.issues or []),
            )
            for r in rows
        ],
    )


@router.get("/{source}/facets", response_model=SellReconciliationFacets)
async def sell_reconciliation_facets(
    source: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Filter-bar options.

    Statements come from the ADAPTER, not from the reconciliation rows: a statement that
    has never been reconciled must still be selectable, or the only way to discover it is
    to already have run the thing.
    """
    adapter, source = _resolve(source)
    batches = await adapter.list_batches(db, current_user.tenant_id, current_user.id)
    airlines = (await db.execute(
        select(SellReconciliation.airline_name)
        .where(*_scope(current_user, source), SellReconciliation.airline_name.isnot(None))
        .distinct().order_by(SellReconciliation.airline_name)
    )).scalars().all()
    return SellReconciliationFacets(
        airlines=list(airlines), batches=batches, statuses=sorted(SELL_RECON_STATUSES))


@router.get("/{source}/rows/{recon_id}", response_model=SellReconciliationDetail)
async def sell_reconciliation_detail(
    source: str,
    recon_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    adapter, source = _resolve(source)
    r = (await db.execute(
        select(SellReconciliation)
        .where(*_scope(current_user, source), SellReconciliation.id == recon_id)
    )).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Reconciliation row not found.")

    ticket = None
    if r.ticket_id:
        # Tenant-scoped on purpose. The BSP detail endpoint fetches its statement row
        # without one; not repeating that here.
        ticket = (await db.execute(
            select(UploadedTicket).where(
                UploadedTicket.id == r.ticket_id,
                UploadedTicket.tenant_id == current_user.tenant_id)
        )).scalar_one_or_none()

    buy_row = None
    if r.source_row_id is not None:
        model = getattr(adapter, "model", None)
        if model is not None:
            row = (await db.execute(
                select(model).where(model.id == r.source_row_id,
                                    model.tenant_id == current_user.tenant_id)
            )).scalar_one_or_none()
            if row is not None:
                buy_row = dict(getattr(row, "data", None) or {})
                buy_row["_source_file"] = getattr(row, "source_file", None)

    return SellReconciliationDetail(
        id=r.id, source=r.source, batch_id=r.batch_id, source_row_id=r.source_row_id,
        ticket_id=r.ticket_id, ticket_number=r.ticket_number,
        ticket_prefix=r.ticket_prefix,
        airline_name=r.airline_name, airline_code=r.airline_code,
        issue_date=r.issue_date, sector=r.sector, pax_name=r.pax_name,
        match_status=r.match_status, severity=r.severity, match_method=r.match_method,
        buy_net=_f(r.buy_net), sell_net=_f(r.sell_net),
        margin=_f(r.margin), abs_margin=_f(r.abs_margin),
        sell_legs=r.sell_legs, buy_rows=r.buy_rows,
        issue_count=len(r.issues or []),
        reconciled_at=r.reconciled_at, remarks=r.remarks,
        fields=[BuySellFieldDiff(**d) for d in (r.field_diffs or [])],
        issues=[SellReconciliationIssue(**i) for i in (r.issues or [])],
        notes=list(r.notes or []),
        buy_row=buy_row,
        ticket=UploadedTicketRead.model_validate(ticket) if ticket else None,
    )


@router.get("/{source}/runs/latest")
async def latest_run(
    source: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The most recent attempt, so the screen can say when it last ran and whether it failed."""
    _adapter, source = _resolve(source)
    run = (await db.execute(
        select(SellReconciliationRun)
        .where(SellReconciliationRun.tenant_id == current_user.tenant_id,
               SellReconciliationRun.created_by_id == current_user.id,
               SellReconciliationRun.source == source)
        .order_by(SellReconciliationRun.started_at.desc().nullslast(),
                  SellReconciliationRun.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if run is None:
        return {"status": "idle", "source": source}
    return {
        "status": run.status, "source": run.source, "run_id": run.id,
        "batch_id": run.batch_id, "started_at": run.started_at,
        "completed_at": run.completed_at, "error": run.error,
        "total_rows": run.total_rows, "total_margin": _f(run.total_margin),
    }
