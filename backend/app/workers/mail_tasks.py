"""Celery: check every connected mailbox for new mail from onboarded senders.

Scheduled by celery beat every MAIL_POLL_MINUTES (see celery_app.py) on its own `mail` queue,
so a mailbox check never waits behind a 2,000-page BSP parse. Per-mailbox locking lives in
services/mail/sync.py, so an overlapping run (or a user's "Check now") cannot double-import.

Uses a per-task NullPool engine, like the BSP and LCC tasks: asyncio.run builds a new event
loop per task, and a pooled asyncpg connection is bound to the loop that opened it.
"""
import asyncio
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _new_session_factory():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _sync_all() -> dict:
    from app.services.mail import sync

    engine, Session = _new_session_factory()
    try:
        async with Session() as db:
            return await sync.sync_all(db)
    finally:
        await engine.dispose()


@celery_app.task(name="mail.sync_all", queue="mail", ignore_result=True,
                 soft_time_limit=20 * 60, time_limit=21 * 60)
def sync_all():
    from app.config import settings
    if not settings.MAIL_INTAKE_ENABLED:
        return {"skipped": "MAIL_INTAKE_ENABLED is false"}
    summary = asyncio.run(_sync_all())
    if summary.get("new_messages") or summary.get("errors"):
        logger.info("[mail] sync_all %s", summary)
    return summary
