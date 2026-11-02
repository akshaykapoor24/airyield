"""Celery tasks for Internal Statement's background upload (services/internal_import.py).

`POST /internal-tickets/imports/{id}/parse` and `…/save` commit the job with a new `attempt`
before enqueueing, so the job row — not the message — is the source of truth. Each task claims
the job for its attempt and stops quietly when the attempt has moved on (the user read the file
again, or discarded it): `Superseded`.

NO AUTOMATIC RETRY. A file that failed to read fails the same way again, and a save that failed
is back under review with its reason — the user decides what to do. With acks_late a message
whose worker died is not redelivered (reject_on_worker_lost is off), and the page shows the job
stuck at its phase; reading or saving again starts a fresh attempt.

Run a worker with:
    celery -A app.workers.celery_app.celery_app worker -l info -Q imports -c 2
    (add --pool=solo on Windows dev)
"""
import asyncio
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# The save's code (Internal Statement's copy of tickets.py) is loaded when the worker starts,
# with the rest — not at its first save. Loaded late, a worker started before a code change ran
# the newer save over the older ticket schema it had loaded at start ("'TicketRow' object has
# no attribute 'cancellation_date'"). A worker runs the code it started with: restart it after
# a change.
import app.api.v1.internal_tickets  # noqa: E402,F401


def _new_engine():
    """Fresh NullPool async engine, safe inside this task's own event loop (as bsp_tasks)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _run(step: str, import_id: str, attempt: int) -> None:
    from app.services import internal_import as imp

    engine, Session = _new_engine()
    status = "parsing" if step == "parse" else "saving"
    try:
        if step == "parse":
            # Housekeeping first, while nothing of this run is held: imports left alone go.
            try:
                async with Session() as db:
                    await imp.purge_expired(db)
            except Exception:  # noqa: BLE001 — never a reason not to read the file
                logger.warning("Purging expired imports failed", exc_info=True)
            await imp.run_parse(Session, import_id, attempt)
        else:
            await imp.run_save(Session, import_id, attempt)
    except imp.Superseded:
        logger.info("Import %s attempt %s superseded — stopping", import_id, attempt)
    except Exception as exc:  # noqa: BLE001 — said to the user; the log has the trace
        logger.exception("Import %s %s failed", import_id, step)
        what = "read" if step == "parse" else "saved"
        await imp.fail(Session, import_id, attempt, status, f"The file could not be {what}: {imp.short_error(exc)}")
    finally:
        await engine.dispose()


@celery_app.task(bind=True, acks_late=True, queue="imports")
def parse_internal_import(self, import_id: str, attempt: int):
    asyncio.run(_run("parse", import_id, attempt))


@celery_app.task(bind=True, acks_late=True, queue="imports")
def save_internal_import(self, import_id: str, attempt: int):
    asyncio.run(_run("save", import_id, attempt))
