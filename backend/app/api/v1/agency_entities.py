from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agency_entity import AgencyEntity
from app.models.agency_login_id import AgencyLoginId
from app.models.agency import Agency
from app.models.user import User
from app.schemas.agency_entity import (
    AgencyEntityCreate, AgencyEntityUpdate, AgencyEntityRead, BulkUploadResult,
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
    """User scope — entities are private to their owner."""
    return AgencyEntity.user_id == current_user.id


async def _load(entity_id: int, db: AsyncSession, current_user: User) -> AgencyEntity:
    result = await db.execute(
        select(AgencyEntity)
        .options(selectinload(AgencyEntity.agency))
        .where(AgencyEntity.id == entity_id, _scope(current_user))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Entity not found")
    return obj


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


async def _code_exists(db: AsyncSession, agency_id: int, code: str, exclude_id: int | None = None) -> bool:
    """Code uniqueness is scoped PER AGENCY (two agencies may reuse a code)."""
    q = select(AgencyEntity.id).where(AgencyEntity.agency_id == agency_id, AgencyEntity.code == code)
    if exclude_id is not None:
        q = q.where(AgencyEntity.id != exclude_id)
    return (await db.execute(q)).scalar_one_or_none() is not None


async def _login_counts(db: AsyncSession, current_user: User, agency_id: int | None) -> dict[int, int]:
    q = (
        select(AgencyLoginId.entity_id, func.count())
        .where(AgencyLoginId.user_id == current_user.id, AgencyLoginId.entity_id.isnot(None))
        .group_by(AgencyLoginId.entity_id)
    )
    if agency_id is not None:
        q = q.where(AgencyLoginId.agency_id == agency_id)
    return {eid: c for eid, c in (await db.execute(q)).all()}


@router.get("/", response_model=list[AgencyEntityRead])
async def list_entities(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    agency_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(AgencyEntity).options(selectinload(AgencyEntity.agency)).where(_scope(current_user))
    if agency_id is not None:
        q = q.where(AgencyEntity.agency_id == agency_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            AgencyEntity.name.ilike(term),
            AgencyEntity.code.ilike(term),
            AgencyEntity.city.ilike(term),
            AgencyEntity.state.ilike(term),
        ))
    q = q.order_by(AgencyEntity.name).offset(skip).limit(limit)
    rows = (await db.execute(q)).scalars().all()

    counts = await _login_counts(db, current_user, agency_id)
    for e in rows:
        e.login_id_count = counts.get(e.id, 0)
    return rows


@router.post("/", response_model=AgencyEntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    payload: AgencyEntityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = (payload.name or "").strip()
    code = (payload.code or "").strip()
    if not name or not code:
        raise HTTPException(status_code=400, detail="name and code are required.")
    agency_id = await _validate_agency(db, current_user, payload.agency_id)
    if await _code_exists(db, agency_id, code):
        raise HTTPException(status_code=400, detail=f"An entity with code '{code}' already exists for this agency.")

    entity = AgencyEntity(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        agency_id=agency_id,
        name=name,
        code=code,
        address=(payload.address or "").strip() or None,
        state=(payload.state or "").strip() or None,
        city=(payload.city or "").strip() or None,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(entity)
    await db.commit()
    return await _load(entity.id, db, current_user)


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_entities(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"AGENCY", "NAME", "CODE"}

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
                "Missing required columns: AGENCY, NAME, CODE. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: AGENCY, NAME, CODE"
            )
            raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}. Ensure it is a valid .xlsx or .xls file.")

    # Pre-load this user's agencies for the AGENCY column lookup (match on name)
    agencies = (await db.execute(select(Agency).where(Agency.user_id == current_user.id))).scalars().all()
    agency_lookup = {str(a.name).strip().lower(): a.id for a in agencies if a.name}

    total = len(df)
    success = 0
    errors: list[str] = []

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        agency_raw = _cell(row.get("AGENCY"))
        name = _cell(row.get("NAME"))
        code = _cell(row.get("CODE"))
        if not agency_raw or not name or not code:
            errors.append(f"Row {row_num}: AGENCY, NAME and CODE are required.")
            continue
        agency_id = agency_lookup.get(agency_raw.lower())
        if agency_id is None:
            errors.append(f"Row {row_num}: agency '{agency_raw}' not found in your agencies — skipped.")
            continue
        if await _code_exists(db, agency_id, code):
            errors.append(f"Row {row_num}: code '{code}' already exists for agency '{agency_raw}' — skipped.")
            continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(AgencyEntity(
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                agency_id=agency_id,
                name=name,
                code=code,
                address=_cell(row.get("ADDRESS")) or None,
                state=_cell(row.get("STATE")) or None,
                city=_cell(row.get("CITY")) or None,
                is_active=is_active,
            ))
            await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e}")

    return BulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.get("/template")
async def download_entity_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Agency Entity Template"
    ws.append(["AGENCY", "NAME", "CODE", "ADDRESS", "STATE", "CITY", "ACTIVE"])
    ws.append(["Lords Travels", "Lords Delhi", "DEL-001", "12 CP", "Delhi", "New Delhi", "yes"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="agency_entity_template.xlsx"'},
    )


@router.get("/{entity_id}", response_model=AgencyEntityRead)
async def get_entity(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load(entity_id, db, current_user)


@router.patch("/{entity_id}", response_model=AgencyEntityRead)
async def update_entity(
    entity_id: int,
    payload: AgencyEntityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(entity_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)

    # resolve the target agency (may be changing) for the code-uniqueness check
    target_agency = obj.agency_id
    if "agency_id" in data:
        target_agency = await _validate_agency(db, current_user, data["agency_id"])
        data["agency_id"] = target_agency

    if "code" in data:
        new_code = (data["code"] or "").strip()
        if not new_code:
            raise HTTPException(status_code=400, detail="code cannot be empty.")
        if await _code_exists(db, target_agency, new_code, exclude_id=obj.id):
            raise HTTPException(status_code=400, detail=f"An entity with code '{new_code}' already exists for this agency.")
        data["code"] = new_code

    for field, value in data.items():
        setattr(obj, field, value)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(entity_id, db, current_user)
    await db.delete(obj)
    await db.commit()
