"""Risk analysis: where the income the other boards report could fail to arrive.

Total Revenue says what we sold, Commission income what it earned, PLB Accrual what we
expect. This board asks what could go wrong with those figures, per airline:

  * Unflown       sold, not yet flown. A flown-based incentive is not earned on it yet,
                  and a cancellation or no-show still reverses it.
  * No travel     sale that cannot be placed as flown or unflown at all.
  * Refunds       sale already given back — a volume that will not count toward a slab.
  * Unmatched     sale no deal matched. It earns nothing unless a deal is added.
  * Needs data    a deal matched but pays on something the statement does not print, so
                  the income on it cannot be confirmed.
  * Not priced    sale commission has never been run on — income simply not counted yet.
  * ADM           debit memos raised against us, as a share of sale.

Every factor reads the SAME lines the Total Revenue board adds (its scope, filters and
sale predicate are imported, not copied). Unflown is a share of net sale, the rest are
shares of ISSUED sale — see `_measures` for why — and the thresholds that make a
factor medium or high are sent with the response and printed on the page. Concentration
— how much of the sale rests on one carrier — is agency-level and is reported apart.

Deliberately NOT re-derived here: PLB leakage (expired deals with flown revenue, rates
of 0, unattributed flown). services/plb_accrual.py is the authority for that and the
page links to its board filtered to those statuses.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.revenue_board import (
    _filters, _resolve_scope, _scope_conds, _share,
)
from app.api.v1.sales_flown import SALE, _segment_cond, currency_split
from app.database import get_db
from app.dependencies import get_current_user
from app.models.income_board import (
    MATCHED_STATUSES, TXN_CREDIT_MEMO, TXN_DEBIT_MEMO, TXN_REFUND, TXN_SALE,
    IncomeBoardRow as R,
)
from app.models.user import User
from app.schemas.risk_board import (
    AgingBucket, RiskAirlineRow, RiskFactorDef, RiskSummaryResponse, RiskTotals,
)

router = APIRouter()

#: The factors, in the order the page shows them. Thresholds are % (see `_factors`).
FACTORS: tuple[RiskFactorDef, ...] = (
    RiskFactorDef(key="unflown", label="Unflown", medium=25, high=50,
                  explain="Sold, not yet flown: no flown incentive earned on it yet, "
                          "and a cancellation still reverses it."),
    RiskFactorDef(key="undated", label="No travel date", medium=10, high=30,
                  explain="Sale whose statement printed no travel date, so it cannot be "
                          "told flown from unflown. Upload the TGQ HMPR for BSP rows."),
    RiskFactorDef(key="refund", label="Refunds", medium=5, high=10,
                  explain="Refunded, as a share of issued sale — volume that will not "
                          "count toward a slab."),
    RiskFactorDef(key="unmatched", label="No deal", medium=5, high=15,
                  explain="Sale no deal matched. It earns nothing until a deal covers it."),
    RiskFactorDef(key="needs_data", label="Unconfirmable", medium=5, high=15,
                  explain="A deal matched but pays on a figure the statement does not "
                          "print, so the income cannot be confirmed."),
    RiskFactorDef(key="unpriced", label="Not priced", medium=10, high=30,
                  explain="Commission has never been run on this sale."),
    RiskFactorDef(key="adm", label="ADM", medium=0.5, high=1,
                  explain="Debit memos raised by the airline, as a share of sale."),
)
FACTOR_BY_KEY = {f.key: f for f in FACTORS}

#: Share of sale on the single largest carrier.
CONCENTRATION = {"medium": 40.0, "high": 60.0}

AGING = (
    ("0_30", "Flies in 0–30 days", 0, 30),
    ("31_90", "31–90 days", 31, 90),
    ("91_180", "91–180 days", 91, 180),
    ("180_plus", "Over 180 days", 181, None),
)

LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def _f(v) -> float | None:
    return None if v is None else float(v)


def _z(v) -> float:
    return float(v or 0)


def _level(value: float, medium: float, high: float) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low"


def _measures(as_of: date):
    """The per-group sums, in a fixed order `_factors` reads back.

    The status factors are measured on ISSUED sale only (`txn_class = sale`) and divided
    by issued sale. Net sale is the wrong denominator: a refund usually carries a
    different status from the issue it reverses, so "unmatched issues / net sale" runs
    past 100% on any carrier with meaningful refunds.
    """
    counted = R.counts_in_net.is_(True)
    issued = and_(SALE, R.txn_class == TXN_SALE)
    return (
        func.sum(R.gross_amount).filter(SALE),                                   # 0 sold
        func.count().filter(counted),                                            # 1 rows
        func.sum(R.gross_amount).filter(and_(SALE, R.travel_date > as_of)),      # 2 unflown
        func.sum(R.gross_amount).filter(and_(SALE, R.txn_class == TXN_REFUND)),  # 3 refunds
        func.sum(R.gross_amount).filter(and_(issued, R.status == "unmatched")),  # 4
        func.sum(R.gross_amount).filter(and_(issued, R.status == "needs_data")), # 5
        func.sum(R.gross_amount).filter(and_(issued, R.priced.is_(False))),      # 6
        func.sum(R.incentive).filter(                                            # 7
            and_(counted, R.status.in_(MATCHED_STATUSES))),
        func.sum(R.incentive).filter(                                            # 8
            and_(counted, R.status.in_(MATCHED_STATUSES), R.slab_dependent.is_(True))),
        func.sum(func.abs(R.gross_amount)).filter(                               # 9 adm
            and_(counted, R.txn_class == TXN_DEBIT_MEMO)),
        func.count().filter(and_(counted, R.txn_class == TXN_DEBIT_MEMO)),       # 10
        func.sum(func.abs(R.gross_amount)).filter(                               # 11 acm
            and_(counted, R.txn_class == TXN_CREDIT_MEMO)),
        func.sum(R.variance_total).filter(and_(counted, R.variance_total > 0)),  # 12
        func.count().filter(and_(counted, R.declared_net_ok.is_(False))),        # 13
        func.sum(R.gross_amount).filter(issued),                                 # 14 issued
        func.sum(R.gross_amount).filter(and_(SALE, R.travel_date.is_(None))),   # 15 undated
    )


def _factors(r) -> dict[str, float]:
    sold, issued = _z(r[0]), _z(r[14])
    return {
        "unflown": _share(r[2], sold),
        "undated": _share(r[15], sold),
        "refund": _share(abs(_z(r[3])), issued),
        "unmatched": _share(r[4], issued),
        "needs_data": _share(r[5], issued),
        "unpriced": _share(r[6], issued),
        "adm": _share(r[9], issued),
    }


def _levels(factors: dict[str, float]) -> dict[str, str]:
    return {k: _level(v, FACTOR_BY_KEY[k].medium, FACTOR_BY_KEY[k].high)
            for k, v in factors.items()}


@router.get("/summary", response_model=RiskSummaryResponse)
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
    top: int = Query(default=30, ge=3, le=100),
):
    """Factors overall and per airline, the unflown aging, and concentration.

    Windowed on the SALE (issue date), like Total Revenue's default basis.
    """
    as_of = as_of or date.today()
    scope = _resolve_scope(current_user, scope)
    base = list(_scope_conds(current_user, scope))

    def conds(cur: str | None):
        return base + _filters(
            basis="issue", date_from=date_from, date_to=date_to, airline=airline,
            supplier=None, source=source, category=category, currency=cur,
        ) + list(_segment_cond(segment))

    picked, others = await currency_split(db, conds(None), currency)
    where = conds(picked)

    # ── overall ───────────────────────────────────────────────────────────────
    r = (await db.execute(select(*_measures(as_of)).where(*where))).one()
    overall_factors = _factors(r)

    # ── per airline ───────────────────────────────────────────────────────────
    air = (await db.execute(
        select(R.airline_id, func.max(R.airline_name), *_measures(as_of))
        .where(*where).group_by(R.airline_id)
    )).all()
    sold_total = _z(r[0])
    shares = sorted((_share(a[2], sold_total) for a in air if _z(a[2]) > 0), reverse=True)
    top_row = max(air, key=lambda a: _z(a[2]), default=None)

    rows: list[RiskAirlineRow] = []
    for a in air:
        m = a[2:]
        if not _z(m[0]) and not m[1]:
            continue
        f = _factors(m)
        lv = _levels(f)
        worst = max(lv.values(), key=LEVEL_RANK.__getitem__, default="low")
        rows.append(RiskAirlineRow(
            airline_id=a[0],
            airline=a[1] or ("Not carrier-attributed" if a[0] is None else f"#{a[0]}"),
            sold=_f(m[0]), share_pct=_share(m[0], sold_total), rows=m[1],
            factors=f, levels=lv, level=worst,
            score=sum(LEVEL_RANK[v] for v in lv.values()),
            unflown=_f(m[2]), incentive=_f(m[7]),
            slab_dependent_incentive=_f(m[8]), adm_exposure=_f(m[9]),
        ))
    rows.sort(key=lambda x: (-x.score, -(x.sold or 0)))
    level_counts = {k: sum(1 for x in rows if x.level == k) for k in LEVEL_RANK}

    top1 = shares[0] if shares else 0.0
    totals = RiskTotals(
        sold=_f(r[0]), issued=_f(r[14]), rows=r[1], unflown=_f(r[2]),
        no_travel_date=_f(r[15]), refunds=_f(r[3]),
        unmatched_sale=_f(r[4]), needs_data_sale=_f(r[5]), unpriced_sale=_f(r[6]),
        incentive=_f(r[7]), slab_dependent_incentive=_f(r[8]),
        adm_exposure=_f(r[9]), adm_count=r[10], acm_credit=_f(r[11]),
        under_recovery=_f(r[12]), declared_mismatch_rows=r[13],
        top_airline=(top_row[1] if top_row and top_row[1] else None),
        top_airline_share_pct=top1,
        top3_share_pct=round(sum(shares[:3]), 2),
        hhi=round(sum(s * s for s in shares), 0),
    )

    # ── unflown, by how far out it flies ──────────────────────────────────────
    days = R.travel_date - as_of
    bucket = case(
        *[((days <= hi) if lo == 0 else and_(days >= lo, days <= hi), key)
          for key, _l, lo, hi in AGING if hi is not None],
        else_="180_plus",
    )
    aging_rows = {
        k: (amt, n) for k, amt, n in (await db.execute(
            select(bucket, func.sum(R.gross_amount).filter(SALE), func.count().filter(SALE))
            .where(*where, R.travel_date > as_of).group_by(bucket)
        )).all()
    }
    aging = [
        AgingBucket(key=key, label=label, amount=round(_z(aging_rows.get(key, (0, 0))[0]), 2),
                    rows=aging_rows.get(key, (0, 0))[1])
        for key, label, _lo, _hi in AGING
    ]

    return RiskSummaryResponse(
        scope=scope, currency=picked, as_of=as_of,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        factors=list(FACTORS), totals=totals,
        overall_factors=overall_factors, overall_levels=_levels(overall_factors),
        concentration_level=_level(top1, CONCENTRATION["medium"], CONCENTRATION["high"]),
        unflown_aging=aging, by_airline=rows[:top], level_counts=level_counts,
        other_currencies=others,
    )
