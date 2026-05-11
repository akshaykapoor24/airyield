from datetime import datetime
from io import BytesIO

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import Optional

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.airline import Airline
from app.models.airline_approval import AirlineApproval
from app.models.user import User, UserRole
from app.schemas.airline import (
    AirlineRead, AirlineCreate, AirlineUpdate, AirlineBulkUploadResult,
    AirlineApprovalRead, AirlineApprovalAction,
)

router = APIRouter()
PLATFORM = UserRole.PLATFORM_ADMIN
SUBMITTERS = (
    UserRole.PLATFORM_ADMIN,
    UserRole.SUPER_ADMIN,
    UserRole.COMPANY_ADMIN,
    UserRole.OPERATIONS_USER,
    UserRole.FINANCE_USER,
    UserRole.APPROVER,
)


def _is_platform_admin(user: User) -> bool:
    role = user.role
    if isinstance(role, UserRole):
        return role == PLATFORM
    role_str = str(role).lower()
    return role_str in {PLATFORM.value.lower(), PLATFORM.name.lower()}


@router.get("/count")
async def count_airlines(
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(func.count()).select_from(Airline)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Airline.name.ilike(term),
            Airline.iata_code.ilike(term),
            Airline.icao_code.ilike(term),
        ))
    result = await db.execute(q)
    return {"total": result.scalar()}


@router.get("/", response_model=list[AirlineRead])
async def list_airlines(
    skip: int = 0, limit: int = 100,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Airline)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Airline.name.ilike(term),
            Airline.iata_code.ilike(term),
            Airline.icao_code.ilike(term),
        ))
    q = q.order_by(Airline.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_airline(payload: AirlineCreate, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(require_role(*SUBMITTERS))):
    from app import crud
    iata = payload.iata_code.strip().upper()
    request_type = (payload.request_type or "new").lower()

    if request_type == "update":
        if not payload.target_id:
            raise HTTPException(status_code=400, detail="target_id is required for update requests.")
        target_check = await db.execute(select(Airline).where(Airline.id == payload.target_id))
        if not target_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Airline with id {payload.target_id} not found.")

        if _is_platform_admin(current_user):
            target_airline = (await db.execute(select(Airline).where(Airline.id == payload.target_id))).scalar_one()
            target_airline.name = payload.name.strip()
            target_airline.iata_code = iata
            target_airline.icao_code = payload.icao_code.strip().upper() if payload.icao_code else None
            await db.commit()
            await db.refresh(target_airline)
            return {"status": "updated", "airline": AirlineRead.model_validate(target_airline)}

        approval = AirlineApproval(
            name=payload.name.strip(),
            iata_code=iata,
            icao_code=payload.icao_code.strip().upper() if payload.icao_code else None,
            submitted_by_id=current_user.id,
            tenant_id=current_user.tenant_id,
            status="pending",
            request_type="update",
            target_airline_id=payload.target_id,
        )
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        return {"status": "pending_approval", "approval_id": approval.id}

    # ── request_type == "new" (default) ────────────────────────────────────
    existing = await db.execute(select(Airline).where(Airline.iata_code == iata))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Airline with code '{payload.iata_code}' already exists.")

    if _is_platform_admin(current_user):
        cleaned_payload = AirlineCreate(
            name=payload.name.strip(),
            iata_code=iata,
            icao_code=payload.icao_code.strip().upper() if payload.icao_code else None,
            logo_url=payload.logo_url,
        )
        airline = await crud.airline.create(db, obj_in=cleaned_payload)
        return {"status": "added", "airline": AirlineRead.model_validate(airline)}

    pending = await db.execute(
        select(AirlineApproval).where(
            AirlineApproval.iata_code == iata,
            func.lower(AirlineApproval.status) == "pending",
        )
    )
    if pending.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Airline '{iata}' is already pending approval.")

    approval = AirlineApproval(
        name=payload.name.strip(),
        iata_code=iata,
        icao_code=payload.icao_code.strip().upper() if payload.icao_code else None,
        submitted_by_id=current_user.id,
        tenant_id=current_user.tenant_id,
        status="pending",
        request_type="new",
        target_airline_id=None,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return {"status": "pending_approval", "approval_id": approval.id}


@router.post("/bulk-upload", response_model=AirlineBulkUploadResult)
async def bulk_upload_airlines(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    from app import crud

    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"CODE", "AIRLINE"}

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
        last_missing: set[str] | None = None

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
                "Missing required columns: CODE, AIRLINE. Your Excel header may not be on the first row."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. "
                "Your Excel header may be on a different row (e.g. a title/meta row is present). "
                "Required: CODE, AIRLINE  |  Optional: IATA_NUMERIC_CODE, AIRLINE_ID, DUPLICATE_FLAG"
            )
            raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
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
        row_num = i + used_header_row + 2
        airline_id = str(row.get("AIRLINE_ID", "") or "").strip()
        row_prefix = f"Row {row_num} (AIRLINE_ID {airline_id})" if airline_id else f"Row {row_num}"
        code = str(row.get("CODE", "") or "").strip().upper()
        airline_name = str(row.get("AIRLINE", "") or "").strip()
        # Your XLS exports include "IATA_NUMERIC_CODE" (e.g. 098). Your DB currently stores this in `icao_code`.
        iata_numeric_raw = str(row.get("IATA_NUMERIC_CODE", "") or "").strip()
        iata_numeric_clean = iata_numeric_raw.replace(".0", "").strip()
        iata_numeric_clean = iata_numeric_clean.zfill(3) if iata_numeric_clean and iata_numeric_clean.isdigit() else iata_numeric_clean
        iata_numeric_value = iata_numeric_clean or None

        if not code or not airline_name:
            errors.append(f"{row_prefix}: CODE and AIRLINE are required.")
            continue
        if len(code) < 2 or len(code) > 3:
            errors.append(f"{row_prefix}: Airline code '{code}' must be 2 or 3 characters.")
            continue

        existing = await db.execute(select(Airline).where(Airline.iata_code == code))
        if existing.scalar_one_or_none():
            errors.append(f"{row_prefix}: Airline '{code}' already exists — skipped.")
            continue

        try:
            if _is_platform_admin(current_user):
                await crud.airline.create(
                    db,
                    obj_in={"name": airline_name, "iata_code": code, "icao_code": iata_numeric_value, "logo_url": None},
                )
            else:
                pending = await db.execute(
                    select(AirlineApproval).where(
                        AirlineApproval.iata_code == code,
                        func.lower(AirlineApproval.status) == "pending",
                    )
                )
                if pending.scalar_one_or_none():
                    errors.append(f"{row_prefix}: Airline '{code}' already pending approval — skipped.")
                    continue
                approval = AirlineApproval(
                    name=airline_name,
                    iata_code=code,
                    icao_code=iata_numeric_value,
                    submitted_by_id=current_user.id,
                    tenant_id=current_user.tenant_id,
                    status="pending",
                )
                db.add(approval)
                await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"{row_prefix}: {e}")

    failed = total - success
    return AirlineBulkUploadResult(total=total, success=success, failed=failed, errors=errors)


@router.get("/template")
async def download_airline_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Airline Template"

    headers = ["AIRLINE_ID", "Code", "IATA_NUMERIC_CODE", "Airline", "DUPLICATE_FLAG"]
    ws.append(headers)
    ws.append(["", "", "", "", ""])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="airline_template.xlsx"'},
    )


@router.get("/approvals", response_model=list[AirlineApprovalRead])
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    pending_filter = func.lower(AirlineApproval.status) == "pending"
    if _is_platform_admin(current_user):
        result = await db.execute(
            select(AirlineApproval)
            .options(selectinload(AirlineApproval.submitted_by))
            .where(pending_filter)
            .order_by(AirlineApproval.submitted_at.desc())
        )
    else:
        result = await db.execute(
            select(AirlineApproval)
            .options(selectinload(AirlineApproval.submitted_by))
            .where(AirlineApproval.submitted_by_id == current_user.id)
            .order_by(AirlineApproval.submitted_at.desc())
        )
    return result.scalars().all()


@router.patch("/approvals/{approval_id}/approve", response_model=AirlineRead)
async def approve_airline(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    from app import crud
    result = await db.execute(select(AirlineApproval).where(AirlineApproval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if (approval.status or "").lower() != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{approval.status}'.")

    request_type = (getattr(approval, "request_type", None) or "new").lower()

    if request_type == "update":
        target_result = await db.execute(select(Airline).where(Airline.id == approval.target_airline_id))
        target = target_result.scalar_one_or_none()
        if not target:
            approval.status = "rejected"
            approval.rejection_reason = "Target airline no longer exists."
            approval.reviewed_by_id = current_user.id
            approval.reviewed_at = datetime.utcnow()
            await db.commit()
            raise HTTPException(status_code=409, detail="Target airline no longer exists; request auto-rejected.")

        target.name = approval.name
        target.iata_code = approval.iata_code
        target.icao_code = approval.icao_code

        approval.status = "approved"
        approval.reviewed_by_id = current_user.id
        approval.reviewed_at = datetime.utcnow()

        await db.commit()
        await db.refresh(target)
        return target

    # ── request_type == "new" ───────────────────────────────────────────────
    existing = await db.execute(select(Airline).where(Airline.iata_code == approval.iata_code))
    if existing.scalar_one_or_none():
        approval.status = "rejected"
        approval.rejection_reason = "Airline was already added directly."
        approval.reviewed_by_id = current_user.id
        approval.reviewed_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(status_code=409, detail=f"Airline '{approval.iata_code}' was already added.")

    airline = await crud.airline.create(
        db,
        obj_in={
            "name": approval.name,
            "iata_code": approval.iata_code,
            "icao_code": approval.icao_code,
            "logo_url": None,
        },
    )
    approval.status = "approved"
    approval.reviewed_by_id = current_user.id
    approval.reviewed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(airline)
    return airline


@router.patch("/approvals/{approval_id}/reject")
async def reject_airline(
    approval_id: int,
    payload: AirlineApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    result = await db.execute(select(AirlineApproval).where(AirlineApproval.id == approval_id))
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


@router.get("/{airline_id}", response_model=AirlineRead)
async def get_airline(airline_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    from app import crud
    obj = await crud.airline.get(db, id=airline_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Airline not found")
    return obj


@router.patch("/{airline_id}", response_model=AirlineRead)
async def update_airline(airline_id: int, payload: AirlineUpdate, db: AsyncSession = Depends(get_db),
                         _: User = Depends(require_role(UserRole.PLATFORM_ADMIN))):
    from app import crud
    obj = await crud.airline.get(db, id=airline_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Airline not found")
    update_data = payload.model_dump(exclude_unset=True)
    if "iata_code" in update_data and update_data["iata_code"]:
        next_code = update_data["iata_code"].strip().upper()
        existing = await db.execute(
            select(Airline).where(Airline.iata_code == next_code, Airline.id != airline_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Airline with code '{next_code}' already exists.")
        update_data["iata_code"] = next_code
    if "icao_code" in update_data:
        update_data["icao_code"] = update_data["icao_code"].strip().upper() if update_data["icao_code"] else None
    if "name" in update_data and update_data["name"] is not None:
        update_data["name"] = update_data["name"].strip()
    payload = AirlineUpdate(**update_data)
    return await crud.airline.update(db, db_obj=obj, obj_in=payload)


@router.delete("/{airline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_airline(airline_id: int, db: AsyncSession = Depends(get_db),
                         _: User = Depends(require_role(UserRole.PLATFORM_ADMIN))):
    from app import crud
    await crud.airline.remove(db, id=airline_id)
