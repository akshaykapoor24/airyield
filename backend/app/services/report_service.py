"""
ReportService — aggregation queries for dashboard and reports.
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import date

from app.models.income import IncomeRecord
from app.models.ticket import Ticket
from app.models.airline import Airline
from app.models.supplier import Supplier


class ReportService:
    @staticmethod
    async def dashboard_stats(db: AsyncSession) -> dict:
        total_income = await db.scalar(select(func.sum(IncomeRecord.total_income)))
        total_tickets = await db.scalar(select(func.count(Ticket.id)))
        approved_income = await db.scalar(
            select(func.sum(IncomeRecord.total_income)).where(IncomeRecord.is_approved == True)
        )
        return {
            "total_income": float(total_income or 0),
            "approved_income": float(approved_income or 0),
            "total_tickets": total_tickets or 0,
        }

    @staticmethod
    async def income_summary(
        db: AsyncSession,
        period_from: Optional[str],
        period_to: Optional[str],
        airline_id: Optional[int],
    ) -> dict:
        stmt = select(func.sum(IncomeRecord.total_income), func.count(IncomeRecord.id))
        result = await db.execute(stmt)
        row = result.one()
        return {"total_income": float(row[0] or 0), "record_count": row[1]}

    @staticmethod
    async def by_airline(db: AsyncSession, period_from: Optional[str], period_to: Optional[str]) -> list:
        stmt = (
            select(Airline.name, Airline.iata_code, func.sum(IncomeRecord.total_income).label("total_income"))
            .join(Ticket, Ticket.id == IncomeRecord.ticket_id)
            .join(Airline, Airline.id == Ticket.airline_id)
            .group_by(Airline.id)
            .order_by(func.sum(IncomeRecord.total_income).desc())
        )
        result = await db.execute(stmt)
        return [{"airline": r[0], "iata_code": r[1], "total_income": float(r[2] or 0)} for r in result.all()]

    @staticmethod
    async def by_supplier(db: AsyncSession, period_from: Optional[str], period_to: Optional[str]) -> list:
        stmt = (
            select(Supplier.name, func.sum(IncomeRecord.total_income).label("total_income"))
            .join(Ticket, Ticket.id == IncomeRecord.ticket_id)
            .join(Supplier, Supplier.id == Ticket.supplier_id)
            .group_by(Supplier.id)
            .order_by(func.sum(IncomeRecord.total_income).desc())
        )
        result = await db.execute(stmt)
        return [{"supplier": r[0], "total_income": float(r[1] or 0)} for r in result.all()]

    @staticmethod
    async def by_route(
        db: AsyncSession, period_from: Optional[str], period_to: Optional[str], airline_id: Optional[int]
    ) -> list:
        stmt = (
            select(
                Ticket.origin_code,
                Ticket.destination_code,
                func.sum(IncomeRecord.total_income).label("total_income"),
                func.count(Ticket.id).label("ticket_count"),
            )
            .join(Ticket, Ticket.id == IncomeRecord.ticket_id)
            .group_by(Ticket.origin_code, Ticket.destination_code)
            .order_by(func.sum(IncomeRecord.total_income).desc())
        )
        result = await db.execute(stmt)
        return [
            {"route": f"{r[0]}-{r[1]}", "total_income": float(r[2] or 0), "ticket_count": r[3]}
            for r in result.all()
        ]

    @staticmethod
    async def by_class(db: AsyncSession, period_from: Optional[str], period_to: Optional[str]) -> list:
        stmt = (
            select(
                Ticket.booking_class,
                func.sum(IncomeRecord.total_income).label("total_income"),
                func.count(Ticket.id).label("ticket_count"),
            )
            .join(Ticket, Ticket.id == IncomeRecord.ticket_id)
            .group_by(Ticket.booking_class)
        )
        result = await db.execute(stmt)
        return [
            {"class": r[0], "total_income": float(r[1] or 0), "ticket_count": r[2]}
            for r in result.all()
        ]
