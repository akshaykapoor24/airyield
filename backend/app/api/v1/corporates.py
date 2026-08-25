"""Corporate Billing — a private directory of corporate clients + their billing.

Mirrors `customers.py`: onboard corporates (CRUD + XLS bulk upload), list their
sold tickets (matched by passenger name) over a date range with markup/GST, and
bill them. Billings are stored in the shared `billings` table with `corporate_id`
set. All rows are scoped per user (tenant_id + created_by_id).
"""
import re
from datetime import date
from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, func, or_, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.corporate import Corporate
from app.models.customer import Customer
from app.models.billing import Billing
from app.models.deal import Deal
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User
from app.models.tenant import Tenant
from app.schemas.corporate import (
    CorporateCreate, CorporateUpdate, CorporateRead, CorporateBulkUploadResult,
    CorporateBulkCreate, CorporateSoldTicketsResponse,
)
from app.schemas.customer import SoldTicketRead, SoldTicketsSummary
from app.schemas.billing import BillingCreate, BillingUpdate, BillingRead, BillingListItem
from app.services.billing_pdf import build_billing_pdf
from app.services.billing_calc import (
    to_float as _f,
    compute_markup as _compute_markup,
    compute_gst as _compute_gst,
    safe_date as _safe_date,
    passenger_name as _passenger_name,
)

router = APIRouter()

_MARKUP_TYPES = {"percentage", "fixed"}
_BILLING_TYPES = {"reseller", "agency"}
_TRUTHY = {"registered", "yes", "true", "y", "1"}

# Ceiling for one bulk-create request. The wizard commits per row, so a runaway
# paste is a long transaction loop rather than a rejected payload without it.
_MAX_BULK_ROWS = 2000

# Legal form of the corporate entity. Stored as these slugs; the labels the user
# picks from live in frontend/src/lib/party.ts (CORPORATE_TYPES) — keep the two in step.
_CORPORATE_TYPES = {
    "proprietorship", "partnership", "llp", "private_limited", "public_limited",
    "opc", "huf", "trust", "society", "government", "other",
}

# Excel is typed by hand, so the bulk upload accepts the way people actually write
# these ("Pvt Ltd", "Partnership Firm") — and the full dropdown labels too, since
# the obvious way to fill the column is to copy one out of the form.
_CORPORATE_TYPE_ALIASES = {
    "sole_proprietorship": "proprietorship", "proprietary_firm": "proprietorship",
    "proprietor": "proprietorship", "proprietary": "proprietorship",
    "proprietorship_proprietary_firm": "proprietorship",
    "partnership_firm": "partnership",
    "limited_liability_partnership": "llp",
    "llp_limited_liability_partnership": "llp",
    "pvt_ltd": "private_limited", "private_ltd": "private_limited",
    "private_limited_company": "private_limited",
    "public_ltd": "public_limited", "public_limited_company": "public_limited",
    "one_person_company": "opc", "one_person_company_opc": "opc",
    "hindu_undivided_family": "huf", "huf_hindu_undivided_family": "huf",
    "ngo": "society", "society_ngo": "society",
    "psu": "government", "government_psu": "government", "govt": "government",
}


def _norm_corporate_type(value) -> Optional[str]:
    """'Pvt. Ltd' / 'Society / NGO' / 'private_limited' → the stored slug, else None."""
    if not value:
        return None
    v = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    v = _CORPORATE_TYPE_ALIASES.get(v, v)
    return v if v in _CORPORATE_TYPES else None


def _cell(row, column: str) -> Optional[str]:
    """One trimmed string out of an uploaded row, or None.

    `pd.read_excel(dtype=str)` gives a BLANK cell as NaN, not "" — and NaN is
    truthy, so the obvious `str(row.get(c, "") or "")` stores the literal "nan".
    Most of these columns are optional and usually empty, so that has to be
    caught here rather than at every call site.
    """
    value = row.get(column)
    if value is None or value != value:      # NaN != NaN
        return None
    v = str(value).strip()
    return v or None


def _clean_upper(value) -> Optional[str]:
    """Strip + uppercase a possibly-None identifier (GST/PAN), returning None if empty."""
    if value is None:
        return None
    v = str(value).strip().upper()
    return v or None


def _scope(current_user: User):
    """Ownership filter: corporate must belong to the current user + tenant."""
    return and_(
        Corporate.tenant_id == current_user.tenant_id,
        Corporate.created_by_id == current_user.id,
    )


def _norm_choice(value: Optional[str], allowed: set[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    return v if v in allowed else None


async def _get_owned_corporate(corporate_id: int, db: AsyncSession, current_user: User) -> Corporate:
    result = await db.execute(
        select(Corporate).where(Corporate.id == corporate_id, _scope(current_user))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Corporate not found")
    return obj


async def _get_owned_billing(billing_id: int, corporate_id: int, db: AsyncSession, current_user: User) -> Billing:
    result = await db.execute(
        select(Billing).where(
            Billing.id == billing_id,
            Billing.corporate_id == corporate_id,
            Billing.tenant_id == current_user.tenant_id,
            Billing.created_by_id == current_user.id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Billing not found")
    return obj


@router.get("/", response_model=list[CorporateRead])
async def list_corporates(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Corporate).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Corporate.company.ilike(term),
            Corporate.email.ilike(term),
            Corporate.city.ilike(term),
            # Pre-split rows may still carry the contact's name and no company.
            Corporate.first_name.ilike(term),
            Corporate.last_name.ilike(term),
        ))
    q = q.order_by(Corporate.company, Corporate.first_name).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=CorporateRead, status_code=status.HTTP_201_CREATED)
async def create_corporate(
    payload: CorporateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company = (payload.company or "").strip()
    if not company:
        raise HTTPException(status_code=400, detail="Corporate name is required.")
    gst_registered = bool(payload.gst_registered)
    corporate = Corporate(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        company=company,
        corporate_type=_norm_corporate_type(payload.corporate_type),
        phone=(payload.phone or "").strip() or None,
        email=(payload.email or "").strip() or None,
        address=(payload.address or "").strip() or None,
        city=(payload.city or "").strip() or None,
        state=(payload.state or "").strip() or None,
        pincode=(payload.pincode or "").strip() or None,
        country=(payload.country or "").strip() or None,
        gst_registered=gst_registered,
        gst_no=_clean_upper(payload.gst_no) if gst_registered else None,
        pan_no=_clean_upper(payload.pan_no),
        markup_type=_norm_choice(payload.markup_type, _MARKUP_TYPES),
        markup_value=payload.markup_value,
        billing_type=_norm_choice(payload.billing_type, _BILLING_TYPES),
    )
    db.add(corporate)
    await db.commit()
    await db.refresh(corporate)
    return corporate


@router.post("/bulk-upload", response_model=CorporateBulkUploadResult)
async def bulk_upload_corporates(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"COMPANY"}

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
                "Missing required column: COMPANY. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: COMPANY"
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
        company = _cell(row, "COMPANY")
        if not company:
            errors.append(f"{row_prefix}: COMPANY is required.")
            continue

        markup_value_raw = _cell(row, "MARKUP_VALUE")
        markup_value: float | None = None
        if markup_value_raw:
            try:
                markup_value = float(markup_value_raw)
            except ValueError:
                errors.append(f"{row_prefix}: MARKUP_VALUE '{markup_value_raw}' is not a number.")
                continue

        gst_registered = (_cell(row, "GST_REGISTERED") or "").lower() in _TRUTHY

        try:
            corporate = Corporate(
                tenant_id=current_user.tenant_id,
                created_by_id=current_user.id,
                company=company,
                corporate_type=_norm_corporate_type(_cell(row, "CORPORATE_TYPE")),
                phone=_cell(row, "PHONE"),
                email=_cell(row, "EMAIL"),
                address=_cell(row, "ADDRESS"),
                city=_cell(row, "CITY"),
                state=_cell(row, "STATE"),
                pincode=_cell(row, "PINCODE"),
                country=_cell(row, "COUNTRY"),
                gst_registered=gst_registered,
                gst_no=_clean_upper(_cell(row, "GST_NO")) if gst_registered else None,
                pan_no=_clean_upper(_cell(row, "PAN_NO")),
                markup_type=_norm_choice(_cell(row, "MARKUP_TYPE"), _MARKUP_TYPES),
                markup_value=markup_value,
                billing_type=_norm_choice(_cell(row, "BILLING_TYPE"), _BILLING_TYPES),
            )
            db.add(corporate)
            await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"{row_prefix}: {e}")

    return CorporateBulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


# Rows already mapped and reviewed in the browser wizard. Declared BEFORE
# /{corporate_id} so the path is not swallowed by it.
@router.post("/bulk-create", response_model=CorporateBulkUploadResult)
async def bulk_create_corporates(
    payload: CorporateBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save the reviewed output of the import wizard.

    The wizard has already mapped columns and shown the user every row, so this
    is not a parser — but it IS the validation boundary, and it re-checks and
    re-normalises each row exactly as the .xls path does. Partial success is the
    point: one rejected row reports itself and the rest still save.
    """
    if not payload.rows:
        raise HTTPException(status_code=400, detail="No rows to save.")
    if len(payload.rows) > _MAX_BULK_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many rows in one import ({len(payload.rows)}). Split the file into batches of {_MAX_BULK_ROWS}.",
        )

    total = len(payload.rows)
    success = 0
    errors: list[str] = []

    for i, row in enumerate(payload.rows):
        # The wizard labels rows by their line in the sheet, but it only sends the
        # ones it kept, so the two numberings cannot be reconciled here. Count
        # what was actually sent and say so.
        row_prefix = f"Row {i + 1}"
        company = (row.company or "").strip()
        if not company:
            errors.append(f"{row_prefix}: Corporate name is required.")
            continue

        gst_registered = bool(row.gst_registered)
        try:
            db.add(Corporate(
                tenant_id=current_user.tenant_id,
                created_by_id=current_user.id,
                company=company,
                corporate_type=_norm_corporate_type(row.corporate_type),
                phone=(row.phone or "").strip() or None,
                email=(row.email or "").strip() or None,
                address=(row.address or "").strip() or None,
                city=(row.city or "").strip() or None,
                state=(row.state or "").strip() or None,
                pincode=(row.pincode or "").strip() or None,
                country=(row.country or "").strip() or None,
                gst_registered=gst_registered,
                gst_no=_clean_upper(row.gst_no) if gst_registered else None,
                pan_no=_clean_upper(row.pan_no),
                markup_type=_norm_choice(row.markup_type, _MARKUP_TYPES),
                markup_value=row.markup_value,
                billing_type=_norm_choice(row.billing_type, _BILLING_TYPES),
            ))
            await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"{row_prefix}: {e}")

    return CorporateBulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.get("/template")
async def download_corporate_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Corporate Template"

    headers = [
        "COMPANY", "CORPORATE_TYPE", "PHONE", "EMAIL",
        "ADDRESS", "CITY", "STATE", "PINCODE", "COUNTRY",
        "GST_REGISTERED", "GST_NO", "PAN_NO",
        "MARKUP_TYPE", "MARKUP_VALUE", "BILLING_TYPE",
    ]
    ws.append(headers)
    ws.append(["Acme Pvt Ltd", "Private Limited", "9876543210", "accounts@acme.com",
               "12 MG Road, Andheri East", "Mumbai", "Maharashtra", "400069", "India",
               "Registered", "27ABCDE1234F1Z5", "ABCDE1234F", "percentage", "10", "reseller"])
    ws.append(["Beta Traders", "Proprietorship", "9123456780", "info@betatraders.in",
               "Shop 4, Sector 18", "Noida", "Uttar Pradesh", "201301", "India",
               "Unregistered", "", "", "fixed", "500", "agency"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="corporate_template.xlsx"'},
    )


@router.get("/{corporate_id}", response_model=CorporateRead)
async def get_corporate(
    corporate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_owned_corporate(corporate_id, db, current_user)


@router.patch("/{corporate_id}", response_model=CorporateRead)
async def update_corporate(
    corporate_id: int,
    payload: CorporateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_owned_corporate(corporate_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "company" in data:
        company = (data["company"] or "").strip()
        if not company:
            raise HTTPException(status_code=400, detail="Corporate name is required.")
        data["company"] = company
    if "corporate_type" in data:
        data["corporate_type"] = _norm_corporate_type(data["corporate_type"])
    if "markup_type" in data:
        data["markup_type"] = _norm_choice(data["markup_type"], _MARKUP_TYPES)
    if "billing_type" in data:
        data["billing_type"] = _norm_choice(data["billing_type"], _BILLING_TYPES)
    if "gst_no" in data:
        data["gst_no"] = _clean_upper(data["gst_no"])
    if "pan_no" in data:
        data["pan_no"] = _clean_upper(data["pan_no"])
    registered = data.get("gst_registered", obj.gst_registered)
    if not registered:
        data["gst_no"] = None
    renamed_to = data["company"] if data.get("company") and data["company"] != obj.company else None
    for field, value in data.items():
        setattr(obj, field, value)
    # customers.company mirrors this name (models/customer.py), so a rename has
    # to reach the employees or every one of them keeps advertising the old one.
    if renamed_to:
        await db.execute(
            update(Customer)
            .where(
                Customer.corporate_id == obj.id,
                Customer.tenant_id == current_user.tenant_id,
                Customer.created_by_id == current_user.id,
            )
            .values(company=renamed_to)
        )
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{corporate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_corporate(
    corporate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_owned_corporate(corporate_id, db, current_user)

    # deals.corporate_id is ON DELETE RESTRICT (nulling it would break the deal's
    # own scope CHECK), so refuse here with something readable rather than letting
    # the driver raise an FK error.
    deals_named = (await db.execute(
        select(func.count()).select_from(Deal).where(Deal.corporate_id == corporate_id)
    )).scalar() or 0
    if deals_named:
        raise HTTPException(
            status_code=409,
            detail=f"This corporate is named on {deals_named} outgoing deal(s) and cannot be deleted. "
                   "Close or re-scope those deals first, or mark the corporate inactive.",
        )

    # customers.corporate_id is ON DELETE SET NULL — its people survive as
    # individuals. `company` mirrors the name, so it has to go with the link;
    # left behind it would read as a free-text employer that no longer exists.
    await db.execute(
        update(Customer)
        .where(
            Customer.corporate_id == obj.id,
            Customer.tenant_id == current_user.tenant_id,
            Customer.created_by_id == current_user.id,
        )
        .values(company=None)
    )

    await db.delete(obj)
    await db.commit()


@router.get("/{corporate_id}/sold-tickets", response_model=CorporateSoldTicketsResponse)
async def get_corporate_sold_tickets(
    corporate_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    date_field: str = "ticket",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    corporate = await _get_owned_corporate(corporate_id, db, current_user)

    # WHOSE TICKETS COUNT AS THIS CORPORATE'S. An organisation is not a passenger,
    # so the names to match are its EMPLOYEES' — every customer in Employee Master
    # linked to it (customers.corporate_id).
    emp_res = await db.execute(
        select(Customer.first_name, Customer.last_name).where(
            Customer.corporate_id == corporate.id,
            Customer.tenant_id == current_user.tenant_id,
            Customer.created_by_id == current_user.id,
        )
    )
    names = [(f, l) for f, l in emp_res.all()]
    # Plus the corporate's own contact name, for rows that predate corp_entity_01
    # and were billed by it before the employee link existed.
    if corporate.first_name:
        names.append((corporate.first_name, corporate.last_name))

    # Match by passenger first+last name (case-insensitive); also match the
    # combined pax_name (airline statements store the full name in one field).
    conds = []
    for raw_fn, raw_ln in names:
        fn = (raw_fn or "").strip().lower()
        ln = (raw_ln or "").strip().lower()
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
        markup_amount = _compute_markup(base, corporate.markup_type, corporate.markup_value)
        gst_amount = _compute_gst(base, markup_amount, corporate.billing_type)
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
            incentive_breakdown=t.incentive_breakdown,
            is_billed=bool(t.is_billed),
            billing_id=t.billing_id,
            base_amount=round(base, 2),
            markup_amount=round(markup_amount, 2),
            gst_amount=round(gst_amount, 2),
            total_with_markup=round(total, 2),
        ))

    return CorporateSoldTicketsResponse(
        corporate=CorporateRead.model_validate(corporate),
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

@router.post("/{corporate_id}/billings", response_model=BillingRead, status_code=status.HTTP_201_CREATED)
async def create_billing(
    corporate_id: int,
    payload: BillingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    corporate = await _get_owned_corporate(corporate_id, db, current_user)
    if not payload.billing_name.strip():
        raise HTTPException(status_code=400, detail="billing_name is required.")
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one ticket is required to create a billing.")

    ticket_ids = [it.ticket_id for it in payload.items]
    addl_map = {it.ticket_id: _f(it.additional_markup) for it in payload.items}
    disc_map = {it.ticket_id: _f(it.discount) for it in payload.items}

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

    already = [t.ticket_number or str(t.id) for t in tickets if t.is_billed]
    if already:
        raise HTTPException(status_code=400, detail=f"Already billed: {', '.join(already)}. Refresh and try again.")

    line_items: list[dict] = []
    total_base = total_markup = total_addl = total_gst = grand = 0.0
    for t in tickets:
        base = _f(t.total_amt) if t.total_amt is not None else _f(t.sell_fare)
        corp_markup = _compute_markup(base, corporate.markup_type, corporate.markup_value)
        addl = addl_map.get(t.id, 0.0)
        disc = disc_map.get(t.id, 0.0)
        total_mk = corp_markup + addl
        gst = _compute_gst(base, total_mk, corporate.billing_type, disc)
        line_total = base + total_mk - disc + gst
        total_base += base
        total_markup += corp_markup
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
            "markup_amount": round(corp_markup, 2),
            "additional_markup": round(addl, 2),
            "discount": round(disc, 2),
            "gst_amount": round(gst, 2),
            "total": round(line_total, 2),
        })

    billing = Billing(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        corporate_id=corporate.id,
        billing_name=payload.billing_name.strip(),
        period_from=payload.period_from,
        period_to=payload.period_to,
        billing_type=corporate.billing_type,
        total_base=round(total_base, 2),
        total_markup=round(total_markup, 2),
        total_additional_markup=round(total_addl, 2),
        total_gst=round(total_gst, 2),
        grand_total=round(grand, 2),
        line_items=line_items,
    )
    db.add(billing)
    await db.flush()  # assign billing.id before linking tickets
    for t in tickets:
        t.is_billed = True
        t.billing_id = billing.id
    await db.commit()
    await db.refresh(billing)
    return billing


@router.get("/{corporate_id}/billings", response_model=list[BillingListItem])
async def list_billings(
    corporate_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_corporate(corporate_id, db, current_user)
    res = await db.execute(
        select(Billing)
        .where(
            Billing.corporate_id == corporate_id,
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


@router.get("/{corporate_id}/billings/{billing_id}", response_model=BillingRead)
async def get_billing(
    corporate_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_corporate(corporate_id, db, current_user)
    return await _get_owned_billing(billing_id, corporate_id, db, current_user)


@router.patch("/{corporate_id}/billings/{billing_id}", response_model=BillingRead)
async def update_billing(
    corporate_id: int,
    billing_id: int,
    payload: BillingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_corporate(corporate_id, db, current_user)
    billing = await _get_owned_billing(billing_id, corporate_id, db, current_user)

    addl_map = {it.ticket_id: _f(it.additional_markup) for it in payload.items}

    new_items: list[dict] = []
    total_base = total_markup = total_addl = total_gst = grand = 0.0
    for it in (billing.line_items or []):
        base = _f(it.get("base_amount"))
        markup = _f(it.get("markup_amount"))
        addl = addl_map.get(it.get("ticket_id"), _f(it.get("additional_markup")))
        disc = _f(it.get("discount"))   # preserved from creation (not edited in the popup)
        gst = _compute_gst(base, markup + addl, billing.billing_type, disc)
        line_total = base + markup + addl - disc + gst
        total_base += base
        total_markup += markup
        total_addl += addl
        total_gst += gst
        grand += line_total
        new_items.append({
            **it,
            "additional_markup": round(addl, 2),
            "discount": round(disc, 2),
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


@router.delete("/{corporate_id}/billings/{billing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_billing(
    corporate_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned_corporate(corporate_id, db, current_user)
    billing = await _get_owned_billing(billing_id, corporate_id, db, current_user)
    # Free the tickets locked to this billing so they can be billed again.
    await db.execute(
        update(UploadedTicket)
        .where(UploadedTicket.billing_id == billing.id)
        .values(is_billed=False, billing_id=None)
    )
    await db.delete(billing)
    await db.commit()


@router.get("/{corporate_id}/billings/{billing_id}/pdf")
async def download_billing_pdf(
    corporate_id: int,
    billing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    corporate = await _get_owned_corporate(corporate_id, db, current_user)
    billing = await _get_owned_billing(billing_id, corporate_id, db, current_user)

    tenant = None
    if current_user.tenant_id:
        tres = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
        tenant = tres.scalar_one_or_none()
    agency = {
        "name": (tenant.name if tenant and tenant.name else (tenant.domain if tenant else "")) or current_user.full_name,
        "domain": tenant.domain if tenant else "",
        "email": current_user.email,
    }
    # Corporate shares the customer field shape (company/first_name/.../gst_no/pan_no),
    # so it can be passed straight through as the BILL TO party.
    buf = build_billing_pdf(billing, corporate, agency)
    safe = "".join(c for c in (billing.billing_name or "") if c.isalnum() or c in (" ", "-", "_")).strip().replace(" ", "_") or "billing"
    filename = f"corporate-billing-{billing.id}-{safe}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
