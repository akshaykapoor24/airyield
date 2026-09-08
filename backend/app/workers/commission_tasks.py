"""Celery task for a vendor commission run on a non-BSP statement.

The BSP twin is `workers/bsp_commission_tasks.py` and this deliberately mirrors it,
including the per-task NullPool engine (the FastAPI asyncpg pool is not safe across the
fresh event loop `asyncio.run` builds per task, nor across a prefork).

TAKES A run_id, NOT A BATCH. The API creates the `commission_runs` row and commits it
BEFORE enqueueing — exactly as `/bsp-commission/.../run` flips the statement to "queued"
before calling `.delay()`. That gives the task a natural idempotency key, makes the
"already running" check a one-row lookup, and means a broker that never delivers leaves a
visible queued run rather than silence.

Run a worker with:
    celery -A app.workers.celery_app.celery_app worker -l info -Q commission
    (add --pool=solo on Windows dev)
"""
import asyncio
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, acks_late=True, queue="commission")
def run_commission(self, run_id: int):
    try:
        asyncio.run(_run(run_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("commission run %s failed", run_id)
        try:
            asyncio.run(_mark_failed(run_id, str(exc)))
        except Exception:  # noqa: BLE001
            logger.exception("could not mark commission run %s failed", run_id)
        raise self.retry(exc=exc, countdown=min(60 * (self.request.retries + 1), 600))


def _new_engine():
    """Fresh NullPool async engine, safe inside this task's own event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return engine, Session


async def _run(run_id: int):
    from sqlalchemy import select
    from app.models.commission_run import CommissionRun
    from app.services.commission import CommissionRunner, get_adapter

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            run = (await db.execute(
                select(CommissionRun).where(CommissionRun.id == run_id)
            )).scalar_one_or_none()
            if run is None:
                logger.warning("commission run %s no longer exists", run_id)
                return
            adapter = get_adapter(run.source)
            if adapter is None:
                run.status = "failed"
                run.error = f"No commission adapter registered for source '{run.source}'."
                await db.commit()
                return

            await CommissionRunner(adapter).run(db, run)
            logger.info(
                "commission %s/%s: %d rows — %d calculated, %d reversed, %d excluded, "
                "%d needs-data, %d skipped, %d unmatched, total %.2f, variance %.2f",
                run.source, run.batch_id, run.total_rows, run.calculated_rows,
                run.reversed_rows, run.excluded_rows, run.needs_data_rows,
                run.skipped_rows, run.unmatched_rows,
                float(run.total_incentive or 0), float(run.variance_total or 0),
            )
    finally:
        await engine.dispose()


async def _mark_failed(run_id: int, message: str):
    from sqlalchemy import update
    from app.models.commission_run import CommissionRun

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            async with db.begin():
                await db.execute(
                    update(CommissionRun)
                    .where(CommissionRun.id == run_id)
                    .values(status="failed", error=(message or "")[:2000])
                )
    finally:
        await engine.dispose()
