from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.entity import Entity
from app.models.user import User
from app.schemas.entity import EntityCreate, EntityUpdate, EntityRead, BulkUploadResult

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
    """Tenant scope — entities are shared across the tenant's users."""
    return Entity.tenant_id == current_user.tenant_id


async def _get_scoped_entity(entity_id: int, db: AsyncSession, current_user: User) -> Entity:
    result = await db.execute(select(Entity).where(Entity.id == entity_id, _scope(current_user)))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Entity not found")
    return obj


async def _code_exists(db: AsyncSession, current_user: User, code: str, exclude_id: int | None = None) -> bool:
    q = select(Entity.id).where(_scope(current_user), Entity.code == code)
    if exclude_id is not None:
        q = q.where(Entity.id != exclude_id)
    return (await db.execute(q)).scalar_one_or_none() is not None


@router.get("/", response_model=list[EntityRead])
async def list_entities(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Entity).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Entity.name.ilike(term),
            Entity.code.ilike(term),
            Entity.city.ilike(term),
            Entity.state.ilike(term),
        ))
    q = q.order_by(Entity.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    payload: EntityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = (payload.name or "").strip()
    code = (payload.code or "").strip()
    if not name or not code:
        raise HTTPException(status_code=400, detail="name and code are required.")
    if await _code_exists(db, current_user, code):
        raise HTTPException(status_code=400, detail=f"An entity with code '{code}' already exists.")

    entity = Entity(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        name=name,
        code=code,
        address=(payload.address or "").strip() or None,
        state=(payload.state or "").strip() or None,
        city=(payload.city or "").strip() or None,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_entities(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"NAME", "CODE"}

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
                "Missing required columns: NAME, CODE. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: NAME, CODE"
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
        code = _cell(row.get("CODE"))
        if not name or not code:
            errors.append(f"Row {row_num}: NAME and CODE are required.")
            continue
        if await _code_exists(db, current_user, code):
            errors.append(f"Row {row_num}: code '{code}' already exists — skipped.")
            continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(Entity(
                tenant_id=current_user.tenant_id,
                created_by_id=current_user.id,
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
    ws.title = "Entity Template"
    ws.append(["NAME", "CODE", "ADDRESS", "STATE", "CITY", "ACTIVE"])
    ws.append(["Acme Pvt Ltd", "ENT-001", "12 MG Road", "Maharashtra", "Mumbai", "yes"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="entity_template.xlsx"'},
    )


@router.get("/{entity_id}", response_model=EntityRead)
async def get_entity(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_scoped_entity(entity_id, db, current_user)


@router.patch("/{entity_id}", response_model=EntityRead)
async def update_entity(
    entity_id: int,
    payload: EntityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_scoped_entity(entity_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "code" in data:
        new_code = (data["code"] or "").strip()
        if not new_code:
            raise HTTPException(status_code=400, detail="code cannot be empty.")
        if await _code_exists(db, current_user, new_code, exclude_id=obj.id):
            raise HTTPException(status_code=400, detail=f"An entity with code '{new_code}' already exists.")
        data["code"] = new_code
    for field, value in data.items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_scoped_entity(entity_id, db, current_user)
    await db.delete(obj)
    await db.commit()
