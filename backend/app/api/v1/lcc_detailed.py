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
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.models.user import User
from app.services import gcs
from app.services import lcc_detailed_spec as spec
from app.services.lcc_statement import _clean, detect_format

router = APIRouter()

_MIN_MATCHED_COLUMNS = 3
_SAMPLE_ROWS = 50


def _bucket() -> str:
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _scope(model, user: User):
    return (model.tenant_id == user.tenant_id, model.created_by_id == user.id)


def _progress_pct(b: LccDetailedBatch) -> int:
    if b.status == "completed":
        return 100
    if b.total_rows:
        return min(100, int(b.processed_rows * 100 / b.total_rows))
    return 0


def _read_df(content: bytes, filename: str, header_row: int, nrows: int | None = None) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        # index_col=False: these exports end each data row with a trailing delimiter, so
        # pandas would otherwise treat the first column as a row index and shift every
        # value left (garbage in every typed column). Force positional column alignment.
        return pd.read_csv(io.BytesIO(content), dtype=str, sep=None, engine="python",
                           header=header_row, index_col=False, nrows=nrows)
    if name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(content), dtype=str, header=header_row, nrows=nrows)
    return pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl", header=header_row, nrows=nrows)


def _detect_df(content: bytes, filename: str) -> tuple[pd.DataFrame, int, int]:
    """Pick the header row (0/1/2) whose columns recognise the most standard columns.
    Returns (df, header_row, matched_count)."""
    best: tuple[int, pd.DataFrame, int] | None = None
    last_err: Exception | None = None
    for hr in (0, 1, 2):
        try:
            df = _read_df(content, filename, hr)
        except Exception as e:  # noqa: BLE001 — unreadable at this offset, try the next
            last_err = e
            continue
        df.dropna(how="all", inplace=True)
        cols = [str(c) for c in df.columns]
        _, matched, _ = spec.suggest_mapping(cols)
        if best is None or matched > best[0]:
            best = (matched, df, hr)
    if best is None:
        raise HTTPException(status_code=400, detail=f"Could not read the file: {last_err}. Upload a valid .xlsx, .xls or .csv.")
    matched, df, hr = best
    if matched < _MIN_MATCHED_COLUMNS:
        sample = ", ".join(spec.LCC_STANDARD_HEADERS[:5])
        raise HTTPException(
            status_code=400,
            detail=f"This doesn't look like an LCC Detailed statement — only {matched} known "
                   f"column(s) were recognised. Expected headers such as: {sample}…",
        )
    return df, hr, matched


def _seg_str(s: dict) -> str:
    return f"{s.get('route') or ''} {s.get('flight_no') or ''}".strip()


def _disp(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return str(v)


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
@router.post("/extract")
async def extract(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store the file, detect headers, auto-map, and stage a batch. Nothing is
    ingested yet — the user reviews the mapping, then calls /confirm."""
    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    df, header_row, matched = _detect_df(content, file.filename or "")
    cols = [str(c) for c in df.columns]
    total_rows = int(len(df))
    suggested_mapping, matched_columns, is_template_match = spec.suggest_mapping(cols)
    source_format = detect_format(cols)

    sample_df = df.head(_SAMPLE_ROWS)
    sample_rows = [
        {str(c): _clean(row[c]) for c in cols}
        for _, row in sample_df.iterrows()
    ]

    batch_id = str(uuid.uuid4())
    # Store the source file — REQUIRED (the worker re-downloads it). Hard-fail otherwise.
    blob_name = f"lcc-detailed/{current_user.tenant_id}/{batch_id}/{file.filename}"
    try:
        await gcs.upload_bytes(content, blob_name, file.content_type or "application/octet-stream", _bucket())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not store the file: {exc}")

    batch = LccDetailedBatch(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        source_file=file.filename,
        file_url=blob_name,
        source_format=source_format,
        header_row=header_row,
        column_map=suggested_mapping,
        status="staged",
        total_rows=total_rows,
        processed_rows=0,
        matched_columns=matched_columns,
        uploaded_at=datetime.utcnow(),
    )
    db.add(batch)
    await db.commit()

    return {
        "batch_id": batch_id,
        "file_name": file.filename,
        "total_rows": total_rows,
        "header_row": header_row,
        "source_format": source_format,
        "xls_columns": cols,
        "suggested_mapping": suggested_mapping,
        "sample_rows": sample_rows,
        "is_template_match": is_template_match,
        "matched_columns": matched_columns,
        "standard_total": len(spec.LCC_STANDARD_COLUMNS),
    }


class ConfirmPayload(BaseModel):
    batch_id: str
    column_map: dict[str, str]
    expected_rows: int | None = None   # user-declared expected record count (optional)


@router.post("/confirm", status_code=status.HTTP_202_ACCEPTED)
async def confirm(
    payload: ConfirmPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist the confirmed mapping and enqueue background ingestion."""
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == payload.batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if batch.status != "staged":
        raise HTTPException(status_code=409, detail=f"This upload is already '{batch.status}'.")

    # Keep only mappings that point at a real standard field.
    valid_fields = {c["field"] for c in spec.LCC_STANDARD_COLUMNS}
    clean_map = {k: v for k, v in payload.column_map.items() if k in valid_fields and v}
    batch.column_map = clean_map
    batch.matched_columns = len(clean_map)
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
            "progress_pct": _progress_pct(b),
            "row_count": b.processed_rows if b.status == "completed" else b.total_rows,
            "has_file": bool(b.file_url),
            "created_by_name": current_user.full_name,
        }
        for b in rows
    ]


@router.get("/records")
async def list_records(
    batch_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated typed rows + folded Taxes/Segments/SSR display columns."""
    base = select(LccDetailed).where(*_scope(LccDetailed, current_user))
    if batch_id:
        base = base.where(LccDetailed.batch_id == batch_id)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    q = base.order_by(LccDetailed.id.desc()).limit(limit).offset(offset)
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
        {"header": "Departure Date", "field": "departure_date"},
        {"header": "Taxes Total", "field": "taxes_total"},
        {"header": "Taxes", "field": "__taxes__"},
        {"header": "Segments", "field": "__segments__"},
        {"header": "SSR", "field": "__ssr__"},
        {"header": "Format", "field": "__format__"},
    ]

    out_rows = []
    for r in rows:
        d = {c["field"]: _disp(getattr(r, c["field"], None)) for c in spec.CORE_COLUMNS}
        d["departure_date"] = _disp(r.departure_date)
        d["taxes_total"] = _disp(r.taxes_total)
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

    return {"total": total or 0, "limit": limit, "offset": offset, "columns": columns, "rows": out_rows}


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


@router.get("/batches/{batch_id}/viewer-url")
async def viewer_url(
    batch_id: str,
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
    if not batch or not batch.file_url:
        raise HTTPException(status_code=404, detail="No file stored for this upload.")

    src = (batch.source_file or "").lower()
    if src.endswith((".xlsx", ".xls")):
        url = await gcs.generate_signed_url(batch.file_url, _bucket(), inline=True)
        return {"url": url, "converted": False}

    # CSV → cache a first-N-rows xlsx conversion next to the original.
    xlsx_blob = batch.file_url.rsplit("/", 1)[0] + "/_preview.xlsx"
    if not await gcs.blob_exists(xlsx_blob, _bucket()):
        content = await gcs.download_bytes(batch.file_url, _bucket())
        xlsx = await asyncio.get_event_loop().run_in_executor(
            None, _make_preview_xlsx, content, batch.source_file or "", batch.header_row or 0, _PREVIEW_ROWS
        )
        await gcs.upload_bytes(
            xlsx, xlsx_blob,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _bucket(),
        )
    url = await gcs.generate_signed_url(xlsx_blob, _bucket(), inline=True)
    return {"url": url, "converted": True, "preview_rows": _PREVIEW_ROWS}


@router.get("/batches/{batch_id}/file-url")
async def get_batch_file_url(
    batch_id: str,
    inline: bool = Query(True, description="inline (preview) vs attachment (download)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch or not batch.file_url:
        raise HTTPException(status_code=404, detail="No file stored for this upload.")
    # For inline PREVIEW of a .csv, override the served content-type to text/plain so the
    # browser displays it instead of downloading it (browsers download text/csv even inline).
    content_type = None
    if inline and (batch.source_file or "").lower().endswith(".csv"):
        content_type = "text/plain; charset=utf-8"
    url = await gcs.generate_signed_url(
        batch.file_url, _bucket(), expiry_minutes=60, inline=inline, content_type=content_type
    )
    return {"url": url, "file_name": batch.source_file}


@router.delete("/batches/{batch_id}")
async def delete_batch(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an upload (rows cascade via FK); best-effort remove the stored file."""
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")
    file_url = batch.file_url
    await db.delete(batch)
    await db.commit()
    if file_url:
        for blob in (file_url, file_url.rsplit("/", 1)[0] + "/_preview.xlsx"):
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
