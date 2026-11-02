"""Internal Statement → Upload Statement, for files of any size — `/internal-tickets/imports`.

The upload, mapping, review and save of /internal-tickets/upload/…, with the file's lines kept
on the server instead of travelling to the browser and back (services/internal_import.py):

  POST   /imports                      the file, once: stored, its columns and date format read
  POST   /imports/{id}/read            read again at another sheet / header row
  POST   /imports/{id}/parse           the mapping chosen: the worker reads every line
  GET    /imports/{id}                 where the worker is; once ready, the review's summary
  POST   /imports/{id}/summary         the same, "All vendors" duplicates of the picked suppliers
  GET    /imports/{id}/rows            a page of the review grid
  POST   /imports/{id}/rows            a blank line at the end
  PATCH  /imports/{id}/rows/{row_no}   one line edited, removed or put back
  POST   /imports/{id}/rows/bulk       many lines at once
  POST   /imports/{id}/save            the statement details: the worker saves it
  DELETE /imports/{id}                 discard

Scoped to tenant and creator, as every Internal Statement read is.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.internal_tickets import _impl
from app.database import get_db
from app.dependencies import get_current_user
from app.models.internal_ticket_import import InternalTicketImport as Job
from app.models.internal_ticket_import import InternalTicketImportRow as Row
from app.models.user import User
from app.schemas.uploaded_ticket import TicketExtractionPreview
from app.services import file_store
from app.services import internal_import as imp

logger = logging.getLogger(__name__)
router = APIRouter()

# As /upload/extract allows. The file goes to the browser never, so this is the upload alone.
_MAX_MB = 50

# The last few files uploaded, by import: re-reading at another header row should not fetch
# the file back from GCS. One API process, a handful of files — anything older is loaded.
_FILES: "OrderedDict[str, bytes]" = OrderedDict()
_FILES_KEPT = 3


def _keep(import_id: str, content: bytes) -> None:
    _FILES[import_id] = content
    _FILES.move_to_end(import_id)
    while len(_FILES) > _FILES_KEPT:
        _FILES.popitem(last=False)


async def _content(job: Job) -> bytes:
    if job.id in _FILES:
        _FILES.move_to_end(job.id)
        return _FILES[job.id]
    try:
        content = await file_store.load(job.file_locator, imp.bucket())
    except Exception as exc:  # noqa: BLE001 — storage, said plainly
        raise HTTPException(status_code=410, detail=f"The uploaded file is no longer available: {exc}")
    _keep(job.id, content)
    return content


async def _job(db: AsyncSession, user: User, import_id: str, *, lock: bool = False) -> Job:
    q = select(Job).where(Job.id == import_id, Job.tenant_id == user.tenant_id, Job.created_by_id == user.id)
    job = (await db.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Upload not found — it may have expired. Upload the file again.")
    return job


async def _ready(db: AsyncSession, user: User, import_id: str) -> Job:
    """The job, locked, while it is under review — an edit never lands on a statement being saved."""
    job = await _job(db, user, import_id, lock=True)
    if job.status != "ready":
        raise HTTPException(status_code=409, detail={
            "saving": "The statement is being saved — it can't be changed now.",
            "saved": "This statement has been saved.",
        }.get(job.status, "The file is still being read."))
    return job


def _head(head: dict, dates: list[dict]) -> dict:
    """The upload step's answer: the file's columns as /upload/extract gives them (no rows), and
    its date format as /upload/detect-date-formats gives it."""
    fields = TicketExtractionPreview.model_fields
    preview = TicketExtractionPreview(**{k: v for k, v in head.items() if k in fields and k != "rows"}, rows=[])
    return {"preview": preview.model_dump(mode="json"),
            "date_formats": {"period_label": None, "fields": dates}}


async def _enqueue(db: AsyncSession, job: Job, task) -> None:
    """Hand the job to the worker — or say why it can't be, on the job and to the page."""
    try:
        task.delay(job.id, job.attempt)
    except Exception as exc:  # noqa: BLE001 — the broker is down
        logger.exception("Could not queue import %s", job.id)
        job.status = "failed" if job.status == "parsing" else "ready"
        job.phase = None
        job.error = "The background worker could not be reached. Try again in a minute."
        await db.commit()
        raise HTTPException(status_code=503, detail=job.error) from exc


def _bump(job: Job, status: str) -> None:
    job.status, job.phase, job.error = status, "queued", None
    job.attempt = (job.attempt or 0) + 1
    job.processed_rows = 0
    job.updated_at = datetime.utcnow()


# ── The file ─────────────────────────────────────────────────────────────────

@router.post("")
async def create_import(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store the file and read its columns and date format — once. Nothing is mapped yet."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")
    content = await file.read(_MAX_MB * 1024 * 1024 + 1)
    if len(content) > _MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {_MAX_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    try:
        head, dates = await asyncio.to_thread(imp.read_head, content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    import_id = str(uuid.uuid4())
    content_type = mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    locator, _ = await file_store.store(
        content, imp.blob_name(current_user.tenant_id, import_id, file.filename), content_type, imp.bucket())
    now = datetime.utcnow()
    db.add(Job(
        id=import_id, tenant_id=current_user.tenant_id, created_by_id=current_user.id,
        file_name=file.filename, file_locator=locator, file_size=len(content),
        sheet_name=head.get("sheet_name"), header_row=head.get("header_row"),
        status="uploaded", total_rows=head.get("total_rows", 0),
        read_info={"columns": head.get("xls_columns", [])},
        created_at=now, updated_at=now,
    ))
    await db.commit()
    _keep(import_id, content)
    try:
        await imp.purge_expired(db)
    except Exception:  # noqa: BLE001 — housekeeping never fails an upload
        await db.rollback()
        logger.warning("Purging expired imports failed", exc_info=True)
    return {"import_id": import_id, **_head(head, dates)}


class _ReadPayload(BaseModel):
    sheet_name: str | None = Field(None, max_length=255)
    header_row: int | None = Field(None, ge=0)


@router.post("/{import_id}/read")
async def reread_import(
    import_id: str,
    payload: _ReadPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read the stored file again at another sheet or header row. Its columns change, so any
    mapping and any lines read are dropped — the next Next reads it afresh."""
    job = await _job(db, current_user, import_id, lock=True)
    if job.status in ("saving", "saved"):
        raise HTTPException(status_code=409, detail="This statement is being saved or has been saved.")
    content = await _content(job)
    sheet = payload.sheet_name or job.sheet_name
    header = payload.header_row if payload.header_row is not None else (None if payload.sheet_name else job.header_row)
    try:
        head, dates = await asyncio.to_thread(imp.read_head, content, job.file_name, sheet, header)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    job.sheet_name, job.header_row = head.get("sheet_name"), head.get("header_row")
    job.read_info = {"columns": head.get("xls_columns", [])}
    job.column_map, job.total_rows = None, head.get("total_rows", 0)
    # A read in flight is of the old columns: a new attempt stops it.
    job.status, job.phase, job.error, job.attempt = "uploaded", None, None, (job.attempt or 0) + 1
    job.updated_at = datetime.utcnow()
    await db.execute(delete(Row).where(Row.import_id == job.id))
    await db.commit()
    return {"import_id": job.id, **_head(head, dates)}


class _ParsePayload(BaseModel):
    column_map: dict[str, str] = Field(default_factory=dict)
    date_formats: dict[str, str] | None = None


@router.post("/{import_id}/parse")
async def parse_import(
    import_id: str,
    payload: _ParsePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The mapping and date format chosen: the worker reads every line into the review. Asked
    again — a date format changed on the review — it reads afresh, and edits are lost."""
    from app.workers.import_tasks import parse_internal_import

    job = await _job(db, current_user, import_id, lock=True)
    if job.status in ("saving", "saved"):
        raise HTTPException(status_code=409, detail="This statement is being saved or has been saved.")
    formats = _impl._checked_date_formats(payload.date_formats, required=True)
    columns = set((job.read_info or {}).get("columns") or [])
    job.column_map = {f: c for f, c in payload.column_map.items() if c and c in columns}
    job.date_formats = formats
    job.result, job.total_rows = None, 0
    _bump(job, "parsing")
    await db.commit()
    await _enqueue(db, job, parse_internal_import)
    return imp.view(job)


@router.get("/{import_id}")
async def get_import(
    import_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Where the worker is. Under review, also the summary above the grid — counted off the
    lines as they stand, edits included."""
    job = await _job(db, current_user, import_id)
    out = imp.view(job)
    if job.status == "ready":
        out["summary"] = await imp.summary(db, job)
    return out


class _SummaryPayload(BaseModel):
    # "All vendors": the supplier groups given a vendor — duplicates are counted among their lines.
    groups: list[str] | None = Field(None, max_length=5000)


@router.post("/{import_id}/summary")
async def import_summary(
    import_id: str,
    payload: _SummaryPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """GET /imports/{id}, with the duplicates of an "All vendors" file counted among the lines of
    the suppliers given a vendor — the lines Save sends."""
    job = await _job(db, current_user, import_id)
    out = imp.view(job)
    if job.status == "ready":
        out["summary"] = await imp.summary(db, job, payload.groups)
    return out


# ── The review ───────────────────────────────────────────────────────────────

@router.get("/{import_id}/rows")
async def import_rows(
    import_id: str,
    view: str = Query("all"),
    q: str = Query("", max_length=200),
    page: int = Query(0, ge=0),
    size: int = Query(100, ge=1, le=imp.PAGE_MAX),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A page of the review grid — all lines, or a tab of them (services/internal_import.VIEWS),
    searched over every value."""
    job = await _job(db, current_user, import_id)
    if job.status != "ready":
        raise HTTPException(status_code=409, detail="The file is still being read.")
    return await imp.page(db, job, view_name=view, q=q, page_no=page, size=size)


class _EditPayload(BaseModel):
    # {field: value}; a blank value clears the field.
    values: dict[str, Any] | None = None
    # True removes the line (not saved), False puts it back.
    excluded: bool | None = None


class _BulkPayload(_EditPayload):
    row_nos: list[int] = Field(..., min_length=1, max_length=imp.BULK_MAX)


async def _edit(db: AsyncSession, user: User, import_id: str, row_nos: list[int], payload: _EditPayload) -> list[dict]:
    job = await _ready(db, user, import_id)
    try:
        rows = await imp.edit_rows(db, job, user, row_nos, values=payload.values, excluded=payload.excluded)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await db.commit()
    return rows


@router.patch("/{import_id}/rows/{row_no}")
async def edit_import_row(
    import_id: str,
    row_no: int,
    payload: _EditPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One line edited, removed or put back. Answers the line as it now stands — a changed
    ticket number, passenger, date or amount is checked for a duplicate again."""
    rows = await _edit(db, current_user, import_id, [row_no], payload)
    if not rows:
        raise HTTPException(status_code=404, detail="Row not found.")
    return rows[0]


@router.post("/{import_id}/rows/bulk")
async def edit_import_rows(
    import_id: str,
    payload: _BulkPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The grid's "apply to the selected rows" and "remove the selected rows"."""
    return {"rows": await _edit(db, current_user, import_id, payload.row_nos, payload)}


@router.post("/{import_id}/rows")
async def add_import_row(
    import_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A blank line at the end of the review, for a ticket the file is missing."""
    job = await _ready(db, current_user, import_id)
    row = await imp.add_row(db, job)
    await db.commit()
    return row


# ── The save ─────────────────────────────────────────────────────────────────

class _SavePayload(BaseModel):
    """The statement details — as /upload/confirm takes them, without the rows."""
    statement_name: str | None = Field(None, max_length=500)
    statement_category: str | None = None
    agency: str | None = Field(None, max_length=300)
    customer_type: str | None = None
    customer_agency_id: int | None = None
    corporate_id: int | None = None
    customer_id: int | None = None
    multi_vendor: bool = False
    # "All vendors": supplier group ("<Supplier Name>|GDS") → "agency:<id>" | "airline" | "".
    vendor_picks: dict[str, str] = Field(default_factory=dict)


@router.post("/{import_id}/save")
async def save_import(
    import_id: str,
    payload: _SavePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save the reviewed lines as a statement — in the worker. What the user must change (the
    customer, the statement type) is said here; the duplicate check runs again in the save."""
    from app.workers.import_tasks import save_internal_import

    job = await _ready(db, current_user, import_id)
    long_rows = await imp.long_rows(db, job.id)
    if long_rows:
        raise HTTPException(status_code=422, detail=imp.too_long_message(long_rows))
    category = payload.statement_category or None
    if category is not None and category not in _impl.STATEMENT_CATEGORIES:
        raise HTTPException(status_code=422, detail="Statement type must be a Booking / MO or an Accounting statement.")
    if not payload.multi_vendor:
        party = await _impl._resolve_customer_party(
            db, current_user, payload.customer_type, payload.customer_agency_id,
            payload.corporate_id, payload.customer_id)
        if party.customer_type is None:
            raise HTTPException(status_code=422, detail="Choose who these tickets were sold to.")
    job.save_request = payload.model_dump()
    _bump(job, "saving")
    await db.commit()
    await _enqueue(db, job, save_internal_import)
    return imp.view(job)


@router.delete("/{import_id}")
async def discard_import(
    import_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Throw the upload away — its lines and its stored file. A saved statement keeps its file."""
    job = await _job(db, current_user, import_id, lock=True)
    if job.status == "saving":
        raise HTTPException(status_code=409, detail="The statement is being saved — wait for it to finish.")
    await imp.discard(db, job)
    await db.commit()
    _FILES.pop(import_id, None)
    return {"import_id": import_id, "deleted": True}
