"""Sales vs Flown: of what we sold, how much has flown — and what that flown earns.

THE QUESTION. A ticket is SOLD on its issue date and FLOWN on its travel date, and a
flown-based incentive (PLB) is earned only on the second. Finance keeps this as a cohort
grid in Excel — sale month down the side, flown month across the top — and reads off it
how much of each month's sale has flown, what share of that is commissionable, and where
the flown total sits against the deal's slabs. This board is that grid, off the data.

SAME SALE AS TOTAL REVENUE, BY CONSTRUCTION. The scope, the filters, the currency pick
and the sale predicate are the revenue board's own (api/v1/revenue_board.py), not a copy:
`sold` here is `sale` there for the same window, so the two tabs cannot disagree.

WHAT "FLOWN" MEANS HERE. travel_date <= as_of (default today). It is inferred from the
travel date the statement printed, not from an airline's uplift file — a no-show or a
cancellation after the fact is not visible until the refund lands. The page says so.

THE EXCLUSION IS OBSERVED, NOT ASSUMED. The sheet types a flat 35%. Here it is the
commissionable share of flown gross on the lines that printed a fare breakdown — the
same deflator services/plb_accrual.py derives — and the page lets a user override it.
For a deal line it is taken on the deal's own basis (Basic / +YQ / +YR).
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.revenue_board import (
    _filters, _month_label, _pick_currency, _resolve_scope, _scope_conds, _share,
)
from app.database import get_db
from app.dependencies import get_current_user
from app.models.income_board import (
    REVENUE_TXN_CLASSES, TXN_REFUND, IncomeBoardRow as R,
)
from app.models.user import User
from app.schemas.sales_flown import (
    CohortCell, CohortRow, FlownAirlinePoint, FlownMonthPoint, FlownTotals,
    PlbDealLine, SalesFlownResponse, SlabBand,
)
from app.services import plb_accrual

router = APIRouter()

#: A line that is part of the sale — the same two conditions as measures.sale_gross.
SALE = and_(R.txn_class.in_(REVENUE_TXN_CLASSES), R.counts_in_net.is_(True))


def _f(v) -> float | None:
    return None if v is None else float(v)


def _z(v) -> float:
    return float(v or 0)


async def currency_split(
    db: AsyncSession, where, wanted: str | None,
) -> tuple[str | None, dict[str, int]]:
    """The currency to show (the caller's, else the busiest) and the rows it leaves out.

    Totals are never added across currencies; the board picks one and says what that
    left behind, the rule revenue_board._pick_currency states.
    """
    if not wanted:
        return await _pick_currency(db, where)
    cur = func.coalesce(R.currency, "INR")
    rows = (await db.execute(select(cur, func.count()).where(*where).group_by(cur))).all()
    return wanted, {c: n for c, n in rows if c != wanted}


def _segment_cond(segment: str | None):
    return (R.segment == segment,) if segment in ("D", "I") else ()


def _sum(*conds):
    return func.sum(R.gross_amount).filter(and_(SALE, *conds))


def _deflator(basic, yq, yr, gross_bd, want_yq=False, want_yr=False) -> float | None:
    """Commissionable share of gross, in %, over the lines that printed a breakdown."""
    g = _z(gross_bd)
    if not g:
        return None
    v = _z(basic) + (_z(yq) if want_yq else 0) + (_z(yr) if want_yr else 0)
    return round(v / g * 100, 2)


def _breakdown_cols(*conds):
    """Basic, YQ, YR and the gross they sit on, for flown lines with a fare printed."""
    has_bd = and_(SALE, R.fare_amount.isnot(None), *conds)
    return (
        func.sum(R.fare_amount).filter(has_bd),
        func.sum(R.yq).filter(has_bd),
        func.sum(R.yr).filter(has_bd),
        func.sum(R.gross_amount).filter(has_bd),
    )


@router.get("/summary", response_model=SalesFlownResponse)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="auto", pattern="^(auto|mine|agency)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    airline: list[int] | None = Query(default=None),
    segment: str | None = Query(default=None, pattern="^(D|I)$"),
    source: list[str] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    currency: str | None = Query(default=None),
    as_of: date | None = Query(default=None),
    top: int = Query(default=25, ge=3, le=100),
):
    """The cohort grid, the flown-by-month series, per-airline flown and the PLB panel.

    `date_from`/`date_to` window the SALE (issue date). The flown-by-month series and
    the PLB panel are windowed on TRAVEL date instead, because what flew in April is an
    April question whenever it was sold.
    """
    as_of = as_of or date.today()
    scope = _resolve_scope(current_user, scope)
    base = list(_scope_conds(current_user, scope))

    def conds(basis: str, cur: str | None):
        return base + _filters(
            basis=basis, date_from=date_from, date_to=date_to, airline=airline,
            supplier=None, source=source, category=category, currency=cur,
        ) + list(_segment_cond(segment))

    picked, others = await currency_split(db, conds("issue", None), currency)
    where = conds("issue", picked)

    flown_c = (R.travel_date <= as_of,)
    unflown_c = (R.travel_date > as_of,)
    undated_c = (R.travel_date.is_(None),)

    # ── the band ──────────────────────────────────────────────────────────────
    row = (await db.execute(
        select(
            _sum(), func.count().filter(R.counts_in_net.is_(True)),
            _sum(*flown_c), _sum(*unflown_c), _sum(*undated_c),
            func.count().filter(and_(SALE, *undated_c)),
            _sum(R.txn_class == TXN_REFUND),
            *_breakdown_cols(*flown_c),
        ).where(*where)
    )).one()
    flown_total = _z(row[2])
    totals = FlownTotals(
        sold=_f(row[0]), rows=row[1], flown=_f(row[2]), unflown=_f(row[3]),
        no_travel_date=_f(row[4]), no_travel_date_rows=row[5], refunds=_f(row[6]),
        deflator_pct=_deflator(row[7], row[8], row[9], row[10]),
        deflator_coverage_pct=_share(row[10], flown_total) if flown_total else None,
    )

    # ── the cohort grid ───────────────────────────────────────────────────────
    cell_rows = (await db.execute(
        select(R.issue_ym, R.travel_ym, _sum(), func.count().filter(SALE))
        .where(*where, R.issue_ym.isnot(None))
        .group_by(R.issue_ym, R.travel_ym)
    )).all()
    # Flown/unflown per sale month by DATE, not by month — a sale flying later this
    # month is not flown yet, and the grid's month columns cannot say that.
    split_rows = {
        r[0]: r for r in (await db.execute(
            select(R.issue_ym, _sum(), _sum(*flown_c), _sum(*unflown_c), _sum(*undated_c),
                   func.count().filter(SALE))
            .where(*where, R.issue_ym.isnot(None)).group_by(R.issue_ym)
        )).all()
    }
    cohorts: dict[str, CohortRow] = {}
    flown_months: set[str] = set()
    for sale_ym, flown_ym, amount, n in cell_rows:
        s = split_rows.get(sale_ym)
        c = cohorts.get(sale_ym)
        if c is None:
            c = cohorts[sale_ym] = CohortRow(
                sale_ym=sale_ym, label=_month_label(sale_ym),
                sold=_z(s[1]) if s else 0, flown=_z(s[2]) if s else 0,
                unflown=_z(s[3]) if s else 0, no_travel_date=_z(s[4]) if s else 0,
                rows=s[5] if s else 0, cells=[],
            )
        if flown_ym:
            flown_months.add(flown_ym)
        if amount is not None or n:
            c.cells.append(CohortCell(flown_ym=flown_ym, amount=round(_z(amount), 2), rows=n))

    # ── flown by travel month, whatever month it was sold in ──────────────────
    travel_where = conds("travel", picked)
    fm_rows = (await db.execute(
        select(R.travel_ym, _sum(), func.count().filter(SALE))
        .where(*travel_where, R.travel_ym.isnot(None))
        .group_by(R.travel_ym).order_by(R.travel_ym)
    )).all()
    as_of_ym = f"{as_of.year:04d}-{as_of.month:02d}"
    flown_by_month = [
        FlownMonthPoint(ym=r[0], label=_month_label(r[0]), flown=round(_z(r[1]), 2),
                        rows=r[2], future=r[0] > as_of_ym)
        for r in fm_rows
    ]

    # ── per airline ───────────────────────────────────────────────────────────
    air_rows = (await db.execute(
        select(R.airline_id, func.max(R.airline_name), _sum(), _sum(*flown_c),
               _sum(*unflown_c), _sum(*undated_c), *_breakdown_cols(*flown_c),
               func.count().filter(SALE))
        .where(*where).group_by(R.airline_id)
        .order_by(func.coalesce(_sum(), 0).desc()).limit(top)
    )).all()
    by_airline = [
        FlownAirlinePoint(
            airline_id=r[0],
            airline=r[1] or ("Not carrier-attributed" if r[0] is None else f"#{r[0]}"),
            sold=_f(r[2]), flown=_f(r[3]), unflown=_f(r[4]), no_travel_date=_f(r[5]),
            flown_pct=_share(r[3], r[2]),
            deflator_pct=_deflator(r[6], r[7], r[8], r[9]), rows=r[10],
        )
        for r in air_rows
    ]

    # ── PLB deal lines, when one carrier is in view ───────────────────────────
    plb_airline: str | None = None
    plb_lines: list[PlbDealLine] = []
    if airline and len(airline) == 1:
        name = (await db.execute(
            select(func.max(R.airline_name)).where(*base, R.airline_id == airline[0])
        )).scalar()
        plb_airline = name
        if name:
            plb_lines = await _plb_lines(
                db, current_user, base, airline[0], name, picked, source, category, as_of,
                date_from or date(as_of.year, 1, 1), date_to or as_of,
            )

    return SalesFlownResponse(
        scope=scope, currency=picked, as_of=as_of,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        totals=totals,
        cohorts=[cohorts[k] for k in sorted(cohorts)],
        flown_months=sorted(flown_months),
        flown_by_month=flown_by_month,
        by_airline=by_airline,
        plb_lines=plb_lines, plb_airline=plb_airline,
        other_currencies=others,
    )


def _deal_segment(flight_type: str | None) -> tuple[str, str | None]:
    ft = (flight_type or "").strip().lower()
    if ft.startswith("dom"):
        return "Domestic", "D"
    if ft.startswith("int"):
        return "International", "I"
    return "Both", None


async def _plb_lines(
    db: AsyncSession, user: User, base, airline_id: int, airline_name: str,
    currency: str | None, source, category, as_of: date,
    window_start: date, window_end: date,
) -> list[PlbDealLine]:
    """The selected carrier's PLB deal lines, each measured on flown in its own period.

    Rate resolution is plb_accrual.resolve_plb_rate verbatim — the same band this board
    reports is the band the accrual board accrues at. Achievement is commissionable
    flown over the incentive's period up to as_of, which is also that board's rule.

    Deals are matched to the carrier by NAME, because a deal stores `airline_name` and
    no id — plb_accrual keys its board the same way, through norm_key.
    """
    key = plb_accrual.norm_key(airline_name)
    lines = [
        ln for ln in await plb_accrual.load_deal_lines(
            db, user.tenant_id, user.id, window_start, window_end)
        if ln.airline_key == key
    ]
    out: list[PlbDealLine] = []
    for ln in lines:
        seg_label, seg_letter = _deal_segment(ln.cfg.flight_type)
        end = min(ln.period_end, as_of) if ln.period_end else as_of
        conds = list(base) + _filters(
            basis="travel", date_from=ln.period_start, date_to=end,
            airline=[airline_id], supplier=None, source=source, category=category,
            currency=currency,
        ) + list(_segment_cond(seg_letter))
        if ln.period_start is None:
            # An undated contract is not accrued against — plb_accrual says the same.
            flown, basic, yq, yr, gross_bd = 0, None, None, None, None
        else:
            r = (await db.execute(select(_sum(), *_breakdown_cols()).where(*conds))).one()
            flown, basic, yq, yr, gross_bd = _z(r[0]), r[1], r[2], r[3], r[4]
        defl = _deflator(basic, yq, yr, gross_bd, ln.want_yq, ln.want_yr)
        achieved = round(flown * defl / 100, 2) if defl is not None else None
        rate = plb_accrual.resolve_plb_rate(ln, achieved or 0.0, None)

        target_based = (ln.cfg.target_based or "Fixed").strip().title()
        bands: list[SlabBand] = []
        if target_based.lower() == "slab":
            seg, cls = plb_accrual._slab_keys(ln.cfg)
            want = f"{seg}{cls}"
            for s in sorted(ln.cfg.slabs or [], key=lambda s: float(s.base_target_amount or 0)):
                cell = next((float(v.value) for v in (s.values or [])
                             if v.value_key == want and v.value is not None), None)
                bands.append(SlabBand(threshold=float(s.base_target_amount or 0), rate_pct=cell))
        nxt = next((b for b in bands if (achieved or 0) < b.threshold), None)

        out.append(PlbDealLine(
            deal_id=ln.deal_id, deal_no=ln.deal_no, entity=ln.entity, channel=ln.channel,
            segment=seg_label, period_start=ln.period_start, period_end=ln.period_end,
            basis_label=ln.basis_label, target_based=target_based, bands=bands,
            flown=round(flown, 2), deflator_pct=defl, achieved=achieved,
            rate_pct=rate.pct, rate_explain=rate.explain,
            payout=round(achieved * rate.pct / 100, 2) if achieved is not None else None,
            next_band=nxt,
            gap_to_next=round(nxt.threshold - (achieved or 0), 2) if nxt else None,
            achieved_pct_of_next=(round((achieved or 0) / nxt.threshold * 100, 1)
                                  if nxt and nxt.threshold else None),
        ))
    return out
