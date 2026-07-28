"""Airline Adjustments — ADM / ACM / RA spreadsheet upload + repository.

Upload an IATA BSPlink ADM/ACM/RA export (.xlsx/.xls/.csv); the known export
columns are matched by header and stored verbatim (one table per type). The
repository lists the stored rows. Synchronous parse — these row-exports are
small (unlike the async BSP PDF pipeline). Everything is scoped per user/tenant.
"""
from __future__ import annotations

import io
import math
import uuid
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.airline_adjustment import ADJUSTMENT_MODELS
from app.models.user import User
from app.services import airline_adjustment_spec as spec

router = APIRouter()

# A file with fewer than this many recognised columns is almost certainly the
# wrong document type — reject it with a helpful message instead of importing junk.
_MIN_MATCHED_COLUMNS = 3


def _adj_bucket() -> str:
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


# ── helpers ──────────────────────────────────────────────────────────────────
def _model_for(adj_type: str):
    model = ADJUSTMENT_MODELS.get((adj_type or "").lower())
    if model is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown adjustment type '{adj_type}'. Use one of: {', '.join(spec.ADJUSTMENT_TYPES)}.",
        )
    return model


def _scope(model, user: User):
    return (model.tenant_id == user.tenant_id, model.created_by_id == user.id)


def _clean(value) -> str | None:
    """Cell value -> stripped string, or None for empty / NaN."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    return s


def _row_to_dict(obj, adj_type: str) -> dict:
    d = {
        "id": obj.id,
        "batch_id": obj.batch_id,
        "source_file": obj.source_file,
        "uploaded_at": obj.uploaded_at,
    }
    for f in spec.fields(adj_type):
        d[f] = getattr(obj, f)
    return d


def _read_df(content: bytes, filename: str, header_row: int) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        # sep=None + python engine sniffs the delimiter (IATA exports are ';'-separated).
        return pd.read_csv(io.BytesIO(content), dtype=str, sep=None, engine="python", header=header_row)
    if name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(content), dtype=str, header=header_row)
    return pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl", header=header_row)


def _parse(content: bytes, filename: str, adj_type: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return (dataframe, {df_column -> model_field}) for the best-matching header row.

    Tries the first three rows as the header (BSP exports sometimes carry a title
    row) and keeps whichever recognises the most known columns.
    """
    field_set = set(spec.fields(adj_type))
    best: tuple[int, pd.DataFrame, dict[str, str]] | None = None
    last_err: Exception | None = None

    for header_row in (0, 1, 2):
        try:
            df = _read_df(content, filename, header_row)
        except Exception as e:  # unreadable at this header offset — try the next
            last_err = e
            continue
        df.dropna(how="all", inplace=True)
        colmap: dict[str, str] = {}
        for col in df.columns:
            key = spec.norm(col)
            if key in field_set and key not in colmap.values():
                colmap[col] = key
        if best is None or len(colmap) > best[0]:
            best = (len(colmap), df, colmap)

    if best is None:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read the file: {last_err}. Upload a valid .xlsx, .xls or .csv export.",
        )

    matched, df, colmap = best
    if matched < _MIN_MATCHED_COLUMNS:
        sample = ", ".join(spec.HEADERS[adj_type.lower()][:5])
        raise HTTPException(
            status_code=400,
            detail=(
                f"This doesn't look like an {adj_type.upper()} file — only {matched} known "
                f"column(s) were recognised. Expected headers such as: {sample}…"
            ),
        )
    return df, colmap


# ── routes ───────────────────────────────────────────────────────────────────
@router.get("/{adj_type}/columns")
async def get_columns(adj_type: str, current_user: User = Depends(get_current_user)):
    """Ordered [{header, field}] for the type — drives the repository table headers."""
    _model_for(adj_type)
    return spec.columns(adj_type)


@router.post("/{adj_type}/upload")
async def upload_adjustments(
    adj_type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Parse an ADM/ACM/RA export and store its rows under a new batch_id."""
    model = _model_for(adj_type)

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    df, colmap = _parse(content, file.filename or "", adj_type)

    batch_id = str(uuid.uuid4())
    uploaded_at = datetime.utcnow()

    # Store the original spreadsheet in GCS so the upload can be viewed/downloaded
    # later. Best-effort — a GCS hiccup must not lose a successful import.
    file_url = None
    try:
        from app.services import gcs
        blob_name = f"adjustments/{current_user.tenant_id}/{adj_type.lower()}/{batch_id}/{file.filename}"
        await gcs.upload_bytes(content, blob_name, file.content_type or "application/octet-stream", _adj_bucket())
        file_url = blob_name
    except Exception:  # noqa: BLE001
        file_url = None

    objs = []
    for _, row in df.iterrows():
        values = {field: _clean(row[col]) for col, field in colmap.items()}
        if not any(v is not None for v in values.values()):
            continue  # blank row
        objs.append(model(
            tenant_id=current_user.tenant_id,
            created_by_id=current_user.id,
            batch_id=batch_id,
            source_file=file.filename,
            file_url=file_url,
            uploaded_at=uploaded_at,
            **values,
        ))

    if not objs:
        raise HTTPException(status_code=400, detail="No data rows were found in the file.")

    db.add_all(objs)
    await db.commit()

    return {
        "batch_id": batch_id,
        "type": adj_type.lower(),
        "file_name": file.filename,
        "inserted": len(objs),
        "matched_columns": len(colmap),
    }


@router.get("/{adj_type}/records")
async def list_records(
    adj_type: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    batch_id: str | None = Query(None),
    search: str | None = Query(None, description="Match document number / airline / agent code"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated repository of stored adjustment rows for the type."""
    model = _model_for(adj_type)

    base = select(model).where(*_scope(model, current_user))
    if batch_id:
        base = base.where(model.batch_id == batch_id)
    if search and search.strip():
        s = f"%{search.strip()}%"
        base = base.where(or_(
            model.document_number.ilike(s),
            model.airline_code.ilike(s),
            model.agent_code.ilike(s),
        ))

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    q = base.order_by(model.uploaded_at.desc(), model.id.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    return {
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "columns": spec.columns(adj_type),
        "rows": [_row_to_dict(r, adj_type) for r in rows],
    }


@router.get("/{adj_type}/batches")
async def list_batches(
    adj_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per upload (batch) — file name, when, and how many rows."""
    model = _model_for(adj_type)
    q = (
        select(
            model.batch_id,
            model.source_file,
            func.max(model.file_url).label("file_url"),
            func.max(model.uploaded_at).label("uploaded_at"),
            func.count().label("row_count"),
        )
        .where(*_scope(model, current_user))
        .group_by(model.batch_id, model.source_file)
        .order_by(func.max(model.uploaded_at).desc())
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "batch_id": r.batch_id,
            "source_file": r.source_file,
            "uploaded_at": r.uploaded_at,
            "row_count": r.row_count,
            "has_file": bool(r.file_url),
            "created_by_name": current_user.full_name,
        }
        for r in rows
    ]


@router.get("/{adj_type}/batches/{batch_id}/file-url")
async def get_batch_file_url(
    adj_type: str,
    batch_id: str,
    inline: bool = Query(True, description="inline (preview) vs attachment (download)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Signed GCS URL for the original uploaded spreadsheet — inline for preview
    (e.g. via the Office web viewer) or attachment for download."""
    model = _model_for(adj_type)
    row = (await db.execute(
        select(model.file_url, model.source_file)
        .where(model.batch_id == batch_id, *_scope(model, current_user)).limit(1)
    )).first()
    if not row or not row.file_url:
        raise HTTPException(status_code=404, detail="No file stored for this upload.")
    from app.services import gcs
    url = await gcs.generate_signed_url(row.file_url, _adj_bucket(), expiry_minutes=60, inline=inline)
    return {"url": url, "file_name": row.source_file}


@router.delete("/{adj_type}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(
    adj_type: str,
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model = _model_for(adj_type)
    obj = (await db.execute(
        select(model).where(model.id == record_id, *_scope(model, current_user))
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Record not found.")
    await db.delete(obj)
    await db.commit()


@router.delete("/{adj_type}/batches/{batch_id}")
async def delete_batch(
    adj_type: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an entire upload (all rows sharing the batch_id)."""
    model = _model_for(adj_type)
    res = await db.execute(
        delete(model).where(model.batch_id == batch_id, *_scope(model, current_user))
    )
    await db.commit()
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return {"deleted": res.rowcount}


@router.get("/{adj_type}/template")
async def download_template(adj_type: str, current_user: User = Depends(get_current_user)):
    """Blank .xlsx with the exact column headers for the type."""
    _model_for(adj_type)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = f"{adj_type.upper()} Template"
    ws.append(spec.HEADERS[adj_type.lower()])

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{adj_type.lower()}_template.xlsx"'},
    )
