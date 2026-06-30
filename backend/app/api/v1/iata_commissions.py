from io import BytesIO
from datetime import date
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.iata_commission import IataCommission
from app.models.user import User
from app.schemas.iata_commission import (
    IataCommissionCreate, IataCommissionUpdate, IataCommissionRead, BulkUploadResult,
)

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
    """Tenant scope — IATA commission rows are shared across the tenant's users."""
    return IataCommission.tenant_id == current_user.tenant_id


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


@router.post("/", response_model=IataCommissionRead, status_code=status.HTTP_201_CREATED)
async def create_iata_commission(
    payload: IataCommissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    airline = (payload.airline_name or "").strip()
    if not airline:
        raise HTTPException(status_code=400, detail="airline_name is required.")

    obj = IataCommission(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        airline_name=airline,
        airline_code=(payload.airline_code or "").strip() or None,
        iata_numeric_code=(payload.iata_numeric_code or "").strip() or None,
        iata_commission_pct=payload.iata_commission_pct,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(obj)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_iata_commissions(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
            db.add(IataCommission(
                tenant_id=current_user.tenant_id,
                created_by_id=current_user.id,
                airline_name=airline,
                airline_code=_cell(row.get("AIRLINE_CODE")) or None,
                iata_numeric_code=_cell(row.get("IATA_NUMERIC_CODE")) or None,
                iata_commission_pct=pct,
                valid_from=valid_from,
                valid_to=valid_to,
                is_active=is_active,
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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
):
    obj = await _load(pk, db, current_user)
    await db.delete(obj)
    await db.commit()
