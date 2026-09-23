"""The income board: what we earned, by airline and by consolidator.

EVERY FIGURE IS AGGREGATED IN SQL. The existing /dashboard/income-summary loads every
matching ticket into Python and sums it in a loop; at this table's grain — one row per
priced settlement document — that would mean pulling tens of thousands of rows to
render six tiles. Each endpoint here issues one GROUP BY.

SCOPING IS MANUAL AND DOUBLE, as everywhere in this repo: `tenant_id` AND
`created_by_id`. The one departure is the agency-wide scope, which drops
`created_by_id` deliberately and is gated on role — see `_scope`. It exists because
"which airline earns us most" is a question about the business, not about one person's
uploads, and with two people loading statements neither would otherwise ever see the
whole picture.

WHAT THIS MODULE REFUSES TO DO. It does not coalesce a NULL incentive to zero, it does
not add `iata_commission` into an incentive total, and it does not let a memo into a
revenue denominator. Those three are enforced in services/income_board/measures.py so
that no endpoint can quietly decide otherwise; this module only chooses dimensions and
filters.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.airline import Airline
from app.models.income_board import (
    DIRECTION_INBOUND, TXN_CREDIT_MEMO, TXN_DEBIT_MEMO, IncomeBoardRow as R,
)
from app.models.user import User, UserRole, role_matches
from app.schemas.income_board import (
    AirlinePoint, FilterOptions, FreshnessResponse, IncomeSummaryResponse, IncomeTotals,
    MonthPoint, SourceFreshness, SourcePoint, SupplierPoint,
)
from app.services.income_board import (
    PROJECTED_SOURCES, measures, project_batch, stamp_bsp_ndc_overlap,
)
from app.services.income_board.project import batch_changes
from app.services.report_download.registry import SOURCE_BY_KEY

logger = logging.getLogger(__name__)

router = APIRouter()

# Who may look past their own uploads at the whole workspace. Deliberately narrow: the
# board shows what every user in the tenant earned, which is not every user's business.
AGENCY_SCOPE_ROLES = (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)

# Who may trigger a rebuild. It is a write over the whole workspace's projection.
REBUILD_ROLES = (UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN)

# Derived from the report registry, not retyped beside it. The hand-written copy this
# replaced had already drifted — "Third party (GDS)" here against "Third Party GDS"
# there — so the same upload was called two different things on two screens.
_SOURCE_LABELS = {
    **{key: src.sheet_title for key, src in SOURCE_BY_KEY.items()},
    # The one source the report has no entry for: the selling side, which is not a
    # vendor statement at all.
    "uploaded-ticket": "Sell book",
}

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def can_view_agency(user: User) -> bool:
    """role_matches, not ==: users.role stores the enum NAME, not its value."""
    return role_matches(user.role, *AGENCY_SCOPE_ROLES)


def _scope(user: User, scope: str):
    """The scope predicate. `agency` drops created_by_id; everything else keeps it."""
    if scope == "agency":
        if not can_view_agency(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a Super Admin or Company Admin can view agency-wide income.",
            )
        return (R.tenant_id == user.tenant_id,)
    return (R.tenant_id == user.tenant_id, R.created_by_id == user.id)


def _filters(
    *, basis: str, date_from: date | None, date_to: date | None,
    airline: list[int] | None, supplier: list[int] | None, source: list[str] | None,
    direction: str = DIRECTION_INBOUND,
):
    """Everything the caller narrowed by, as a list of predicates.

    `basis` picks which date the period means. An airline consolidator reads these
    differently on purpose: sales basis is when the ticket was issued, travel basis is
    when it flew, and the same month holds different money under each.

    `priced` IS NOT OPTIONAL AND IS NOT A NARROWING. `income_board_rows` stopped being
    "every priced line" and became every statement line, priced or not, so that
    /dashboard/revenue can answer what was SOLD. Without this predicate every count on
    this board silently absorbs the unpriced half: `rows` stops meaning priced lines,
    `unattributed_airline_rows` picks up every Third Party API row (which has no carrier
    by nature), and the airline ranking fills with carriers that earned nothing because
    nobody has costed them yet. It lives here, at the bottom of the funnel every query
    in this module builds its WHERE from, rather than in each of them.
    """
    col = R.travel_date if basis == "travel" else R.issue_date
    conds = [R.direction == direction, R.priced.is_(True)]
    if date_from:
        conds.append(col >= date_from)
    if date_to:
        conds.append(col <= date_to)
    if airline:
        conds.append(R.airline_id.in_(airline))
    if supplier:
        conds.append(R.supplier_id.in_(supplier))
    if source:
        conds.append(R.source.in_(source))
    return conds


def _ym_col(basis: str):
    return R.travel_ym if basis == "travel" else R.issue_ym


def _f(v) -> float | None:
    """Decimal -> float, preserving NULL. NULL is a different claim from 0."""
    return None if v is None else float(v)


def _pareto(rows: list, value_index: int) -> list[tuple]:
    """Attach share and running share. Ranking is by the incentive, never by gross."""
    total = sum(float(r[value_index] or 0) for r in rows)
    out, running = [], 0.0
    for r in rows:
        v = float(r[value_index] or 0)
        running += v
        out.append((
            round(v / total * 100, 2) if total else 0.0,
            round(running / total * 100, 2) if total else 0.0,
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Summary — the whole board in one round trip
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/summary", response_model=IncomeSummaryResponse)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="mine", pattern="^(mine|agency)$"),
    basis: str = Query(default="issue", pattern="^(issue|travel)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    airline: list[int] | None = Query(default=None),
    supplier: list[int] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    top: int = Query(default=10, ge=3, le=50),
):
    """KPI band, month series, and the two rankings the board exists for.

    One endpoint rather than five, because the tiles and the charts must agree and the
    cheapest way to guarantee that is to compute them from the same predicates in the
    same request.
    """
    where = [*_scope(current_user, scope),
             *_filters(basis=basis, date_from=date_from, date_to=date_to,
                       airline=airline, supplier=supplier, source=source)]

    totals_row = (await db.execute(
        select(
            measures.incentive_sum(DIRECTION_INBOUND),
            measures.iata_sum(DIRECTION_INBOUND),
            measures.gross_revenue(DIRECTION_INBOUND),
            measures.incentive_sum("outbound"),
            measures.markup_sum(),
            func.count(),
            measures.needs_data_count(),
            func.count().filter(R.status == "unmatched"),
            func.count().filter(R.airline_id.is_(None)),
            # Only third-party rows can lack a consolidator; BSP and LCC have none by
            # nature, so counting them here would invent a data-quality problem.
            func.count().filter(and_(R.counterparty_kind == "supplier",
                                     R.supplier_id.is_(None))),
            measures.memo_exposure(TXN_DEBIT_MEMO),
            measures.memo_exposure(TXN_CREDIT_MEMO),
            func.count().filter(R.slab_dependent.is_(True)),
        ).where(*where)
    )).one()

    vendor, iata, gross, paid, markup = (_f(x) for x in totals_row[:5])
    totals = IncomeTotals(
        vendor_income=vendor, iata_commission=iata, gross_revenue=gross,
        commission_paid=paid, markup_income=markup,
        spread=(vendor or 0) - (paid or 0) + (markup or 0),
        rows=totals_row[5], needs_data_rows=totals_row[6],
        unmatched_rows=totals_row[7],
        unattributed_airline_rows=totals_row[8],
        unattributed_supplier_rows=totals_row[9],
        debit_memo_amount=_f(totals_row[10]),
        credit_memo_amount=_f(totals_row[11]),
        slab_dependent_rows=totals_row[12],
    )

    ym = _ym_col(basis)
    month_rows = (await db.execute(
        select(ym, measures.incentive_sum(), measures.gross_revenue(), func.count(),
               func.bool_or(R.slab_dependent))
        .where(*where, ym.isnot(None)).group_by(ym).order_by(ym)
    )).all()
    by_month = [
        MonthPoint(
            ym=r[0],
            label=f"{_MONTHS[int(r[0][5:7]) - 1]} {r[0][2:4]}",
            incentive=_f(r[1]), gross=_f(r[2]), rows=r[3],
            has_slab_dependent=bool(r[4]),
        )
        for r in month_rows
    ]

    air_rows = (await db.execute(
        select(R.airline_id, func.max(R.airline_name), measures.incentive_sum(),
               measures.iata_sum(), measures.gross_revenue(), func.count(),
               measures.needs_data_count())
        .where(*where).group_by(R.airline_id)
        .order_by(func.coalesce(measures.incentive_sum(), 0).desc()).limit(top)
    )).all()
    air_share = _pareto(air_rows, 2)
    by_airline = [
        AirlinePoint(
            airline_id=r[0],
            airline=r[1] or ("Unattributed carrier" if r[0] is None else f"#{r[0]}"),
            incentive=_f(r[2]), iata_commission=_f(r[3]), gross=_f(r[4]),
            rows=r[5], needs_data_rows=r[6],
            share_pct=air_share[i][0], cumulative_pct=air_share[i][1],
        )
        for i, r in enumerate(air_rows)
    ]

    # Suppliers exist only on the third-party sources. Restricting here rather than
    # filtering NULLs afterwards keeps BSP and LCC out of a ranking they cannot be in.
    sup_where = [*where, R.counterparty_kind == "supplier"]
    sup_rows = (await db.execute(
        select(R.supplier_id, func.max(R.supplier_name), func.max(R.supplier_code),
               func.max(R.supplier_branch), measures.incentive_sum(),
               measures.iata_sum(), measures.gross_revenue(), func.count(),
               measures.needs_data_count(), func.max(R.supplier_match_by))
        .where(*sup_where).group_by(R.supplier_id)
        .order_by(func.coalesce(measures.incentive_sum(), 0).desc()).limit(top)
    )).all()
    sup_share = _pareto(sup_rows, 4)
    by_supplier = [
        SupplierPoint(
            supplier_id=r[0],
            supplier=r[1] or ("Unattributed consolidator" if r[0] is None else f"#{r[0]}"),
            supplier_code=r[2], branch=r[3],
            incentive=_f(r[4]), iata_commission=_f(r[5]), gross=_f(r[6]),
            rows=r[7], needs_data_rows=r[8],
            share_pct=sup_share[i][0], cumulative_pct=sup_share[i][1],
            match_quality=r[9],
        )
        for i, r in enumerate(sup_rows)
    ]

    src_rows = (await db.execute(
        select(R.source, measures.incentive_sum(), func.count(),
               measures.needs_data_count())
        .where(*where).group_by(R.source).order_by(R.source)
    )).all()
    by_source = [
        SourcePoint(source=r[0], label=_SOURCE_LABELS.get(r[0], r[0]),
                    incentive=_f(r[1]), rows=r[2], needs_data_rows=r[3])
        for r in src_rows
    ]

    return IncomeSummaryResponse(
        scope=scope, basis=basis,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        totals=totals, by_month=by_month, by_airline=by_airline,
        by_supplier=by_supplier, by_source=by_source,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Filters
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/filters", response_model=FilterOptions)
async def get_filters(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="mine", pattern="^(mine|agency)$"),
):
    """Only what the board actually holds.

    Read off the projection, not off the airline and supplier masters: a picker offering
    2,340 suppliers of which four appear on the board is a worse picker.

    `priced` again, and separately, because these four queries do not go through
    `_filters`. Offering a carrier, a consolidator, a source or a month that exists only
    on unpriced rows is the same failure in a different shape: the user picks it and the
    board comes back empty, which reads as "nothing earned" rather than "nothing priced".
    """
    where = (*_scope(current_user, scope), R.priced.is_(True))

    airlines = [
        {"id": r[0], "name": r[1] or "Unattributed carrier"}
        for r in (await db.execute(
            select(R.airline_id, func.max(R.airline_name))
            .where(*where).group_by(R.airline_id)
            .order_by(func.max(R.airline_name).nulls_last())
        )).all()
    ]
    suppliers = [
        {"id": r[0], "name": r[1] or "Unattributed consolidator", "code": r[2]}
        for r in (await db.execute(
            select(R.supplier_id, func.max(R.supplier_name), func.max(R.supplier_code))
            .where(*where, R.counterparty_kind == "supplier").group_by(R.supplier_id)
            .order_by(func.max(R.supplier_name).nulls_last())
        )).all()
    ]
    sources = [r[0] for r in (await db.execute(
        select(distinct(R.source)).where(*where).order_by(R.source))).all()]
    months = [r[0] for r in (await db.execute(
        select(distinct(R.issue_ym)).where(*where, R.issue_ym.isnot(None))
        .order_by(R.issue_ym.desc()))).all()]

    return FilterOptions(
        airlines=airlines, suppliers=suppliers, sources=sources, months=months,
        can_view_agency=can_view_agency(current_user),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Freshness and rebuild
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/freshness", response_model=FreshnessResponse)
async def get_freshness(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="mine", pattern="^(mine|agency)$"),
):
    """Is the board current with the statements that have been LOADED, and priced?

    Rendered as a blocking banner, not a footnote. The table is filled by hooks — on
    every ingest path now, not only on the commission runs — and a write path nobody
    hooked leaves it quietly out of date. A wrong board is worse than no board.
    `never` is every batch on day one, because the migration ships the table empty on
    purpose.

    TWO REASONS A BATCH CAN BE BEHIND, and conflating them was the old version's blind
    spot: it asked `commission_runs` alone, so a statement uploaded and never priced
    was not merely unprojected, it was invisible to the check. `batch_changes` takes the
    later of the two timestamps instead — when the statement landed, and when it was
    last priced — so an uncosted upload counts as work the board owes.

    `scope=agency` matches the revenue board's default. Without it a Company Admin
    reading a board that sums the whole workspace would be told it was current on the
    strength of their own uploads alone.
    """
    tid = current_user.tenant_id
    uid = None if (scope == "agency" and can_view_agency(current_user)) else current_user.id
    out: list[SourceFreshness] = []
    stale_total = never_total = 0

    proj_where = [R.tenant_id == tid]
    if uid is not None:
        proj_where.append(R.created_by_id == uid)
    projected = {
        (r[0], r[1]): r[2]
        for r in (await db.execute(
            select(R.source, R.batch_id, func.max(R.projected_at))
            .where(*proj_where).group_by(R.source, R.batch_id)
        )).all()
    }

    for src in PROJECTED_SOURCES:
        # EVERY batch, not just the priced ones. An uploaded statement is sale the
        # moment it lands, so a board that has not projected it is behind even though
        # nothing has ever been run on it — which is exactly the state a workspace is in
        # on the day this ships.
        batches = await batch_changes(db, tenant_id=tid, user_id=uid, source=src)
        n_proj = n_stale = n_never = 0
        last = None
        for batch, _owner, changed in batches:
            at = projected.get((src, batch))
            if at is None:
                n_never += 1
                continue
            n_proj += 1
            last = at if last is None or at > last else last
            if changed is not None and changed > at:
                n_stale += 1
        stale_total += n_stale
        never_total += n_never
        out.append(SourceFreshness(
            source=src, batches=len(batches), projected=n_proj,
            stale=n_stale, never=n_never,
            last_projected_at=last.isoformat() if last else None,
        ))

    return FreshnessResponse(
        by_source=out, stale_total=stale_total, never_total=never_total,
        ok=(stale_total == 0 and never_total == 0),
    )


@router.post("/rebuild")
async def rebuild(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="mine", pattern="^(mine|agency)$"),
):
    """Re-project every batch — loaded or priced — in scope.

    Synchronous and idempotent. Each batch costs two set-based statements, so this is
    seconds of work rather than the kind of job that needs a queue; when it stops being
    so, the loop moves to workers/ unchanged, because project_batch is the whole of it.

    `scope=agency` rebuilds the whole workspace. It is the mode the revenue board needs:
    that board defaults to agency scope, so a rebuild that covered only the caller's own
    uploads would clear the staleness banner while leaving half the figures unprojected.
    Already gated — REBUILD_ROLES is Super Admin and Company Admin, who are the same two
    roles allowed to read agency-wide in the first place.
    """
    if not role_matches(current_user.role, *REBUILD_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a Super Admin or Company Admin can rebuild the income board.",
        )

    tid = current_user.tenant_id
    uid = None if scope == "agency" else current_user.id
    done: dict[str, int] = {}
    failed: list[str] = []

    # Every batch of every projectable source, and the owner comes from the batch rather
    # than from the caller. A tenant-wide rebuild re-projects a colleague's upload under
    # THEIR user id, because `created_by_id` is half the projection's unique key —
    # writing it under the admin's id would duplicate every row rather than restate it.
    batches: list[tuple[str, str, int]] = []
    for src in PROJECTED_SOURCES:
        for batch, owner, _changed in await batch_changes(
            db, tenant_id=tid, user_id=uid, source=src,
        ):
            batches.append((src, batch, owner))

    for src, batch, owner in batches:
        try:
            n = await project_batch(db, tenant_id=tid, user_id=owner,
                                    source=src, batch_id=batch)
            done[src] = done.get(src, 0) + n
        except Exception:
            # One malformed batch must not cost the caller the other forty.
            logger.exception("income_board: rebuild failed for %s/%s", src, batch)
            failed.append(f"{src}/{batch}")

    # Once, at the end, rather than per batch: it is a workspace-wide statement and the
    # answer only settles when both sides have finished projecting.
    try:
        await stamp_bsp_ndc_overlap(db, tenant_id=tid)
    except Exception:
        logger.exception("income_board: NDC/BSP overlap stamp failed for tenant %s", tid)

    await db.commit()

    return {"batches": len(batches), "rows_by_source": done, "failed": failed,
            "scope": scope}
