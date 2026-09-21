from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.india_tax import canonical_state, normalise as norm_tax_id, tax_id_error
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user_entity import UserEntity
from app.models.user_login_id import UserLoginId
from app.models.user import User
from app.schemas.user_entity import (
    UserEntityCreate, UserEntityUpdate, UserEntityRead,
    UserEntityBulkCreate, BulkCreateResult, BulkUploadResult,
)
from app.services import spreadsheet
# Super Admin manages entities; everyone else sees only the ones granted to them.
from app.services.entity_access import entity_scope, require_entity_manager

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
    """The entities this caller may see: the Super Admin's own, or — for anyone else —
    exactly those granted to them in User management. See services/entity_access."""
    return entity_scope(current_user)


async def _get_scoped_entity(entity_id: int, db: AsyncSession, current_user: User) -> UserEntity:
    result = await db.execute(select(UserEntity).where(UserEntity.id == entity_id, _scope(current_user)))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Entity not found")
    return obj


# ── The rules ─────────────────────────────────────────────────────────────────
#
# ONE PLACE for what a valid entity is, called by create, "+ Add another", the XLS
# upload and edit alike — so no path can be a way around another.

def entity_problem(state, gst, pan) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """(canonical state, GSTIN, PAN, problem) for one entity's tax identity.

    ALL THREE ARE REQUIRED, and they are checked AGAINST EACH OTHER, in the order the form
    asks for them: the state fixes a GSTIN's first two characters, the PAN fixes characters
    3 to 12, and the 15th is a check digit (app.core.india_tax.tax_id_error — the same
    check Agency Master uses). A GSTIN that is well-formed but belongs to another state or
    another PAN is refused, because it would put the wrong registration on every invoice
    this entity raises.

    Returns a problem string rather than raising so the bulk paths can attribute it to one
    row and still save the others.
    """
    raw_state = (state or "").strip()
    canon = canonical_state(raw_state)
    gst = norm_tax_id(gst)
    pan = norm_tax_id(pan)
    if not raw_state:
        return None, gst, pan, "State is required — the GSTIN's first two characters are checked against it."
    if not canon:
        return None, gst, pan, f"'{raw_state}' is not an Indian state or union territory with a GST code."
    if not pan:
        return canon, gst, pan, "PAN Number is required."
    if not gst:
        return canon, gst, pan, "GST Number is required."
    return canon, gst, pan, tax_id_error(gst, pan, canon)


async def _code_taken(db: AsyncSession, user_id: int, code: str, exclude_id: int | None = None) -> bool:
    """Is this code already used by one of the owner's entities, IGNORING CASE?

    Case-blind because "TSI" and "tsi" are the same code to anyone reading a report; the
    old check was an exact compare and let both in. Mirrors uq_user_entities_user_code_ci.
    """
    q = select(UserEntity.id).where(
        UserEntity.user_id == user_id, func.lower(UserEntity.code) == code.lower(),
    )
    if exclude_id is not None:
        q = q.where(UserEntity.id != exclude_id)
    return (await db.execute(q)).first() is not None


async def _gst_owner(db: AsyncSession, user_id: int, gst: str, exclude_id: int | None = None) -> Optional[UserEntity]:
    """The owner's entity already registered under this GSTIN, if any.

    THE GSTIN, NOT THE NAME OR THE PAN, is what makes two entities the same: a group's
    entities often share a name, and one PAN legitimately holds a GSTIN in each state it
    registers in (and up to 35 in one state — the 13th character). Mirrors
    uq_user_entities_user_gstin. Returned rather than a bool so the message can name it.
    """
    q = select(UserEntity).where(UserEntity.user_id == user_id, UserEntity.gst_number == gst)
    if exclude_id is not None:
        q = q.where(UserEntity.id != exclude_id)
    return (await db.execute(q.limit(1))).scalar_one_or_none()


def _gst_taken_message(gst: str, other: UserEntity) -> str:
    return f"GSTIN {gst} is already registered to your entity '{other.name}' ({other.code})."


async def _new_entity_problem(
    db: AsyncSession, user_id: int, name: str, code: str, state, gst, pan,
    seen_codes: set[str], seen_gsts: set[str],
) -> tuple[dict, Optional[str]]:
    """Every check a NEW entity must pass, in the order a person would fix them.

    `seen_codes` / `seen_gsts` carry what earlier rows of the same batch claimed, so two
    rows of one submit cannot both take a code or a GSTIN — they would otherwise both pass
    the database check and one would fail on the unique index a commit later, with a far
    less readable message.
    """
    if not name or not code:
        return {}, "Entity Name and Code are required."
    canon, gst, pan, problem = entity_problem(state, gst, pan)
    if problem:
        return {}, problem
    if code.lower() in seen_codes:
        return {}, f"Code '{code}' is repeated in this batch."
    if await _code_taken(db, user_id, code):
        return {}, f"An entity with code '{code}' already exists."
    if gst in seen_gsts:
        return {}, f"GSTIN {gst} is repeated in this batch."
    other = await _gst_owner(db, user_id, gst)
    if other is not None:
        return {}, _gst_taken_message(gst, other)
    return {"state": canon, "gst_number": gst, "pan_number": pan}, None


def _entity_row(user_id: int, tenant_id: Optional[int], name: str, code: str, tax: dict, *,
                address, city, is_active) -> UserEntity:
    return UserEntity(
        user_id=user_id,
        tenant_id=tenant_id,
        name=name,
        code=code,
        address=(address or "").strip() or None,
        city=(city or "").strip() or None,
        is_active=is_active if is_active is not None else True,
        **tax,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

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
            UserEntity.gst_number.ilike(term),
        ))
    q = q.order_by(UserEntity.name, UserEntity.code).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", response_model=UserEntityRead, status_code=status.HTTP_201_CREATED)
async def create_entity(
    payload: UserEntityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_entity_manager),
):
    name = (payload.name or "").strip()
    code = (payload.code or "").strip()
    tax, problem = await _new_entity_problem(
        db, current_user.id, name, code, payload.state, payload.gst_number, payload.pan_number,
        set(), set(),
    )
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    entity = _entity_row(current_user.id, current_user.tenant_id, name, code, tax,
                         address=payload.address, city=payload.city, is_active=payload.is_active)
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity


@router.post("/bulk", response_model=BulkCreateResult, status_code=status.HTTP_201_CREATED)
async def bulk_create_entities(
    payload: UserEntityBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_entity_manager),
):
    """Create several entities in one submit (the Add Entity form's '+ Add another').

    Valid rows are saved even if others fail, and every rejection is reported with
    its row number — so one typo never costs the user the whole batch.
    """
    rows = payload.entities or []
    if not rows:
        raise HTTPException(status_code=400, detail="No entities supplied.")

    # Read ONCE, before any commit or rollback. A rollback expires every loaded instance,
    # `current_user` included, and touching it afterwards raises MissingGreenlet — which
    # used to replace the real reason on every failing row after the first.
    user_id, tenant_id = current_user.id, current_user.tenant_id

    errors: list[str] = []
    created: list[UserEntity] = []
    seen_codes: set[str] = set()
    seen_gsts: set[str] = set()

    for i, item in enumerate(rows, start=1):
        name = (item.name or "").strip()
        code = (item.code or "").strip()
        tax, problem = await _new_entity_problem(
            db, user_id, name, code, item.state, item.gst_number, item.pan_number,
            seen_codes, seen_gsts,
        )
        if problem:
            errors.append(f"Entity {i}: {problem}")
            continue
        seen_codes.add(code.lower())
        seen_gsts.add(tax["gst_number"])

        entity = _entity_row(user_id, tenant_id, name, code, tax,
                             address=item.address, city=item.city, is_active=item.is_active)
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


# The spreadsheet headers a GSTIN / PAN may arrive under, first match wins.
_GST_HEADERS = ("GST_NUMBER", "GST", "GSTIN")
_PAN_HEADERS = ("PAN_NUMBER", "PAN")


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_entities(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_entity_manager),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"NAME", "CODE", "STATE"}

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
                # GST and PAN are required too, under any of their accepted headers.
                if not any(h in df_try.columns for h in _GST_HEADERS):
                    missing = missing | {"GST_NUMBER"}
                if not any(h in df_try.columns for h in _PAN_HEADERS):
                    missing = missing | {"PAN_NUMBER"}
                last_missing = missing
                if not missing:
                    df = df_try
                    used_header_row = header_row
                    break
            except Exception:
                continue

        if df is None:
            detail = (
                "Missing required columns: NAME, CODE, STATE, GST_NUMBER, PAN_NUMBER. "
                "Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. "
                "Required: NAME, CODE, STATE, GST_NUMBER, PAN_NUMBER — download the template."
            )
            raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}. Ensure it is a valid .xlsx or .xls file.")

    # See bulk_create_entities: read before any rollback can expire the instance.
    user_id, tenant_id = current_user.id, current_user.tenant_id

    total = len(df)
    success = 0
    errors: list[str] = []
    seen_codes: set[str] = set()
    seen_gsts: set[str] = set()

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        name = _cell(row.get("NAME"))
        code = _cell(row.get("CODE"))
        gst = next((_cell(row.get(h)) for h in _GST_HEADERS if _cell(row.get(h))), "")
        pan = next((_cell(row.get(h)) for h in _PAN_HEADERS if _cell(row.get(h))), "")

        tax, problem = await _new_entity_problem(
            db, user_id, name, code, _cell(row.get("STATE")), gst, pan, seen_codes, seen_gsts,
        )
        if problem:
            errors.append(f"Row {row_num}: {problem}")
            continue
        seen_codes.add(code.lower())
        seen_gsts.add(tax["gst_number"])

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(_entity_row(user_id, tenant_id, name, code, tax,
                               address=_cell(row.get("ADDRESS")), city=_cell(row.get("CITY")),
                               is_active=is_active))
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
    # STATE, GST_NUMBER AND PAN_NUMBER ARE REQUIRED and checked against each other: the
    # GSTIN's first two digits are the state's GST code (07 Delhi, 06 Haryana, 27
    # Maharashtra) and characters 3-12 are the PAN. Two entities of one group may share a
    # NAME and even a PAN (one GSTIN per state); CODE and GST_NUMBER must be unique.
    ws.append(["NAME", "CODE", "ADDRESS", "STATE", "CITY", "GST_NUMBER", "PAN_NUMBER", "ACTIVE"])
    ws.append(["Acme Travels Pvt Ltd", "ACME-DEL", "12 Connaught Place", "Delhi", "New Delhi",
               "07AAPFU0939F1ZX", "AAPFU0939F", "yes"])
    ws.append(["Acme Travels Pvt Ltd", "ACME-BOM", "4 Nariman Point", "Maharashtra", "Mumbai",
               "27AAPFU0939F1ZV", "AAPFU0939F", "yes"])

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
    current_user: User = Depends(require_entity_manager),
):
    """Edit an entity. STATE, GST AND PAN ARE RE-CHECKED AS A SET whenever the edit touches
    any of them, using the stored value for whichever ones it does not send — a GSTIN is
    only right relative to a state and a PAN.

    So an entity saved before GST and PAN were required is asked for both the first time
    its details are edited, while a PATCH that only flips Active (the list's toggle) still
    goes through: it does not touch the tax identity, so there is nothing to re-check.
    """
    obj = await _get_scoped_entity(entity_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)

    if "name" in data:
        data["name"] = (data["name"] or "").strip()
        if not data["name"]:
            raise HTTPException(status_code=400, detail="Entity Name cannot be empty.")

    if "code" in data:
        new_code = (data["code"] or "").strip()
        if not new_code:
            raise HTTPException(status_code=400, detail="Code cannot be empty.")
        if await _code_taken(db, obj.user_id, new_code, exclude_id=obj.id):
            raise HTTPException(status_code=400, detail=f"An entity with code '{new_code}' already exists.")
        data["code"] = new_code

    if {"state", "gst_number", "pan_number"} & data.keys():
        sent = lambda field: data[field] if field in data else getattr(obj, field)  # noqa: E731
        canon, gst, pan, problem = entity_problem(sent("state"), sent("gst_number"), sent("pan_number"))
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        other = await _gst_owner(db, obj.user_id, gst, exclude_id=obj.id)
        if other is not None:
            raise HTTPException(status_code=400, detail=_gst_taken_message(gst, other))
        data.update(state=canon, gst_number=gst, pan_number=pan)

    for field in ("address", "city"):
        if field in data:
            data[field] = (data[field] or "").strip() or None

    for field, value in data.items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_entity_manager),
):
    """Delete an entity AND every login ID / IATA number under it.

    A login ID belongs to its entity — it takes its state from it and cannot be saved
    without one — so leaving them behind would only create orphans. The foreign key is
    ON DELETE CASCADE (profile_login_cascade_01); they are also deleted explicitly here,
    in the same transaction, so this endpoint says what it does rather than relying on a
    rule that lives only in the schema. Team members' access grants to the entity go too
    (user_entity_access cascades). The My Profile Delete popup lists the login IDs first.
    """
    obj = await _get_scoped_entity(entity_id, db, current_user)
    await db.execute(
        delete(UserLoginId).where(
            UserLoginId.entity_id == obj.id, UserLoginId.user_id == obj.user_id,
        )
    )
    await db.delete(obj)
    await db.commit()
