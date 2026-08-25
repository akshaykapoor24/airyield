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
from app.models.agency import CHANNELS, Agency, norm_channel, scope_covers
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


async def _validate_agency(db: AsyncSession, current_user: User, agency_id: int | None) -> Agency:
    """Ensure agency_id is one of the caller's OWN agencies, and return it.

    Returns the row rather than the id because the caller needs its `channels`
    to check the credential's channel against.
    """
    if agency_id is None:
        raise HTTPException(status_code=400, detail="agency_id is required.")
    agency = (await db.execute(
        select(Agency).where(Agency.id == agency_id, Agency.user_id == current_user.id)
    )).scalar_one_or_none()
    if not agency:
        raise HTTPException(status_code=400, detail=f"Agency id {agency_id} not found in your agencies.")
    return agency


def _agency_resolver(agencies: list[Agency]):
    """Resolve an XLS AGENCY (+ optional AGENCY_BRANCH / CHANNEL) cell to one row.

    Replaces the plain `{name.lower(): id}` dict this used to build. That dict was
    a comprehension, so on duplicate names it was LAST-WRITE-WINS and silently
    filed every row under whichever branch happened to be iterated last. A vendor
    is deliberately onboarded once per branch AND once per channel, so a bare name
    is ambiguous twice over: "Lords Travels" can mean Delhi or Mumbai, and Lords
    Delhi can mean its GDS agency or its LCC one. Both narrow the candidates; an
    ambiguity that survives both is an error naming what would settle it, never a
    guess — the guess would file credentials under the wrong account.

    The CHANNEL column is a natural tie-breaker here, since a credential is always
    for exactly one channel: a mirror id is a GDS artifact and an airline portal
    login is an LCC one.
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

        # A legacy BOTH agency covers whichever channel is asked for, hence scope_covers.
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
            f"set CHANNEL on this row to say which agency the credential belongs to."
        )

    return resolve


def _validate_channel(agency: Agency, raw) -> str:
    """A credential's channel — always exactly one, and inside the agency's scope.

    Unlike an entity, this is never BOTH: a mirror id is a GDS artifact and an
    airline portal login is an LCC artifact, and the two are not interchangeable.
    """
    ch = norm_channel(raw)
    if ch not in CHANNELS:
        raise HTTPException(
            status_code=400,
            detail="channel is required — GDS (mirror ID) or LCC (login ID / airline ID).",
        )
    if not scope_covers(agency.channels, ch):
        raise HTTPException(
            status_code=400,
            detail=f"This agency trades on {agency.channels} only — it has no {ch} credentials.",
        )
    return ch


async def _validate_entity(
    db: AsyncSession, current_user: User, agency_id: int, entity_id: int | None, channel: str
) -> int | None:
    """Ensure entity_id (if given) belongs to the caller, to the chosen agency,
    AND trades on the channel this credential is for.

    The cross-channel check lives here because this is already the one place that
    enforces "the entity belongs to this agency" — keeping both invariants
    together means a caller cannot satisfy one and skip the other.
    """
    if entity_id is None:
        return None
    entity = (await db.execute(
        select(AgencyEntity).where(
            AgencyEntity.id == entity_id,
            AgencyEntity.user_id == current_user.id,
            AgencyEntity.agency_id == agency_id,
        )
    )).scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=400, detail=f"Entity id {entity_id} not found under the chosen agency.")
    if not scope_covers(entity.channels, channel):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Entity '{entity.code}' is scoped to {entity.channels} only — "
                f"it cannot hold a {channel} credential."
            ),
        )
    return entity_id


@router.get("/", response_model=list[AgencyLoginIdRead])
async def list_login_ids(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    agency_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    channel: Optional[str] = None,
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
    ch = norm_channel(channel)
    if ch is not None:
        if ch not in CHANNELS:
            raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")
        q = q.where(AgencyLoginId.channel == ch)
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
    agency = await _validate_agency(db, current_user, payload.agency_id)
    channel = _validate_channel(agency, payload.channel)
    login_val = (payload.login_id or "").strip()
    if not login_val:
        label = "Mirror ID" if channel == "GDS" else "Login ID / Airline ID"
        raise HTTPException(status_code=400, detail=f"{label} is required.")
    vendor_id = await _validate_vendor(db, payload.vendor_id)
    entity_id = await _validate_entity(db, current_user, agency.id, payload.entity_id, channel)

    obj = AgencyLoginId(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        agency_id=agency.id,
        channel=channel,
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
    required = {"LOGIN_ID", "AGENCY", "CHANNEL"}

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
                "Missing required columns: LOGIN_ID, AGENCY, CHANNEL. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: LOGIN_ID, AGENCY, CHANNEL"
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

    # This user's agencies, resolved by (name, branch) rather than name alone —
    # a vendor is onboarded once per branch, so a bare name can be ambiguous.
    agencies = (await db.execute(select(Agency).where(Agency.user_id == current_user.id))).scalars().all()
    resolve_agency = _agency_resolver(agencies)

    entities = (await db.execute(
        select(AgencyEntity).where(AgencyEntity.user_id == current_user.id)
    )).scalars().all()
    # Keyed by (agency_id, code|name) so an entity code resolves within its agency.
    # NO channel in the key, deliberately: entities carry a channel SCOPE rather
    # than being duplicated per channel, so a code is still unique per agency and
    # this .setdefault cannot silently collapse two rows into one.
    entity_lookup: dict[tuple[int, str], AgencyEntity] = {}
    for e in entities:
        for key in (e.code, e.name):
            if key:
                entity_lookup.setdefault((e.agency_id, str(key).strip().lower()), e)

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
        agency, why = resolve_agency(
            agency_raw, _cell(row.get("AGENCY_BRANCH")), _cell(row.get("CHANNEL")),
        )
        if agency is None:
            errors.append(f"Row {row_num}: {why}")
            continue

        try:
            channel = _validate_channel(agency, row.get("CHANNEL"))
        except HTTPException as e:
            errors.append(f"Row {row_num}: {e.detail}")
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
            entity = entity_lookup.get((agency.id, entity_raw.lower()))
            if entity is None:
                errors.append(f"Row {row_num}: entity '{entity_raw}' not found under agency '{agency_raw}' — skipped.")
                continue
            if not scope_covers(entity.channels, channel):
                errors.append(
                    f"Row {row_num}: entity '{entity_raw}' is scoped to {entity.channels} only — "
                    f"it cannot hold a {channel} credential."
                )
                continue
            entity_id = entity.id

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            db.add(AgencyLoginId(
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                agency_id=agency.id,
                channel=channel,
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
    # LOGIN_ID holds the mirror ID on a GDS row and the portal login / airline ID
    # on an LCC row — one column, relabelled by channel in the app.
    # AGENCY_BRANCH is only needed when a vendor is onboarded on several branches.
    ws.append([
        "CHANNEL", "LOGIN_ID", "AGENCY", "AGENCY_BRANCH", "ENTITY_CODE",
        "AIRLINE_NAME", "AIRLINE_CODE", "LOB", "VENDOR", "ACTIVE",
    ])
    # VENDOR is optional and must match the Suppliers master when set, so the
    # samples leave it blank — a sample row that fails on a name this particular
    # database has never heard of teaches the wrong lesson.
    ws.append(["GDS", "6X2K-DEL", "Lords Travels", "DEL", "DEL-001", "", "", "B2B", "", "yes"])
    ws.append(["LCC", "6E-AGT-88213", "Lords Travels", "DEL", "DEL-001", "IndiGo", "6E", "B2B", "", "yes"])

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

    # resolve the target agency (may be changing) so channel and entity are
    # checked against the agency this credential will actually belong to
    agency = None
    if "agency_id" in data:
        agency = await _validate_agency(db, current_user, data["agency_id"])
        data["agency_id"] = agency.id
    target_agency = agency.id if agency else obj.agency_id

    # `channel` must not reach the blind setattr below unvalidated. Re-check it
    # whenever EITHER side moves — switching a credential to a GDS-only agency
    # has to invalidate an LCC channel just as surely as changing the channel does.
    if "channel" in data or agency is not None:
        agency = agency or await _validate_agency(db, current_user, obj.agency_id)
        data["channel"] = _validate_channel(agency, data.get("channel", obj.channel))
    channel = data.get("channel", obj.channel)

    if "vendor_id" in data:
        data["vendor_id"] = await _validate_vendor(db, data["vendor_id"])

    # If the agency or channel changed but the entity was not re-specified,
    # re-check that the existing entity still fits both.
    if "entity_id" in data:
        data["entity_id"] = await _validate_entity(db, current_user, target_agency, data["entity_id"], channel)
    elif obj.entity_id is not None and ("agency_id" in data or "channel" in data):
        await _validate_entity(db, current_user, target_agency, obj.entity_id, channel)

    if "login_id" in data:
        new_login = (data["login_id"] or "").strip()
        if not new_login:
            label = "Mirror ID" if channel == "GDS" else "Login ID / Airline ID"
            raise HTTPException(status_code=400, detail=f"{label} cannot be empty.")
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
