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
from app.models.supplier import Supplier
from app.models.supplier_approval import SupplierApproval
from app.models.user import User, UserRole
from app.schemas.supplier import (
    SupplierRead, SupplierCreate, SupplierUpdate, SupplierBulkUploadResult,
    SupplierApprovalRead, SupplierApprovalAction,
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


async def _generate_code(db: AsyncSession) -> str:
    result = await db.execute(select(func.max(Supplier.id)))
    max_id = result.scalar() or 0
    return f"SUPP-{(max_id + 1):04d}"


@router.get("/count")
async def count_suppliers(
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(func.count()).select_from(Supplier)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Supplier.name.ilike(term),
            Supplier.code.ilike(term),
            Supplier.vendor_type.ilike(term),
            Supplier.vendor_name.ilike(term),
            Supplier.branch.ilike(term),
        ))
    result = await db.execute(q)
    return {"total": result.scalar()}


@router.get("/", response_model=list[SupplierRead])
async def list_suppliers(
    skip: int = 0, limit: int = 100,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Supplier)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Supplier.name.ilike(term),
            Supplier.code.ilike(term),
            Supplier.vendor_type.ilike(term),
            Supplier.vendor_name.ilike(term),
            Supplier.branch.ilike(term),
        ))
    q = q.order_by(Supplier.name).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    request_type = (payload.request_type or "new").lower()

    if request_type == "update":
        if not payload.target_id:
            raise HTTPException(status_code=400, detail="target_id is required for update requests.")
        target_check = await db.execute(select(Supplier).where(Supplier.id == payload.target_id))
        if not target_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"Supplier with id {payload.target_id} not found.")

        if _is_platform_admin(current_user):
            target = (await db.execute(select(Supplier).where(Supplier.id == payload.target_id))).scalar_one()
            target.name = payload.name.strip()
            target.vendor_type = payload.vendor_type
            target.vendor_name = payload.vendor_name
            target.branch = payload.branch
            target.branches = payload.branches
            target.contact_phone = payload.contact_phone
            target.alternate_phone = payload.alternate_phone
            target.contact_email = payload.contact_email
            target.alternate_email = payload.alternate_email
            target.gst_number = payload.gst_number
            target.pan_number = payload.pan_number
            target.notes = payload.notes
            await db.commit()
            await db.refresh(target)
            return {"status": "updated", "supplier": SupplierRead.model_validate(target)}

        approval = SupplierApproval(
            name=payload.name.strip(),
            vendor_type=payload.vendor_type,
            vendor_name=payload.vendor_name,
            branch=payload.branch,
            branches=payload.branches,
            contact_phone=payload.contact_phone,
            alternate_phone=payload.alternate_phone,
            contact_email=payload.contact_email,
            alternate_email=payload.alternate_email,
            gst_number=payload.gst_number,
            pan_number=payload.pan_number,
            notes=payload.notes,
            submitted_by_id=current_user.id,
            tenant_id=current_user.tenant_id,
            status="pending",
            request_type="update",
            target_supplier_id=payload.target_id,
        )
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        return {"status": "pending_approval", "approval_id": approval.id}

    # request_type == "new"
    if _is_platform_admin(current_user):
        code = payload.code.strip() if payload.code else await _generate_code(db)
        existing = await db.execute(select(Supplier).where(Supplier.code == code))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Supplier with code '{code}' already exists.")
        supplier = Supplier(
            name=payload.name.strip(),
            code=code,
            vendor_type=payload.vendor_type,
            vendor_name=payload.vendor_name,
            branch=payload.branch,
            branches=payload.branches,
            contact_phone=payload.contact_phone,
            alternate_phone=payload.alternate_phone,
            contact_email=payload.contact_email,
            alternate_email=payload.alternate_email,
            gst_number=payload.gst_number,
            pan_number=payload.pan_number,
            notes=payload.notes,
        )
        db.add(supplier)
        await db.commit()
        await db.refresh(supplier)
        return {"status": "added", "supplier": SupplierRead.model_validate(supplier)}

    approval = SupplierApproval(
        name=payload.name.strip(),
        vendor_type=payload.vendor_type,
        vendor_name=payload.vendor_name,
        branch=payload.branch,
        branches=payload.branches,
        contact_phone=payload.contact_phone,
        alternate_phone=payload.alternate_phone,
        contact_email=payload.contact_email,
        alternate_email=payload.alternate_email,
        gst_number=payload.gst_number,
        pan_number=payload.pan_number,
        notes=payload.notes,
        submitted_by_id=current_user.id,
        tenant_id=current_user.tenant_id,
        status="pending",
        request_type="new",
        target_supplier_id=None,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return {"status": "pending_approval", "approval_id": approval.id}


@router.post("/bulk-upload", response_model=SupplierBulkUploadResult)
async def bulk_upload_suppliers(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"VENDOR_NAME"}

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
                "Missing required column: VENDOR_NAME. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: VENDOR_NAME"
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
        row_prefix = f"Row {row_num}"
        name = str(row.get("VENDOR_NAME", "") or "").strip()
        if not name:
            errors.append(f"{row_prefix}: VENDOR_NAME is required.")
            continue

        vendor_type = str(row.get("TYPE", "") or "").strip() or None
        vendor_name = str(row.get("VENDOR_DISPLAY_NAME", "") or "").strip() or None
        branch = str(row.get("BRANCH", "") or "").strip() or None
        # Parse BRANCHES column: "Delhi|DEL;Mumbai|BOM"
        branches_raw = str(row.get("BRANCHES", "") or "").strip()
        branches: list | None = None
        if branches_raw:
            parsed = []
            for entry in branches_raw.split(";"):
                parts = entry.strip().split("|")
                if parts[0].strip():
                    parsed.append({"name": parts[0].strip(), "iata_code": (parts[1].strip().upper() if len(parts) > 1 else "")})
            branches = parsed or None
        contact_phone = str(row.get("CONTACT_NUMBER", "") or "").strip() or None
        alternate_phone = str(row.get("ALTERNATE_CONTACT_NO", "") or "").strip() or None
        contact_email = str(row.get("CONTACT_EMAIL", "") or "").strip() or None
        alternate_email = str(row.get("ALTERNATE_EMAIL", "") or "").strip() or None
        gst_number = str(row.get("GST_NUMBER", "") or "").strip() or None
        pan_number = str(row.get("PAN_NUMBER", "") or "").strip() or None
        notes = str(row.get("REMARKS", "") or "").strip() or None

        try:
            if _is_platform_admin(current_user):
                code = await _generate_code(db)
                supplier = Supplier(
                    name=name, code=code,
                    vendor_type=vendor_type, vendor_name=vendor_name,
                    branch=branch, branches=branches,
                    contact_phone=contact_phone, alternate_phone=alternate_phone,
                    contact_email=contact_email, alternate_email=alternate_email,
                    gst_number=gst_number, pan_number=pan_number, notes=notes,
                )
                db.add(supplier)
                await db.commit()
            else:
                approval = SupplierApproval(
                    name=name, vendor_type=vendor_type, vendor_name=vendor_name,
                    branch=branch, branches=branches,
                    contact_phone=contact_phone, alternate_phone=alternate_phone,
                    contact_email=contact_email, alternate_email=alternate_email,
                    gst_number=gst_number, pan_number=pan_number, notes=notes,
                    submitted_by_id=current_user.id,
                    tenant_id=current_user.tenant_id,
                    status="pending", request_type="new",
                )
                db.add(approval)
                await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"{row_prefix}: {e}")

    return SupplierBulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.get("/template")
async def download_supplier_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Supplier Template"

    headers = [
        "VENDOR_NAME", "VENDOR_DISPLAY_NAME", "TYPE",
        "BRANCHES",
        "CONTACT_NUMBER", "ALTERNATE_CONTACT_NO",
        "CONTACT_EMAIL", "ALTERNATE_EMAIL", "GST_NUMBER", "PAN_NUMBER", "REMARKS",
    ]
    ws.append(headers)
    # Sample row showing BRANCHES format
    ws.append(["Sample Supplier", "Display Name", "Agent", "Delhi|DEL;Mumbai|BOM", "", "", "", "", "", "", ""])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="supplier_template.xlsx"'},
    )


@router.get("/approvals", response_model=list[SupplierApprovalRead])
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    pending_filter = func.lower(SupplierApproval.status) == "pending"
    if _is_platform_admin(current_user):
        result = await db.execute(
            select(SupplierApproval)
            .options(selectinload(SupplierApproval.submitted_by))
            .where(pending_filter)
            .order_by(SupplierApproval.submitted_at.desc())
        )
    else:
        result = await db.execute(
            select(SupplierApproval)
            .options(selectinload(SupplierApproval.submitted_by))
            .where(SupplierApproval.submitted_by_id == current_user.id)
            .order_by(SupplierApproval.submitted_at.desc())
        )
    approvals = result.scalars().all()
    return [SupplierApprovalRead.model_validate(a) for a in approvals]


@router.patch("/approvals/{approval_id}/approve", response_model=SupplierRead)
async def approve_supplier(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    result = await db.execute(select(SupplierApproval).where(SupplierApproval.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if (approval.status or "").lower() != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{approval.status}'.")

    request_type = (getattr(approval, "request_type", None) or "new").lower()

    if request_type == "update":
        target_result = await db.execute(select(Supplier).where(Supplier.id == approval.target_supplier_id))
        target = target_result.scalar_one_or_none()
        if not target:
            approval.status = "rejected"
            approval.rejection_reason = "Target supplier no longer exists."
            approval.reviewed_by_id = current_user.id
            approval.reviewed_at = datetime.utcnow()
            await db.commit()
            raise HTTPException(status_code=409, detail="Target supplier no longer exists; request auto-rejected.")

        target.name = approval.name
        target.vendor_type = approval.vendor_type
        target.vendor_name = approval.vendor_name
        target.branch = approval.branch
        target.branches = approval.branches
        target.contact_phone = approval.contact_phone
        target.alternate_phone = approval.alternate_phone
        target.contact_email = approval.contact_email
        target.alternate_email = approval.alternate_email
        target.gst_number = approval.gst_number
        target.pan_number = approval.pan_number
        target.notes = approval.notes

        approval.status = "approved"
        approval.reviewed_by_id = current_user.id
        approval.reviewed_at = datetime.utcnow()

        await db.commit()
        await db.refresh(target)
        return target

    # request_type == "new"
    code = await _generate_code(db)
    supplier = Supplier(
        name=approval.name, code=code,
        vendor_type=approval.vendor_type, vendor_name=approval.vendor_name,
        branch=approval.branch, branches=approval.branches,
        contact_phone=approval.contact_phone, alternate_phone=approval.alternate_phone,
        contact_email=approval.contact_email, alternate_email=approval.alternate_email,
        gst_number=approval.gst_number, pan_number=approval.pan_number,
        notes=approval.notes,
    )
    db.add(supplier)
    approval.status = "approved"
    approval.reviewed_by_id = current_user.id
    approval.reviewed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(supplier)
    return supplier


@router.patch("/approvals/{approval_id}/reject")
async def reject_supplier(
    approval_id: int,
    payload: SupplierApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    result = await db.execute(select(SupplierApproval).where(SupplierApproval.id == approval_id))
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


@router.get("/{supplier_id}", response_model=SupplierRead)
async def get_supplier(
    supplier_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return obj


@router.patch("/{supplier_id}", response_model=SupplierRead)
async def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(UserRole.PLATFORM_ADMIN)),
):
    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    return obj
