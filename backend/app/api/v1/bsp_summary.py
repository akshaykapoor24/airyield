"""BSP Summary (FCAGBILLSUMNG) upload + summary↔detailed group reconciliation.

Mounted at prefix ``/bsp`` alongside the detailed BSP router:
  POST   /bsp/summary/upload         upload a summary PDF (starts a new group)
  GET    /bsp/summary/{batch_id}     summary status + header + grand totals + match
  GET    /bsp/summary/{batch_id}/rows  per-airline breakdown
  GET    /bsp/groups                 paired list for the BSP repository
  GET    /bsp/groups/{group_id}      per-line summary-vs-detailed comparison
  DELETE /bsp/groups/{group_id}      delete both legs + files
"""
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.bsp_statement import BspStatement
from app.models.bsp_summary import BspSummaryStatement, BspSummaryRow
from app.services import file_store
from app.utils.security import create_file_token, verify_file_token
from app.schemas.bsp_summary import (
    BspSummaryUploadResponse, BspSummaryRead, BspSummaryRowRead,
    BspGroupRead, BspGroupComparison, BspComparisonLine,
)

router = APIRouter()
logger = logging.getLogger(__name__)

GT_LINES = ("issues", "refunds", "debit_memos", "credit_memos",
            "std_comm", "sup_comm", "tax_on_comm", "balance_payable")
GT_TOLERANCE = Decimal("1")


def _bsp_bucket() -> str:
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _detail_progress(s: BspStatement) -> int:
    if s.status == "completed":
        return 100
    if s.total_pages:
        return min(100, int(s.processed_pages * 100 / s.total_pages))
    return 0


# ── Upload a summary PDF → new group + queue for parsing ────────────────────
@router.post("/summary/upload", response_model=BspSummaryUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_bsp_summary(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store a BSP **summary** PDF, start a new statement group, and enqueue parsing.
    The user then uploads the matching detailed PDF against the returned group_id."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")
    if not file.filename.lower().endswith(".pdf") and (file.content_type or "") != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are supported.")

    max_bytes = settings.BSP_MAX_UPLOAD_MB * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.BSP_MAX_UPLOAD_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    batch_id = str(uuid.uuid4())
    group_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # Falls back to local disk when the bucket is unreachable — a storage outage must
    # not stop the statement being parsed (the bytes are already in hand).
    file_url, remote = await file_store.store(
        content, f"bsp-summary/{current_user.tenant_id}/{batch_id}/{file.filename}",
        "application/pdf", _bsp_bucket(),
    )
    if not remote:
        logger.warning("[BSP] Stored summary %s locally — remote storage unavailable.", file.filename)

    db.add(BspSummaryStatement(
        batch_id=batch_id, tenant_id=current_user.tenant_id, created_by_id=current_user.id,
        group_id=group_id, file_name=file.filename, file_url=file_url,
        status="pending", created_at=now,
    ))
    await db.commit()

    from app.workers.bsp_tasks import parse_bsp_summary
    parse_bsp_summary.delay(batch_id, current_user.tenant_id, current_user.id)
    return BspSummaryUploadResponse(batch_id=batch_id, group_id=group_id, status="pending")


async def _owned_summary(batch_id: str, db: AsyncSession, user: User) -> BspSummaryStatement:
    s = await db.scalar(select(BspSummaryStatement).where(
        BspSummaryStatement.batch_id == batch_id,
        BspSummaryStatement.tenant_id == user.tenant_id,
        BspSummaryStatement.created_by_id == user.id,
    ))
    if not s:
        raise HTTPException(status_code=404, detail="BSP summary not found")
    return s


@router.get("/summary/{batch_id}", response_model=BspSummaryRead)
async def get_bsp_summary(batch_id: str, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    return BspSummaryRead.model_validate(await _owned_summary(batch_id, db, current_user))


@router.get("/summary/{batch_id}/rows", response_model=List[BspSummaryRowRead])
async def get_bsp_summary_rows(batch_id: str, db: AsyncSession = Depends(get_db),
                               current_user: User = Depends(get_current_user)):
    await _owned_summary(batch_id, db, current_user)
    rows = (await db.execute(
        select(BspSummaryRow).where(BspSummaryRow.summary_id == batch_id).order_by(BspSummaryRow.id)
    )).scalars().all()
    return [BspSummaryRowRead.model_validate(r) for r in rows]


@router.post("/summary/{batch_id}/reparse", status_code=status.HTTP_202_ACCEPTED)
async def reparse_bsp_summary(batch_id: str, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    """Re-run the parser on the already-stored summary PDF, in place (same group).
    Useful after a parser improvement — e.g. to backfill the per-FOP (CASH / CARD)
    breakdown for a summary that was parsed before that support existed. The worker
    is idempotent: it deletes the old rows and re-inserts from the stored PDF."""
    s = await _owned_summary(batch_id, db, current_user)
    if not s.file_url:
        raise HTTPException(status_code=404, detail="No source file to re-parse.")
    if s.status == "processing":
        raise HTTPException(status_code=409, detail="This summary is already being processed.")
    s.status = "pending"
    s.error = None
    await db.commit()   # commit BEFORE enqueue so the worker can't 404 on its own batch

    from app.workers.bsp_tasks import parse_bsp_summary
    parse_bsp_summary.delay(batch_id, current_user.tenant_id, current_user.id)
    return {"batch_id": batch_id, "status": "pending"}


_FILE_KIND = "bsp_summary"


@router.get("/summary/{batch_id}/file-url")
async def get_bsp_summary_file_url(batch_id: str, request: Request,
                                   db: AsyncSession = Depends(get_db),
                                   current_user: User = Depends(get_current_user)):
    """URL to view the source summary PDF inline — a signed GCS URL, or a tokenised
    link to the endpoint below when the PDF is held locally."""
    s = await _owned_summary(batch_id, db, current_user)
    if not s.file_url:
        raise HTTPException(status_code=404, detail="No file attached to this summary.")
    url = await file_store.signed_url(s.file_url, _bsp_bucket(), expiry_minutes=60, inline=True)
    if url is None:
        token = create_file_token(batch_id, _FILE_KIND)
        url = f"{request.url_for('stream_bsp_summary_file', batch_id=batch_id)}?token={token}"
    return {"url": url}


@router.get("/summary/{batch_id}/file", name="stream_bsp_summary_file")
async def stream_bsp_summary_file(
    batch_id: str,
    token: str = Query(..., description="Short-lived file-access token from /file-url"),
    db: AsyncSession = Depends(get_db),
):
    """Serve a locally-stored summary PDF. Authorised by the short-lived token rather
    than a header, because this is opened with window.open (see bsp.stream_bsp_file)."""
    if not verify_file_token(token, batch_id, _FILE_KIND):
        raise HTTPException(status_code=403, detail="Invalid or expired file link.")
    s = await db.scalar(select(BspSummaryStatement).where(BspSummaryStatement.batch_id == batch_id))
    if not s or not s.file_url:
        raise HTTPException(status_code=404, detail="No file attached to this summary.")
    try:
        content = await file_store.load(s.file_url, _bsp_bucket())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The stored file is no longer available.")
    name = s.file_name or file_store.file_name(s.file_url) or "summary.pdf"
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.get("/summary/{batch_id}/xlsx")
async def export_bsp_summary_xlsx(batch_id: str, db: AsyncSession = Depends(get_db),
                                  current_user: User = Depends(get_current_user)):
    """Download the uploaded Agent Billing Summary as an Excel workbook (data-filled)."""
    from app.services.bsp_export import build_bsp_summary_xlsx, xlsx_filename
    s = await _owned_summary(batch_id, db, current_user)
    rows = (await db.execute(
        select(BspSummaryRow).where(BspSummaryRow.summary_id == batch_id).order_by(BspSummaryRow.id)
    )).scalars().all()
    buf = build_bsp_summary_xlsx(s, rows)
    fname = xlsx_filename("bsp-summary", s.agent_code or s.agent_name, s.reference)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ── Paired groups list for the BSP repository ───────────────────────────────
@router.get("/groups", response_model=List[BspGroupRead])
async def list_bsp_groups(db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    from app.models.user import User as UserModel
    summaries = (await db.execute(
        select(BspSummaryStatement).where(
            BspSummaryStatement.tenant_id == current_user.tenant_id,
            BspSummaryStatement.created_by_id == current_user.id,
        ).order_by(BspSummaryStatement.created_at.desc())
    )).scalars().all()
    group_ids = [s.group_id for s in summaries]
    details = {}
    if group_ids:
        for d in (await db.execute(select(BspStatement).where(
            BspStatement.group_id.in_(group_ids),
            BspStatement.tenant_id == current_user.tenant_id,
        ))).scalars().all():
            details[d.group_id] = d
    uname = await db.scalar(select(UserModel.full_name).where(UserModel.id == current_user.id))

    out = []
    for s in summaries:
        d = details.get(s.group_id)
        out.append(BspGroupRead(
            group_id=s.group_id, agent_code=s.agent_code, agent_name=s.agent_name,
            reference=s.reference, period_from=s.period_from, period_to=s.period_to,
            summary_batch_id=s.batch_id, summary_status=s.status,
            summary_balance=s.gt_balance_payable, summary_file_name=s.file_name,
            detail_batch_id=(d.batch_id if d else None),
            detail_status=(d.status if d else None),
            detail_balance=(d.gt_balance_payable if d else None),
            detail_progress_pct=(_detail_progress(d) if d else None),
            detail_file_name=(d.file_name if d else None),
            match_status=s.match_status,
            created_by_name=uname, created_at=s.created_at,
        ))
    return out


@router.get("/groups/{group_id}", response_model=BspGroupComparison)
async def get_bsp_group_comparison(group_id: str, db: AsyncSession = Depends(get_db),
                                   current_user: User = Depends(get_current_user)):
    summ = await db.scalar(select(BspSummaryStatement).where(
        BspSummaryStatement.group_id == group_id,
        BspSummaryStatement.tenant_id == current_user.tenant_id,
        BspSummaryStatement.created_by_id == current_user.id,
    ))
    if not summ:
        raise HTTPException(status_code=404, detail="BSP statement group not found")
    det = await db.scalar(select(BspStatement).where(
        BspStatement.group_id == group_id,
        BspStatement.tenant_id == current_user.tenant_id,
    ))

    lines: List[BspComparisonLine] = []
    for name in GT_LINES:
        s = getattr(summ, f"gt_{name}")
        d = getattr(det, f"gt_{name}") if det else None
        var = (Decimal(str(s or 0)) - Decimal(str(d or 0))) if (s is not None or d is not None) else None
        ok = var is not None and abs(var) <= GT_TOLERANCE
        lines.append(BspComparisonLine(line=name, summary=s, detail=d, variance=var, ok=ok))

    return BspGroupComparison(
        group_id=group_id, match_status=summ.match_status, matched_at=summ.matched_at,
        lines=lines, summary=BspSummaryRead.model_validate(summ),
    )


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bsp_group(group_id: str, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    summ = await db.scalar(select(BspSummaryStatement).where(
        BspSummaryStatement.group_id == group_id,
        BspSummaryStatement.tenant_id == current_user.tenant_id,
        BspSummaryStatement.created_by_id == current_user.id,
    ))
    det = await db.scalar(select(BspStatement).where(
        BspStatement.group_id == group_id,
        BspStatement.tenant_id == current_user.tenant_id,
        BspStatement.created_by_id == current_user.id,
    ))
    if not summ and not det:
        raise HTTPException(status_code=404, detail="BSP statement group not found")

    blobs = []
    if summ:
        blobs.append(summ.file_url)
        await db.delete(summ)
    if det:
        blobs.append(det.file_url)
        await db.delete(det)
    await db.commit()
    for b in blobs:
        if b:
            try:
                await file_store.delete(b, _bsp_bucket())
            except Exception:  # noqa: BLE001
                pass
    return None
