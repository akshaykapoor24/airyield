"""The revenue board: what the loaded statements sold, and what that sale earned.

NOT /dashboard/income, AND THE DIFFERENCE IS THE POINT. That board answers "what have
the statements we have PRICED earned us" and filters `priced = TRUE`; this one answers
"what did we SELL", which includes every statement sitting in the workspace whether or
not anybody has run commission on it. They read the same table through two predicates
rather than two projections, so a carrier's gross cannot mean one thing here and another
there.

WHAT THIS MODULE REFUSES TO DO, on top of everything api/v1/income_board.py already
refuses. It does not add a line that restates another line — `counts_in_net` is on every
sale measure, enforced in services/income_board/measures.py so that no endpoint here can
quietly decide otherwise. It does not add across currencies. And it does not present
Third Party API's missing carrier as an unattributed one: an aggregator's hotel row has
no airline by nature, which is a different sentence from a resolution that failed.

EVERY FIGURE IS AGGREGATED IN SQL, and `/summary` issues its six GROUP BYs in one
request so the tiles and the charts cannot disagree. The incentive-by-type breakdown is
the one thing NOT in it: it is a LATERAL over a JSONB column, it is the most expensive
read on the board, and the card that shows it is not always open. It has its own
endpoint and the page fetches it when it needs it.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import (
    Numeric, Text, and_, cast, column, distinct, func, literal, select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.income_board import (
    DIRECTION_INBOUND, SALE_SOURCES, SOURCE_TP_API, IncomeBoardRow as R,
)
from app.models.user import User
from app.schemas.revenue_board import (
    AirlineDetailResponse, AirlineRevenuePoint, CategoryPoint, IncentiveTypePoint,
    LinkedStatementPoint, MonthPoint, NotCountedPoint, ProductPoint, RevenueFilterOptions,
    RevenueSummaryResponse, RevenueTotals, SourcePoint, SupplierPoint,
)
from app.services.income_board import measures
from app.services.report_download.registry import SOURCE_BY_KEY
from app.services.revenue_linked import linked_totals

logger = logging.getLogger(__name__)

router = APIRouter()

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: Which of the Statements hub's three families a source belongs to, and what to call
#: it. Both read off the report registry rather than retyped here, so this board, the
#: Commission income tab and the downloadable workbook all say one thing about one
#: upload — a hand-written copy had already drifted once.
SOURCE_CATEGORY = {key: SOURCE_BY_KEY[key].category for key in SALE_SOURCES}
SOURCE_LABEL = {key: SOURCE_BY_KEY[key].sheet_title for key in SALE_SOURCES}

#: The order the Statements hub shows them in, so the cards read the way the nav does.
CATEGORY_ORDER = ("BSP", "LCC", "Third Party")


def _f(v) -> float | None:
    """Decimal -> float, preserving NULL. NULL is a different claim from 0."""
    return None if v is None else float(v)


def _share(value, total) -> float:
    v, t = float(value or 0), float(total or 0)
    return round(v / t * 100, 2) if t else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Scope and filters
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_scope(user: User, scope: str) -> str:
    """`auto` -> the widest scope this user is allowed.

    The default differs from the income board's on purpose. "What did we sell" is a
    question about the business, not about one person's uploads, and with two people
    loading statements neither would otherwise ever see the whole picture. Everyone else
    still gets their own uploads, and the toggle is there either way.
    """
    from app.api.v1.income_board import can_view_agency
    if scope == "auto":
        return "agency" if can_view_agency(user) else "mine"
    if scope == "agency" and not can_view_agency(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a Super Admin or Company Admin can view agency-wide revenue.",
        )
    return scope


def _scope_conds(user: User, scope: str):
    if scope == "agency":
        return (R.tenant_id == user.tenant_id,)
    return (R.tenant_id == user.tenant_id, R.created_by_id == user.id)


def _filters(
    *, basis: str, date_from: date | None, date_to: date | None,
    airline: list[int] | None, supplier: list[int] | None,
    source: list[str] | None, category: list[str] | None, currency: str | None,
):
    """Everything the caller narrowed by.

    `SALE_SOURCES` is not a narrowing and is not optional. The table also holds the
    linked statements and the selling side; letting either into a sale total is the
    double-count this whole board is arranged to avoid, and it would not look wrong —
    just larger.
    """
    col = R.travel_date if basis == "travel" else R.issue_date
    wanted = list(SALE_SOURCES)
    if source:
        wanted = [s for s in wanted if s in set(source)]
    if category:
        cats = set(category)
        wanted = [s for s in wanted if SOURCE_CATEGORY.get(s) in cats]
    conds = [R.direction == DIRECTION_INBOUND, R.source.in_(wanted or ["__none__"])]
    if date_from:
        conds.append(col >= date_from)
    if date_to:
        conds.append(col <= date_to)
    if airline:
        conds.append(R.airline_id.in_(airline))
    if supplier:
        conds.append(R.supplier_id.in_(supplier))
    if currency:
        conds.append(func.coalesce(R.currency, "INR") == currency)
    return conds


def _ym(basis: str):
    return R.travel_ym if basis == "travel" else R.issue_ym


def _month_label(ym: str) -> str:
    return f"{_MONTHS[int(ym[5:7]) - 1]} {ym[2:4]}"


async def _pick_currency(db: AsyncSession, where) -> tuple[str | None, dict[str, int]]:
    """The currency with the most rows, and what that leaves out.

    Totals are per currency and are never converted or added across them — the rule
    services/report_download/summary.py already holds every report to. A board cannot
    honour it by ignoring it: it has to choose one and SAY what it chose, which is what
    the second return value is for.
    """
    cur = func.coalesce(R.currency, "INR")
    rows = (await db.execute(
        select(cur, func.count()).where(*where).group_by(cur).order_by(func.count().desc())
    )).all()
    if not rows:
        return None, {}
    return rows[0][0], {r[0]: r[1] for r in rows[1:]}


# ══════════════════════════════════════════════════════════════════════════════
# Summary — the whole board in one round trip
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/summary", response_model=RevenueSummaryResponse)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="auto", pattern="^(auto|mine|agency)$"),
    basis: str = Query(default="issue", pattern="^(issue|travel)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    airline: list[int] | None = Query(default=None),
    supplier: list[int] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    currency: str | None = Query(default=None),
    top: int = Query(default=15, ge=3, le=100),
):
    """The KPI band, the source split, the month series and the three rankings.

    One endpoint rather than six, for the reason the income board gives: the tiles and
    the charts must agree, and the cheapest way to guarantee that is to compute them
    from the same predicates in the same request.
    """
    scope = _resolve_scope(current_user, scope)
    base = list(_scope_conds(current_user, scope))
    picked = currency
    if picked is None:
        picked, others = await _pick_currency(
            db, base + _filters(basis=basis, date_from=date_from, date_to=date_to,
                                airline=airline, supplier=supplier, source=source,
                                category=category, currency=None))
    else:
        _c, others = await _pick_currency(
            db, base + _filters(basis=basis, date_from=date_from, date_to=date_to,
                                airline=airline, supplier=supplier, source=source,
                                category=category, currency=None))
        others = {k: v for k, v in {**others, _c: 0}.items() if k != picked and v}

    where = base + _filters(
        basis=basis, date_from=date_from, date_to=date_to, airline=airline,
        supplier=supplier, source=source, category=category, currency=picked)

    # ── the band ──────────────────────────────────────────────────────────────
    row = (await db.execute(
        select(
            measures.sale_gross(),
            measures.sale_rows(),
            measures.counted_incentive(),
            measures.counted_iata(),
            measures.unpriced_rows(),
            func.count().filter(and_(R.status == "needs_data", R.counts_in_net.is_(True))),
            func.count().filter(and_(R.status == "unmatched", R.counts_in_net.is_(True))),
            # A carrier that could not be resolved -- and NOT the aggregator rows, which
            # have no carrier by nature. Two different sentences, two counters.
            func.count().filter(and_(R.airline_id.is_(None), R.source != SOURCE_TP_API,
                                     R.counts_in_net.is_(True))),
            func.count().filter(and_(R.source == SOURCE_TP_API, R.counts_in_net.is_(True))),
            func.count().filter(and_(_ym(basis).is_(None), R.counts_in_net.is_(True))),
            func.count().filter(R.counts_in_net.is_(False)),
            measures.not_counted_gross(),
        ).where(*where)
    )).one()

    totals = RevenueTotals(
        sale=_f(row[0]), sale_rows=row[1], incentive=_f(row[2]), iata_commission=_f(row[3]),
        unpriced_rows=row[4], needs_data_rows=row[5], unmatched_rows=row[6],
        unattributed_airline_rows=row[7], not_carrier_attributed_rows=row[8],
        undated_rows=row[9], not_counted_rows=row[10], not_counted_sale=_f(row[11]),
    )

    # ── by source, and the categories folded out of it ────────────────────────
    src_rows = (await db.execute(
        select(R.source, measures.sale_gross(), func.count().filter(R.counts_in_net.is_(True)),
               measures.counted_incentive(),
               func.count().filter(and_(R.priced.is_(True), R.counts_in_net.is_(True))),
               measures.unpriced_rows(),
               func.count().filter(R.counts_in_net.is_(False)))
        .where(*where).group_by(R.source)
    )).all()
    by_source = [
        SourcePoint(
            source=r[0], category=SOURCE_CATEGORY.get(r[0], "Third Party"),
            label=SOURCE_LABEL.get(r[0], r[0]), sale=_f(r[1]), rows=r[2],
            incentive=_f(r[3]), priced_rows=r[4], unpriced_rows=r[5],
            not_counted_rows=r[6], share_pct=_share(r[1], totals.sale),
        )
        for r in src_rows
    ]
    by_source.sort(key=lambda p: (CATEGORY_ORDER.index(p.category)
                                  if p.category in CATEGORY_ORDER else 99, p.source))

    by_category: list[CategoryPoint] = []
    for cat in CATEGORY_ORDER:
        members = [p for p in by_source if p.category == cat]
        if not members:
            continue
        sale = sum(p.sale or 0 for p in members)
        inc = [p.incentive for p in members if p.incentive is not None]
        by_category.append(CategoryPoint(
            category=cat, sale=sale if members else None,
            rows=sum(p.rows for p in members),
            incentive=sum(inc) if inc else None,
            share_pct=_share(sale, totals.sale),
            sources=[p.source for p in members],
        ))

    # ── month x source, folded so the column can stack ────────────────────────
    ym = _ym(basis)
    month_rows = (await db.execute(
        select(ym, R.source, measures.sale_gross(), measures.counted_incentive(),
               func.count().filter(R.counts_in_net.is_(True)))
        .where(*where, ym.isnot(None)).group_by(ym, R.source).order_by(ym)
    )).all()
    months: dict[str, MonthPoint] = {}
    for key, src, sale, inc, rows in month_rows:
        pt = months.get(key)
        if pt is None:
            pt = months[key] = MonthPoint(ym=key, label=_month_label(key), sale=0,
                                          incentive=None, rows=0, by_source={})
        pt.sale = (pt.sale or 0) + float(sale or 0)
        if inc is not None:
            pt.incentive = (pt.incentive or 0) + float(inc)
        pt.rows += rows
        if sale is not None:
            pt.by_source[src] = round(float(sale), 2)
    by_month = [months[k] for k in sorted(months)]

    # ── airline x source, which is the question this board exists for ─────────
    air_rows = (await db.execute(
        select(R.airline_id, func.max(R.airline_name), R.source,
               measures.sale_gross(), measures.counted_incentive(),
               func.count().filter(R.counts_in_net.is_(True)))
        .where(*where).group_by(R.airline_id, R.source)
    )).all()
    airlines: dict[int | None, AirlineRevenuePoint] = {}
    for aid, name, src, sale, inc, rows in air_rows:
        pt = airlines.get(aid)
        if pt is None:
            pt = airlines[aid] = AirlineRevenuePoint(
                airline_id=aid,
                airline=name or ("Not carrier-attributed" if aid is None else f"#{aid}"),
                sale=0, incentive=None, rows=0, share_pct=0.0,
                by_source={}, by_incentive_type={},
            )
        pt.sale = (pt.sale or 0) + float(sale or 0)
        if inc is not None:
            pt.incentive = (pt.incentive or 0) + float(inc)
        pt.rows += rows
        if sale is not None:
            pt.by_source[src] = round(float(sale), 2)
    by_airline = sorted(airlines.values(), key=lambda p: -(p.sale or 0))[:top]
    for pt in by_airline:
        pt.share_pct = _share(pt.sale, totals.sale)

    # The incentive split per carrier — "how much PLB did Air India earn" is the
    # question the matrix's last columns exist for.
    #
    # NARROWED TO THE ROWS THE TABLE WILL ACTUALLY SHOW. This is a LATERAL over an
    # unindexed JSONB column, the most expensive read on the board; run across every
    # carrier it would dominate the request to fill in cells nobody sees. Bounded to the
    # top N, it reads a slice.
    shown_ids = [p.airline_id for p in by_airline if p.airline_id is not None]
    if shown_ids:
        kv = _breakdown_lateral()
        split = (await db.execute(
            select(R.airline_id, kv.c.key, func.sum(cast(kv.c.value, Numeric(18, 2))))
            .select_from(R).join(kv, literal(True))
            .where(*where, *_breakdown_guards(kv), R.airline_id.in_(shown_ids))
            .group_by(R.airline_id, kv.c.key)
        )).all()
        per_airline = {p.airline_id: p for p in by_airline}
        for aid, key, amount in split:
            pt = per_airline.get(aid)
            if pt is not None and amount is not None:
                pt.by_incentive_type[key] = round(float(amount), 2)

    # ── consolidators. Only the third-party sources have one. ─────────────────
    sup_rows = (await db.execute(
        select(R.supplier_id, func.max(R.supplier_name), func.max(R.supplier_code),
               func.max(R.supplier_branch), measures.sale_gross(),
               measures.counted_incentive(), func.count().filter(R.counts_in_net.is_(True)))
        .where(*where, R.counterparty_kind == "supplier").group_by(R.supplier_id)
        .order_by(func.coalesce(measures.sale_gross(), 0).desc()).limit(top)
    )).all()
    by_supplier = [
        SupplierPoint(
            supplier_id=r[0],
            supplier=r[1] or ("Unattributed consolidator" if r[0] is None else f"#{r[0]}"),
            supplier_code=r[2], branch=r[3], sale=_f(r[4]), incentive=_f(r[5]),
            rows=r[6], share_pct=_share(r[4], totals.sale),
        )
        for r in sup_rows
    ]

    # ── products. The aggregator source only. ─────────────────────────────────
    prod_rows = (await db.execute(
        select(R.product, measures.sale_gross(), func.count().filter(R.counts_in_net.is_(True)))
        .where(*where, R.source == SOURCE_TP_API).group_by(R.product)
        .order_by(func.coalesce(measures.sale_gross(), 0).desc())
    )).all()
    api_total = sum(float(r[1] or 0) for r in prod_rows)
    by_product = [
        ProductPoint(product=r[0], sale=_f(r[1]), rows=r[2],
                     share_pct=_share(r[1], api_total))
        for r in prod_rows
    ]

    # ── why the total is what it is ───────────────────────────────────────────
    # The single most-asked question about a de-duplicated figure is "why is this
    # smaller than my statement". Answering it with a number and a reason is the whole
    # justification for storing `counts_in_net_reason` rather than a bare boolean.
    nc_rows = (await db.execute(
        select(R.counts_in_net_reason, func.count(), func.sum(R.gross_amount),
               func.array_agg(distinct(R.source)))
        .where(*where, R.counts_in_net.is_(False))
        .group_by(R.counts_in_net_reason)
        .order_by(func.count().desc())
    )).all()
    not_counted = [
        NotCountedPoint(reason=r[0] or "No reason recorded", rows=r[1],
                        amount=_f(r[2]), sources=sorted(r[3] or []))
        for r in nc_rows
    ]

    return RevenueSummaryResponse(
        scope=scope, basis=basis, currency=picked,
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
        totals=totals, by_category=by_category, by_source=by_source,
        by_month=by_month, by_airline=by_airline, by_supplier=by_supplier,
        by_product=by_product, not_counted=not_counted, other_currencies=others,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Incentive by type — its own endpoint, fetched when the card is opened
# ══════════════════════════════════════════════════════════════════════════════

def _breakdown_lateral():
    """`incentive_breakdown` unrolled to (key, value) rows.

    A LATERAL over `jsonb_each_text` rather than eleven `->>'PLB'` columns, because
    `deal_incentives.incentive_type` is a String and the canonical eleven in
    api/v1/tickets.py are a convention rather than a constraint. A twelfth type added to
    a deal has to appear on this chart without a migration, and a fixed column list would
    drop it silently — which on an incentive breakdown means money that was earned and is
    nowhere on screen.

    NO `render_derived`, AND THAT IS THE WHOLE SUBTLETY. It emits a column definition
    list — `AS inc(key text, value text)` — which Postgres allows only for a function
    that does NOT declare its own OUT parameters. `jsonb_each_text` declares both, so it
    answers `a column definition list is redundant for a function with OUT parameters`
    and rejects the statement outright.

    It compiles perfectly either way, so a compile-only test cannot tell the two apart;
    this one was caught by running it. Naming the columns in `table_valued` is enough —
    the function supplies the types.
    """
    return func.jsonb_each_text(R.incentive_breakdown).table_valued(
        "key", "value",
    ).lateral("inc")


def _breakdown_guards(kv):
    """The predicates every read of the breakdown carries.

    Claimable rows only, counted rows only, and the value regex-guarded before casting —
    the engine writes floats, but a hand-edited row must not be able to take a chart
    down with a cast error.
    """
    return (
        R.incentive_breakdown.isnot(None),
        R.counts_in_net.is_(True),
        R.status.in_(("calculated", "reversed")),
        kv.c.value.op("~")(r"^-?[0-9]+(\.[0-9]+)?$"),
    )


def _incentive_type_select(where, extra=()):
    """SUM per incentive type, out of the breakdown JSONB."""
    kv = _breakdown_lateral()
    return (
        select(kv.c.key, func.sum(cast(kv.c.value, Numeric(18, 2))), func.count())
        .select_from(R).join(kv, literal(True))
        .where(*where, *_breakdown_guards(kv), *extra)
        .group_by(kv.c.key)
    )


@router.get("/by-incentive-type", response_model=list[IncentiveTypePoint])
async def by_incentive_type(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="auto", pattern="^(auto|mine|agency)$"),
    basis: str = Query(default="issue", pattern="^(issue|travel)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    airline: list[int] | None = Query(default=None),
    supplier: list[int] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    currency: str | None = Query(default=None),
):
    """PLB, Super PLB, Transaction Fee and the rest, for the current filter.

    Separate from `/summary` because it is the board's most expensive read — a LATERAL
    over an unindexed JSONB column across the whole scope — and the card it feeds is not
    always open.
    """
    scope = _resolve_scope(current_user, scope)
    where = list(_scope_conds(current_user, scope)) + _filters(
        basis=basis, date_from=date_from, date_to=date_to, airline=airline,
        supplier=supplier, source=source, category=category, currency=currency)
    rows = (await db.execute(_incentive_type_select(where))).all()
    total = sum(float(r[1] or 0) for r in rows)
    return [
        IncentiveTypePoint(incentive_type=r[0], amount=_f(r[1]), rows=r[2],
                           share_pct=_share(r[1], total))
        for r in sorted(rows, key=lambda r: -(float(r[1] or 0)))
    ]


# ══════════════════════════════════════════════════════════════════════════════
# One carrier, across every statement type
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/airline/{airline_id}", response_model=AirlineDetailResponse)
async def get_airline(
    airline_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="auto", pattern="^(auto|mine|agency)$"),
    basis: str = Query(default="issue", pattern="^(issue|travel)$"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    category: list[str] | None = Query(default=None),
    currency: str | None = Query(default=None),
):
    """The drill-down the board exists for: this carrier, everywhere it appears.

    The same aggregations as `/summary`, narrowed to one `airline_id` and with the
    incentive split included — that split is cheap here, because one carrier is a small
    slice of the board, which is exactly why it is a separate endpoint at board level.

    Grouped on the ID and never on the name. BSP's carrier name is free text, so a
    name-grouped drill-down would split one airline across several pages; the name that
    comes back is a label snapshot, taken with `max()` for that reason.
    """
    scope = _resolve_scope(current_user, scope)
    where = list(_scope_conds(current_user, scope)) + _filters(
        basis=basis, date_from=date_from, date_to=date_to, airline=[airline_id],
        supplier=None, source=source, category=category, currency=currency)

    row = (await db.execute(
        select(
            func.max(R.airline_name),
            measures.sale_gross(), measures.sale_rows(),
            measures.counted_incentive(), measures.counted_iata(),
            measures.unpriced_rows(),
            func.count().filter(and_(R.status == "needs_data", R.counts_in_net.is_(True))),
            func.count().filter(and_(R.status == "unmatched", R.counts_in_net.is_(True))),
            func.count().filter(and_(_ym(basis).is_(None), R.counts_in_net.is_(True))),
            func.count().filter(R.counts_in_net.is_(False)),
            measures.not_counted_gross(),
        ).where(*where)
    )).one()

    totals = RevenueTotals(
        sale=_f(row[1]), sale_rows=row[2], incentive=_f(row[3]), iata_commission=_f(row[4]),
        unpriced_rows=row[5], needs_data_rows=row[6], unmatched_rows=row[7],
        # A row reached through an airline id is attributed by construction.
        unattributed_airline_rows=0, not_carrier_attributed_rows=0,
        undated_rows=row[8], not_counted_rows=row[9], not_counted_sale=_f(row[10]),
    )

    src_rows = (await db.execute(
        select(R.source, measures.sale_gross(), func.count().filter(R.counts_in_net.is_(True)),
               measures.counted_incentive(),
               func.count().filter(and_(R.priced.is_(True), R.counts_in_net.is_(True))),
               measures.unpriced_rows(),
               func.count().filter(R.counts_in_net.is_(False)))
        .where(*where).group_by(R.source)
    )).all()
    by_source = sorted(
        (SourcePoint(
            source=r[0], category=SOURCE_CATEGORY.get(r[0], "Third Party"),
            label=SOURCE_LABEL.get(r[0], r[0]), sale=_f(r[1]), rows=r[2],
            incentive=_f(r[3]), priced_rows=r[4], unpriced_rows=r[5],
            not_counted_rows=r[6], share_pct=_share(r[1], totals.sale),
        ) for r in src_rows),
        key=lambda p: (CATEGORY_ORDER.index(p.category)
                       if p.category in CATEGORY_ORDER else 99, p.source),
    )

    ym = _ym(basis)
    month_rows = (await db.execute(
        select(ym, R.source, measures.sale_gross(), measures.counted_incentive(),
               func.count().filter(R.counts_in_net.is_(True)))
        .where(*where, ym.isnot(None)).group_by(ym, R.source).order_by(ym)
    )).all()
    months: dict[str, MonthPoint] = {}
    for key, src, sale, inc, rows in month_rows:
        pt = months.get(key)
        if pt is None:
            pt = months[key] = MonthPoint(ym=key, label=_month_label(key), sale=0,
                                          incentive=None, rows=0, by_source={})
        pt.sale = (pt.sale or 0) + float(sale or 0)
        if inc is not None:
            pt.incentive = (pt.incentive or 0) + float(inc)
        pt.rows += rows
        if sale is not None:
            pt.by_source[src] = round(float(sale), 2)

    inc_rows = (await db.execute(_incentive_type_select(where))).all()
    inc_total = sum(float(r[1] or 0) for r in inc_rows)
    by_incentive_type = [
        IncentiveTypePoint(incentive_type=r[0], amount=_f(r[1]), rows=r[2],
                           share_pct=_share(r[1], inc_total))
        for r in sorted(inc_rows, key=lambda r: -(float(r[1] or 0)))
    ]

    return AirlineDetailResponse(
        airline_id=airline_id,
        airline=row[0] or f"#{airline_id}",
        totals=totals, by_source=by_source,
        by_month=[months[k] for k in sorted(months)],
        by_incentive_type=by_incentive_type,
        linked=[LinkedStatementPoint(**r) for r in await linked_totals(
            db, tenant_id=current_user.tenant_id,
            user_id=None if scope == "agency" else current_user.id,
            airline_id=airline_id,
        )],
    )


# ══════════════════════════════════════════════════════════════════════════════
# The linked statements
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/linked", response_model=list[LinkedStatementPoint])
async def get_linked(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="auto", pattern="^(auto|mine|agency)$"),
    airline: int | None = Query(default=None),
):
    """TGQ HMPR, the memos and the four LCC ledgers — never added to sale.

    Read live off the statement tables rather than the projection: they are a side
    panel, not a dimension, and projecting rows that can never enter a total would be
    three more arm families for nothing. See services/revenue_linked.py.

    NOT FILTERED BY DATE, deliberately, and the panel says so. Each of these six types
    keeps its transaction date in a different column and two of them were built without
    a real sample (`registry.schema_unverified`), so a date filter here would silently
    drop rows for a reason that has nothing to do with the period a reader chose.
    """
    scope = _resolve_scope(current_user, scope)
    rows = await linked_totals(
        db, tenant_id=current_user.tenant_id,
        user_id=None if scope == "agency" else current_user.id,
        airline_id=airline,
    )
    return [LinkedStatementPoint(**r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# Filters
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/filters", response_model=RevenueFilterOptions)
async def get_filters(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    scope: str = Query(default="auto", pattern="^(auto|mine|agency)$"),
):
    """Only what the board actually holds.

    Read off the projection, not off the airline and supplier masters: a picker offering
    2,340 suppliers of which four appear on the board is a worse picker. The incentive
    types come from the breakdown for the same reason — offering "Cashback" to a
    workspace whose deals have never paid one is noise.
    """
    from app.api.v1.income_board import can_view_agency

    scope = _resolve_scope(current_user, scope)
    where = list(_scope_conds(current_user, scope)) + [
        R.direction == DIRECTION_INBOUND, R.source.in_(list(SALE_SOURCES)),
    ]

    airlines = [
        {"id": r[0],
         "name": r[1] or ("Not carrier-attributed" if r[0] is None else f"#{r[0]}")}
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
    currencies = [r[0] for r in (await db.execute(
        select(distinct(func.coalesce(R.currency, "INR"))).where(*where))).all()]
    inc_types = [r[0] for r in (await db.execute(_incentive_type_select(where))).all()]

    return RevenueFilterOptions(
        airlines=airlines, suppliers=suppliers, sources=sources,
        categories=[c for c in CATEGORY_ORDER
                    if any(SOURCE_CATEGORY.get(s) == c for s in sources)],
        months=months, currencies=sorted(currencies),
        incentive_types=sorted(inc_types),
        can_view_agency=can_view_agency(current_user),
        default_scope=scope,
    )
