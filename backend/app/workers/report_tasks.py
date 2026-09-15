"""Celery task that builds one Workspace → Report download workbook.

Takes a report_exports id. The API committed the row as ``queued`` before enqueueing, so the
row — not the Celery message — is the source of truth, and everything here is written to
survive the ways a message and a row drift apart:

  DUPLICATE OR LATE DELIVERY. The claim is one conditional UPDATE (queued, or processing with
  a dead heartbeat) that bumps ``attempt``. A second copy of the message claims nothing and
  exits. Every later write carries ``WHERE attempt = :claimed``.

  DELETE / RETRY WHILE RUNNING. A heartbeat every 20 s re-asserts ``processing`` for this
  attempt; when it matches no row the user deleted or retried the report, the build is told to
  stop, and the finalize (also fenced) would lose anyway — in which case the file it stored is
  deleted rather than orphaned.

  ONE BUILD PER WORKSPACE. A claim is refused while another report of the same workspace is
  live, and the message re-queues itself a minute later, so one workspace cannot occupy every
  worker slot.

  NO AUTOMATIC RETRY. A build that failed on its data fails the same way again, and a worker
  that died is visible as "stalled" — the user decides, with the Retry button. With
  acks_late and the default reject_on_worker_lost, a killed worker's message is not
  redelivered.

  TIME. Celery's soft limit raises SoftTimeLimitExceeded, which subclasses Exception and can be
  swallowed by any broad ``except`` deep in a mapper; and time limits do not work at all under
  the Windows ``--pool=solo`` dev worker. So the build also carries a cooperative deadline that
  ``BuildState.tick`` enforces between chunks.

  DISK. openpyxl's write-only mode spools every sheet to a temp file in tempfile's directory.
  Each build gets its own temp directory (removed in ``finally``; a crashed build's leftovers
  are swept on a later run), and a free-space check runs before any work starts.

Run a worker with:
    celery -A app.workers.celery_app.celery_app worker -l info -Q reports -c 1 --max-tasks-per-child=1
    (add --pool=solo on Windows dev)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from celery.exceptions import SoftTimeLimitExceeded

from app.workers.celery_app import celery_app

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)

REPORT_QUEUE = "reports"
SOFT_TIME_LIMIT_S = 45 * 60
HARD_TIME_LIMIT_S = 48 * 60
# Below the soft limit, so a slow build fails through our own fenced path with a clean
# message and temp-dir cleanup, not through a signal landing somewhere arbitrary.
BUILD_DEADLINE_S = 40 * 60
HEARTBEAT_INTERVAL_S = 20
TENANT_BUSY_COUNTDOWN_S = 60
TEMP_PREFIX = "ayreport-"
TEMP_SWEEP_AGE_S = 6 * 60 * 60
# Free-space estimate: spooled sheet XML plus the zipped copy written at save, per row, with
# headroom. Doubled when detail sheets repeat every row in its native layout.
DISK_BYTES_PER_ROW = 6_000
DISK_HEADROOM = 1.2

TIMEOUT_MESSAGE = (
    "The report took too long to build. Narrow the period, untick some files "
    "or turn off detail sheets, then try again."
)
ACCOUNT_INACTIVE_MESSAGE = "Your account or workspace is not active, so this report was not generated."
DISK_MESSAGE = "The report server is short of disk space. Please try again later or narrow the period."
STORAGE_MESSAGE = "The finished report could not be stored. Please retry."


@dataclass
class _RunState:
    """What the synchronous task wrapper needs to know about an async run that escaped."""
    attempt: Optional[int] = None


@dataclass(frozen=True)
class _Claim:
    id: int
    attempt: int
    tenant_id: int
    created_by_id: int
    params: dict
    selection: dict
    storage_key: str
    title: Optional[str]
    estimated_rows: int


@dataclass(frozen=True)
class _Owner:
    name: Optional[str]
    email: Optional[str]
    tenant_name: Optional[str]


@dataclass(frozen=True)
class _StoredRef:
    """storage.StoredExportRef for a claimed row, once its file name is known."""
    id: int
    tenant_id: int
    created_by_id: int
    storage_key: str
    file_name: str


class _StorageFailed(Exception):
    """The workbook was built but could not be stored anywhere."""


@celery_app.task(
    # ignore_result: nothing reads the task result (the row is the state), and without it a
    # publish with Redis down blocks ~110 s in the result backend before failing.
    bind=True, acks_late=True, queue=REPORT_QUEUE, ignore_result=True,
    soft_time_limit=SOFT_TIME_LIMIT_S, time_limit=HARD_TIME_LIMIT_S,
)
def generate_report(self, export_id: int) -> None:
    run = _RunState()
    try:
        asyncio.run(_run(export_id, self.request.id, run))
    except SoftTimeLimitExceeded:
        # Landed outside the build's own handlers (e.g. in the event loop machinery).
        logger.error("report %s hit the soft time limit outside the build", export_id)
        if run.attempt is not None:
            from app.models.report_export import ERROR_TIMEOUT
            asyncio.run(_fail(export_id, run.attempt, ERROR_TIMEOUT, TIMEOUT_MESSAGE))
    except Exception:  # noqa: BLE001 — logged, never retried (see module docstring)
        logger.exception("report %s crashed outside the build", export_id)


def _utcnow() -> datetime:
    from app.services.report_download.jobs import utcnow
    return utcnow()


def _json_safe(value: Any) -> Any:
    """Round-trip through JSON so a stray Decimal or date cannot fail a finished build at the
    last write — the JSONB columns serialise with plain json.dumps."""
    return json.loads(json.dumps(value, default=str)) if value is not None else None


async def _fail(
    export_id: int, attempt: int, code: str, message: str, *, engine: "AsyncEngine | None" = None,
) -> None:
    """Record a failure for THIS attempt only. Never raises: a failure to record a failure
    must not replace the original error in the log.

    Only a row still ``processing`` is touched. Every call follows a successful claim, and a
    Retry puts the row back to ``queued`` WITHOUT changing ``attempt`` — so matching queued
    rows too would let a slow old build fail the user's retry before its worker ever sees it.
    """
    from sqlalchemy import update
    from app.models.report_export import STATUS_FAILED, STATUS_PROCESSING, ReportExport as RE

    own_engine = engine is None
    if own_engine:
        engine = _new_engine()
    try:
        async with engine.begin() as c:
            await c.execute(
                update(RE)
                .where(RE.id == export_id, RE.attempt == attempt, RE.status == STATUS_PROCESSING)
                .values(status=STATUS_FAILED, error_code=code, error=message[:500],
                        completed_at=_utcnow())
            )
    except Exception:  # noqa: BLE001
        logger.exception("report %s: could not record failure %s", export_id, code)
    finally:
        if own_engine:
            with suppress(Exception):
                await engine.dispose()


def _new_engine() -> "AsyncEngine":
    """Fresh NullPool engine: the API's pooled asyncpg connections are bound to another loop."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from app.config import settings

    return create_async_engine(settings.DATABASE_URL, poolclass=NullPool)


def _sweep_stale_temp_dirs() -> None:
    """Remove ayreport-* directories a crashed or killed build left behind."""
    cutoff = time.time() - TEMP_SWEEP_AGE_S
    try:
        with os.scandir(tempfile.gettempdir()) as entries:
            for entry in entries:
                if (entry.name.startswith(TEMP_PREFIX) and entry.is_dir(follow_symlinks=False)
                        and entry.stat(follow_symlinks=False).st_mtime < cutoff):
                    shutil.rmtree(entry.path, ignore_errors=True)
    except OSError:
        logger.warning("report temp sweep failed", exc_info=True)


async def _housekeeping(conn: "AsyncConnection") -> None:
    from app.services.report_download import jobs

    try:
        purged = await jobs.purge_expired(conn, _utcnow())
        if purged:
            logger.info("expired %d report(s)", purged)
    except Exception:  # noqa: BLE001 — housekeeping must never block the build it precedes
        logger.warning("report purge failed", exc_info=True)
        with suppress(Exception):
            await conn.rollback()
    await asyncio.to_thread(_sweep_stale_temp_dirs)


def claim_statement(export_id: int, task_id: Optional[str], now: datetime):
    """The claim UPDATE … RETURNING for one report (pure; compiled in tests).

    Claimable: queued, or processing with a dead heartbeat. Refused while another report of
    the same workspace is live. Bumps ``attempt``, which fences every write of any older
    attempt still running somewhere.
    """
    from sqlalchemy import exists, or_, select, update
    from sqlalchemy.orm import aliased
    from app.models.report_export import STATUS_PROCESSING, STATUS_QUEUED, ReportExport as RE
    from app.services.report_download import jobs

    other = aliased(RE)
    tenant_busy = exists(
        select(other.id).where(
            other.tenant_id == RE.tenant_id,
            other.id != export_id,
            other.status == STATUS_PROCESSING,
            other.heartbeat_at >= now - jobs.STALE_AFTER,
        )
    )
    return (
        update(RE)
        .where(RE.id == export_id,
               or_(RE.status == STATUS_QUEUED, jobs.stale_processing_clause(now)),
               ~tenant_busy)
        .values(status=STATUS_PROCESSING, attempt=RE.attempt + 1, started_at=now,
                heartbeat_at=now, processed_rows=0, stage="Starting", celery_task_id=task_id,
                error=None, error_code=None, completed_at=None)
        .returning(RE.attempt, RE.tenant_id, RE.created_by_id, RE.params, RE.selection,
                   RE.storage_key, RE.title, RE.estimated_rows)
    )


async def _claim(conn: "AsyncConnection", export_id: int, task_id: Optional[str]) -> Optional[_Claim]:
    """Take the row for this attempt, or None (duplicate delivery, deleted, done, or busy).

    The workspace lock closes the gap in the NOT EXISTS check: two workers claiming two
    reports of one workspace at the same instant would each miss the other's uncommitted
    claim and both start.
    """
    from sqlalchemy import select, text
    from app.models.report_export import ReportExport as RE

    tenant_id = await conn.scalar(select(RE.tenant_id).where(RE.id == export_id))
    if tenant_id is None:
        await conn.commit()
        return None
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('report_export_claim'), :tenant_id)"),
        {"tenant_id": tenant_id},
    )
    row = (await conn.execute(claim_statement(export_id, task_id, _utcnow()))).first()
    await conn.commit()
    if row is None:
        return None
    return _Claim(
        id=export_id, attempt=row.attempt, tenant_id=row.tenant_id,
        created_by_id=row.created_by_id, params=row.params, selection=row.selection,
        storage_key=row.storage_key, title=row.title, estimated_rows=row.estimated_rows or 0,
    )


async def _requeue_if_waiting(conn: "AsyncConnection", export_id: int) -> None:
    """An unclaimed row still ``queued`` means its workspace is busy: try again later.

    Stamps ``heartbeat_at`` on the queued row each time, so "a worker has seen this recently"
    is visible to the API: a queued row nobody has touched for ``QUEUED_STUCK_AFTER`` lost
    its message and is offered a Retry instead of holding a slot forever (jobs.is_stuck_queued).
    """
    from sqlalchemy import update
    from app.models.report_export import (
        ERROR_QUEUE_FAILED, STATUS_FAILED, STATUS_QUEUED, ReportExport as RE,
    )

    touched = (await conn.execute(
        update(RE).where(RE.id == export_id, RE.status == STATUS_QUEUED)
        .values(heartbeat_at=_utcnow()).returning(RE.id)
    )).first()
    await conn.commit()
    if touched is None:
        logger.info("report %s: nothing to claim (no longer queued)", export_id)
        return
    logger.info("report %s: workspace busy, re-queued in %ss", export_id, TENANT_BUSY_COUNTDOWN_S)
    try:
        generate_report.apply_async((export_id,), queue=REPORT_QUEUE, countdown=TENANT_BUSY_COUNTDOWN_S)
    except Exception:  # noqa: BLE001 — a lost re-queue must be visible, not a silent forever-wait
        logger.exception("report %s: could not re-queue", export_id)
        await conn.execute(
            update(RE).where(RE.id == export_id, RE.status == STATUS_QUEUED).values(
                status=STATUS_FAILED, error_code=ERROR_QUEUE_FAILED,
                error="The report queue is unavailable right now. Please retry in a few minutes.",
                completed_at=_utcnow(),
            )
        )
        await conn.commit()


async def _active_owner(conn: "AsyncConnection", claim: _Claim) -> Optional[_Owner]:
    """The requesting user if they are still active, in the same workspace, on a live plan.

    A report can wait in the queue for a long time; the request-time check is not enough.
    """
    from sqlalchemy import select
    from app.models.tenant import Tenant
    from app.models.user import User

    row = (await conn.execute(
        select(User.is_active, User.tenant_id, User.full_name, User.email,
               Tenant.name.label("tenant_name"), Tenant.plan_status, Tenant.plan_expires_at)
        .select_from(User)
        .outerjoin(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == claim.created_by_id)
    )).first()
    await conn.commit()
    if row is None or not row.is_active or row.tenant_id != claim.tenant_id:
        return None
    # A transient Tenant reuses the one definition of "may use the product".
    if not Tenant(plan_status=row.plan_status, plan_expires_at=row.plan_expires_at).has_active_plan:
        return None
    return _Owner(name=row.full_name, email=row.email, tenant_name=row.tenant_name)


async def _heartbeat(hb_conn: "AsyncConnection", export_id: int, attempt: int, state: Any) -> None:
    """Publish progress every HEARTBEAT_INTERVAL_S on its own connection; stop the build
    (``state.cancelled``) when the fenced update no longer matches the row.

    A transient DB error is logged and retried on the next beat: if it persists, the row goes
    stale and a Retry's new attempt fences this build out anyway.
    """
    from sqlalchemy import update
    from app.models.report_export import STATUS_PROCESSING, ReportExport as RE

    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        try:
            result = await hb_conn.execute(
                update(RE)
                .where(RE.id == export_id, RE.status == STATUS_PROCESSING, RE.attempt == attempt)
                .values(processed_rows=state.processed, stage=(state.stage or "")[:120] or None,
                        heartbeat_at=_utcnow())
            )
            await hb_conn.commit()
        except Exception:  # noqa: BLE001
            logger.warning("report %s: heartbeat failed", export_id, exc_info=True)
            with suppress(Exception):
                await hb_conn.rollback()
            continue
        if result.rowcount == 0:
            logger.info("report %s: deleted or taken over; stopping attempt %s", export_id, attempt)
            state.cancelled = True
            return


async def _stop(task: "asyncio.Task[None] | None") -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await task


async def _finalize(
    conn: "AsyncConnection", claim: _Claim, *, file_name: str, locator: str, remote: bool,
    bucket: str, file_size: int, result: Any, processed: int,
) -> bool:
    """Mark the report completed for this attempt. False when the fence lost."""
    from sqlalchemy import update
    from app.config import settings
    from app.models.report_export import STATUS_COMPLETED, STATUS_PROCESSING, ReportExport as RE

    now = _utcnow()
    row = (await conn.execute(
        update(RE)
        .where(RE.id == claim.id, RE.status == STATUS_PROCESSING, RE.attempt == claim.attempt)
        .values(
            status=STATUS_COMPLETED, stage="Done", processed_rows=processed,
            file_locator=locator, file_name=file_name, file_size=file_size,
            stored_remotely=remote, storage_bucket=bucket if remote else "",
            sheet_row_counts=_json_safe(result.sheet_row_counts),
            summary=_json_safe(result.summary),
            combined_rows=result.combined_rows,
            completed_at=now, heartbeat_at=now,
            expires_at=now + timedelta(days=settings.REPORT_EXPORT_RETENTION_DAYS),
        )
        .returning(RE.id)
    )).first()
    await conn.commit()
    return row is not None


async def _run(export_id: int, task_id: Optional[str], run: _RunState) -> None:
    import app.models  # noqa: F401 — every mapper registered before any ORM class is used
    from app.models import report_export as rx
    from app.services import file_store
    from app.services.report_download import storage
    from app.services.report_download.types import Period, ReportMeta, ReportOptions

    engine = _new_engine()
    conn: "AsyncConnection | None" = None
    hb_conn: "AsyncConnection | None" = None
    hb_task: "asyncio.Task[None] | None" = None
    result: Any = None
    tmpdir: Optional[str] = None
    saved_tempdir = tempfile.tempdir
    # The builder's exception types are only importable once its module loads, which happens
    # after the claim (so a broken import fails the report visibly instead of leaving it
    # queued). `except` evaluates these tuples when an exception arrives, not at def time.
    cancelled_errors: tuple[type[BaseException], ...] = ()
    timeout_errors: tuple[type[BaseException], ...] = (SoftTimeLimitExceeded,)
    selection_errors: tuple[type[BaseException], ...] = ()
    claim: Optional[_Claim] = None
    try:
        conn = await engine.connect()
        await _housekeeping(conn)
        claim = await _claim(conn, export_id, task_id)
        if claim is None:
            await _requeue_if_waiting(conn, export_id)
            return
        run.attempt = claim.attempt
        logger.info("report %s: claimed attempt %s", export_id, claim.attempt)

        owner = await _active_owner(conn, claim)
        if owner is None:
            await _fail(export_id, claim.attempt, rx.ERROR_ACCOUNT_INACTIVE, ACCOUNT_INACTIVE_MESSAGE, engine=engine)
            return

        from app.services.report_download import builder, selection
        cancelled_errors = (builder.ReportCancelled,)
        timeout_errors = (builder.ReportTimeout, SoftTimeLimitExceeded)
        selection_errors = (selection.SelectionError,)

        params = claim.params
        date_from = date.fromisoformat(params["date_from"])
        date_to = date.fromisoformat(params["date_to"])
        opts = params.get("options") or {}
        options = ReportOptions(
            basis=params.get("basis", "transaction"),
            bsp_scope=params.get("bsp_scope", "whole_statement"),
            include_detail_sheets=bool(opts.get("include_detail_sheets", True)),
            include_pii=bool(opts.get("include_pii", False)),
            undated_rows=opts.get("undated_rows", "include"),
        )

        tmpdir = tempfile.mkdtemp(prefix=f"{TEMP_PREFIX}{export_id}-")
        tempfile.tempdir = tmpdir   # openpyxl spools write-only sheets via tempfile
        # estimated_rows already counts the detail-sheet copy (selection.estimate doubles it).
        needed = int(claim.estimated_rows * DISK_BYTES_PER_ROW * DISK_HEADROOM)
        free = shutil.disk_usage(tmpdir).free
        if free <= needed:
            logger.error("report %s: %d bytes free in %s, estimate needs %d", export_id, free, tmpdir, needed)
            await _fail(export_id, claim.attempt, rx.ERROR_STORAGE, DISK_MESSAGE, engine=engine)
            return

        state = builder.BuildState(stage="Starting", deadline=time.monotonic() + BUILD_DEADLINE_S)
        hb_conn = await engine.connect()
        hb_task = asyncio.create_task(_heartbeat(hb_conn, export_id, claim.attempt, state))

        state.tick(stage="Checking uploads")
        sel = await selection.resolve_selection(
            conn, claim.tenant_id, claim.created_by_id,
            [(u["source_type"], u["upload_id"]) for u in claim.selection.get("included") or []],
            [(u["source_type"], u["upload_id"]) for u in claim.selection.get("unticked") or []],
        )
        await conn.commit()   # hand the builder an idle connection

        meta = ReportMeta(
            export_id=export_id, title=claim.title, generated_at=_utcnow(),
            generated_by_name=owner.name, generated_by_email=owner.email,
            tenant_name=owner.tenant_name, period=Period(date_from, date_to), options=options,
            source_types=tuple(params.get("source_types") or ()),
        )
        file_name = storage.export_file_name(export_id, date_from, date_to)
        path = os.path.join(tmpdir, file_name)
        result = await builder.build_report(conn, sel, params, meta, path, state)
        if conn.in_transaction():
            await conn.commit()

        state.tick(stage="Saving workbook")
        await asyncio.to_thread(result.workbook.save)
        file_size = os.path.getsize(path)
        if state.cancelled:
            raise builder.ReportCancelled()

        state.stage = "Storing file"
        bucket = storage.reports_bucket()
        local_root = None
        try:
            local_root = storage.local_root()
            blob = storage.blob_name(_StoredRef(
                id=export_id, tenant_id=claim.tenant_id, created_by_id=claim.created_by_id,
                storage_key=claim.storage_key, file_name=file_name))
            # No silent local fallback when a bucket is configured: the API may run on another
            # host than this worker, so a workbook on this disk would be a "ready" report that
            # 404s. A GCS outage fails the report instead, and Retry stores it once GCS is back.
            locator, remote = await file_store.store_path(
                path, blob, storage.XLSX_MEDIA_TYPE, bucket, local_root=local_root,
                fallback_local=not bucket)
        except SoftTimeLimitExceeded:
            raise   # a timeout, not a storage fault
        except Exception as exc:
            raise _StorageFailed() from exc

        await _stop(hb_task)
        hb_task = None
        try:
            won = await _finalize(
                conn, claim, file_name=file_name, locator=locator, remote=remote, bucket=bucket,
                file_size=file_size, result=result, processed=state.processed)
        except Exception:
            await file_store.delete(locator, bucket if remote else "", local_root=local_root)
            raise
        if won:
            logger.info("report %s: completed (%d bytes, %s)", export_id, file_size,
                        "gcs" if remote else "local")
        else:
            logger.info("report %s: finished after being deleted or taken over; removing its file", export_id)
            await file_store.delete(locator, bucket if remote else "", local_root=local_root)

    except _StorageFailed:
        logger.exception("report %s: could not store the workbook", export_id)
        await _fail(export_id, claim.attempt, rx.ERROR_STORAGE, STORAGE_MESSAGE, engine=engine)
    except cancelled_errors:
        logger.info("report %s: cancelled (row deleted or superseded)", export_id)
    except timeout_errors:
        logger.warning("report %s: timed out", export_id)
        if claim is not None:
            await _fail(export_id, claim.attempt, rx.ERROR_TIMEOUT, TIMEOUT_MESSAGE, engine=engine)
    except selection_errors as exc:
        logger.info("report %s: selection no longer valid: %s", export_id, exc)
        await _fail(export_id, claim.attempt, rx.ERROR_BUILD,
                    f"The uploads in this report changed since it was requested: {exc}", engine=engine)
    except Exception:
        logger.exception("report %s: build failed", export_id)
        if claim is not None:
            await _fail(export_id, claim.attempt, rx.ERROR_BUILD,
                        f"The report could not be built. Reference #{export_id}.", engine=engine)
    finally:
        await _stop(hb_task)
        if result is not None:
            with suppress(Exception):
                result.workbook.discard()
        tempfile.tempdir = saved_tempdir
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        for c in (hb_conn, conn):
            if c is not None:
                with suppress(Exception):
                    await c.close()
        with suppress(Exception):
            await engine.dispose()
