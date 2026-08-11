import re
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
from app.dependencies import get_current_user, is_platform_admin, require_role
from app.models.supplier import Supplier
from app.models.supplier_approval import SupplierApproval
from app.models.user import User, UserRole
from app.schemas.supplier import (
    SupplierRead, SupplierCreate, SupplierUpdate, SupplierBulkUploadResult,
    SupplierApprovalRead, SupplierApprovalAction, SupplierApprovalEdit,
)
from app.services.master_approval_edit import apply_admin_edit, SUPPLIER_CORE_FIELDS

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


# Directory / member-list fields shared by Supplier and SupplierApproval.
# Kept in one place so create/update/approve/bulk-upload stay in sync.
DIRECTORY_FIELDS = (
    "region_chapter", "membership_category",
    "address_1", "address_2", "address_3",
    "city", "pincode", "telephone_mobile", "website",
    "email_address", "alternate_email_id", "accounts_email",
    "fax_no", "representative_1", "representative_2",
)


def _directory_kwargs(obj) -> dict:
    """Extract the directory fields from a payload/ORM object as a kwargs dict."""
    return {f: getattr(obj, f, None) for f in DIRECTORY_FIELDS}


# Everything a platform admin may change on a pending request. Composed from
# DIRECTORY_FIELDS so that constant stays the single source for those 15 names.
SUPPLIER_FIELDS = (*SUPPLIER_CORE_FIELDS, *DIRECTORY_FIELDS)




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

        if is_platform_admin(current_user):
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
            for _f, _v in _directory_kwargs(payload).items():
                setattr(target, _f, _v)
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
            **_directory_kwargs(payload),
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
    if is_platform_admin(current_user):
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
            **_directory_kwargs(payload),
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
        **_directory_kwargs(payload),
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
    # The name column may be labelled COMPANY NAME (new directory) or VENDOR_NAME (legacy template).
    NAME_COLS = ("COMPANY_NAME", "VENDOR_NAME")

    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        # Uppercase, then collapse any run of non-alphanumeric chars to a single "_".
        # e.g. "REGION / CHAPTER" -> "REGION_CHAPTER", "E.MAIL ADDRESS" -> "E_MAIL_ADDRESS".
        df.columns = [
            re.sub(r"[^A-Z0-9]+", "_", str(c).strip().upper()).strip("_")
            for c in df.columns
        ]
        df.dropna(how="all", inplace=True)
        return df

    def _cell(row, *keys):
        """First non-empty cell value among the given normalized column names."""
        for k in keys:
            val = row.get(k)
            if val is None:
                continue
            s = str(val).strip()
            if s and s.lower() not in ("nan", "none"):
                return s
        return None

    try:
        df = None
        used_header_row = 0

        for header_row in (0, 1, 2):
            try:
                if filename.endswith(".xls"):
                    df_try = pd.read_excel(BytesIO(content), dtype=str, header=header_row)
                else:
                    df_try = pd.read_excel(BytesIO(content), dtype=str, engine="openpyxl", header=header_row)
                df_try = _normalize_columns(df_try)
                if any(c in df_try.columns for c in NAME_COLS):
                    df = df_try
                    used_header_row = header_row
                    break
            except Exception:
                continue

        if df is None:
            raise HTTPException(
                status_code=400,
                detail="Missing required name column. Expected 'COMPANY NAME' (or 'VENDOR_NAME'). "
                       "Check that the header is in the first few rows.",
            )
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
        name = _cell(row, *NAME_COLS)
        if not name:
            errors.append(f"{row_prefix}: COMPANY NAME / VENDOR_NAME is required.")
            continue

        # Legacy vendor fields (blank for a plain directory import)
        vendor_type = _cell(row, "TYPE")
        vendor_name = _cell(row, "VENDOR_DISPLAY_NAME")
        branch = _cell(row, "BRANCH")
        # Parse BRANCHES column: "Delhi|DEL;Mumbai|BOM"
        branches_raw = _cell(row, "BRANCHES") or ""
        branches: list | None = None
        if branches_raw:
            parsed = []
            for entry in branches_raw.split(";"):
                parts = entry.strip().split("|")
                if parts[0].strip():
                    parsed.append({"name": parts[0].strip(), "iata_code": (parts[1].strip().upper() if len(parts) > 1 else "")})
            branches = parsed or None
        contact_phone = _cell(row, "CONTACT_NUMBER")
        alternate_phone = _cell(row, "ALTERNATE_CONTACT_NO")
        contact_email = _cell(row, "CONTACT_EMAIL")
        alternate_email = _cell(row, "ALTERNATE_EMAIL")
        gst_number = _cell(row, "GST_NUMBER")
        pan_number = _cell(row, "PAN_NUMBER")
        notes = _cell(row, "REMARKS")

        # Directory / member-list fields
        directory = {
            "region_chapter": _cell(row, "REGION_CHAPTER", "REGION"),
            "membership_category": _cell(row, "MEMBERSHIP_CATEGORY", "MEMBERSHIP"),
            "address_1": _cell(row, "ADD1", "ADDRESS_1", "ADDRESS1"),
            "address_2": _cell(row, "ADD2", "ADDRESS_2", "ADDRESS2"),
            "address_3": _cell(row, "ADD3", "ADDRESS_3", "ADDRESS3"),
            "city": _cell(row, "CITY"),
            "pincode": _cell(row, "PINCODE", "PIN_CODE", "PIN"),
            "telephone_mobile": _cell(row, "TELEPHONE_NOS_MOBILE_NOS", "TELEPHONE_MOBILE", "TELEPHONE_NOS", "TELEPHONE", "PHONE", "MOBILE"),
            "website": _cell(row, "WEBSITE", "WEB"),
            "email_address": _cell(row, "E_MAIL_ADDRESS", "EMAIL_ADDRESS", "E_MAIL", "EMAIL"),
            "alternate_email_id": _cell(row, "ALTERNATE_E_MAIL_ID_1", "ALTERNATE_EMAIL_ID_1", "ALTERNATE_EMAIL_ID", "ALTERNATE_E_MAIL_ID"),
            "accounts_email": _cell(row, "ACCOUNTS", "ACCOUNTS_EMAIL"),
            "fax_no": _cell(row, "FAX_NO", "FAX"),
            "representative_1": _cell(row, "REPRESENTATIVE_I", "REPRESENTATIVE_1", "REPRESENTATIVE"),
            "representative_2": _cell(row, "REPRESENTATIVE_II", "REPRESENTATIVE_2"),
        }

        try:
            if is_platform_admin(current_user):
                code = await _generate_code(db)
                supplier = Supplier(
                    name=name, code=code,
                    vendor_type=vendor_type, vendor_name=vendor_name,
                    branch=branch, branches=branches,
                    contact_phone=contact_phone, alternate_phone=alternate_phone,
                    contact_email=contact_email, alternate_email=alternate_email,
                    gst_number=gst_number, pan_number=pan_number, notes=notes,
                    **directory,
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
                    **directory,
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

    # Directory columns first (exact XLS wording so download -> fill -> upload round-trips),
    # then the legacy vendor columns so vendor-style rows can still be imported.
    headers = [
        "COMPANY NAME", "REGION / CHAPTER", "MEMBERSHIP CATEGORY",
        "ADD1", "ADD2", "ADD3", "CITY", "PINCODE",
        "TELEPHONE NOS. & MOBILE NOS.", "WEBSITE",
        "E.MAIL ADDRESS", "ALTERNATE E-MAIL ID-1", "ACCOUNTS", "FAX NO",
        "REPRESENTATIVE I", "REPRESENTATIVE II",
        # --- Legacy vendor fields (optional) ---
        "TYPE", "BRANCHES", "GST_NUMBER", "PAN_NUMBER", "REMARKS",
    ]
    ws.append(headers)
    # Sample row
    ws.append([
        "G.B. Tours and Travels", "ANDHRA PRADESH & TELANGANA STATE CHAPTER (AP & TS)", "ACTIVE",
        "19-11-9A, First floor, Sarada Nagar", "Tiruchanoor Road", "", "TIRUPATI", "517501",
        "(T)+91-877-2227390 (M)+91-9441531290", "www.example.com",
        "gbtravels25@yahoo.co.in; gbtours25@yahoo.com", "", "", "+91-877-2221508",
        "Mr. Gandikota Bhaskar", "Mrs. G. Chandrika",
        "", "Delhi|DEL;Mumbai|BOM", "", "", "",
    ])

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
    if is_platform_admin(current_user):
        result = await db.execute(
            select(SupplierApproval)
            .options(
                selectinload(SupplierApproval.submitted_by),
                # SupplierApprovalRead.model_validate reads obj.edited_by
                # directly, so it must be eager-loaded or serialisation raises
                # MissingGreenlet — but only once a row has been edited.
                selectinload(SupplierApproval.edited_by),
            )
            .where(pending_filter)
            .order_by(SupplierApproval.submitted_at.desc())
        )
    else:
        result = await db.execute(
            select(SupplierApproval)
            .options(
                selectinload(SupplierApproval.submitted_by),
                # SupplierApprovalRead.model_validate reads obj.edited_by
                # directly, so it must be eager-loaded or serialisation raises
                # MissingGreenlet — but only once a row has been edited.
                selectinload(SupplierApproval.edited_by),
            )
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
        for _f, _v in _directory_kwargs(approval).items():
            setattr(target, _f, _v)

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
        **_directory_kwargs(approval),
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


# ── platform admin edits a pending request ─────────────────────────────────
# Declared before "/{supplier_id}": FastAPI matches in declaration order, so
# below it this path would bind there and 422 on the literal "approvals".

@router.patch("/approvals/{approval_id}", response_model=SupplierApprovalRead)
async def edit_supplier_approval(
    approval_id: int,
    payload: SupplierApprovalEdit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    """Correct a pending request before approving it.

    Approve already copies this row onto the master, so editing the row in place
    is all that is needed for the corrected values to land — this endpoint only
    has to record what the submitter originally sent so they can see the change.
    """
    result = await db.execute(
        select(SupplierApproval).where(SupplierApproval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if (approval.status or "").lower() != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{approval.status}'.")

    if (approval.request_type or "new").lower() == "update":
        # Editing a request whose target was deleted can only produce a row that
        # approve will auto-reject, so refuse rather than waste the admin's work.
        target = await db.execute(
            select(Supplier.id).where(Supplier.id == approval.target_supplier_id)
        )
        if not target.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="The supplier this request targets no longer exists; it can only be rejected.",
            )

    changes = payload.model_dump(exclude_unset=True)
    # branches arrives as a list of SupplierBranchIn; model_dump has already
    # turned it into plain dicts, which is what the JSON column stores. Assign
    # the new list wholesale — these columns have no mutation tracking.

    try:
        apply_admin_edit(
            approval,
            fields=SUPPLIER_FIELDS,
            changes=changes,
            editor_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await db.commit()

    # edited_by was set by id, so the relationship is not loaded; re-select with
    # both eager loads rather than lazy-loading them during serialisation.
    fresh = await db.execute(
        select(SupplierApproval)
        .options(
            selectinload(SupplierApproval.submitted_by),
            selectinload(SupplierApproval.edited_by),
        )
        .where(SupplierApproval.id == approval_id)
    )
    return SupplierApprovalRead.model_validate(fresh.scalar_one())


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
