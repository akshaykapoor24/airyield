"""What each workspace costs to run — the console's AI, Files and Database columns.

tenant_usage.py answers "how much has this workspace done", in rows. This answers "what does
it cost the platform to carry": OpenAI spend, object storage, and its share of Postgres.

    ai_usage        ai_usage_events, priced by services/ai_pricing.py
    file_usage      stored_objects (see services/usage_meter.py for how rows get there)
    db_footprint    an ESTIMATE, computed from Postgres itself — see below

THE DATABASE FIGURE IS AN ESTIMATE, AND HERE IS EXACTLY WHICH ONE
    Postgres does not know which bytes of a shared table belong to which workspace. So each
    table's real on-disk size — pg_total_relation_size: heap, indexes and TOAST, bloat
    included — is split across workspaces by their share of its rows:

        workspace bytes = Σ over tables  table_size × workspace_rows / table_rows

    Row widths within one table are similar enough for this to be right to within a few
    percent, and it adds up to the real disk figure rather than to a sum of column widths
    that would miss indexes and page overhead. Exact per-row measurement (pg_column_size)
    would read every row of every table on each page load, and still miss the indexes.

    Tables with no tenant_id of their own (a deal's slabs, a BSP upload's parse errors)
    take their share from the nearest tenant-scoped ancestor, found through the same
    CHILD_TABLES map the workspace delete uses. That map, and the group each table belongs
    to, are enforced complete by tests/test_tenant_deletion.py — so a table added tomorrow
    is attributed here without anyone remembering this module. Whatever is left over
    (global masters, NULL-tenant rows, system catalogs) is the platform's own share.

    Measuring counts every tenant-scoped table, so the result is cached for FOOTPRINT_TTL_S
    and shared by every page, filter and the stats tiles; `measured_at` says how old it is.
"""
from __future__ import annotations

import asyncio
import importlib
import pkgutil
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import String, func, literal, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_pricing import cost_usd

FOOTPRINT_TTL_S = 300
# Per-workspace hover panels list the biggest few members and fold the rest into one line.
_MEMBER_LINES = 5

FEATURE_LABELS: dict[str, str] = {
    "ai-extract": "Deal sheet extraction",
    "ai-narration": "Statement narration parsing",
    "series-extract": "Series contract reading",
}

# The first segment of every stored object's path (services/usage_meter.classify), named the
# way the product's own navigation names the feature.
SOURCE_LABELS: dict[str, str] = {
    "bsp": "BSP statements",
    "bsp-summary": "BSP summary",
    "deals": "Deal sheets",
    "tickets": "Internal statements",
    "customer-statements": "Customer statements",
    "statements": "Vendor statements",
    "lcc-detailed": "Detailed statements",
    "adjustments": "ADM / ACM / RA",
    "series": "Series contracts",
    "logos": "Company logo",
    "reports": "Generated reports",
}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _member_names(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    from app.models.user import User

    ids = {u for u in user_ids if u is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))).all()
    return {uid: (name or email or f"User #{uid}") for uid, name, email in rows}


def _member_label(user_id: int | None, names: dict[int, str]) -> str:
    # NULL is either a member since removed (the FK is SET NULL) or a file from before
    # metering whose uploader the sync script could not recover — not knowable which.
    if user_id is None:
        return "Unknown member"
    return names.get(user_id, f"User #{user_id}")


# ── OpenAI ───────────────────────────────────────────────────────────────────

@dataclass
class _Tally:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    unpriced_calls: int = 0

    def add(self, model: str, calls: int, prompt: int, cached: int, completion: int) -> None:
        self.calls += calls
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        dollars = cost_usd(model, prompt, cached, completion)
        if dollars is None:
            self.unpriced_calls += calls
        else:
            self.cost += dollars

    def line(self, label: str) -> dict:
        return {
            "label": label,
            "calls": self.calls,
            "tokens": self.prompt_tokens + self.completion_tokens,
            "cost_usd": round(self.cost, 4),
        }


def _ai_summary(total: _Tally, month: _Tally, by_feature: dict[str, _Tally],
                by_member: dict[int | None, _Tally], names: dict[int, str]) -> dict:
    features = sorted(by_feature.items(), key=lambda kv: (-kv[1].cost, -kv[1].calls))
    members = sorted(by_member.items(), key=lambda kv: (-kv[1].cost, -kv[1].calls))
    member_lines = [t.line(_member_label(uid, names)) for uid, t in members[:_MEMBER_LINES]]
    if len(members) > _MEMBER_LINES:
        rest = _Tally()
        for _, t in members[_MEMBER_LINES:]:
            rest.calls += t.calls
            rest.prompt_tokens += t.prompt_tokens
            rest.completion_tokens += t.completion_tokens
            rest.cost += t.cost
        member_lines.append(rest.line(f"{len(members) - _MEMBER_LINES} others"))
    return {
        "calls": total.calls,
        "prompt_tokens": total.prompt_tokens,
        "completion_tokens": total.completion_tokens,
        "cost_usd": round(total.cost, 4),
        "unpriced_calls": total.unpriced_calls,
        "month_calls": month.calls,
        "month_cost_usd": round(month.cost, 4),
        "by_feature": [t.line(FEATURE_LABELS.get(f, f)) for f, t in features],
        "by_member": member_lines,
    }


def _ai_columns(E, month_start: datetime):
    in_month = E.created_at >= month_start
    return (
        func.count(),
        func.coalesce(func.sum(E.prompt_tokens), 0),
        func.coalesce(func.sum(E.cached_prompt_tokens), 0),
        func.coalesce(func.sum(E.completion_tokens), 0),
        func.count().filter(in_month),
        func.coalesce(func.sum(E.prompt_tokens).filter(in_month), 0),
        func.coalesce(func.sum(E.cached_prompt_tokens).filter(in_month), 0),
        func.coalesce(func.sum(E.completion_tokens).filter(in_month), 0),
    )


async def ai_usage(db: AsyncSession, tenant_ids: list[int],
                   now: datetime | None = None) -> dict[int, dict]:
    """``{tenant_id: summary}`` — all-time and this calendar month (UTC), by feature and by
    member. One grouped query; pricing happens here because it is per model."""
    from app.models.usage_meter import AiUsageEvent as E

    if not tenant_ids:
        return {}
    rows = (await db.execute(
        select(E.tenant_id, E.user_id, E.feature, E.model, *_ai_columns(E, _month_start(now or _utcnow())))
        .where(E.tenant_id.in_(tenant_ids))
        .group_by(E.tenant_id, E.user_id, E.feature, E.model)
    )).all()

    totals: dict[int, _Tally] = defaultdict(_Tally)
    months: dict[int, _Tally] = defaultdict(_Tally)
    features: dict[int, dict[str, _Tally]] = defaultdict(lambda: defaultdict(_Tally))
    members: dict[int, dict[int | None, _Tally]] = defaultdict(lambda: defaultdict(_Tally))
    for tid, uid, feature, model, n, p, c, o, mn, mp, mc, mo in rows:
        totals[tid].add(model, n, p, c, o)
        months[tid].add(model, mn, mp, mc, mo)
        features[tid][feature].add(model, n, p, c, o)
        members[tid][uid].add(model, n, p, c, o)

    names = await _member_names(db, {uid for m in members.values() for uid in m if uid is not None})
    return {
        tid: _ai_summary(totals[tid], months[tid], features[tid], members[tid], names)
        for tid in totals
    }


# ── stored files ─────────────────────────────────────────────────────────────

async def file_usage(db: AsyncSession, tenant_ids: list[int]) -> dict[int, dict]:
    """``{tenant_id: summary}``. `uploads` counts every file a member ever uploaded,
    deleted or not — the activity. `files` / `bytes` are what is stored right now,
    uploads and generated files alike — the cost."""
    from app.models.usage_meter import ORIGIN_UPLOAD, STORAGE_GCS, StoredObject as S

    if not tenant_ids:
        return {}
    live = S.deleted_at.is_(None)
    rows = (await db.execute(
        select(
            S.tenant_id, S.user_id, S.source, S.origin, S.storage,
            func.count(),
            func.count().filter(live),
            func.coalesce(func.sum(S.size_bytes).filter(live), 0),
        )
        .where(S.tenant_id.in_(tenant_ids))
        .group_by(S.tenant_id, S.user_id, S.source, S.origin, S.storage)
    )).all()

    out: dict[int, dict] = {}
    sources: dict[int, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    members: dict[int, dict[int | None, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for tid, uid, source, origin, storage, n_all, n_live, live_bytes in rows:
        live_bytes = int(live_bytes)   # SUM(bigint) is numeric: asyncpg hands back a Decimal
        s = out.setdefault(tid, {"uploads": 0, "files": 0, "bytes": 0, "gcs_bytes": 0, "local_bytes": 0})
        if origin == ORIGIN_UPLOAD:
            s["uploads"] += n_all
            members[tid][uid][0] += n_all
            members[tid][uid][1] += live_bytes
        s["files"] += n_live
        s["bytes"] += live_bytes
        s["gcs_bytes" if storage == STORAGE_GCS else "local_bytes"] += live_bytes
        sources[tid][source][0] += n_live
        sources[tid][source][1] += live_bytes

    names = await _member_names(db, {uid for m in members.values() for uid in m if uid is not None})
    for tid, s in out.items():
        s["by_source"] = [
            {"label": SOURCE_LABELS.get(src, src), "files": n, "bytes": b}
            for src, (n, b) in sorted(sources[tid].items(), key=lambda kv: -kv[1][1])
            if n
        ]
        ranked = sorted(members[tid].items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
        s["by_member"] = [
            {"label": _member_label(uid, names), "files": n, "bytes": b}
            for uid, (n, b) in ranked[:_MEMBER_LINES]
        ]
    return out


# ── database footprint ───────────────────────────────────────────────────────

@dataclass
class Footprint:
    measured_at: datetime
    database_bytes: int
    attributed_bytes: int
    # {tenant_id: {area label: bytes}}
    by_tenant: dict[int, dict[str, int]] = field(default_factory=dict)

    def for_tenant(self, tenant_id: int) -> dict:
        areas = self.by_tenant.get(tenant_id, {})
        total = sum(areas.values())
        return {
            "bytes": total,
            "share": (total / self.database_bytes) if self.database_bytes else 0.0,
            "by_area": [
                {"label": label, "bytes": b}
                for label, b in sorted(areas.items(), key=lambda kv: -kv[1])
                if b
            ],
            "measured_at": self.measured_at,
        }


_footprint: Footprint | None = None
_footprint_at = 0.0
_footprint_lock = asyncio.Lock()


def _load_all_models() -> None:
    """app.models.__init__ omits a few modules (see tests/test_tenant_usage.py); a table
    whose model was never imported is not in the metadata, and would silently read as
    platform overhead."""
    import app.models

    for mod in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{mod.name}")


def _anchor(table_name: str, tables, depth: int = 0) -> str | None:
    """The tenant-scoped table whose row shares this table's bytes follow."""
    from app.services.tenant_deletion import CHILD_TABLES

    if "tenant_id" in tables[table_name].c:
        return table_name
    child = CHILD_TABLES.get(table_name)
    if child is None or depth > 8:
        return None
    return _anchor(child.links[0].parent_table, tables, depth + 1)


async def _measure(db: AsyncSession) -> Footprint:
    from app.database import Base
    from app.services.tenant_deletion import group_for_table

    _load_all_models()
    tables = Base.metadata.tables
    anchors = {name: a for name in tables if (a := _anchor(name, tables))}

    size_rows = (await db.execute(
        text(
            "SELECT c.relname, pg_total_relation_size(c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind = 'r' AND n.nspname = ANY(current_schemas(false)) "
            "AND c.relname = ANY(:names)"
        ),
        {"names": sorted(anchors)},
    )).all()
    sizes = {name: int(size) for name, size in size_rows}
    database_bytes = int((await db.execute(text("SELECT pg_database_size(current_database())"))).scalar() or 0)

    # Only tables that exist: a model whose migration has not run would fail the whole UNION.
    scoped = sorted({a for n, a in anchors.items() if n in sizes and a in sizes})
    rows_by_table: dict[str, dict[int | None, int]] = defaultdict(dict)
    if scoped:
        parts = [
            select(
                literal(name, String).label("tbl"),
                tables[name].c.tenant_id.label("tenant_id"),
                func.count().label("n"),
            ).group_by(tables[name].c.tenant_id)
            for name in scoped
        ]
        for tbl, tid, n in (await db.execute(union_all(*parts))).all():
            rows_by_table[tbl][tid] = n

    def area_of(name: str) -> str:
        group = group_for_table(name)
        return group.label if group else "Other"

    by_tenant = attribute(anchors, sizes, rows_by_table, area_of)
    return Footprint(
        measured_at=_utcnow(),
        database_bytes=database_bytes,
        attributed_bytes=sum(sum(a.values()) for a in by_tenant.values()),
        by_tenant=by_tenant,
    )


def attribute(anchors: dict[str, str], sizes: dict[str, int],
              rows_by_table: dict[str, dict[int | None, int]],
              area_of) -> dict[int, dict[str, int]]:
    """The arithmetic of the estimate, apart from the queries that feed it.

    Each table's bytes are split by its anchor's row shares; rows with a NULL tenant_id
    (global rules, the platform admin's account) keep their share with the platform.
    """
    by_tenant: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for name, anchor in anchors.items():
        size = sizes.get(name, 0)
        shares = rows_by_table.get(anchor)
        total_rows = sum(shares.values()) if shares else 0
        if not size or not total_rows:
            continue
        area = area_of(name)
        for tid, n in shares.items():
            if tid is not None:
                by_tenant[tid][area] += size * n / total_rows
    return {tid: {a: int(b) for a, b in areas.items()} for tid, areas in by_tenant.items()}


async def db_footprint(*, max_age_s: float = FOOTPRINT_TTL_S) -> Footprint:
    """The cached footprint, re-measured when older than max_age_s. The lock keeps two
    concurrent page loads from both running the count.

    Measured on its own session: the result is shared across requests, so it must not
    depend on — or, by failing, abort — whichever request's transaction happened to
    trigger the refresh."""
    from app.database import AsyncSessionLocal

    global _footprint, _footprint_at
    if _footprint is not None and time.monotonic() - _footprint_at < max_age_s:
        return _footprint
    async with _footprint_lock:
        if _footprint is not None and time.monotonic() - _footprint_at < max_age_s:
            return _footprint
        async with AsyncSessionLocal() as session:
            _footprint = await _measure(session)
        _footprint_at = time.monotonic()
        return _footprint


# ── platform totals (the stats tiles) ────────────────────────────────────────

async def platform_totals(db: AsyncSession, now: datetime | None = None) -> dict:
    """Every workspace plus the unattributed remainder (platform-admin calls, NULL tenant)."""
    from app.models.usage_meter import AiUsageEvent as E, ORIGIN_UPLOAD, STORAGE_GCS, StoredObject as S

    total, month = _Tally(), _Tally()
    for model, n, p, c, o, mn, mp, mc, mo in (await db.execute(
        select(E.model, *_ai_columns(E, _month_start(now or _utcnow()))).group_by(E.model)
    )).all():
        total.add(model, n, p, c, o)
        month.add(model, mn, mp, mc, mo)

    live = S.deleted_at.is_(None)
    uploads, files, gcs_bytes, local_bytes, unattributed = (await db.execute(
        select(
            func.count().filter(S.origin == ORIGIN_UPLOAD),
            func.count().filter(live),
            func.coalesce(func.sum(S.size_bytes).filter(live, S.storage == STORAGE_GCS), 0),
            func.coalesce(func.sum(S.size_bytes).filter(live, S.storage != STORAGE_GCS), 0),
            # Mostly files of deleted workspaces: the workspace delete removes rows and
            # leaves objects to the bucket's lifecycle rule, so they bill with no owner.
            func.coalesce(func.sum(S.size_bytes).filter(live, S.tenant_id.is_(None)), 0),
        )
    )).one()

    # numeric → Decimal, as above
    gcs_bytes, local_bytes, unattributed = int(gcs_bytes), int(local_bytes), int(unattributed)
    fp = await db_footprint()
    return {
        "ai_calls": total.calls,
        "ai_cost_usd": round(total.cost, 4),
        "ai_unpriced_calls": total.unpriced_calls,
        "ai_month_calls": month.calls,
        "ai_month_cost_usd": round(month.cost, 4),
        "uploads": uploads,
        "files": files,
        "gcs_bytes": gcs_bytes,
        "local_bytes": local_bytes,
        "unattributed_bytes": unattributed,
        "database_bytes": fp.database_bytes,
        "database_attributed_bytes": fp.attributed_bytes,
        "database_measured_at": fp.measured_at,
    }
