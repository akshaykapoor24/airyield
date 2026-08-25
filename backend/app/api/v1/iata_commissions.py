from io import BytesIO
from datetime import date, datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, func, or_, true as sa_true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, is_platform_admin, require_role
from app.models.iata_commission import IataCommission
from app.models.iata_commission_approval import IataCommissionApproval
from app.models.user import User, UserRole
from app.schemas.iata_commission import (
    IataCommissionCreate, IataCommissionUpdate, IataCommissionRead, BulkUploadResult,
    IataCommissionApprovalRead, IataCommissionApprovalAction, IataCommissionApprovalEdit,
)
from app.services.master_approval_edit import apply_admin_edit, IATA_COMMISSION_FIELDS
from app.services.master_export import master_export_response

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


def _parse_date(raw: str) -> date | None:
    """Parse an ISO YYYY-MM-DD date cell; raise ValueError on a non-empty bad value."""
    s = (raw or "").strip()
    if not s:
        return None
    return date.fromisoformat(s[:10])


def _parse_pct(raw: str) -> float | None:
    s = (raw or "").strip().rstrip("%").strip()
    if not s:
        return None
    return float(s)


def _scope(current_user: User):
    """Which rows this caller may see.

    IATA Commission used to live in the tenant's User Master and every row
    carried a tenant_id. It is now a Master Governance master: the platform
    admin owns it and the rows they add are global (tenant_id NULL). So a
    tenant user sees the global master plus whatever their own tenant created
    before the move, and the platform admin sees every row — the legacy ones
    included, since reviewing and cleaning those up is now their job.
    """
    if is_platform_admin(current_user):
        return sa_true()
    return or_(
        IataCommission.tenant_id.is_(None),
        IataCommission.tenant_id == current_user.tenant_id,
    )


async def _load(pk: int, db: AsyncSession, current_user: User) -> IataCommission:
    result = await db.execute(
        select(IataCommission).where(IataCommission.id == pk, _scope(current_user))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="IATA commission row not found")
    return obj


@router.get("/", response_model=list[IataCommissionRead])
async def list_iata_commissions(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(IataCommission).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            IataCommission.airline_name.ilike(term),
            IataCommission.airline_code.ilike(term),
            IataCommission.iata_numeric_code.ilike(term),
        ))
    q = q.order_by(IataCommission.airline_name).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_iata_commission(
    payload: IataCommissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    """Add a row, or — for a tenant user — queue the request for approval.

    Same contract as the other System Masters: a platform admin's write lands
    on the master immediately; anyone else's becomes a pending request that
    Master Governance reviews.
    """
    airline = (payload.airline_name or "").strip()
    if not airline:
        raise HTTPException(status_code=400, detail="airline_name is required.")

    code = (payload.airline_code or "").strip() or None
    numeric = (payload.iata_numeric_code or "").strip() or None
    request_type = (payload.request_type or "new").lower()

    if request_type == "update":
        if not payload.target_id:
            raise HTTPException(status_code=400, detail="target_id is required for update requests.")
        target = (await db.execute(
            select(IataCommission).where(IataCommission.id == payload.target_id)
        )).scalar_one_or_none()
        if not target:
            raise HTTPException(
                status_code=404,
                detail=f"IATA commission row with id {payload.target_id} not found.",
            )

        if is_platform_admin(current_user):
            target.airline_name = airline
            target.airline_code = code
            target.iata_numeric_code = numeric
            target.iata_commission_pct = payload.iata_commission_pct
            target.valid_from = payload.valid_from
            target.valid_to = payload.valid_to
            if payload.is_active is not None:
                target.is_active = payload.is_active
            await db.commit()
            await db.refresh(target)
            return {"status": "updated", "iata_commission": IataCommissionRead.model_validate(target)}

        approval = IataCommissionApproval(
            airline_name=airline,
            airline_code=code,
            iata_numeric_code=numeric,
            iata_commission_pct=payload.iata_commission_pct,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            submitted_by_id=current_user.id,
            tenant_id=current_user.tenant_id,
            status="pending",
            request_type="update",
            target_iata_commission_id=payload.target_id,
        )
        db.add(approval)
        await db.commit()
        await db.refresh(approval)
        return {"status": "pending_approval", "approval_id": approval.id}

    # ── request_type == "new" (default) ────────────────────────────────────
    # No uniqueness to enforce: one airline legitimately has several rows, one
    # per validity window.
    if is_platform_admin(current_user):
        obj = IataCommission(
            # Master Governance data is global — see _scope.
            tenant_id=None,
            created_by_id=current_user.id,
            airline_name=airline,
            airline_code=code,
            iata_numeric_code=numeric,
            iata_commission_pct=payload.iata_commission_pct,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            is_active=payload.is_active if payload.is_active is not None else True,
        )
        db.add(obj)
        await db.commit()
        return {"status": "added", "iata_commission": await _load(obj.id, db, current_user)}

    approval = IataCommissionApproval(
        airline_name=airline,
        airline_code=code,
        iata_numeric_code=numeric,
        iata_commission_pct=payload.iata_commission_pct,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        submitted_by_id=current_user.id,
        tenant_id=current_user.tenant_id,
        status="pending",
        request_type="new",
        target_iata_commission_id=None,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return {"status": "pending_approval", "approval_id": approval.id}


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_iata_commissions(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    """Import rows in bulk. A platform admin's land on the master; a tenant
    user's each become a pending "new" request, one per sheet row."""
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"AIRLINE_NAME"}

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
                "Missing required column: AIRLINE_NAME. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: AIRLINE_NAME"
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
        airline = _cell(row.get("AIRLINE_NAME"))
        if not airline:
            errors.append(f"Row {row_num}: AIRLINE_NAME is required.")
            continue

        try:
            pct = _parse_pct(_cell(row.get("IATA_COMMISSION_PCT")))
            valid_from = _parse_date(_cell(row.get("VALID_FROM")))
            valid_to = _parse_date(_cell(row.get("VALID_TO")))
        except ValueError as e:
            errors.append(f"Row {row_num}: invalid number/date — {e}")
            continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            if is_platform_admin(current_user):
                db.add(IataCommission(
                    # Master Governance data is global — see _scope.
                    tenant_id=None,
                    created_by_id=current_user.id,
                    airline_name=airline,
                    airline_code=_cell(row.get("AIRLINE_CODE")) or None,
                    iata_numeric_code=_cell(row.get("IATA_NUMERIC_CODE")) or None,
                    iata_commission_pct=pct,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    is_active=is_active,
                ))
            else:
                # ACTIVE is a master-only column — an approval row has no
                # is_active, and approve() always creates the row active.
                db.add(IataCommissionApproval(
                    airline_name=airline,
                    airline_code=_cell(row.get("AIRLINE_CODE")) or None,
                    iata_numeric_code=_cell(row.get("IATA_NUMERIC_CODE")) or None,
                    iata_commission_pct=pct,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    submitted_by_id=current_user.id,
                    tenant_id=current_user.tenant_id,
                    status="pending",
                    request_type="new",
                    target_iata_commission_id=None,
                ))
            await db.commit()
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e}")

    return BulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.get("/template")
async def download_iata_commission_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "IATA Commission Template"
    ws.append(["AIRLINE_NAME", "AIRLINE_CODE", "IATA_NUMERIC_CODE", "IATA_COMMISSION_PCT", "VALID_FROM", "VALID_TO", "ACTIVE"])
    ws.append(["Air India", "AI", "098", "5", "2026-01-01", "2026-12-31", "yes"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="iata_commission_template.xlsx"'},
    )


@router.get("/export")
async def export_iata_commissions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(PLATFORM)),
):
    """The whole IATA commission master as .xlsx, for review in Excel.

    Column headers match download_iata_commission_template so a reviewed sheet
    can go straight back through /bulk-upload; ID is for reference only.
    """
    result = await db.execute(select(IataCommission).order_by(IataCommission.airline_name))
    commissions = result.scalars().all()

    headers = [
        "ID", "AIRLINE_NAME", "AIRLINE_CODE", "IATA_NUMERIC_CODE",
        "IATA_COMMISSION_PCT", "VALID_FROM", "VALID_TO", "ACTIVE",
    ]
    rows = [
        [
            c.id, c.airline_name, c.airline_code, c.iata_numeric_code,
            c.iata_commission_pct, c.valid_from, c.valid_to, c.is_active,
        ]
        for c in commissions
    ]

    return master_export_response(
        sheet_title="IATA Commission Master",
        filename="iata_commission_master.xlsx",
        headers=headers,
        rows=rows,
    )


# ── approval queue ─────────────────────────────────────────────────────────
# All of these are declared before "/{pk}": FastAPI matches in declaration
# order, so below it "/approvals" would bind there and 422 on the literal.

@router.get("/approvals", response_model=list[IataCommissionApprovalRead])
async def list_iata_commission_approvals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(*SUBMITTERS)),
):
    """Master Governance sees every pending request; a submitter sees their own
    — approved and rejected included, so they can follow what happened to it."""
    q = (
        select(IataCommissionApproval)
        .options(
            selectinload(IataCommissionApproval.submitted_by),
            # Without this, edited_by lazy-loads during serialisation and
            # raises MissingGreenlet — but only once a row has been edited.
            selectinload(IataCommissionApproval.edited_by),
        )
        .order_by(IataCommissionApproval.submitted_at.desc())
    )
    if is_platform_admin(current_user):
        q = q.where(func.lower(IataCommissionApproval.status) == "pending")
    else:
        q = q.where(IataCommissionApproval.submitted_by_id == current_user.id)
    result = await db.execute(q)
    return result.scalars().all()


async def _load_pending_approval(approval_id: int, db: AsyncSession) -> IataCommissionApproval:
    result = await db.execute(
        select(IataCommissionApproval).where(IataCommissionApproval.id == approval_id)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if (approval.status or "").lower() != "pending":
        raise HTTPException(status_code=400, detail=f"Request is already '{approval.status}'.")
    return approval


@router.patch("/approvals/{approval_id}/approve", response_model=IataCommissionRead)
async def approve_iata_commission(
    approval_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    approval = await _load_pending_approval(approval_id, db)
    request_type = (approval.request_type or "new").lower()

    if request_type == "update":
        target = (await db.execute(
            select(IataCommission).where(
                IataCommission.id == approval.target_iata_commission_id
            )
        )).scalar_one_or_none()
        if not target:
            approval.status = "rejected"
            approval.rejection_reason = "Target IATA commission row no longer exists."
            approval.reviewed_by_id = current_user.id
            approval.reviewed_at = datetime.utcnow()
            await db.commit()
            raise HTTPException(
                status_code=409,
                detail="Target IATA commission row no longer exists; request auto-rejected.",
            )

        target.airline_name = approval.airline_name
        target.airline_code = approval.airline_code
        target.iata_numeric_code = approval.iata_numeric_code
        target.iata_commission_pct = approval.iata_commission_pct
        target.valid_from = approval.valid_from
        target.valid_to = approval.valid_to

        approval.status = "approved"
        approval.reviewed_by_id = current_user.id
        approval.reviewed_at = datetime.utcnow()

        await db.commit()
        await db.refresh(target)
        return target

    # ── request_type == "new" ──────────────────────────────────────────────
    row = IataCommission(
        # Approved requests join the global master — see _scope.
        tenant_id=None,
        # The master's created_by_id is NOT NULL and means "who put this row
        # here"; on an approved request that is the submitter, not the admin.
        created_by_id=approval.submitted_by_id,
        airline_name=approval.airline_name,
        airline_code=approval.airline_code,
        iata_numeric_code=approval.iata_numeric_code,
        iata_commission_pct=approval.iata_commission_pct,
        valid_from=approval.valid_from,
        valid_to=approval.valid_to,
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
async def reject_iata_commission(
    approval_id: int,
    payload: IataCommissionApprovalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    approval = await _load_pending_approval(approval_id, db)
    approval.status = "rejected"
    approval.rejection_reason = payload.rejection_reason
    approval.reviewed_by_id = current_user.id
    approval.reviewed_at = datetime.utcnow()
    await db.commit()
    return {"status": "rejected"}


@router.patch("/approvals/{approval_id}", response_model=IataCommissionApprovalRead)
async def edit_iata_commission_approval(
    approval_id: int,
    payload: IataCommissionApprovalEdit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    """Correct a pending request before approving it.

    Approve already copies this row onto the master, so editing the row in place
    is all that is needed for the corrected values to land — this endpoint only
    has to record what the submitter originally sent so they can see the change.
    """
    approval = await _load_pending_approval(approval_id, db)
    changes = payload.model_dump(exclude_unset=True)

    if (approval.request_type or "new").lower() == "update":
        # Editing a request whose target was deleted can only produce a row that
        # approve will auto-reject, so refuse rather than waste the admin's work.
        target = await db.execute(
            select(IataCommission.id).where(
                IataCommission.id == approval.target_iata_commission_id
            )
        )
        if not target.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail="The IATA commission row this request targets no longer exists; "
                       "it can only be rejected.",
            )

    try:
        apply_admin_edit(
            approval,
            fields=IATA_COMMISSION_FIELDS,
            changes=changes,
            editor_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    await db.commit()

    fresh = await db.execute(
        select(IataCommissionApproval)
        .options(
            selectinload(IataCommissionApproval.submitted_by),
            selectinload(IataCommissionApproval.edited_by),
        )
        .where(IataCommissionApproval.id == approval_id)
    )
    return fresh.scalar_one()


@router.get("/{pk}", response_model=IataCommissionRead)
async def get_iata_commission(
    pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load(pk, db, current_user)


@router.patch("/{pk}", response_model=IataCommissionRead)
async def update_iata_commission(
    pk: int,
    payload: IataCommissionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    obj = await _load(pk, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "airline_name" in data:
        new_name = (data["airline_name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="airline_name cannot be empty.")
        data["airline_name"] = new_name
    for field, value in data.items():
        setattr(obj, field, value)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.delete("/{pk}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_iata_commission(
    pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(PLATFORM)),
):
    obj = await _load(pk, db, current_user)
    await db.delete(obj)
    await db.commit()
