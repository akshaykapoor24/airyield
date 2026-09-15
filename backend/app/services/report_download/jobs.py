"""The report job lifecycle as the API sees it: create, list, retry, delete, download, purge.

The worker side (claim, heartbeat, build, finalize) is app/workers/report_tasks.py; the two
halves agree on one row, report_exports, and on the rules pinned here:

LIVENESS. A ``queued`` report is never stale — it may legitimately wait behind a 40-minute
build of another workspace, and failing it by age would punish exactly the users a busy
queue already inconveniences. A ``processing`` report is stale once its heartbeat is older
than STALE_AFTER: the worker died, and the UI offers Retry. Every function here that asks
"is it live?" uses ``active_clause`` / ``stale_processing_clause`` so the list chip, the
caps and the worker claim can never disagree.

CAPS. Active reports are capped per user, per workspace and (queued only) globally. The
count and the insert run under a transaction-scoped advisory lock on the WORKSPACE, not the
user: two members of one workspace submitting at the same instant would otherwise both see
"2 active" and both insert, breaking the per-workspace cap the per-user lock cannot see.

READ-ONLY READS. Listing and polling never write. Expiry happens when the worker claims
its next job (``purge_expired``) and, for GCS, through the bucket lifecycle rule — a report
must not wait for someone to open the page before its file is removed.

Errors are raised as HTTPException with a message fit to show the user, like the other
services the API calls directly (statement_supplier_selection, auth_service).
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, status as http
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import settings
from app.core import rate_limit
from app.models.report_export import (
    ERROR_QUEUE_FAILED, STATUS_COMPLETED, STATUS_DELETED, STATUS_EXPIRED, STATUS_FAILED,
    STATUS_PROCESSING, STATUS_QUEUED, ReportExport,
)
from app.models.user import User
from app.schemas.report_download import DisplayStatus, ExportCreate, ExportListItem, ExportRead
from app.services import file_store
from app.services.report_download import storage
from app.services.report_download.types import REPORT_ENGINE_VERSION, ReportOptions
from app.utils.security import create_file_token, verify_file_token

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)
# A queued row's heartbeat_at is stamped at creation / retry and each time a worker finds its
# workspace busy and re-queues it (every ~60 s). Untouched for this long, its Celery message
# was lost (broker restart, no `reports` worker): it stops holding a cap slot and offers Retry.
QUEUED_STUCK_AFTER = timedelta(minutes=15)
FILE_TOKEN_KIND = "report_export"
DOWNLOAD_LINK_MINUTES = 10
# Starting (or retrying) a build is expensive for the whole platform, not just the caller.
EXPORT_RATE_LIMIT = 10
EXPORT_RATE_WINDOW_S = 3600
QUEUE_FULL_RETRY_AFTER_S = 120
_ADVISORY_LOCK_NAMESPACE = "report_export"

RE = ReportExport


# ── status ───────────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    """Naive UTC, the convention of every DateTime column here (models default to
    datetime.utcnow). Always bound from Python, never DB now(), so stale and expiry
    comparisons cannot drift with the database session's time zone."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_stale(heartbeat_at: Optional[datetime], now: datetime) -> bool:
    """A processing heartbeat older than STALE_AFTER (or never written) means a dead worker."""
    return heartbeat_at is None or heartbeat_at < now - STALE_AFTER


def is_stuck_queued(heartbeat_at: Optional[datetime], now: datetime) -> bool:
    """A queued row no worker has touched for QUEUED_STUCK_AFTER lost its message.

    NULL (a row written before queued rows were stamped) is NOT stuck: better a row that
    waits than one that is re-sent while its original message is still in the queue."""
    return heartbeat_at is not None and heartbeat_at < now - QUEUED_STUCK_AFTER


def display_status(
    status: str,
    heartbeat_at: Optional[datetime],
    now: datetime,
    expires_at: Optional[datetime] = None,
) -> DisplayStatus:
    """The chip the history list shows.

    ``expires_at`` makes a completed report read "expired" the moment retention passes, even
    before purge_expired has flipped its status — the download endpoint refuses it by then,
    so "ready" would be a promise the API does not keep.
    """
    if status == STATUS_QUEUED:
        return "stalled" if is_stuck_queued(heartbeat_at, now) else "waiting"
    if status == STATUS_PROCESSING:
        return "stalled" if is_stale(heartbeat_at, now) else "generating"
    if status == STATUS_COMPLETED:
        return "expired" if expires_at is not None and expires_at <= now else "ready"
    if status == STATUS_FAILED:
        return "failed"
    # expired — and deleted, which no endpoint lists but must still map to something.
    return "expired"


def active_clause(now: datetime) -> ColumnElement[bool]:
    """Rows that occupy a slot: queued and not stuck, or processing with a live heartbeat."""
    return or_(
        and_(RE.status == STATUS_QUEUED,
             or_(RE.heartbeat_at.is_(None), RE.heartbeat_at >= now - QUEUED_STUCK_AFTER)),
        and_(RE.status == STATUS_PROCESSING, RE.heartbeat_at >= now - STALE_AFTER),
    )


def stuck_queued_clause(now: datetime) -> ColumnElement[bool]:
    """SQL twin of ``is_stuck_queued``."""
    return and_(RE.status == STATUS_QUEUED, RE.heartbeat_at < now - QUEUED_STUCK_AFTER)


def stale_processing_clause(now: datetime) -> ColumnElement[bool]:
    """SQL twin of ``is_stale`` for processing rows (NULL heartbeat counts as stale)."""
    return and_(
        RE.status == STATUS_PROCESSING,
        or_(RE.heartbeat_at.is_(None), RE.heartbeat_at < now - STALE_AFTER),
    )


def file_token_subject(export_id: int, owner_id: int) -> str:
    """The file-token ``sub`` for one report. Binding the owner means a link minted for one
    user's report can never be replayed against a row that later belongs to someone else."""
    return f"report_export:{export_id}:{owner_id}"


# ── serialisation ────────────────────────────────────────────────────────────

def _item_fields(export: Any, now: datetime, queue_position: Optional[int]) -> dict[str, Any]:
    """ExportListItem fields from an ORM row or a column-tuple Row (same attribute names)."""
    params = export.params or {}
    return {
        "id": export.id,
        "title": export.title,
        "status": export.status,
        "display_status": display_status(export.status, export.heartbeat_at, now, export.expires_at),
        "stage": export.stage,
        "processed_rows": export.processed_rows or 0,
        "estimated_rows": export.estimated_rows or 0,
        "queue_position": queue_position,
        "date_from": params.get("date_from"),
        "date_to": params.get("date_to"),
        "basis": params.get("basis"),
        "source_types": list(params.get("source_types") or []),
        "combined_rows": export.combined_rows,
        "file_size": export.file_size,
        "created_at": export.created_at,
        "completed_at": export.completed_at,
        "expires_at": export.expires_at,
        "error_code": export.error_code,
        "error": export.error,
    }


async def _queue_positions(db: AsyncSession, queued_ids: list[int], now: datetime) -> dict[int, int]:
    """How many reports are ahead of each queued id: queued earlier, plus live builds.

    One round trip whatever the page holds (the per-user cap keeps it to a couple of ids).
    A global figure on purpose — the workers are shared — and only a count, so nothing
    about other workspaces leaks.
    """
    if not queued_ids:
        return {}
    live = func.count().filter(and_(
        RE.status == STATUS_PROCESSING, RE.heartbeat_at >= now - STALE_AFTER))
    ahead = [func.count().filter(and_(RE.status == STATUS_QUEUED, RE.id < i)) for i in queued_ids]
    row = (await db.execute(
        select(live, *ahead).where(RE.status.in_((STATUS_QUEUED, STATUS_PROCESSING)))
    )).one()
    return {i: int(row[0]) + int(row[k + 1]) for k, i in enumerate(queued_ids)}


async def read_model(db: AsyncSession, export: ReportExport) -> ExportRead:
    """The full ExportRead for one owned row."""
    position = await queue_position(db, export)
    return ExportRead(
        **_item_fields(export, utcnow(), position),
        params=export.params or {},
        selection=export.selection or {},
        sheet_row_counts=export.sheet_row_counts,
        summary=export.summary,
        file_name=export.file_name,
    )


# ── guards ───────────────────────────────────────────────────────────────────

def _require_tenant(user: User) -> int:
    if user.tenant_id is None:
        raise HTTPException(
            status_code=http.HTTP_403_FORBIDDEN,
            detail="Report download is only available inside a workspace.",
        )
    return user.tenant_id


async def _rate_limit(user: User) -> None:
    allowed, retry_after = await rate_limit.hit(
        "report-export", str(user.id), EXPORT_RATE_LIMIT, EXPORT_RATE_WINDOW_S)
    if not allowed:
        raise HTTPException(
            status_code=http.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have started a lot of reports in the last hour. Please wait a few minutes and try again.",
            headers={"Retry-After": str(retry_after)},
        )


async def _lock_tenant(db: AsyncSession, tenant_id: int) -> None:
    """Serialise cap checks for one workspace until this transaction ends."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:ns), :tenant_id)"),
        {"ns": _ADVISORY_LOCK_NAMESPACE, "tenant_id": tenant_id},
    )


async def _enforce_caps(db: AsyncSession, tenant_id: int, user_id: int, now: datetime) -> None:
    active = active_clause(now)
    mine, workspace, queued = (await db.execute(
        select(
            func.count().filter(and_(RE.created_by_id == user_id, RE.tenant_id == tenant_id, active)),
            func.count().filter(and_(RE.tenant_id == tenant_id, active)),
            func.count().filter(RE.status == STATUS_QUEUED),
        ).where(or_(RE.tenant_id == tenant_id, RE.status == STATUS_QUEUED))
    )).one()
    if mine >= settings.REPORT_EXPORT_MAX_ACTIVE_PER_USER:
        raise HTTPException(
            status_code=http.HTTP_409_CONFLICT,
            detail=(f"You already have {mine} reports waiting or generating. "
                    "Wait for one to finish, or delete it, before starting another."),
        )
    if workspace >= settings.REPORT_EXPORT_MAX_ACTIVE_PER_TENANT:
        raise HTTPException(
            status_code=http.HTTP_409_CONFLICT,
            detail=(f"Your workspace already has {workspace} reports waiting or generating. "
                    "Try again when one of them finishes."),
        )
    if queued >= settings.REPORT_EXPORT_MAX_QUEUED_GLOBAL:
        raise HTTPException(
            status_code=http.HTTP_429_TOO_MANY_REQUESTS,
            detail="The report queue is full right now. Please try again in a few minutes.",
            headers={"Retry-After": str(QUEUE_FULL_RETRY_AFTER_S)},
        )


async def _enqueue(db: AsyncSession, export: ReportExport) -> None:
    """Hand a committed queued row to Celery; a broker failure marks it failed, visibly.

    The row is committed first so the worker can never be handed an id it cannot see.
    """
    from app.workers.report_tasks import REPORT_QUEUE, generate_report

    try:
        sent = await asyncio.to_thread(generate_report.apply_async, (export.id,), queue=REPORT_QUEUE)
    except Exception:  # noqa: BLE001 — any broker error becomes a visible, retryable failure
        logger.exception("report %s: could not enqueue", export.id)
        await db.execute(
            update(RE).where(RE.id == export.id, RE.status == STATUS_QUEUED).values(
                status=STATUS_FAILED, error_code=ERROR_QUEUE_FAILED,
                error="The report queue is unavailable right now. Please retry in a few minutes.",
                completed_at=utcnow(),
            )
        )
    else:
        # The worker may already have claimed the row and stamped this same id itself.
        await db.execute(update(RE).where(RE.id == export.id).values(celery_task_id=sent.id))
    await db.commit()
    await db.refresh(export)


# ── API operations ───────────────────────────────────────────────────────────

async def create_export(db: AsyncSession, user: User, req: ExportCreate) -> ReportExport:
    """Validate ownership and size, enforce the caps, insert a queued row and enqueue it."""
    from app.services.report_download.selection import SelectionError, estimate, resolve_selection

    tenant_id = _require_tenant(user)
    await _rate_limit(user)
    now = utcnow()

    await _lock_tenant(db, tenant_id)
    conn = await db.connection()
    try:
        sel = await resolve_selection(
            conn, tenant_id, user.id,
            [(r.source_type, r.upload_id) for r in req.included_uploads],
            [(r.source_type, r.upload_id) for r in req.unticked_uploads],
        )
    except SelectionError as exc:
        raise HTTPException(status_code=http.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))

    options = ReportOptions(
        basis=req.basis,
        bsp_scope=req.bsp_scope,
        include_detail_sheets=req.options.include_detail_sheets,
        include_pii=req.options.include_pii,
        undated_rows=req.options.undated_rows,
    )
    rows, cells = estimate(sel, options)
    if rows > settings.REPORT_EXPORT_MAX_ROWS or cells > settings.REPORT_EXPORT_MAX_CELLS:
        raise HTTPException(
            status_code=http.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(f"This selection is too large for one report (about {rows:,} rows; the limit is "
                    f"{settings.REPORT_EXPORT_MAX_ROWS:,}). Narrow the period, untick some files "
                    "or turn off detail sheets."),
        )

    await _enforce_caps(db, tenant_id, user.id, now)

    export = ReportExport(
        tenant_id=tenant_id,
        created_by_id=user.id,
        title=req.title,
        status=STATUS_QUEUED,
        heartbeat_at=now,          # queued rows are stamped; see QUEUED_STUCK_AFTER
        params={
            "date_from": req.date_from.isoformat(),
            "date_to": req.date_to.isoformat(),
            "basis": req.basis,
            "bsp_scope": req.bsp_scope,
            "source_types": list(req.source_types),
            "options": req.options.model_dump(),
        },
        selection={
            "included": [
                {
                    "source_type": u.source_key,
                    "upload_id": u.upload_id,
                    "file_name": u.file_name,
                    "uploaded_at": u.uploaded_at.isoformat() if u.uploaded_at else None,
                    "total_rows": u.total_rows,
                }
                for u in sel.uploads
            ],
            "unticked": [
                {"source_type": u.source_key, "upload_id": u.upload_id, "file_name": u.file_name}
                for u in sel.unticked
            ],
        },
        engine_version=REPORT_ENGINE_VERSION,
        storage_key=secrets.token_urlsafe(24),
        estimated_rows=rows,
        created_at=now,
    )
    db.add(export)
    await db.commit()   # also releases the advisory lock
    await db.refresh(export)
    await _enqueue(db, export)
    return export


async def list_exports(
    db: AsyncSession, user: User, limit: int, offset: int,
) -> tuple[list[ExportListItem], int]:
    """One page of the caller's history, newest first. Never writes.

    Selects only list columns: this runs every 3 s while a report is active, and
    ``selection`` / ``summary`` can be tens of KB each.
    """
    tenant_id = _require_tenant(user)
    now = utcnow()
    owned = and_(RE.tenant_id == tenant_id, RE.created_by_id == user.id, RE.status != STATUS_DELETED)

    total = int(await db.scalar(select(func.count()).select_from(RE).where(owned)) or 0)
    rows = (await db.execute(
        select(
            RE.id, RE.title, RE.status, RE.stage, RE.processed_rows, RE.estimated_rows,
            RE.params, RE.combined_rows, RE.file_size, RE.created_at, RE.completed_at,
            RE.expires_at, RE.heartbeat_at, RE.error_code, RE.error,
        )
        .where(owned)
        .order_by(RE.created_at.desc(), RE.id.desc())
        .limit(limit)
        .offset(offset)
    )).all()
    positions = await _queue_positions(db, [r.id for r in rows if r.status == STATUS_QUEUED], now)
    return [ExportListItem(**_item_fields(r, now, positions.get(r.id))) for r in rows], total


async def get_owned_export(db: AsyncSession, user: User, export_id: int) -> ReportExport:
    """The caller's own report, or 404 — also for deleted rows and other users' ids."""
    tenant_id = _require_tenant(user)
    export = await db.scalar(
        select(RE).where(
            RE.id == export_id,
            RE.tenant_id == tenant_id,
            RE.created_by_id == user.id,
            RE.status != STATUS_DELETED,
        )
    )
    if export is None:
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="Report not found.")
    return export


async def queue_position(db: AsyncSession, export: ReportExport) -> Optional[int]:
    """Reports ahead of a queued report; None for any other status."""
    if export.status != STATUS_QUEUED:
        return None
    return (await _queue_positions(db, [export.id], utcnow())).get(export.id)


async def retry_export(db: AsyncSession, user: User, export: ReportExport) -> ReportExport:
    """Re-queue a failed or stalled report with its original params and selection.

    "Stalled" is a processing row whose worker went quiet, or a queued row whose message was
    lost. The attempt counter is NOT reset: a stalled worker that wakes up later still holds
    the old attempt, so its heartbeat and finalize match nothing (the next claim bumps it).
    """
    tenant_id = _require_tenant(user)
    now = utcnow()
    retryable = (
        export.status == STATUS_FAILED
        or (export.status == STATUS_PROCESSING and is_stale(export.heartbeat_at, now))
        or (export.status == STATUS_QUEUED and is_stuck_queued(export.heartbeat_at, now))
    )
    if not retryable:
        raise HTTPException(
            status_code=http.HTTP_409_CONFLICT,
            detail="Only a failed or stalled report can be retried.",
        )
    await _rate_limit(user)
    await _lock_tenant(db, tenant_id)
    await _enforce_caps(db, tenant_id, user.id, now)

    requeued = (await db.execute(
        update(RE)
        .where(RE.id == export.id,
               or_(RE.status == STATUS_FAILED, stale_processing_clause(now), stuck_queued_clause(now)))
        .values(
            status=STATUS_QUEUED, stage=None, processed_rows=0, error=None, error_code=None,
            celery_task_id=None, started_at=None, heartbeat_at=now, completed_at=None,
        )
        .returning(RE.id)
    )).first()
    if requeued is None:
        await db.rollback()
        raise HTTPException(
            status_code=http.HTTP_409_CONFLICT,
            detail="This report changed while you were retrying it. Refresh and try again.",
        )
    await db.commit()
    await db.refresh(export)
    await _enqueue(db, export)
    return export


async def delete_export(db: AsyncSession, user: User, export: ReportExport) -> None:
    """Soft delete: keep the audit row, purge the file now.

    The locator is read under a row lock in the same transaction as the update, so a worker
    finalizing at that moment either commits first (and we purge the file it just stored) or
    loses its fence (and deletes the file itself). A running build stops at its next
    heartbeat, when its fenced update finds the row no longer processing.
    """
    _require_tenant(user)
    current = (await db.execute(
        select(RE.file_locator, RE.storage_bucket)
        .where(RE.id == export.id, RE.status != STATUS_DELETED)
        .with_for_update()
    )).first()
    if current is None:
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="Report not found.")
    await db.execute(
        update(RE).where(RE.id == export.id).values(
            status=STATUS_DELETED, deleted_at=utcnow(), file_locator=None, stage=None)
    )
    await db.commit()
    await _purge_file(export.id, current.file_locator, current.storage_bucket)


async def download_url(export: ReportExport, stream_url: str) -> str:
    """A short-lived URL for a completed report: GCS signed, or a token link to stream_url."""
    now = utcnow()
    if export.status == STATUS_EXPIRED or (
            export.status == STATUS_COMPLETED and export.expires_at is not None
            and export.expires_at <= now):
        raise HTTPException(
            status_code=http.HTTP_410_GONE,
            detail="This report has expired. Run it again to download a fresh copy.",
        )
    if export.status != STATUS_COMPLETED or not export.file_locator:
        raise HTTPException(
            status_code=http.HTTP_409_CONFLICT,
            detail="This report is not ready to download yet.",
        )
    try:
        url = await file_store.signed_url(
            export.file_locator, export.storage_bucket or "",
            expiry_minutes=DOWNLOAD_LINK_MINUTES, inline=False,
        )
    except Exception:  # noqa: BLE001 — credentials / network; the details belong in the log
        logger.exception("report %s: could not sign a download URL", export.id)
        raise HTTPException(
            status_code=http.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The download link could not be created. Please try again shortly.",
        )
    if url is None:
        token = create_file_token(
            file_token_subject(export.id, export.created_by_id), FILE_TOKEN_KIND, DOWNLOAD_LINK_MINUTES)
        url = f"{stream_url}?token={token}"
    return url


async def open_local_file(db: AsyncSession, export_id: int, token: str) -> tuple[Path, str]:
    """Authorise a token link and return (path, download name) for a locally stored report.

    The token is checked before anything about the row is revealed: a missing row and a bad
    token get the same 403, so the endpoint is no oracle for which ids exist.
    """
    export = await db.scalar(select(RE).where(RE.id == export_id))
    if export is None or export.status == STATUS_DELETED or not verify_file_token(
            token, file_token_subject(export.id, export.created_by_id), FILE_TOKEN_KIND):
        raise HTTPException(status_code=http.HTTP_403_FORBIDDEN, detail="Invalid or expired download link.")
    now = utcnow()
    if export.status == STATUS_EXPIRED or (export.expires_at is not None and export.expires_at <= now):
        raise HTTPException(
            status_code=http.HTTP_410_GONE,
            detail="This report has expired. Run it again to download a fresh copy.",
        )
    if export.status != STATUS_COMPLETED or not file_store.is_local(export.file_locator):
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="This report file is not available here.")
    path = file_store.local_path(export.file_locator, storage.local_root())
    if not path.is_file():
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="The stored report file is no longer available.")
    return path, export.file_name or path.name


# ── housekeeping (worker) ────────────────────────────────────────────────────

async def _purge_file(export_id: int, locator: Optional[str], bucket: Optional[str]) -> None:
    """Best-effort removal of one stored report; failures are logged, never raised."""
    if not locator:
        return
    try:
        root = storage.local_root() if file_store.is_local(locator) else None
        await file_store.delete(locator, bucket or "", local_root=root)
    except Exception:  # noqa: BLE001 — an orphan is left to the lifecycle rule, not to the user
        logger.warning("report %s: could not remove stored file %s", export_id, locator, exc_info=True)


async def purge_expired(conn: AsyncConnection, now: datetime, limit: int = 50) -> int:
    """Expire completed reports past retention and delete their files. Cross-tenant.

    Commits on ``conn`` (and leaves it with no open transaction). Rows are taken with
    SKIP LOCKED so two workers purging at once split the work instead of queueing on each
    other, and files are deleted only after the status change commits — a crash in between
    leaves an orphan object for the lifecycle rule, never an ``expired`` row whose file
    still downloads.
    """
    due = (await conn.execute(
        select(RE.id, RE.file_locator, RE.storage_bucket)
        .where(RE.status == STATUS_COMPLETED, RE.expires_at <= now)
        .order_by(RE.expires_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )).all()
    if due:
        await conn.execute(
            update(RE)
            .where(RE.id.in_([r.id for r in due]), RE.status == STATUS_COMPLETED)
            .values(status=STATUS_EXPIRED, file_locator=None)
        )
    await conn.commit()
    for r in due:
        await _purge_file(r.id, r.file_locator, r.storage_bucket)
    return len(due)
