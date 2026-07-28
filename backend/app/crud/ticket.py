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
        # Legacy path: the legacy_deals table has been removed, so there is no deal to
        # look up and no income record to compute here. Kept for API compatibility.
        ticket.matched_deal_id = deal_id
        ticket.is_manually_matched = True
        await db.commit()
        await db.refresh(ticket)
        return ticket
