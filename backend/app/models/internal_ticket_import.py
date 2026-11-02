"""Internal Statement's background upload: an import job and its staging rows.

A sales report runs to a lakh of lines, too many to read, review and save inside requests
or to hold in the browser. So the file is uploaded ONCE (`internal_ticket_imports` keeps
where it is stored), a Celery worker reads it into `internal_ticket_import_rows`, the review
screen pages through those rows on the server, and Save has the worker write the statement
from them (services/internal_import.py, workers/import_tasks.py).

The staging rows are not tickets. Nothing else reads them, and they go when the statement is
saved or the import is discarded; an import left alone is purged after IMPORT_TTL.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InternalTicketImport(Base):
    """One file on its way to becoming an Internal Statement.

    status:
      uploaded — stored and its columns read; mapping not chosen yet
      parsing  — the worker is reading it into staging rows (`phase` says how far)
      ready    — staging rows in place, under review
      saving   — the worker is writing the statement
      saved    — done: `batch_id` is the statement, `result` what was saved
      failed   — the read failed (`error`); a failed SAVE goes back to `ready` with `error`

    `attempt` fences the worker: each read or save asked for bumps it, and a worker only
    writes while the attempt it was given is still the current one — a re-read started while
    an older read is running wins, and the older one stops."""
    __tablename__ = "internal_ticket_imports"

    id:              Mapped[str]             = mapped_column(String(36), primary_key=True)
    tenant_id:       Mapped[int]             = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id:   Mapped[int]             = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # ── the file ─────────────────────────────────────────────────────────────
    file_name:       Mapped[str]             = mapped_column(String(500), nullable=False)
    # services/file_store.py locator: a GCS blob, or "local://…" when GCS was unavailable.
    file_locator:    Mapped[str]             = mapped_column(String(1000), nullable=False)
    file_size:       Mapped[int]             = mapped_column(Integer, nullable=False, default=0)
    sheet_name:      Mapped[str | None]      = mapped_column(String(255), nullable=True)
    header_row:      Mapped[int | None]      = mapped_column(Integer, nullable=True)

    # ── how it is read ───────────────────────────────────────────────────────
    column_map:      Mapped[dict | None]     = mapped_column(JSONB, nullable=True)   # {field: column}
    date_formats:    Mapped[dict | None]     = mapped_column(JSONB, nullable=True)   # {field: DMY|MDY|YMD}

    # ── where the worker is ──────────────────────────────────────────────────
    status:          Mapped[str]             = mapped_column(String(16), nullable=False, default="uploaded")
    phase:           Mapped[str | None]      = mapped_column(String(16), nullable=True)
    attempt:         Mapped[int]             = mapped_column(Integer, nullable=False, default=0)
    total_rows:      Mapped[int]             = mapped_column(Integer, nullable=False, default=0)
    processed_rows:  Mapped[int]             = mapped_column(Integer, nullable=False, default=0)
    error:           Mapped[str | None]      = mapped_column(Text, nullable=True)
    heartbeat_at:    Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # What the read found that the rows do not say: its warnings, the Excel dates put back,
    # the review columns the file filled.
    read_info:       Mapped[dict | None]     = mapped_column(JSONB, nullable=True)
    # The statement details Save was pressed with, and what it saved.
    save_request:    Mapped[dict | None]     = mapped_column(JSONB, nullable=True)
    result:          Mapped[dict | None]     = mapped_column(JSONB, nullable=True)
    batch_id:        Mapped[str | None]      = mapped_column(String(100), nullable=True)

    created_at:      Mapped[datetime]        = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at:      Mapped[datetime]        = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class InternalTicketImportRow(Base):
    """One line of an import, read and mapped — a TicketRow as JSON (`data`, its empty fields
    left out) with what the review screen filters on worked out beside it."""
    __tablename__ = "internal_ticket_import_rows"

    import_id:       Mapped[str]             = mapped_column(String(36), ForeignKey("internal_ticket_imports.id", ondelete="CASCADE"), primary_key=True)
    row_no:          Mapped[int]             = mapped_column(Integer, primary_key=True)   # 1-based, file order
    tenant_id:       Mapped[int]             = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    data:            Mapped[dict]            = mapped_column(JSONB, nullable=False)
    # Every value of the line, lower-cased — what the review's search matches.
    search_text:     Mapped[str]             = mapped_column(Text, nullable=False, default="")
    # services/ticket_duplicates.py: the line's key, and the statement a ticket with it is
    # already loaded in — a duplicate, not saved.
    dedup_key:       Mapped[str | None]      = mapped_column(String(64), nullable=True)
    duplicate_of:    Mapped[str | None]      = mapped_column(String(100), nullable=True)
    # A Booking or Travel Date that did not read in the declared format.
    bad_date:        Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False)
    # A value longer than its ticket column holds — the line can't be saved as it stands.
    too_long:        Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False)
    # "All vendors": "<Supplier Name>|GDS|LCC" — which vendor pick the line follows.
    supplier_group:  Mapped[str | None]      = mapped_column(String(400), nullable=True)
    # Removed on the review screen: kept, so it can be put back, and not saved.
    excluded:        Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False)
    edited:          Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False)
