"""Every database read of Workspace → Report download: the upload picker and the build.

All functions take an ``AsyncConnection`` and filter by ``tenant_id AND created_by_id``. Child
tables with no owner columns (``bsp_tax_breakups``, ``statement_batch_suppliers``,
``statement_batch_airline_ids``, ``tenant_airlines``) are reached only through an owner-scoped
parent or for batch ids ``selection.resolve_selection`` already proved owned. Column lists are
explicit; ``file_url`` is never read, and JSONB is read only where a mapper needs it.

WHY THE LISTING LOOKS LIKE THIS. The picker shows, per upload, how many rows fall in the
period. Spec-driven uploads keep their dates as text in ``data`` in whatever layout the file
used, so the count is a regex date parse (``normalize.date_key_sql``) over every row of the
user's uploads of that type — one ``GROUP BY batch`` per type. That can be slow for a large
account, so each type runs under ``statement_timeout = 15s`` inside a SAVEPOINT: a type that
times out comes back with ``null`` counts and a note instead of failing the page or poisoning
the request's transaction for the types after it.

WHY STREAMS. The builder never holds a whole upload: rows arrive through a server-side cursor
in partitions of ``STREAM_CHUNK``. asyncpg keeps a cursor's portal open across other statements
on the same connection, so the builder may run a tax-breakup or owner lookup between two
partitions (verified against the local database). Consumers should wrap a stream in
``contextlib.aclosing`` so an exception mid-upload closes the cursor at once.

The period filter used by streams and by the listing is the SAME expression
(``row_period_key``), so a row can never be counted by the picker and then left out by the
build, or the reverse.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from time import monotonic
from typing import Any, AsyncIterator, Iterable, Optional, Sequence

from sqlalchemy import (
    BigInteger, Date, String, all_, and_, any_, case, false, func, literal, or_, select, text, true,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.airline import Airline
from app.models.bsp_statement import BspStatement, BspStatementRow, BspTaxBreakup
from app.models.bsp_summary import BspSummaryRow, BspSummaryStatement
from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.models.statement_batch_airline_id import StatementBatchAirlineId
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import TgqHmpr
from app.models.tenant_airline import TenantAirline
from app.services import bsp_tgq_enrichment
from app.services.report_download import pii
from app.services.report_download.linking import OwnerHit
from app.services.report_download.normalize import date_key_sql
from app.services.report_download.registry import CATEGORY_ORDER, SOURCES, ReportSource, get_source
from app.services.report_download.types import (
    AirlineInfo, AirlineMaster, AirlineSnap, Period, ReportOptions, SupplierSnap, TaxComponent,
)
from app.services.statement_display import display_columns

logger = logging.getLogger(__name__)

LISTING_TIMEOUT = "15s"
# Overall budget for one Find-uploads request (see _ListingBudget).
LISTING_BUDGET_S = 20.0
STREAM_CHUNK = 5_000
TAX_CHUNK = 5_000
OWNER_FORMS_CHUNK = 500
MAX_EXTRA_KEYS = 200
#: When counts are unavailable, uploads made this close to the period are ticked by default.
UNDATED_WINDOW_DAYS = 60
STATUS_COMPLETED = "completed"
_PG_QUERY_CANCELED = "57014"

NOTE_COUNTS_UNAVAILABLE = "Row counts unavailable"
NOTE_NO_DATES = "No readable dates"

# Row attributes the streams add next to the model's columns (never model column names).
UNDATED_ATTR = "rd_undated"
IN_PERIOD_ATTR = "rd_in_period"

LEDGER_KEYS = ("lcc-di", "lcc-divided-pnr", "lcc-flown-report", "lcc-cta-bta")
TP_KEYS = ("tp-gds", "tp-lcc", "tp-api")
# BSP tax pivot: the codes an Indian agency reads first, then alphabetical (mapper caps at 80).
BSP_TAX_CODES_FIRST = ("YQ", "YR", "K3", "IN")

__all__ = [
    "source_overview", "list_matching_uploads", "mark_possible_duplicates",
    "row_period_key", "stream_rows", "stream_bsp_keys", "bsp_tax_components", "bsp_tax_codes",
    "lcc_tax_codes", "lcc_extra_keys", "distinct_data_keys", "supplier_snapshots",
    "batch_airlines", "lcc_batch_airlines", "bsp_statement_headers", "bsp_summaries_by_group",
    "bsp_summary_statement_headers", "lcc_batch_headers", "airline_master", "tgq_file_names",
    "bsp_owner_lookup", "upload_fingerprint", "upload_fingerprints", "load_tgq_index",
]


# ── small helpers ────────────────────────────────────────────────────────────

def _text_array(values: Iterable[str]):
    return literal(list(values), ARRAY(String))


def _int_array(values: Iterable[int]):
    return literal(list(values), ARRAY(BigInteger))


def _chunks(values: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _owner(model: Any, tenant_id: int, user_id: int) -> list:
    return [model.tenant_id == tenant_id, model.created_by_id == user_id]


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min)


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _is_timeout(exc: DBAPIError) -> bool:
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == _PG_QUERY_CANCELED or "statement timeout" in str(exc).lower()


def _stream_columns(src: ReportSource, columns: Optional[Sequence[str]]) -> list:
    """Explicit column list: the model's columns minus ``file_url`` (never exported) and, for
    everything but BSP (whose mapper reads the settlement section from it), ``raw_data``."""
    table = src.model.__table__
    if columns is not None:
        return [table.c[name] for name in columns]
    skip = {"file_url"} if src.storage == "bsp" else {"file_url", "raw_data"}
    return [c for c in table.columns if c.name not in skip]


# ── transaction-date period keys (design §D) ─────────────────────────────────

def _data_key(model: Any, field: str):
    return date_key_sql(model.data[field].astext)


def _text_period_key(src: ReportSource, m: Any):
    """'YYYY-MM-DD' text (or NULL) of the row's transaction-basis date."""
    key = src.key
    if key in ("adm", "acm"):
        return func.coalesce(date_key_sql(m.issue_date), date_key_sql(m.reporting_date))
    if key == "ra":
        return func.coalesce(date_key_sql(m.application_date), date_key_sql(m.reporting_date))
    if key == "tgq-hmpr":
        ticket = _data_key(m, "ticket_date")
        return case(
            (func.upper(m.data["transaction_type"].astext).like("%REF%"),
             func.coalesce(_data_key(m, "void_exchange_refund_date"), ticket)),
            else_=ticket,
        )
    if key == "ndc":
        return func.coalesce(_data_key(m, "date_of_issue"), _data_key(m, "date_of_booking"))
    if key == "lcc-di":
        return _data_key(m, "deposit_date")
    if key == "lcc-divided-pnr":
        return func.coalesce(_data_key(m, "divided_date"), _data_key(m, "booking_date"))
    if key == "lcc-flown-report":
        return func.coalesce(_data_key(m, "flown_date"), _data_key(m, "travel_date"), _data_key(m, "booking_date"))
    if key == "lcc-cta-bta":
        return func.coalesce(_data_key(m, "transaction_date"), _data_key(m, "booking_date"))
    if key in ("tp-gds", "tp-lcc"):
        return _data_key(m, "issue_date")
    if key == "tp-api":
        return func.coalesce(_data_key(m, "transaction_date"), _data_key(m, "booking_date"))
    raise KeyError(f"No text period key for {key!r}")


def row_period_key(src: ReportSource, period: Period, header: Any = None):
    """``(key expression, lower bound, upper bound, upper bound exclusive)`` of a source's
    row-level transaction date, or None when the whole upload is in scope (BSP whole-statement,
    BSP Summary). BSP rows use ``coalesce(issue_date, statement period_from)``; LCC Detailed
    its typed ``transaction_date``; every other source the text key above."""
    m = src.model
    if src.storage == "bsp":
        pf = getattr(header, "period_from", None)
        return (func.coalesce(m.issue_date, literal(pf, Date)), period.date_from, period.date_to, False)
    if src.storage == "bsp_summary":
        return None
    if src.storage == "lcc_detailed":
        return (m.transaction_date, _day_start(period.date_from),
                _day_start(period.date_to + timedelta(days=1)), True)
    return (_text_period_key(src, m), period.date_from.isoformat(), period.date_to.isoformat(), False)


def _in_range(key: Any, lo: Any, hi: Any, exclusive: bool):
    return and_(key >= lo, key < hi) if exclusive else and_(key >= lo, key <= hi)


# ── source overview ──────────────────────────────────────────────────────────

async def _overview_counts(conn: AsyncConnection, src: ReportSource, tenant_id: int, user_id: int) -> tuple[int, int]:
    if src.header_model is not None:
        H, R = src.header_model, src.model
        h_where = _owner(H, tenant_id, user_id)
        if src.storage == "lcc_detailed":
            h_where.append(H.status != "staged")      # an unconfirmed upload wizard session
        uploads = select(func.count()).select_from(H).where(*h_where).scalar_subquery()
        rows = select(func.count()).select_from(R).where(*_owner(R, tenant_id, user_id)).scalar_subquery()
        stmt = select(uploads, rows)
    else:
        m = src.model
        rows = func.count().filter(m.is_total.is_(False)) if src.exclude_totals else func.count()
        stmt = select(func.count(m.batch_id.distinct()), rows).where(*_owner(m, tenant_id, user_id))
    r = (await conn.execute(stmt)).first()
    return (int(r[0] or 0), int(r[1] or 0)) if r is not None else (0, 0)


async def source_overview(conn: AsyncConnection, tenant_id: int, user_id: int) -> list[dict]:
    """``[{category, types: [{key, label, uploads, rows}]}]`` in category and registry order."""
    counts = {src.key: await _overview_counts(conn, src, tenant_id, user_id) for src in SOURCES}
    return [
        {
            "category": cat,
            "types": [
                {"key": s.key, "label": s.label, "uploads": counts[s.key][0], "rows": counts[s.key][1]}
                for s in SOURCES if s.category == cat
            ],
        }
        for cat in CATEGORY_ORDER
    ]


# ── upload listing ───────────────────────────────────────────────────────────

def _near_period(ts: Optional[datetime], period: Period) -> bool:
    if ts is None:
        return False
    lo = _day_start(period.date_from - timedelta(days=UNDATED_WINDOW_DAYS))
    hi = _day_start(period.date_to + timedelta(days=UNDATED_WINDOW_DAYS + 1))
    return lo <= ts < hi


def _uploaded_in(ts: Optional[datetime], period: Period) -> bool:
    return ts is not None and _day_start(period.date_from) <= ts < _day_start(period.date_to + timedelta(days=1))


def _item(src: ReportSource, *, upload_id: str, file_name: Optional[str], uploaded_at: Optional[datetime],
          status: Optional[str], total: int, in_period: Optional[int], undated: Optional[int],
          date_min: Any, date_max: Any, notes: Optional[list[str]] = None) -> dict:
    selectable = not src.completed_only or (status or "").lower() == STATUS_COMPLETED
    notes = list(notes or [])
    if not selectable:
        notes.append(f"Not completed ({status or 'not processed'}); it can be included once processing finishes.")
    if in_period is None:
        default = False
    else:
        default = in_period > 0
        if in_period == 0 and (undated or 0) > 0:
            notes.append(NOTE_NO_DATES)
    return {
        "source_type": src.key, "category": src.category, "label": src.label,
        "upload_id": upload_id, "file_name": file_name, "uploaded_at": uploaded_at,
        "status": status, "reference": None, "total_rows": int(total or 0),
        "rows_in_period": in_period, "rows_undated": undated,
        "date_min": _iso(date_min), "date_max": _iso(date_max),
        "selectable": selectable, "default_selected": bool(default and selectable),
        "possible_duplicate_of": None, "notes": notes,
    }


def _listed(item: dict, period: Period) -> bool:
    ip, ud = item["rows_in_period"], item["rows_undated"]
    if ip is None:
        return True
    if ip > 0 or (ud or 0) > 0:
        return True
    # A not-completed upload with nothing readable yet: shown (disabled) when it could belong.
    return not item["selectable"] and item["total_rows"] == 0 and _near_period(item["uploaded_at"], period)


def _statement_overlap(pf: Optional[date], pt: Optional[date], period: Period) -> Optional[bool]:
    """None when the statement has no period at all (undated)."""
    lo, hi = pf or pt, pt or pf
    if lo is None:
        return None
    return lo <= period.date_to and hi >= period.date_from


async def _list_bsp(conn, src, tenant_id, user_id, period, basis, bsp_scope) -> list[dict]:
    S, R = BspStatement, BspStatementRow
    on = and_(R.statement_id == S.batch_id, R.tenant_id == tenant_id, R.created_by_id == user_id)
    cols = [S.batch_id, S.file_name, S.created_at, S.status, S.statement_name, S.group_id,
            S.period_from, S.period_to, func.count(R.id)]
    row_scope = basis == "transaction" and bsp_scope == "issue_date"
    if row_scope:
        eff = func.coalesce(R.issue_date, S.period_from)
        cols += [
            func.count(R.id).filter(eff.between(period.date_from, period.date_to)),
            func.count(R.id).filter(eff.is_(None)),
            func.min(eff), func.max(eff),
        ]
    stmt = (select(*cols).select_from(S).outerjoin(R, on)
            .where(*_owner(S, tenant_id, user_id)).group_by(S.batch_id))
    out = []
    for r in (await conn.execute(stmt)).all():
        total = int(r[8] or 0)
        overlap = _statement_overlap(r.period_from, r.period_to, period)
        if basis == "upload":
            ip, ud = (total if _uploaded_in(r.created_at, period) else 0), 0
            dmin, dmax = r.period_from, r.period_to
        elif row_scope:
            ip, ud, dmin, dmax = int(r[9] or 0), int(r[10] or 0), r[11], r[12]
        else:
            ip = total if overlap else 0
            ud = total if overlap is None else 0
            dmin, dmax = r.period_from or r.period_to, r.period_to or r.period_from
        item = _item(src, upload_id=r.batch_id, file_name=r.file_name, uploaded_at=r.created_at,
                     status=r.status, total=total, in_period=ip, undated=ud, date_min=dmin, date_max=dmax)
        if not item["selectable"] and total == 0 and basis == "transaction" and overlap:
            item["_force"] = True
        item["_group_id"], item["_statement_name"] = r.group_id, r.statement_name
        out.append(item)
    return out


async def _list_bsp_summary(conn, src, tenant_id, user_id, period, basis) -> list[dict]:
    S, R = BspSummaryStatement, BspSummaryRow
    on = and_(R.summary_id == S.batch_id, R.tenant_id == tenant_id, R.created_by_id == user_id)
    stmt = (select(S.batch_id, S.file_name, S.created_at, S.status, S.agent_name, S.period_from,
                   S.period_to, func.count(R.id))
            .select_from(S).outerjoin(R, on).where(*_owner(S, tenant_id, user_id)).group_by(S.batch_id))
    out = []
    for r in (await conn.execute(stmt)).all():
        total = int(r[7] or 0)
        overlap = _statement_overlap(r.period_from, r.period_to, period)
        if basis == "upload":
            ip, ud = (total if _uploaded_in(r.created_at, period) else 0), 0
        else:
            ip = total if overlap else 0
            ud = total if overlap is None else 0
        item = _item(src, upload_id=r.batch_id, file_name=r.file_name, uploaded_at=r.created_at,
                     status=r.status, total=total, in_period=ip, undated=ud,
                     date_min=r.period_from or r.period_to, date_max=r.period_to or r.period_from)
        item["reference"] = r.agent_name
        if not item["selectable"] and total == 0 and basis == "transaction" and overlap:
            item["_force"] = True
        out.append(item)
    return out


async def _list_lcc_detailed(conn, src, tenant_id, user_id, period, basis) -> list[dict]:
    B, L = LccDetailedBatch, LccDetailed
    on = and_(L.batch_id == B.batch_id, L.tenant_id == tenant_id, L.created_by_id == user_id)
    td = L.transaction_date
    lo, hi = _day_start(period.date_from), _day_start(period.date_to + timedelta(days=1))
    stmt = (
        select(B.batch_id, B.source_file, B.uploaded_at, B.status, B.airline_name, func.count(L.id),
               func.count(L.id).filter(and_(td >= lo, td < hi)),
               func.count(L.id).filter(td.is_(None)), func.min(td), func.max(td))
        .select_from(B).outerjoin(L, on)
        .where(*_owner(B, tenant_id, user_id), B.status != "staged")
        .group_by(B.batch_id)
    )
    out = []
    for r in (await conn.execute(stmt)).all():
        total = int(r[5] or 0)
        if basis == "upload":
            ip, ud = (total if _uploaded_in(r.uploaded_at, period) else 0), 0
        else:
            ip, ud = int(r[6] or 0), int(r[7] or 0)
        item = _item(src, upload_id=r.batch_id, file_name=r.source_file, uploaded_at=r.uploaded_at,
                     status=r.status, total=total, in_period=ip, undated=ud, date_min=r[8], date_max=r[9])
        item["reference"] = r.airline_name
        out.append(item)
    return out


async def _list_spec(conn, src, tenant_id, user_id, period, basis) -> list[dict]:
    m = src.model
    where = _owner(m, tenant_id, user_id)
    if src.exclude_totals:
        where.append(m.is_total.is_(False))
    if basis == "upload":
        stmt = (select(m.batch_id, func.max(m.source_file), func.max(m.uploaded_at), func.count())
                .where(*where).group_by(m.batch_id))
        out = []
        for r in (await conn.execute(stmt)).all():
            total = int(r[3] or 0)
            ip = total if _uploaded_in(r[2], period) else 0
            out.append(_item(src, upload_id=r[0], file_name=r[1], uploaded_at=r[2], status=None,
                             total=total, in_period=ip, undated=0, date_min=None, date_max=None))
        return out

    # OFFSET 0 keeps the planner from inlining the subquery, so the regex date parse runs
    # once per row rather than once per aggregate that reads it.
    inner = (select(m.batch_id, m.source_file, m.uploaded_at, _text_period_key(src, m).label("k"))
             .where(*where).offset(0).subquery())
    k = inner.c.k
    lo, hi = period.date_from.isoformat(), period.date_to.isoformat()
    stmt = (
        select(inner.c.batch_id, func.max(inner.c.source_file), func.max(inner.c.uploaded_at), func.count(),
               func.count().filter(and_(k >= lo, k <= hi)), func.count().filter(k.is_(None)),
               func.min(k), func.max(k))
        .group_by(inner.c.batch_id)
    )
    return [
        _item(src, upload_id=r[0], file_name=r[1], uploaded_at=r[2], status=None, total=int(r[3] or 0),
              in_period=int(r[4] or 0), undated=int(r[5] or 0), date_min=r[6], date_max=r[7])
        for r in (await conn.execute(stmt)).all()
    ]


async def _list_spec_fallback(conn, src, tenant_id, user_id, period) -> list[dict]:
    """Counts timed out: every upload of the type, no counts, ticked when uploaded near the period."""
    m = src.model
    where = _owner(m, tenant_id, user_id)
    if src.exclude_totals:
        where.append(m.is_total.is_(False))
    stmt = select(m.batch_id, func.max(m.source_file), func.max(m.uploaded_at), func.count()).where(*where).group_by(m.batch_id)
    out = []
    for r in (await conn.execute(stmt)).all():
        item = _item(src, upload_id=r[0], file_name=r[1], uploaded_at=r[2], status=None, total=int(r[3] or 0),
                     in_period=None, undated=None, date_min=None, date_max=None, notes=[NOTE_COUNTS_UNAVAILABLE])
        item["default_selected"] = _near_period(r[2], period)
        out.append(item)
    return out


async def _list_header_fallback(conn, src, tenant_id, user_id, period) -> list[dict]:
    """Counts timed out for a header type: its uploads from the header table alone, ticked
    when the statement period overlaps (or, with no period, it was uploaded near it)."""
    H = src.header_model
    if src.storage == "bsp":
        cols = [H.batch_id, H.file_name, H.created_at, H.status, func.greatest(H.row_count, H.total_rows),
                H.period_from, H.period_to, H.group_id, H.statement_name]
    elif src.storage == "bsp_summary":
        cols = [H.batch_id, H.file_name, H.created_at, H.status, literal(0), H.period_from, H.period_to,
                literal(None, String), H.agent_name]
    else:
        cols = [H.batch_id, H.source_file, H.uploaded_at, H.status, H.total_rows, literal(None, Date),
                literal(None, Date), literal(None, String), H.airline_name]
    where = _owner(H, tenant_id, user_id)
    if src.storage == "lcc_detailed":
        where.append(H.status != "staged")
    out = []
    for r in (await conn.execute(select(*cols).where(*where))).all():
        item = _item(src, upload_id=r[0], file_name=r[1], uploaded_at=r[2], status=r[3], total=int(r[4] or 0),
                     in_period=None, undated=None, date_min=r[5] or r[6], date_max=r[6] or r[5],
                     notes=[NOTE_COUNTS_UNAVAILABLE])
        overlap = _statement_overlap(r[5], r[6], period)
        near = overlap if overlap is not None else _near_period(r[2], period)
        item["default_selected"] = bool(item["selectable"] and near)
        if src.storage == "bsp":
            item["_group_id"], item["_statement_name"] = r[7], r[8]
        else:
            item["reference"] = r[8]
        out.append(item)
    return out


@dataclass
class _ListingBudget:
    """One Find-uploads request's overall time budget.

    Each type may time out at LISTING_TIMEOUT on its counts and again on its fallback, so 15
    types could otherwise hold the request for minutes. Once one count has timed out, or the
    budget is spent, the remaining types skip straight to the cheap header-only listing."""
    deadline: float
    timed_out: bool = False

    def exhausted(self) -> bool:
        return self.timed_out or monotonic() >= self.deadline


async def _set_timeout(conn: AsyncConnection, value: str) -> None:
    # set_config(…, is_local => true) is SET LOCAL with a bindable value.
    await conn.execute(text("SELECT set_config('statement_timeout', :v, true)"), {"v": value})


async def _list_type(conn, src, tenant_id, user_id, period, basis, bsp_scope, original_timeout,
                     budget: "_ListingBudget") -> list[dict]:
    async def run() -> list[dict]:
        if src.storage == "bsp":
            return await _list_bsp(conn, src, tenant_id, user_id, period, basis, bsp_scope)
        if src.storage == "bsp_summary":
            return await _list_bsp_summary(conn, src, tenant_id, user_id, period, basis)
        if src.storage == "lcc_detailed":
            return await _list_lcc_detailed(conn, src, tenant_id, user_id, period, basis)
        return await _list_spec(conn, src, tenant_id, user_id, period, basis)

    if not budget.exhausted():
        try:
            async with conn.begin_nested():
                await _set_timeout(conn, LISTING_TIMEOUT)
                items = await run()
                await _set_timeout(conn, original_timeout)
            return items
        except DBAPIError as exc:
            if not _is_timeout(exc):
                raise
            budget.timed_out = True
            logger.warning("report uploads: counting %s timed out for user %s", src.key, user_id)
    fallback = _list_header_fallback if src.header_model is not None else _list_spec_fallback
    try:
        async with conn.begin_nested():
            await _set_timeout(conn, LISTING_TIMEOUT)
            items = await fallback(conn, src, tenant_id, user_id, period)
            await _set_timeout(conn, original_timeout)
        return items
    except DBAPIError as exc:
        if not _is_timeout(exc):
            raise
        logger.warning("report uploads: listing %s timed out for user %s", src.key, user_id)
        return []


async def _attach_references(conn, src: ReportSource, tenant_id: int, user_id: int, items: list[dict]) -> None:
    if not items:
        return
    ids = [i["upload_id"] for i in items]
    if src.key == "bsp":
        groups = {i["_group_id"] for i in items if i.get("_group_id")}
        summaries = await bsp_summaries_by_group(conn, tenant_id, user_id, groups) if groups else {}
        for i in items:
            sm = summaries.get(i.get("_group_id"))
            i["reference"] = (getattr(sm, "agent_name", None) if sm is not None else None) or i.get("_statement_name")
    elif src.key in TP_KEYS:
        snaps = await supplier_snapshots(conn, tenant_id, user_id, src.key, ids)
        for i in items:
            snap = snaps.get(i["upload_id"])
            i["reference"] = snap.name if snap is not None else None
    elif src.key in LEDGER_KEYS:
        snaps = await batch_airlines(conn, tenant_id, user_id, src.key, ids)
        for i in items:
            snap = snaps.get(i["upload_id"])
            i["reference"] = snap.name if snap is not None else None


def _sort_key(item: dict) -> tuple:
    ts = item.get("uploaded_at")
    return (ts is None, -(ts.timestamp()) if ts is not None else 0.0, item["upload_id"])


def mark_possible_duplicates(uploads: list[dict]) -> None:
    """Point an older upload at a newer one of the same type that looks like the same file. Pure.

    Two strengths, because unticking by default silently drops a whole file from the report:
      * same row count AND date range (and the same reference — airline / supplier / agent —
        when both carry one): noted AND unticked; re-uploading one export gives exactly this.
      * same file name only: noted, but left ticked. Generic export names ("Statement.xlsx")
        are common, and two airlines' files can share one.
    Uploads whose references differ are never related at all.
    """
    by_type: dict[str, list[dict]] = {}
    for u in uploads:
        by_type.setdefault(u.get("source_type"), []).append(u)
    for group in by_type.values():
        ordered = sorted(group, key=_sort_key)
        for i, older in enumerate(ordered):
            name = (older.get("file_name") or "").strip().lower()
            shape = (older.get("total_rows"), older.get("date_min"), older.get("date_max"))
            dated = older.get("date_min") is not None or older.get("date_max") is not None
            ref = (older.get("reference") or "").strip().lower()
            name_match: Optional[dict] = None
            for newer in ordered[:i]:
                if newer.get("upload_id") == older.get("upload_id"):
                    continue
                newer_ref = (newer.get("reference") or "").strip().lower()
                if ref and newer_ref and ref != newer_ref:
                    continue
                same_shape = (dated and (older.get("total_rows") or 0) > 0
                              and shape == (newer.get("total_rows"), newer.get("date_min"), newer.get("date_max")))
                if same_shape:
                    older["possible_duplicate_of"] = {"upload_id": newer["upload_id"], "file_name": newer.get("file_name")}
                    older["default_selected"] = False
                    name_match = None
                    break
                if name_match is None and name and name == (newer.get("file_name") or "").strip().lower():
                    name_match = newer
            if name_match is not None and not older.get("possible_duplicate_of"):
                older["possible_duplicate_of"] = {"upload_id": name_match["upload_id"], "file_name": name_match.get("file_name")}


async def list_matching_uploads(
    conn: AsyncConnection, tenant_id: int, user_id: int, *, types: Sequence[str], date_from: date,
    date_to: date, basis: str, bsp_scope: str,
) -> dict:
    """The caller's uploads of ``types`` with rows in the period (shape: schemas.UploadsResponse)."""
    period = Period(date_from, date_to)
    wanted = set(types)
    original_timeout = await conn.scalar(text("SELECT current_setting('statement_timeout')")) or "0"
    budget = _ListingBudget(monotonic() + LISTING_BUDGET_S)
    uploads: list[dict] = []
    for src in SOURCES:
        if src.key not in wanted:
            continue
        items = await _list_type(conn, src, tenant_id, user_id, period, basis, bsp_scope,
                                 original_timeout, budget)
        items = [i for i in items if i.pop("_force", False) or _listed(i, period)]
        await _attach_references(conn, src, tenant_id, user_id, items)
        for i in items:
            i.pop("_group_id", None)
            i.pop("_statement_name", None)
        uploads.extend(sorted(items, key=_sort_key))
    mark_possible_duplicates(uploads)

    estimated = 0
    for u in uploads:
        if not (u["selectable"] and u["default_selected"]):
            continue
        if u["rows_in_period"] is None:
            estimated += u["total_rows"]
        else:
            estimated += u["rows_in_period"] + (u["rows_undated"] or 0)
    return {"uploads": uploads, "estimated_rows": estimated}


# ── reference data for the build ─────────────────────────────────────────────

async def airline_master(conn: AsyncConnection) -> AirlineMaster:
    """The global airlines master (no tenant data), once per build."""
    master = AirlineMaster()
    rows = (await conn.execute(select(Airline.iata_code, Airline.iata_numeric_code, Airline.name))).all()
    for iata, numeric, name in rows:
        code = (numeric or "").strip()
        info = AirlineInfo(iata_code=(iata or "").strip().upper() or None,
                           numeric_code=code.zfill(3) if code.isdigit() else (code or None), name=name)
        if info.numeric_code:
            master.by_numeric.setdefault(info.numeric_code, info)
        if info.iata_code:
            master.by_iata.setdefault(info.iata_code, info)
    return master


_BSP_HEADER_COLS = (
    "batch_id", "statement_name", "airline_code", "airline_name", "period_from", "period_to",
    "file_name", "row_count", "status", "total_rows", "group_id", "gt_issues", "gt_refunds",
    "gt_debit_memos", "gt_credit_memos", "gt_std_comm", "gt_sup_comm", "gt_tax_on_comm",
    "gt_balance_payable", "gt_doc_count", "created_at",
)
_SUMMARY_HEADER_COLS = (
    "batch_id", "group_id", "agent_code", "agent_name", "reference", "billing_period_code",
    "period_from", "period_to", "currency", "file_name", "status", "gt_issues", "gt_refunds",
    "gt_debit_memos", "gt_credit_memos", "gt_std_comm", "gt_sup_comm", "gt_tax_on_comm",
    "gt_balance_payable", "gt_doc_count", "match_status", "match_detail", "created_at",
)
_LCC_BATCH_COLS = (
    "batch_id", "source_file", "source_format", "tenant_airline_id", "airline_id", "airline_name",
    "airline_code", "airline_ref_id", "status", "total_rows", "uploaded_at", "completed_at",
)


def _cols(model: Any, names: Sequence[str]) -> list:
    return [model.__table__.c[n] for n in names]


async def bsp_statement_headers(conn: AsyncConnection, tenant_id: int, user_id: int,
                                statement_ids: Sequence[str]) -> dict[str, Any]:
    if not statement_ids:
        return {}
    S = BspStatement
    rows = (await conn.execute(select(*_cols(S, _BSP_HEADER_COLS)).where(
        *_owner(S, tenant_id, user_id), S.batch_id == any_(_text_array(statement_ids))))).all()
    return {r.batch_id: r for r in rows}


async def bsp_summaries_by_group(conn: AsyncConnection, tenant_id: int, user_id: int,
                                 group_ids: Iterable[str]) -> dict[str, Any]:
    """The caller's own BSP summary per detailed-statement group (group_id is free text, so
    the pairing is owner-scoped). A completed summary wins, then the newest."""
    groups = sorted({g for g in group_ids if g})
    if not groups:
        return {}
    S = BspSummaryStatement
    rows = (await conn.execute(select(*_cols(S, _SUMMARY_HEADER_COLS)).where(
        *_owner(S, tenant_id, user_id), S.group_id == any_(_text_array(groups))))).all()
    best: dict[str, Any] = {}
    for r in rows:
        cur = best.get(r.group_id)
        rank = ((r.status or "") == STATUS_COMPLETED, r.created_at or datetime.min)
        if cur is None or rank > ((cur.status or "") == STATUS_COMPLETED, cur.created_at or datetime.min):
            best[r.group_id] = r
    return best


async def bsp_summary_statement_headers(conn: AsyncConnection, tenant_id: int, user_id: int,
                                        summary_ids: Sequence[str]) -> dict[str, Any]:
    if not summary_ids:
        return {}
    S = BspSummaryStatement
    rows = (await conn.execute(select(*_cols(S, _SUMMARY_HEADER_COLS)).where(
        *_owner(S, tenant_id, user_id), S.batch_id == any_(_text_array(summary_ids))))).all()
    return {r.batch_id: r for r in rows}


async def lcc_batch_headers(conn: AsyncConnection, tenant_id: int, user_id: int,
                            batch_ids: Sequence[str]) -> dict[str, Any]:
    if not batch_ids:
        return {}
    B = LccDetailedBatch
    rows = (await conn.execute(select(*_cols(B, _LCC_BATCH_COLS)).where(
        *_owner(B, tenant_id, user_id), B.batch_id == any_(_text_array(batch_ids))))).all()
    return {r.batch_id: r for r in rows}


def _snap(ta_id, airline_id, name, code, numeric, ref_id) -> AirlineSnap:
    return AirlineSnap(tenant_airline_id=ta_id, airline_id=airline_id, name=name, code=code,
                       iata_numeric_code=numeric, ref_id=ref_id)


async def lcc_batch_airlines(conn: AsyncConnection, tenant_id: int, user_id: int,
                             batch_ids: Sequence[str]) -> dict[str, AirlineSnap]:
    """The airline declared on each owned LCC Detailed batch (its primary tenant airline id;
    the batch's own snapshot columns when the batch predates the id)."""
    if not batch_ids:
        return {}
    B, TA = LccDetailedBatch, TenantAirline
    stmt = (
        select(B.batch_id, B.tenant_airline_id, B.airline_id, B.airline_name, B.airline_code, B.airline_ref_id,
               TA.airline_id.label("ta_airline_id"), TA.airline_name.label("ta_name"),
               TA.airline_code.label("ta_code"), TA.iata_numeric_code, TA.ref_id)
        .select_from(B)
        .outerjoin(TA, and_(TA.id == B.tenant_airline_id, TA.tenant_id == tenant_id))
        .where(*_owner(B, tenant_id, user_id), B.batch_id == any_(_text_array(batch_ids)))
    )
    out: dict[str, AirlineSnap] = {}
    for r in (await conn.execute(stmt)).all():
        out[r.batch_id] = _snap(
            r.tenant_airline_id, r.ta_airline_id or r.airline_id, r.ta_name or r.airline_name,
            r.ta_code or r.airline_code, r.iata_numeric_code, r.ref_id or r.airline_ref_id,
        )
    return out


async def batch_airlines(conn: AsyncConnection, tenant_id: int, user_id: int, slug: str,
                         batch_ids: Sequence[str]) -> dict[str, AirlineSnap]:
    """Declared airline per LCC ledger upload (``statement_batch_airline_ids`` → tenant
    airline; first by ref id). ``batch_ids`` must already be proven owned: the link table has
    no created_by column, only the tenant."""
    if not batch_ids:
        return {}
    L, TA = StatementBatchAirlineId, TenantAirline
    stmt = (
        select(L.batch_id, TA.id, TA.airline_id, TA.airline_name, TA.airline_code, TA.iata_numeric_code, TA.ref_id)
        .select_from(L).join(TA, TA.id == L.tenant_airline_id)
        .where(L.tenant_id == tenant_id, TA.tenant_id == tenant_id, L.slug == slug,
               L.batch_id == any_(_text_array(batch_ids)))
        .order_by(L.batch_id, TA.ref_id)
    )
    out: dict[str, AirlineSnap] = {}
    for r in (await conn.execute(stmt)).all():
        out.setdefault(r[0], _snap(r[1], r[2], r[3], r[4], r[5], r[6]))
    return out


async def supplier_snapshots(conn: AsyncConnection, tenant_id: int, user_id: int, slug: str,
                             batch_ids: Sequence[str]) -> dict[str, SupplierSnap]:
    """Declared consolidator per third-party upload (snapshot columns). ``batch_ids`` must
    already be proven owned (the link table is tenant-scoped only)."""
    if not batch_ids:
        return {}
    S = StatementBatchSupplier
    stmt = select(S.batch_id, S.supplier_id, S.supplier_name, S.supplier_code, S.supplier_branch).where(
        S.tenant_id == tenant_id, S.slug == slug, S.batch_id == any_(_text_array(batch_ids)))
    return {r[0]: SupplierSnap(supplier_id=r[1], name=r[2], code=r[3], branch=r[4])
            for r in (await conn.execute(stmt)).all()}


async def tgq_file_names(conn: AsyncConnection, tenant_id: int, user_id: int) -> dict[str, str]:
    """TGQ batch id → file name for every TGQ upload of the caller (enrichment names the file)."""
    T = TgqHmpr
    rows = (await conn.execute(
        select(T.batch_id, func.max(T.source_file)).where(*_owner(T, tenant_id, user_id)).group_by(T.batch_id)
    )).all()
    return {r[0]: r[1] for r in rows if r[1]}


# ── fingerprints ─────────────────────────────────────────────────────────────

async def upload_fingerprints(conn: AsyncConnection, tenant_id: int, user_id: int, source_key: str,
                              upload_ids: Sequence[str]) -> dict[str, tuple[Optional[str], int, Optional[int]]]:
    """``upload_id → (status, row count, max row id)`` — compared before and after the build
    to notice an upload re-processed or deleted meanwhile. Missing ids are absent."""
    if not upload_ids:
        return {}
    src = get_source(source_key)
    arr = _text_array(upload_ids)
    if src.header_model is not None:
        H, R = src.header_model, src.model
        link = getattr(R, src.batch_attr)
        stmt = (select(H.batch_id, H.status, func.count(R.id), func.max(R.id)).select_from(H)
                .outerjoin(R, and_(link == H.batch_id, R.tenant_id == tenant_id, R.created_by_id == user_id))
                .where(*_owner(H, tenant_id, user_id), H.batch_id == any_(arr)).group_by(H.batch_id))
    else:
        m = src.model
        stmt = (select(m.batch_id, literal(None, String), func.count(), func.max(m.id))
                .where(*_owner(m, tenant_id, user_id), m.batch_id == any_(arr)).group_by(m.batch_id))
    return {r[0]: (r[1], int(r[2] or 0), r[3]) for r in (await conn.execute(stmt)).all()}


async def upload_fingerprint(conn: AsyncConnection, tenant_id: int, user_id: int, source_key: str,
                             upload_id: str) -> Optional[tuple[Optional[str], int, Optional[int]]]:
    return (await upload_fingerprints(conn, tenant_id, user_id, source_key, [upload_id])).get(upload_id)


# ── streams ──────────────────────────────────────────────────────────────────

async def _stream(conn: AsyncConnection, stmt: Any, chunk: int) -> AsyncIterator[list]:
    async with conn.stream(stmt.execution_options(yield_per=chunk)) as result:
        async for part in result.partitions(chunk):
            yield part


def _order_for(src: ReportSource, cols: Any) -> list:
    if src.exclude_totals:        # sector-split tables: a ticket's legs stay together, in order
        return [cols.row_seq, cols.sector_index, cols.id]
    return [cols.id]


async def stream_rows(
    conn: AsyncConnection, tenant_id: int, user_id: int, source_key: str, upload_id: str, *,
    period: Optional[Period], options: ReportOptions, header: Any = None,
    columns: Optional[Sequence[str]] = None, filter_period: bool = True, flag_period: bool = False,
    chunk: int = STREAM_CHUNK,
) -> AsyncIterator[list]:
    """Rows of one owned upload in partitions, with the period filter applied in SQL.

    * transaction basis: rows whose period key is in the period, plus undated rows when
      ``options.undated_rows == "include"``. BSP rows are filtered only under the
      ``issue_date`` scope (whole statements otherwise); BSP Summary is never filtered.
    * upload basis, or ``filter_period=False``: every row (key scans).
    * ``flag_period=True``: every row, with ``rd_in_period`` saying whether the filter above
      would have kept it (NDC grouping needs the whole upload).

    Every row carries ``rd_undated`` (no readable period date). TGQ / NDC grand-total lines are
    always excluded. Order: id, or ``row_seq, sector_index, id`` for the sector-split tables.
    """
    src = get_source(source_key)
    m = src.model
    cols = _stream_columns(src, columns)
    where = [*_owner(m, tenant_id, user_id), getattr(m, src.batch_attr) == upload_id]
    if src.exclude_totals:
        where.append(m.is_total.is_(False))

    key = None
    if period is not None and options.basis == "transaction":
        if src.storage != "bsp" or options.bsp_scope == "issue_date":
            key = row_period_key(src, period, header)
    if key is None or not (filter_period or flag_period):
        stmt = select(*cols, false().label(UNDATED_ATTR), true().label(IN_PERIOD_ATTR)).where(*where)
        stmt = stmt.order_by(*_order_for(src, m))
        async for part in _stream(conn, stmt, chunk):
            yield part
        return

    expr, lo, hi, exclusive = key
    inner = select(*cols, expr.label("rd_key")).where(*where).offset(0).subquery()
    k = inner.c.rd_key
    keep = func.coalesce(_in_range(k, lo, hi, exclusive), False)
    if options.undated_rows == "include":
        keep = or_(keep, k.is_(None))
    out_cols = [inner.c[c.name] for c in cols]
    stmt = select(*out_cols, k.is_(None).label(UNDATED_ATTR), keep.label(IN_PERIOD_ATTR))
    if not flag_period:
        stmt = stmt.where(keep)
    stmt = stmt.order_by(*_order_for(src, inner.c))
    async for part in _stream(conn, stmt, chunk):
        yield part


_BSP_KEY_COLS = (
    "id", "airline_accounting_code", "airline_code", "document_number", "ticket_number", "spdr_no",
    "rtdn", "alt_document_numbers", "associated_docs", "transaction_type", "issue_date",
    "transaction_amount", "fare_amount", "gross", "commission", "adm", "acm", "refund", "net_due",
)


async def stream_bsp_keys(
    conn: AsyncConnection, tenant_id: int, user_id: int, statement_id: str, *, header: Any,
    period: Optional[Period], options: ReportOptions, chunk: int = STREAM_CHUNK,
) -> AsyncIterator[list]:
    """Identity columns of EVERY row of one owned BSP statement (linking pre-pass), each with
    ``in_period``: always true for whole statements / the upload basis; under the issue-date
    scope ``coalesce(issue_date, period_from)`` in the period (undated rows count as in period
    when the report includes undated rows, because they are then written)."""
    R = BspStatementRow
    in_period: Any = true()
    if period is not None and options.basis == "transaction" and options.bsp_scope == "issue_date":
        expr, lo, hi, exclusive = row_period_key(get_source("bsp"), period, header)
        in_period = func.coalesce(_in_range(expr, lo, hi, exclusive), False)
        if options.undated_rows == "include":
            in_period = or_(in_period, expr.is_(None))
    stmt = (select(*_cols(R, _BSP_KEY_COLS), in_period.label("in_period"))
            .where(*_owner(R, tenant_id, user_id), R.statement_id == statement_id)
            .order_by(R.id))
    async for part in _stream(conn, stmt, chunk):
        yield part


async def bsp_tax_components(conn: AsyncConnection, tenant_id: int, user_id: int,
                             row_ids: Sequence[int]) -> dict[int, list[TaxComponent]]:
    """Tax / fee / penalty breakups per BSP row id, ≤ ``TAX_CHUNK`` ids per query, reached
    through the owner-scoped row table."""
    T, R = BspTaxBreakup, BspStatementRow
    out: dict[int, list[TaxComponent]] = {}
    ids = list(row_ids)
    for part in _chunks(ids, TAX_CHUNK):
        stmt = (select(T.bsp_row_id, T.component_type, T.component_code, T.amount)
                .select_from(T).join(R, R.id == T.bsp_row_id)
                .where(*_owner(R, tenant_id, user_id), T.tenant_id == tenant_id,
                       T.bsp_row_id == any_(_int_array(part)))
                .order_by(T.bsp_row_id, T.id))
        for rid, ctype, code, amount in (await conn.execute(stmt)).all():
            out.setdefault(rid, []).append(TaxComponent(ctype, code, amount))
    return out


def order_bsp_tax_codes(codes: Iterable[str]) -> list[str]:
    uniq = {c.strip().upper() for c in codes if c and c.strip()}
    first = [c for c in BSP_TAX_CODES_FIRST if c in uniq]
    return first + sorted(uniq - set(first))


async def bsp_tax_codes(conn: AsyncConnection, tenant_id: int, user_id: int,
                        statement_ids: Sequence[str]) -> list[str]:
    """Distinct TAX / FEE component codes over the included statements, pivot order."""
    if not statement_ids:
        return []
    T, R = BspTaxBreakup, BspStatementRow
    code = func.upper(func.btrim(T.component_code))
    stmt = (select(code).distinct().select_from(T).join(R, R.id == T.bsp_row_id)
            .where(*_owner(R, tenant_id, user_id), T.tenant_id == tenant_id,
                   R.statement_id == any_(_text_array(statement_ids)),
                   func.upper(T.component_type).in_(("TAX", "FEE")), T.component_code.isnot(None)))
    return order_bsp_tax_codes(r[0] for r in (await conn.execute(stmt)).all())


async def lcc_tax_codes(conn: AsyncConnection, tenant_id: int, user_id: int,
                        batch_ids: Sequence[str]) -> list[str]:
    """Distinct ``taxes[].code`` over the included LCC Detailed batches (unordered; the builder
    orders them with ``lcc_codes.sort_codes``)."""
    if not batch_ids:
        return []
    stmt = text(
        "SELECT DISTINCT upper(btrim(e->>'code')) FROM lcc_detailed l "
        "CROSS JOIN LATERAL jsonb_array_elements("
        "  CASE WHEN jsonb_typeof(l.taxes) = 'array' THEN l.taxes ELSE '[]'::jsonb END) AS e "
        "WHERE l.tenant_id = :t AND l.created_by_id = :u AND l.batch_id = ANY(:ids) "
        "AND jsonb_typeof(e) = 'object' AND coalesce(btrim(e->>'code'), '') <> ''"
    )
    rows = (await conn.execute(stmt, {"t": tenant_id, "u": user_id, "ids": list(batch_ids)})).all()
    return [r[0] for r in rows if r[0]]


def _filter_keys(keys: Iterable[str], include_pii: bool, skip: Iterable[str] = ()) -> tuple[str, ...]:
    skipped = set(skip)
    kept = sorted(k for k in keys if k and k not in skipped and pii.allowed(k, include_pii))
    return tuple(kept[:MAX_EXTRA_KEYS])


async def _jsonb_keys(conn: AsyncConnection, table: str, column: str, tenant_id: int, user_id: int,
                      batch_ids: Sequence[str]) -> list[str]:
    # table / column come from the registry (trusted identifiers), never from the request.
    stmt = text(
        f"SELECT DISTINCT k FROM {table} x "
        f"CROSS JOIN LATERAL jsonb_object_keys("
        f"  CASE WHEN jsonb_typeof(x.{column}) = 'object' THEN x.{column} ELSE '{{}}'::jsonb END) AS k "
        f"WHERE x.tenant_id = :t AND x.created_by_id = :u AND x.batch_id = ANY(:ids)"
    )
    rows = (await conn.execute(stmt, {"t": tenant_id, "u": user_id, "ids": list(batch_ids)})).all()
    return [r[0] for r in rows]


async def lcc_extra_keys(conn: AsyncConnection, tenant_id: int, user_id: int, batch_ids: Sequence[str],
                         include_pii: bool) -> tuple[str, ...]:
    """Keys of LCC Detailed ``extra`` (mapped fields with no typed column), PII-filtered, ≤ 200."""
    if not batch_ids:
        return ()
    keys = await _jsonb_keys(conn, LccDetailed.__tablename__, "extra", tenant_id, user_id, batch_ids)
    return _filter_keys(keys, include_pii)


async def distinct_data_keys(conn: AsyncConnection, tenant_id: int, user_id: int, source_key: str,
                             batch_ids: Sequence[str], include_pii: bool) -> tuple[str, ...]:
    """``data`` keys of a spec-driven source beyond its display columns, PII-filtered, sorted,
    ≤ 200 — the detail sheet's ``data.<key>`` columns."""
    if not batch_ids:
        return ()
    src = get_source(source_key)
    if src.storage != "spec":
        return ()
    keys = await _jsonb_keys(conn, src.model.__tablename__, "data", tenant_id, user_id, batch_ids)
    shown = {c["field"] for c in display_columns(source_key)}
    return _filter_keys(keys, include_pii, shown)


# ── owner lookup outside the selection (design §C.7) ─────────────────────────

async def bsp_owner_lookup(conn: AsyncConnection, tenant_id: int, user_id: int,
                           excluded_statement_ids: Sequence[str], forms: Sequence[str]) -> list[OwnerHit]:
    """Rows of the caller's OTHER completed BSP statements whose document number, ticket number
    or RTDN equals one of ``forms`` (text forms from ``linking.owner_probe_forms``).

    UNION ALL of three equality probes, not one OR, so each arm can use its own index
    ((tenant, created_by, document_number) / (…, rtdn) once migrated; ticket_number already).
    Forms go in batches of ``OWNER_FORMS_CHUNK``. Rows of the included statements are left
    out: those are all in the builder's selection index already.
    """
    R, S = BspStatementRow, BspStatement
    uniq = list(dict.fromkeys(f for f in forms if f))
    excluded = _text_array(excluded_statement_ids or ())
    hits: dict[int, OwnerHit] = {}
    for part in _chunks(uniq, OWNER_FORMS_CHUNK):
        arr = _text_array(part)
        arms = [
            select(R.id, R.airline_accounting_code, R.document_number, R.ticket_number, R.rtdn,
                   func.upper(R.transaction_type), S.file_name)
            .select_from(R).join(S, S.batch_id == R.statement_id)
            .where(*_owner(R, tenant_id, user_id), *_owner(S, tenant_id, user_id),
                   S.status == STATUS_COMPLETED, R.statement_id != all_(excluded), col == any_(arr))
            for col in (R.document_number, R.ticket_number, R.rtdn)
        ]
        for r in (await conn.execute(union_all(*arms))).all():
            if r[0] not in hits:
                hits[r[0]] = OwnerHit(row_id=r[0], code=r[1], document_number=r[2], ticket_number=r[3],
                                      rtdn=r[4], canon=r[5] or "", file_name=r[6])
    return list(hits.values())


async def load_tgq_index(conn: AsyncConnection, tenant_id: int, user_id: int, **kwargs: Any):
    """``bsp_tgq_enrichment.load_tgq_index`` through the query layer, so a test can stub it."""
    return await bsp_tgq_enrichment.load_tgq_index(conn, tenant_id, user_id, **kwargs)
