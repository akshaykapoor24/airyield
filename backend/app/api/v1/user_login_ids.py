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
from app.models.user_login_id import UserLoginId
from app.models.user_entity import UserEntity
from app.models.user import User
from app.schemas.user_login_id import (
    UserLoginIdCreate, UserLoginIdUpdate, UserLoginIdRead, BulkUploadResult,
)
from app.services import spreadsheet
# Super Admin manages login IDs; everyone else sees those under their granted entities.
from app.services.entity_access import login_scope, require_entity_manager

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
    """The login IDs this caller may see: the Super Admin's own, or — for anyone else —
    every login ID under an entity granted to them. See services/entity_access."""
    return login_scope(current_user)


async def _load(login_id_pk: int, db: AsyncSession, current_user: User) -> UserLoginId:
    """Fetch a user-scoped UserLoginId with its entity eager-loaded (its state and fallback
    city are read from there).

    `populate_existing` because sessions here do not expire on commit (database.py): after
    an edit moves a login to another entity, the instance still holds the OLD entity, and a
    plain re-select would hand it back unchanged — the response would name the entity the
    login just left.
    """
    result = await db.execute(
        select(UserLoginId)
        .options(selectinload(UserLoginId.entity))
        .where(UserLoginId.id == login_id_pk, _scope(current_user))
        .execution_options(populate_existing=True)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Login ID not found")
    return obj


async def _require_entity(db: AsyncSession, user_id: int, entity_id: Optional[int]) -> UserEntity:
    """The entity a login ID / IATA number belongs to — required, and one of the caller's own.

    REQUIRED because a login is located by its entity: its state IS the entity's (a GSTIN
    belongs to one state, so an office elsewhere is another entity), and its city falls
    back to the entity's. A login with no entity has neither.
    """
    if entity_id is None:
        raise HTTPException(status_code=400, detail="Entity is required — pick the entity this login ID belongs to.")
    entity = (await db.execute(
        select(UserEntity).where(UserEntity.id == entity_id, UserEntity.user_id == user_id)
    )).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=400, detail=f"Entity id {entity_id} not found in your entities.")
    return entity


def _own_city(city: Optional[str], entity: UserEntity) -> Optional[str]:
    """What to store in `city`: the office's own city, or NULL for "the entity's".

    Blank → NULL, and so is a value equal to the entity's city: storing a copy would stop
    the login following the entity if the entity's city is corrected later — the whole
    point of NULL meaning "inherit".
    """
    value = (city or "").strip()
    if not value or value.lower() == (entity.city or "").strip().lower():
        return None
    return value


async def _login_holder(db: AsyncSession, user_id: int, login: str, exclude_id: int | None = None) -> Optional[UserEntity | bool]:
    """Who already holds this login ID / IATA number, IGNORING CASE, across ALL the owner's
    entities — the entity it sits under, True if it sits under none, None if it is free.

    Across all entities, not per entity: an IATA code is issued to one office of one
    entity, so the same value under a second entity is always a mistake rather than a
    second office. Mirrors uq_user_login_ids_user_login_ci.
    """
    q = (
        select(UserLoginId)
        .options(selectinload(UserLoginId.entity))
        .where(UserLoginId.user_id == user_id, func.lower(UserLoginId.login_id) == login.lower())
    )
    if exclude_id is not None:
        q = q.where(UserLoginId.id != exclude_id)
    hit = (await db.execute(q.limit(1))).scalar_one_or_none()
    if hit is None:
        return None
    return hit.entity if hit.entity is not None else True


def _taken_message(login: str, holder) -> str:
    if holder is True:
        return f"Login ID '{login}' already exists."
    return f"Login ID '{login}' already exists under your entity '{holder.name}' ({holder.code})."


@router.get("/", response_model=list[UserLoginIdRead])
async def list_login_ids(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    entity_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(UserLoginId).options(selectinload(UserLoginId.entity)).where(_scope(current_user))
    if entity_id is not None:
        q = q.where(UserLoginId.entity_id == entity_id)
    if search and search.strip():
        term = f"%{search.strip()}%"
        # The entity's name, code and city are searchable too — "tsi" should find every
        # IATA number under TSI, which is how these are looked up.
        q = q.outerjoin(UserEntity, UserEntity.id == UserLoginId.entity_id).where(or_(
            UserLoginId.login_id.ilike(term),
            UserLoginId.city.ilike(term),
            UserEntity.name.ilike(term),
            UserEntity.code.ilike(term),
            UserEntity.city.ilike(term),
        ))
    q = q.order_by(UserLoginId.login_id).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=UserLoginIdRead, status_code=status.HTTP_201_CREATED)
async def create_login_id(
    payload: UserLoginIdCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_entity_manager),
):
    login_val = (payload.login_id or "").strip()
    if not login_val:
        raise HTTPException(status_code=400, detail="Login ID / IATA Number is required.")
    entity = await _require_entity(db, current_user.id, payload.entity_id)
    holder = await _login_holder(db, current_user.id, login_val)
    if holder is not None:
        raise HTTPException(status_code=400, detail=_taken_message(login_val, holder))

    obj = UserLoginId(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        login_id=login_val,
        entity_id=entity.id,
        city=_own_city(payload.city, entity),
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(obj)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_login_ids(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_entity_manager),
):
    """LOGIN_ID + ENTITY_CODE (both required), CITY optional (blank = the entity's).

    A sheet from the old template still imports: its AIRLINE_NAME / AIRLINE_CODE / LOB /
    VENDOR columns are simply not read, since a login no longer carries them.
    """
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"LOGIN_ID", "ENTITY_CODE"}

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
                # Format from the bytes, not the extension: a supplier's ".xls"
                # is as often an xlsx or a CSV, and a real one needs an engine
                # pandas will not pick on its own.
                df_try = spreadsheet.read_df(content, filename, header_row)
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
                "Missing required columns: LOGIN_ID, ENTITY_CODE. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: LOGIN_ID, ENTITY_CODE"
            )
            raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}. Ensure it is a valid .xlsx or .xls file.")

    # Read ONCE, before any commit or rollback: a rollback expires `current_user`, and
    # touching it afterwards raises MissingGreenlet in place of the row's real error.
    user_id, tenant_id = current_user.id, current_user.tenant_id

    # This user's OWN entities, by code (ignoring case) and by name as a fallback.
    entities = (await db.execute(
        select(UserEntity).where(UserEntity.user_id == user_id)
    )).scalars().all()
    entity_lookup: dict[str, UserEntity] = {}
    for e in entities:
        for key in (e.code, e.name):
            if key:
                entity_lookup.setdefault(str(key).strip().lower(), e)

    total = len(df)
    success = 0
    errors: list[str] = []
    seen: set[str] = set()

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        login_val = _cell(row.get("LOGIN_ID"))
        if not login_val:
            errors.append(f"Row {row_num}: LOGIN_ID is required.")
            continue

        entity_raw = _cell(row.get("ENTITY_CODE"))
        if not entity_raw:
            errors.append(f"Row {row_num}: ENTITY_CODE is required.")
            continue
        entity = entity_lookup.get(entity_raw.lower())
        if entity is None:
            errors.append(f"Row {row_num}: entity '{entity_raw}' not found in your entities — skipped.")
            continue

        if login_val.lower() in seen:
            errors.append(f"Row {row_num}: login ID '{login_val}' is repeated in this file.")
            continue
        holder = await _login_holder(db, user_id, login_val)
        if holder is not None:
            errors.append(f"Row {row_num}: {_taken_message(login_val, holder)}")
            continue
        seen.add(login_val.lower())

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(UserLoginId(
                user_id=user_id,
                tenant_id=tenant_id,
                login_id=login_val,
                entity_id=entity.id,
                city=_own_city(_cell(row.get("CITY")), entity),
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
    # One row per login ID / IATA number. ENTITY_CODE is the code of one of your entities
    # (My Profile → Entities) and decides the STATE. Leave CITY blank to use the entity's;
    # fill it only for an office in another city of the same state. Each LOGIN_ID may
    # appear once across all your entities.
    ws.append(["LOGIN_ID", "ENTITY_CODE", "CITY", "ACTIVE"])
    ws.append(["14312345", "ENT-DEL", "", "yes"])
    ws.append(["14398765", "ENT-DEL", "", "yes"])
    ws.append(["14454321", "ENT-BOM", "Pune", "yes"])

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
    current_user: User = Depends(require_entity_manager),
):
    """Edit a login ID. The entity cannot be cleared, only changed — and changing it (or
    the city) re-decides whether the city is the office's own or the new entity's."""
    obj = await _load(login_id_pk, db, current_user)
    data = payload.model_dump(exclude_unset=True)

    if "login_id" in data:
        new_login = (data["login_id"] or "").strip()
        if not new_login:
            raise HTTPException(status_code=400, detail="Login ID / IATA Number cannot be empty.")
        holder = await _login_holder(db, obj.user_id, new_login, exclude_id=obj.id)
        if holder is not None:
            raise HTTPException(status_code=400, detail=_taken_message(new_login, holder))
        data["login_id"] = new_login

    if "entity_id" in data or "city" in data:
        entity = await _require_entity(db, obj.user_id, data.get("entity_id", obj.entity_id))
        data["entity_id"] = entity.id
        data["city"] = _own_city(data.get("city", obj.city), entity)

    for field, value in data.items():
        setattr(obj, field, value)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.delete("/{login_id_pk}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_login_id(
    login_id_pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_entity_manager),
):
    obj = await _load(login_id_pk, db, current_user)
    await db.delete(obj)
    await db.commit()
