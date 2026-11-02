"""Internal Statement's background upload — a lakh-line sales report read, reviewed and saved
on the server.

THE FLOW (api/v1/internal_imports.py, workers/import_tasks.py):
  1. The file is uploaded ONCE. It is stored (services/file_store.py) and only its columns and
     date format are read — `read_head`. Everything later reads the stored copy.
  2. The mapping is chosen as before. "Next" queues the worker (`run_parse`): it reads every
     line, keys each for the duplicate check against the tickets already loaded, and writes
     the lines into staging rows (models/internal_ticket_import.py), a chunk at a time, with
     progress the page polls.
  3. The review screen pages through the staging rows on the server — `page`, `summary` — and
     an edit changes one row (`edit_rows`). Nothing of the file is held by the browser.
  4. Save queues the worker again (`run_save`). It builds the tickets from the staging rows
     through the same save as a small upload — tickets.save_statement, in Internal Statement's
     copy of that module — so the duplicate rule, the period and the name cannot differ.

WHY STAGING ROWS AND NOT DRAFT TICKETS. Every reader of internal_uploaded_tickets — vendor
reconciliation, the Payment Module's mapping, the duplicate check itself — would have to learn
to skip a draft; one that did not would reconcile tickets nobody had reviewed. The staging rows
are read by nothing but this module, and are gone once the statement is saved.

FENCING. Every worker run is given the job's `attempt`, and every write it makes checks the job
still has that attempt (`_claim`). Reading the file again while a read is running, or discarding
the import, bumps or removes it, and the old run stops at its next write.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Numeric, String, and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.internal_ticket import InternalTicketStatement, InternalUploadedTicket
from app.models.internal_ticket_import import InternalTicketImport as Job
from app.models.internal_ticket_import import InternalTicketImportRow as Row
from app.schemas.uploaded_ticket import TicketRow
from app.services import file_store, ticket_duplicates, ticket_extraction

logger = logging.getLogger(__name__)

# An import nobody saved or discarded is purged after this.
IMPORT_TTL = timedelta(hours=48)
# Staging rows written per transaction — and how often the progress bar moves.
WRITE_CHUNK = 2000
# The review grid's largest page, and the most rows one bulk edit may name.
PAGE_MAX = 200
BULK_MAX = 5000
# Lines listed in the duplicates box (every one is marked in the grid all the same).
LISTED = ticket_duplicates.MAX_LISTED

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")
_ISO_SQL = r"^\d{4}-\d{2}-\d{2}"
# How the review's tabs narrow the rows.
VIEWS = ("all", "duplicates", "dates", "long", "edited", "removed")

# The most each text field of a ticket holds — a longer value fails the whole save, so the
# line is flagged on the review instead (`too_long`).
LIMITS = {c.name: c.type.length for c in InternalUploadedTicket.__table__.c
          if isinstance(c.type, String) and c.type.length}


class Superseded(Exception):
    """The import was read again, saved, or discarded since this worker run began."""


def bucket() -> str:
    return settings.GCS_TICKETS_BUCKET_NAME


def blob_name(tenant_id: int, import_id: str, file_name: str) -> str:
    return f"internal-imports/{tenant_id}/{import_id}/{file_name}"


# ── Reading the file (CPU; run in a thread) ──────────────────────────────────

def _extract(content: bytes, file_name: str, **kw) -> dict:
    """TicketExtractionService.extract as Internal Statement reads a file — the flags its copy
    of tickets.py passes (api/v1/internal_tickets.py) — with the fast xlsx reader. extract
    awaits nothing, so it runs to completion in a loop of its own, in this thread."""
    return asyncio.run(ticket_extraction.TicketExtractionService.extract(
        content, file_name, statement_type="B2B", split_legs=False, keep_raw=False,
        internal_standard=True, fast_read=True, **kw))


def read_head(content: bytes, file_name: str, sheet: str | None = None,
              header_row: int | None = None) -> tuple[dict, list[dict]]:
    """The upload step's read: the columns, samples and suggested mapping (extract with no
    rows), and the order the date columns are written in — off ONE read of the file."""
    read = ticket_extraction.read_file_table(content, file_name, sheet, header_row, fast_read=True)
    head = _extract(content, file_name, include_rows=False, read=read)
    dates = ticket_extraction.detect_date_formats(content, file_name, read=read)
    return head, dates


def read_rows(content: bytes, job: Job) -> dict:
    """Every line of the file, mapped and read in the declared date format."""
    return _extract(content, job.file_name, column_mapping=job.column_map or None,
                    date_formats=job.date_formats, sheet_name=job.sheet_name,
                    header_row=job.header_row)


# ── One line's facts ─────────────────────────────────────────────────────────

def clean(row: dict) -> dict:
    """A line as a TicketRow, as JSON, its empty fields left out — what a staging row keeps."""
    return TicketRow.model_validate(row).model_dump(mode="json", exclude_none=True)


def channel(ticket_number) -> str:
    """GDS for a numeric document number, LCC for a PNR — as the page reads a line's channel."""
    digits = re.sub(r"[\s-]", "", str(ticket_number or ""))
    return "GDS" if re.fullmatch(r"\d{8,}", digits) else "LCC"


def supplier_group(data: dict) -> str:
    """"<Supplier Name>|GDS" — the "All vendors" pick a line follows (page.tsx supplierGroup)."""
    return f"{str(data.get('supplier_name') or '').strip()}|{channel(data.get('ticket_number'))}"


def bad_date(data: dict) -> bool:
    """A Booking (else Doc) or Travel Date that did not read in the declared format — kept as
    written, for the reviewer to correct; it saves as it stands."""
    for v in (data.get("ticket_date") or data.get("doc_date"), data.get("departure_datetime")):
        if v and not _ISO_DAY.match(str(v)):
            return True
    return False


def too_long(data: dict) -> list[str]:
    """The fields whose value is longer than the ticket column holds."""
    return [k for k, v in data.items()
            if isinstance(v, str) and k in LIMITS and len(v) > LIMITS[k]]


def search_text(data: dict) -> str:
    return " ".join(str(v) for v in data.values()
                    if v not in (None, "") and not isinstance(v, (dict, list))).lower()


def facts(data: dict) -> dict:
    """What a staging row keeps beside the line, worked out from it."""
    return {"search_text": search_text(data), "dedup_key": ticket_duplicates.ticket_key(data),
            "bad_date": bad_date(data), "too_long": bool(too_long(data)),
            "supplier_group": supplier_group(data)}


def filled_fields(rows: list[dict]) -> list[str]:
    """The ticket fields any line has a value in — the review grid's columns."""
    out: set[str] = set()
    for r in rows:
        out.update(k for k, v in r.items() if v not in (None, ""))
    return sorted(out)


# ── Edits ────────────────────────────────────────────────────────────────────

# What the grid edits: a ticket field, not the row's bookkeeping or its nested parts.
_NOT_EDITABLE = {"row_order", "raw_data", "tax_breakup", "segments"}
EDITABLE = frozenset(f for f in TicketRow.model_fields if f not in _NOT_EDITABLE)


def edited(data: dict, values: dict[str, Any]) -> dict:
    """`data` with `values` set — a blank clears the field — checked as a TicketRow, which turns
    "1,250" into an error rather than a ticket. ValueError names what is wrong."""
    unknown = sorted(set(values) - EDITABLE)
    if unknown:
        raise ValueError(f"Not a ticket field: {', '.join(unknown)}.")
    out = dict(data)
    for key, value in values.items():
        if value is None or (isinstance(value, str) and value.strip() == ""):
            out.pop(key, None)
        else:
            out[key] = value.strip() if isinstance(value, str) else value
    try:
        return clean(out)
    except ValidationError as exc:
        err = exc.errors()[0]
        where = ".".join(str(p) for p in err.get("loc", ())) or "A value"
        raise ValueError(f"{where}: {err.get('msg', 'not valid')}.") from exc


# ── "All vendors": each line's vendor ───────────────────────────────────────

def apply_vendor_picks(rows: list[dict], groups: list[str | None], picks: dict[str, str],
                       airline_ids: dict[str, int]) -> tuple[list[dict], int]:
    """The lines that have a vendor, each with its Payable To — and how many have none.

    `picks` is the page's: supplier group → "agency:<id>" | "airline" | "". "Bought from the
    airline" pays the line's own airline, found in the airline master by its code; a line whose
    code is not there has no vendor. A line without one is not saved (user, 2026-10-29)."""
    kept, dropped = [], 0
    for data, group in zip(rows, groups):
        pick = picks.get(group or "") or ""
        if pick.startswith("agency:") and pick[7:].isdigit():
            kept.append({**data, "payable_type": "b2b", "payable_agency_id": int(pick[7:])})
            continue
        if pick == "airline":
            airline_id = airline_ids.get(str(data.get("airlines_code") or "").strip().upper())
            if airline_id is not None:
                kept.append({**data, "payable_type": "airline", "payable_airline_id": airline_id})
                continue
        dropped += 1
    return kept, dropped


# ── The job ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.utcnow()


def view(job: Job) -> dict:
    """The job as the page reads it."""
    waiting = (job.phase == "queued" and job.updated_at is not None
               and (_now() - job.updated_at).total_seconds())
    return {
        "import_id": job.id, "status": job.status, "phase": job.phase,
        "total_rows": job.total_rows, "processed_rows": job.processed_rows,
        "error": job.error, "file_name": job.file_name,
        "sheet_name": job.sheet_name, "header_row": job.header_row,
        "column_map": job.column_map, "date_formats": job.date_formats,
        "batch_id": job.batch_id, "result": job.result,
        "read": {k: v for k, v in (job.read_info or {}).items() if k != "columns"},
        # Seconds the job has waited for a worker — the page says so past a few.
        "queued_for": int(waiting) if waiting else 0,
    }


async def _claim(db: AsyncSession, import_id: str, attempt: int, status: str) -> Job:
    """The job, locked, if this run is still the one it is waiting on — else Superseded."""
    job = (await db.execute(select(Job).where(Job.id == import_id).with_for_update())).scalar_one_or_none()
    if job is None or job.attempt != attempt or job.status != status:
        raise Superseded()
    job.heartbeat_at = job.updated_at = _now()
    return job


async def _set(Session, import_id: str, attempt: int, status: str, **values) -> None:
    async with Session() as db, db.begin():
        job = await _claim(db, import_id, attempt, status)
        for k, v in values.items():
            setattr(job, k, v)


async def fail(Session, import_id: str, attempt: int, status: str, message: str) -> None:
    """A run that could not finish. A read leaves the import `failed`; a save puts it back
    under review, with the reason — its rows are untouched."""
    try:
        async with Session() as db, db.begin():
            job = await _claim(db, import_id, attempt, status)
            job.status = "failed" if status == "parsing" else "ready"
            job.phase = None
            job.error = (message or "Something went wrong.")[:2000]
    except Superseded:
        pass


# ── The read (worker) ────────────────────────────────────────────────────────

def _user(job: Job) -> SimpleNamespace:
    """Who the duplicate check is for: the ticket tables are read per tenant and creator."""
    return SimpleNamespace(id=job.created_by_id, tenant_id=job.tenant_id)


async def run_parse(Session, import_id: str, attempt: int) -> None:
    """Read the stored file into staging rows. `Session` is the worker's session factory."""
    async with Session() as db, db.begin():
        job = await _claim(db, import_id, attempt, "parsing")
        job.phase, job.error, job.processed_rows = "reading", None, 0
        snapshot = SimpleNamespace(**{c: getattr(job, c) for c in (
            "id", "tenant_id", "created_by_id", "file_name", "file_locator", "sheet_name",
            "header_row", "column_map", "date_formats", "read_info")})

    started = time.monotonic()
    content = await file_store.load(snapshot.file_locator, bucket())
    try:
        result = await asyncio.to_thread(read_rows, content, snapshot)
    except ValueError as exc:
        await fail(Session, import_id, attempt, "parsing", str(exc))
        return
    del content
    rows = [clean(r) for r in result["rows"]]
    logger.info("import %s: read %d lines in %.1fs", import_id, len(rows), time.monotonic() - started)
    await _set(Session, import_id, attempt, "parsing", phase="checking", total_rows=len(rows))

    async with Session() as db:
        found = await ticket_duplicates.find(db, _user(snapshot), rows,
                                             statements=InternalTicketStatement, tickets=InternalUploadedTicket)
    duplicate_of = {d["index"]: d["batch_id"] for d in found.lines}
    logger.info("import %s: %d duplicates found by %.1fs", import_id, len(duplicate_of), time.monotonic() - started)

    async with Session() as db, db.begin():
        job = await _claim(db, import_id, attempt, "parsing")
        await db.execute(delete(Row).where(Row.import_id == import_id))
        job.phase = "writing"
    for n in range(0, len(rows), WRITE_CHUNK):
        chunk = [
            {"import_id": import_id, "row_no": i + 1, "tenant_id": snapshot.tenant_id, "data": data,
             **facts(data), "duplicate_of": duplicate_of.get(i)}
            for i, data in enumerate(rows[n:n + WRITE_CHUNK], start=n)
        ]
        async with Session() as db, db.begin():
            job = await _claim(db, import_id, attempt, "parsing")
            await db.execute(insert(Row), chunk)
            job.processed_rows = n + len(chunk)

    async with Session() as db, db.begin():
        job = await _claim(db, import_id, attempt, "parsing")
        job.status, job.phase, job.error = "ready", None, None
        logger.info("import %s: ready after %.1fs", import_id, time.monotonic() - started)
        job.read_info = {
            **(snapshot.read_info or {}),
            "warnings": result.get("warnings", []),
            "date_fix": result.get("date_fix"),
            "filled": filled_fields(rows),
        }


# ── The review ───────────────────────────────────────────────────────────────

def _kept(import_id: str):
    return and_(Row.import_id == import_id, Row.excluded.is_(False))


async def _date_stats(db: AsyncSession, import_id: str, field: str) -> dict:
    v = Row.data[field].astext
    iso = v.op("~")(_ISO_SQL)
    bad = and_(v != "", ~iso)
    read, first, last, unreadable = (await db.execute(
        select(func.count().filter(iso), func.min(func.left(v, 10)).filter(iso),
               func.max(func.left(v, 10)).filter(iso), func.count().filter(bad))
        .where(_kept(import_id))
    )).one()
    cells = (await db.execute(
        select(Row.row_no, v).where(_kept(import_id), bad).order_by(Row.row_no).limit(3)
    )).all() if unreadable else []
    return {"key": field, "read": read, "first": first, "last": last, "unreadable": unreadable,
            "cells": [{"index": n - 1, "value": value} for n, value in cells]}


async def _dates(db: AsyncSession, import_id: str) -> list[dict]:
    """How the Booking and Travel Dates read — as the page's datesRead worked it out off the
    rows. A file with only a Doc Date has it as its Booking Date."""
    booked = await _date_stats(db, import_id, "ticket_date")
    if not booked["read"] and not booked["unreadable"]:
        doc = await _date_stats(db, import_id, "doc_date")
        if doc["read"] or doc["unreadable"]:
            booked = doc
    booked["field"] = "ticket_date"
    travel = await _date_stats(db, import_id, "departure_datetime")
    travel["field"] = "departure_datetime"
    return [booked, travel]


async def _duplicates(db: AsyncSession, job: Job, total: int, groups: list[str] | None = None) -> dict:
    """The duplicates box, as POST /upload/duplicates answers it (ticket_duplicates.Duplicates
    .preview) — of the rows not removed. `groups` ("All vendors"): of the lines of the suppliers
    given a vendor only — the lines a save sends, as the page checked them before."""
    scope = _kept(job.id)
    if groups is not None:
        scope = and_(scope, Row.supplier_group.in_(groups))
        total = (await db.execute(select(func.count()).select_from(Row).where(scope))).scalar_one()
    dup = and_(scope, Row.duplicate_of.isnot(None))
    matched = (await db.execute(
        select(Row.duplicate_of, func.count(), func.sum(Row.data["total_amt"].astext.cast(Numeric)))
        .where(dup).group_by(Row.duplicate_of)
    )).all()
    count = sum(n for _, n, _ in matched)
    amount = sum((a or Decimal("0") for _, _, a in matched), Decimal("0"))
    S = InternalTicketStatement
    loaded = {s.batch_id: s for s in (await db.execute(
        select(S.batch_id, S.statement_name, S.file_name, S.valid_from, S.valid_to, S.created_at)
        .where(S.tenant_id == job.tenant_id, S.batch_id.in_([b for b, _, _ in matched]))
    )).all()} if matched else {}
    statements = []
    for batch_id, n, _ in sorted(matched, key=lambda m: -m[1]):
        s = loaded.get(batch_id)
        if s is not None:
            statements.append({**ticket_duplicates.Loaded(*s).as_dict(), "matched": n})
    lines = (await db.execute(
        select(Row.row_no, Row.data, Row.duplicate_of).where(dup).order_by(Row.row_no).limit(LISTED)
    )).all() if count else []
    new = total - count
    reason = None
    if total and not new:
        reason = (f"All {total} tickets of this file are duplicates of tickets already loaded"
                  " — there is nothing new to save.")
    elif not total:
        reason = "Every row has been removed — there is nothing to save."
    return {
        "total": total, "duplicates": count, "new": new,
        "duplicates_amount": format(amount.quantize(Decimal("0.01"), ROUND_HALF_UP), "f"),
        "statements": statements,
        "lines": [{**ticket_duplicates.shown(d), "index": n - 1, "batch_id": b} for n, d, b in lines],
        "rows": [], "can_save": reason is None, "reason": reason,
    }


async def _long_fields(db: AsyncSession, import_id: str, fields: list[str]) -> list[dict]:
    """Which fields hold the values too long to save, and on how many lines."""
    present = [f for f in fields if f in LIMITS]
    if not present:
        return []
    counts = (await db.execute(
        select(*[func.count().filter(func.length(Row.data[f].astext) > LIMITS[f]) for f in present])
        .where(_kept(import_id), Row.too_long.is_(True))
    )).one()
    return [{"field": f, "limit": LIMITS[f], "rows": n} for f, n in zip(present, counts) if n]


async def summary(db: AsyncSession, job: Job, groups: list[str] | None = None) -> dict:
    """What the review screen shows above the grid, off the staging rows as they now stand.
    `groups` as in `_duplicates`."""
    counts = (await db.execute(
        select(func.count(),
               func.count().filter(Row.excluded.is_(False)),
               func.count().filter(and_(Row.excluded.is_(False), Row.bad_date.is_(True))),
               func.count().filter(and_(Row.excluded.is_(False), Row.edited.is_(True))),
               func.count().filter(and_(Row.excluded.is_(False), Row.too_long.is_(True))))
        .where(Row.import_id == job.id)
    )).one()
    rows, kept, bad, changed, long_count = counts
    filled = (job.read_info or {}).get("filled") or list(LIMITS)
    booked = func.coalesce(func.nullif(Row.data["ticket_date"].astext, ""), Row.data["doc_date"].astext)
    first, last = (await db.execute(
        select(func.min(func.left(booked, 10)), func.max(func.left(booked, 10)))
        .where(_kept(job.id), booked.op("~")(_ISO_SQL))
    )).one()
    suppliers = (await db.execute(
        select(Row.supplier_group, func.count()).where(_kept(job.id)).group_by(Row.supplier_group)
    )).all()
    return {
        "rows": rows, "kept": kept, "removed": rows - kept, "bad_dates": bad, "edited": changed,
        "too_long": long_count,
        "long_fields": await _long_fields(db, job.id, filled) if long_count else [],
        # The grid marks a value longer than its field holds.
        "limits": {f: LIMITS[f] for f in filled if f in LIMITS},
        "period": {"from": first, "to": last} if first else None,
        "dates": await _dates(db, job.id),
        "suppliers": [{"group": g or "|LCC", "count": n} for g, n in suppliers],
        "duplicates": await _duplicates(db, job, kept, groups),
    }


def _row_out(r: Row) -> dict:
    return {"row_no": r.row_no, "data": r.data, "duplicate_of": r.duplicate_of,
            "bad_date": r.bad_date, "too_long": r.too_long, "excluded": r.excluded, "edited": r.edited}


async def long_rows(db: AsyncSession, import_id: str) -> int:
    """Lines not removed that hold a value too long to save."""
    return (await db.execute(
        select(func.count()).select_from(Row).where(_kept(import_id), Row.too_long.is_(True))
    )).scalar_one()


def too_long_message(n: int) -> str:
    rows, them = ("rows have", "them") if n != 1 else ("row has", "it")
    return f"{n:,} {rows} a value too long to save — fix or remove {them} under “Too long”, then save."


def _like(text: str) -> str:
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def page(db: AsyncSession, job: Job, *, view_name: str = "all", q: str = "",
               page_no: int = 0, size: int = 100) -> dict:
    """One page of the review grid: a tab (VIEWS), a search over every value of the line."""
    where = {
        "all": [_kept(job.id)],
        "duplicates": [_kept(job.id), Row.duplicate_of.isnot(None)],
        "dates": [_kept(job.id), Row.bad_date.is_(True)],
        "long": [_kept(job.id), Row.too_long.is_(True)],
        "edited": [_kept(job.id), Row.edited.is_(True)],
        "removed": [Row.import_id == job.id, Row.excluded.is_(True)],
    }[view_name if view_name in VIEWS else "all"]
    if q.strip():
        where.append(Row.search_text.like(_like(q.strip()), escape="\\"))
    total = (await db.execute(select(func.count()).select_from(Row).where(*where))).scalar_one()
    size = max(1, min(size, PAGE_MAX))
    found = (await db.execute(
        select(Row).where(*where).order_by(Row.row_no).offset(max(0, page_no) * size).limit(size)
    )).scalars().all()
    return {"total": total, "page": page_no, "size": size, "rows": [_row_out(r) for r in found]}


async def edit_rows(db: AsyncSession, job: Job, user, row_nos: list[int], *,
                    values: dict[str, Any] | None = None, excluded: bool | None = None) -> list[dict]:
    """Set `values` on the rows, or remove / put back (`excluded`). A changed line is keyed
    again and checked against the tickets already loaded, as a save will check it. ValueError
    for a value that is not one."""
    found = (await db.execute(
        select(Row).where(Row.import_id == job.id, Row.row_no.in_(row_nos)).order_by(Row.row_no).with_for_update()
    )).scalars().all()
    changed = []
    for r in found:
        if values:
            data = edited(r.data, values)
            if data != r.data:
                r.data = data
                for k, v in facts(data).items():
                    setattr(r, k, v)
                r.edited = True
                changed.append(r)
        if excluded is not None:
            r.excluded = excluded
    if changed:
        dupes = await ticket_duplicates.find(db, user, [r.data for r in changed],
                                             statements=InternalTicketStatement, tickets=InternalUploadedTicket)
        again = {d["index"]: d["batch_id"] for d in dupes.lines}
        for i, r in enumerate(changed):
            r.duplicate_of = again.get(i)
    job.updated_at = _now()
    await db.flush()
    return [_row_out(r) for r in found]


async def add_row(db: AsyncSession, job: Job) -> dict:
    """A blank line at the end, for a ticket the file is missing."""
    last = (await db.execute(select(func.max(Row.row_no)).where(Row.import_id == job.id))).scalar_one()
    r = Row(import_id=job.id, row_no=(last or 0) + 1, tenant_id=job.tenant_id, data={},
            **facts({}), edited=True)
    db.add(r)
    job.total_rows = (job.total_rows or 0) + 1
    await db.flush()
    return _row_out(r)


# ── The save (worker) ────────────────────────────────────────────────────────

async def _airline_ids(db: AsyncSession) -> dict[str, int]:
    """IATA code → id of the active airlines in the airline master (page.tsx airlineIds)."""
    from app.models.airline import Airline
    found = await db.execute(select(Airline.id, Airline.iata_code)
                             .where(Airline.is_active.is_(True), Airline.iata_code.isnot(None)))
    return {code.strip().upper(): airline_id for airline_id, code in found.all() if code}


async def run_save(Session, import_id: str, attempt: int) -> None:
    """Write the statement from the staging rows — tickets.save_statement in Internal
    Statement's copy of tickets.py — in one transaction: all of it, or nothing."""
    from fastapi import HTTPException

    from app.api.v1.internal_tickets import _impl   # tickets.py over the internal tables
    from app.models.user import User
    from app.schemas.uploaded_ticket import ConfirmTicketUploadPayload

    started = time.monotonic()
    async with Session() as db, db.begin():
        job = await _claim(db, import_id, attempt, "saving")
        job.phase, job.processed_rows = "checking", 0
        request = dict(job.save_request or {})
        snapshot = SimpleNamespace(**{c: getattr(job, c) for c in (
            "id", "tenant_id", "created_by_id", "file_name", "file_locator", "column_map",
            "date_formats", "read_info")})

    try:
        async with Session() as db:
            user = await db.get(User, snapshot.created_by_id)
            n = await long_rows(db, import_id)
            if n:
                raise HTTPException(status_code=422, detail=too_long_message(n))
            found = (await db.execute(
                select(Row.data, Row.supplier_group).where(_kept(import_id)).order_by(Row.row_no)
            )).all()
            rows = [d for d, _ in found]
            no_vendor = 0
            if request.get("multi_vendor"):
                rows, no_vendor = apply_vendor_picks(rows, [g for _, g in found],
                                                     request.get("vendor_picks") or {}, await _airline_ids(db))
            if not rows:
                raise HTTPException(status_code=400, detail=(
                    "No row has a vendor — pick one for a supplier under Vendors in this file."
                    if no_vendor else "No rows to save."))
            payload = ConfirmTicketUploadPayload(
                file_name=snapshot.file_name,
                rows=[TicketRow.model_validate(d) for d in rows],
                statement_type="B2B",
                agency=request.get("agency") or "—",
                agency_id=None,
                statement_name=request.get("statement_name"),
                statement_category=request.get("statement_category"),
                customer_type=request.get("customer_type"),
                customer_agency_id=request.get("customer_agency_id"),
                corporate_id=request.get("corporate_id"),
                customer_id=request.get("customer_id"),
                date_formats=snapshot.date_formats,
                multi_vendor=bool(request.get("multi_vendor")),
                columns=(snapshot.read_info or {}).get("columns"),
                column_map=snapshot.column_map,
            )
            del found, rows
            logger.info("import %s: %d lines loaded to save by %.1fs", import_id, len(payload.rows),
                        time.monotonic() - started)
            await _set(Session, import_id, attempt, "saving", phase="saving", total_rows=len(payload.rows))

            async def progress(done: int, total: int) -> None:
                await _set(Session, import_id, attempt, "saving", processed_rows=done)

            result = await _impl.save_statement(db, user, payload, progress=progress)
            logger.info("import %s: %d tickets built by %.1fs", import_id, result.created_count,
                        time.monotonic() - started)
            # The file stays with the statement — where the upload put it, when that is GCS
            # (the statement's file link signs a GCS blob).
            if not file_store.is_local(snapshot.file_locator):
                await db.execute(update(InternalTicketStatement)
                                 .where(InternalTicketStatement.batch_id == result.batch_id)
                                 .values(file_url=snapshot.file_locator))
            job = await _claim(db, import_id, attempt, "saving")
            job.status, job.phase, job.error = "saved", None, None
            job.batch_id = result.batch_id
            job.processed_rows = job.total_rows
            job.result = {**result.model_dump(mode="json"), "no_vendor": no_vendor}
            await db.execute(delete(Row).where(Row.import_id == import_id))
            await db.commit()
            logger.info("import %s: saved as %s after %.1fs", import_id, result.batch_id, time.monotonic() - started)
    except HTTPException as exc:
        await fail(Session, import_id, attempt, "saving", str(exc.detail))
    except Superseded:
        raise
    except Exception as exc:  # noqa: BLE001 — said to the user; the log has the trace
        logger.exception("Internal Statement import %s could not be saved", import_id)
        await fail(Session, import_id, attempt, "saving", f"The statement could not be saved: {short_error(exc)}")


def short_error(exc: Exception) -> str:
    """An error as one line — the database's own words, not the statement it was running."""
    if isinstance(exc, DBAPIError) and exc.orig is not None:
        return str(exc.orig).split("\n")[0].split(": ", 1)[-1]
    return str(exc).split("\n")[0][:500]


# ── Housekeeping ─────────────────────────────────────────────────────────────

async def discard(db: AsyncSession, job: Job) -> None:
    """The import and its rows; the stored file too, unless it is a saved statement's."""
    locator, keep_file = job.file_locator, job.batch_id is not None
    await db.execute(delete(Job).where(Job.id == job.id))
    if not keep_file:
        try:
            await file_store.delete(locator, bucket())
        except Exception:  # noqa: BLE001 — an orphaned file must not keep the import
            logger.warning("Could not delete the stored file of import %s", job.id, exc_info=True)


async def purge_expired(db: AsyncSession) -> int:
    """Imports older than IMPORT_TTL, unless a worker is on one right now. Committed here."""
    cutoff, busy = _now() - IMPORT_TTL, _now() - timedelta(minutes=30)
    old = (await db.execute(
        select(Job).where(Job.created_at < cutoff,
                          or_(Job.heartbeat_at.is_(None), Job.heartbeat_at < busy))
        .limit(50)
    )).scalars().all()
    for job in old:
        await discard(db, job)
    await db.commit()
    return len(old)

