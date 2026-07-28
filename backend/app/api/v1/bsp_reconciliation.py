"""Airline / BSP reconciliation — run the engine, list results with filters, drill in."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.ticket_reconciliation import TicketReconciliation
from app.models.uploaded_ticket import UploadedTicket
from app.models.bsp_statement import BspStatementRow, BspTaxBreakup
from app.schemas.ticket_reconciliation import (
    RunReconciliationPayload, ReconciliationRunResult,
    ReconciliationPage, ReconciliationSummary, ReconciliationRowRead,
    ReconciliationDetail, FieldDiff, ReconciliationIssue,
    RECON_STATUSES,
)
from app.schemas.bsp_statement import BspStatementRowRead, BspTaxComponentRead
from app.schemas.uploaded_ticket import UploadedTicketRead
from app.services.bsp_reconciliation import BspReconciliationService

router = APIRouter()

_COUNT_KEYS = ["matched", "minor_diff", "mismatch", "missing_bsp", "extra_bsp", "possible_match"]


def _scope(user: User):
    return (
        TicketReconciliation.tenant_id == user.tenant_id,
        TicketReconciliation.created_by_id == user.id,
    )


@router.post("/run", response_model=ReconciliationRunResult)
async def run_reconciliation(
    payload: RunReconciliationPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """(Re)compute reconciliation across all the user's tickets + BSP rows and persist."""
    s = await BspReconciliationService.run(
        db,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        commission_source=payload.commission_source,
        statement_id=payload.statement_id,
    )
    return ReconciliationRunResult(
        run_id=s.run_id, reconciled_at=s.reconciled_at, total=s.total,
        matched=s.matched, minor_diff=s.minor_diff, mismatch=s.mismatch,
        missing_bsp=s.missing_bsp, extra_bsp=s.extra_bsp, possible_match=s.possible_match,
        total_abs_variance=s.total_abs_variance,
    )


@router.get("/", response_model=ReconciliationPage)
async def list_reconciliation(
    date_from: date | None = Query(None, description="Filter by issue_date >="),
    date_to:   date | None = Query(None, description="Filter by issue_date <="),
    airline:   str | None = Query(None, description="airline_name match"),
    status:    str | None = Query(None, description="match_status filter"),
    txn_type:  str | None = Query(None, description="TKTT/ADM/ACM/RA/RFND/EMD/EXCH"),
    search:    str | None = Query(None, description="ticket_number contains"),
    offset:    int = Query(0, ge=0),
    limit:     int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = []
    if date_from:
        filters.append(TicketReconciliation.issue_date >= date_from)
    if date_to:
        filters.append(TicketReconciliation.issue_date <= date_to)
    if airline and airline.strip() and airline.lower() != "all":
        filters.append(TicketReconciliation.airline_name.ilike(f"%{airline.strip()}%"))
    if status and status.strip() and status.lower() != "all":
        if status not in RECON_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {sorted(RECON_STATUSES)}")
        filters.append(TicketReconciliation.match_status == status)
    if txn_type and txn_type.strip() and txn_type.lower() != "all":
        filters.append(func.upper(TicketReconciliation.txn_type) == txn_type.strip().upper())
    if search and search.strip():
        filters.append(TicketReconciliation.ticket_number.ilike(f"%{search.strip()}%"))

    where = (*_scope(current_user), *filters)

    # Summary over the FILTERED set (grouped counts + variance sum) so cards match the grid.
    grp = (
        await db.execute(
            select(
                TicketReconciliation.match_status,
                func.count(),
                func.coalesce(func.sum(TicketReconciliation.abs_variance), 0),
            ).where(*where).group_by(TicketReconciliation.match_status)
        )
    ).all()
    counts = {k: 0 for k in _COUNT_KEYS}
    total = 0
    total_variance = 0.0
    for st, cnt, var in grp:
        total += cnt
        total_variance += float(var or 0)
        if st in counts:
            counts[st] = cnt

    last_run = await db.scalar(select(func.max(TicketReconciliation.reconciled_at)).where(*_scope(current_user)))

    summary = ReconciliationSummary(
        total=total, total_variance=round(total_variance, 2), last_run_at=last_run, **counts,
    )

    rows = (await db.execute(
        select(TicketReconciliation)
        .where(*where)
        .order_by(TicketReconciliation.abs_variance.desc().nullslast(), TicketReconciliation.id.desc())
        .offset(offset).limit(limit)
    )).scalars().all()

    row_reads = [
        ReconciliationRowRead(
            id=r.id, ticket_id=r.ticket_id, bsp_row_id=r.bsp_row_id,
            ticket_number=r.ticket_number, airline_name=r.airline_name, airline_code=r.airline_code,
            issue_date=r.issue_date, txn_type=r.txn_type, match_status=r.match_status,
            severity=r.severity, net_variance=_f(r.net_variance), abs_variance=_f(r.abs_variance),
            issue_count=len(r.issues or []),
        )
        for r in rows
    ]
    return ReconciliationPage(summary=summary, total=total, offset=offset, limit=limit, rows=row_reads)


@router.get("/{recon_id}", response_model=ReconciliationDetail)
async def get_reconciliation(
    recon_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = (await db.execute(
        select(TicketReconciliation).where(TicketReconciliation.id == recon_id, *_scope(current_user))
    )).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Reconciliation record not found")

    fields = [FieldDiff(**{k: fd.get(k) for k in ("field", "label", "expected", "actual", "variance", "match", "severity")})
              for fd in (r.field_diffs or [])]
    issues = [ReconciliationIssue(**{k: iss.get(k) for k in ("rule_id", "field", "severity", "message", "expected", "actual", "variance")})
              for iss in (r.issues or [])]

    # Full records for the side-by-side popup (BSP statement vs internal ticket).
    ticket_out = None
    if r.ticket_id is not None:
        ticket = (await db.execute(
            select(UploadedTicket).where(
                UploadedTicket.id == r.ticket_id,
                UploadedTicket.tenant_id == current_user.tenant_id,
            )
        )).scalar_one_or_none()
        if ticket is not None:
            ticket_out = UploadedTicketRead.model_validate(ticket)

    bsp_out = None
    if r.bsp_row_id is not None:
        bsp_row = (await db.execute(
            select(BspStatementRow).where(BspStatementRow.id == r.bsp_row_id)
        )).scalar_one_or_none()
        if bsp_row is not None:
            bsp_out = BspStatementRowRead.model_validate(bsp_row)
            # Attach tax/fee components in one query (mirror bsp.py /rows).
            taxes = (await db.execute(
                select(BspTaxBreakup).where(BspTaxBreakup.bsp_row_id == r.bsp_row_id)
            )).scalars().all()
            bsp_out.taxes = [BspTaxComponentRead.model_validate(t) for t in taxes]

    return ReconciliationDetail(
        id=r.id, ticket_id=r.ticket_id, bsp_row_id=r.bsp_row_id,
        ticket_number=r.ticket_number, airline_name=r.airline_name, airline_code=r.airline_code,
        issue_date=r.issue_date, txn_type=r.txn_type, match_status=r.match_status, severity=r.severity,
        net_variance=_f(r.net_variance), abs_variance=_f(r.abs_variance), issue_count=len(r.issues or []),
        pax_name=r.pax_name, match_method=r.match_method, commission_source=r.commission_source,
        reconciled_at=r.reconciled_at, remarks=r.remarks,
        fields=fields, issues=issues, related_bsp=r.related_bsp or [],
        bsp_row=bsp_out, ticket=ticket_out,
    )


def _f(v):
    return float(v) if v is not None else None
