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
from app.models.agency import CHANNEL_SCOPES, CHANNELS, Agency, norm_channel, scope_covers
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


async def _validate_agency(db: AsyncSession, current_user: User, agency_id: int | None) -> Agency:
    """Ensure agency_id is one of the caller's OWN agencies, and return it.

    Returns the row rather than the id because callers need its `channels` to
    check an entity's scope against.
    """
    if agency_id is None:
        raise HTTPException(status_code=400, detail="agency_id is required.")
    agency = (await db.execute(
        select(Agency).where(Agency.id == agency_id, Agency.user_id == current_user.id)
    )).scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=400, detail=f"Agency id {agency_id} not found in your agencies.")
    return agency


def _validate_scope(agency: Agency, raw) -> str:
    """An entity's channels, checked against what its agency actually trades on.

    Defaults to the agency's own scope, which is right for the common case: a
    GDS-only agency's entities are GDS entities, and a BOTH agency's entity
    usually works both unless told otherwise.
    """
    scope = norm_channel(raw) or agency.channels
    if scope not in CHANNEL_SCOPES:
        raise HTTPException(status_code=400, detail=f"channels must be one of {sorted(CHANNEL_SCOPES)}.")
    # BOTH covers everything; anything narrower must sit inside the agency's scope.
    if agency.channels != "BOTH" and scope != agency.channels:
        raise HTTPException(
            status_code=400,
            detail=f"This agency trades on {agency.channels} only — an entity cannot be scoped to {scope}.",
        )
    return scope


def _agency_resolver(agencies: list[Agency]):
    """Resolve an XLS AGENCY (+ optional AGENCY_BRANCH / channel) cell to one row.

    Replaces the plain `{name.lower(): id}` dict this used to build. That dict was
    a comprehension, so on duplicate names it was LAST-WRITE-WINS and silently
    filed every row under whichever branch happened to be iterated last. A vendor
    is deliberately onboarded once per branch AND once per channel, so a bare name
    is ambiguous twice over: "Lords Travels" can mean Delhi or Mumbai, and Lords
    Delhi can mean its GDS agency or its LCC one. Both narrow the candidates; an
    ambiguity that survives both is an error naming what would settle it, never a
    guess — the guess would file entities under the wrong account.
    """
    by_name: dict[str, list[Agency]] = {}
    for a in agencies:
        if not a.name:
            continue
        by_name.setdefault(str(a.name).strip().lower(), []).append(a)

    def resolve(name_raw: str, branch_raw: str = "", channel_raw: str = "") -> tuple[Agency | None, str]:
        n = (name_raw or "").strip().lower()
        branch = (branch_raw or "").strip().lower()
        matches = by_name.get(n, [])
        if not matches:
            return None, f"agency '{name_raw}' not found in your agencies — skipped."

        if branch:
            matches = [m for m in matches if str(m.branch_code or "").strip().lower() == branch]
            if not matches:
                return None, f"agency '{name_raw}' branch '{branch_raw}' not found in your agencies — skipped."

        # The row's own channel column disambiguates a branch onboarded twice. A
        # legacy BOTH agency covers whichever channel is asked for, hence scope_covers.
        channel = norm_channel(channel_raw)
        if len(matches) > 1 and channel:
            narrowed = [m for m in matches if scope_covers(m.channels, channel)]
            if narrowed:
                matches = narrowed

        if len(matches) == 1:
            return matches[0], ""

        branches = {str(m.branch_code) for m in matches}
        if len(branches) > 1:
            return None, (
                f"'{name_raw}' is onboarded on {len(branches)} branches ({', '.join(sorted(branches))}) — "
                f"add an AGENCY_BRANCH column to say which."
            )
        channels = ", ".join(sorted(str(m.channels) for m in matches))
        return None, (
            f"'{name_raw}' branch '{sorted(branches)[0]}' is onboarded once per channel ({channels}) — "
            f"set CHANNELS on this row to say which agency it belongs to."
        )

    return resolve


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
    channel: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(AgencyEntity).options(selectinload(AgencyEntity.agency)).where(_scope(current_user))
    if agency_id is not None:
        q = q.where(AgencyEntity.agency_id == agency_id)
    ch = norm_channel(channel)
    if ch is not None:
        if ch not in CHANNELS:
            raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")
        # A BOTH entity belongs to either channel's list.
        q = q.where(or_(AgencyEntity.channels == ch, AgencyEntity.channels == "BOTH"))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            AgencyEntity.name.ilike(term),
            AgencyEntity.code.ilike(term),
            AgencyEntity.channels.ilike(term),
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
    agency = await _validate_agency(db, current_user, payload.agency_id)
    if await _code_exists(db, agency.id, code):
        raise HTTPException(status_code=400, detail=f"An entity with code '{code}' already exists for this agency.")

    entity = AgencyEntity(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        agency_id=agency.id,
        name=name,
        code=code,
        channels=_validate_scope(agency, payload.channels),
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
    required = {"AGENCY", "NAME", "CODE", "CHANNELS"}

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
                "Missing required columns: AGENCY, NAME, CODE, CHANNELS. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: AGENCY, NAME, CODE, CHANNELS"
            )
            raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}. Ensure it is a valid .xlsx or .xls file.")

    agencies = (await db.execute(select(Agency).where(Agency.user_id == current_user.id))).scalars().all()
    resolve_agency = _agency_resolver(agencies)

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
        agency, why = resolve_agency(
            agency_raw, _cell(row.get("AGENCY_BRANCH")), _cell(row.get("CHANNELS")),
        )
        if agency is None:
            errors.append(f"Row {row_num}: {why}")
            continue
        if await _code_exists(db, agency.id, code):
            errors.append(f"Row {row_num}: code '{code}' already exists for agency '{agency_raw}' — skipped.")
            continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(AgencyEntity(
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                agency_id=agency.id,
                name=name,
                code=code,
                channels=_validate_scope(agency, row.get("CHANNELS")),
                address=_cell(row.get("ADDRESS")) or None,
                state=_cell(row.get("STATE")) or None,
                city=_cell(row.get("CITY")) or None,
                is_active=is_active,
            ))
            await db.commit()
            success += 1
        except HTTPException as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e.detail}")
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
    # AGENCY_BRANCH is only needed when a vendor is onboarded on more than one
    # branch — leave it blank otherwise and the name alone resolves.
    # CHANNELS is GDS | LCC | BOTH and must sit inside the agency's own scope. It
    # doubles as the tie-breaker when one branch is onboarded on both channels as
    # two agencies: the row lands under the agency whose channel it names.
    ws.append(["AGENCY", "AGENCY_BRANCH", "NAME", "CODE", "CHANNELS", "ADDRESS", "STATE", "CITY", "ACTIVE"])
    ws.append(["Lords Travels", "DEL", "Lords Delhi HO", "DEL-001", "GDS", "12 CP", "Delhi", "New Delhi", "yes"])
    ws.append(["Lords Travels", "DEL", "Lords Delhi Sales", "DEL-002", "LCC", "8 Nehru Place", "Delhi", "New Delhi", "yes"])

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

    # resolve the target agency (may be changing) for the code-uniqueness and
    # scope checks below
    agency = None
    if "agency_id" in data:
        agency = await _validate_agency(db, current_user, data["agency_id"])
        data["agency_id"] = agency.id

    if "code" in data:
        new_code = (data["code"] or "").strip()
        if not new_code:
            raise HTTPException(status_code=400, detail="code cannot be empty.")
        target = agency.id if agency else obj.agency_id
        if await _code_exists(db, target, new_code, exclude_id=obj.id):
            raise HTTPException(status_code=400, detail=f"An entity with code '{new_code}' already exists for this agency.")
        data["code"] = new_code

    # `channels` must never reach the blind setattr below unvalidated — that loop
    # writes whatever the schema accepted, and an entity scoped outside its
    # agency's channels would then hold credentials the agency cannot use.
    # Re-check it whenever EITHER side moves, not only when channels is sent.
    if "channels" in data or agency is not None:
        agency = agency or await _validate_agency(db, current_user, obj.agency_id)
        data["channels"] = _validate_scope(agency, data.get("channels", obj.channels))

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
