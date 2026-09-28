"""Records what a workspace costs to run, from the two chokepoints every feature uses.

    ai_client.call_json            → record_ai_call         → ai_usage_events
    gcs.upload_* / file_store      → record_object_stored   → stored_objects
    gcs.delete_blob / file_store   → record_object_deleted  → stored_objects.deleted_at

The read side — pricing, per-workspace totals, the database footprint — is
services/tenant_resources.py. See app/models/usage_meter.py for the tables.

WHO PAYS IS AMBIENT, NOT A PARAMETER
    A UsageScope names the workspace and member an action is on behalf of. The API opens
    one per authenticated request (dependencies.get_current_user); a Celery task opens one
    for the job it runs. The chokepoints read it from a ContextVar, so neither call_json nor
    upload_bytes had to grow tenant/user parameters, and neither did the dozen call sites
    above them.

    A ContextVar and not a global because each request runs in its own asyncio task with its
    own copy of the context — two concurrent requests cannot see each other's scope — and
    because asyncio.gather copies it into the child tasks deal extraction fans its chunks
    out to.

    Nothing is recorded outside a scope. That is deliberate: the unit tests and one-off
    scripts that exercise file_store and call_json directly must not write to whatever
    database DATABASE_URL happens to point at.

RECORDING NEVER BREAKS THE THING IT RECORDS
    Every write is wrapped: a metering failure (table not migrated yet, database slow or
    down) is logged and swallowed, and a write that takes longer than _WRITE_TIMEOUT_S is
    abandoned. An upload that succeeded must not answer 500 because its ledger row did not.

ITS OWN CONNECTION, ITS OWN TRANSACTION
    The caller's transaction may roll back — a parse fails after the file was stored — but
    OpenAI has already billed the call and the object is already in the bucket. So the row
    is committed independently. The engine is NullPool because this module runs in both the
    API and the Celery workers, and the workers call asyncio.run per task: a pooled asyncpg
    connection is bound to the loop that opened it (same reason the workers build their own
    NullPool engines). The extra connect is noise next to an upload or a model call.
"""
from __future__ import annotations

import asyncio
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator

from app.config import settings

logger = logging.getLogger(__name__)

_WRITE_TIMEOUT_S = 5.0


# ── scope ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UsageScope:
    tenant_id: int | None
    user_id: int | None


_scope: ContextVar[UsageScope | None] = ContextVar("usage_scope", default=None)


def enter_scope(tenant_id: int | None, user_id: int | None) -> Token:
    """Attribute everything metered from here on in this context. For the request path,
    where the context dies with the request and there is nothing to reset."""
    return _scope.set(UsageScope(tenant_id, user_id))


@contextmanager
def scope(tenant_id: int | None, user_id: int | None) -> Iterator[UsageScope]:
    """A bounded scope, for workers and housekeeping. (None, None) is a system scope: it
    attributes nothing but still lets a delete be recorded."""
    token = _scope.set(UsageScope(tenant_id, user_id))
    try:
        yield _scope.get()
    finally:
        _scope.reset(token)


def current_scope() -> UsageScope | None:
    return _scope.get()


# ── classification (shared with scripts/sync_stored_objects.py) ──────────────

# Path kinds the product writes itself rather than a member uploading them.
_GENERATED_SOURCES = frozenset({"reports"})
# lcc_detailed._preview_blob: a cached xlsx rendering beside the uploaded CSV.
_PREVIEW_SUFFIX = "._preview.xlsx"


def _segments(object_name: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", object_name or "") if p]


def classify(object_name: str) -> tuple[str, str]:
    """(source, origin) for an object name.

    Every upload is written as ``{kind}/{tenant_id}/…`` — bsp/, deals/, statements/,
    reports/ — so the first segment says which feature it belongs to.
    """
    from app.models.usage_meter import ORIGIN_GENERATED, ORIGIN_UPLOAD

    parts = _segments(object_name)
    source = (parts[0] if parts else "other").lower()[:40]
    generated = source in _GENERATED_SOURCES or (object_name or "").endswith(_PREVIEW_SUFFIX)
    return source, ORIGIN_GENERATED if generated else ORIGIN_UPLOAD


def tenant_from_path(object_name: str) -> int | None:
    """The workspace an object's path names, or None. series/ writes 0 for "no tenant"."""
    parts = _segments(object_name)
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1]) or None
    return None


# ── writing ──────────────────────────────────────────────────────────────────

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        _engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    return _engine


def _active_scope() -> UsageScope | None:
    if not settings.USAGE_METERING_ENABLED:
        return None
    return _scope.get()


async def _execute(stmt: Any, what: str) -> None:
    """Run one statement in its own committed transaction. Never raises."""
    async def run() -> None:
        async with _get_engine().begin() as conn:
            await conn.execute(stmt)

    try:
        await asyncio.wait_for(run(), timeout=_WRITE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — see "never breaks" in the module docstring
        logger.warning("[usage] could not record %s: %s", what, exc)


def _tenant_value(tenant_id: int | None):
    """The id as a scalar subquery, so an id that names no workspace (a path segment that
    only looks like one, a tenant deleted mid-request) records NULL instead of failing the
    foreign key and losing the row."""
    if tenant_id is None:
        return None
    from sqlalchemy import select
    from app.models.tenant import Tenant

    return select(Tenant.id).where(Tenant.id == tenant_id).scalar_subquery()


def _int(value: Any) -> int:
    # isinstance, not int(): a test's MagicMock usage must read as 0, not blow up.
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


async def record_ai_call(*, feature: str, model: str, usage: Any,
                         duration_ms: int | None = None) -> None:
    """One completed chat completion. `usage` is the SDK's CompletionUsage (or None)."""
    active = _active_scope()
    if active is None:
        return
    from sqlalchemy import insert
    from app.models.usage_meter import AiUsageEvent

    prompt_details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    stmt = insert(AiUsageEvent).values(
        tenant_id=_tenant_value(active.tenant_id),
        user_id=active.user_id,
        feature=(feature or "ai")[:40],
        model=(model or "unknown")[:80],
        prompt_tokens=_int(getattr(usage, "prompt_tokens", 0)),
        cached_prompt_tokens=_int(getattr(prompt_details, "cached_tokens", 0)),
        completion_tokens=_int(getattr(usage, "completion_tokens", 0)),
        reasoning_tokens=_int(getattr(completion_details, "reasoning_tokens", 0)),
        duration_ms=duration_ms,
        created_at=datetime.utcnow(),
    )
    await _execute(stmt, f"AI call ({feature})")


async def record_object_stored(*, storage: str, bucket: str, object_name: str,
                               size_bytes: int, content_type: str | None) -> None:
    """An object now exists at (storage, bucket, object_name). Re-storing the same name
    replaces the row's size and revives it if it had been marked deleted."""
    active = _active_scope()
    if active is None:
        return
    from sqlalchemy.dialects.postgresql import insert
    from app.models.usage_meter import StoredObject

    source, origin = classify(object_name)
    tenant_id = active.tenant_id if active.tenant_id is not None else tenant_from_path(object_name)
    stmt = insert(StoredObject).values(
        tenant_id=_tenant_value(tenant_id),
        user_id=active.user_id,
        storage=storage,
        bucket=bucket or "",
        object_name=object_name,
        source=source,
        origin=origin,
        size_bytes=max(int(size_bytes or 0), 0),
        content_type=(content_type or None) and content_type[:255],
        created_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_stored_objects_location",
        set_={
            "tenant_id": stmt.excluded.tenant_id,
            "user_id": stmt.excluded.user_id,
            "source": stmt.excluded.source,
            "origin": stmt.excluded.origin,
            "size_bytes": stmt.excluded.size_bytes,
            "content_type": stmt.excluded.content_type,
            "created_at": stmt.excluded.created_at,
            "deleted_at": None,
        },
    )
    await _execute(stmt, f"stored object {object_name}")


async def record_object_deleted(*, storage: str, bucket: str, object_name: str) -> None:
    active = _active_scope()
    if active is None:
        return
    from sqlalchemy import update
    from app.models.usage_meter import StoredObject

    stmt = (
        update(StoredObject)
        .where(
            StoredObject.storage == storage,
            StoredObject.bucket == (bucket or ""),
            StoredObject.object_name == object_name,
            StoredObject.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.utcnow())
    )
    await _execute(stmt, f"deleted object {object_name}")
