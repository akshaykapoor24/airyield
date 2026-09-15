"""One generated Workspace → Report download workbook, from request to expiry.

THE ROW IS THE JOB. The API inserts it as ``queued`` and commits BEFORE handing the id to
Celery (workers/report_tasks.py), so a broker that never delivers leaves a visible row, and
the task has a natural idempotency key. Every later write is fenced:

  * the worker claims with ``attempt = attempt + 1`` and every heartbeat / finalize / fail
    it issues carries ``WHERE attempt = :claimed``. A Retry, a delete, or a second worker
    that took over a stalled build bumps or changes the row, so the stale worker's writes
    match nothing and it stops at its next heartbeat instead of overwriting a newer run;
  * ``status`` is the only lifecycle field, guarded by a CHECK constraint so a typo in a
    raw UPDATE cannot invent a state no screen knows how to show.

WHY A RANDOM ``storage_key``. The stored object's path embeds it
(``reports/{tenant}/{user}/{id}-{storage_key}/{file}``), so knowing a report id is not
enough to guess where its file lives — a report holds every PNR and passenger name the
user uploaded.

SOFT DELETE. ``deleted`` rows keep the audit trail (who generated what, when) while the
file itself is purged immediately; list and detail endpoints hide them.

No foreign key points at any statement table: the selection is a snapshot in ``selection``
JSONB, and deleting an upload must never be blocked by, or cascade into, report history.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    SmallInteger, String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# The lifecycle, in order. `expired` is set by jobs.purge_expired once retention passes;
# `deleted` by the user. Kept as plain strings (not an Enum type) so adding a state is a
# CHECK-constraint migration, not an ALTER TYPE.
STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"
STATUS_DELETED = "deleted"
STATUSES: tuple[str, ...] = (
    STATUS_QUEUED, STATUS_PROCESSING, STATUS_COMPLETED,
    STATUS_FAILED, STATUS_EXPIRED, STATUS_DELETED,
)
STATUS_CHECK_SQL = "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")"

# error_code vocabulary. The code is for the UI and support; `error` holds only a message
# that is safe to show the user — internals go to the worker log, never into the row.
# A cancelled build (row deleted or retried) writes nothing, and "stalled" is derived from
# the heartbeat at read time, so neither has a code.
ERROR_QUEUE_FAILED = "QUEUE_FAILED"
ERROR_TIMEOUT = "TIMEOUT"
ERROR_BUILD = "BUILD_ERROR"
ERROR_STORAGE = "STORAGE_ERROR"
ERROR_ACCOUNT_INACTIVE = "ACCOUNT_INACTIVE"


class ReportExport(Base):
    __tablename__ = "report_exports"
    __table_args__ = (
        CheckConstraint(STATUS_CHECK_SQL, name="ck_report_exports_status"),
        # The history list: one user's reports, newest first.
        Index("ix_report_exports_owner_created", "tenant_id", "created_by_id", "created_at"),
        # Caps and the worker claim: live `processing` rows by heartbeat.
        Index("ix_report_exports_status_heartbeat", "status", "heartbeat_at"),
        # purge_expired: completed rows past retention.
        Index("ix_report_exports_status_expires", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # No ondelete: SET NULL would orphan a row that still names a stored file, and the
    # tenant-deletion registry pulls this table in with the users group instead.
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=STATUS_QUEUED, server_default=STATUS_QUEUED)
    stage: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # What was asked for — {date_from, date_to, basis, bsp_scope, source_types[], options{…}} —
    # exactly the dict builder.build_report receives, so a Retry rebuilds the same report.
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The uploads resolved at request time: {included:[{source_type, upload_id, file_name,
    # uploaded_at, total_rows}], unticked:[{source_type, upload_id, file_name}]}.
    selection: Mapped[dict] = mapped_column(JSONB, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0")

    estimated_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0")
    processed_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0")
    # Rows on the Combined sheet(s). A column rather than a key inside `summary` so the
    # history list can show it without reading the (up to ~50 KB) summary document.
    combined_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet_row_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    storage_key: Mapped[str] = mapped_column(String(40), nullable=False)
    # The bucket the file went to at store time ('' = local disk). Recorded rather than
    # re-derived so a later change of GCS_REPORTS_BUCKET_NAME cannot orphan old files.
    storage_bucket: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_locator: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stored_remotely: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # All naive UTC, bound from Python (datetime.utcnow) — never DB now(), so the stale and
    # expiry comparisons cannot drift with the database session's time zone.
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
