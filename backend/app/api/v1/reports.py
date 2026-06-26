from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.uploaded_ticket import UploadedTicket
from app.models.ticket_statement import TicketStatement

router = APIRouter()

# Must stay byte-identical to INCENTIVE_TYPE_KEYS in tickets.py and the
# frontend INCENTIVE_TYPE_COLS.
INCENTIVE_TYPE_KEYS = [
    "PLB", "Super PLB", "Transaction Fee", "Deposit Incentive (DI)",
    "Marketing Fund", "Ancillary", "Frontend", "Backend", "Cashback",
    "Segment Incentive", "Push Action",
]


def _f(v) -> float:
    return float(v) if v is not None else 0.0


@router.get("/by-airline")
async def report_by_airline(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.by_airline(db, period_from=period_from, period_to=period_to)


@router.get("/by-supplier")
async def report_by_supplier(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.by_supplier(db, period_from=period_from, period_to=period_to)


@router.get("/by-route")
async def report_by_route(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    airline_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.by_route(db, period_from=period_from, period_to=period_to, airline_id=airline_id)


@router.get("/by-class")
async def report_by_class(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.by_class(db, period_from=period_from, period_to=period_to)


@router.get("/dashboard")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.dashboard_stats(db)


@router.get("/supplier-wise")
async def report_supplier_wise(
    supplier:  str = Query(..., description="Supplier (agency) name from the supplier master"),
    date_from: Optional[date] = Query(None, description="Include statements valid on/after this date"),
    date_to:   Optional[date] = Query(None, description="Include statements valid on/before this date"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate uploaded-ticket income for one supplier over a date range.

    A supplier maps to TicketStatement.agency. The date range filters statements
    by validity-period overlap; the matching statements' tickets are aggregated
    per incentive type, plus ticket count, sell fare, commission and total income.
    """
    # 1. Matching statements for this supplier (scoped to the current user/tenant)
    stmt_q = select(TicketStatement).where(
        TicketStatement.agency == supplier,
        TicketStatement.tenant_id == current_user.tenant_id,
        TicketStatement.created_by_id == current_user.id,
    )
    if date_from:                                  # overlap: drop statements ending before range start
        stmt_q = stmt_q.where(TicketStatement.valid_to >= date_from)
    if date_to:                                    # overlap: drop statements starting after range end
        stmt_q = stmt_q.where(TicketStatement.valid_from <= date_to)
    statements = (await db.execute(stmt_q)).scalars().all()

    empty = {
        "supplier": supplier,
        "date_from": date_from,
        "date_to": date_to,
        "ticket_count": 0,
        "statement_count": 0,
        "total_sell_fare": 0.0,
        "total_commission": 0.0,
        "total_income": 0.0,
        "incentive_totals": {k: 0.0 for k in INCENTIVE_TYPE_KEYS},
        "statements": [],
    }
    if not statements:
        return empty

    stmt_by_batch = {s.batch_id: s for s in statements}
    batch_ids = list(stmt_by_batch.keys())

    # 2. Tickets for those statements
    tickets = (await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.batch_id.in_(batch_ids),
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
        )
    )).scalars().all()

    # 3. Aggregate overall + per statement
    totals = {k: 0.0 for k in INCENTIVE_TYPE_KEYS}
    total_income = total_sell_fare = total_commission = 0.0
    per_stmt: dict[str, dict] = {
        bid: {"ticket_count": 0, "total_income": 0.0} for bid in batch_ids
    }
    for t in tickets:
        bd = t.incentive_breakdown or {}
        for k in INCENTIVE_TYPE_KEYS:
            v = bd.get(k)
            if v is not None:
                totals[k] += float(v)
        inc = _f(t.calculated_incentive)
        total_income    += inc
        total_sell_fare += _f(t.sell_fare)
        total_commission += _f(t.comm_sell)
        ps = per_stmt.get(t.batch_id)
        if ps is not None:
            ps["ticket_count"] += 1
            ps["total_income"] += inc

    statements_out = sorted(
        [
            {
                "batch_id":       s.batch_id,
                "statement_name": s.statement_name,
                "statement_type": getattr(s, "statement_type", "B2B") or "B2B",
                "valid_from":     s.valid_from,
                "valid_to":       s.valid_to,
                "ticket_count":   per_stmt[s.batch_id]["ticket_count"],
                "total_income":   round(per_stmt[s.batch_id]["total_income"], 2),
            }
            for s in statements
        ],
        key=lambda x: (x["valid_from"] or date.min),
    )

    return {
        "supplier": supplier,
        "date_from": date_from,
        "date_to": date_to,
        "ticket_count": len(tickets),
        "statement_count": len(statements),
        "total_sell_fare": round(total_sell_fare, 2),
        "total_commission": round(total_commission, 2),
        "total_income": round(total_income, 2),
        "incentive_totals": {k: round(v, 2) for k, v in totals.items()},
        "statements": statements_out,
    }
