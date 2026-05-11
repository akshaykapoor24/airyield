from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.crud.base import CRUDBase
from app.models.ticket import Ticket


class CRUDTicket(CRUDBase):
    def __init__(self):
        super().__init__(Ticket)

    async def get_multi_filtered(
        self, db: AsyncSession, skip: int, limit: int,
        airline_id=None, supplier_id=None
    ) -> list[Ticket]:
        stmt = select(Ticket)
        if airline_id:
            stmt = stmt.where(Ticket.airline_id == airline_id)
        if supplier_id:
            stmt = stmt.where(Ticket.supplier_id == supplier_id)
        stmt = stmt.offset(skip).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    async def manual_match(
        self, db: AsyncSession, *, ticket: Ticket, deal_id: int, user_id: int
    ) -> Ticket:
        from app.models.income import IncomeRecord
        from app.services.income_calculator import IncomeCalculatorService
        from sqlalchemy import select as sa_select
        from app.models.uploaded_deal import UploadedDeal

        ticket.matched_deal_id = deal_id
        ticket.is_manually_matched = True

        deal_result = await db.execute(sa_select(UploadedDeal).where(UploadedDeal.id == deal_id))
        deal = deal_result.scalar_one_or_none()
        if deal:
            income_data = IncomeCalculatorService.calculate(ticket, deal)
            # upsert income record
            existing = await db.execute(
                sa_select(IncomeRecord).where(IncomeRecord.ticket_id == ticket.id)
            )
            record = existing.scalar_one_or_none()
            if record:
                for k, v in income_data.items():
                    setattr(record, k, v)
            else:
                db.add(IncomeRecord(**income_data))

        await db.commit()
        await db.refresh(ticket)
        return ticket
