from io import BytesIO
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.airline_class_master import AirlineClassMaster
from app.models.class_approval import ClassApproval
from app.models.user import User, UserRole
from app.schemas.airline_class_master import (
    AirlineClassMasterCreate,
    AirlineClassMasterRead,
    AirlineClassMasterUpdate,
    BulkUploadResult,
    ClassApprovalRead,
    ClassApprovalAction,
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


def _normalize_cell(v: object) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _normalize_value_payload(data: dict) -> dict:
    # Store normalized strings to make duplicate checks reliable.
    airline_name = _normalize_cell(data.get("airline_name")).upper()
    class_type = _normalize_cell(data.get("class_type")).upper()
    class_code = _normalize_cell(data.get("class_code")).upper()
    airline_type = _normalize_cell(data.get("airline_type")).upper() or None
    class_note = _normalize_cell(data.get("class_note")).strip() or None

    return {
        "airline_name": airline_name,
        "class_type": class_type,
        "class_code": class_code,
        "airline_type": airline_type,
        "class_note": class_note,
        "is_active": data.get("is_active", True),
    }


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [
        str(c).strip().upper().replace(" ", "_").replace("/", "_").replace("-", "_")
        for c in df.columns
    ]
    df.dropna(how="all", inplace=True)
    return df


def _is_platform_admin(user: User) -> bool:
    role = user.role
    if isinstance(role, UserRole):
        return role == PLATFORM
    role_str = str(role).lower()
    return role_str in {PLATFORM.value.lower(), PLATFORM.name.lower()}


@router.get("/template")
async def download_airline_class_template():
    # Generates template on demand (no static file dependency).
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Airline Class Template"

    headers = ["ROW_ID", "AIRLINE_NAME", "CLASS_TYPE", "CLASS_CODE", "AIRLINE_TYPE", "CLASS_NOTE"]
    ws.append(headers)
    ws.append(["", "", "", "", "", ""])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="airline_class_template.xlsx"'},
    )


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_airline_classes(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    content = await file.read()
    filename = (file.filename or "").lower()

    required = {"AIRLINE_NAME", "CLASS_TYPE", "CLASS_CODE"}

    try:
        df = None
        used_header_row = 0
        last_missing: set[str] | None = None

        # Some Excel exports include a title/meta row above the real headers.
        for header_row in (0, 1, 2, 3):
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
            if last_missing is None:
                detail = (
                    "Missing required columns: AIRLINE_NAME, CLASS_TYPE, CLASS_CODE. "
                    "Your Excel header may not be on the first row."
                )
            else:
                detail = (
                    f"Missing required columns: {sorted(last_missing)}. "
                    "Your Excel header may be on a different row (e.g. a title/meta row is present). "
                    "Required: AIRLINE_NAME, CLASS_TYPE, CLASS_CODE"
                )
            raise HTTPException(status_code=400, detail=detail)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot parse file: {e}. Make sure it is a valid .xlsx or .xls file.",
        )

    total = len(df)
    success = 0
    errors: list[str] = []

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        airline_name = _normalize_cell(row.get("AIRLINE_NAME")).upper()
        class_type = _normalize_cell(row.get("CLASS_TYPE")).upper()
        class_code = _normalize_cell(row.get("CLASS_CODE")).upper()
        airline_type = _normalize_cell(row.get("AIRLINE_TYPE")).upper() or None
        class_note = _normalize_cell(row.get("CLASS_NOTE")).strip() or None

        if not airline_name or not class_type or not class_code:
            errors.append(f"Row {row_num}: AIRLINE_NAME, CLASS_TYPE and CLASS_CODE are required.")
            continue

        # Duplicate check: (airline_name, class_type, class_code)
        existing = await db.execute(
            select(AirlineClassMaster).where(
                AirlineClassMaster.airline_name == airline_name,
                AirlineClassMaster.class_type == class_type,
                AirlineClassMaster.class_code == class_code,
            )
        )
        if existing.scalar_one_or_none():
            errors.append(f"Row {row_num}: Class already exists for this airline — skipped.")
            continue

        payload = {
            "airline_name": airline_name,
            "class_type": class_type,
            "class_code": class_code,
            "airline_type": airline_type,
            "class_note": class_note,
            "is_active": True,
        }
        try:
            if _is_platform_admin(current_user):
                obj = AirlineClassMaster(**payload)
                db.add(obj)
                await db.commit()
            else:
                pending = await db.execute(
                    select(ClassApproval).where(
                        ClassApproval.airline_name == airline_name,
                        ClassApproval.class_type == class_type,
                        ClassApproval.class_code == class_code,
                        func.lower(ClassApproval.status) == "pending",
                    )
                )
                if pending.scalar_one_or_none():
                    errors.append(f"Row {row_num}: Class already pending approval — skipped.")
                    continue
                approval = ClassApproval(
                    airline_name=airline_name,
                    class_type=class_type,
                    class_code=class_code,
                    airline_type=airline_type,
                    class_note=class_note,
                    submitted_by_id=current_user.id,
                    tenant_id=current_user.tenant_id,
                    status="pending",
                )
                db.add(approval)
                await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e}")

    failed = total - success
    return BulkUploadResult(total=total, success=success, failed=failed, errors=errors)


@router.get("/airlines-by-type/{airline_type}")
async def get_airlines_by_type(
    airline_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AirlineClassMaster.airline_name)
        .where(func.upper(AirlineClassMaster.airline_type) == airline_type.upper())
        .distinct()
        .order_by(AirlineClassMaster.airline_name)
    )
    return [row[0] for row in result.all()]


@router.get("/count")
async def count_airline_classes(
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(func.count()).select_from(AirlineClassMaster)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            AirlineClassMaster.airline_name.ilike(term),
            AirlineClassMaster.class_type.ilike(term),
            AirlineClassMaster.class_code.ilike(term),
            AirlineClassMaster.airline_type.ilike(term),
            AirlineClassMaster.class_note.ilike(term),
        ))
    result = await db.execute(stmt)
    return {"total": result.scalar()}


@router.get("/", response_model=list[AirlineClassMasterRead])
async def list_airline_classes(
    skip: int = 0,
    limit: int = 100,
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(AirlineClassMaster)
    if q and q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            AirlineClassMaster.airline_name.ilike(term),
            AirlineClassMaster.class_type.ilike(term),
            AirlineClassMaster.class_code.ilike(term),
            AirlineClassMaster.airline_type.ilike(term),
            AirlineClassMaster.class_note.ilike(term),
        ))
    stmt = stmt.order_by(AirlineClassMaster.airline_name, AirlineClassMaster.class_code).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_airline_class(
    payload: AirlineClassMasterCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    normalized = _normalize_value_payload(payload.model_dump())
    request_type = (payload.request_type or "new").lower()

    if request_type == "update":
        if not payload.target_id:
            raise HTTPException(status_code=400, detail="target_id is required for update requests.")
        target_check = await db.execute(select(AirlineClassMaster).where(AirlineClassMaster.id == payload.target_id))
        if not target_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Class with id {payload.target_id} not found.")

        if _is_platform_admin(current_user):
            target_class = (
                await db.execute(select(AirlineClassMaster).where(AirlineClassMaster.id == payload.target_id))
            ).scalar_one()
            target_class.airline_name = normalized["airline_name"]
            target_class.class_type = normalized["class_type"]
            target_class.class_code = normalized["class_code"]
            target_class.airline_type = normalized["airline_type"]
            target_class.class_note = normalized["class_note"]
            await db.commit()
            await db.refresh(target_class)
            return {"status": "updated", "class_row": AirlineClassMasterRead.model_validate(target_class)}

        approval = ClassApproval(
            airline_name=normalized["airline_name"],
            class_type=normalized["class_type"],
            class_code=normalized["class_code"],
            airline_type=normalized["airline_type"],
            class_note=normalized["class_note"],
            submitted_by_id=current_user.id,
            tenant_id=current_user.tenant_id,
            status="pending",
            request_type="update",
            target_class_id=payload.target_id,
        )
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        return {"status": "pending_approval", "approval_id": approval.id}

    # ── request_type == "new" (default) ────────────────────────────────────
    existing = await db.execute(
        select(AirlineClassMaster).where(
            AirlineClassMaster.airline_name == normalized["airline_name"],
            AirlineClassMaster.class_type == normalized["class_type"],
            AirlineClassMaster.class_code == normalized["class_code"],
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Class already exists for this airline.")

    if _is_platform_admin(current_user):
        obj = AirlineClassMaster(**{k: v for k, v in normalized.items() if k != "is_active"}, is_active=True)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return {"status": "added", "class_row": AirlineClassMasterRead.model_validate(obj)}

    pending = await db.execute(
        select(ClassApproval).where(
            ClassApproval.airline_name == normalized["airline_name"],
            ClassApproval.class_type == normalized["class_type"],
            ClassApproval.class_code == normalized["class_code"],
            func.lower(ClassApproval.status) == "pending",
        )
    )
    if pending.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Class is already pending approval.")

    approval = ClassApproval(
        airline_name=normalized["airline_name"],
        class_type=normalized["class_type"],
        class_code=normalized["class_code"],
        airline_type=normalized["airline_type"],
        class_note=normalized["class_note"],
        submitted_by_id=current_user.id,
        tenant_id=current_user.tenant_id,
        status="pending",
        request_type="new",
        target_class_id=None,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return {"status": "pending_approval", "approval_id": approval.id}


@router.get("/approvals", response_model=list[ClassApprovalRead])
async def list_class_approvals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    pending_filter = func.lower(ClassApproval.status) == "pending"
    if _is_platform_admin(current_user):
        result = await db.execute(
            select(ClassApproval)
            .options(selectinload(ClassApproval.submitted_by))
            .where(pending_filter)
            .order_by(ClassApproval.submitted_at.desc())
        )
    else:
        result = await db.execute(
            select(ClassApproval)
            .options(selectinload(ClassApproval.submitted_by))
            .where(ClassApproval.submitted_by_id == current_user.id)
            .order_by(ClassApproval.submitted_at.desc())
        )
    return result.scalars().all()


@router.patch("/approvals/{approval_id}/approve", response_model=AirlineClassMasterRead)
async def approve_class(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PLATFORM_ADMIN)),
):
    result = await db.execute(select(ClassApproval).where(ClassApproval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if (approval.status or "").lower() != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{approval.status}'.")

    request_type = (getattr(approval, "request_type", None) or "new").lower()

    if request_type == "update":
        target_result = await db.execute(
            select(AirlineClassMaster).where(AirlineClassMaster.id == approval.target_class_id)
        )
        target = target_result.scalar_one_or_none()
        if not target:
            approval.status = "rejected"
            approval.rejection_reason = "Target class no longer exists."
            approval.reviewed_by_id = current_user.id
            approval.reviewed_at = datetime.utcnow()
            await db.commit()
            raise HTTPException(status_code=409, detail="Target class no longer exists; request auto-rejected.")

        target.airline_name = approval.airline_name
        target.class_type = approval.class_type
        target.class_code = approval.class_code
        target.airline_type = approval.airline_type
        target.class_note = approval.class_note

        approval.status = "approved"
        approval.reviewed_by_id = current_user.id
        approval.reviewed_at = datetime.utcnow()

        await db.commit()
        await db.refresh(target)
        return target

    # ── request_type == "new" ───────────────────────────────────────────────
    existing = await db.execute(
        select(AirlineClassMaster).where(
            AirlineClassMaster.airline_name == approval.airline_name,
            AirlineClassMaster.class_type == approval.class_type,
            AirlineClassMaster.class_code == approval.class_code,
        )
    )
    if existing.scalar_one_or_none():
        approval.status = "rejected"
        approval.rejection_reason = "Class was already added directly."
        approval.reviewed_by_id = current_user.id
        approval.reviewed_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(status_code=409, detail="Class already exists in master.")

    row = AirlineClassMaster(
        airline_name=approval.airline_name,
        class_type=approval.class_type,
        class_code=approval.class_code,
        airline_type=approval.airline_type,
        class_note=approval.class_note,
        is_active=True,
    )
    db.add(row)

    approval.status = "approved"
    approval.reviewed_by_id = current_user.id
    approval.reviewed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return row


@router.patch("/approvals/{approval_id}/reject")
async def reject_class(
    approval_id: int,
    payload: ClassApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PLATFORM_ADMIN)),
):
    result = await db.execute(select(ClassApproval).where(ClassApproval.id == approval_id))
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


@router.get("/{class_id}", response_model=AirlineClassMasterRead)
async def get_airline_class(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(AirlineClassMaster).where(AirlineClassMaster.id == class_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Class not found")
    return obj


@router.patch("/{class_id}", response_model=AirlineClassMasterRead)
async def update_airline_class(
    class_id: int,
    payload: AirlineClassMasterUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PLATFORM_ADMIN)),
):
    obj = await db.execute(select(AirlineClassMaster).where(AirlineClassMaster.id == class_id))
    existing = obj.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Class not found")

    data = payload.model_dump(exclude_unset=True)
    if "airline_name" in data and data["airline_name"] is not None:
        existing.airline_name = _normalize_cell(data["airline_name"]).upper()
    if "class_type" in data and data["class_type"] is not None:
        existing.class_type = _normalize_cell(data["class_type"]).upper()
    if "class_code" in data and data["class_code"] is not None:
        existing.class_code = _normalize_cell(data["class_code"]).upper()
    if "airline_type" in data:
        existing.airline_type = _normalize_cell(data["airline_type"]).upper() or None
    if "class_note" in data:
        existing.class_note = _normalize_cell(data["class_note"]).strip() or None
    if "is_active" in data and data["is_active"] is not None:
        existing.is_active = bool(data["is_active"])

    await db.commit()
    await db.refresh(existing)
    return existing


@router.delete("/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_airline_class(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.PLATFORM_ADMIN)),
):
    obj = await db.execute(select(AirlineClassMaster).where(AirlineClassMaster.id == class_id))
    existing = obj.scalar_one_or_none()
    if not existing:
        raise HTTPException(status_code=404, detail="Class not found")
    await db.delete(existing)
    await db.commit()

