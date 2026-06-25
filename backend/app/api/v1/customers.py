from datetime import date
from io import BytesIO
from typing import Optional

import pandas as pd
from dateutil import parser as _du
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.customer import Customer
from app.models.billing import Billing
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User
from app.models.tenant import Tenant
from app.schemas.customer import (
    CustomerCreate, CustomerUpdate, CustomerRead, CustomerBulkUploadResult,
    SoldTicketRead, SoldTicketsResponse, SoldTicketsSummary,
)
from app.schemas.billing import BillingCreate, BillingUpdate, BillingRead, BillingListItem
from app.services.billing_pdf import build_billing_pdf

router = APIRouter()

_MARKUP_TYPES = {"percentage", "fixed"}
_BILLING_TYPES = {"reseller", "agency"}
_GST_RATE = 0.18


def _scope(current_user: User):
    """Ownership filter: customer must belong to the current user + tenant."""
    return and_(
        Customer.tenant_id == current_user.tenant_id,
        Customer.created_by_id == current_user.id,
    )


def _f(value) -> float:
    """Coerce a possibly-None Decimal/str to float."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _norm_choice(value: Optional[str], allowed: set[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    return v if v in allowed else None


def _safe_date(*raws) -> Optional[date]:
    """Parse a ticket date string to a date. Handles ISO YYYY-MM-DD and dayfirst formats.
    Mirrors the parser used in services/deal_matching.py.
    """
    for raw in raws:
        if not raw:
            continue
        try:
            s = str(raw).strip()
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return date.fromisoformat(s[:10])
            return _du.parse(s, dayfirst=True).date()
        except Exception:
            continue
    return None


def _passenger_name(t: UploadedTicket) -> str:
    if t.pax_name:
        return t.pax_name
    name = f"{t.first_name or ''} {t.last_name or ''}".strip()
    return name or "—"


def _compute_markup(base: float, markup_type: Optional[str], markup_value) -> float:
    mtype = (markup_type or "").lower()
    mval = _f(markup_value)
    if mtype == "percentage":
        return base * mval / 100.0
    if mtype == "fixed":
        return mval
    return 0.0


def _compute_gst(base: float, markup: float, billing_type: Optional[str]) -> float:
    """GST (18%) base depends on billing type:
      - reseller: GST on the whole marked-up price (gross + markup)
      - agency:   GST on the markup only
      - unset/other: no GST applied
    """
    bt = (billing_type or "").lower()
    if bt == "reseller":
        return (base + markup) * _GST_RATE
    if bt == "agency":
        return markup * _GST_RATE
    return 0.0


async def _get_owned_customer(customer_id: int, db: AsyncSession, current_user: User) -> Customer:
    result = await db.execute(
        select(Customer).where(Customer.id == customer_id, _scope(current_user))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Customer not found")
    return obj


async def _get_owned_billing(billing_id: int, customer_id: int, db: AsyncSession, current_user: User) -> Billing:
    result = await db.execute(
        select(Billing).where(
            Billing.id == billing_id,
            Billing.customer_id == customer_id,
            Billing.tenant_id == current_user.tenant_id,
            Billing.created_by_id == current_user.id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Billing not found")
    return obj


@router.get("/", response_model=list[CustomerRead])
async def list_customers(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Customer).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Customer.first_name.ilike(term),
            Customer.last_name.ilike(term),
            Customer.company.ilike(term),
            Customer.email.ilike(term),
        ))
    q = q.order_by(Customer.first_name, Customer.last_name).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    first_name = (payload.first_name or "").strip()
    if not first_name:
        raise HTTPException(status_code=400, detail="first_name is required.")
    customer = Customer(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        first_name=first_name,
        last_name=(payload.last_name or "").strip() or None,
        company=(payload.company or "").strip() or None,
        title=(payload.title or "").strip() or None,
        phone=(payload.phone or "").strip() or None,
        email=(payload.email or "").strip() or None,
        gst_no=(payload.gst_no or "").strip() or None,
        markup_type=_norm_choice(payload.markup_type, _MARKUP_TYPES),
        markup_value=payload.markup_value,
        billing_type=_norm_choice(payload.billing_type, _BILLING_TYPES),
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer


@router.post("/bulk-upload", response_model=CustomerBulkUploadResult)
async def bulk_upload_customers(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"FIRST_NAME"}

    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        df.columns = [
            str(c).strip().upper().replace(" ", "_").replace("/", "_").replace("-", "_")
            for c in df.columns
        ]
        df.dropna(how="all", inplace=True)
        return df

    try:
        df = None
        used_header_row = 0
        last_missing = None

        for header_row in (0, 1, 2):
            try:
                if filename.endswith(".xls"):
                    df_try = pd.read_excel(BytesIO(content), dtype=str, header=header_row)
                else:
                    df_try = pd.read_excel(BytesIO(content), dtype=str, engine="openpyxl", header=header_row)
                df_try = _normalize_columns(df_try)
                missing = required - set(df_try.columns)
                last_missing = missing
                if not missing:
                    df = df_try
                    used_header_row = header_row
                    break
            except Exception:
                continue

        if df is None:
            detail = (
                "Missing required column: FIRST_NAME. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: FIRST_NAME"
            )
            raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}. Ensure it is a valid .xlsx or .xls file.")

    total = len(df)
    success = 0
    errors: list[str] = []

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        row_prefix = f"Row {row_num}"
        first_name = str(row.get("FIRST_NAME", "") or "").strip()
        if not first_name:
            errors.append(f"{row_prefix}: FIRST_NAME is required.")
            continue

        markup_value_raw = str(row.get("MARKUP_VALUE", "") or "").strip()
        markup_value: float | None = None
        if markup_value_raw:
            try:
                markup_value = float(markup_value_raw)
            except ValueError:
                errors.append(f"{row_prefix}: MARKUP_VALUE '{markup_value_raw}' is not a number.")
                continue

        try:
            customer = Customer(
                tenant_id=current_user.tenant_id,
                created_by_id=current_user.id,
                first_name=first_name,
                last_name=str(row.get("LAST_NAME", "") or "").strip() or None,
                company=str(row.get("COMPANY", "") or "").strip() or None,
                title=str(row.get("TITLE", "") or "").strip() or None,
                phone=str(row.get("PHONE", "") or "").strip() or None,
                email=str(row.get("EMAIL", "") or "").strip() or None,
                markup_type=_norm_choice(str(row.get("MARKUP_TYPE", "") or ""), _MARKUP_TYPES),
                markup_value=markup_value,
                billing_type=_norm_choice(str(row.get("BILLING_TYPE", "") or ""), _BILLING_TYPES),
            )
            db.add(customer)
            await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"{row_prefix}: {e}")

    return CustomerBulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.get("/template")
async def download_customer_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Customer Template"

    headers = [
        "FIRST_NAME", "LAST_NAME", "COMPANY", "TITLE", "PHONE", "EMAIL",
        "MARKUP_TYPE", "MARKUP_VALUE", "BILLING_TYPE",
    ]
    ws.append(headers)
    # Sample rows showing accepted values for MARKUP_TYPE (percentage|fixed) / BILLING_TYPE (reseller|agency)
    ws.append(["John", "Doe", "Acme Pvt Ltd", "Mr", "9876543210", "john@acme.com", "percentage", "10", "reseller"])
    ws.append(["Jane", "Roe", "Beta Travels", "Ms", "9123456780", "jane@beta.com", "fixed", "500", "agency"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="customer_template.xlsx"'},
    )


@router.get("/{customer_id}", response_model=CustomerRead)
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_owned_customer(customer_id, db, current_user)


@router.patch("/{customer_id}", response_model=CustomerRead)
async def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_owned_customer(customer_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "markup_type" in data:
        data["markup_type"] = _norm_choice(data["markup_type"], _MARKUP_TYPES)
    if "billing_type" in data:
        data["billing_type"] = _norm_choice(data["billing_type"], _BILLING_TYPES)
    for field, value in data.items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_owned_customer(customer_id, db, current_user)
    await db.delete(obj)
    await db.commit()


@router.get("/{customer_id}/sold-tickets", response_model=SoldTicketsResponse)
async def get_customer_sold_tickets(
    customer_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    date_field: str = "ticket",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = await _get_owned_customer(customer_id, db, current_user)

    fn = (customer.first_name or "").strip().lower()
    ln = (customer.last_name or "").strip().lower()

    # Match by passenger first+last name (case-insensitive); also match the
    # combined pax_name (airline statements store the full name in one field).
    conds = []
    if fn and ln:
        conds.append(and_(
            func.lower(UploadedTicket.first_name) == fn,
            func.lower(UploadedTicket.last_name) == ln,
        ))
        conds.append(UploadedTicket.pax_name.ilike(f"%{fn}%{ln}%"))
    elif fn:
        conds.append(func.lower(UploadedTicket.first_name) == fn)
        conds.append(UploadedTicket.pax_name.ilike(f"%{fn}%"))

    if not conds:
        tickets: list[UploadedTicket] = []
    else:
        q = (
            select(UploadedTicket)
            .where(
                UploadedTicket.tenant_id == current_user.tenant_id,
                UploadedTicket.created_by_id == current_user.id,
                or_(*conds),
            )
            .order_by(UploadedTicket.created_at.desc())
        )
        result = await db.execute(q)
        tickets = result.scalars().all()

    # Filter by date range (date fields are strings; parse in Python).
    # date_field selects which date to filter on: 'travel' uses departure/travel date,
    # otherwise the ticket issue date. Tickets with no parseable date are excluded.
    if date_from or date_to:
        use_travel = date_field == "travel"
        in_range: list[UploadedTicket] = []
        for t in tickets:
            d = _safe_date(t.departure_datetime, t.travel_dt) if use_travel else _safe_date(t.ticket_date)
            if d is None:
                continue
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            in_range.append(t)
        tickets = in_range

    rows: list[SoldTicketRead] = []
    total_base = total_markup = total_gst = total_with_markup = 0.0
    for t in tickets:
        base = _f(t.total_amt) if t.total_amt is not None else _f(t.sell_fare)
        markup_amount = _compute_markup(base, customer.markup_type, customer.markup_value)
        gst_amount = _compute_gst(base, markup_amount, customer.billing_type)
        total = base + markup_amount + gst_amount
        total_base += base
        total_markup += markup_amount
        total_gst += gst_amount
        total_with_markup += total
        rows.append(SoldTicketRead(
            id=t.id,
            ticket_number=t.ticket_number,
            airline_name=t.airline_name,
            airlines_code=t.airlines_code,
            first_name=t.first_name,
            last_name=t.last_name,
            pax_name=t.pax_name,
            sector=t.sector,
            booking_class=t.booking_class,
            ticket_date=t.ticket_date,
            ticket_status=t.ticket_status,
            sell_fare=_f(t.sell_fare) if t.sell_fare is not None else None,
            total_amt=_f(t.total_amt) if t.total_amt is not None else None,
            calculated_incentive=_f(t.calculated_incentive) if t.calculated_incentive is not None else None,
            base_amount=round(base, 2),
            markup_amount=round(markup_amount, 2),
            gst_amount=round(gst_amount, 2),
            total_with_markup=round(total, 2),
        ))

    return SoldTicketsResponse(
        customer=CustomerRead.model_validate(customer),
        tickets=rows,
        summary=SoldTicketsSummary(
            count=len(rows),
            total_base=round(total_base, 2),
            total_markup=round(total_markup, 2),
            total_gst=round(total_gst, 2),
            total_with_markup=round(total_with_markup, 2),
        ),
    )


# ── Billing ─────────────────────────────────────────────────────────────────

@router.post("/{customer_id}/billings", response_model=BillingRead, status_code=status.HTTP_201_CREATED)
async def create_billing(
    customer_id: int,
    payload: BillingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = await _get_owned_customer(customer_id, db, current_user)
    if not payload.billing_name.strip():
        raise HTTPException(status_code=400, detail="billing_name is required.")
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one ticket is required to create a billing.")

    ticket_ids = [it.ticket_id for it in payload.items]
    addl_map = {it.ticket_id: _f(it.additional_markup) for it in payload.items}

    res = await db.execute(
        select(UploadedTicket).where(
            UploadedTicket.id.in_(ticket_ids),
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
        )
    )
    tickets = res.scalars().all()
    if not tickets:
        raise HTTPException(status_code=400, detail="No matching tickets found for this billing.")

    line_items: list[dict] = []
    total_base = total_markup = total_addl = total_gst = grand = 0.0
    for t in tickets:
        base = _f(t.total_amt) if t.total_amt is not None else _f(t.sell_fare)
        cust_markup = _compute_markup(base, customer.markup_type, customer.markup_value)
        addl = addl_map.get(t.id, 0.0)
        total_mk = cust_markup + addl
        gst = _compute_gst(base, total_mk, customer.billing_type)
        line_total = base + total_mk + gst
        total_base += base
        total_markup += cust_markup
        total_addl += addl
        total_gst += gst
        grand += line_total
        line_items.append({
            "ticket_id": t.id,
            "ticket_number": t.ticket_number,
            "airline_name": t.airline_name,
            "airlines_code": t.airlines_code,
            "passenger": _passenger_name(t),
            "sector": t.sector,
            "ticket_date": t.ticket_date,
            "base_amount": round(base, 2),
            "markup_amount": round(cust_markup, 2),
            "additional_markup": round(addl, 2),
            "gst_amount": round(gst, 2),
            "total": round(line_total, 2),
        })

    billing = Billing(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        customer_id=customer.id,
        billing_name=payload.billing_name.strip(),
        period_from=payload.period_from,
        period_to=payload.period_to,
        billing_type=customer.billing_type,
        total_base=round(total_base, 2),
        total_markup=round(total_markup, 2),
        total_additional_markup=round(total_addl, 2),
        total_gst=round(total_gst, 2),
        grand_total=round(grand, 2),
        line_items=line_items,
    )
    db.add(billing)
    await db.commit()
    await db.refresh(billing)
    return billing


@router.get("/{customer_id}/billings", response_model=list[BillingListItem])
async def list_billings(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_customer(customer_id, db, current_user)
    res = await db.execute(
        select(Billing)
        .where(
            Billing.customer_id == customer_id,
            Billing.tenant_id == current_user.tenant_id,
            Billing.created_by_id == current_user.id,
        )
        .order_by(Billing.created_at.desc())
    )
    billings = res.scalars().all()
    return [
        BillingListItem(
            id=b.id,
            billing_name=b.billing_name,
            period_from=b.period_from,
            period_to=b.period_to,
            total_base=_f(b.total_base),
            total_markup=_f(b.total_markup),
            total_additional_markup=_f(b.total_additional_markup),
            total_gst=_f(b.total_gst),
            grand_total=_f(b.grand_total),
            item_count=len(b.line_items or []),
            created_at=b.created_at,
        )
        for b in billings
    ]


@router.get("/{customer_id}/billings/{billing_id}", response_model=BillingRead)
async def get_billing(
    customer_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_customer(customer_id, db, current_user)
    return await _get_owned_billing(billing_id, customer_id, db, current_user)


@router.patch("/{customer_id}/billings/{billing_id}", response_model=BillingRead)
async def update_billing(
    customer_id: int,
    billing_id: int,
    payload: BillingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_customer(customer_id, db, current_user)
    billing = await _get_owned_billing(billing_id, customer_id, db, current_user)

    addl_map = {it.ticket_id: _f(it.additional_markup) for it in payload.items}

    new_items: list[dict] = []
    total_base = total_markup = total_addl = total_gst = grand = 0.0
    for it in (billing.line_items or []):
        base = _f(it.get("base_amount"))
        markup = _f(it.get("markup_amount"))
        addl = addl_map.get(it.get("ticket_id"), _f(it.get("additional_markup")))
        gst = _compute_gst(base, markup + addl, billing.billing_type)
        line_total = base + markup + addl + gst
        total_base += base
        total_markup += markup
        total_addl += addl
        total_gst += gst
        grand += line_total
        new_items.append({
            **it,
            "additional_markup": round(addl, 2),
            "gst_amount": round(gst, 2),
            "total": round(line_total, 2),
        })

    billing.line_items = new_items
    billing.total_base = round(total_base, 2)
    billing.total_markup = round(total_markup, 2)
    billing.total_additional_markup = round(total_addl, 2)
    billing.total_gst = round(total_gst, 2)
    billing.grand_total = round(grand, 2)
    await db.commit()
    await db.refresh(billing)
    return billing


@router.delete("/{customer_id}/billings/{billing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_billing(
    customer_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_customer(customer_id, db, current_user)
    billing = await _get_owned_billing(billing_id, customer_id, db, current_user)
    await db.delete(billing)
    await db.commit()


@router.get("/{customer_id}/billings/{billing_id}/pdf")
async def download_billing_pdf(
    customer_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = await _get_owned_customer(customer_id, db, current_user)
    billing = await _get_owned_billing(billing_id, customer_id, db, current_user)

    tenant = None
    if current_user.tenant_id:
        tres = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
        tenant = tres.scalar_one_or_none()
    agency = {
        "name": (tenant.name if tenant and tenant.name else (tenant.domain if tenant else "")) or current_user.full_name,
        "domain": tenant.domain if tenant else "",
        "email": current_user.email,
    }
    buf = build_billing_pdf(billing, customer, agency)
    safe = "".join(c for c in (billing.billing_name or "") if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_") or "billing"
    filename = f"billing-{billing.id}-{safe}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
