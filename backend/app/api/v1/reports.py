from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/by-airline")
async def report_by_airline(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.by_airline(db, period_from=period_from, period_to=period_to)


@router.get("/by-supplier")
async def report_by_supplier(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.by_supplier(db, period_from=period_from, period_to=period_to)


@router.get("/by-route")
async def report_by_route(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    airline_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.by_route(db, period_from=period_from, period_to=period_to, airline_id=airline_id)


@router.get("/by-class")
async def report_by_class(
    period_from: Optional[str] = Query(None),
    period_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.by_class(db, period_from=period_from, period_to=period_to)


@router.get("/dashboard")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.report_service import ReportService
    return await ReportService.dashboard_stats(db)
