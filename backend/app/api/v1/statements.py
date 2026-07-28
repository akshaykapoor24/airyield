"""Generic spec-driven vendor statements (TGQ HMPR, later NDC / LCC / GDS).

Upload an XLS/CSV export; the spec's fixed columns are stored verbatim in a JSONB
``data`` blob and the repeating ``Tax_TypeN`` / ``TaxN`` pairs are folded into a JSONB
``taxes`` array (so any number of taxes is supported — no fixed Tax1..Tax20 columns).
Each statement type has its OWN dedicated table, resolved by ``{slug}`` via
``STATEMENT_MODELS`` (e.g. ``tgq-hmpr`` → ``tgq_hmpr``). Same REST shape as the
airline-adjustments router, so the frontend batch view is reused unchanged. The
original spreadsheet is stored in GCS for preview/download. Scoped per user/tenant.
"""
from __future__ import annotations

import io
import math
import re
import uuid
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.statement_row import STATEMENT_MODELS
from app.models.user import User
from app.services import statement_spec as spec

router = APIRouter()

_MIN_MATCHED_COLUMNS = 3
_TAX_TYPE_RE = re.compile(r"^tax_type(\d+)$")
_TAX_AMT_RE = re.compile(r"^tax(\d+)$")


def _bucket() -> str:
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _resolve(slug: str):
    """(normalized slug, dedicated model) or 404."""
    s = (slug or "").lower()
    model = STATEMENT_MODELS.get(s)
    if model is None or spec.spec_for(s) is None:
        raise HTTPException(status_code=404, detail=f"Unknown statement type '{slug}'.")
    return s, model


def _scope(model, user: User):
    return (model.tenant_id == user.tenant_id, model.created_by_id == user.id)


def _clean(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    return s


def _read_df(content: bytes, filename: str, header_row: int) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content), dtype=str, sep=None, engine="python", header=header_row)
    if name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(content), dtype=str, header=header_row)
    return pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl", header=header_row)


def _parse(content: bytes, filename: str, slug: str):
    """(df, {col->field}, {col->normalized}) for the header row that recognises the most columns."""
    field_set = set(spec.fields(slug))
    best = None
    last_err: Exception | None = None
    for header_row in (0, 1, 2):
        try:
            df = _read_df(content, filename, header_row)
        except Exception as e:  # noqa: BLE001 — unreadable at this offset, try the next
            last_err = e
            continue
        df.dropna(how="all", inplace=True)
        colmap: dict = {}
        normmap: dict = {}
        for col in df.columns:
            key = spec.norm(col)
            normmap[col] = key
            if key in field_set and key not in colmap.values():
                colmap[col] = key
        if best is None or len(colmap) > best[0]:
            best = (len(colmap), df, colmap, normmap)
    if best is None:
        raise HTTPException(status_code=400, detail=f"Could not read the file: {last_err}. Upload a valid .xlsx, .xls or .csv.")
    matched, df, colmap, normmap = best
    if matched < _MIN_MATCHED_COLUMNS:
        sample = ", ".join(spec.headers(slug)[:5])
        raise HTTPException(
            status_code=400,
            detail=f"This doesn't look like a {spec.spec_for(slug)['label']} file — only {matched} known "
                   f"column(s) were recognised. Expected headers such as: {sample}…",
        )
    return df, colmap, normmap


def _fold_taxes(row, normmap: dict) -> list[dict]:
    """Fold every Tax_TypeN / TaxN pair (any N) into [{type, amount}, ...]; drop empty types."""
    types: dict[int, str | None] = {}
    amounts: dict[int, str | None] = {}
    for col, nz in normmap.items():
        m = _TAX_TYPE_RE.match(nz)
        if m:
            types[int(m.group(1))] = _clean(row[col])
            continue
        m = _TAX_AMT_RE.match(nz)
        if m:
            amounts[int(m.group(1))] = _clean(row[col])
    out: list[dict] = []
    for n in sorted(types):
        t = types[n]
        if t:
            out.append({"type": t, "amount": amounts.get(n)})
    return out


def _detect_df(content: bytes, filename: str, score_fn):
    """Pick the header row (0/1/2) whose columns score highest via `score_fn(cols)`."""
    best = None
    last_err: Exception | None = None
    for hr in (0, 1, 2):
        try:
            df = _read_df(content, filename, hr)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        df.dropna(how="all", inplace=True)
        score = score_fn([str(c) for c in df.columns])
        if best is None or score > best[0]:
            best = (score, df)
    if best is None:
        raise HTTPException(status_code=400, detail=f"Could not read the file: {last_err}. Upload a valid .xlsx, .xls or .csv.")
    if best[0] < _MIN_MATCHED_COLUMNS:
        raise HTTPException(status_code=400, detail="This doesn't look like a valid statement — too few recognised columns.")
    return best[1]


def _seg_str(s: dict) -> str:
    return f"{s.get('route') or ''} {s.get('flight_no') or ''}".strip()


def _get_builder(parser_name: str):
    """Resolve a custom-parser module exposing build_col_map(cols) + build_row(row, cols)."""
    if parser_name == "lcc":
        from app.services import lcc_statement as m
        return m
    if parser_name == "di":
        from app.services import di_statement as m
        return m
    if parser_name == "divided-pnr":
        from app.services import divided_pnr as m
        return m
    if parser_name == "flown-report":
        from app.services import flown_report as m
        return m
    if parser_name == "cta-bta":
        from app.services import cta_bta_report as m
        return m
    # Generic flat parsers (Third Party GDS/LCC, …) registered in flat_statement.
    from app.services import flat_statement
    b = flat_statement.get(parser_name)
    if b is not None:
        return b
    raise HTTPException(status_code=500, detail=f"No parser registered for '{parser_name}'.")


# ── routes ───────────────────────────────────────────────────────────────────
@router.get("/{slug}/columns")
async def get_columns(slug: str, current_user: User = Depends(get_current_user)):
    slug, _ = _resolve(slug)
    cols = spec.columns(slug)
    if spec.fold_taxes(slug):
        cols = cols + [{"header": "Taxes", "field": "__taxes__"}]
    return cols


@router.post("/{slug}/upload")
async def upload_statement(
    slug: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Parse a statement export → verbatim fixed columns + folded taxes, under one batch."""
    slug, model = _resolve(slug)

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    parser_name = spec.parser(slug)
    batch_id = str(uuid.uuid4())
    uploaded_at = datetime.utcnow()

    # Store the original file in GCS (best-effort — never lose a successful import).
    file_url = None
    try:
        from app.services import gcs
        blob_name = f"statements/{current_user.tenant_id}/{slug}/{batch_id}/{file.filename}"
        await gcs.upload_bytes(content, blob_name, file.content_type or "application/octet-stream", _bucket())
        file_url = blob_name
    except Exception:  # noqa: BLE001
        file_url = None

    objs = []
    if parser_name:
        # Multi-format normalizer (LCC / DI): alias-map → canonical fields (+ fold taxes/segments/ssr for LCC).
        builder = _get_builder(parser_name)
        df = _detect_df(content, file.filename or "", lambda cols: len(builder.build_col_map(cols)))
        cols = [str(c) for c in df.columns]
        matched = len(builder.build_col_map(cols))
        for _, row in df.iterrows():
            b = builder.build_row(row, cols)
            if not (b["data"] or b["taxes"] or b["segments"] or b["ssr"]):
                continue  # blank row
            objs.append(model(
                tenant_id=current_user.tenant_id, created_by_id=current_user.id,
                batch_id=batch_id, source_file=file.filename, file_url=file_url, uploaded_at=uploaded_at,
                data=b["data"], taxes=b["taxes"], segments=b["segments"],
                ssr=b["ssr"], raw_data=b["raw_data"], source_format=b["source_format"],
            ))
    else:
        # Verbatim spec-driven path (TGQ HMPR / NDC): fixed columns + Tax_TypeN/TaxN folding.
        df, colmap, normmap = _parse(content, file.filename or "", slug)
        matched = len(colmap)
        fold = spec.fold_taxes(slug)
        for _, row in df.iterrows():
            data = {field: _clean(row[col]) for col, field in colmap.items()}
            taxes = _fold_taxes(row, normmap) if fold else []
            if not any(v is not None for v in data.values()) and not taxes:
                continue  # blank row
            objs.append(model(
                tenant_id=current_user.tenant_id, created_by_id=current_user.id,
                batch_id=batch_id, source_file=file.filename, file_url=file_url,
                uploaded_at=uploaded_at, data=data, taxes=taxes,
            ))

    if not objs:
        raise HTTPException(status_code=400, detail="No data rows were found in the file.")

    db.add_all(objs)
    await db.commit()
    return {
        "batch_id": batch_id,
        "type": slug,
        "file_name": file.filename,
        "inserted": len(objs),
        "matched_columns": matched,
    }


@router.get("/{slug}/records")
async def list_records(
    slug: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    batch_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated rows — fixed columns flattened from `data`, plus a folded `Taxes` column."""
    slug, model = _resolve(slug)
    base = select(model).where(*_scope(model, current_user))
    if batch_id:
        base = base.where(model.batch_id == batch_id)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    q = base.order_by(model.uploaded_at.desc(), model.id.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    parser_name = spec.parser(slug)
    fold = spec.fold_taxes(slug)
    cols = spec.columns(slug)
    if parser_name == "lcc":
        cols = cols + [
            {"header": "Taxes", "field": "__taxes__"},
            {"header": "Segments", "field": "__segments__"},
            {"header": "SSR", "field": "__ssr__"},
            {"header": "Format", "field": "__format__"},
        ]
    elif parser_name:  # any other custom parser (DI / Divided PNR / Flown / Third Party …) is a flat ledger
        cols = cols + [{"header": "Format", "field": "__format__"}]
    elif fold:
        cols = cols + [{"header": "Taxes", "field": "__taxes__"}]

    out_rows = []
    for r in rows:
        d = dict(r.data or {})
        d["id"] = r.id
        if parser_name == "lcc":
            d["__taxes__"] = " · ".join(
                f"{t.get('code')} {t.get('amount') or ''}".strip()
                for t in (r.taxes or []) if t.get("code")
            )
            d["__segments__"] = " · ".join(_seg_str(s) for s in (r.segments or []))
            d["__ssr__"] = " · ".join(
                f"{s.get('code')} {s.get('amount') or ''}".strip()
                for s in (r.ssr or []) if s.get("code")
            )
            d["__format__"] = r.source_format or ""
        elif parser_name:
            d["__format__"] = r.source_format or ""
        elif fold:
            d["__taxes__"] = " · ".join(
                f"{t.get('type')} {t.get('amount') or ''}".strip()
                for t in (r.taxes or []) if t.get("type")
            )
        out_rows.append(d)

    return {"total": total or 0, "limit": limit, "offset": offset, "columns": cols, "rows": out_rows}


@router.get("/{slug}/batches")
async def list_batches(slug: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """One row per upload — file name, when, how many rows, whether the file is stored."""
    slug, model = _resolve(slug)
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


@router.get("/{slug}/batches/{batch_id}/file-url")
async def get_batch_file_url(
    slug: str,
    batch_id: str,
    inline: bool = Query(True, description="inline (preview) vs attachment (download)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Signed GCS URL for the original uploaded file — inline for preview, attachment for download."""
    slug, model = _resolve(slug)
    row = (await db.execute(
        select(model.file_url, model.source_file)
        .where(model.batch_id == batch_id, *_scope(model, current_user)).limit(1)
    )).first()
    if not row or not row.file_url:
        raise HTTPException(status_code=404, detail="No file stored for this upload.")
    from app.services import gcs
    url = await gcs.generate_signed_url(row.file_url, _bucket(), expiry_minutes=60, inline=inline)
    return {"url": url, "file_name": row.source_file}


@router.delete("/{slug}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(slug: str, record_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    slug, model = _resolve(slug)
    obj = (await db.execute(
        select(model).where(model.id == record_id, *_scope(model, current_user))
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Record not found.")
    await db.delete(obj)
    await db.commit()


@router.delete("/{slug}/batches/{batch_id}")
async def delete_batch(slug: str, batch_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete an entire upload (all rows sharing the batch_id)."""
    slug, model = _resolve(slug)
    res = await db.execute(delete(model).where(model.batch_id == batch_id, *_scope(model, current_user)))
    await db.commit()
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return {"deleted": res.rowcount}


@router.get("/{slug}/template")
async def download_template(slug: str, current_user: User = Depends(get_current_user)):
    """Blank .xlsx with the exact headers (fixed columns + Tax_Type1/Tax1 … pairs)."""
    slug, _ = _resolve(slug)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = f"{spec.spec_for(slug)['label']} Template"[:31]
    ws.append(spec.template_headers(slug))

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{slug}_template.xlsx"'},
    )
