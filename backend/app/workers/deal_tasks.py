"""
Celery tasks for async deal processing and ticket batch ingestion.
"""
import asyncio
from app.workers.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def process_ticket_upload(self, file_path: str, batch_id: str, user_id: int):
    """
    Reads the uploaded Excel/CSV ticket file, matches each row to a deal,
    calculates income, and persists IncomeRecord rows.
    """
    try:
        asyncio.run(_process_ticket_upload(file_path, batch_id, user_id))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


async def _process_ticket_upload(file_path: str, batch_id: str, user_id: int):
    import pandas as pd
    from app.database import AsyncSessionLocal
    from app.models.ticket import Ticket
    from app.models.income import IncomeRecord
    from app.services.deal_matching import DealMatchingService
    from app.services.income_calculator import IncomeCalculatorService
    from datetime import date

    df = pd.read_excel(file_path) if file_path.endswith((".xls", ".xlsx")) else pd.read_csv(file_path)

    async with AsyncSessionLocal() as db:
        for _, row in df.iterrows():
            ticket = Ticket(
                ticket_number=str(row["ticket_number"]),
                pnr=str(row.get("pnr", "")),
                airline_id=int(row["airline_id"]),
                booking_class=str(row["booking_class"]),
                travel_date=row["travel_date"],
                issue_date=row.get("issue_date", date.today()),
                passenger_name=str(row.get("passenger_name", "")),
                origin_code=str(row["origin"]),
                destination_code=str(row["destination"]),
                base_fare=float(row["base_fare"]),
                taxes=float(row.get("taxes", 0)),
                total_fare=float(row["total_fare"]),
                currency=str(row.get("currency", "USD")),
                upload_batch_id=batch_id,
                created_by_id=user_id,
            )
            db.add(ticket)
            await db.flush()

            deal = await DealMatchingService.find_best_deal(
                db,
                airline_id=ticket.airline_id,
                supplier_id=ticket.supplier_id,
                booking_class=ticket.booking_class,
                travel_date=ticket.travel_date,
            )

            if deal:
                ticket.matched_deal_id = deal.id
                income_data = IncomeCalculatorService.calculate(ticket, deal)
                income = IncomeRecord(**income_data)
                db.add(income)

        await db.commit()
