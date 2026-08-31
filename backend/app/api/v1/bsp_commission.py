"""Commission income on BSP statements.

`Vendors data → Commission income`: pick a parsed BSP detailed statement, run the
calculation, and read back the estimated commission per settlement row.

The heavy lifting lives in `app.services.bsp_commission`; the run itself is a
Celery job because a BSP statement can hold tens of thousands of rows.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.bsp_statement import BspStatement, BspStatementRow, BspTaxBreakup
# Enrichment runs inside the commission run, so a TGQ HMPR uploaded afterwards is
# inert until a re-run — the detail screen says so, and needs this to know.
from app.models.statement_row import TgqHmpr
from app.models.user import User
from app.schemas.bsp_commission import (
    BspCommissionRowRead,
    BspCommissionRowsPage,
    BspCommissionRunResponse,
    BspCommissionStatementRead,
    BspCommissionSummary,
    BspCommissionReasonGroup,
)
from app.services.bsp_commission import BspCommissionService
from app.services.bsp_reconciliation import INCENTIVE_TYPE_KEYS

router = APIRouter()

_RUNNING = ("queued", "processing")

# A queued/processing run whose heartbeat has gone quiet this long has lost its
# worker (broker down, task dropped, worker killed). Treat it as recoverable so
# the UI can never wedge on a run that will never finish. The worker refreshes the
# heartbeat on every progress flush, so a slow run is never mistaken for a dead one.
STALE_AFTER = timedelta(minutes=5)

# A hand-picked selection runs inline in the request; this caps how many rows one
# such call may carry so it stays a quick check, not a full run in disguise.
MAX_INLINE_ROWS = 500
# Distinct (status, reason) buckets the gaps tab will return.
MAX_GAP_GROUPS = 50


def _is_stale(s: BspStatement) -> bool:
    if s.commission_status not in _RUNNING:
        return False
    beat = s.commission_heartbeat_at
    if beat is None:         # queued before this was tracked, or never stamped
        return True
    return datetime.utcnow() - beat > STALE_AFTER


def _progress_pct(s: BspStatement) -> int:
    if s.commission_status == "completed":
        return 100
    if s.commission_total_rows:
        return min(100, int(s.commission_processed_rows * 100 / s.commission_total_rows))
    return 0


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


async def _latest_tgq_upload(db: AsyncSession, user: User) -> datetime | None:
    """When this user last uploaded a TGQ HMPR statement.

    One query for a whole page of statements rather than one each. Used to tell
    the user that re-running would now find data it could not find before —
    enrichment happens inside the run, so a TGQ uploaded afterwards is inert
    until then, and nothing on screen said so.
    """
    return await db.scalar(
        select(func.max(TgqHmpr.uploaded_at)).where(
            TgqHmpr.tenant_id == user.tenant_id,
            TgqHmpr.created_by_id == user.id,
        )
    )


def _to_read(
    s: BspStatement, latest_tgq: datetime | None = None,
) -> BspCommissionStatementRead:
    return BspCommissionStatementRead(
        batch_id=s.batch_id,
        statement_name=s.statement_name,
        airline_code=s.airline_code,
        airline_name=s.airline_name,
        period_from=s.period_from,
        period_to=s.period_to,
        row_count=s.row_count,
        parse_status=s.status,
        status=s.commission_status,
        total_rows=s.commission_total_rows,
        processed_rows=s.commission_processed_rows,
        progress_pct=_progress_pct(s),
        error=s.commission_error,
        heartbeat_at=s.commission_heartbeat_at,
        is_stale=_is_stale(s),
        calculated_at=s.commission_calculated_at,
        total_incentive=_f(s.commission_total_incentive),
        iata_total=_f(s.commission_iata_total),
        matched_rows=s.commission_matched_rows,
        unmatched_rows=s.commission_unmatched_rows,
        excluded_rows=s.commission_excluded_rows,
        skipped_rows=s.commission_skipped_rows,
        needs_data_rows=s.commission_needs_data_rows,
        pending_rows=s.commission_pending_rows,
        enriched_rows=s.commission_enriched_rows,
        tgq_stale=bool(
            latest_tgq
            and s.commission_calculated_at
            and latest_tgq > s.commission_calculated_at
        ),
        created_at=s.created_at,
    )


async def _owned(batch_id: str, db: AsyncSession, user: User) -> BspStatement:
    stmt = await db.scalar(
        select(BspStatement).where(
            BspStatement.batch_id == batch_id,
            BspStatement.tenant_id == user.tenant_id,
            BspStatement.created_by_id == user.id,
        )
    )
    if not stmt:
        raise HTTPException(status_code=404, detail="BSP statement not found")
    return stmt


# ── Statement picker ───────────────────────────────────────────────────────

@router.get("/statements", response_model=list[BspCommissionStatementRead])
async def list_commission_statements(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every parsed BSP detailed statement, with its commission run state."""
    rows = (await db.execute(
        select(BspStatement)
        .where(
            BspStatement.tenant_id == current_user.tenant_id,
            BspStatement.created_by_id == current_user.id,
        )
        .order_by(BspStatement.created_at.desc())
    )).scalars().all()
    latest_tgq = await _latest_tgq_upload(db, current_user)
    return [_to_read(s, latest_tgq) for s in rows]


@router.get("/statements/{batch_id}", response_model=BspCommissionStatementRead)
async def get_commission_statement(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _to_read(
        await _owned(batch_id, db, current_user),
        await _latest_tgq_upload(db, current_user),
    )


# ── Run ────────────────────────────────────────────────────────────────────

class RunPayload(BaseModel):
    """Empty body → the whole statement (queued to the worker).
    `row_ids` → just those rows, calculated inline and returned immediately."""
    row_ids: Optional[list[int]] = Field(default=None)


@router.post(
    "/statements/{batch_id}/run",
    response_model=BspCommissionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_commission(
    batch_id: str,
    payload: RunPayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Calculate commission for a statement, or for a hand-picked set of rows.

    Idempotent either way — a run resets and recomputes whatever it covers.
    """
    stmt = await _owned(batch_id, db, current_user)

    if stmt.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="This statement has not finished parsing yet — there are no rows to calculate.",
        )

    row_ids = (payload.row_ids if payload else None) or []

    # ── Selected rows → inline, no worker needed ──────────────────────────
    if row_ids:
        if len(row_ids) > MAX_INLINE_ROWS:
            raise HTTPException(
                status_code=400,
                detail=f"Select at most {MAX_INLINE_ROWS} rows at a time, or run the whole statement.",
            )
        summary = await BspCommissionService.run_rows(
            db, batch_id=batch_id, tenant_id=current_user.tenant_id,
            created_by_id=current_user.id, row_ids=row_ids,
        )
        return BspCommissionRunResponse(
            batch_id=batch_id, status="completed", mode="inline",
            processed=summary.total, calculated=summary.calculated,
            reversed=summary.reversed_, excluded=summary.excluded,
            skipped=summary.skipped, unmatched=summary.unmatched,
            errors=summary.errors, total_incentive=round(summary.total_incentive, 2),
        )

    # ── Whole statement → the worker ──────────────────────────────────────
    if stmt.commission_status in _RUNNING and not _is_stale(stmt):
        raise HTTPException(status_code=409, detail="A calculation is already running for this statement.")

    stmt.commission_status = "queued"
    stmt.commission_error = None
    stmt.commission_processed_rows = 0
    stmt.commission_heartbeat_at = datetime.utcnow()
    await db.commit()

    # Publish only after the state is durable, and never leave the statement
    # claiming to be running if the broker would not take the job.
    try:
        from app.workers.bsp_commission_tasks import calculate_bsp_commission
        calculate_bsp_commission.delay(batch_id, current_user.tenant_id, current_user.id)
    except Exception as exc:  # noqa: BLE001 — broker down / not configured
        stmt.commission_status = "failed"
        stmt.commission_error = (
            "Could not queue the calculation — the background worker is unreachable. "
            f"Start Redis and a Celery worker on the 'bsp' queue, then try again. ({exc})"
        )[:2000]
        await db.commit()
        raise HTTPException(status_code=503, detail=stmt.commission_error)

    return BspCommissionRunResponse(batch_id=batch_id, status="queued", mode="queued")


@router.post("/statements/{batch_id}/reset", response_model=BspCommissionStatementRead)
async def reset_commission_run(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Release a run that will never finish, so the statement can be run again."""
    stmt = await _owned(batch_id, db, current_user)
    if stmt.commission_status in _RUNNING:
        stmt.commission_status = "idle"
        stmt.commission_error = None
        stmt.commission_processed_rows = 0
        await db.commit()
    return _to_read(stmt)


# ── Results ────────────────────────────────────────────────────────────────

def _row_conditions(
    batch_id: str, user: User, search: str | None, txn_type: str | None,
    air: str | None, comm_status: str | None, deal_id: int | None,
    enrichment: str | None = None,
) -> list:
    conds = [
        BspStatementRow.statement_id == batch_id,
        BspStatementRow.tenant_id == user.tenant_id,
        BspStatementRow.created_by_id == user.id,
    ]
    if search and search.strip():
        s = f"%{search.strip()}%"
        conds.append(or_(
            BspStatementRow.document_number.ilike(s),
            BspStatementRow.ticket_number.ilike(s),
            BspStatementRow.matched_deal_name.ilike(s),
            # so typing "DEL" finds every journey through Delhi
            BspStatementRow.enriched_sector.ilike(s),
        ))
    if txn_type:
        conds.append(BspStatementRow.transaction_type == txn_type)
    if air:
        conds.append(BspStatementRow.airline_accounting_code == air)
    if comm_status:
        conds.append(BspStatementRow.commission_status == comm_status)
    if deal_id is not None:
        conds.append(BspStatementRow.matched_deal_id == deal_id)
    if enrichment == "enriched":
        conds.append(BspStatementRow.enrichment_source.is_not(None))
    elif enrichment == "not_enriched":
        conds.append(BspStatementRow.enrichment_source.is_(None))
    return conds


async def _tax_map(db: AsyncSession, row_ids: list[int]) -> dict[int, dict[str, float]]:
    if not row_ids:
        return {}
    q = (
        select(
            BspTaxBreakup.bsp_row_id,
            BspTaxBreakup.component_code,
            func.sum(BspTaxBreakup.amount),
        )
        .where(
            BspTaxBreakup.bsp_row_id.in_(row_ids),
            func.upper(BspTaxBreakup.component_code).in_(["YQ", "YR"]),
        )
        .group_by(BspTaxBreakup.bsp_row_id, BspTaxBreakup.component_code)
    )
    out: dict[int, dict[str, float]] = {}
    for rid, code, amt in (await db.execute(q)).all():
        out.setdefault(rid, {})[(code or "").upper()] = float(amt or 0)
    return out


@router.get("/statements/{batch_id}/rows", response_model=BspCommissionRowsPage)
async def list_commission_rows(
    batch_id: str,
    offset: int = 0,
    limit: int = 100,
    search: Optional[str] = Query(None),
    txn_type: Optional[str] = Query(None),
    air: Optional[str] = Query(None),
    comm_status: Optional[str] = Query(None, description="calculated|excluded|reversed|skipped|unmatched|pending"),
    deal_id: Optional[int] = Query(None),
    enrichment: Optional[str] = Query(None, description="enriched|not_enriched"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned(batch_id, db, current_user)
    limit = max(1, min(limit, 500))
    conds = _row_conditions(batch_id, current_user, search, txn_type, air, comm_status, deal_id, enrichment)

    total = (await db.execute(
        select(func.count()).select_from(BspStatementRow).where(*conds)
    )).scalar_one()

    rows = (await db.execute(
        select(BspStatementRow)
        .where(*conds)
        .order_by(BspStatementRow.id.asc())
        .offset(offset).limit(limit)
    )).scalars().all()

    taxes = await _tax_map(db, [r.id for r in rows])

    out = [
        BspCommissionRowRead(
            id=r.id,
            document_number=r.document_number,
            ticket_number=r.ticket_number,
            transaction_type=r.transaction_type,
            airline_code=r.airline_code,
            airline_accounting_code=r.airline_accounting_code,
            airline_name=r.airline_name,
            issue_date=r.issue_date,
            stat=r.stat,
            form_of_payment=r.form_of_payment,
            fare_amount=_f(r.fare_amount),
            yq=taxes.get(r.id, {}).get("YQ"),
            yr=taxes.get(r.id, {}).get("YR"),
            transaction_amount=_f(r.transaction_amount),
            standard_commission_amount=_f(r.standard_commission_amount),
            matched_deal_id=r.matched_deal_id,
            matched_deal_type=r.matched_deal_type,
            matched_deal_name=r.matched_deal_name,
            calculated_incentive=_f(r.calculated_incentive),
            iata_commission=_f(r.iata_commission),
            incentive_breakdown=r.incentive_breakdown,
            commission_status=r.commission_status,
            commission_reason=r.commission_reason,
            skipped_criteria=r.skipped_criteria,
            enriched_sector=r.enriched_sector,
            enriched_booking_class=r.enriched_booking_class,
            enriched_travel_date=r.enriched_travel_date,
            enriched_travel_date_source=r.enriched_travel_date_source,
            enriched_leg_count=r.enriched_leg_count,
            enrichment_source=r.enrichment_source,
        )
        for r in rows
    ]
    return BspCommissionRowsPage(total=total, offset=offset, limit=limit, rows=out)


@router.get("/statements/{batch_id}/rows/facets")
async def commission_row_facets(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct values for the results-grid filter dropdowns."""
    await _owned(batch_id, db, current_user)
    scope = (
        BspStatementRow.statement_id == batch_id,
        BspStatementRow.tenant_id == current_user.tenant_id,
        BspStatementRow.created_by_id == current_user.id,
    )

    async def _distinct(col):
        return (await db.execute(
            select(col).where(*scope, col.isnot(None), col != "").distinct().order_by(col)
        )).scalars().all()

    return {
        "txn_types": await _distinct(BspStatementRow.transaction_type),
        "airlines": await _distinct(BspStatementRow.airline_accounting_code),
        "statuses": await _distinct(BspStatementRow.commission_status),
        "enrichment": await _distinct(BspStatementRow.enrichment_source),
    }


@router.get("/statements/{batch_id}/summary", response_model=BspCommissionSummary)
async def commission_summary(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-airline × incentive-type totals for this statement."""
    await _owned(batch_id, db, current_user)
    rows = (await db.execute(
        select(BspStatementRow).where(
            BspStatementRow.statement_id == batch_id,
            BspStatementRow.tenant_id == current_user.tenant_id,
            BspStatementRow.created_by_id == current_user.id,
            BspStatementRow.calculated_incentive.is_not(None),
        )
    )).scalars().all()
    return BspCommissionSummary(**BspCommissionService.summarise(rows))


@router.get("/statements/{batch_id}/gaps", response_model=list[BspCommissionReasonGroup])
async def commission_gaps(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unmatched / skipped rows grouped by reason, so the gaps are actionable."""
    await _owned(batch_id, db, current_user)
    rows = (await db.execute(
        select(
            BspStatementRow.commission_status,
            BspStatementRow.commission_reason,
            BspStatementRow.document_number,
        ).where(
            BspStatementRow.statement_id == batch_id,
            BspStatementRow.tenant_id == current_user.tenant_id,
            BspStatementRow.created_by_id == current_user.id,
            # `needs_data` belongs here: it is a gap the user can close, and the
            # reason string says how. `pending` deliberately does NOT — a row
            # nobody has run yet is not a shortfall in the deal setup, and adding
            # it would bury the real gaps under every untouched row.
            BspStatementRow.commission_status.in_(
                ["unmatched", "skipped", "excluded", "needs_data"]
            ),
        )
    )).all()

    groups: "OrderedDict[tuple, dict]" = OrderedDict()
    for st, reason, doc in rows:
        key = (st, reason or "—")
        g = groups.setdefault(key, {"status": st, "reason": reason or "—", "count": 0, "sample_documents": []})
        g["count"] += 1
        if doc and len(g["sample_documents"]) < 5:
            g["sample_documents"].append(doc)

    # Capped. This tab is a shortlist of things to act on, and one reason string
    # that accidentally varies per row (a ticket number in it, say) would other-
    # wise return a group per row — 12,000 groups and a megabyte of JSON.
    ordered = sorted(groups.values(), key=lambda g: (-g["count"], g["status"]))
    return [BspCommissionReasonGroup(**g) for g in ordered[:MAX_GAP_GROUPS]]


# ── Per-row diagnosis ("why did / didn't this match?") ─────────────────────

@router.get("/rows/{row_id}/matched-deals")
async def row_matched_deals(
    row_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every airline deal that matches this BSP row, best first."""
    from app.services.deal_matching import DealMatchingService

    row, ctx = await _row_context(row_id, db, current_user)
    if not ctx.airline_name or ctx.issue_date is None:
        return []

    # Same inputs the run used, or the popup would list deals the run never considered.
    matches = await DealMatchingService.find_all_deals(
        db=db, airline_name=ctx.airline_name, travel_date=ctx.travel_date or ctx.issue_date,
        tenant_id=current_user.tenant_id, created_by_id=current_user.id,
        issue_date=ctx.issue_date, segment_type=ctx.segment_type,
        booking_class=ctx.booking_class, invoice_type="Sales",
        sell_fare=ctx.fare_amount, sell_tax_yq=ctx.yq, sale_yr=ctx.yr,
        statement_type="AIRLINE", skip_criteria=ctx.skip_criteria,
    )
    return [
        {
            "deal_id": m.deal_id,
            "deal_no": m.deal_no,
            "deal_type": m.deal_type,
            "deal_name": m.deal_name,
            "deal_maker_name": m.deal_maker_name,
            "valid_from": m.valid_from,
            "valid_to": m.valid_to,
            "iata_commission": m.iata_commission,
            "calculated_incentive": m.calculated_incentive,
            "incentive_breakdown": m.incentive_breakdown,
            "is_best": i == 0,
        }
        for i, m in enumerate(matches)
    ]


@router.get("/rows/{row_id}/match-diagnosis")
async def row_match_diagnosis(
    row_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Step-by-step trace of every approved airline deal against this BSP row."""
    from app.services.deal_matching import DealMatchingService

    row, ctx = await _row_context(row_id, db, current_user)

    base = {
        "row_id": row.id,
        "document_number": row.document_number,
        "transaction_type": row.transaction_type,
        "raw_airline_code": row.airline_accounting_code or row.airline_code,
        "airline_resolved": ctx.airline_name,
        "issue_date": ctx.issue_date,
        "stat": row.stat,
        "segment_type": ctx.segment_type,
        "fare_amount": ctx.fare_amount,
        "sell_tax_yq": ctx.yq,
        "sale_yr": ctx.yr,
        "tour_code": ctx.tour_code,
        # The row's own truth, not a constant — an enriched row skipped nothing.
        "skipped_criteria": ctx.skipped_labels,
        "sector": ctx.sector,
        "booking_class": ctx.booking_class,
        "travel_date": ctx.travel_date,
        "travel_date_source": ctx.travel_date_source,
        "leg_count": ctx.leg_count,
        "enrichment_source": ctx.enrichment_source,
        "enrichment_ref": ctx.enrichment_ref,
        "commission_status": row.commission_status,
        "commission_reason": row.commission_reason,
    }

    if not ctx.airline_name:
        return {**base, "deals": [], "total_deals_checked": 0, "matched_count": 0,
                "note": "Airline code is not in the airline master — no deal can match."}
    if ctx.issue_date is None:
        return {**base, "deals": [], "total_deals_checked": 0, "matched_count": 0,
                "note": "Row has no issue date — deal validity cannot be checked."}

    deals = await DealMatchingService.diagnose_match(
        db=db, airline_name=ctx.airline_name, travel_date=ctx.travel_date or ctx.issue_date,
        tenant_id=current_user.tenant_id, created_by_id=current_user.id,
        issue_date=ctx.issue_date, segment_type=ctx.segment_type,
        booking_class=ctx.booking_class, invoice_type="Sales",
        sell_fare=ctx.fare_amount, sell_tax_yq=ctx.yq, sale_yr=ctx.yr,
        ticket_sector=ctx.sector,
        ticket_date_raw=ctx.issue_date.isoformat(),
        ticket_departure_raw=ctx.travel_date.isoformat() if ctx.travel_date else None,
        ticket_airline_name=ctx.airline_name,
        tour_code=ctx.tour_code,
        statement_type="AIRLINE",
        skip_criteria=ctx.skip_criteria,
        rule_skip_fields=ctx.skip_rule_fields,
    )
    return {
        **base,
        "deals": deals,
        "total_deals_checked": len(deals),
        "matched_count": sum(1 for d in deals if getattr(d, "overall_match", False)),
    }


async def _row_context(row_id: int, db: AsyncSession, user: User):
    from app.services.bsp_commission import load_row_contexts

    row = await db.scalar(
        select(BspStatementRow).where(
            BspStatementRow.id == row_id,
            BspStatementRow.tenant_id == user.tenant_id,
            BspStatementRow.created_by_id == user.id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="BSP row not found")
    ctx = (await load_row_contexts(db, [row]))[0]
    return row, ctx


# ── Export ─────────────────────────────────────────────────────────────────

@router.get("/statements/{batch_id}/xlsx")
async def export_commission_xlsx(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from openpyxl import Workbook

    stmt = await _owned(batch_id, db, current_user)
    rows = (await db.execute(
        select(BspStatementRow).where(
            BspStatementRow.statement_id == batch_id,
            BspStatementRow.tenant_id == current_user.tenant_id,
            BspStatementRow.created_by_id == current_user.id,
        ).order_by(BspStatementRow.id.asc())
    )).scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Commission income"
    header = [
        "Document #", "Ticket #", "TRNC", "Airline", "Issue Date", "STAT", "FOP",
        "Sector", "Class", "Travel Date", "Enriched From",
        "Fare", "Std Comm", "Matched Deal", *INCENTIVE_TYPE_KEYS,
        "IATA Comm", "Estimated Commission", "Status", "Reason",
    ]
    ws.append(header)
    for r in rows:
        bd = r.incentive_breakdown or {}
        ws.append([
            r.document_number, r.ticket_number, r.transaction_type,
            r.airline_name or r.airline_accounting_code or r.airline_code,
            r.issue_date.isoformat() if r.issue_date else None,
            r.stat, r.form_of_payment,
            r.enriched_sector, r.enriched_booking_class,
            r.enriched_travel_date.isoformat() if r.enriched_travel_date else None,
            r.enrichment_source,
            _f(r.fare_amount), _f(r.standard_commission_amount),
            r.matched_deal_name,
            *[bd.get(k) for k in INCENTIVE_TYPE_KEYS],
            _f(r.iata_commission), _f(r.calculated_incentive),
            r.commission_status, r.commission_reason,
        ])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = (stmt.statement_name or stmt.file_name or batch_id).rsplit(".", 1)[0]
    stamp = datetime.utcnow().strftime("%Y%m%d")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="commission-income-{name}-{stamp}.xlsx"'},
    )
