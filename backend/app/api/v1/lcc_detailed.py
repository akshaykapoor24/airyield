"""LCC Detailed Statement — dedicated upload wizard + scalable storage.

Flow (see frontend LccUploadWizard):
    POST /lcc-detailed/extract   -> store file to GCS, detect headers, auto-map,
                                    create a `staged` batch, return preview + mapping
    POST /lcc-detailed/confirm   -> persist the user's mapping, flip to `pending`,
                                    enqueue the Celery ingest task (HTTP 202)
    GET  /lcc-detailed/status/{batch_id}  -> poll processing progress
    GET  /lcc-detailed/records   -> paginated typed rows + folded Taxes/Segments/SSR

Mounted at top-level `/lcc-detailed` (NOT under the generic `/statements/{slug}`
catch-all). Scoped per user: every query filters tenant_id + created_by_id.
"""
from __future__ import annotations

import asyncio
import io
import uuid
from datetime import date, datetime, timedelta
from typing import NamedTuple

import pandas as pd
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, column, delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.corporate import Corporate
from app.models.customer import Customer
from app.models.lcc_batch_airline_id import LccBatchAirlineId
from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.models.lcc_detailed_batch_file import LccDetailedBatchFile
from app.models.tenant_airline import TenantAirline
from app.models.user import User
from app.services import customer_resolver as cres
from app.services import gcs
from app.services import employee_from_passenger as emp
from app.services import lcc_billing_projection as proj
from app.services import lcc_merge
from app.services import ticket_retag as retag
from app.services import lcc_detailed_spec as spec
from app.services import spreadsheet
from app.services.lcc_airline_selection import resolve_for_upload
from app.services.lcc_statement import _clean, detect_format

router = APIRouter()

_MIN_MATCHED_COLUMNS = 3
_SAMPLE_ROWS = 50

# Drill-in filters arrive as `f.<field>` (and `f.<field>.from` / `.to` for a date range),
# the same wire protocol the generic statements router uses, so adding one is a spec edit
# rather than a signature change. Unknown fields are ignored, never rejected — a stale
# bookmark should degrade, not 400.
_FILTER_PREFIX = "f."
# Facet dropdowns past this are unusable anyway; the client falls back to typing.
_MAX_FACET_VALUES = 200


def _bucket() -> str:
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _scope(model, user: User):
    return (model.tenant_id == user.tenant_id, model.created_by_id == user.id)


# ── drill-in filtering ───────────────────────────────────────────────────────
_FILTER_BY_FIELD: dict[str, dict] = {f["field"]: f for f in spec.FILTERS}
# Resolved ONCE at import, so a typo in the spec is an AttributeError at startup rather
# than a 500 in production — and so no request path ever calls getattr on user input.
# `__segments__` is excluded: it has no column, see _segments_cond.
_FILTER_COLS = {
    f["field"]: getattr(LccDetailed, f["field"])
    for f in spec.FILTERS if f["field"] != spec.SEGMENTS_FILTER_FIELD
}
_SUMMARY_COLS = {f["field"]: getattr(LccDetailed, f["field"]) for f in spec.SUMMARY_FIELDS}
# The date columns are DateTime; departure_date is a real Date. Drives the end-of-day
# handling in _date_cond, which is the one place this distinction changes the answer.
_DATE_ONLY_FIELDS = {"departure_date"}


def _like(value: str) -> str:
    """`%value%` with LIKE wildcards escaped, so a literal `_` or `%` searches for itself.

    Payment numbers and promo codes routinely contain underscores, and `_` is LIKE's
    single-character wildcard — unescaped, the search silently over-matches. Pair with
    `.ilike(pattern, escape="\\\\")`.
    """
    esc = value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{esc}%"


def _as_date(raw: str):
    """`YYYY-MM-DD` — what <input type="date"> emits — or None if it won't parse."""
    try:
        return date.fromisoformat(raw.strip()[:10])
    except (ValueError, AttributeError):
        return None


def _segments_cond(value: str):
    """Contains-match over the rendered `route flight_no` of ANY leg in `segments`.

    An EXISTS over jsonb_array_elements rather than casting the whole JSONB to text: the
    cast matches the object KEYS too, so searching "route" or "leg" would return every
    row. The string matched here is exactly what _seg_str puts in the Segments cell, so
    what you type is what you see.
    """
    seg = func.jsonb_array_elements(LccDetailed.segments).table_valued(column("value", JSONB))
    leg = seg.c.value
    return and_(
        LccDetailed.segments.isnot(None),
        select(literal(1)).select_from(seg).where(
            func.concat_ws(" ", leg["route"].astext, leg["flight_no"].astext)
            .ilike(_like(value), escape="\\")
        ).correlate(LccDetailed).exists(),
    )


def _date_cond(field: str, bound: str, value: str):
    """One end of a date range, or None if the value doesn't parse."""
    d = _as_date(value)
    if d is None:
        return None
    col = _FILTER_COLS[field]
    if field in _DATE_ONLY_FIELDS:
        return col >= d if bound == "from" else col <= d
    # DateTime column: `<= to` compares against 00:00:00 and would drop everything
    # transacted later that same day, so the upper bound is the NEXT midnight,
    # exclusive. Bare comparisons, no ::date cast, so any index still applies.
    return (col >= datetime.combine(d, datetime.min.time()) if bound == "from"
            else col < datetime.combine(d + timedelta(days=1), datetime.min.time()))


def _filter_conds(request: Request | None) -> list:
    """Declared `f.<field>` params on the request → SQLAlchemy conditions.

    The field name is only ever a dict key into the spec's allowlist, and the column comes
    from the pre-resolved _FILTER_COLS. Anything unknown, blank or unparseable is skipped
    rather than rejected — a stale bookmark should degrade, not 400.
    """
    if request is None:
        return []
    conds: list = []
    for key, raw in request.query_params.multi_items():
        if not key.startswith(_FILTER_PREFIX):
            continue
        field, _, bound = key[len(_FILTER_PREFIX):].partition(".")
        f = _FILTER_BY_FIELD.get(field)
        value = (raw or "").strip()
        if not f or not value:
            continue

        if f["type"] == "daterange":
            if bound in ("from", "to"):
                cond = _date_cond(field, bound, value)
                if cond is not None:
                    conds.append(cond)
        elif bound:
            continue          # `f.name1.from` on a non-daterange filter is malformed
        elif field == spec.SEGMENTS_FILTER_FIELD:
            conds.append(_segments_cond(value))
        elif f["type"] == "select":
            if f.get("options"):
                # Statically declared Yes/No over the `international` boolean.
                b = {"yes": True, "no": False}.get(value.lower())
                if b is not None:
                    conds.append(_FILTER_COLS[field].is_(b))
            else:
                conds.append(_FILTER_COLS[field] == value)
        else:
            conds.append(_FILTER_COLS[field].ilike(_like(value), escape="\\"))
    return conds


def _record_conds(user: User, batch_id: str | None, request: Request | None) -> list:
    """Scope + batch + whichever declared `f.<field>` filters the request carries."""
    conds = [*_scope(LccDetailed, user)]
    if batch_id:
        conds.append(LccDetailed.batch_id == batch_id)
    return conds + _filter_conds(request)


async def _tenant_airlines(
    db: AsyncSession, user: User, tenant_airline_ids: list[int]
) -> list[TenantAirline]:
    """Resolve the user's Airline Master entries for an upload.

    An LCC export carries no carrier, so this selection is the ONLY thing that
    identifies the airline. A statement may cover SEVERAL of the user's ids for that
    carrier — but not ids from two carriers; see services/lcc_airline_selection.py.
    """
    try:
        return await resolve_for_upload(db, user.tenant_id, tenant_airline_ids)
    except ValueError as exc:
        # MixedAirlineSelection and UnknownAirlineId are both ValueErrors and both
        # carry a message written for the user.
        raise HTTPException(status_code=400, detail=str(exc))


async def _stamp_airline(
    db: AsyncSession, batch: LccDetailedBatch, tas: list[TenantAirline]
) -> None:
    """Put the selection on the batch: the scalar columns from the primary (first)
    id, and the full set in the link table.

    The scalar airline_* columns stay single-valued and correct because every id in
    the selection shares one carrier — that is the whole reason for that rule.
    """
    primary = tas[0]
    batch.tenant_airline_id = primary.id
    batch.airline_id = primary.airline_id
    batch.airline_name = primary.airline_name
    batch.airline_code = primary.airline_code
    batch.airline_ref_id = primary.ref_id

    # Replace rather than merge: re-declaring the airline on a batch means "these are
    # the ids now", so an id dropped from the selection must not linger.
    await db.execute(
        delete(LccBatchAirlineId).where(LccBatchAirlineId.batch_id == batch.batch_id)
    )
    for ta in tas:
        db.add(LccBatchAirlineId(batch_id=batch.batch_id, tenant_airline_id=ta.id))


async def _batch_airline_ids(
    db: AsyncSession, batch_ids: list[str]
) -> dict[str, list[tuple[int, str]]]:
    """`{batch_id: [(tenant_airline_id, ref_id), ...]}` for a whole page of batches in
    ONE query — the batches list renders every row's id set, so a query per row would
    be an N+1 on the busiest screen in this view."""
    if not batch_ids:
        return {}
    rows = (await db.execute(
        select(LccBatchAirlineId.batch_id, TenantAirline.id, TenantAirline.ref_id)
        .join(TenantAirline, TenantAirline.id == LccBatchAirlineId.tenant_airline_id)
        .where(LccBatchAirlineId.batch_id.in_(batch_ids))
        .order_by(TenantAirline.ref_id)
    )).all()
    out: dict[str, list[tuple[int, str]]] = {}
    for batch_id, ta_id, ref_id in rows:
        out.setdefault(batch_id, []).append((ta_id, ref_id))
    return out


async def _batch_files(db: AsyncSession, batch_ids: list[str]) -> dict[str, list[dict]]:
    """`{batch_id: [{role, source_file, has_file}, ...]}` for a whole page in ONE
    query — the uploads list renders every row, so a query per row would be an N+1 on
    the busiest screen in this view. Same reasoning as `_batch_airline_ids`."""
    if not batch_ids:
        return {}
    rows = (await db.execute(
        select(LccDetailedBatchFile)
        .where(LccDetailedBatchFile.batch_id.in_(batch_ids))
        .order_by(LccDetailedBatchFile.role)
    )).scalars().all()
    out: dict[str, list[dict]] = {}
    for f in rows:
        out.setdefault(f.batch_id, []).append({
            "role": f.role, "source_file": f.source_file,
            "has_file": bool(f.file_url), "row_count": f.row_count,
        })
    return out


async def _batch_file(
    db: AsyncSession, batch: LccDetailedBatch, role: str | None
) -> tuple[str | None, str, int]:
    """(file_url, source_file, header_row) for one role, or the batch's primary file.

    Falls back to the batch scalars when no role is asked for, or when the batch
    predates the child table — those still have exactly one file, described there.
    """
    rows = (await db.execute(
        select(LccDetailedBatchFile).where(LccDetailedBatchFile.batch_id == batch.batch_id)
    )).scalars().all()
    if role:
        match = next((f for f in rows if f.role == role), None)
        if match is None:
            raise HTTPException(
                status_code=404, detail=f"This upload has no {role} file.")
        return match.file_url, match.source_file or "", match.header_row or 0
    return batch.file_url, batch.source_file or "", batch.header_row or 0


def _progress_pct(b: LccDetailedBatch) -> int:
    if b.status == "completed":
        return 100
    if b.total_rows:
        return min(100, int(b.processed_rows * 100 / b.total_rows))
    return 0


def _read_df(content: bytes, filename: str, header_row: int, nrows: int | None = None) -> pd.DataFrame:
    """Delegates to services/spreadsheet.py, which decides the format from the bytes.

    The CSV trailing-delimiter fix that used to live here (index_col=False, or pandas
    steals the first column as an index and shifts every value left) moved there with
    it, so the worker's copy of this reader cannot drift away from it.
    """
    return spreadsheet.read_df(content, filename, header_row, nrows=nrows)


_ROLE_LABEL = {
    lcc_merge.ROLE_ACCOUNT: "account statement",
    lcc_merge.ROLE_PAX: "passenger report",
    lcc_merge.ROLE_SINGLE: "LCC Detailed statement",
}


class Detected(NamedTuple):
    """One uploaded file, read and identified."""
    role: str
    filename: str
    content: bytes
    df: pd.DataFrame
    columns: list[str]
    header_row: int
    matched: int


def _detect_df(content: bytes, filename: str) -> Detected:
    """Read a file, find its header row, and identify which kind of statement it is.

    Header detection is delegated to ``spreadsheet.read_table``, which scans 25 rows
    (rather than the three this used to try), reads the grid ONCE, and already knows
    how to skip the title/period/company lines an airline portal puts above its
    header. `recognise` is what steers it: the row that maps onto the most standard
    columns is the header.

    The acceptance gate is per ROLE. A file that classifies as an account statement or
    a passenger report has already proved itself through headers only that kind of file
    has, so demanding three *IndiGo* columns of it — and naming them in the error —
    would be both wrong and unhelpful. A passenger report clears that generic bar by a
    single column as it is.
    """
    try:
        res = spreadsheet.read_table(
            content, filename,
            recognise=lambda headers: spec.suggest_mapping([str(h) for h in headers])[1],
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Could not read the file: {e}. Upload a valid .xlsx, .xls or .csv.",
        )

    cols = [str(c) for c in res.columns]
    _, matched, _ = spec.suggest_mapping(cols)
    role = lcc_merge.classify(cols)

    missing = lcc_merge.missing_required(role, cols)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"“{filename}” looks like an {_ROLE_LABEL[role]}, but it is missing "
                   f"{' and '.join(missing)}.",
        )
    if role == lcc_merge.ROLE_SINGLE and matched < _MIN_MATCHED_COLUMNS:
        sample = ", ".join(spec.LCC_STANDARD_HEADERS[:5])
        raise HTTPException(
            status_code=400,
            detail=f"This doesn't look like an LCC Detailed statement — only {matched} known "
                   f"column(s) were recognised. Expected headers such as: {sample}…",
        )
    return Detected(role=role, filename=filename, content=content, df=res.df,
                    columns=cols, header_row=res.header_row, matched=matched)


def _seg_str(s: dict) -> str:
    return f"{s.get('route') or ''} {s.get('flight_no') or ''}".strip()


def _disp(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return str(v)


def _money_str(value) -> str | None:
    """Serialize a summed Decimal as a string — a float round-trip would lose paise."""
    return None if value is None else format(value.normalize(), "f")


# ── mapping / metadata ───────────────────────────────────────────────────────
@router.get("/standard-columns")
async def standard_columns(current_user: User = Depends(get_current_user)):
    """Grouped standard column spec for the mapping UI."""
    return {"groups": spec.grouped_columns(), "total": len(spec.LCC_STANDARD_COLUMNS)}


@router.get("/template")
async def download_template(current_user: User = Depends(get_current_user)):
    """Blank .xlsx with the exact 129 standard headers."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "LCC Detailed Template"
    ws.append(spec.LCC_STANDARD_HEADERS)

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="lcc_detailed_template.xlsx"'},
    )


# ── extract → confirm ────────────────────────────────────────────────────────
# Which file's block is echoed at the top level for a client that only understands one.
# The ACCOUNT statement wins on a merged upload: it is the spine — one imported row per
# transaction — and its mapping is the one that decides what gets billed.
_PRIMARY_ROLE_ORDER = (lcc_merge.ROLE_ACCOUNT, lcc_merge.ROLE_SINGLE, lcc_merge.ROLE_PAX)
# How many SPINE rows to merge for the preview. The passenger file is read whole
# regardless — it is the lookup, and truncating it would leave sampled transactions
# looking unmatched when they are not.
_SAMPLE_SOURCE_ROWS = 2000


def _rows_of(df: pd.DataFrame) -> list[dict]:
    return [{str(k): v for k, v in row.items()} for _, row in df.iterrows()]


def _validate_combination(detected: list[Detected]) -> None:
    """Reject the file pairs that cannot be merged, saying which they are.

    A silent misclassification is the worst outcome here: it produces a batch that
    looks plausible and is wrong, so every rejected shape names what was seen.
    """
    roles = [d.role for d in detected]
    for role in set(roles):
        if roles.count(role) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"Both files look like the same thing — an {_ROLE_LABEL[role]}. "
                       f"Upload one account statement and one passenger report.",
            )
    if len(detected) == 2 and lcc_merge.ROLE_SINGLE in roles:
        other = next(d for d in detected if d.role != lcc_merge.ROLE_SINGLE)
        raise HTTPException(
            status_code=400,
            detail=f"“{next(d.filename for d in detected if d.role == lcc_merge.ROLE_SINGLE)}” is a "
                   f"standard LCC Detailed statement and “{other.filename}” is an "
                   f"{_ROLE_LABEL[other.role]}. Those two can't be merged — upload them separately.",
        )


def _file_block(d: Detected, *, with_account: bool, with_pax: bool,
                merged_rows: list[dict]) -> dict:
    """The mapping pane for one file: its columns, the auto-mapping, and real rows.

    The columns and sample shown are POST-merge, so the user maps what will actually
    be ingested — for the account statement that means its own columns plus the
    passenger, base fare, derived tax and legs the passenger file joins in. Those
    added columns are named after standard template headers precisely so
    `suggest_mapping` resolves them here with no special-casing.

    A passenger file uploaded ALONGSIDE an account file produces no rows of its own —
    it is a lookup — so its pane is informational and carries no sample.
    """
    if d.role == lcc_merge.ROLE_ACCOUNT:
        # The spine. Its own headers plus what the passenger file joins in.
        cols = lcc_merge.account_columns_after_merge(d.columns, with_pax=with_pax)
    elif d.role == lcc_merge.ROLE_PAX and not with_account:
        # A passenger file on its own imports as an ordinary statement, reshaped.
        cols = lcc_merge.pax_columns_after_reshape(d.columns, with_account=False)
    else:
        cols = d.columns
    mapping, matched_columns, is_template_match = spec.suggest_mapping(cols)
    return {
        "role": d.role,
        "role_label": _ROLE_LABEL[d.role],
        "file_name": d.filename,
        "header_row": d.header_row,
        "source_rows": int(len(d.df)),
        "xls_columns": cols,
        "suggested_mapping": mapping,
        "sample_rows": [{c: row.get(c) for c in cols} for row in merged_rows[:_SAMPLE_ROWS]],
        "matched_columns": matched_columns,
        "is_template_match": is_template_match,
    }


@router.post("/extract")
async def extract(
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
    tenant_airline_ids: list[int] = Form(default=[]),
    tenant_airline_id: int | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store the file(s), detect headers, auto-map, and stage a batch. Nothing is
    ingested yet — the user reviews the mapping, then calls /confirm.

    ONE file is the ordinary case. TWO are accepted because an Air India Express
    statement is issued as an account file plus a passenger file that only mean
    anything joined on PNR; which is which is decided from their headers, so the order
    they are dropped in does not matter. Both are staged under one batch, because
    creating the batch once is what keeps the airline validated once and leaves no
    half-made upload behind if the second file is rejected.

    The airline selection is required and resolved here rather than at /confirm, so a
    batch is never in a state where rows could be ingested without an airline. Several
    ids may be sent — one statement usually covers more than one of the user's logins
    for that carrier — but they must all be the same airline.

    `file` (singular) and `tenant_airline_id` (singular) are both still accepted so a
    client that has not picked up the newer fields cannot suddenly 422 mid-upload."""
    picked = list(tenant_airline_ids)
    if tenant_airline_id is not None and tenant_airline_id not in picked:
        picked.append(tenant_airline_id)
    tas = await _tenant_airlines(db, current_user, picked)
    ta = tas[0]

    uploads = [f for f in (files or []) if f is not None and f.filename]
    if file is not None and file.filename:
        uploads.append(file)
    if not uploads:
        raise HTTPException(status_code=400, detail="Choose a statement file to upload.")
    if len(uploads) > 2:
        raise HTTPException(
            status_code=400,
            detail="An LCC statement is one file, or two when the airline splits it into "
                   "an account statement and a passenger report.",
        )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    detected: list[Detected] = []
    for up in uploads:
        content = await up.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"“{up.filename}” exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit.",
            )
        if not content:
            raise HTTPException(status_code=400, detail=f"“{up.filename}” is empty.")
        detected.append(_detect_df(content, up.filename or ""))
    _validate_combination(detected)

    by_role = {d.role: d for d in detected}
    acct = by_role.get(lcc_merge.ROLE_ACCOUNT)
    pax = by_role.get(lcc_merge.ROLE_PAX)

    # Preview rows. A `single` file is shown exactly as it reads; the other two go
    # through the merge, so what the user maps is what will be stored. Only the SPINE
    # is capped — the passenger file is read whole, because truncating a lookup makes
    # matched transactions look unmatched.
    merged_by_role: dict[str, list[dict]] = {}
    if pax is not None or acct is not None:
        rows, _stats = lcc_merge.merge(
            _rows_of(pax.df) if pax is not None else [],
            pax.columns if pax is not None else [],
            _rows_of(acct.df.head(_SAMPLE_SOURCE_ROWS)) if acct is not None else [],
            acct.columns if acct is not None else [],
            airline_code=ta.airline_code,
        )
        for r in rows:
            merged_by_role.setdefault(r.role, []).append(r.data)
    for d in detected:
        if d.role == lcc_merge.ROLE_SINGLE:
            merged_by_role[d.role] = [
                {str(c): _clean(row[c]) for c in d.columns}
                for _, row in d.df.head(_SAMPLE_ROWS).iterrows()
            ]

    with_account, with_pax = acct is not None, pax is not None
    blocks = {d.role: _file_block(d, with_account=with_account, with_pax=with_pax,
                                  merged_rows=merged_by_role.get(d.role, []))
              for d in detected}
    primary = next(r for r in _PRIMARY_ROLE_ORDER if r in blocks)
    head = blocks[primary]

    if len(detected) == 2:
        source_format = "lcc-merged"
    elif primary == lcc_merge.ROLE_SINGLE:
        source_format = detect_format(by_role[primary].columns)
    else:
        source_format = f"lcc-{primary}"

    batch_id = str(uuid.uuid4())
    # Store the source files — REQUIRED (the worker re-downloads them). Hard-fail
    # otherwise. The role segment in the path matters: the two halves of one export are
    # routinely named alike, and a flat path would have the second overwrite the first.
    for d in detected:
        blob = f"lcc-detailed/{current_user.tenant_id}/{batch_id}/{d.role}/{d.filename}"
        try:
            await gcs.upload_bytes(d.content, blob, "application/octet-stream", _bucket())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Could not store “{d.filename}”: {exc}")
        blocks[d.role]["file_url"] = blob

    source_rows = sum(int(len(d.df)) for d in detected)
    batch = LccDetailedBatch(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        # The scalars still describe the PRIMARY file, so every reader written before
        # the child table — /file-url, /viewer-url, the batches list — keeps working.
        source_file=by_role[primary].filename,
        file_url=head["file_url"],
        source_format=source_format,
        header_row=by_role[primary].header_row,
        column_map=head["suggested_mapping"],
        status="staged",
        # Source lines for now; the worker replaces total_rows with the number of rows
        # it actually writes, which a merge makes smaller.
        total_rows=source_rows,
        source_rows=source_rows,
        merge_version=lcc_merge.MERGE_VERSION,
        processed_rows=0,
        matched_columns=head["matched_columns"],
        uploaded_at=datetime.utcnow(),
    )
    db.add(batch)
    for d in detected:
        b = blocks[d.role]
        db.add(LccDetailedBatchFile(
            batch_id=batch_id, role=d.role, source_file=d.filename,
            file_url=b["file_url"], header_row=d.header_row,
            column_map=b["suggested_mapping"], xls_columns=b["xls_columns"],
            row_count=b["source_rows"],
        ))
    # After db.add: _stamp_airline writes the link rows, whose FK is the batch.
    await _stamp_airline(db, batch, tas)
    await db.commit()

    return {
        "batch_id": batch_id,
        "airline_name": ta.airline_name,
        "airline_code": ta.airline_code,
        "airline_ref_id": ta.ref_id,
        "airline_ref_ids": [t.ref_id for t in tas],
        "tenant_airline_ids": [t.id for t in tas],
        "source_format": source_format,
        "source_rows": source_rows,
        "standard_total": len(spec.LCC_STANDARD_COLUMNS),
        "primary_role": primary,
        "files": [blocks[d.role] for d in detected],
        # Flattened primary, for a client that predates the per-file blocks.
        "file_name": head["file_name"],
        "total_rows": source_rows,
        "header_row": head["header_row"],
        "xls_columns": head["xls_columns"],
        "suggested_mapping": head["suggested_mapping"],
        "sample_rows": head["sample_rows"],
        "is_template_match": head["is_template_match"],
        "matched_columns": head["matched_columns"],
    }


class ConfirmPayload(BaseModel):
    batch_id: str
    # One map per file, keyed by role. `column_map` (singular) is still accepted and
    # applies to the primary file, so a client that predates the two-file upload keeps
    # working unchanged.
    column_maps: dict[str, dict[str, str]] | None = None
    column_map: dict[str, str] | None = None
    expected_rows: int | None = None   # user-declared expected record count (optional)


@router.post("/confirm", status_code=status.HTTP_202_ACCEPTED)
async def confirm(
    payload: ConfirmPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist the confirmed mapping(s) and enqueue background ingestion."""
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == payload.batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if batch.status != "staged":
        raise HTTPException(status_code=409, detail=f"This upload is already '{batch.status}'.")

    file_rows = (await db.execute(
        select(LccDetailedBatchFile).where(LccDetailedBatchFile.batch_id == batch.batch_id)
    )).scalars().all()

    # Keep only mappings that point at a real standard field.
    valid_fields = {c["field"] for c in spec.LCC_STANDARD_COLUMNS}

    def _clean_map(raw: dict[str, str] | None) -> dict[str, str] | None:
        if raw is None:
            return None
        return {k: v for k, v in raw.items() if k in valid_fields and v}

    incoming = {role: _clean_map(m) for role, m in (payload.column_maps or {}).items()}
    primary_map = _clean_map(payload.column_map)

    # The singular map addresses the primary file — the one whose mapping the batch's
    # own `column_map` column mirrors.
    primary_role = next(
        (r for r in _PRIMARY_ROLE_ORDER if any(f.role == r for f in file_rows)), None
    )
    if primary_map is not None and primary_role and primary_role not in incoming:
        incoming[primary_role] = primary_map

    unknown = set(incoming) - {f.role for f in file_rows}
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"This upload has no {', '.join(sorted(unknown))} file.",
        )

    for f in file_rows:
        if f.role in incoming:
            f.column_map = incoming[f.role]
        if f.role == primary_role:
            batch.column_map = f.column_map or {}
            batch.matched_columns = len(batch.column_map)

    # A batch staged before the child table existed has no file rows; fall back to the
    # scalar so those can still be re-confirmed.
    if not file_rows and primary_map is not None:
        batch.column_map = primary_map
        batch.matched_columns = len(primary_map)

    batch.expected_rows = payload.expected_rows if (payload.expected_rows or 0) > 0 else None
    batch.status = "pending"
    batch.error = None
    await db.commit()   # commit BEFORE enqueue so the worker can't 404 on its own batch

    from app.workers.lcc_tasks import ingest_lcc_detailed
    ingest_lcc_detailed.delay(payload.batch_id, current_user.tenant_id, current_user.id)

    return {"batch_id": payload.batch_id, "status": "pending", "total_rows": batch.total_rows}


@router.get("/status/{batch_id}")
async def get_status(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return {
        "batch_id": batch.batch_id,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "processed_rows": batch.processed_rows,
        "expected_rows": batch.expected_rows,
        # Lines READ, as against total_rows = rows WRITTEN. A merge collapses
        # passenger-per-segment lines into passenger rows, so the two differ and the
        # wizard's "expected records" check has to compare against this one — against
        # the other, every merged upload would end on a false "N records missing".
        "source_rows": batch.source_rows,
        "merge_stats": batch.merge_stats,
        "progress_pct": _progress_pct(batch),
        "matched_columns": batch.matched_columns,
        "error": batch.error,
        "source_file": batch.source_file,
        "completed_at": batch.completed_at,
    }


# ── batches / records ────────────────────────────────────────────────────────
@router.get("/batches")
async def list_batches(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per upload, straight from the header table (no GROUP BY)."""
    rows = (await db.execute(
        select(LccDetailedBatch)
        .where(*_scope(LccDetailedBatch, current_user))
        .order_by(LccDetailedBatch.uploaded_at.desc())
    )).scalars().all()
    links = await _batch_airline_ids(db, [b.batch_id for b in rows])
    files = await _batch_files(db, [b.batch_id for b in rows])
    return [
        {
            "batch_id": b.batch_id,
            "source_file": b.source_file,
            "uploaded_at": b.uploaded_at,
            "completed_at": b.completed_at,
            "status": b.status,
            "total_rows": b.total_rows,
            "processed_rows": b.processed_rows,
            "expected_rows": b.expected_rows,
            "source_rows": b.source_rows,
            "merge_stats": b.merge_stats,
            "progress_pct": _progress_pct(b),
            "row_count": b.processed_rows if b.status == "completed" else b.total_rows,
            "has_file": bool(b.file_url),
            # Every source file behind this upload. `source_file` / `has_file` above
            # still describe the primary one, because that is what the uploads table
            # reads today — this is additive.
            "files": files.get(b.batch_id, []),
            "created_by_name": current_user.full_name,
            "airline_name": b.airline_name,
            "airline_code": b.airline_code,
            "airline_ref_id": b.airline_ref_id,
            "tenant_airline_id": b.tenant_airline_id,
            # The full set this upload covers. Falls back to the primary columns for a
            # batch that predates the link table and was never re-saved.
            "airline_ref_ids": (
                [ref for _, ref in links[b.batch_id]] if b.batch_id in links
                else ([b.airline_ref_id] if b.airline_ref_id else [])
            ),
            "tenant_airline_ids": (
                [tid for tid, _ in links[b.batch_id]] if b.batch_id in links
                else ([b.tenant_airline_id] if b.tenant_airline_id else [])
            ),
            "billable_rows": b.billable_rows,
            "resolved_rows": b.resolved_rows,
            "unresolved_rows": b.unresolved_rows,
            "projected_rows": b.projected_rows,
            "resolution_status": b.resolution_status,
        }
        for b in rows
    ]


class BatchAirlinePayload(BaseModel):
    # Several ids may be sent — one statement usually covers more than one of the
    # user's logins for that carrier. The singular field is still accepted so an
    # older client keeps working; see extract() for the same pairing.
    tenant_airline_ids: list[int] = []
    tenant_airline_id: int | None = None

    def picked(self) -> list[int]:
        out = list(self.tenant_airline_ids)
        if self.tenant_airline_id is not None and self.tenant_airline_id not in out:
            out.append(self.tenant_airline_id)
        return out


@router.patch("/batches/{batch_id}/airline")
async def set_batch_airline(
    batch_id: str,
    payload: BatchAirlinePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set (or correct) the airline on an already-uploaded batch.

    Batches imported before the airline was captured have none, and the rows parsed
    correctly — only the carrier was missing. So this stamps the header and issues one
    indexed bulk UPDATE over the rows rather than re-uploading or re-ingesting."""
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")

    tas = await _tenant_airlines(db, current_user, payload.picked())
    ta = tas[0]
    await _stamp_airline(db, batch, tas)

    result = await db.execute(
        update(LccDetailed)
        .where(LccDetailed.batch_id == batch_id, *_scope(LccDetailed, current_user))
        .values(
            airline_id=ta.airline_id,
            airline_name=ta.airline_name,
            airline_code=ta.airline_code,
        )
    )
    await db.commit()

    return {
        "batch_id": batch_id,
        "airline_name": ta.airline_name,
        "airline_code": ta.airline_code,
        "airline_ref_id": ta.ref_id,
        "airline_ref_ids": [t.ref_id for t in tas],
        "tenant_airline_ids": [t.id for t in tas],
        "rows_updated": result.rowcount or 0,
    }


# ── billing: resolve each row to a customer / corporate ──────────────────────
# An LCC export names no customer, only a passenger per row. These endpoints resolve
# that passenger against the Customer master so the rows can later be projected into
# `uploaded_tickets`, the one table Customer/Corporate Billing reads.

MAX_GAP_GROUPS = 50          # mirrors api/v1/bsp_commission.py:54
_BILL_PARTY_TYPES = ("corporate", "direct")

# How many hand-picked rows one call may carry. 500 matches bsp_commission's
# MAX_INLINE_ROWS; the cap exists because project_batch flushes per inserted row, so a
# selection is a quick action rather than a full run in disguise. The two are kept EQUAL
# so a "select all matching" can always be posted back in one call.
MAX_SEND_ROWS = 500
MAX_BILLING_SELECT_IDS = 500


def _bill_kind(total) -> str:
    """Classify a row from `total`, NOT `base_fare`.

    A fee-only row (no-show, seat, PSFR/UDFR re-charge) has base_fare 0 but real money
    in total, and a change fee can exceed a fare refund and flip the row's sign — on
    one real 203-row statement, classifying on base_fare drops 24 rows worth ₹13,581
    and mis-signs another. `total = 0` is a payment movement: money moved between
    accounts, no fare, nothing to bill.
    """
    if total is None or total == 0:
        return "payment"
    return "sale" if total > 0 else "refund"


async def _resolve_bill_party(
    db: AsyncSession, user: User,
    customer_type: str | None, customer_id: int | None, corporate_id: int | None,
    *, upgrade_employee: bool = True,
) -> tuple[str | None, int | None, int | None]:
    """Authorise a party against the master rather than trusting the ids sent.

    Mirrors tickets.py::_resolve_customer_party. Returns the normalised triple, with
    the ids that do not belong to the chosen type nulled — the same discipline as
    frontend lib/customerType.ts::buildTagPayload, enforced server-side so a stale id
    from a previously chosen type can never travel attached to the wrong one.

    `upgrade_employee` (default True, the LCC resolver's behaviour) turns a picked
    customer who belongs to a corporate into a 'corporate' tag carrying BOTH ids, so
    the employer can bill their employee's ticket. Pass False when the caller means
    the party literally — re-tagging a ticket to bill an employee DIRECTLY has to
    leave the corporate out, or the ticket stays claimable by the employer and the
    correction the user asked for silently does nothing.
    """
    ct = (customer_type or "").strip().lower() or None
    if ct is None:
        return None, None, None
    if ct not in _BILL_PARTY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=("An LCC statement bills a customer or a corporate. Agency billing "
                    "claims tickets through their statement, not through this link."),
        )

    if ct == "corporate":
        if not corporate_id:
            raise HTTPException(status_code=400, detail="Pick a corporate.")
        row = (await db.execute(select(Corporate).where(
            Corporate.id == corporate_id,
            Corporate.tenant_id == user.tenant_id,
            Corporate.created_by_id == user.id,
        ))).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=400, detail=f"Corporate id {corporate_id} is not in your corporates.")
        # A customer may also be named, when the row resolved to an employee.
        # Validated here; whether it is CARRIED is retag.derive_party's call.
        cust_id = None
        if customer_id:
            cust = (await db.execute(select(Customer).where(
                Customer.id == customer_id,
                Customer.tenant_id == user.tenant_id,
                Customer.created_by_id == user.id,
            ))).scalar_one_or_none()
            if not cust:
                raise HTTPException(status_code=400, detail=f"Customer id {customer_id} is not in your customers.")
            cust_id = cust.id
        return retag.derive_party(
            "corporate", cust_id, row.id, upgrade_employee=upgrade_employee,
        )

    if not customer_id:
        raise HTTPException(status_code=400, detail="Pick a customer.")
    cust = (await db.execute(select(Customer).where(
        Customer.id == customer_id,
        Customer.tenant_id == user.tenant_id,
        Customer.created_by_id == user.id,
    ))).scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=400, detail=f"Customer id {customer_id} is not in your customers.")
    # A customer who belongs to a corporate is an employee — services/ticket_retag
    # decides whether to carry the employer, since that is the same rule the
    # re-tag endpoint needs and it must not exist in two places.
    return retag.derive_party(
        "direct", cust.id, None,
        employee_corporate_id=cust.corporate_id,
        upgrade_employee=upgrade_employee,
    )


async def _owned_batch(batch_id: str, db: AsyncSession, current_user: User) -> LccDetailedBatch:
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return batch


async def _status_counts(db: AsyncSession, batch_id: str) -> dict[str, int]:
    """`{bill_status: n}` for one batch — the chips' source, and _recount's."""
    rows = (await db.execute(
        select(LccDetailed.bill_status, func.count())
        .where(LccDetailed.batch_id == batch_id)
        .group_by(LccDetailed.bill_status)
    )).all()
    return {s: n for s, n in rows}


async def _billing_state_counts(db: AsyncSession, batch_id: str) -> dict[str, int]:
    """`{billing_state: n}` for one batch, over the same LEFT JOIN billing-rows uses.

    Every state in one round trip via COUNT(*) FILTER (WHERE …) rather than seven
    queries. Scoped exactly like _status_counts — on batch_id alone, because the caller
    has already proved the batch is theirs through _owned_batch.

    Deliberately NOT narrowed by the caller's filters: this drives header counts, which
    must hold still while you page and search rather than re-describing the filter you
    just typed.
    """
    from app.models.uploaded_ticket import UploadedTicket

    T = aliased(UploadedTicket)
    row = (await db.execute(
        select(*[
            func.count().filter(proj.billing_state_cond(s, T)).label(s)
            for s in proj.BILLING_STATES
        ])
        .select_from(LccDetailed)
        .outerjoin(T, T.id == LccDetailed.projected_ticket_id)
        .where(LccDetailed.batch_id == batch_id)
    )).one()
    return {s: getattr(row, s) or 0 for s in proj.BILLING_STATES}


async def _recount(db: AsyncSession, batch: LccDetailedBatch) -> None:
    """Refresh the batch's billing counters from its rows."""
    billable = (cres.RESOLVED, cres.DEFAULTED, cres.OVERRIDDEN)
    counts = await _status_counts(db, batch.batch_id)
    batch.resolved_rows = sum(counts.get(s, 0) for s in billable)
    batch.unresolved_rows = sum(
        n for s, n in counts.items() if s not in billable and s != cres.EXCLUDED
    )
    batch.billable_rows = batch.resolved_rows + batch.unresolved_rows
    batch.projected_rows = await db.scalar(
        select(func.count()).select_from(LccDetailed)
        .where(LccDetailed.batch_id == batch.batch_id,
               LccDetailed.projected_ticket_id.isnot(None))
    ) or 0


class ResolvePayload(BaseModel):
    # A human's pick is the most authoritative thing on the row, so a re-run keeps it
    # unless the caller explicitly says otherwise.
    reset_overrides: bool = False


@router.post("/batches/{batch_id}/resolve-customers")
async def resolve_customers(
    batch_id: str,
    payload: ResolvePayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Classify every row and match its GST party, then its passenger, against the
    Customer master."""
    payload = payload or ResolvePayload()
    batch = await _owned_batch(batch_id, db, current_user)
    if batch.status != "completed":
        raise HTTPException(status_code=409, detail="This upload is still importing.")

    index = await cres.CustomerIndex.load(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id
    )
    rows = (await db.execute(
        select(LccDetailed.id, LccDetailed.name1, LccDetailed.total,
               LccDetailed.bill_status, LccDetailed.gst_number)
        .where(LccDetailed.batch_id == batch_id, *_scope(LccDetailed, current_user))
    )).all()

    now = datetime.utcnow()
    default_set = bool(batch.default_customer_type)
    updates: list[dict] = []
    summary: dict[str, int] = {}

    for row_id, name1, total, current_status, gst_number in rows:
        kind = _bill_kind(total)

        if not payload.reset_overrides and current_status == cres.OVERRIDDEN and kind != "payment":
            summary[cres.OVERRIDDEN] = summary.get(cres.OVERRIDDEN, 0) + 1
            updates.append({"id": row_id, "bill_kind": kind})
            continue

        if kind == "payment":
            m = cres.CustomerMatch(status=cres.EXCLUDED, note=cres.REASON[cres.EXCLUDED])
        else:
            # The GSTIN the airline printed on the booking is tried first — it names
            # the party exactly, where the passenger name only matches if that person
            # happens to be on the master. Falls through to the name when the file
            # carries no GSTIN or the master does not know it.
            m = index.resolve(name1, gstin=gst_number)
            if m.status == cres.UNRESOLVED and default_set:
                # The batch fallback is the primary path in practice: an LCC export's
                # passengers rarely overlap the Customer master at all.
                m = cres.CustomerMatch(
                    status=cres.DEFAULTED,
                    customer_id=batch.default_customer_id,
                    corporate_id=batch.default_corporate_id,
                    customer_type=batch.default_customer_type,
                    display_name=(name1 or "").strip(),
                    note="Billed to this upload's default party.",
                )

        summary[m.status] = summary.get(m.status, 0) + 1
        updates.append({
            "id": row_id,
            "bill_kind": kind,
            "bill_status": m.status,
            "bill_customer_type": m.customer_type,
            "bill_customer_id": m.customer_id,
            "bill_corporate_id": m.corporate_id,
            "bill_match_reason": m.note,
            "resolved_at": now,
            "resolved_by_id": current_user.id,
        })

    if updates:
        await db.execute(update(LccDetailed), updates)

    batch.resolution_status = "projected" if batch.resolution_status == "projected" else "resolved"
    await _recount(db, batch)
    await db.commit()

    return await _billing_summary(db, batch, customers_in_scope=len(index), summary=summary)


async def _billing_summary(
    db: AsyncSession, batch: LccDetailedBatch, *,
    customers_in_scope: int, summary: dict[str, int] | None = None,
) -> dict:
    """The worklist's header, in one shape.

    Returned by both `resolve-customers` (which has just recomputed `summary` in memory)
    and the read-only `billing-summary`, so the frontend has one type and one setter for
    the chips no matter which call refreshed them.
    """
    return {
        "batch_id": batch.batch_id,
        "customers_in_scope": customers_in_scope,
        "summary": summary if summary is not None else await _status_counts(db, batch.batch_id),
        "state_counts": await _billing_state_counts(db, batch.batch_id),
        "billable_rows": batch.billable_rows,
        "resolved_rows": batch.resolved_rows,
        "unresolved_rows": batch.unresolved_rows,
        "projected_rows": batch.projected_rows,
        "resolution_status": batch.resolution_status,
    }


@router.get("/batches/{batch_id}/billing-summary")
async def billing_summary(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What `resolve-customers` returns, WITHOUT resolving anything.

    The worklist needs these counts every time it opens and after every edit. Getting
    them from the POST meant that merely looking at the screen re-matched every row —
    which, on an upload already sent to billing, could silently re-point a row billing
    already sees. This is the read-only way to ask.

    `customers_in_scope` is a plain count rather than len(CustomerIndex): its one
    consumer only tests it against zero, to say "your Customer master is empty".
    """
    batch = await _owned_batch(batch_id, db, current_user)
    in_scope = await db.scalar(
        select(func.count()).select_from(Customer).where(*_scope(Customer, current_user))
    ) or 0
    return await _billing_summary(db, batch, customers_in_scope=in_scope)


_BILLING_STATE_PATTERN = "^(" + "|".join((*proj.BILLING_STATES, "sendable")) + ")$"


@router.get("/batches/{batch_id}/billing-rows")
async def list_billing_rows(
    batch_id: str,
    status_filter: str | None = Query(None, alias="status"),
    billing_state: str | None = Query(None, pattern=_BILLING_STATE_PATTERN),
    q: str | None = Query(None, max_length=100),
    kind: str | None = Query(None),
    ids_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The resolution worklist, paginated like /records.

    Two independent filters, because they answer two different questions: `status` is
    the row's MATCH status (does it have a party?) and `billing_state` is where it has
    got to on its way into billing. A row can be "Set by you" and "Ready to send" at the
    same time, so these are never merged into one param.

    `ids_only=true` returns just the matching ids, capped, for the "select all N
    matching" affordance. It lives on this endpoint rather than a sibling so the ids can
    only ever come from the same predicate builder as the visible page.
    """
    from app.models.uploaded_ticket import UploadedTicket

    await _owned_batch(batch_id, db, current_user)

    # The join is 1:1 — T.id is a primary key and projected_ticket_id is a FK to it — so
    # the COUNT over base.subquery() below cannot fan out. Do not "fix" it with DISTINCT.
    # UploadedTicket needs no _scope of its own: it is reachable only through
    # projected_ticket_id, which this same scoped pipeline is the only writer of.
    T = aliased(UploadedTicket)
    base = (select(LccDetailed, T)
            .outerjoin(T, T.id == LccDetailed.projected_ticket_id)
            .where(LccDetailed.batch_id == batch_id, *_scope(LccDetailed, current_user)))
    if status_filter:
        base = base.where(LccDetailed.bill_status == status_filter)
    if kind:
        base = base.where(LccDetailed.bill_kind == kind)
    if billing_state:
        base = base.where(proj.billing_state_cond(billing_state, T))
    if q and q.strip():
        # One box over both identities a user has to hand. _like escapes the LIKE
        # wildcards, which matters here: PNRs and payment refs carry underscores.
        pattern = _like(q.strip())
        base = base.where(or_(
            LccDetailed.name1.ilike(pattern, escape="\\"),
            LccDetailed.record_locator.ilike(pattern, escape="\\"),
        ))

    # Narrowed to the id before counting: the subquery would otherwise carry all ~130
    # columns of both tables for no reason. The join is 1:1 on a PK so the count is
    # unaffected either way.
    total = await db.scalar(
        select(func.count()).select_from(base.with_only_columns(LccDetailed.id).subquery())
    ) or 0

    if ids_only:
        ids = (await db.execute(
            base.with_only_columns(LccDetailed.id)
            .order_by(LccDetailed.id.asc()).limit(MAX_BILLING_SELECT_IDS)
        )).scalars().all()
        return {"total": total, "ids": list(ids), "truncated": total > len(ids)}

    pairs = (await db.execute(
        base.order_by(LccDetailed.id.asc()).limit(limit).offset(offset)
    )).all()
    rows = [r for r, _t in pairs]
    tickets = {r.id: t for r, t in pairs}

    # Resolve the party names for display in one query rather than per row. The id sets
    # carry the TICKET's party as well as the row's, so a stale row can name both.
    cust_ids = {r.bill_customer_id for r in rows if r.bill_customer_id}
    corp_ids = {r.bill_corporate_id for r in rows if r.bill_corporate_id}
    cust_ids |= {t.customer_id for t in tickets.values() if t is not None and t.customer_id}
    corp_ids |= {t.corporate_id for t in tickets.values() if t is not None and t.corporate_id}
    cust_names = dict((await db.execute(
        select(Customer.id, func.concat(Customer.first_name, " ", func.coalesce(Customer.last_name, "")))
        .where(Customer.id.in_(cust_ids or {-1}))
    )).all())
    corp_names = dict((await db.execute(
        select(Corporate.id, Corporate.company).where(Corporate.id.in_(corp_ids or {-1}))
    )).all())

    def _party_name(ct: str | None, cust_id: int | None, corp_id: int | None):
        if ct == "corporate":
            return corp_names.get(corp_id)
        return (cust_names.get(cust_id) or "").strip() or None

    def _row(r):
        t = tickets.get(r.id)
        state = proj.billing_state(r, t)
        return {
            "id": r.id,
            "passenger": r.name1,
            "record_locator": r.record_locator,
            "transaction_date": r.transaction_date,
            "departure_date": r.departure_date,
            "total": float(r.total) if r.total is not None else None,
            "base_fare": float(r.base_fare) if r.base_fare is not None else None,
            "bill_kind": r.bill_kind,
            "bill_status": r.bill_status,
            "bill_customer_type": r.bill_customer_type,
            "bill_customer_id": r.bill_customer_id,
            "bill_corporate_id": r.bill_corporate_id,
            "party_name": _party_name(r.bill_customer_type, r.bill_customer_id, r.bill_corporate_id),
            "customer_name": (cust_names.get(r.bill_customer_id) or "").strip() or None,
            "bill_match_reason": r.bill_match_reason,
            "projected_ticket_id": r.projected_ticket_id,
            "billing_state": state,
            "billing_id": t.billing_id if t is not None else None,
            # Only for a stale row, and it is the whole point of that state: the screen
            # can say "sent as X, now billed to Y" instead of an unexplained warning.
            "billed_party_name": (
                _party_name(t.customer_type, t.customer_id, t.corporate_id)
                if state == "stale" else None
            ),
            "sendable": state in proj.SENDABLE_STATES,
        }

    # No state_counts here on purpose: they cover the whole batch, so recomputing them
    # per page would put a full-batch aggregate behind every search keystroke. The
    # header gets them from billing-summary, which is called after mutations instead.
    return {
        "total": total, "limit": limit, "offset": offset,
        "rows": [_row(r) for r in rows],
    }


@router.get("/batches/{batch_id}/billing-gaps")
async def billing_gaps(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rows grouped by (status, reason), with a few example passengers each.

    Structurally the same as bsp_commission's /gaps. This only collapses because
    `bill_match_reason` is identical per gap type — see customer_resolver.REASON.
    """
    await _owned_batch(batch_id, db, current_user)
    billable = (cres.RESOLVED, cres.DEFAULTED, cres.OVERRIDDEN)

    rows = (await db.execute(
        select(
            LccDetailed.bill_status,
            LccDetailed.bill_match_reason,
            func.count().label("n"),
            func.array_agg(func.coalesce(LccDetailed.name1, "—")).label("samples"),
        )
        .where(LccDetailed.batch_id == batch_id, *_scope(LccDetailed, current_user),
               LccDetailed.bill_status.notin_(billable))
        .group_by(LccDetailed.bill_status, LccDetailed.bill_match_reason)
        .order_by(func.count().desc())
        .limit(MAX_GAP_GROUPS)
    )).all()

    return [{
        "status": s,
        "reason": reason,
        "count": n,
        # Dedup then cap: one passenger can hold several rows in the same gap.
        "sample_passengers": list(dict.fromkeys(samples or []))[:5],
    } for s, reason, n, samples in rows]


class BillingPartyPayload(BaseModel):
    customer_type: str | None = None      # corporate | direct
    customer_id: int | None = None
    corporate_id: int | None = None


@router.patch("/batches/{batch_id}/billing-default")
async def set_billing_default(
    batch_id: str,
    payload: BillingPartyPayload,
    apply_to: str = Query("unresolved", pattern="^(unresolved|all)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set the batch's fallback party and stamp it onto rows that need one.

    `apply_to=unresolved` (the default) leaves rows a human or the resolver already
    settled; `all` re-stamps every billable row, overrides included.
    """
    batch = await _owned_batch(batch_id, db, current_user)
    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id,
        # A HUMAN picked this party, so store the one they picked. The employee
        # upgrade belongs to the automatic resolver, which is guessing from a
        # passenger name and should leave the employer able to bill. Here it would
        # silently overrule the choice: pick an employee and the row comes back
        # reading as their corporate, with no way to bill them directly.
        upgrade_employee=False,
    )
    batch.default_customer_type = ct
    batch.default_customer_id = cust_id
    batch.default_corporate_id = corp_id

    rows_updated = 0
    if ct:
        conds = [LccDetailed.batch_id == batch_id, *_scope(LccDetailed, current_user),
                 LccDetailed.bill_kind != "payment"]
        if apply_to == "unresolved":
            conds.append(LccDetailed.bill_status.notin_(
                (cres.RESOLVED, cres.DEFAULTED, cres.OVERRIDDEN)
            ))
        result = await db.execute(
            update(LccDetailed).where(*conds).values(
                bill_status=cres.DEFAULTED,
                bill_customer_type=ct,
                bill_customer_id=cust_id,
                bill_corporate_id=corp_id,
                bill_match_reason="Billed to this upload's default party.",
                resolved_at=datetime.utcnow(),
                resolved_by_id=current_user.id,
            )
        )
        rows_updated = result.rowcount or 0

    if batch.resolution_status == "none":
        batch.resolution_status = "resolved"
    await _recount(db, batch)
    await db.commit()

    return {"batch_id": batch_id, "customer_type": ct, "customer_id": cust_id,
            "corporate_id": corp_id, "rows_updated": rows_updated,
            "resolved_rows": batch.resolved_rows, "unresolved_rows": batch.unresolved_rows}


@router.patch("/rows/{row_id}/billing-party")
async def set_row_billing_party(
    row_id: int,
    payload: BillingPartyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A human's pick for one row. Survives a re-resolve unless reset explicitly."""
    row = await db.scalar(
        select(LccDetailed).where(LccDetailed.id == row_id, *_scope(LccDetailed, current_user))
    )
    if not row:
        raise HTTPException(status_code=404, detail="Row not found.")
    if row.bill_kind == "payment":
        raise HTTPException(
            status_code=409,
            detail="This row is a payment movement — it carries no fare, so there is nothing to bill.",
        )
    # Once a row is in billing, the TICKET is the thing that exists and its party
    # is what billing reads; this row is only the record of how it got there.
    # Editing it here would change nothing anyone bills and would leave the two
    # permanently disagreeing, so it is refused and the correction is pointed at
    # the screen that actually owns it.
    if row.projected_ticket_id is not None:
        raise HTTPException(
            status_code=409,
            detail=("This row is already in billing. Change who it is billed to from "
                    "Billing → Sold Tickets, not here."),
        )

    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id,
        # A HUMAN picked this party, so store the one they picked. The employee
        # upgrade belongs to the automatic resolver, which is guessing from a
        # passenger name and should leave the employer able to bill. Here it would
        # silently overrule the choice: pick an employee and the row comes back
        # reading as their corporate, with no way to bill them directly.
        upgrade_employee=False,
    )
    row.bill_customer_type = ct
    row.bill_customer_id = cust_id
    row.bill_corporate_id = corp_id
    row.bill_status = cres.OVERRIDDEN if ct else cres.UNRESOLVED
    row.bill_match_reason = None if ct else cres.REASON[cres.UNRESOLVED]
    row.resolved_at = datetime.utcnow()
    row.resolved_by_id = current_user.id

    batch = await _owned_batch(row.batch_id, db, current_user)
    await _recount(db, batch)
    await db.commit()

    return {"id": row.id, "bill_status": row.bill_status, "customer_type": ct,
            "customer_id": cust_id, "corporate_id": corp_id}


class BulkBillingPartyPayload(BillingPartyPayload):
    row_ids: list[int]


@router.patch("/batches/{batch_id}/billing-party-bulk")
async def set_rows_billing_party(
    batch_id: str,
    payload: BulkBillingPartyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One party for a hand-picked set of rows — the per-row picker, in bulk.

    Stamped as OVERRIDDEN, exactly like the single-row endpoint, so a human's pick
    survives the next re-match.

    Payment movements in the selection are SKIPPED and counted, not refused. The
    single-row endpoint 409s on one because there the payment row IS the request; here,
    failing forty good rows over one payment row would be the wrong trade.

    Rows already in billing are skipped the same way and for the same reason as the
    single-row 409: the ticket is what billing reads, so re-stamping this row would
    change nothing and leave the two disagreeing. They are corrected from
    Billing → Sold Tickets.
    """
    batch = await _owned_batch(batch_id, db, current_user)
    ids = _checked_ids(payload.row_ids, "use the default party above")
    await _owned_row_ids(db, batch_id, current_user, ids)

    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id,
        # A HUMAN picked this party, so store the one they picked. The employee
        # upgrade belongs to the automatic resolver, which is guessing from a
        # passenger name and should leave the employer able to bill. Here it would
        # silently overrule the choice: pick an employee and the row comes back
        # reading as their corporate, with no way to bill them directly.
        upgrade_employee=False,
    )
    if not ct:
        raise HTTPException(status_code=400, detail="Pick a customer or corporate.")

    result = await db.execute(
        update(LccDetailed).where(
            LccDetailed.id.in_(ids),
            LccDetailed.batch_id == batch_id,
            *_scope(LccDetailed, current_user),
            # NULL-safe: `bill_kind != 'payment'` would drop never-resolved rows, whose
            # kind is still NULL. See lcc_billing_projection's note on the same trap.
            or_(LccDetailed.bill_kind.is_(None), LccDetailed.bill_kind != "payment"),
            LccDetailed.projected_ticket_id.is_(None),
        ).values(
            bill_status=cres.OVERRIDDEN,
            bill_customer_type=ct,
            bill_customer_id=cust_id,
            bill_corporate_id=corp_id,
            bill_match_reason=None,
            resolved_at=datetime.utcnow(),
            resolved_by_id=current_user.id,
        )
    )
    rows_updated = result.rowcount or 0

    # Counted separately, not lumped into one "skipped" number: the two reasons
    # need different things from the user. A payment movement can never be billed;
    # a row in billing is billed already and is edited from Billing instead.
    skipped_in_billing = await db.scalar(
        select(func.count()).select_from(LccDetailed).where(
            LccDetailed.id.in_(ids),
            LccDetailed.batch_id == batch_id,
            *_scope(LccDetailed, current_user),
            LccDetailed.projected_ticket_id.isnot(None),
        )
    ) or 0

    if batch.resolution_status == "none":
        batch.resolution_status = "resolved"
    await _recount(db, batch)
    await db.commit()

    return {"batch_id": batch_id, "customer_type": ct, "customer_id": cust_id,
            "corporate_id": corp_id, "rows_updated": rows_updated,
            "skipped_in_billing": skipped_in_billing,
            "skipped_payments": len(ids) - rows_updated - skipped_in_billing,
            "billable_rows": batch.billable_rows,
            "resolved_rows": batch.resolved_rows,
            "unresolved_rows": batch.unresolved_rows}


# ── adding a passenger to the Employee Master ────────────────────────────────
# The worklist can match a passenger against the Employee Master but has never been
# able to ADD one — `services/customer_resolver` says so in its own docstring: it
# reads the masters and never writes them. So a passenger who is not on file leaves
# the user to open User master → Employee Master in another tab, retype the name, and
# come back. This is that round trip, as one button.
#
# Note this creation deliberately does NOT go through `POST /customers/`. That route
# does not inherit the corporate's terms — it doesn't need to, because the form in
# front of it has already copied them down in the browser (lib/party.ts
# `seedFromCorporate`). There is no form here, so the inheritance has to happen on
# this side, through the same canonical list: services/party_inherit.

class CreateEmployeePayload(BaseModel):
    # The employer to file them under. Omitted, the corporate already chosen on the
    # row is used — the ordinary path, since the button only appears once a party has
    # been picked.
    corporate_id: int | None = None


class CreateEmployeesBulkPayload(BaseModel):
    row_ids: list[int]
    # One employer for the whole selection. Omitted, each row uses its own.
    corporate_id: int | None = None


async def _corporate_for(db: AsyncSession, user: User, corporate_id: int | None) -> Corporate:
    corp = (await db.execute(select(Corporate).where(
        Corporate.id == corporate_id,
        Corporate.tenant_id == user.tenant_id,
        Corporate.created_by_id == user.id,
    ))).scalar_one_or_none()
    if corp is None:
        raise HTTPException(
            status_code=404,
            detail=f"Corporate id {corporate_id} is not in your corporates.",
        )
    return corp


async def _add_row_passenger_to_master(
    db: AsyncSession, user: User, row: LccDetailed, corp: Corporate, dupes, index=None,
):
    """File this row's passenger under `corp`, then point the row at them.

    The creation rule lives in services/employee_from_passenger, shared with the NDC
    worklist. Only the re-tag below is LCC's own, because only the caller knows what
    a row of this statement type looks like.
    """
    outcome = await emp.create_employee_from_passenger(
        db, user, row.name1, corp, dupes, index)
    if not outcome.created:
        return outcome

    # customer_type 'corporate' carrying BOTH ids: the employer is invoiced, and the
    # employee is recorded as who travelled. The same shape the party picker produces
    # for an employee, and the same OVERRIDDEN status — a person chose it.
    row.bill_customer_type = "corporate"
    row.bill_customer_id = outcome.customer_id
    row.bill_corporate_id = corp.id
    row.bill_status = cres.OVERRIDDEN
    row.bill_match_reason = None
    row.resolved_at = datetime.utcnow()
    row.resolved_by_id = user.id
    return outcome


def _guard_row_for_employee(row: LccDetailed) -> str | None:
    """Why this row cannot take an employee, or None."""
    if _is_payment_row(row):
        return "This row is a payment movement — there is nothing to bill."
    if row.projected_ticket_id is not None:
        return "This row is already in billing. Remove it from the billing first."
    return None


def _is_payment_row(row: LccDetailed) -> bool:
    return (row.bill_kind or "") == "payment"


@router.post("/rows/{row_id}/create-employee", status_code=status.HTTP_201_CREATED)
async def create_employee_from_row(
    row_id: int,
    payload: CreateEmployeePayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add this row's passenger to the Employee Master under a corporate, and bill the
    row to them."""
    from app.services.party_dedupe import CustomerDuplicates

    payload = payload or CreateEmployeePayload()
    row = await db.scalar(
        select(LccDetailed).where(LccDetailed.id == row_id, *_scope(LccDetailed, current_user))
    )
    if not row:
        raise HTTPException(status_code=404, detail="Row not found.")
    blocked = _guard_row_for_employee(row)
    if blocked:
        raise HTTPException(status_code=409, detail=blocked)

    corporate_id = payload.corporate_id or row.bill_corporate_id
    if not corporate_id:
        raise HTTPException(
            status_code=400,
            detail="Pick the corporate this passenger works for first.",
        )
    corp = await _corporate_for(db, current_user, corporate_id)

    dupes = await CustomerDuplicates.load(db, current_user)
    index = await cres.CustomerIndex.load(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id)
    outcome = await _add_row_passenger_to_master(db, current_user, row, corp, dupes, index)
    if not outcome.created:
        raise HTTPException(status_code=409, detail=outcome.reason)

    batch = await _owned_batch(row.batch_id, db, current_user)
    if batch.resolution_status == "none":
        batch.resolution_status = "resolved"
    await _recount(db, batch)
    await db.commit()

    return {
        "customer_id": outcome.customer_id,
        "passenger": outcome.display_name,
        "corporate_id": corp.id,
        "company": corp.company,
        "inherited": list(outcome.inherited),
        "row_id": row.id,
        "bill_status": row.bill_status,
        "billable_rows": batch.billable_rows,
        "resolved_rows": batch.resolved_rows,
        "unresolved_rows": batch.unresolved_rows,
    }


@router.post("/batches/{batch_id}/create-employees", status_code=status.HTTP_201_CREATED)
async def create_employees_from_rows(
    batch_id: str,
    payload: CreateEmployeesBulkPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The same, for a hand-picked selection.

    Rows that cannot take an employee are SKIPPED and reported, not failed — a
    selection of thirty is nearly always going to contain one that is already on file,
    and refusing the lot for it would make the button useless at the size it exists for.
    """
    from app.services.party_dedupe import CustomerDuplicates

    batch = await _owned_batch(batch_id, db, current_user)
    ids = _checked_ids(payload.row_ids, "tick the rows to add")
    await _owned_row_ids(db, batch_id, current_user, ids)

    rows = (await db.execute(
        select(LccDetailed).where(LccDetailed.id.in_(ids), *_scope(LccDetailed, current_user))
        .order_by(LccDetailed.id)
    )).scalars().all()

    dupes = await CustomerDuplicates.load(db, current_user)
    # Loaded ONCE for the whole selection. It does not see employees created earlier
    # in this same loop — `dupes` is what catches those, and it claims each identity
    # as it goes.
    index = await cres.CustomerIndex.load(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id)
    # One lookup per corporate, not per row: a selection of thirty rows under one
    # employer would otherwise re-read it thirty times.
    corps: dict[int, Corporate] = {}
    created: list[dict] = []
    skipped: list[dict] = []

    for row in rows:
        blocked = _guard_row_for_employee(row)
        if blocked:
            skipped.append({"row_id": row.id, "passenger": row.name1, "reason": blocked})
            continue
        corporate_id = payload.corporate_id or row.bill_corporate_id
        if not corporate_id:
            skipped.append({"row_id": row.id, "passenger": row.name1,
                            "reason": "No corporate picked for this row."})
            continue
        if corporate_id not in corps:
            corps[corporate_id] = await _corporate_for(db, current_user, corporate_id)
        outcome = await _add_row_passenger_to_master(
            db, current_user, row, corps[corporate_id], dupes, index)
        if outcome.created:
            created.append({"row_id": row.id, "customer_id": outcome.customer_id,
                            "passenger": outcome.display_name,
                            "company": corps[corporate_id].company})
        else:
            skipped.append({"row_id": row.id, "passenger": row.name1,
                            "reason": outcome.reason})

    if created and batch.resolution_status == "none":
        batch.resolution_status = "resolved"
    await _recount(db, batch)
    await db.commit()

    return {
        "batch_id": batch_id,
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "billable_rows": batch.billable_rows,
        "resolved_rows": batch.resolved_rows,
        "unresolved_rows": batch.unresolved_rows,
    }


async def _owned_row_ids(
    db: AsyncSession, batch_id: str, current_user: User, ids: list[int],
) -> None:
    """Every id must be a row of THIS batch, owned by this caller, or nothing runs.

    project_batch filters on batch_id alone, so this is where the tenant boundary is
    enforced for any endpoint that takes hand-picked ids. Refusing the whole call rather
    than quietly narrowing it also stops the endpoint being used to probe which ids
    exist.
    """
    found = set((await db.execute(
        select(LccDetailed.id).where(
            LccDetailed.id.in_(ids),
            LccDetailed.batch_id == batch_id,
            *_scope(LccDetailed, current_user),
        )
    )).scalars().all())
    missing = len(ids) - len(found)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"{missing} of the selected rows are not in this upload.",
        )


def _checked_ids(row_ids: list[int] | None, action: str) -> list[int] | None:
    """Normalise a hand-picked selection. None means "the whole upload"."""
    if row_ids is None:
        return None
    ids = list(dict.fromkeys(row_ids))          # dedupe, keep the caller's order
    if not ids:
        # An EXPLICIT empty list is a mistake, not "do everything" — the None/[] split
        # is what keeps a bug in the caller from silently acting on the whole upload.
        raise HTTPException(status_code=400, detail=f"Tick at least one row, or {action}.")
    if len(ids) > MAX_SEND_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Select at most {MAX_SEND_ROWS} rows at a time, or {action}.",
        )
    return ids


class SendToBillingPayload(BaseModel):
    """No body / null → the whole upload, synced. `row_ids` → those rows, added only."""
    row_ids: list[int] | None = Field(default=None)


@router.post("/batches/{batch_id}/send-to-billing")
async def send_to_billing(
    batch_id: str,
    payload: SendToBillingPayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Project the resolved rows into `uploaded_tickets` so billing can see them.

    Idempotent: re-running syncs rather than duplicates, and any ticket already on an
    invoice is left exactly as it was.

    With `row_ids`, only those rows are touched and nothing is ever removed — see
    project_batch's docstring for why a selective send is additive. Withdrawing a row
    from billing stays the whole-upload send's job.
    """
    batch = await _owned_batch(batch_id, db, current_user)
    if batch.status != "completed":
        raise HTTPException(status_code=409, detail="This upload is still importing.")
    if batch.resolution_status == "none":
        raise HTTPException(
            status_code=409,
            detail="Resolve this upload's customers first — nothing here has a party to bill yet.",
        )

    ids = _checked_ids(payload.row_ids if payload else None, "send the whole upload")
    if ids:
        await _owned_row_ids(db, batch_id, current_user, ids)

    result = await proj.project_batch(db, batch, row_ids=ids)
    await _recount(db, batch)
    await db.commit()
    return {"batch_id": batch_id, **result}


@router.get("/records")
async def list_records(
    request: Request,
    batch_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated typed rows + folded Taxes/Segments/SSR display columns.

    Narrowed by the `f.<field>` filters declared in `spec.FILTERS`; `total` and `summary`
    both cover the whole filtered set, so they stay consistent with what the grid shows.
    """
    conds = _record_conds(current_user, batch_id, request)

    # Count, pax and the column totals in one round trip — they all share the same WHERE,
    # and the summary covers the ENTIRE filtered set, not the visible page. No numeric-cast
    # guard is needed here (unlike _num() in the JSONB-backed statements router): these are
    # real NUMERIC(14,2) columns, so SUM() is exact.
    agg = (await db.execute(
        select(
            func.count().label("n"),
            func.coalesce(func.sum(LccDetailed.pax_count), 0).label("pax"),
            *[func.sum(_SUMMARY_COLS[f["field"]]).label(f"s_{f['field']}")
              for f in spec.SUMMARY_FIELDS],
        ).select_from(LccDetailed).where(*conds)
    )).one()
    total = agg.n or 0

    q = (select(LccDetailed).where(*conds)
         .order_by(LccDetailed.id.desc()).limit(limit).offset(offset))
    rows = (await db.execute(q)).scalars().all()

    fmt = ""
    if batch_id:
        b = await db.scalar(
            select(LccDetailedBatch.source_format).where(
                LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
            )
        )
        fmt = b or ""

    columns = [{"header": c["header"], "field": c["field"]} for c in spec.CORE_COLUMNS]
    columns += [
        # Declared at upload, not present in the source file — see models/tenant_airline.py.
        {"header": "Airline", "field": "__airline__"},
        {"header": "Departure Date", "field": "departure_date"},
        # NOT "Taxes Total" — that is now a mappable core column and is already in the
        # list above. Declaring it here as well gave the grid the same field twice.
        # Derived at ingest, so they belong here rather than in the mappable spec:
        {"header": "Row Type", "field": "row_kind"},
        {"header": "Movement", "field": "movement_kind"},
        {"header": "Taxes", "field": "__taxes__"},
        {"header": "Segments", "field": "__segments__"},
        {"header": "SSR", "field": "__ssr__"},
        {"header": "Format", "field": "__format__"},
    ]

    out_rows = []
    for r in rows:
        d = {c["field"]: _disp(getattr(r, c["field"], None)) for c in spec.CORE_COLUMNS}
        d["__airline__"] = " ".join(x for x in (r.airline_code, r.airline_name) if x)
        d["departure_date"] = _disp(r.departure_date)
        d["row_kind"] = _disp(r.row_kind)
        d["movement_kind"] = _disp(r.movement_kind)
        d["__taxes__"] = " · ".join(
            f"{t.get('code')} {t.get('amount') or ''}".strip()
            for t in (r.taxes or []) if t.get("code")
        )
        d["__segments__"] = " · ".join(_seg_str(s) for s in (r.segments or []))
        d["__ssr__"] = " · ".join(
            f"{s.get('code')} {s.get('amount') or ''}".strip()
            for s in (r.ssr or []) if s.get("code")
        )
        d["__format__"] = fmt
        d["id"] = r.id
        out_rows.append(d)

    return {
        "total": total, "limit": limit, "offset": offset,
        "columns": columns, "rows": out_rows,
        "filters": spec.FILTERS,
        "summary": {
            "fields": spec.SUMMARY_FIELDS,
            # Serialized as strings — a float round-trip would lose paise.
            "computed": {
                f["field"]: _money_str(getattr(agg, f"s_{f['field']}")) or "0"
                for f in spec.SUMMARY_FIELDS
            },
            "row_count": total,
            "pax_count": int(agg.pax or 0),
        },
    }


@router.get("/records/facets")
async def record_facets(
    batch_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct values for every facet-backed `select` filter, for the dropdowns.

    Scoped to the batch — the question is "what payment methods are in THIS file" — but
    deliberately NOT narrowed by the other active filters, so the options don't vanish
    from under the user as they narrow. One query rather than one per column: the batch
    is scanned once and every facet aggregated in the same pass.

    Filters that declare static `options` (the `international` boolean) are absent; the
    client uses their declared options instead.
    """
    selects = [f for f in spec.FILTERS if f["type"] == "select" and not f.get("options")]
    if not selects:
        return {}

    conds = [*_scope(LccDetailed, current_user)]
    if batch_id:
        conds.append(LccDetailed.batch_id == batch_id)

    row = (await db.execute(
        select(*[func.array_agg(func.distinct(_FILTER_COLS[f["field"]])) for f in selects])
        .where(*conds)
    )).one()

    out: dict[str, list[str]] = {}
    for i, f in enumerate(selects):
        # array_agg(DISTINCT x) keeps NULL as an element, and an empty batch aggregates
        # to NULL rather than to an empty array.
        values = sorted({v for v in (row[i] or []) if v not in (None, "")})
        out[f["field"]] = values[:_MAX_FACET_VALUES]
    return out


_PREVIEW_ROWS = 2000   # rows converted to xlsx for the Excel Online preview


def _make_preview_xlsx(content: bytes, filename: str, header_row: int, nrows: int) -> bytes:
    """Read the first `nrows` rows and write them to an .xlsx (values kept as text so
    long numbers/ids/phones aren't mangled into scientific notation). Runs in a thread."""
    from openpyxl import Workbook
    df = _read_df(content, filename, header_row, nrows=nrows)
    df.dropna(how="all", inplace=True)
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Sheet1")
    ws.append([str(c) for c in df.columns])
    for tup in df.itertuples(index=False, name=None):
        ws.append(["" if _clean(v) is None else _clean(v) for v in tup])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _preview_blob(file_url: str) -> str:
    """Where a file's cached xlsx preview lives.

    Derived from the FILE, not from its folder. Keyed on the folder, the two files of
    a merged upload shared one cache entry — preview the account statement, then the
    passenger report, and you were handed the account statement again.
    """
    return f"{file_url}._preview.xlsx"


@router.get("/batches/{batch_id}/viewer-url")
async def viewer_url(
    batch_id: str,
    role: str | None = Query(None, description="which source file, for a merged upload"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Signed URL to an .xlsx the frontend can open in the Microsoft Office web viewer
    (renders as a real spreadsheet). xlsx/xls uploads are served directly; a .csv is
    converted to an xlsx (first N rows) and cached in GCS so repeat previews are instant."""
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")
    file_url, source_file, header_row = await _batch_file(db, batch, role)
    if not file_url:
        raise HTTPException(status_code=404, detail="No file stored for this upload.")

    if source_file.lower().endswith((".xlsx", ".xls")):
        url = await gcs.generate_signed_url(file_url, _bucket(), inline=True)
        return {"url": url, "converted": False, "file_name": source_file}

    # CSV → cache a first-N-rows xlsx conversion beside the original.
    xlsx_blob = _preview_blob(file_url)
    if not await gcs.blob_exists(xlsx_blob, _bucket()):
        content = await gcs.download_bytes(file_url, _bucket())
        xlsx = await asyncio.get_event_loop().run_in_executor(
            None, _make_preview_xlsx, content, source_file, header_row, _PREVIEW_ROWS
        )
        await gcs.upload_bytes(
            xlsx, xlsx_blob,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _bucket(),
        )
    url = await gcs.generate_signed_url(xlsx_blob, _bucket(), inline=True)
    return {"url": url, "converted": True, "preview_rows": _PREVIEW_ROWS,
            "file_name": source_file}


@router.get("/batches/{batch_id}/file-url")
async def get_batch_file_url(
    batch_id: str,
    inline: bool = Query(True, description="inline (preview) vs attachment (download)"),
    role: str | None = Query(None, description="which source file, for a merged upload"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")
    file_url, source_file, _ = await _batch_file(db, batch, role)
    if not file_url:
        raise HTTPException(status_code=404, detail="No file stored for this upload.")
    # For inline PREVIEW of a .csv, override the served content-type to text/plain so the
    # browser displays it instead of downloading it (browsers download text/csv even inline).
    content_type = None
    if inline and source_file.lower().endswith(".csv"):
        content_type = "text/plain; charset=utf-8"
    url = await gcs.generate_signed_url(
        file_url, _bucket(), expiry_minutes=60, inline=inline, content_type=content_type
    )
    return {"url": url, "file_name": source_file}


@router.delete("/batches/{batch_id}")
async def delete_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an upload (rows cascade via FK); best-effort remove the stored file.

    Projected tickets do NOT cascade — they live in `uploaded_tickets` under their own
    statement — so they are removed here explicitly, and refused outright once any of
    them is on an invoice.
    """
    from app.models.ticket_statement import TicketStatement
    from app.models.uploaded_ticket import UploadedTicket

    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")

    if batch.billing_batch_id:
        billed = (await db.execute(
            select(func.count(), func.min(UploadedTicket.billing_id))
            .where(UploadedTicket.batch_id == batch.billing_batch_id,
                   UploadedTicket.billing_id.isnot(None))
        )).one()
        if billed[0]:
            raise HTTPException(
                status_code=409,
                detail=(f"{billed[0]} row(s) from this upload are on billing #{billed[1]}. "
                        "Delete that billing first, then delete this upload."),
            )
        await db.execute(
            delete(UploadedTicket).where(UploadedTicket.batch_id == batch.billing_batch_id)
        )
        await db.execute(
            delete(TicketStatement).where(TicketStatement.batch_id == batch.billing_batch_id)
        )

    # EVERY source file, not just the primary one. The child rows cascade with the
    # batch, so this list has to be taken before the delete — and without it a merged
    # upload's second blob would sit in the bucket forever with nothing left pointing
    # at it.
    stored = [
        f.file_url for f in (await db.execute(
            select(LccDetailedBatchFile).where(LccDetailedBatchFile.batch_id == batch_id)
        )).scalars().all() if f.file_url
    ]
    if batch.file_url and batch.file_url not in stored:
        stored.append(batch.file_url)

    await db.delete(batch)
    await db.commit()
    for file_url in stored:
        # The old folder-derived preview name is still tried, so previews cached
        # before that path changed are cleaned up too rather than orphaned.
        for blob in (file_url, _preview_blob(file_url),
                     file_url.rsplit("/", 1)[0] + "/_preview.xlsx"):
            try:
                await gcs.delete_blob(blob, _bucket())
            except Exception:  # noqa: BLE001
                pass
    return {"deleted": True, "batch_id": batch_id}


@router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await db.scalar(
        select(LccDetailed).where(LccDetailed.id == record_id, *_scope(LccDetailed, current_user))
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Record not found.")
    await db.delete(obj)
    await db.commit()
