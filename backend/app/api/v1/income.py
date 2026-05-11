from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.income import IncomeRecordRead, IncomeOverrideRequest

router = APIRouter()


@router.get("/", response_model=list[IncomeRecordRead])
async def list_income(
    skip: int = 0,
    limit: int = 100,
    airline_id: Optional[int] = Query(None),
    supplier_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app import crud
    return await crud.income.get_multi_filtered(db, skip=skip, limit=limit,
                                                airline_id=airline_id, supplier_id=supplier_id)


@router.get("/summary")
async def income_summary(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    airline_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.income_summary(db, period_from=period_from, period_to=period_to, airline_id=airline_id)


@router.patch("/{income_id}/override", response_model=IncomeRecordRead)
async def override_income(
    income_id: int,
    payload: IncomeOverrideRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app import crud
    record = await crud.income.get(db, id=income_id)
    if not record:
        raise HTTPException(status_code=404, detail="Income record not found")
    return await crud.income.apply_override(db, record=record, payload=payload, user_id=current_user.id)


@router.post("/{income_id}/approve", response_model=IncomeRecordRead)
async def approve_income(
    income_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app import crud
    record = await crud.income.get(db, id=income_id)
    if not record:
        raise HTTPException(status_code=404, detail="Income record not found")
    return await crud.income.approve(db, record=record, user_id=current_user.id)
