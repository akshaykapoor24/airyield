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
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.corporate import Corporate
from app.models.customer import Customer
from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.models.tenant_airline import TenantAirline
from app.models.user import User
from app.services import customer_resolver as cres
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


async def _tenant_airline(db: AsyncSession, user: User, tenant_airline_id: int) -> TenantAirline:
    """Resolve one of the user's Airline Master entries. An LCC export carries no
    carrier, so this selection is the ONLY thing that identifies the airline."""
    obj = (await db.execute(
        select(TenantAirline).where(
            TenantAirline.id == tenant_airline_id,
            TenantAirline.tenant_id == user.tenant_id,
        )
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(
            status_code=400,
            detail="That airline is not in your Airline Master. Add it under User Master → Airline Master.",
        )
    return obj


def _stamp_airline(batch: LccDetailedBatch, ta: TenantAirline) -> None:
    batch.tenant_airline_id = ta.id
    batch.airline_id = ta.airline_id
    batch.airline_name = ta.airline_name
    batch.airline_code = ta.airline_code
    batch.airline_ref_id = ta.ref_id


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
    tenant_airline_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store the file, detect headers, auto-map, and stage a batch. Nothing is
    ingested yet — the user reviews the mapping, then calls /confirm.

    `tenant_airline_id` is required and resolved here rather than at /confirm, so a
    batch is never in a state where rows could be ingested without an airline."""
    ta = await _tenant_airline(db, current_user, tenant_airline_id)
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
    _stamp_airline(batch, ta)
    db.add(batch)
    await db.commit()

    return {
        "batch_id": batch_id,
        "file_name": file.filename,
        "airline_name": ta.airline_name,
        "airline_code": ta.airline_code,
        "airline_ref_id": ta.ref_id,
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
            "airline_name": b.airline_name,
            "airline_code": b.airline_code,
            "airline_ref_id": b.airline_ref_id,
            "tenant_airline_id": b.tenant_airline_id,
            "billable_rows": b.billable_rows,
            "resolved_rows": b.resolved_rows,
            "unresolved_rows": b.unresolved_rows,
            "projected_rows": b.projected_rows,
            "resolution_status": b.resolution_status,
        }
        for b in rows
    ]


class BatchAirlinePayload(BaseModel):
    tenant_airline_id: int


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

    ta = await _tenant_airline(db, current_user, payload.tenant_airline_id)
    _stamp_airline(batch, ta)

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
        "rows_updated": result.rowcount or 0,
    }


# ── billing: resolve each row to a customer / corporate ──────────────────────
# An LCC export names no customer, only a passenger per row. These endpoints resolve
# that passenger against the Customer master so the rows can later be projected into
# `uploaded_tickets`, the one table Customer/Corporate Billing reads.

MAX_GAP_GROUPS = 50          # mirrors api/v1/bsp_commission.py:54
_BILL_PARTY_TYPES = ("corporate", "direct")


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
) -> tuple[str | None, int | None, int | None]:
    """Authorise a party against the master rather than trusting the ids sent.

    Mirrors tickets.py::_resolve_customer_party. Returns the normalised triple, with
    the ids that do not belong to the chosen type nulled — the same discipline as
    frontend lib/customerType.ts::buildTagPayload, enforced server-side so a stale id
    from a previously chosen type can never travel attached to the wrong one.
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
        return "corporate", cust_id, row.id

    if not customer_id:
        raise HTTPException(status_code=400, detail="Pick a customer.")
    cust = (await db.execute(select(Customer).where(
        Customer.id == customer_id,
        Customer.tenant_id == user.tenant_id,
        Customer.created_by_id == user.id,
    ))).scalar_one_or_none()
    if not cust:
        raise HTTPException(status_code=400, detail=f"Customer id {customer_id} is not in your customers.")
    # A customer who belongs to a corporate is an employee — carry the corporate too,
    # because corporates.py defines a corporate's tickets as its employees' tickets.
    return ("corporate" if cust.corporate_id else "direct"), cust.id, cust.corporate_id


async def _owned_batch(batch_id: str, db: AsyncSession, current_user: User) -> LccDetailedBatch:
    batch = await db.scalar(
        select(LccDetailedBatch).where(
            LccDetailedBatch.batch_id == batch_id, *_scope(LccDetailedBatch, current_user)
        )
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return batch


async def _recount(db: AsyncSession, batch: LccDetailedBatch) -> None:
    """Refresh the batch's billing counters from its rows."""
    billable = (cres.RESOLVED, cres.DEFAULTED, cres.OVERRIDDEN)
    rows = (await db.execute(
        select(LccDetailed.bill_status, func.count())
        .where(LccDetailed.batch_id == batch.batch_id)
        .group_by(LccDetailed.bill_status)
    )).all()
    counts = {s: n for s, n in rows}
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
    """Classify every row and match its passenger against the Customer master."""
    payload = payload or ResolvePayload()
    batch = await _owned_batch(batch_id, db, current_user)
    if batch.status != "completed":
        raise HTTPException(status_code=409, detail="This upload is still importing.")

    index = await cres.CustomerIndex.load(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id
    )
    rows = (await db.execute(
        select(LccDetailed.id, LccDetailed.name1, LccDetailed.total, LccDetailed.bill_status)
        .where(LccDetailed.batch_id == batch_id, *_scope(LccDetailed, current_user))
    )).all()

    now = datetime.utcnow()
    default_set = bool(batch.default_customer_type)
    updates: list[dict] = []
    summary: dict[str, int] = {}

    for row_id, name1, total, current_status in rows:
        kind = _bill_kind(total)

        if not payload.reset_overrides and current_status == cres.OVERRIDDEN and kind != "payment":
            summary[cres.OVERRIDDEN] = summary.get(cres.OVERRIDDEN, 0) + 1
            updates.append({"id": row_id, "bill_kind": kind})
            continue

        if kind == "payment":
            m = cres.CustomerMatch(status=cres.EXCLUDED, note=cres.REASON[cres.EXCLUDED])
        else:
            m = index.resolve(name1)
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

    return {
        "batch_id": batch_id,
        "customers_in_scope": len(index),
        "summary": summary,
        "billable_rows": batch.billable_rows,
        "resolved_rows": batch.resolved_rows,
        "unresolved_rows": batch.unresolved_rows,
    }


@router.get("/batches/{batch_id}/billing-rows")
async def list_billing_rows(
    batch_id: str,
    status_filter: str | None = Query(None, alias="status"),
    kind: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The resolution worklist, paginated like /records."""
    await _owned_batch(batch_id, db, current_user)

    base = select(LccDetailed).where(
        LccDetailed.batch_id == batch_id, *_scope(LccDetailed, current_user)
    )
    if status_filter:
        base = base.where(LccDetailed.bill_status == status_filter)
    if kind:
        base = base.where(LccDetailed.bill_kind == kind)

    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = (await db.execute(
        base.order_by(LccDetailed.id.asc()).limit(limit).offset(offset)
    )).scalars().all()

    # Resolve the party names for display in one query rather than per row.
    cust_ids = {r.bill_customer_id for r in rows if r.bill_customer_id}
    corp_ids = {r.bill_corporate_id for r in rows if r.bill_corporate_id}
    cust_names = dict((await db.execute(
        select(Customer.id, func.concat(Customer.first_name, " ", func.coalesce(Customer.last_name, "")))
        .where(Customer.id.in_(cust_ids or {-1}))
    )).all())
    corp_names = dict((await db.execute(
        select(Corporate.id, Corporate.company).where(Corporate.id.in_(corp_ids or {-1}))
    )).all())

    return {
        "total": total or 0, "limit": limit, "offset": offset,
        "rows": [{
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
            "party_name": (corp_names.get(r.bill_corporate_id)
                           if r.bill_customer_type == "corporate"
                           else (cust_names.get(r.bill_customer_id) or "").strip() or None),
            "customer_name": (cust_names.get(r.bill_customer_id) or "").strip() or None,
            "bill_match_reason": r.bill_match_reason,
            "projected_ticket_id": r.projected_ticket_id,
        } for r in rows],
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
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id
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

    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id
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


@router.post("/batches/{batch_id}/send-to-billing")
async def send_to_billing(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Project the resolved rows into `uploaded_tickets` so billing can see them.

    Idempotent: re-running syncs rather than duplicates, and any ticket already on an
    invoice is left exactly as it was.
    """
    from app.services.lcc_billing_projection import project_batch

    batch = await _owned_batch(batch_id, db, current_user)
    if batch.status != "completed":
        raise HTTPException(status_code=409, detail="This upload is still importing.")
    if batch.resolution_status == "none":
        raise HTTPException(
            status_code=409,
            detail="Resolve this upload's customers first — nothing here has a party to bill yet.",
        )

    result = await project_batch(db, batch)
    await _recount(db, batch)
    await db.commit()
    return {"batch_id": batch_id, **result}


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
        # Declared at upload, not present in the source file — see models/tenant_airline.py.
        {"header": "Airline", "field": "__airline__"},
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
        d["__airline__"] = " ".join(x for x in (r.airline_code, r.airline_name) if x)
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
