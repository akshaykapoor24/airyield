"""Platform admin → Subscriptions → Invoice: invoices the platform raises to a workspace.

Mounted under /subscriptions beside the plan console (api/v1/__init__.py), and guarded the
same way: PLATFORM_ADMIN on every route, no tenant scoping, because billing workspaces is
the one job that looks across them.

    GET    /subscriptions/{tenant_id}/invoice-draft     what the Generate form opens with
    GET    /subscriptions/{tenant_id}/invoices          that workspace's invoices
    POST   /subscriptions/{tenant_id}/invoices          raise one — numbered, taxed, stored
    GET    /subscriptions/invoices/{id}/pdf             the document
    POST   /subscriptions/invoices/{id}/send            email it, PDF attached
    PATCH  /subscriptions/invoices/{id}                 mark paid / unpaid, or cancel

There is no DELETE, on purpose: see app/models/platform_invoice.py.
"""
import asyncio
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.subscriptions import _owner_map
from app.database import get_db
from app.dependencies import require_role
from app.models.platform_invoice import (
    STATUS_CANCELLED, STATUS_ISSUED, STATUS_PAID, PlatformInvoice,
)
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.platform_invoice import (
    InvoiceCreate, InvoiceDraft, InvoiceRead, InvoiceSend, InvoiceStatusUpdate,
)
from app.services import email_service
from app.services import platform_invoices as pi
from app.services.platform_invoice_pdf import build_platform_invoice_pdf, inr, pdf_filename

logger = logging.getLogger(__name__)

router = APIRouter()

_admin = Depends(require_role(UserRole.PLATFORM_ADMIN))


def _read(inv: PlatformInvoice) -> InvoiceRead:
    read = InvoiceRead.model_validate(inv)
    read.place_of_supply = pi.state_label(inv.place_of_supply_code)
    read.overdue = bool(inv.status == STATUS_ISSUED and inv.due_date and inv.due_date < date.today())
    return read


async def _tenant(db: AsyncSession, tenant_id: int) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
    return tenant


async def _invoice(db: AsyncSession, invoice_id: int) -> PlatformInvoice:
    inv = await db.get(PlatformInvoice, invoice_id)
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    return inv


async def _pdf_bytes(inv: PlatformInvoice) -> bytes:
    # ReportLab is CPU-bound; a long invoice must not stall every other request.
    buf = await asyncio.to_thread(build_platform_invoice_pdf, inv)
    return buf.getvalue()


@router.get("/{tenant_id}/invoice-draft", response_model=InvoiceDraft)
async def invoice_draft(tenant_id: int, db: AsyncSession = Depends(get_db), _: User = _admin):
    tenant = await _tenant(db, tenant_id)
    owner = (await _owner_map(db, [tenant.id])).get(tenant.id)
    return await pi.draft(db, tenant, owner)


@router.get("/{tenant_id}/invoices", response_model=list[InvoiceRead])
async def list_invoices(tenant_id: int, db: AsyncSession = Depends(get_db), _: User = _admin):
    rows = (await db.execute(
        select(PlatformInvoice)
        .where(PlatformInvoice.billed_tenant_id == tenant_id)
        .order_by(PlatformInvoice.invoice_date.desc(), PlatformInvoice.id.desc())
    )).scalars().all()
    return [_read(inv) for inv in rows]


@router.post("/{tenant_id}/invoices", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    tenant_id: int,
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = _admin,
):
    """Raise an invoice. Everything is validated and taxed BEFORE a number is taken, so a
    rejected form never touches the series."""
    tenant = await _tenant(db, tenant_id)
    try:
        issuer = pi.clean_party(payload.issuer.model_dump(), "Your company", bank=True)
        bill_to = pi.clean_party(payload.bill_to.model_dump(), "Bill to")
        lines = pi.clean_lines([line.model_dump() for line in payload.lines])
        totals = pi.compute(lines, payload.gst_rate, issuer, bill_to)
    except pi.InvoiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    number, fy, serial = await pi.allocate_number(db, payload.invoice_date)
    inv = PlatformInvoice(
        invoice_number=number,
        financial_year=fy,
        serial=serial,
        billed_tenant_id=tenant.id,
        status=STATUS_ISSUED,
        invoice_date=payload.invoice_date,
        due_date=payload.due_date,
        period_from=payload.period_from,
        period_to=payload.period_to,
        issuer=issuer,
        bill_to=bill_to,
        gst_treatment=totals.treatment,
        place_of_supply_code=totals.place_of_supply_code,
        gst_rate=pi.q2(str(payload.gst_rate)),
        currency="INR",
        line_items=totals.lines,
        subtotal=totals.subtotal,
        cgst=totals.cgst,
        sgst=totals.sgst,
        igst=totals.igst,
        total_tax=totals.total_tax,
        grand_total=totals.grand_total,
        notes=(payload.notes or "").strip() or None,
        created_by_id=admin.id,
        created_at=datetime.utcnow(),
    )
    db.add(inv)
    await db.commit()          # releases the numbering lock
    await db.refresh(inv)
    logger.info("platform invoice %s raised to workspace %s for %s", number, tenant.id, inv.grand_total)
    return _read(inv)


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: int, db: AsyncSession = Depends(get_db), _: User = _admin):
    inv = await _invoice(db, invoice_id)
    pdf = await _pdf_bytes(inv)
    return StreamingResponse(
        iter([pdf]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{pdf_filename(inv)}"'},
    )


@router.post("/invoices/{invoice_id}/send", response_model=InvoiceRead)
async def send_invoice(
    invoice_id: int,
    payload: InvoiceSend,
    db: AsyncSession = Depends(get_db),
    _: User = _admin,
):
    """Email the invoice, PDF attached. Marked sent only once the mail server accepts it."""
    inv = await _invoice(db, invoice_id)
    if inv.status == STATUS_CANCELLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="A cancelled invoice can't be sent.")
    try:
        await email_service.send_invoice_email(
            str(payload.to),
            invoice_number=inv.invoice_number,
            issuer_name=inv.issuer.get("name") or "",
            recipient_name=inv.bill_to.get("name") or "",
            amount=f"INR {inr(inv.grand_total)}",
            due_date=inv.due_date.strftime("%d %b %Y") if inv.due_date else None,
            message=payload.message,
            pdf=await _pdf_bytes(inv),
            filename=pdf_filename(inv),
        )
    except Exception as exc:  # noqa: BLE001 — the admin must hear it did not go
        logger.exception("platform invoice %s: email to %s failed", inv.invoice_number, payload.to)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The email could not be sent ({exc}). The invoice was not marked as sent.",
        )
    inv.sent_at = datetime.utcnow()
    inv.sent_to = str(payload.to)
    await db.commit()
    await db.refresh(inv)
    return _read(inv)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceRead)
async def update_invoice_status(
    invoice_id: int,
    payload: InvoiceStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = _admin,
):
    """Record a payment (there is no gateway), undo one recorded by mistake, or cancel.

    Cancelling is final. A cancelled number stays in the series with its reason — that is
    what makes the series gapless — and the correct invoice is raised as a new one.
    """
    inv = await _invoice(db, invoice_id)
    if inv.status == STATUS_CANCELLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This invoice is cancelled. Raise a new one instead.")

    if payload.status == STATUS_PAID:
        inv.status = STATUS_PAID
        inv.paid_at = payload.paid_at or date.today()
        inv.payment_reference = (payload.payment_reference or "").strip() or None
    elif payload.status == STATUS_ISSUED:
        inv.status = STATUS_ISSUED
        inv.paid_at = None
        inv.payment_reference = None
    else:
        reason = (payload.cancel_reason or "").strip()
        if not reason:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Say why the invoice is being cancelled — it is printed on it.")
        inv.status = STATUS_CANCELLED
        inv.cancelled_at = datetime.utcnow()
        inv.cancel_reason = reason

    await db.commit()
    await db.refresh(inv)
    return _read(inv)
