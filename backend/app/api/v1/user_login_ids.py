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
from app.models.user_login_id import UserLoginId
from app.models.user_entity import UserEntity
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.user_login_id import (
    UserLoginIdCreate, UserLoginIdUpdate, UserLoginIdRead, BulkUploadResult,
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
    return UserLoginId.user_id == current_user.id


async def _load(login_id_pk: int, db: AsyncSession, current_user: User) -> UserLoginId:
    """Fetch a user-scoped UserLoginId with vendor + entity eager-loaded."""
    result = await db.execute(
        select(UserLoginId)
        .options(selectinload(UserLoginId.vendor), selectinload(UserLoginId.entity))
        .where(UserLoginId.id == login_id_pk, _scope(current_user))
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


async def _validate_entity(db: AsyncSession, current_user: User, entity_id: int | None) -> int | None:
    """Ensure entity_id (if given) is one of the caller's OWN entities."""
    if entity_id is None:
        return None
    exists = (await db.execute(
        select(UserEntity.id).where(UserEntity.id == entity_id, UserEntity.user_id == current_user.id)
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=400, detail=f"Entity id {entity_id} not found in your entities.")
    return entity_id


@router.get("/", response_model=list[UserLoginIdRead])
async def list_login_ids(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(UserLoginId).options(
        selectinload(UserLoginId.vendor), selectinload(UserLoginId.entity)
    ).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            UserLoginId.login_id.ilike(term),
            UserLoginId.airline_name.ilike(term),
            UserLoginId.airline_code.ilike(term),
            UserLoginId.lob.ilike(term),
        ))
    q = q.order_by(UserLoginId.login_id).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=UserLoginIdRead, status_code=status.HTTP_201_CREATED)
async def create_login_id(
    payload: UserLoginIdCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    login_val = (payload.login_id or "").strip()
    if not login_val:
        raise HTTPException(status_code=400, detail="login_id is required.")
    vendor_id = await _validate_vendor(db, payload.vendor_id)
    entity_id = await _validate_entity(db, current_user, payload.entity_id)

    obj = UserLoginId(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
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
    required = {"LOGIN_ID"}

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
                "Missing required column: LOGIN_ID. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: LOGIN_ID"
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

    # Pre-load this user's OWN entities for optional ENTITY_CODE lookup
    entities = (await db.execute(
        select(UserEntity).where(UserEntity.user_id == current_user.id)
    )).scalars().all()
    entity_lookup: dict[str, int] = {}
    for e in entities:
        for key in (e.code, e.name):
            if key:
                entity_lookup.setdefault(str(key).strip().lower(), e.id)

    total = len(df)
    success = 0
    errors: list[str] = []

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        login_val = _cell(row.get("LOGIN_ID"))
        if not login_val:
            errors.append(f"Row {row_num}: LOGIN_ID is required.")
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
            entity_id = entity_lookup.get(entity_raw.lower())
            if entity_id is None:
                errors.append(f"Row {row_num}: entity '{entity_raw}' not found in your entities — skipped.")
                continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(UserLoginId(
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
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
    ws.title = "Login ID Template"
    ws.append(["LOGIN_ID", "AIRLINE_NAME", "AIRLINE_CODE", "LOB", "VENDOR", "ENTITY_CODE", "ACTIVE"])
    ws.append(["AI-DEL-001", "Air India", "AI", "Domestic", "Acme Travels", "ENT-001", "yes"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="user_login_id_template.xlsx"'},
    )


@router.get("/{login_id_pk}", response_model=UserLoginIdRead)
async def get_login_id(
    login_id_pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load(login_id_pk, db, current_user)


@router.patch("/{login_id_pk}", response_model=UserLoginIdRead)
async def update_login_id(
    login_id_pk: int,
    payload: UserLoginIdUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(login_id_pk, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "vendor_id" in data:
        data["vendor_id"] = await _validate_vendor(db, data["vendor_id"])
    if "entity_id" in data:
        data["entity_id"] = await _validate_entity(db, current_user, data["entity_id"])
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
