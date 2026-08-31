"""PLB accrual board — supplier income accrued on flown revenue, before the airline pays.

WHAT THIS COMPUTES

    Final PLB = Σ(flown for months INSIDE the PLB period) × deflator% × PLB rate%

One board row is one DEAL LINE: (airline × channel × entity × LOB × PLB period).
`flown` is gross revenue per month, `deflator` is the fraction of that gross which
is actually commissionable under the deal's base definition (Basic / Basic+YQ /
Basic+YQ+YR), and the rate comes off the deal's PLB incentive.

The three "—" rules, in order of how much money they hide:

  * PLB period expired          → no accrual EVEN THOUGH flown exists. This is
                                  revenue leakage and is surfaced, not hidden.
  * rate resolves to 0          → no accrual
  * no flown inside the period  → no accrual

WHY A DEFLATOR EXISTS AT ALL

If we always had a fare breakdown we would sum the commissionable components
directly. We do not: "provisional flown" is frequently a gross figure the airline
quotes before any statement lands. The deflator is the ratio we OBSERVE on the
statements we do hold, applied to the gross we do not have a breakdown for. It is
derived per (airline × entity × channel × LOB × month) and can be locked to a
negotiated value — see models/plb_accrual.py.

HOW FLOWN IS ATTRIBUTED TO AN ENTITY — read this before changing it

No statement row carries the booking entity. BSP settles per AGENT CODE, and a
deal names the login ids / IATA codes it covers, so the chain that does exist is:

    bsp_statements.group_id → bsp_summary_statements.agent_code
                            → the deal line whose login_ids contains that code
                            → that deal's entity

That chain needs the summary PDF uploaded and login ids filled in. When it breaks,
we do NOT guess. The ladder is:

  1. agent code resolves to exactly one deal line for this airline+channel → that line
  2. only one deal line exists for this airline+channel → that line
  3. otherwise → the flown is unattributed. Every candidate line reports
     status NEEDS_SPLIT with the pooled figure shown for context, and the user
     keys the split with `manual_flown` — which is what they do in Excel today.

Fabricating a pro-rata split here would make the board look complete and be wrong.
"""
from __future__ import annotations

import calendar
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, Numeric, case, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.airline import Airline
from app.models.bsp_statement import BspStatement, BspStatementRow, BspTaxBreakup
from app.models.bsp_summary import BspSummaryStatement
from app.models.deal import (
    Deal,
    DealIncentiveConfig,
    DealIncentiveSlab,
    DealKind,
    DealDirection,
    DealLifecycleType,
    DealStatusType,
)
from app.models.lcc_detailed import LccDetailed
from app.models.login_id import LoginId
from app.models.plb_accrual import PlbAccrualInput, PlbAirlineSetting
from app.models.statement_row import ThirdPartyGds, ThirdPartyLcc

# The incentive this board is about. The deal tree carries 11 incentive types;
# only PLB accrues on flown revenue the way the sheet models it.
PLB_INCENTIVE = "PLB"

# Reuse the BSP engine's transaction policy verbatim rather than re-deciding it:
# an issue adds, a refund subtracts, and an ADM/ACM/void/exchange is not revenue.
from app.services.bsp_commission import _ISSUE_TXN, _REFUND_TXN  # noqa: E402

QUARTERS = {"JFM": 1, "AMJ": 4, "JAS": 7, "OND": 10}
QUARTER_OF_MONTH = {
    1: "JFM", 2: "JFM", 3: "JFM", 4: "AMJ", 5: "AMJ", 6: "AMJ",
    7: "JAS", 8: "JAS", 9: "JAS", 10: "OND", 11: "OND", 12: "OND",
}

# Board row statuses, worst first. `rank_status` relies on this order.
STATUS_ORDER = [
    "EXPIRED_WITH_FLOWN",   # flown revenue, no live deal — leakage
    "NO_DEAL",              # flown revenue for an airline with no PLB deal at all
    "NO_RATE",              # a live deal earning 0% on live volume
    "NEEDS_SPLIT",          # flown could not be attributed to one entity
    "EXPIRING",             # PLB period ends within EXPIRY_WINDOW_DAYS
    "UNCONFIRMED",          # flown month is later than the airline's confirmed month
    "OK",
]
EXPIRY_WINDOW_DAYS = 90


# ── Keys and small helpers ───────────────────────────────────────────────────

def norm_key(value: str | None) -> str:
    """The single place a display value becomes a stored grain key.

    Lowercased and whitespace-collapsed so 'Air  France' and 'AIR FRANCE' are one
    airline, and '' rather than NULL so the UNIQUE constraints on the input tables
    actually dedupe (Postgres treats NULLs as distinct).
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def _f(v) -> float:
    """DB NUMERIC arrives as Decimal; None means 0 for summing."""
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def ym_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_span(start: date, end: date) -> list[str]:
    """Every 'YYYY-MM' from start to end inclusive."""
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def ym_to_dates(ym: str) -> tuple[date, date]:
    y, m = int(ym[:4]), int(ym[5:7])
    return date(y, m, 1), _month_end(y, m)


@dataclass
class Period:
    key: str
    label: str
    start: date
    end: date

    @property
    def months(self) -> list[str]:
        return month_span(self.start, self.end)


def resolve_period(
    period: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    today: date | None = None,
) -> Period:
    """Turn what the UI sent into a concrete month window.

    Explicit from/to always wins. Otherwise a period key:
      'AMJ-26'   → Apr–Jun 2026   (the sheet's own convention)
      'JFM-26'   → Jan–Mar 2026
      '2026-04'  → that single month
      'FY26-27'  → Apr 2026 – Mar 2027
    Default is the financial quarter containing today.
    """
    if date_from and date_to:
        if date_to < date_from:
            date_from, date_to = date_to, date_from
        start = date(date_from.year, date_from.month, 1)
        end = _month_end(date_to.year, date_to.month)
        return Period(f"{ym_of(start)}..{ym_of(end)}", f"{start:%b %Y} – {end:%b %Y}", start, end)

    p = (period or "").strip().upper().replace(" ", "-")

    m = re.fullmatch(r"(JFM|AMJ|JAS|OND)-?(\d{2}|\d{4})", p)
    if m:
        q, yr = m.group(1), int(m.group(2))
        year = yr if yr > 100 else 2000 + yr
        sm = QUARTERS[q]
        start, end = date(year, sm, 1), _month_end(year, sm + 2)
        return Period(f"{q}-{year % 100:02d}", f"{q} {year % 100:02d}", start, end)

    m = re.fullmatch(r"FY-?(\d{2})-?(\d{2})", p)
    if m:
        y1 = 2000 + int(m.group(1))
        start, end = date(y1, 4, 1), _month_end(y1 + 1, 3)
        return Period(f"FY{m.group(1)}-{m.group(2)}", f"FY {m.group(1)}-{m.group(2)}", start, end)

    m = re.fullmatch(r"(\d{4})-(\d{2})", p)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        start, end = date(y, mo, 1), _month_end(y, mo)
        return Period(f"{y:04d}-{mo:02d}", f"{start:%b %Y}", start, end)

    t = today or date.today()
    q = QUARTER_OF_MONTH[t.month]
    sm = QUARTERS[q]
    year = t.year
    start, end = date(year, sm, 1), _month_end(year, sm + 2)
    return Period(f"{q}-{year % 100:02d}", f"{q} {year % 100:02d}", start, end)


def period_label(start: date | None, end: date | None) -> str:
    """'Jan 26- Dec 26' — the PLB Period column, formatted like the source sheet."""
    if not start and not end:
        return "—"
    if start and end:
        return f"{start:%b %y}- {end:%b %y}"
    return f"{start:%b %y}- …" if start else f"… -{end:%b %y}"


# ── Flown aggregation ────────────────────────────────────────────────────────

@dataclass
class FlownAgg:
    """Gross plus the fare components needed to derive a deflator.

    Kept separate rather than pre-combined because which components count depends
    on each deal's own base definition, and one airline's flown feeds several deal
    lines that may define their base differently.
    """
    gross: float = 0.0
    base: float = 0.0
    yq: float = 0.0
    yr: float = 0.0
    sources: set[str] = field(default_factory=set)

    def add(self, other: "FlownAgg") -> None:
        self.gross += other.gross
        self.base += other.base
        self.yq += other.yq
        self.yr += other.yr
        self.sources |= other.sources

    def commissionable(self, want_yq: bool, want_yr: bool) -> float:
        v = self.base
        if want_yq:
            v += self.yq
        if want_yr:
            v += self.yr
        return v


# (airline_key, channel_key, agent_key, ym) → FlownAgg
FlownIndex = dict[tuple[str, str, str, str], FlownAgg]


def _base_yq_yr_wanted(calc_cols: str | None) -> tuple[bool, bool]:
    """Decode 'Basic+YQ+YR' the same way deal_matching._calc_base does, so the
    board's base definition and the commission engine's can never disagree."""
    t = (calc_cols or "Basic").upper().replace(" ", "")
    return ("YQ" in t, "YR" in t)


async def _bsp_agent_codes(db: AsyncSession, tenant_id: int, user_id: int) -> dict[str, str]:
    """BSP batch_id → agent code, via the summary statement it is grouped with.

    The agent code is the only entity-bearing identifier in the BSP pipeline, and
    it lives on the SUMMARY document, not the detailed one. Statements whose
    summary was never uploaded simply do not appear here, and their flown falls to
    rung 2 or 3 of the attribution ladder.
    """
    rows = (await db.execute(
        select(BspStatement.batch_id, BspSummaryStatement.agent_code)
        .join(BspSummaryStatement, BspSummaryStatement.group_id == BspStatement.group_id)
        .where(
            BspStatement.tenant_id == tenant_id,
            BspStatement.created_by_id == user_id,
            BspStatement.group_id.is_not(None),
            BspSummaryStatement.agent_code.is_not(None),
        )
    )).all()
    return {batch: norm_key(code) for batch, code in rows if code}


async def flown_from_bsp(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    start: date,
    end: date,
    travel_basis: bool,
) -> FlownIndex:
    """Monthly flown from BSP settlement rows, aggregated IN SQL.

    `travel_basis` buckets on the TGQ-recovered travel date where one exists —
    BSP itself prints no travel date, so a row without a TGQ counterpart falls
    back to its issue date. The fallback is counted so the caller can tell the
    user how much of the month is really sales-dated.
    """
    R = BspStatementRow
    bucket_date = (
        func.coalesce(R.enriched_travel_date, R.issue_date) if travel_basis else R.issue_date
    )
    ym = func.to_char(bucket_date, "YYYY-MM")

    # Issues add, refunds subtract, everything else earns nothing. transaction_type
    # is stored upper-case by the parser but legacy rows are lower-case.
    txn = func.upper(func.coalesce(R.transaction_type, ""))
    sign = case((txn.in_(sorted(_REFUND_TXN)), -1.0), else_=1.0)
    counted = txn.in_(sorted(_ISSUE_TXN | _REFUND_TXN))

    # YQ / YR are rows in bsp_tax_breakups, never columns — one grouped subquery
    # keyed by row id, joined once, rather than a correlated scan per row.
    tax = (
        select(
            BspTaxBreakup.bsp_row_id.label("row_id"),
            func.coalesce(func.sum(case((func.upper(BspTaxBreakup.component_code) == "YQ", BspTaxBreakup.amount))), 0).label("yq"),
            func.coalesce(func.sum(case((func.upper(BspTaxBreakup.component_code) == "YR", BspTaxBreakup.amount))), 0).label("yr"),
        )
        .where(BspTaxBreakup.tenant_id == tenant_id)
        .group_by(BspTaxBreakup.bsp_row_id)
        .subquery()
    )

    agent_map = await _bsp_agent_codes(db, tenant_id, user_id)

    # Build each grouping expression ONCE and reuse the same object in SELECT and
    # GROUP BY. Re-writing it produces a second bind parameter for the same
    # literal, and Postgres then sees two different expressions and rejects the
    # grouping.
    airline_expr = func.lower(func.coalesce(Airline.name, R.airline_name, ""))

    rows = (await db.execute(
        select(
            airline_expr.label("airline"),
            R.statement_id.label("batch"),
            ym.label("ym"),
            func.coalesce(func.sum(sign * func.coalesce(R.transaction_amount, 0)), 0).label("gross"),
            func.coalesce(func.sum(sign * func.coalesce(R.fare_amount, 0)), 0).label("base"),
            func.coalesce(func.sum(sign * func.coalesce(tax.c.yq, 0)), 0).label("yq"),
            func.coalesce(func.sum(sign * func.coalesce(tax.c.yr, 0)), 0).label("yr"),
        )
        .select_from(R)
        .outerjoin(tax, tax.c.row_id == R.id)
        .outerjoin(Airline, Airline.iata_numeric_code == R.airline_accounting_code)
        .where(
            R.tenant_id == tenant_id,
            R.created_by_id == user_id,
            bucket_date.is_not(None),
            bucket_date >= start,
            bucket_date <= end,
            counted,
        )
        .group_by(airline_expr, R.statement_id, ym)
    )).all()

    out: FlownIndex = {}
    for airline, batch, ymv, gross, base, yq, yr in rows:
        if not airline:
            continue   # unresolvable carrier — never folded into a named airline
        key = (airline, "gds", agent_map.get(batch, ""), ymv)
        out.setdefault(key, FlownAgg()).add(
            FlownAgg(_f(gross), _f(base), _f(yq), _f(yr), {"bsp"})
        )
    return out


async def flown_from_third_party(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    start: date,
    end: date,
    travel_basis: bool,
) -> FlownIndex:
    """Third-party GDS + LCC statements. Columns live in the `data` JSONB by spec
    field name, so every value is cast on the way out. The carrier comes from the
    statement's own `airline_code`, resolved through the airline master; a row
    whose code does not resolve is left out rather than bucketed as 'unknown'."""
    out: FlownIndex = {}

    for model, channel, yq_field in ((ThirdPartyGds, "gds", "yq"), (ThirdPartyLcc, "lcc", None)):
        d = model.data
        date_field = "travel_date" if travel_basis else (
            "issue_date" if model is ThirdPartyGds else "transaction_date"
        )
        # to_date raises on anything that is not a date, and `data` is free-form
        # JSONB from someone else's spreadsheet. A CASE is the guard, not a WHERE:
        # Postgres only evaluates a CASE branch whose condition matched, whereas
        # WHERE clauses may be reordered and would let to_date see the bad value.
        raw_date = d[date_field].astext
        iso = raw_date.op("~")(r"^\d{4}-\d{2}-\d{2}")
        bucket = case(
            (iso, func.to_date(func.substr(raw_date, 1, 10), "YYYY-MM-DD")),
            else_=None,
        )

        def num(fieldname: str):
            txt = d[fieldname].astext
            return case(
                (txt.op("~")(r"^-?\d+(\.\d+)?$"), cast(txt, Numeric(16, 2))),
                else_=0,
            )

        code = func.upper(func.trim(d["airline_code"].astext))
        # One object per grouping expression, reused in SELECT and GROUP BY —
        # rebuilding it mints a second bind parameter for the same literal and
        # Postgres then refuses the grouping.
        airline_expr = func.lower(Airline.name)
        ym_expr = func.to_char(bucket, "YYYY-MM")
        rows = (await db.execute(
            select(
                airline_expr.label("airline"),
                ym_expr.label("ym"),
                func.coalesce(func.sum(num("total_fare")), 0).label("gross"),
                func.coalesce(func.sum(num("base_fare")), 0).label("base"),
                (func.coalesce(func.sum(num(yq_field)), 0) if yq_field
                 else cast(0, Numeric(16, 2))).label("yq"),
            )
            .select_from(model)
            .join(Airline, func.upper(Airline.iata_code) == code)
            .where(
                model.tenant_id == tenant_id,
                model.created_by_id == user_id,
                bucket.is_not(None),
                bucket >= start,
                bucket <= end,
            )
            .group_by(airline_expr, ym_expr)
        )).all()

        for airline, ymv, gross, base, yq in rows:
            if not airline:
                continue
            key = (airline, channel, "", ymv)
            out.setdefault(key, FlownAgg()).add(
                FlownAgg(_f(gross), _f(base), _f(yq), 0.0, {f"tp-{channel}"})
            )
    return out


async def flown_from_lcc_detailed(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    start: date,
    end: date,
    travel_basis: bool,
) -> FlownIndex:
    """LCC Detailed statements.

    This table has no airline column — the only carrier evidence is the flight
    number on the first segment ('6E 2134' → '6E'). We take the leading two
    alphanumerics and resolve them through the airline master; anything that does
    not resolve contributes nothing, because a mis-attributed carrier on this board
    moves money onto the wrong contract.

    Taxes are a JSONB array of {code, amount}, so YQ/YR come from a lateral sum.
    """
    L = LccDetailed
    txn_day = cast(L.transaction_date, Date)
    bucket = func.coalesce(L.departure_date, txn_day) if travel_basis else txn_day

    # Explicit -> / ->> rather than segments[0]["flight_no"]: the subscript form
    # SQLAlchemy emits for integer keys is PG14+ syntax, the operator form is not.
    flight_no = L.segments.op("->")(0).op("->>")("flight_no")
    code = func.upper(func.substring(func.regexp_replace(flight_no, r"[^A-Za-z0-9]", "", "g"), 1, 2))

    def tax_component(component: str, alias: str):
        """Correlated sum over the row's own taxes array — one scalar per row, so
        the JSONB expansion never reaches the outer GROUP BY. Each component needs
        its own alias or the two subqueries collide on the same derived name."""
        e = func.jsonb_array_elements(
            func.coalesce(L.taxes, text("'[]'::jsonb"))
        ).alias(alias)
        return (
            select(func.coalesce(func.sum(cast(e.column.op("->>")("amount"), Numeric(16, 2))), 0))
            .select_from(e)
            .where(func.upper(e.column.op("->>")("code")) == component)
            .scalar_subquery()
        )

    yq_expr = tax_component("YQ", "tx_yq")
    yr_expr = tax_component("YR", "tx_yr")

    # Same object in SELECT and GROUP BY — see the note in flown_from_bsp.
    airline_expr = func.lower(Airline.name)
    ym_expr = func.to_char(bucket, "YYYY-MM")

    rows = (await db.execute(
        select(
            airline_expr.label("airline"),
            ym_expr.label("ym"),
            func.coalesce(func.sum(func.coalesce(L.total, 0)), 0).label("gross"),
            func.coalesce(func.sum(func.coalesce(L.base_fare, 0)), 0).label("base"),
            func.coalesce(func.sum(yq_expr), 0).label("yq"),
            func.coalesce(func.sum(yr_expr), 0).label("yr"),
        )
        .select_from(L)
        .join(Airline, func.upper(Airline.iata_code) == code)
        .where(
            L.tenant_id == tenant_id,
            L.created_by_id == user_id,
            bucket.is_not(None),
            bucket >= start,
            bucket <= end,
        )
        .group_by(airline_expr, ym_expr)
    )).all()

    out: FlownIndex = {}
    for airline, ymv, gross, base, yq, yr in rows:
        if not airline:
            continue
        key = (airline, "lcc", "", ymv)
        out.setdefault(key, FlownAgg()).add(
            FlownAgg(_f(gross), _f(base), _f(yq), _f(yr), {"lcc"})
        )
    return out


# ── Deal lines ───────────────────────────────────────────────────────────────

@dataclass
class DealLine:
    """One row of the board, before any numbers are attached."""
    deal_id: int
    deal_no: str
    airline_name: str
    airline_key: str
    channel: str            # 'GDS' | 'LCC'
    channel_key: str
    entity: str | None
    entity_key: str
    lob: str | None
    lob_key: str
    period_start: date | None
    period_end: date | None
    basis_label: str        # 'Basic' | 'Basic+YQ' | 'Basic+YQ+YR'
    want_yq: bool
    want_yr: bool
    trigger_type: str | None
    frequency: str | None
    contract_year: str | None
    login_keys: set[str]
    cfg: DealIncentiveConfig
    deal: Deal

    @property
    def cell_key(self) -> tuple[str, str, str, str]:
        return (self.airline_key, self.entity_key, self.channel_key, self.lob_key)

    def covers(self, ym: str) -> bool:
        """Is this month inside the PLB period? An open-ended period covers
        everything on that side; a period with no dates at all covers nothing,
        because an undated contract cannot be accrued against."""
        if not self.period_start and not self.period_end:
            return False
        first, last = ym_to_dates(ym)
        if self.period_start and last < self.period_start:
            return False
        if self.period_end and first > self.period_end:
            return False
        return True


def _login_keys(deal: Deal) -> set[str]:
    """Normalised login ids / IATA codes a deal covers.

    `login_ids` is JSONB written by two different form paths, so it holds either
    bare strings or objects. `login_id` is the joined display fallback for rows
    written before the JSONB column existed.
    """
    out: set[str] = set()
    raw = deal.login_ids
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                out.add(norm_key(item))
            elif isinstance(item, dict):
                for k in ("login_id", "loginId", "iata", "code", "value"):
                    if item.get(k):
                        out.add(norm_key(str(item[k])))
                        break
    if not out and deal.login_id:
        out |= {norm_key(p) for p in str(deal.login_id).split(",") if p.strip()}
    return {k for k in out if k}


async def _lob_map(db: AsyncSession, tenant_id: int, user_id: int) -> dict[str, str]:
    """login id → LOB. LOB is not a deal column; it hangs off the login id master,
    and a deal reaches it through the login ids it names."""
    rows = (await db.execute(
        select(LoginId.login_id, LoginId.lob).where(
            LoginId.created_by_id == user_id,
            LoginId.lob.is_not(None),
        )
    )).all()
    return {norm_key(lid): lob for lid, lob in rows if lid and lob}


async def load_deal_lines(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    window_start: date,
    window_end: date,
    include_expired: bool = True,
) -> list[DealLine]:
    """Every approved, active airline deal carrying a PLB incentive.

    `include_expired` is on by default and that is the point: a deal whose period
    ended before the window is exactly the GULF AIR case — it must still appear,
    with its flown revenue and a zero accrual, or the leakage stays invisible.
    Expired lines are dropped only once they are more than a year stale.
    """
    stmt = (
        select(Deal)
        .options(
            selectinload(Deal.incentives)
            .selectinload(DealIncentiveConfig.slabs)
            .selectinload(DealIncentiveSlab.values)
        )
        .where(
            Deal.tenant_id == tenant_id,
            Deal.created_by_id == user_id,
            Deal.direction == DealDirection.INBOUND,
            Deal.deal_type == DealKind.AIRLINE,
            Deal.status == DealStatusType.APPROVED,
            Deal.deal_lifecycle_status == DealLifecycleType.ACTIVE,
        )
    )
    deals = (await db.execute(stmt)).scalars().unique().all()
    lobs = await _lob_map(db, tenant_id, user_id)

    stale_before = date(window_start.year - 1, window_start.month, 1)
    lines: list[DealLine] = []
    for deal in deals:
        cfg = next(
            (c for c in deal.incentives
             if (c.incentive_type or "").strip().upper() == PLB_INCENTIVE),
            None,
        )
        if cfg is None:
            continue

        start = cfg.contract_valid_from or deal.valid_from
        end = cfg.contract_valid_to or deal.valid_to
        if end and end < stale_before:
            continue
        if start and start > window_end:
            continue

        keys = _login_keys(deal)
        found = {lobs[k] for k in keys if k in lobs}
        lob = next(iter(found)) if len(found) == 1 else None

        calc_cols = cfg.payout_calc_cols or cfg.target_calc_cols
        want_yq, want_yr = _base_yq_yr_wanted(calc_cols)
        basis = "Basic" + ("+YQ" if want_yq else "") + ("+YR" if want_yr else "")
        channel = (deal.airline_type or "GDS").strip().upper()

        lines.append(DealLine(
            deal_id=deal.id,
            deal_no=f"AIR-{deal.id:06d}",
            airline_name=deal.airline_name or "—",
            airline_key=norm_key(deal.airline_name),
            channel=channel,
            channel_key=norm_key(channel),
            entity=deal.entity,
            entity_key=norm_key(deal.entity),
            lob=lob,
            lob_key=norm_key(lob),
            period_start=start,
            period_end=end,
            basis_label=basis,
            want_yq=want_yq,
            want_yr=want_yr,
            trigger_type=deal.trigger_type,
            frequency=cfg.frequency,
            contract_year=deal.contract_year,
            login_keys=keys,
            cfg=cfg,
            deal=deal,
        ))
    return lines


# ── PLB rate resolution ──────────────────────────────────────────────────────

def _slab_keys(cfg: DealIncentiveConfig) -> tuple[str, str]:
    """Which cell of a slab band this line reads.

    Slab values are keyed 'domEconomy' / 'intlBusiness' (see
    deal_matching._pick_amount_slab_cell). The board has no single ticket to take
    a segment or cabin from, so it uses what the incentive itself is written for —
    a Business-only incentive quotes its Business rate, not an Economy one.
    """
    ft = (cfg.flight_type or "").strip().lower()
    seg = "intl" if ft.startswith("int") else "dom"
    cls = (cfg.class_ or "").strip().lower()
    if cls in ("business", "first"):
        return seg, "Business"
    if "premium" in cls:
        return seg, "Premium"
    return seg, "Economy"


@dataclass
class RateResult:
    pct: float
    source: str          # 'locked' | 'fixed' | 'slab' | 'none'
    explain: str


def resolve_plb_rate(
    line: DealLine,
    achieved_base: float,
    locked_pct: float | None,
) -> RateResult:
    """The PLB rate for this line, as a percentage of the commissionable base.

    A locked override always wins. Otherwise a Fixed incentive quotes its rate
    directly, and a Slab incentive resolves the band the achieved base has reached
    and reads that band's segment × class cell.

    A rate of 0 is a real answer, not an error: the sheet has live ITA-CONT and
    UNITED/TSI lines earning 0%, and the board says NO_RATE rather than hiding
    them. `explain` is what the row drawer shows.
    """
    if locked_pct is not None:
        return RateResult(float(locked_pct), "locked", f"Locked override {locked_pct}%")

    cfg = line.cfg
    target_based = (cfg.target_based or "Fixed").strip().lower()

    if target_based != "slab":
        if cfg.incentive_amt_pct is None:
            return RateResult(0.0, "none", "Fixed incentive with no rate set")
        num_pct = (cfg.incentive_num_pct or "Percentage").strip().lower()
        if "percent" not in num_pct:
            # A flat-amount incentive pays per ticket, not per rupee flown — it
            # cannot be expressed as flown × rate, so the board declines rather
            # than inventing a percentage.
            return RateResult(
                0.0, "none",
                f"Flat amount ₹{_f(cfg.incentive_amt_pct):,.2f} per ticket — not a rate on flown revenue",
            )
        return RateResult(_f(cfg.incentive_amt_pct), "fixed", f"Fixed {_f(cfg.incentive_amt_pct)}%")

    if not cfg.slabs:
        return RateResult(0.0, "none", "Slab-based incentive with no slab rows configured")

    seg, cls = _slab_keys(cfg)
    want = f"{seg}{cls}"
    bands = sorted(cfg.slabs, key=lambda s: _f(s.base_target_amount), reverse=True)
    chosen = next((s for s in bands if achieved_base >= _f(s.base_target_amount)), None)
    if chosen is None:
        lowest = min((_f(s.base_target_amount) for s in bands), default=0.0)
        return RateResult(
            0.0, "none",
            f"Achieved ₹{achieved_base:,.0f} is below the first band (₹{lowest:,.0f}) — target not met",
        )

    cell = next(
        (_f(v.value) for v in (chosen.values or [])
         if v.value_key == want and v.value is not None),
        None,
    )
    if cell is None:
        return RateResult(
            0.0, "none",
            f"Band ≥₹{_f(chosen.base_target_amount):,.0f} reached, but no rate set for {want}",
        )
    return RateResult(
        cell, "slab",
        f"Achieved ₹{achieved_base:,.0f} → band ≥₹{_f(chosen.base_target_amount):,.0f} → {want} {cell}%",
    )


# ── Stored inputs ────────────────────────────────────────────────────────────

async def load_inputs(
    db: AsyncSession, tenant_id: int, user_id: int, months: list[str],
) -> dict[tuple[str, str, str, str, str], PlbAccrualInput]:
    """Every override touching this window, keyed by (grain..., ym)."""
    if not months:
        return {}
    rows = (await db.execute(
        select(PlbAccrualInput).where(
            PlbAccrualInput.tenant_id == tenant_id,
            PlbAccrualInput.created_by_id == user_id,
            PlbAccrualInput.ym.in_(months),
        )
    )).scalars().all()
    return {
        (r.airline_key, r.entity_key, r.channel_key, r.lob_key, r.ym): r
        for r in rows
    }


async def load_settings(
    db: AsyncSession, tenant_id: int, user_id: int,
) -> dict[tuple[str, str, str], PlbAirlineSetting]:
    rows = (await db.execute(
        select(PlbAirlineSetting).where(
            PlbAirlineSetting.tenant_id == tenant_id,
            PlbAirlineSetting.created_by_id == user_id,
        )
    )).scalars().all()
    return {(r.airline_key, r.entity_key, r.channel_key): r for r in rows}


# ── Board assembly ───────────────────────────────────────────────────────────

@dataclass
class MonthCell:
    ym: str
    flown: float
    source: str        # 'derived' | 'manual' | 'pooled' | 'none'
    in_period: bool
    confirmed: bool
    deflator_pct: float
    commissionable: float
    pool: float = 0.0  # what the unattributed pool holds, when source == 'pooled'


@dataclass
class BoardRow:
    key: str
    deal_id: int | None
    deal_no: str | None
    airline_name: str
    channel: str
    entity: str | None
    lob: str | None
    plb_period_from: date | None
    plb_period_to: date | None
    plb_period_label: str
    flown_confirmed_through: date | None
    basis_label: str
    deflator_pct: float
    deflator_source: str
    plb_rate_pct: float
    plb_rate_source: str
    plb_rate_explain: str
    months: dict[str, MonthCell]
    flown_total: float
    flown_in_period: float
    commissionable_base: float
    accrual: float
    # The slice of `accrual` that falls on months the PLB period does not cover —
    # what to reverse if the contract has genuinely lapsed rather than rolled over.
    accrual_at_risk: float
    status: str
    status_flags: list[str]
    reasons: list[str]


def _effective_deflator(cells: list[MonthCell]) -> float:
    """Sum of commissionable over sum of flown, as a percentage.

    Showing one deflator for a row whose months differ would otherwise be a lie.
    This is the ratio that actually produced the accrual, and it collapses to the
    single figure the spreadsheet quotes whenever the months agree.
    """
    gross = sum(c.flown for c in cells)
    if abs(gross) < 0.005:
        return 0.0
    return round(sum(c.commissionable for c in cells) / gross * 100, 4)


def _derive_deflator(agg: FlownAgg | None, want_yq: bool, want_yr: bool) -> float | None:
    """The observed commissionable share of gross, as a percentage.

    None when there is nothing to observe. A gross of zero with non-zero
    components (a month that netted out to nil after refunds) is not a ratio
    either, so it is None rather than a division blow-up.
    """
    if agg is None or abs(agg.gross) < 0.005:
        return None
    return round(agg.commissionable(want_yq, want_yr) / agg.gross * 100, 4)


async def _travel_date_coverage(
    db: AsyncSession, tenant_id: int, user_id: int, start: date, end: date,
) -> float | None:
    """Share of BSP rows in the window that carry a real travel date.

    BSP prints no travel date; only a TGQ HMPR counterpart recovers one. On a
    flown-basis board the rest are bucketed by issue date, and the user is owed
    that number rather than a silent approximation. None when there are no rows.
    """
    R = BspStatementRow
    total, enriched = (await db.execute(
        select(func.count(), func.count(R.enriched_travel_date)).where(
            R.tenant_id == tenant_id,
            R.created_by_id == user_id,
            R.issue_date.is_not(None),
            R.issue_date >= start,
            R.issue_date <= end,
        )
    )).one()
    if not total:
        return None
    return round(enriched / total * 100, 1)


async def build_board(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    period: Period,
    basis: str = "auto",
) -> dict:
    """The whole accrual grid for one period.

    `basis` is 'auto' (a flown-triggered deal buckets on travel date, a
    sales-triggered one on issue date), or 'travel' / 'issue' to force one. One
    board can hold both kinds of deal, so 'auto' runs the aggregation twice and
    each line reads the index its own trigger_type calls for.
    """
    months = period.months
    lines = await load_deal_lines(db, tenant_id, user_id, period.start, period.end)

    # Slab bands are judged on achievement across the whole incentive period, which
    # usually starts before the window. Reach back far enough to cover it, but cap
    # at two years so a decade-old contract cannot turn this into a full scan.
    earliest = min(
        [l.period_start for l in lines if l.period_start] + [period.start],
        default=period.start,
    )
    floor = date(period.start.year - 2, period.start.month, 1)
    wide_start = max(earliest, floor)
    wide_months = month_span(wide_start, period.end)

    travel_flags = {True, False} if basis == "auto" else {basis == "travel"}
    indexes: dict[bool, FlownIndex] = {}
    for travel in travel_flags:
        idx: FlownIndex = {}
        for fn in (flown_from_bsp, flown_from_third_party, flown_from_lcc_detailed):
            part = await fn(db, tenant_id, user_id, wide_start, period.end, travel)
            for k, v in part.items():
                idx.setdefault(k, FlownAgg()).add(v)
        indexes[travel] = idx

    def travel_for(line: DealLine) -> bool:
        if basis == "travel":
            return True
        if basis == "issue":
            return False
        return (line.trigger_type or "").strip().lower() == "flown"

    inputs = await load_inputs(db, tenant_id, user_id, wide_months)
    settings = await load_settings(db, tenant_id, user_id)

    # ── Attribution — the ladder documented at the top of this module ────────
    by_airline: dict[str, list[DealLine]] = defaultdict(list)
    for l in lines:
        by_airline[l.airline_key].append(l)

    attributed: dict[bool, dict[tuple[int, str], FlownAgg]] = {k: {} for k in indexes}
    pooled: dict[bool, dict[tuple[str, str, str], FlownAgg]] = {k: {} for k in indexes}
    orphan: dict[tuple[str, str], dict[str, FlownAgg]] = defaultdict(dict)
    pooled_lines: dict[tuple[str, str], set[int]] = defaultdict(set)

    for travel, idx in indexes.items():
        for (airline_key, channel_key, agent_key, ym), agg in idx.items():
            candidates = [l for l in by_airline.get(airline_key, []) if l.channel_key == channel_key]
            if not candidates:
                # A carrier can settle through a channel its deal was not filed
                # under (an LCC airline appearing in BSP). Airline identity wins.
                candidates = by_airline.get(airline_key, [])
            if not candidates:
                orphan[(airline_key, channel_key)].setdefault(ym, FlownAgg()).add(agg)
                continue

            if agent_key:
                narrowed = [l for l in candidates if agent_key in l.login_keys]
                if narrowed:
                    candidates = narrowed

            live = [l for l in candidates if l.covers(ym)] or candidates
            if len(live) == 1:
                attributed[travel].setdefault((live[0].deal_id, ym), FlownAgg()).add(agg)
            else:
                pooled[travel].setdefault((airline_key, channel_key, ym), FlownAgg()).add(agg)
                pooled_lines[(airline_key, channel_key)] |= {l.deal_id for l in live}

    # ── One row per deal line ────────────────────────────────────────────────
    today = date.today()
    rows: list[BoardRow] = []

    for line in lines:
        travel = travel_for(line)
        idx_attr = attributed[travel]
        idx_pool = pooled[travel]
        setting = settings.get((line.airline_key, line.entity_key, line.channel_key))
        confirmed_through = setting.flown_confirmed_through if setting else None
        split_needed = line.deal_id in pooled_lines.get((line.airline_key, line.channel_key), set())

        def cell_for(ym: str) -> MonthCell:
            gk = (line.airline_key, line.entity_key, line.channel_key, line.lob_key, ym)
            override = inputs.get(gk)
            agg = idx_attr.get((line.deal_id, ym))
            pool = idx_pool.get((line.airline_key, line.channel_key, ym))

            locked_def = (
                _f(override.deflator_pct)
                if override is not None and override.deflator_pct is not None else None
            )
            derived_def = _derive_deflator(agg, line.want_yq, line.want_yr)

            if override is not None and override.manual_flown is not None:
                flown, source = _f(override.manual_flown), "manual"
            elif agg is not None:
                flown, source = agg.gross, "derived"
            elif pool is not None and split_needed:
                flown, source = 0.0, "pooled"
            else:
                flown, source = 0.0, "none"

            if locked_def is not None:
                deflator = locked_def
            elif derived_def is not None:
                deflator = derived_def
            elif setting is not None and setting.default_deflator_pct is not None:
                deflator = _f(setting.default_deflator_pct)
            else:
                deflator = None   # filled from the row's own history below

            first, _last = ym_to_dates(ym)
            return MonthCell(
                ym=ym,
                flown=round(flown, 2),
                source=source,
                in_period=line.covers(ym),
                confirmed=bool(confirmed_through and first <= confirmed_through),
                deflator_pct=deflator if deflator is not None else -1.0,
                commissionable=0.0,
                pool=round(pool.gross, 2) if pool is not None else 0.0,
            )

        wide_cells = {ym: cell_for(ym) for ym in wide_months}

        # A month with no observable ratio of its own borrows the row's own most
        # recent observed one: a deflator is a property of the fare mix, which
        # moves slowly, not of one month's settlements.
        observed = [c.deflator_pct for c in wide_cells.values() if c.deflator_pct >= 0]
        fallback = observed[-1] if observed else 100.0
        for c in wide_cells.values():
            if c.deflator_pct < 0:
                c.deflator_pct = fallback
            c.commissionable = round(c.flown * c.deflator_pct / 100, 2)

        # Slab achievement is measured over the incentive's own period, up to the
        # end of the window being viewed — not over the window alone.
        achieved = sum(
            c.commissionable for ym, c in wide_cells.items()
            if c.in_period and ym <= months[-1]
        )
        locked_rate = None
        for ym in months:
            ov = inputs.get((line.airline_key, line.entity_key, line.channel_key, line.lob_key, ym))
            if ov is not None and ov.plb_rate_pct is not None:
                locked_rate = _f(ov.plb_rate_pct)
                break
        rate = resolve_plb_rate(line, achieved, locked_rate)

        window_cells = [wide_cells[ym] for ym in months]
        in_period = [c for c in window_cells if c.in_period]
        flown_total = round(sum(c.flown for c in window_cells), 2)
        flown_in_period = round(sum(c.flown for c in in_period), 2)

        # ACCRUAL POLICY — the accrual is taken on ALL flown in the window, not
        # only on the months the PLB period covers.
        #
        # This matches the source workbook, and the reason is not sloppiness: a
        # PLB period on a row is very often stale because the contract rolled over
        # on the same terms and nobody edited the date. Zeroing the row would
        # silently delete real income from the accrual, and a silent zero is far
        # harder to notice than a flagged number.
        #
        # So the row keeps its figure AND carries EXPIRED_WITH_FLOWN, and the part
        # resting on an uncovered month is reported separately as
        # `accrual_at_risk` — the amount to reverse if the contract really has
        # lapsed. Both numbers roll up, so finance can be conservative on purpose
        # rather than by accident.
        base_total = round(sum(c.commissionable for c in window_cells), 2)
        base_in_period = round(sum(c.commissionable for c in in_period), 2)
        accrual = round(base_total * rate.pct / 100, 2)
        accrual_at_risk = round((base_total - base_in_period) * rate.pct / 100, 2)

        deflator_locked = any(
            (inputs.get((line.airline_key, line.entity_key, line.channel_key, line.lob_key, ym)) is not None
             and inputs[(line.airline_key, line.entity_key, line.channel_key, line.lob_key, ym)].deflator_pct is not None)
            for ym in months
        )

        flags: list[str] = []
        reasons: list[str] = []
        outside = round(flown_total - flown_in_period, 2)
        if abs(outside) >= 1:
            flags.append("EXPIRED_WITH_FLOWN")
            head = (
                f"Rs {abs(outside):,.0f} flown outside the PLB period "
                f"({period_label(line.period_start, line.period_end)})."
            )
            # Only quote an at-risk figure when there is one. A 0% deal accrues
            # nothing to begin with, so "Rs 0 is at risk" would read as reassurance
            # when the real problem is that nothing is being claimed at all.
            reasons.append(
                f"{head} Rs {abs(accrual_at_risk):,.0f} of this accrual rests on a contract "
                f"that does not cover those months - renew it, or reverse that amount."
                if abs(accrual_at_risk) >= 1
                else f"{head} Nothing accrues on it. Renew the contract to claim it."
            )
        if rate.pct == 0 and abs(flown_total) >= 1:
            flags.append("NO_RATE")
            reasons.append(rate.explain)
        if line.period_end:
            days = (line.period_end - max(period.end, today)).days
            if 0 <= days <= EXPIRY_WINDOW_DAYS or period.start <= line.period_end <= period.end:
                flags.append("EXPIRING")
                reasons.append(f"PLB period ends {line.period_end:%d %b %Y} - renegotiate.")
        if any(c.source == "pooled" for c in window_cells):
            flags.append("NEEDS_SPLIT")
            reasons.append(
                "Flown revenue for this airline could not be attributed to one entity. "
                "Key the split, or upload the BSP summary so the agent code resolves."
            )
        unconfirmed = [c.ym for c in window_cells if abs(c.flown) >= 1 and not c.confirmed]
        if unconfirmed and confirmed_through:
            flags.append("UNCONFIRMED")
            reasons.append(
                f"Flown for {', '.join(unconfirmed)} is later than the airline's confirmed month "
                f"({confirmed_through:%b %y}) - provisional."
            )
        if not flags:
            flags.append("OK")

        rows.append(BoardRow(
            key=f"deal-{line.deal_id}",
            deal_id=line.deal_id,
            deal_no=line.deal_no,
            airline_name=line.airline_name,
            channel=line.channel,
            entity=line.entity,
            lob=line.lob,
            plb_period_from=line.period_start,
            plb_period_to=line.period_end,
            plb_period_label=period_label(line.period_start, line.period_end),
            flown_confirmed_through=confirmed_through,
            basis_label=line.basis_label,
            deflator_pct=_effective_deflator(window_cells),
            deflator_source="locked" if deflator_locked else "derived",
            plb_rate_pct=rate.pct,
            plb_rate_source=rate.source,
            plb_rate_explain=rate.explain,
            months=wide_cells,
            flown_total=flown_total,
            flown_in_period=flown_in_period,
            commissionable_base=base_total,
            accrual=accrual,
            accrual_at_risk=accrual_at_risk,
            status=min(flags, key=lambda f: STATUS_ORDER.index(f)),
            status_flags=flags,
            reasons=reasons,
        ))

    # ── Airlines with flown revenue and no PLB deal at all ───────────────────
    for (airline_key, channel_key), by_month in orphan.items():
        cells: dict[str, MonthCell] = {}
        for ym in months:
            agg = by_month.get(ym)
            cells[ym] = MonthCell(
                ym=ym,
                flown=round(agg.gross, 2) if agg else 0.0,
                source="derived" if agg else "none",
                in_period=False, confirmed=False,
                deflator_pct=0.0, commissionable=0.0,
            )
        total = round(sum(c.flown for c in cells.values()), 2)
        if abs(total) < 1:
            continue
        rows.append(BoardRow(
            key=f"nodeal-{airline_key}-{channel_key}",
            deal_id=None, deal_no=None,
            airline_name=airline_key.title(),
            channel=channel_key.upper() or "-",
            entity=None, lob=None,
            plb_period_from=None, plb_period_to=None, plb_period_label="-",
            flown_confirmed_through=None,
            basis_label="-",
            deflator_pct=0.0, deflator_source="none",
            plb_rate_pct=0.0, plb_rate_source="none",
            plb_rate_explain="No approved airline deal with a PLB incentive covers this carrier.",
            months=cells,
            flown_total=total, flown_in_period=0.0,
            commissionable_base=0.0, accrual=0.0, accrual_at_risk=0.0,
            status="NO_DEAL", status_flags=["NO_DEAL"],
            reasons=[f"Rs {total:,.0f} flown with no PLB deal on file - nothing is being claimed."],
        ))

    rows.sort(key=lambda r: (-abs(r.accrual), r.airline_name, r.entity or "", r.channel))

    return {
        "period": {
            "key": period.key, "label": period.label,
            "from": period.start, "to": period.end,
        },
        "months": months,
        "basis": basis,
        "rows": rows,
        "totals": compute_totals(rows, months),
        "data_quality": {
            "travel_date_coverage_pct": await _travel_date_coverage(
                db, tenant_id, user_id, period.start, period.end
            ),
            "unattributed_airlines": sorted({k[0].title() for k in pooled_lines}),
        },
    }


def compute_totals(rows: list[BoardRow], months: list[str]) -> dict:
    """The grand-total row and the KPI figures derived from it.

    Separate from build_board because the API filters rows AFTER building, and a
    totals row that ignored the active filter would contradict the grid above it.
    """
    at_risk = round(sum(
        r.flown_total for r in rows
        if r.status in ("EXPIRED_WITH_FLOWN", "NO_DEAL", "NO_RATE")
    ), 2)
    totals: dict = {
        "rows": len(rows),
        "flown_total": round(sum(r.flown_total for r in rows), 2),
        "flown_in_period": round(sum(r.flown_in_period for r in rows), 2),
        "commissionable_base": round(sum(r.commissionable_base for r in rows), 2),
        "accrual": round(sum(r.accrual for r in rows), 2),
        "accrual_at_risk": round(sum(r.accrual_at_risk for r in rows), 2),
        "by_month": {
            ym: round(sum(r.months[ym].flown for r in rows if ym in r.months), 2)
            for ym in months
        },
        "accrual_by_month": {
            ym: round(sum(
                r.months[ym].commissionable * r.plb_rate_pct / 100
                for r in rows if ym in r.months
            ), 2)
            for ym in months
        },
        "flown_at_risk": at_risk,
        "status_counts": {s: sum(1 for r in rows if s in r.status_flags) for s in STATUS_ORDER},
    }
    # Denominated on all flown in the window, matching the accrual policy above.
    gross = totals["flown_total"]
    totals["effective_deflator_pct"] = (
        round(totals["commissionable_base"] / gross * 100, 2) if abs(gross) >= 0.005 else 0.0
    )
    totals["effective_yield_pct"] = (
        round(totals["accrual"] / gross * 100, 4) if abs(gross) >= 0.005 else 0.0
    )
    confirmed = round(sum(
        c.flown for r in rows for ym, c in r.months.items()
        if ym in months and c.confirmed
    ), 2)
    totals["flown_confirmed"] = confirmed
    totals["flown_provisional"] = round(totals["flown_total"] - confirmed, 2)
    return totals


def filter_rows(
    rows: list[BoardRow],
    airlines: list[str] | None = None,
    entities: list[str] | None = None,
    channels: list[str] | None = None,
    lobs: list[str] | None = None,
    statuses: list[str] | None = None,
    search: str | None = None,
) -> list[BoardRow]:
    """Apply the board's filter bar. Multi-value filters are OR within a facet and
    AND across facets, which is what a filter row on a spreadsheet does."""
    def want(values: list[str] | None, actual: str | None) -> bool:
        if not values:
            return True
        return norm_key(actual) in {norm_key(v) for v in values}

    q = norm_key(search)
    out = []
    for r in rows:
        if not want(airlines, r.airline_name):
            continue
        if not want(entities, r.entity):
            continue
        if not want(channels, r.channel):
            continue
        if not want(lobs, r.lob):
            continue
        if statuses and not ({s.upper() for s in statuses} & set(r.status_flags)):
            continue
        if q:
            hay = norm_key(" ".join(filter(None, [
                r.airline_name, r.entity, r.channel, r.lob, r.deal_no, r.plb_period_label,
            ])))
            if q not in hay:
                continue
        out.append(r)
    return out
