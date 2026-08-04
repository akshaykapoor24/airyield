import logging
import uuid
from collections import defaultdict, OrderedDict
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.airline import Airline
from app.models.bsp_statement import BspStatement, BspStatementRow, BspTaxBreakup, BspParseError
from app.services import file_store
from app.services.bsp_extraction import BspExtractionService
from app.utils.security import create_file_token, verify_file_token
from app.schemas.bsp_statement import (
    BspExtractionPreview,
    BspRow,
    ConfirmBspPayload,
    BspUploadResponse,
    BspStatementRead,
    BspStatementRowRead,
    BspTaxComponentRead,
    BspRowsPage,
    BspParseErrorRead,
    BspParseErrorsPage,
)
from app.schemas.bsp_summary import BspSummaryRowRead

router = APIRouter()
logger = logging.getLogger(__name__)


def _bsp_bucket() -> str:
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _progress_pct(s: BspStatement) -> int:
    if s.status == "completed":
        return 100
    if s.total_pages:
        return min(100, int(s.processed_pages * 100 / s.total_pages))
    return 0


def _to_read(s: BspStatement, created_by_name: Optional[str]) -> BspStatementRead:
    return BspStatementRead(
        batch_id=s.batch_id, statement_name=s.statement_name,
        airline_code=s.airline_code, airline_name=s.airline_name,
        period_from=s.period_from, period_to=s.period_to,
        file_name=s.file_name, file_url=s.file_url, row_count=s.row_count,
        status=s.status, total_pages=s.total_pages, processed_pages=s.processed_pages,
        total_rows=s.total_rows, processed_rows=s.processed_rows,
        progress_pct=_progress_pct(s), error=s.error,
        created_by_name=created_by_name, created_at=s.created_at,
    )


async def _get_owned_statement(batch_id: str, db: AsyncSession, current_user: User) -> BspStatement:
    stmt = await db.scalar(
        select(BspStatement).where(
            BspStatement.batch_id == batch_id,
            BspStatement.tenant_id == current_user.tenant_id,
            BspStatement.created_by_id == current_user.id,
        )
    )
    if not stmt:
        raise HTTPException(status_code=404, detail="BSP statement not found")
    return stmt


# ── Async PDF upload → queue for background parsing ─────────────────────────
@router.post("/upload", response_model=BspUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_bsp_pdf(
    file: UploadFile = File(...),
    airline_code: Optional[str] = Form(None),
    airline_name: Optional[str] = Form(None),
    period_from: Optional[date] = Form(None),
    period_to: Optional[date] = Form(None),
    statement_name: Optional[str] = Form(None),
    group_id: Optional[str] = Form(None),          # links to a BSP summary (paired upload)
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store a BSP settlement PDF and enqueue it for background parsing. Returns
    immediately with a batch_id; the frontend polls GET /bsp/statements/{id}.
    Airline/period are optional — the worker fills them from the PDF header."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")
    if not file.filename.lower().endswith(".pdf") and (file.content_type or "") != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are supported here. Use /upload/extract for Excel/CSV.")

    max_bytes = settings.BSP_MAX_UPLOAD_MB * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.BSP_MAX_UPLOAD_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # Store the source PDF. Falls back to local disk when the bucket is unreachable, so
    # a storage outage delays nothing — the parse only needs the bytes.
    file_url, remote = await file_store.store(
        content, f"bsp/{current_user.tenant_id}/{batch_id}/{file.filename}",
        "application/pdf", _bsp_bucket(),
    )
    if not remote:
        logger.warning("[BSP] Stored %s locally — remote storage unavailable.", file.filename)

    label = airline_name or airline_code or "Statement"
    stmt = BspStatement(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        statement_name=statement_name or f"BSP - {label} - {period_from or now.date()}",
        airline_code=airline_code,
        airline_name=airline_name,
        period_from=period_from,
        period_to=period_to,
        file_name=file.filename,
        file_url=file_url,
        status="pending",
        group_id=group_id,
        created_at=now,
    )
    db.add(stmt)
    await db.commit()   # commit BEFORE enqueue so the worker can't 404 on its own batch

    # Enqueue AFTER commit. Imported here to keep Celery/Redis off the API import path.
    from app.workers.bsp_tasks import parse_bsp_statement
    parse_bsp_statement.delay(batch_id, current_user.tenant_id, current_user.id)

    return BspUploadResponse(batch_id=batch_id, status="pending")


# ── Legacy Excel/CSV: extract (nothing saved) ───────────────────────────────
@router.post("/upload/extract", response_model=BspExtractionPreview)
async def extract_bsp_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")
    max_mb = 50
    chunk = await file.read(max_mb * 1024 * 1024 + 1)
    if len(chunk) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB limit.")
    try:
        result = await BspExtractionService.extract(chunk, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return BspExtractionPreview(
        file_name=result["file_name"],
        total_rows=result["total_rows"],
        rows=[BspRow(**r) for r in result["rows"]],
        warnings=result.get("warnings", []),
        xls_columns=result.get("xls_columns", []),
        suggested_mapping=result.get("suggested_mapping", {}),
    )


# ── Legacy Excel/CSV: confirm / save ────────────────────────────────────────
@router.post("/upload/confirm", status_code=status.HTTP_201_CREATED)
async def confirm_bsp_upload(
    payload: ConfirmBspPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.rows:
        raise HTTPException(status_code=400, detail="No rows to save.")
    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()
    label = payload.airline_name or payload.airline_code or "Statement"
    stmt = BspStatement(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        statement_name=f"BSP - {label} - {payload.period_from or now.date()}",
        airline_code=payload.airline_code,
        airline_name=payload.airline_name,
        period_from=payload.period_from,
        period_to=payload.period_to,
        file_name=payload.file_name,
        row_count=len(payload.rows),
        status="completed",   # spreadsheet rows are already parsed client-side
        total_rows=len(payload.rows),
        processed_rows=len(payload.rows),
        created_at=now,
    )
    db.add(stmt)
    for r in payload.rows:
        db.add(BspStatementRow(
            statement_id=batch_id,
            tenant_id=current_user.tenant_id,
            created_by_id=current_user.id,
            ticket_number=(r.ticket_number or "").strip() or None,
            document_number=(r.ticket_number or "").strip() or None,
            airline_code=r.airline_code or None,
            gross=r.gross,
            commission=r.commission,
            adm=r.adm,
            acm=r.acm,
            refund=r.refund,
            net_due=r.net_due,
            transaction_type=r.transaction_type or None,
            match_status="unmatched",
            raw_data=r.raw_data or None,
            created_at=now,
        ))
    await db.commit()

    # Auto-reconcile the newly-saved statement — best-effort, never fail the upload.
    try:
        from app.services.bsp_reconciliation import BspReconciliationService
        await BspReconciliationService.run(
            db, tenant_id=current_user.tenant_id, created_by_id=current_user.id, statement_id=batch_id,
        )
    except Exception:  # noqa: BLE001
        pass

    return {"batch_id": batch_id, "created_count": len(payload.rows)}


# ── Statements list / detail ────────────────────────────────────────────────
@router.get("/statements", response_model=list[BspStatementRead])
async def list_bsp_statements(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    res = await db.execute(
        select(BspStatement, User.full_name.label("created_by_name"))
        .outerjoin(User, User.id == BspStatement.created_by_id)
        .where(
            BspStatement.tenant_id == current_user.tenant_id,
            BspStatement.created_by_id == current_user.id,
        )
        .order_by(BspStatement.created_at.desc())
    )
    return [_to_read(s, nm) for s, nm in res.all()]


@router.get("/statements/{batch_id}", response_model=BspStatementRead)
async def get_bsp_statement(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = await _get_owned_statement(batch_id, db, current_user)
    nm = await db.scalar(select(User.full_name).where(User.id == stmt.created_by_id))
    return _to_read(stmt, nm)


# ── Rows (server-side paginated; taxes attached via one IN query) ───────────
def _row_conditions(batch_id: str, current_user: User, search: str | None,
                    txn_type: str | None, fop: str | None, air: str | None) -> list:
    """Scope + optional filter conditions shared by the count and page queries."""
    conds = [
        BspStatementRow.statement_id == batch_id,
        BspStatementRow.tenant_id == current_user.tenant_id,
        BspStatementRow.created_by_id == current_user.id,
    ]
    if search and search.strip():
        s = f"%{search.strip()}%"
        conds.append(or_(
            BspStatementRow.document_number.ilike(s),
            BspStatementRow.ticket_number.ilike(s),
        ))
    if txn_type:
        conds.append(BspStatementRow.transaction_type == txn_type)
    if fop:
        conds.append(BspStatementRow.form_of_payment == fop)
    if air:
        conds.append(BspStatementRow.airline_accounting_code == air)
    return conds


@router.get("/statements/{batch_id}/rows/facets")
async def bsp_row_facets(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct values for the detailed-rows filter dropdowns (this statement only)."""
    await _get_owned_statement(batch_id, db, current_user)
    scope = (
        BspStatementRow.statement_id == batch_id,
        BspStatementRow.tenant_id == current_user.tenant_id,
        BspStatementRow.created_by_id == current_user.id,
    )

    async def _distinct(col):
        rows = (await db.execute(
            select(col).where(*scope, col.isnot(None), col != "").distinct().order_by(col)
        )).scalars().all()
        return rows

    return {
        "txn_types": await _distinct(BspStatementRow.transaction_type),
        "fops": await _distinct(BspStatementRow.form_of_payment),
        "airlines": await _distinct(BspStatementRow.airline_accounting_code),
    }


@router.get("/statements/{batch_id}/rows", response_model=BspRowsPage)
async def list_bsp_rows(
    batch_id: str,
    offset: int = 0,
    limit: int = 100,
    search: Optional[str] = Query(None),
    txn_type: Optional[str] = Query(None),
    fop: Optional[str] = Query(None),
    air: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_statement(batch_id, db, current_user)
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    conds = _row_conditions(batch_id, current_user, search, txn_type, fop, air)

    total = await db.scalar(
        select(func.count()).select_from(BspStatementRow).where(*conds)
    )
    page_rows = (await db.execute(
        select(BspStatementRow).where(*conds)
        .order_by(BspStatementRow.id).offset(offset).limit(limit)
    )).scalars().all()

    # Attach taxes for this page in a single grouped query (no N+1).
    ids = [r.id for r in page_rows]
    by_row: dict[int, list] = defaultdict(list)
    if ids:
        taxes = (await db.execute(
            select(BspTaxBreakup).where(BspTaxBreakup.bsp_row_id.in_(ids))
        )).scalars().all()
        for t in taxes:
            by_row[t.bsp_row_id].append(BspTaxComponentRead.model_validate(t))

    rows_out = []
    for r in page_rows:
        item = BspStatementRowRead.model_validate(r)
        item.taxes = by_row.get(r.id, [])
        rows_out.append(item)

    return BspRowsPage(total=total or 0, offset=offset, limit=limit, rows=rows_out)


# ── Per-airline summary DERIVED from the detailed rows ──────────────────────
_FOP_DISPLAY = {"CA": "CASH", "CC": "CARD"}   # detailed FOP code → summary label
_FOP_ORDER   = {"CA": 0, "CC": 1}             # CASH before CARD, like the printed summary
_SUM_KEYS = ("issues", "refunds", "debit_memos", "credit_memos",
             "std_comm", "sup_comm", "tax_on_comm", "balance_payable")


async def _airline_iata_name_map(db: AsyncSession) -> dict:
    """{3-digit accounting code → (iata_code, name)} from the airline master, keyed like
    _load_airline_map (numeric preferred, icao fallback, zero-padded to 3)."""
    rows = (await db.execute(
        select(Airline.iata_numeric_code, Airline.icao_code, Airline.iata_code, Airline.name)
    )).all()
    out: dict[str, tuple] = {}
    for numeric, icao, iata, name in rows:
        code = (numeric or icao or "").strip()
        if not code:
            continue
        key = code.zfill(3) if code.isdigit() else code
        out.setdefault(key, (iata, name))
    return out


def _assemble_derived_summary(agg_rows, air_map: dict) -> list[BspSummaryRowRead]:
    """Turn the per-(category, airline, FOP) aggregate rows into the same CASH/CARD/TOTAL
    shape as the uploaded summary. ≤1 FOP → one full row; ≥2 FOPs → a sub-row per FOP
    carrying only issues+refunds (mirroring the PDF's blank cells) plus a TOTAL row."""
    def dec(v) -> Decimal:
        return Decimal(str(v)) if v is not None else Decimal("0")

    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for r in agg_rows:
        groups.setdefault((r.category or "BSP", r.air or ""), []).append(r)

    out: list[BspSummaryRowRead] = []
    _id = 0
    for (category, air), rows in sorted(groups.items(), key=lambda kv: kv[0]):
        iata, name = air_map.get(air, (None, None))
        total = {k: sum((dec(getattr(r, k)) for r in rows), Decimal("0")) for k in _SUM_KEYS}
        total_docs = sum((r.doc_count or 0) for r in rows)
        fops = sorted((r for r in rows if r.fop), key=lambda r: (_FOP_ORDER.get(r.fop, 99), r.fop))

        def mk(fop, vals, docs):
            nonlocal _id
            _id += 1
            return BspSummaryRowRead(id=_id, category=category, airline_code=air,
                                     airline_iata=iata, airline_name=name, fop=fop,
                                     doc_count=docs, **vals)

        if len(fops) <= 1:
            label = _FOP_DISPLAY.get(fops[0].fop, fops[0].fop) if fops else "TOTAL"
            out.append(mk(label, total, total_docs))
        else:
            for r in fops:
                out.append(mk(_FOP_DISPLAY.get(r.fop, r.fop),
                              {"issues": dec(r.issues), "refunds": dec(r.refunds),
                               "debit_memos": None, "credit_memos": None, "std_comm": None,
                               "sup_comm": None, "tax_on_comm": None, "balance_payable": None},
                              None))
            out.append(mk("TOTAL", total, total_docs))
    return out


@router.get("/statements/{batch_id}/summary", response_model=list[BspSummaryRowRead])
async def bsp_detailed_summary(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-airline summary AGGREGATED FROM THE DETAILED statement rows (not the uploaded
    summary PDF), returned in the same shape as the uploaded summary rows so the UI can
    compare the two and spot gaps. Computed live — no re-parse needed. Buckets
    transaction_amount into issues/refunds/debit/credit by the row's settlement section
    (same substring logic as the grand-total reconciliation), grouped per airline × FOP."""
    await _get_owned_statement(batch_id, db, current_user)

    R = BspStatementRow
    # ``settlement_section`` wins over the printed ``section``: a CANX row is listed under
    # ISSUES but its cancellation charge is settled as a debit memo, so once the parent
    # SPDR's charge is distributed onto it (workers/bsp_tasks.py::_distribute_spdr_canx) it
    # has to total under the SPDR's section — otherwise the split would silently shift money
    # from Debit Memos into Issues. Mirrors _section_bucket() on the worker side.
    sec = func.coalesce(R.raw_data["settlement_section"].astext, R.raw_data["section"].astext)
    cat = func.coalesce(R.raw_data["settlement_category"].astext,
                        R.raw_data["category"].astext, "BSP")

    def bucket(kw: str):
        return func.coalesce(func.sum(case((sec.ilike(f"%{kw}%"), R.transaction_amount))), 0)

    agg = (await db.execute(
        select(
            cat.label("category"),
            R.airline_accounting_code.label("air"),
            R.form_of_payment.label("fop"),
            bucket("ISSUE").label("issues"),
            bucket("REFUND").label("refunds"),
            bucket("DEBIT").label("debit_memos"),
            bucket("CREDIT").label("credit_memos"),
            func.coalesce(func.sum(R.standard_commission_amount), 0).label("std_comm"),
            func.coalesce(func.sum(R.supplier_discount_amount), 0).label("sup_comm"),
            func.coalesce(func.sum(R.tax_on_commission), 0).label("tax_on_comm"),
            func.coalesce(func.sum(R.balance_payable), 0).label("balance_payable"),
            func.count().label("doc_count"),
        )
        .where(
            R.statement_id == batch_id,
            R.tenant_id == current_user.tenant_id,
            R.created_by_id == current_user.id,
        )
        .group_by(cat, R.airline_accounting_code, R.form_of_payment)
    )).all()

    return _assemble_derived_summary(agg, await _airline_iata_name_map(db))


# ── Parse errors (paginated) ────────────────────────────────────────────────
@router.get("/statements/{batch_id}/errors", response_model=BspParseErrorsPage)
async def list_bsp_errors(
    batch_id: str,
    offset: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_statement(batch_id, db, current_user)
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    total = await db.scalar(
        select(func.count()).select_from(BspParseError).where(BspParseError.statement_id == batch_id)
    )
    rows = (await db.execute(
        select(BspParseError).where(BspParseError.statement_id == batch_id)
        .order_by(BspParseError.page_number).offset(offset).limit(limit)
    )).scalars().all()
    return BspParseErrorsPage(
        total=total or 0, offset=offset, limit=limit,
        errors=[BspParseErrorRead.model_validate(r) for r in rows],
    )


# ── Re-parse the stored PDF in place (backfill parser fixes) ────────────────
@router.post("/statements/{batch_id}/reparse", status_code=status.HTTP_202_ACCEPTED)
async def reparse_bsp_statement(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run the parser on the already-stored detailed PDF, in place (same batch +
    group). The worker is idempotent — it deletes this statement's existing rows and
    re-inserts from the stored PDF — so this safely backfills parser improvements
    (e.g. the TOUR/ESAC split) without a re-upload. Large statements take minutes."""
    stmt = await _get_owned_statement(batch_id, db, current_user)
    if not stmt.file_url:
        raise HTTPException(status_code=404, detail="No source file to re-parse.")
    if stmt.status == "processing":
        raise HTTPException(status_code=409, detail="This statement is already being processed.")
    stmt.status = "pending"
    stmt.error = None
    await db.commit()   # commit BEFORE enqueue so the worker can't 404 on its own batch

    from app.workers.bsp_tasks import parse_bsp_statement
    parse_bsp_statement.delay(batch_id, current_user.tenant_id, current_user.id)
    return {"batch_id": batch_id, "status": "pending"}


# ── Openable URL for the source PDF ─────────────────────────────────────────
_FILE_KIND = "bsp_detail"


@router.get("/statements/{batch_id}/file-url")
async def get_bsp_file_url(
    batch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A URL the browser can open directly — a GCS signed URL, or a tokenised link to
    the endpoint below when the PDF is held locally."""
    stmt = await _get_owned_statement(batch_id, db, current_user)
    if not stmt.file_url:
        raise HTTPException(status_code=404, detail="No source file attached.")
    url = await file_store.signed_url(stmt.file_url, _bsp_bucket(), expiry_minutes=60, inline=True)
    if url is None:
        token = create_file_token(batch_id, _FILE_KIND)
        url = f"{request.url_for('stream_bsp_file', batch_id=batch_id)}?token={token}"
    return {"url": url}


@router.get("/statements/{batch_id}/file", name="stream_bsp_file")
async def stream_bsp_file(
    batch_id: str,
    token: str = Query(..., description="Short-lived file-access token from /file-url"),
    db: AsyncSession = Depends(get_db),
):
    """Serve a locally-stored source PDF.

    Deliberately not behind `get_current_user`: this is opened via window.open, which
    sends no Authorization header. The single-batch, short-lived token from /file-url —
    itself issued only to the statement's owner — is the authorisation.
    """
    if not verify_file_token(token, batch_id, _FILE_KIND):
        raise HTTPException(status_code=403, detail="Invalid or expired file link.")
    stmt = await db.scalar(select(BspStatement).where(BspStatement.batch_id == batch_id))
    if not stmt or not stmt.file_url:
        raise HTTPException(status_code=404, detail="No source file attached.")
    try:
        content = await file_store.load(stmt.file_url, _bsp_bucket())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The stored file is no longer available.")
    name = stmt.file_name or file_store.file_name(stmt.file_url) or "statement.pdf"
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# ── XLS export of the detailed rows ─────────────────────────────────────────
@router.get("/statements/{batch_id}/xlsx")
async def export_bsp_detailed_xlsx(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download all detailed rows of a BSP statement as an Excel workbook (data-filled)."""
    from app.services.bsp_export import build_bsp_detailed_xlsx, xlsx_filename
    stmt = await _get_owned_statement(batch_id, db, current_user)
    rows = (await db.execute(
        select(BspStatementRow).where(
            BspStatementRow.statement_id == batch_id,
            BspStatementRow.tenant_id == current_user.tenant_id,
            BspStatementRow.created_by_id == current_user.id,
        ).order_by(BspStatementRow.id)
    )).scalars().all()

    # Attach every row's fare components in one join query (no per-row IN-list limit).
    by_row: dict[int, list] = defaultdict(list)
    taxes = (await db.execute(
        select(BspTaxBreakup)
        .join(BspStatementRow, BspTaxBreakup.bsp_row_id == BspStatementRow.id)
        .where(BspStatementRow.statement_id == batch_id)
    )).scalars().all()
    for t in taxes:
        by_row[t.bsp_row_id].append(t)

    buf = build_bsp_detailed_xlsx(stmt, rows, by_row)
    fname = xlsx_filename("bsp-detailed", stmt.airline_code or stmt.airline_name, stmt.statement_name)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ── Delete ──────────────────────────────────────────────────────────────────
@router.delete("/statements/{batch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bsp_statement(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = await _get_owned_statement(batch_id, db, current_user)
    blob = stmt.file_url
    await db.delete(stmt)  # cascade removes rows → tax breakups + parse errors
    await db.commit()
    if blob:
        await file_store.delete(blob, _bsp_bucket())
