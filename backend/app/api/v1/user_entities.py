from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user_entity import UserEntity
from app.models.user import User
from app.schemas.user_entity import (
    UserEntityCreate, UserEntityUpdate, UserEntityRead,
    UserEntityBulkCreate, BulkCreateResult, BulkUploadResult,
    tax_id_error,
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
    """User scope — entities are private to their owner (not shared per tenant)."""
    return UserEntity.user_id == current_user.id


async def _get_scoped_entity(entity_id: int, db: AsyncSession, current_user: User) -> UserEntity:
    result = await db.execute(select(UserEntity).where(UserEntity.id == entity_id, _scope(current_user)))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Entity not found")
    return obj


async def _code_exists(db: AsyncSession, current_user: User, code: str, exclude_id: int | None = None) -> bool:
    q = select(UserEntity.id).where(_scope(current_user), UserEntity.code == code)
    if exclude_id is not None:
        q = q.where(UserEntity.id != exclude_id)
    return (await db.execute(q)).scalar_one_or_none() is not None


@router.get("/", response_model=list[UserEntityRead])
async def list_entities(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(UserEntity).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            UserEntity.name.ilike(term),
            UserEntity.code.ilike(term),
            UserEntity.city.ilike(term),
            UserEntity.state.ilike(term),
        ))
    q = q.order_by(UserEntity.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=UserEntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    payload: UserEntityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    name = (payload.name or "").strip()
    code = (payload.code or "").strip()
    if not name or not code:
        raise HTTPException(status_code=400, detail="name and code are required.")
    if await _code_exists(db, current_user, code):
        raise HTTPException(status_code=400, detail=f"An entity with code '{code}' already exists.")
    tax_err = tax_id_error(payload.gst_number, payload.pan_number)
    if tax_err:
        raise HTTPException(status_code=400, detail=tax_err)

    entity = _build_entity(payload, current_user, name, code)
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity


def _build_entity(payload: UserEntityCreate, current_user: User, name: str, code: str) -> UserEntity:
    return UserEntity(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        name=name,
        code=code,
        address=(payload.address or "").strip() or None,
        state=(payload.state or "").strip() or None,
        city=(payload.city or "").strip() or None,
        gst_number=payload.gst_number,   # already normalised + validated by the schema
        pan_number=payload.pan_number,
        is_active=payload.is_active if payload.is_active is not None else True,
    )


@router.post("/bulk", response_model=BulkCreateResult, status_code=status.HTTP_201_CREATED)
async def bulk_create_entities(
    payload: UserEntityBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create several entities in one submit (the Add Entity form's '+ Add another').

    Valid rows are saved even if others fail, and every rejection is reported with
    its row number — so one typo never costs the user the whole batch.
    """
    rows = payload.entities or []
    if not rows:
        raise HTTPException(status_code=400, detail="No entities supplied.")

    errors: list[str] = []
    created: list[UserEntity] = []
    seen_codes: set[str] = set()

    for i, item in enumerate(rows, start=1):
        name = (item.name or "").strip()
        code = (item.code or "").strip()
        if not name or not code:
            errors.append(f"Entity {i}: name and code are required.")
            continue
        # Duplicates inside the submitted batch would otherwise fail confusingly
        # on the DB unique constraint, one commit later.
        if code.lower() in seen_codes:
            errors.append(f"Entity {i}: code '{code}' is repeated in this form.")
            continue
        if await _code_exists(db, current_user, code):
            errors.append(f"Entity {i}: an entity with code '{code}' already exists.")
            continue
        tax_err = tax_id_error(item.gst_number, item.pan_number)
        if tax_err:
            errors.append(f"Entity {i}: {tax_err}")
            continue
        seen_codes.add(code.lower())

        entity = _build_entity(item, current_user, name, code)
        db.add(entity)
        try:
            await db.commit()
            await db.refresh(entity)
            created.append(entity)
        except Exception as e:              # noqa: BLE001
            await db.rollback()
            errors.append(f"Entity {i}: {e}")

    return BulkCreateResult(
        total=len(rows),
        success=len(created),
        failed=len(rows) - len(created),
        errors=errors,
        created=[UserEntityRead.model_validate(e) for e in created],
    )


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

        # Tax ids are optional, but a malformed one is a data error worth naming
        # rather than storing silently. Accepts GST_NUMBER / GST / GSTIN headers.
        gst = (_cell(row.get("GST_NUMBER")) or _cell(row.get("GST")) or _cell(row.get("GSTIN"))).upper() or None
        pan = (_cell(row.get("PAN_NUMBER")) or _cell(row.get("PAN"))).upper() or None
        tax_err = tax_id_error(gst, pan)
        if tax_err:
            errors.append(f"Row {row_num}: {tax_err}")
            continue

        try:
            db.add(UserEntity(
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                name=name,
                code=code,
                address=_cell(row.get("ADDRESS")) or None,
                state=_cell(row.get("STATE")) or None,
                city=_cell(row.get("CITY")) or None,
                gst_number=gst,
                pan_number=pan,
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
    ws.append(["NAME", "CODE", "ADDRESS", "STATE", "CITY", "GST_NUMBER", "PAN_NUMBER", "ACTIVE"])
    ws.append(["Acme Pvt Ltd", "ENT-001", "12 MG Road", "Maharashtra", "Mumbai",
               "27ABCDE1234F1Z5", "ABCDE1234F", "yes"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="user_entity_template.xlsx"'},
    )


@router.get("/{entity_id}", response_model=UserEntityRead)
async def get_entity(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _get_scoped_entity(entity_id, db, current_user)


@router.patch("/{entity_id}", response_model=UserEntityRead)
async def update_entity(
    entity_id: int,
    payload: UserEntityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_scoped_entity(entity_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    # Check the values this PATCH would leave on the row, not just what it sends.
    tax_err = tax_id_error(
        data.get("gst_number", obj.gst_number),
        data.get("pan_number", obj.pan_number),
    )
    if tax_err:
        raise HTTPException(status_code=400, detail=tax_err)
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
