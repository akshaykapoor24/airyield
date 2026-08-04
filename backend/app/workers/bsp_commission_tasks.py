"""
Celery task for the BSP commission-income calculation.

A BSP settlement statement can hold ~50k rows, and each row runs a full deal
search, so the calculation cannot live inside an HTTP request. `POST
/bsp-commission/statements/{id}/run` flips the statement to `queued` and enqueues
this task; the worker advances `commission_processed_rows`, which the frontend
polls for the progress bar.

Notes:
  * Uses a per-task NullPool async engine, for the same reason `bsp_tasks` does —
    the FastAPI asyncpg pool is not safe across the fresh event loop
    `asyncio.run` builds for each task, nor across a prefork.
  * Idempotent: every run resets and recomputes the whole statement.
  * Run a worker with:  celery -A app.workers.celery_app.celery_app worker -l info -Q bsp
    (add --pool=solo on Windows dev).
"""
import asyncio
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, acks_late=True, queue="bsp")
def calculate_bsp_commission(self, batch_id: str, tenant_id: int, user_id: int):
    try:
        asyncio.run(_calculate(batch_id, tenant_id, user_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("BSP commission run failed for batch %s", batch_id)
        try:
            asyncio.run(_mark_failed(batch_id, tenant_id, str(exc)))
        except Exception:  # noqa: BLE001
            logger.exception("could not mark BSP commission run %s failed", batch_id)
        raise self.retry(exc=exc, countdown=min(60 * (self.request.retries + 1), 600))


def _new_engine():
    """Fresh NullPool async engine, safe inside this task's own event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return engine, Session


async def _calculate(batch_id: str, tenant_id: int, user_id: int):
    from app.services.bsp_commission import BspCommissionService

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            summary = await BspCommissionService.run(
                db, batch_id=batch_id, tenant_id=tenant_id, created_by_id=user_id,
            )
            logger.info(
                "BSP commission %s: %d rows — %d calculated, %d reversed, %d excluded, "
                "%d skipped, %d unmatched, %d errors, total ₹%.2f",
                batch_id, summary.total, summary.calculated, summary.reversed_,
                summary.excluded, summary.skipped, summary.unmatched, summary.errors,
                summary.total_incentive,
            )
    finally:
        await engine.dispose()


async def _mark_failed(batch_id: str, tenant_id: int, message: str):
    from sqlalchemy import update
    from app.models.bsp_statement import BspStatement

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            async with db.begin():
                await db.execute(
                    update(BspStatement)
                    .where(BspStatement.batch_id == batch_id, BspStatement.tenant_id == tenant_id)
                    .values(commission_status="failed", commission_error=(message or "")[:2000])
                )
    finally:
        await engine.dispose()
