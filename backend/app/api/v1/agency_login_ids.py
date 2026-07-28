from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agency_login_id import AgencyLoginId
from app.models.agency_entity import AgencyEntity
from app.models.agency import Agency
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.agency_login_id import (
    AgencyLoginIdCreate, AgencyLoginIdUpdate, AgencyLoginIdRead, BulkUploadResult,
)

router = APIRouter()


def _cell(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def _scope(current_user: User):
    """User scope — login ids are private to their owner."""
    return AgencyLoginId.user_id == current_user.id


async def _load(login_id_pk: int, db: AsyncSession, current_user: User) -> AgencyLoginId:
    """Fetch a user-scoped AgencyLoginId with vendor + entity + agency eager-loaded."""
    result = await db.execute(
        select(AgencyLoginId)
        .options(
            selectinload(AgencyLoginId.vendor),
            selectinload(AgencyLoginId.entity),
            selectinload(AgencyLoginId.agency),
        )
        .where(AgencyLoginId.id == login_id_pk, _scope(current_user))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Login ID not found")
    return obj


async def _validate_vendor(db: AsyncSession, vendor_id: int | None) -> int | None:
    if vendor_id is None:
        return None
    exists = (await db.execute(select(Supplier.id).where(Supplier.id == vendor_id))).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=400, detail=f"Vendor (supplier) id {vendor_id} not found.")
    return vendor_id


async def _validate_agency(db: AsyncSession, current_user: User, agency_id: int | None) -> int:
    """Ensure agency_id is one of the caller's OWN agencies."""
    if agency_id is None:
        raise HTTPException(status_code=400, detail="agency_id is required.")
    exists = (await db.execute(
        select(Agency.id).where(Agency.id == agency_id, Agency.user_id == current_user.id)
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=400, detail=f"Agency id {agency_id} not found in your agencies.")
    return agency_id


async def _validate_entity(db: AsyncSession, current_user: User, agency_id: int, entity_id: int | None) -> int | None:
    """Ensure entity_id (if given) belongs to the caller AND to the chosen agency."""
    if entity_id is None:
        return None
    exists = (await db.execute(
        select(AgencyEntity.id).where(
            AgencyEntity.id == entity_id,
            AgencyEntity.user_id == current_user.id,
            AgencyEntity.agency_id == agency_id,
        )
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=400, detail=f"Entity id {entity_id} not found under the chosen agency.")
    return entity_id


@router.get("/", response_model=list[AgencyLoginIdRead])
async def list_login_ids(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    agency_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(AgencyLoginId).options(
        selectinload(AgencyLoginId.vendor),
        selectinload(AgencyLoginId.entity),
        selectinload(AgencyLoginId.agency),
    ).where(_scope(current_user))
    if agency_id is not None:
        q = q.where(AgencyLoginId.agency_id == agency_id)
    if entity_id is not None:
        q = q.where(AgencyLoginId.entity_id == entity_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            AgencyLoginId.login_id.ilike(term),
            AgencyLoginId.airline_name.ilike(term),
            AgencyLoginId.airline_code.ilike(term),
            AgencyLoginId.lob.ilike(term),
        ))
    q = q.order_by(AgencyLoginId.login_id).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=AgencyLoginIdRead, status_code=status.HTTP_201_CREATED)
async def create_login_id(
    payload: AgencyLoginIdCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    login_val = (payload.login_id or "").strip()
    if not login_val:
        raise HTTPException(status_code=400, detail="login_id is required.")
    agency_id = await _validate_agency(db, current_user, payload.agency_id)
    vendor_id = await _validate_vendor(db, payload.vendor_id)
    entity_id = await _validate_entity(db, current_user, agency_id, payload.entity_id)

    obj = AgencyLoginId(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        agency_id=agency_id,
        login_id=login_val,
        airline_name=(payload.airline_name or "").strip() or None,
        airline_code=(payload.airline_code or "").strip() or None,
        lob=(payload.lob or "").strip() or None,
        vendor_id=vendor_id,
        entity_id=entity_id,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(obj)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_login_ids(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"LOGIN_ID", "AGENCY"}

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
                "Missing required columns: LOGIN_ID, AGENCY. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: LOGIN_ID, AGENCY"
            )
            raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}. Ensure it is a valid .xlsx or .xls file.")

    # Pre-load suppliers for vendor lookup (global master; match on name/code/vendor_name)
    suppliers = (await db.execute(select(Supplier))).scalars().all()
    vendor_lookup: dict[str, int] = {}
    for s in suppliers:
        for key in (s.name, s.code, s.vendor_name):
            if key:
                vendor_lookup.setdefault(str(key).strip().lower(), s.id)

    # Pre-load this user's agencies (by name) and entities (by code/name within agency)
    agencies = (await db.execute(select(Agency).where(Agency.user_id == current_user.id))).scalars().all()
    agency_lookup = {str(a.name).strip().lower(): a.id for a in agencies if a.name}

    entities = (await db.execute(
        select(AgencyEntity).where(AgencyEntity.user_id == current_user.id)
    )).scalars().all()
    # keyed by (agency_id, code|name) so an entity code resolves within its agency
    entity_lookup: dict[tuple[int, str], int] = {}
    for e in entities:
        for key in (e.code, e.name):
            if key:
                entity_lookup.setdefault((e.agency_id, str(key).strip().lower()), e.id)

    total = len(df)
    success = 0
    errors: list[str] = []

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        login_val = _cell(row.get("LOGIN_ID"))
        agency_raw = _cell(row.get("AGENCY"))
        if not login_val or not agency_raw:
            errors.append(f"Row {row_num}: LOGIN_ID and AGENCY are required.")
            continue
        agency_id = agency_lookup.get(agency_raw.lower())
        if agency_id is None:
            errors.append(f"Row {row_num}: agency '{agency_raw}' not found in your agencies — skipped.")
            continue

        vendor_id: int | None = None
        vendor_raw = _cell(row.get("VENDOR"))
        if vendor_raw:
            vendor_id = vendor_lookup.get(vendor_raw.lower())
            if vendor_id is None:
                errors.append(f"Row {row_num}: vendor '{vendor_raw}' not found in Suppliers master — skipped.")
                continue

        entity_id: int | None = None
        entity_raw = _cell(row.get("ENTITY_CODE"))
        if entity_raw:
            entity_id = entity_lookup.get((agency_id, entity_raw.lower()))
            if entity_id is None:
                errors.append(f"Row {row_num}: entity '{entity_raw}' not found under agency '{agency_raw}' — skipped.")
                continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(AgencyLoginId(
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                agency_id=agency_id,
                login_id=login_val,
                airline_name=_cell(row.get("AIRLINE_NAME")) or None,
                airline_code=_cell(row.get("AIRLINE_CODE")) or None,
                lob=_cell(row.get("LOB")) or None,
                vendor_id=vendor_id,
                entity_id=entity_id,
                is_active=is_active,
            ))
            await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e}")

    return BulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.get("/template")
async def download_login_id_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Agency Login ID Template"
    ws.append(["LOGIN_ID", "AGENCY", "ENTITY_CODE", "AIRLINE_NAME", "AIRLINE_CODE", "LOB", "VENDOR", "ACTIVE"])
    ws.append(["AI-DEL-001", "Lords Travels", "DEL-001", "Air India", "AI", "B2B", "Acme Travels", "yes"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="agency_login_id_template.xlsx"'},
    )


@router.get("/{login_id_pk}", response_model=AgencyLoginIdRead)
async def get_login_id(
    login_id_pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load(login_id_pk, db, current_user)


@router.patch("/{login_id_pk}", response_model=AgencyLoginIdRead)
async def update_login_id(
    login_id_pk: int,
    payload: AgencyLoginIdUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(login_id_pk, db, current_user)
    data = payload.model_dump(exclude_unset=True)

    # resolve the target agency (may be changing) so entity ownership is checked against it
    target_agency = obj.agency_id
    if "agency_id" in data:
        target_agency = await _validate_agency(db, current_user, data["agency_id"])
        data["agency_id"] = target_agency

    if "vendor_id" in data:
        data["vendor_id"] = await _validate_vendor(db, data["vendor_id"])

    # if the agency changed but entity wasn't re-specified, re-check the existing entity still fits
    if "entity_id" in data:
        data["entity_id"] = await _validate_entity(db, current_user, target_agency, data["entity_id"])
    elif "agency_id" in data and obj.entity_id is not None:
        await _validate_entity(db, current_user, target_agency, obj.entity_id)

    if "login_id" in data:
        new_login = (data["login_id"] or "").strip()
        if not new_login:
            raise HTTPException(status_code=400, detail="login_id cannot be empty.")
        data["login_id"] = new_login

    for field, value in data.items():
        setattr(obj, field, value)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.delete("/{login_id_pk}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_login_id(
    login_id_pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(login_id_pk, db, current_user)
    await db.delete(obj)
    await db.commit()
