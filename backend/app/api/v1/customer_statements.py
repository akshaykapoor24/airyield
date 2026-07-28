from __future__ import annotations

import io
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException, status, Query
from fastapi.responses import StreamingResponse
import pandas as pd
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.customer_statement import CustomerStatement, CustomerStatementTicket
from app.models.user import User
from app.schemas.uploaded_ticket import TicketExtractionPreview, TicketRow
from app.schemas.customer_statement import (
    ConfirmCustomerStatementPayload,
    ConfirmCustomerStatementResult,
    CustomerStatementRead,
    CustomerStatementTicketRead,
    CustomerStatementTicketUpdate,
)
from app.services.ticket_extraction import TicketExtractionService, TEMPLATE_HEADERS

router = APIRouter()

# The subset of columns a customer-statement row carries (mirrors the CustomerStatementTicket
# model — shared/B2B only). Copied verbatim from each parsed TicketRow at confirm time.
_ROW_FIELDS = [
    "booking_ref", "segment_type", "invoice_type", "invoice_no", "ticket_date",
    "last_name", "first_name", "sector", "booking_class", "departure_datetime",
    "gds_pnr", "airlines_code", "ticket_number",
    "sell_fare", "sell_tax", "sell_tax_yq", "sale_yr", "sale_k3", "rei_sell",
    "seat_selection", "excess_baggage", "meals", "rfd_sell", "can_charge",
    "booking_fee_sell", "cgst_sell", "sgst_sell", "igst_sell", "comm_sell", "adm",
    "incentive_sell", "dis_sell", "tds_sell", "total_amt", "paid_by_credit_card", "net_amt",
    "cc", "acc_code", "sold_to", "customer_name", "tour_code",
    "tax_breakup", "segments", "airline_name", "split_type",
]


# ── Template download ──────────────────────────────────────────────────────
@router.get("/template/download")
async def download_customer_template(
    current_user: User = Depends(get_current_user),
):
    """Blank B2B XLSX template (same column shape as the internal-statement B2B template)."""
    df = pd.DataFrame(columns=TEMPLATE_HEADERS)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=customer_statement_template.xlsx"},
    )


# ── Upload flow: Step 1 — extract / preview ────────────────────────────────
@router.post("/upload/extract", response_model=TicketExtractionPreview)
async def extract_customer_file(
    file: UploadFile = File(...),
    column_mapping: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    """Parse an XLS/XLSX and return a preview for review. B2B only. No DB write.
    Reuses the internal-statement extraction service (table-agnostic)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    max_mb = 50
    chunk = await file.read(max_mb * 1024 * 1024 + 1)
    if len(chunk) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {max_mb} MB limit.")

    mapping_dict: Optional[dict[str, str]] = None
    if column_mapping:
        try:
            mapping_dict = json.loads(column_mapping)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=400, detail="column_mapping must be a valid JSON string.")

    try:
        result = await TicketExtractionService.extract(
            chunk, file.filename, column_mapping=mapping_dict, statement_type="B2B",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return TicketExtractionPreview(
        file_name=result["file_name"],
        total_rows=result["total_rows"],
        rows=[TicketRow(**r) for r in result["rows"]],
        warnings=result.get("warnings", []),
        xls_columns=result.get("xls_columns", []),
        suggested_mapping=result.get("suggested_mapping", {}),
        is_template_match=result.get("is_template_match", True),
        sample_row=result.get("sample_row", {}),
    )


# ── Upload flow: Step 2 — confirm / save ──────────────────────────────────
@router.post(
    "/upload/confirm",
    response_model=ConfirmCustomerStatementResult,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_customer_upload(
    payload: ConfirmCustomerStatementPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist a reviewed customer statement + its ticket rows into the customer tables."""
    if not payload.rows:
        raise HTTPException(status_code=400, detail="No rows to save.")

    batch_id = str(uuid.uuid4())
    now = datetime.utcnow()
    auto_name = f"{payload.agency} - {payload.valid_from}"

    statement = CustomerStatement(
        batch_id=batch_id,
        tenant_id=current_user.tenant_id,
        statement_type="B2B",
        statement_name=auto_name,
        agency=payload.agency,
        agency_id=payload.agency_id,
        entities=[e.model_dump() for e in payload.entities],
        login_ids=[l.model_dump() for l in payload.login_ids],
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        file_name=payload.file_name,
        created_by_id=current_user.id,
        created_at=now,
    )
    db.add(statement)

    for row in payload.rows:
        ticket = CustomerStatementTicket(
            batch_id=batch_id,
            file_name=payload.file_name,
            tenant_id=current_user.tenant_id,
            created_by_id=current_user.id,
            created_at=now,
            statement_type="B2B",
            **{f: getattr(row, f) for f in _ROW_FIELDS},
        )
        db.add(ticket)

    await db.commit()
    return ConfirmCustomerStatementResult(batch_id=batch_id, created_count=len(payload.rows))


# ── Statement listing ──────────────────────────────────────────────────────
@router.get("/statements", response_model=list[CustomerStatementRead])
async def list_customer_statements(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """All customer statements for the current tenant/user with ticket counts."""
    count_subq = (
        select(CustomerStatementTicket.batch_id, func.count(CustomerStatementTicket.id).label("ticket_count"))
        .where(
            CustomerStatementTicket.tenant_id == current_user.tenant_id,
            CustomerStatementTicket.created_by_id == current_user.id,
        )
        .group_by(CustomerStatementTicket.batch_id)
        .subquery()
    )
    q = (
        select(
            CustomerStatement,
            func.coalesce(count_subq.c.ticket_count, 0).label("ticket_count"),
            User.full_name.label("created_by_name"),
        )
        .outerjoin(count_subq, CustomerStatement.batch_id == count_subq.c.batch_id)
        .outerjoin(User, User.id == CustomerStatement.created_by_id)
        .where(
            CustomerStatement.tenant_id == current_user.tenant_id,
            CustomerStatement.created_by_id == current_user.id,
        )
        .order_by(CustomerStatement.created_at.desc())
    )
    result = await db.execute(q)
    return [
        CustomerStatementRead(
            batch_id=stmt.batch_id,
            statement_type=getattr(stmt, "statement_type", "B2B"),
            statement_name=stmt.statement_name,
            agency=stmt.agency,
            agency_id=stmt.agency_id,
            entities=stmt.entities or [],
            login_ids=stmt.login_ids or [],
            valid_from=stmt.valid_from,
            valid_to=stmt.valid_to,
            file_name=stmt.file_name,
            file_url=stmt.file_url,
            ticket_count=int(count),
            created_by_name=created_by_name,
            created_at=stmt.created_at,
        )
        for stmt, count, created_by_name in result.all()
    ]


@router.get("/statements/{batch_id}", response_model=CustomerStatementRead)
async def get_customer_statement(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A single customer statement with its ticket count + directory selection."""
    stmt = await _get_owned_statement(db, batch_id, current_user)

    count = await db.scalar(
        select(func.count(CustomerStatementTicket.id)).where(
            CustomerStatementTicket.batch_id == batch_id,
            CustomerStatementTicket.tenant_id == current_user.tenant_id,
            CustomerStatementTicket.created_by_id == current_user.id,
        )
    )
    return CustomerStatementRead(
        batch_id=stmt.batch_id,
        statement_type=getattr(stmt, "statement_type", "B2B"),
        statement_name=stmt.statement_name,
        agency=stmt.agency,
        agency_id=stmt.agency_id,
        entities=stmt.entities or [],
        login_ids=stmt.login_ids or [],
        valid_from=stmt.valid_from,
        valid_to=stmt.valid_to,
        file_name=stmt.file_name,
        file_url=stmt.file_url,
        ticket_count=int(count or 0),
        created_at=stmt.created_at,
    )


@router.delete("/statements/{batch_id}", status_code=204)
async def delete_customer_statement(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a customer statement and all of its ticket rows."""
    stmt = await _get_owned_statement(db, batch_id, current_user)
    rows = await db.execute(
        select(CustomerStatementTicket).where(
            CustomerStatementTicket.batch_id == batch_id,
            CustomerStatementTicket.tenant_id == current_user.tenant_id,
            CustomerStatementTicket.created_by_id == current_user.id,
        )
    )
    for t in rows.scalars():
        await db.delete(t)
    await db.delete(stmt)
    await db.commit()


# ── Row listing / edit / delete ────────────────────────────────────────────
@router.get("/uploads", response_model=list[CustomerStatementTicketRead])
async def list_customer_rows(
    skip: int = 0,
    limit: int = 500,
    batch_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ticket rows for the current tenant/user, optionally scoped to one statement."""
    q = select(CustomerStatementTicket).where(
        CustomerStatementTicket.tenant_id == current_user.tenant_id,
        CustomerStatementTicket.created_by_id == current_user.id,
    ).order_by(CustomerStatementTicket.id.asc()).offset(skip).limit(limit)
    if batch_id:
        q = q.where(CustomerStatementTicket.batch_id == batch_id)
    result = await db.execute(q)
    return result.scalars().all()


@router.patch("/uploads/{ticket_id}", response_model=CustomerStatementTicketRead)
async def update_customer_row(
    ticket_id: int,
    payload: CustomerStatementTicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update editable fields on a customer-statement ticket row."""
    ticket = await _get_owned_row(db, ticket_id, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)
    await db.commit()
    await db.refresh(ticket)
    return ticket


@router.delete("/uploads/{ticket_id}", status_code=204)
async def delete_customer_row(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a customer-statement ticket row."""
    ticket = await _get_owned_row(db, ticket_id, current_user)
    await db.delete(ticket)
    await db.commit()


# ── GCS file upload & preview ──────────────────────────────────────────────
@router.post("/statements/{batch_id}/file")
async def upload_customer_statement_file(
    batch_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload the source XLS for a customer statement to GCS. Called right after confirm."""
    import logging, mimetypes
    from app.services import gcs as gcs_service
    from app.config import settings
    log = logging.getLogger(__name__)

    stmt = await _get_owned_statement(db, batch_id, current_user)
    bucket_name = settings.GCS_TICKETS_BUCKET_NAME
    content = await file.read()
    ct = mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    blob_name = f"customer-statements/{current_user.tenant_id}/{batch_id}/{file.filename}"
    try:
        await gcs_service.upload_bytes(content, blob_name, ct, bucket_name)
    except Exception as e:
        log.error("[CUSTOMER FILE UPLOAD] GCS upload FAILED: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"GCS upload failed: {e}")

    stmt.file_url = blob_name
    await db.commit()
    return {"file_url": blob_name}


@router.get("/statements/{batch_id}/file-url")
async def get_customer_statement_file_url(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Short-lived signed URL for previewing/downloading the statement source file."""
    from app.services import gcs as gcs_service
    from app.config import settings

    stmt = await _get_owned_statement(db, batch_id, current_user)
    if not stmt.file_url:
        raise HTTPException(status_code=404, detail="No file attached to this statement")
    bucket_name = settings.GCS_TICKETS_BUCKET_NAME
    url = await gcs_service.generate_signed_url(stmt.file_url, bucket_name, expiry_minutes=60, inline=False)
    return {"url": url, "file_type": "excel"}


# ── helpers ────────────────────────────────────────────────────────────────
async def _get_owned_statement(db: AsyncSession, batch_id: str, current_user: User) -> CustomerStatement:
    stmt = await db.scalar(
        select(CustomerStatement).where(
            CustomerStatement.batch_id == batch_id,
            CustomerStatement.tenant_id == current_user.tenant_id,
            CustomerStatement.created_by_id == current_user.id,
        )
    )
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")
    return stmt


async def _get_owned_row(db: AsyncSession, ticket_id: int, current_user: User) -> CustomerStatementTicket:
    ticket = await db.scalar(
        select(CustomerStatementTicket).where(
            CustomerStatementTicket.id == ticket_id,
            CustomerStatementTicket.tenant_id == current_user.tenant_id,
            CustomerStatementTicket.created_by_id == current_user.id,
        )
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket
