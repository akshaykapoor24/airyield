from datetime import datetime
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import StreamingResponse
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, is_platform_admin, require_role
from app.models.user import User, UserRole
from app.models.airport import (
    Airport, CATEGORIZATION_GROUPS, split_categorization, join_categorization,
)
from app.models.airport_approval import AirportApproval
from app.schemas.airport import (
    AirportCreate, AirportUpdate, AirportRead,
    AirportApprovalRead, AirportApprovalEdit, ApprovalAction, BulkUploadResult,
)
from app.services.master_approval_edit import apply_admin_edit, AIRPORT_FIELDS

router = APIRouter()

PLATFORM  = UserRole.PLATFORM_ADMIN
SUBMITTERS = (
    UserRole.PLATFORM_ADMIN,
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.OPERATIONS_USER,
    UserRole.FINANCE_USER,
    UserRole.APPROVER,
)


# ── helpers ────────────────────────────────────────────────────────────────


def _categorization_filter(value: str):
    """Match one base group against the slash-joined stored value.

    An airport in "MEAI/SAARC" must be found when filtering by either MEAI or
    SAARC, so an equality test is not enough. Patterns anchor on "/" so that
    filtering by "MEAI" cannot accidentally match an unrelated longer name.
    """
    return or_(
        Airport.categorization == value,
        Airport.categorization.ilike(f"{value}/%"),
        Airport.categorization.ilike(f"%/{value}"),
        Airport.categorization.ilike(f"%/{value}/%"),
    )


async def _next_apt_id(db: AsyncSession) -> str:
    result = await db.execute(
        select(Airport.apt_id).where(Airport.apt_id.isnot(None))
        .order_by(Airport.id.desc()).limit(1)
    )
    last = result.scalar_one_or_none()
    if not last:
        return "APT-0001"
    try:
        num = int(last.split("-")[1]) + 1
    except (IndexError, ValueError):
        num = 1
    return f"APT-{num:04d}"


async def _direct_insert(db: AsyncSession, data: dict, user: User) -> Airport:
    apt_id = await _next_apt_id(db)
    airport = Airport(
        apt_id=apt_id,
        iata_code=data["iata_code"].strip().upper(),
        country=data["country"],
        categorization=data.get("categorization"),
        continent=data.get("continent"),
        city_airport_name=data["city_airport_name"],
        created_by_id=user.id,
    )
    db.add(airport)
    await db.commit()
    await db.refresh(airport)
    return airport


# ── list airports (all authenticated users) ────────────────────────────────

@router.get("/count")
async def count_airports(
    q: Optional[str] = None,
    categorization: Optional[str] = None,
    continent: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(func.count()).select_from(Airport).where(Airport.is_active == True)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Airport.iata_code.ilike(term),
            Airport.country.ilike(term),
            Airport.categorization.ilike(term),
            Airport.continent.ilike(term),
            Airport.city_airport_name.ilike(term),
        ))
    if categorization:
        stmt = stmt.where(_categorization_filter(categorization))
    if continent:
        stmt = stmt.where(Airport.continent == continent)
    result = await db.execute(stmt)
    return {"total": result.scalar()}


@router.get("/", response_model=list[AirportRead])
async def list_airports(
    skip: int = 0, limit: int = 100,
    q: Optional[str] = None,
    categorization: Optional[str] = None,
    continent: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Airport).where(Airport.is_active == True)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Airport.iata_code.ilike(term),
            Airport.country.ilike(term),
            Airport.categorization.ilike(term),
            Airport.continent.ilike(term),
            Airport.city_airport_name.ilike(term),
        ))
    if categorization:
        stmt = stmt.where(_categorization_filter(categorization))
    if continent:
        stmt = stmt.where(Airport.continent == continent)
    stmt = stmt.order_by(Airport.apt_id).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


# ── create airport (manual) ────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_airport(
    payload: AirportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    request_type = (payload.request_type or "new").lower()

    if request_type == "update":
        if not payload.target_id:
            raise HTTPException(status_code=400, detail="target_id is required for update requests.")
        target_check = await db.execute(select(Airport).where(Airport.id == payload.target_id))
        if not target_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Airport with id {payload.target_id} not found.")

        if is_platform_admin(current_user):
            target_airport = (await db.execute(select(Airport).where(Airport.id == payload.target_id))).scalar_one()
            target_airport.iata_code = payload.iata_code.strip().upper()
            target_airport.country = payload.country
            target_airport.categorization = payload.categorization
            target_airport.continent = payload.continent
            target_airport.city_airport_name = payload.city_airport_name
            await db.commit()
            await db.refresh(target_airport)
            return {"status": "updated", "airport": AirportRead.model_validate(target_airport)}

        approval = AirportApproval(
            iata_code=payload.iata_code,
            country=payload.country,
            categorization=payload.categorization,
            continent=payload.continent,
            city_airport_name=payload.city_airport_name,
            submitted_by_id=current_user.id,
            tenant_id=current_user.tenant_id,
            status="pending",
            request_type="update",
            target_airport_id=payload.target_id,
        )
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        return {"status": "pending_approval", "approval_id": approval.id}

    # ── request_type == "new" (default) ────────────────────────────────────
    existing = await db.execute(select(Airport).where(Airport.iata_code == payload.iata_code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Airport with IATA '{payload.iata_code}' already exists.")

    if is_platform_admin(current_user):
        airport = await _direct_insert(db, payload.model_dump(), current_user)
        return {"status": "added", "airport": AirportRead.model_validate(airport)}

    pending = await db.execute(
        select(AirportApproval).where(
            AirportApproval.iata_code == payload.iata_code,
            AirportApproval.status == "pending",
        )
    )
    if pending.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Airport '{payload.iata_code}' is already pending approval.")

    approval = AirportApproval(
        iata_code=payload.iata_code,
        country=payload.country,
        categorization=payload.categorization,
        continent=payload.continent,
        city_airport_name=payload.city_airport_name,
        submitted_by_id=current_user.id,
        tenant_id=current_user.tenant_id,
        status="pending",
        request_type="new",
        target_airport_id=None,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return {"status": "pending_approval", "approval_id": approval.id}


# ── bulk XLS upload ────────────────────────────────────────────────────────

@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_airports(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    content = await file.read()
    filename = (file.filename or "").lower()

    required = {"IATA_CODE", "COUNTRY", "CITY_AIRPORT_NAME"}

    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        # normalise column names: strip, upper, spaces/slashes → underscore
        df.columns = [
            c.strip().upper().replace(" ", "_").replace("/", "_").replace("-", "_")
            for c in df.columns
        ]
        df.dropna(how="all", inplace=True)
        return df

    try:
        df = None
        used_header_row = 0
        last_missing: set[str] | None = None

        # Some of your XLS/XLSX exports have a "title/meta" row above the header.
        # We try a few header offsets so we can still find the required columns.
        for header_row in (0, 1, 2):
            try:
                if filename.endswith(".xls"):
                    df_try = pd.read_excel(BytesIO(content), dtype=str, header=header_row)
                else:
                    df_try = pd.read_excel(
                        BytesIO(content),
                        dtype=str,
                        engine="openpyxl",
                        header=header_row,
                    )

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
            # Give a useful error message showing what columns we detected last.
            if last_missing is None:
                detail = (
                    "Missing required columns: IATA_CODE, COUNTRY, CITY_AIRPORT_NAME. "
                    "Your Excel header may not be on the first row."
                )
            else:
                detail = (
                    f"Missing required columns: {sorted(last_missing)}. "
                    "Your Excel header may be on a different row (e.g. a title/meta row is present). "
                    "Required: IATA_CODE, COUNTRY, CITY_AIRPORT_NAME  |  Optional: CATEGORIZATION, CONTINENT"
                )
            raise HTTPException(
                status_code=400,
                detail=detail,
            )
    except Exception as e:
        # If we got here, we likely couldn't read the spreadsheet at all.
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=400,
            detail=f"Cannot parse file: {e}. Make sure it is a valid .xlsx or .xls file.",
        )

    total = len(df)
    success = 0
    errors: list[str] = []

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2  # 1-based + header_row + data offset
        apt_id = str(row.get("APT_ID", "") or "").strip()
        apt_prefix = f" (APT_ID {apt_id})" if apt_id else ""
        iata = str(row.get("IATA_CODE", "") or "").strip().upper()
        country = str(row.get("COUNTRY", "") or "").strip()
        city_airport_name = str(row.get("CITY_AIRPORT_NAME", "") or "").strip()
        # A spreadsheet cell may already hold a combination ("MEAI/SAARC") or a
        # comma-separated list — normalise both to the canonical joined form.
        raw_cat = str(row.get("CATEGORIZATION", "") or "").strip()
        categorization = join_categorization(
            [g for part in raw_cat.split(",") for g in split_categorization(part)]
        ) if raw_cat else None
        continent = str(row.get("CONTINENT", "") or "").strip() or None

        if not iata or not country or not city_airport_name:
            errors.append(f"Row {row_num}{apt_prefix}: IATA_CODE, COUNTRY and CITY_AIRPORT_NAME are required.")
            continue
        if len(iata) != 3:
            errors.append(f"Row {row_num}{apt_prefix}: IATA code '{iata}' must be exactly 3 characters.")
            continue

        # duplicate check
        existing = await db.execute(select(Airport).where(Airport.iata_code == iata))
        if existing.scalar_one_or_none():
            errors.append(f"Row {row_num}{apt_prefix}: Airport '{iata}' already exists — skipped.")
            continue

        data = {"iata_code": iata, "country": country, "city_airport_name": city_airport_name,
                "categorization": categorization, "continent": continent}

        try:
            if is_platform_admin(current_user):
                await _direct_insert(db, data, current_user)
            else:
                pending = await db.execute(
                    select(AirportApproval).where(
                        AirportApproval.iata_code == iata,
                        AirportApproval.status == "pending",
                    )
                )
                if pending.scalar_one_or_none():
                    errors.append(f"Row {row_num}{apt_prefix}: Airport '{iata}' already pending approval — skipped.")
                    continue
                approval = AirportApproval(
                    iata_code=iata, country=country, categorization=categorization,
                    continent=continent, city_airport_name=city_airport_name,
                    submitted_by_id=current_user.id, tenant_id=current_user.tenant_id,
                    status="pending",
                )
                db.add(approval)
                await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {row_num}{apt_prefix}: {e}")

    failed = total - success
    return BulkUploadResult(total=total, success=success, failed=failed, errors=errors)


@router.get("/template")
async def download_airport_template():
    # Generates template on demand so the frontend download never depends on a static file.
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Airport Template"

    # APT_ID is included for Excel row identification, but it is ignored by bulk upload.
    headers = [
        "APT_ID",
        "IATA_CODE",
        "COUNTRY",
        "CATEGORIZATION",
        "CONTINENT",
        "CITY_AIRPORT_NAME",
    ]
    ws.append(headers)

    # Add a single empty row to make it obvious what to fill in.
    ws.append(["", "", "", "", "", ""])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="airport_template.xlsx"'},
    )


# ── get pending approvals ──────────────────────────────────────────────────

@router.get("/approvals", response_model=list[AirportApprovalRead])
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    pending_filter = func.lower(AirportApproval.status) == "pending"
    if is_platform_admin(current_user):
        # platform admin sees all pending
        result = await db.execute(
            select(AirportApproval)
            .options(
                selectinload(AirportApproval.submitted_by),
                # edited_by is set by id, so without this it lazy-loads during
                # serialisation and raises MissingGreenlet — but only once a row
                # has actually been edited.
                selectinload(AirportApproval.edited_by),
            )
            .where(pending_filter)
            .order_by(AirportApproval.submitted_at.desc())
        )
    else:
        # super_admin sees their own submissions (all statuses)
        result = await db.execute(
            select(AirportApproval)
            .options(
                selectinload(AirportApproval.submitted_by),
                # edited_by is set by id, so without this it lazy-loads during
                # serialisation and raises MissingGreenlet — but only once a row
                # has actually been edited.
                selectinload(AirportApproval.edited_by),
            )
            .where(AirportApproval.submitted_by_id == current_user.id)
            .order_by(AirportApproval.submitted_at.desc())
        )
    return result.scalars().all()


# ── approve ────────────────────────────────────────────────────────────────

@router.patch("/approvals/{approval_id}/approve", response_model=AirportRead)
async def approve_airport(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    result = await db.execute(select(AirportApproval).where(AirportApproval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if (approval.status or "").lower() != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{approval.status}'.")

    request_type = (getattr(approval, "request_type", None) or "new").lower()

    if request_type == "update":
        target_result = await db.execute(
            select(Airport).where(Airport.id == approval.target_airport_id)
        )
        target = target_result.scalar_one_or_none()
        if not target:
            approval.status = "rejected"
            approval.rejection_reason = "Target airport no longer exists."
            approval.reviewed_by_id = current_user.id
            approval.reviewed_at = datetime.utcnow()
            await db.commit()
            raise HTTPException(status_code=409, detail="Target airport no longer exists; request auto-rejected.")

        target.iata_code = approval.iata_code
        target.country = approval.country
        target.categorization = approval.categorization
        target.continent = approval.continent
        target.city_airport_name = approval.city_airport_name

        approval.status = "approved"
        approval.reviewed_by_id = current_user.id
        approval.reviewed_at = datetime.utcnow()

        await db.commit()
        await db.refresh(target)
        return target

    # ── request_type == "new" ───────────────────────────────────────────────
    existing = await db.execute(select(Airport).where(Airport.iata_code == approval.iata_code))
    if existing.scalar_one_or_none():
        approval.status = "rejected"
        approval.rejection_reason = "Airport was already added directly."
        approval.reviewed_by_id = current_user.id
        approval.reviewed_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(status_code=409, detail=f"Airport '{approval.iata_code}' was already added.")

    apt_id = await _next_apt_id(db)
    airport = Airport(
        apt_id=apt_id,
        iata_code=approval.iata_code,
        country=approval.country,
        categorization=approval.categorization,
        continent=approval.continent,
        city_airport_name=approval.city_airport_name,
        created_by_id=approval.submitted_by_id,
    )
    db.add(airport)

    approval.status = "approved"
    approval.reviewed_by_id = current_user.id
    approval.reviewed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(airport)
    return airport


# ── reject ─────────────────────────────────────────────────────────────────

@router.patch("/approvals/{approval_id}/reject")
async def reject_airport(
    approval_id: int,
    payload: ApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    result = await db.execute(select(AirportApproval).where(AirportApproval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if (approval.status or "").lower() != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{approval.status}'.")

    approval.status = "rejected"
    approval.rejection_reason = payload.rejection_reason
    approval.reviewed_by_id = current_user.id
    approval.reviewed_at = datetime.utcnow()
    await db.commit()
    return {"status": "rejected"}


# ── platform admin edits a pending request ─────────────────────────────────
# Declared here, inside the approvals block: FastAPI matches in declaration
# order, so below "/{airport_id}" this path would bind there and 422.

@router.patch("/approvals/{approval_id}", response_model=AirportApprovalRead)
async def edit_airport_approval(
    approval_id: int,
    payload: AirportApprovalEdit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    """Correct a pending request before approving it.

    Approve already copies this row onto the master, so editing the row in place
    is all that is needed for the corrected values to land — this endpoint only
    has to record what the submitter originally sent so they can see the change.
    """
    result = await db.execute(
        select(AirportApproval).where(AirportApproval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if (approval.status or "").lower() != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{approval.status}'.")

    changes = payload.model_dump(exclude_unset=True)

    if (approval.request_type or "new").lower() == "update":
        # Editing a request whose target was deleted can only produce a row that
        # approve will auto-reject, so refuse rather than waste the admin's work.
        target = await db.execute(
            select(Airport.id).where(Airport.id == approval.target_airport_id)
        )
        if not target.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="The airport this request targets no longer exists; it can only be rejected.",
            )

    # iata_code is unique on the master. Approve auto-rejects a "new" request
    # that collides — destroying the submission — and for an "update" it does not
    # check at all and would raise a raw IntegrityError. Catch it here, while the
    # admin can still fix the value.
    new_iata = changes.get("iata_code")
    if new_iata and new_iata != approval.iata_code:
        clash = await db.execute(
            select(Airport.id).where(
                Airport.iata_code == new_iata,
                Airport.id != (approval.target_airport_id or -1),
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Airport '{new_iata}' already exists in the master.",
            )

    try:
        apply_admin_edit(
            approval,
            fields=AIRPORT_FIELDS,
            changes=changes,
            editor_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await db.commit()

    # edited_by was set by id, so the relationship is not loaded; re-select with
    # both eager loads rather than lazy-loading them during serialisation.
    fresh = await db.execute(
        select(AirportApproval)
        .options(
            selectinload(AirportApproval.submitted_by),
            selectinload(AirportApproval.edited_by),
        )
        .where(AirportApproval.id == approval_id)
    )
    return fresh.scalar_one()


# ── distinct option lists for deal form dropdowns ─────────────────────────

@router.get("/options")
async def get_airport_options(
    continent: Optional[str] = None,
    country:   Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return distinct values for deal-form dropdowns.

    ?continent=Asia  → { countries: [...] }
    ?country=India   → { airports: [...] }  (IATA codes)
    (no params)      → { continents: [...], country_groups: [...] }
    """
    from sqlalchemy import distinct as sql_distinct

    if continent:
        res = await db.execute(
            select(sql_distinct(Airport.country))
            .where(Airport.continent == continent, Airport.is_active == True)
        )
        return {"countries": sorted(r[0] for r in res.all())}

    if country:
        res = await db.execute(
            select(Airport.iata_code)
            .where(Airport.country == country, Airport.is_active == True)
            .order_by(Airport.iata_code)
        )
        return {"airports": [r[0] for r in res.all()]}

    cont_q = await db.execute(
        select(sql_distinct(Airport.continent))
        .where(Airport.continent.isnot(None), Airport.is_active == True)
    )
    cat_q = await db.execute(
        select(sql_distinct(Airport.categorization))
        .where(Airport.categorization.isnot(None), Airport.is_active == True)
    )
    # Each record may store a combination like "MEAI/SAARC" meaning it belongs to
    # both. Expand every stored value into its base groups and return only those
    # canonical names. split_categorization keeps "GCC/MIDDLE EAST" whole.
    present = {g.upper() for r in cat_q.all() for g in split_categorization(r[0])}
    expanded = [
        c for c in CATEGORIZATION_GROUPS if c.upper() in present
    ] or list(CATEGORIZATION_GROUPS)  # fall back to full list when DB is empty

    return {
        "continents":    sorted(r[0] for r in cont_q.all()),
        "country_groups": expanded,
    }


# ── get single airport ─────────────────────────────────────────────────────

@router.get("/{airport_id}", response_model=AirportRead)
async def get_airport(
    airport_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Airport).where(Airport.id == airport_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Airport not found")
    return obj


# ── update airport ─────────────────────────────────────────────────────────

@router.patch("/{airport_id}", response_model=AirportRead)
async def update_airport(
    airport_id: int,
    payload: AirportUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    result = await db.execute(select(Airport).where(Airport.id == airport_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Airport not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    return obj


# ── delete airport ─────────────────────────────────────────────────────────

@router.delete("/{airport_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_airport(
    airport_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    result = await db.execute(select(Airport).where(Airport.id == airport_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Airport not found")
    await db.delete(obj)
    await db.commit()
