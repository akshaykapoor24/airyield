from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agency import Agency
from app.models.agency_entity import AgencyEntity
from app.models.agency_login_id import AgencyLoginId
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.agency import (
    AgencyCreate, AgencyUpdate, AgencyRead, AgencyOverviewRow,
    AgencyFromSuppliers, AgencyFromSuppliersResult, BulkUploadResult,
)

router = APIRouter()


def _cell(v) -> str:
    """Read a spreadsheet cell as a clean string. pandas reads empty cells as
    NaN (a truthy float), so guard against it instead of `str(v or "")`."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def _scope(current_user: User):
    """User scope — agencies are private to their owner."""
    return Agency.user_id == current_user.id


async def _get_scoped_agency(agency_id: int, db: AsyncSession, current_user: User) -> Agency:
    result = await db.execute(select(Agency).where(Agency.id == agency_id, _scope(current_user)))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Agency not found")
    return obj


async def _name_exists(db: AsyncSession, current_user: User, name: str, exclude_id: int | None = None) -> bool:
    q = select(Agency.id).where(_scope(current_user), func.lower(Agency.name) == name.lower())
    if exclude_id is not None:
        q = q.where(Agency.id != exclude_id)
    return (await db.execute(q)).scalar_one_or_none() is not None


def _from_supplier(supplier: Supplier, current_user: User) -> Agency:
    """Build a new Agency by copying details from a supplier (add-time snapshot)."""
    return Agency(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        name=(supplier.name or "").strip(),
        vendor_type=supplier.vendor_type,
        gst_number=supplier.gst_number,
        pan_number=supplier.pan_number,
        contact_phone=supplier.contact_phone,
        contact_email=supplier.contact_email,
        notes=supplier.notes,
        is_active=True,
    )


@router.get("/", response_model=list[AgencyRead])
async def list_agencies(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Agency).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Agency.name.ilike(term),
            Agency.vendor_type.ilike(term),
            Agency.gst_number.ilike(term),
            Agency.pan_number.ilike(term),
        ))
    q = q.order_by(Agency.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/overview", response_model=list[AgencyOverviewRow])
async def agencies_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per agency with its entity count and login-id count (drill-down source)."""
    ent_sub = (
        select(AgencyEntity.agency_id, func.count().label("c"))
        .where(AgencyEntity.user_id == current_user.id)
        .group_by(AgencyEntity.agency_id)
        .subquery()
    )
    lid_sub = (
        select(AgencyLoginId.agency_id, func.count().label("c"))
        .where(AgencyLoginId.user_id == current_user.id)
        .group_by(AgencyLoginId.agency_id)
        .subquery()
    )
    q = (
        select(
            Agency.id,
            Agency.name,
            func.coalesce(ent_sub.c.c, 0),
            func.coalesce(lid_sub.c.c, 0),
        )
        .outerjoin(ent_sub, ent_sub.c.agency_id == Agency.id)
        .outerjoin(lid_sub, lid_sub.c.agency_id == Agency.id)
        .where(_scope(current_user))
        .order_by(Agency.name)
    )
    rows = (await db.execute(q)).all()
    return [
        AgencyOverviewRow(id=r[0], name=r[1], entity_count=r[2], login_id_count=r[3])
        for r in rows
    ]


@router.post("/", response_model=AgencyRead, status_code=status.HTTP_201_CREATED)
async def create_agency(
    payload: AgencyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")
    if await _name_exists(db, current_user, name):
        raise HTTPException(status_code=400, detail=f"An agency named '{name}' already exists.")

    agency = Agency(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        name=name,
        vendor_type=(payload.vendor_type or "").strip() or None,
        gst_number=(payload.gst_number or "").strip() or None,
        pan_number=(payload.pan_number or "").strip() or None,
        contact_phone=(payload.contact_phone or "").strip() or None,
        contact_email=(payload.contact_email or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(agency)
    await db.commit()
    await db.refresh(agency)
    return agency


@router.post("/from-suppliers", response_model=AgencyFromSuppliersResult)
async def create_agencies_from_suppliers(
    payload: AgencyFromSuppliers,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Copy details from the chosen suppliers into new agencies. Suppliers whose
    name already exists among the user's agencies are skipped (idempotent)."""
    ids = list(dict.fromkeys(payload.supplier_ids or []))  # de-dup, keep order
    if not ids:
        raise HTTPException(status_code=400, detail="supplier_ids is required.")

    suppliers = (await db.execute(select(Supplier).where(Supplier.id.in_(ids)))).scalars().all()
    by_id = {s.id: s for s in suppliers}

    # existing agency names for this user (lower-cased) to skip duplicates
    existing = {
        n.lower()
        for (n,) in (await db.execute(select(Agency.name).where(_scope(current_user)))).all()
    }

    created: list[Agency] = []
    skipped = 0
    for sid in ids:
        s = by_id.get(sid)
        if s is None:
            skipped += 1
            continue
        name = (s.name or "").strip()
        if not name or name.lower() in existing:
            skipped += 1
            continue
        agency = _from_supplier(s, current_user)
        db.add(agency)
        created.append(agency)
        existing.add(name.lower())

    if created:
        await db.commit()
        for a in created:
            await db.refresh(a)

    return AgencyFromSuppliersResult(
        created=len(created),
        skipped=skipped,
        agencies=[AgencyRead.model_validate(a) for a in created],
    )


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_agencies(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"NAME"}

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
                "Missing required column: NAME. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: NAME"
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
        name = _cell(row.get("NAME"))
        if not name:
            errors.append(f"Row {row_num}: NAME is required.")
            continue
        if await _name_exists(db, current_user, name):
            errors.append(f"Row {row_num}: agency '{name}' already exists — skipped.")
            continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(Agency(
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                name=name,
                vendor_type=_cell(row.get("VENDOR_TYPE")) or None,
                gst_number=_cell(row.get("GST")) or None,
                pan_number=_cell(row.get("PAN")) or None,
                contact_phone=_cell(row.get("PHONE")) or None,
                contact_email=_cell(row.get("EMAIL")) or None,
                notes=_cell(row.get("NOTES")) or None,
                is_active=is_active,
            ))
            await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e}")

    return BulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.get("/template")
async def download_agency_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Agency Template"
    ws.append(["NAME", "VENDOR_TYPE", "GST", "PAN", "PHONE", "EMAIL", "NOTES", "ACTIVE"])
    ws.append(["Lords Travels", "Agent", "27ABCDE1234F1Z5", "ABCDE1234F", "9876543210", "ops@lords.com", "", "yes"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="agency_template.xlsx"'},
    )


@router.get("/{agency_id}", response_model=AgencyRead)
async def get_agency(
    agency_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_scoped_agency(agency_id, db, current_user)


@router.patch("/{agency_id}", response_model=AgencyRead)
async def update_agency(
    agency_id: int,
    payload: AgencyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_scoped_agency(agency_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="name cannot be empty.")
        if await _name_exists(db, current_user, new_name, exclude_id=obj.id):
            raise HTTPException(status_code=400, detail=f"An agency named '{new_name}' already exists.")
        data["name"] = new_name
    for field, value in data.items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{agency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agency(
    agency_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_scoped_agency(agency_id, db, current_user)
    await db.delete(obj)
    await db.commit()
