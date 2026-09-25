"""Writing and reading in-app notifications (models/notification.py).

`notify` is idempotent on (tenant_id, dedupe_key): calling it twice with the same key
writes one row. Everything that raises notifications from a scan relies on that — see
services/series/reminders.py.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationRead
from app.models.series import SeriesDeadline
from app.models.user import User


async def notify(
    db: AsyncSession, *, tenant_id: int | None, category: str, kind: str, title: str,
    dedupe_key: str, severity: str = "info", body: str | None = None,
    link: str | None = None, due_date: date | None = None, user_id: int | None = None,
    source_type: str | None = None, source_id: int | None = None,
) -> None:
    """Write a notification unless one with this key already exists. Never commits."""
    await db.execute(
        pg_insert(Notification)
        .values(
            tenant_id=tenant_id, user_id=user_id, category=category, kind=kind,
            severity=severity, title=title[:200], body=(body or None) and body[:500],
            link=link, due_date=due_date, source_type=source_type, source_id=source_id,
            dedupe_key=dedupe_key[:200],
        )
        .on_conflict_do_nothing(constraint="uq_notifications_tenant_dedupe")
    )


def _visible_to(user: User):
    """Addressed to this person, or to the whole workspace."""
    return and_(
        Notification.tenant_id == user.tenant_id,
        or_(Notification.user_id.is_(None), Notification.user_id == user.id),
    )


def _still_relevant():
    """A deadline reminder whose deadline has since been met, waived, or regenerated away
    is noise. Checked on read rather than by deleting rows, so the history survives."""
    return or_(
        Notification.source_type.is_distinct_from("series_deadline"),
        exists().where(and_(
            SeriesDeadline.id == Notification.source_id,
            SeriesDeadline.status == "open",
        )),
    )


def _read_by(user: User):
    return exists().where(and_(
        NotificationRead.notification_id == Notification.id,
        NotificationRead.user_id == user.id,
    ))


async def list_for(db: AsyncSession, user: User, *, category: str | None = None,
                   unread_only: bool = False, limit: int = 30) -> tuple[list[tuple[Notification, bool]], int]:
    """(rows with their read flag, unread count) for one person, newest first."""
    base = [_visible_to(user), _still_relevant()]
    if category:
        base.append(Notification.category == category)

    read_flag = _read_by(user)
    query = select(Notification, read_flag.label("is_read")).where(*base)
    if unread_only:
        query = query.where(~read_flag)
    query = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    rows = [(n, bool(is_read)) for n, is_read in (await db.execute(query)).all()]

    unread = await db.scalar(select(func.count()).select_from(Notification).where(*base, ~read_flag))
    return rows, int(unread or 0)


async def mark_read(db: AsyncSession, user: User, ids: list[int] | None = None,
                    *, category: str | None = None) -> int:
    """Mark the given notifications (or every visible unread one) read for this person."""
    query = select(Notification.id).where(_visible_to(user), ~_read_by(user))
    if ids is not None:
        query = query.where(Notification.id.in_(ids))
    if category:
        query = query.where(Notification.category == category)
    targets = list((await db.execute(query)).scalars())
    if not targets:
        return 0
    await db.execute(
        pg_insert(NotificationRead)
        .values([{"tenant_id": user.tenant_id, "notification_id": nid, "user_id": user.id} for nid in targets])
        .on_conflict_do_nothing(constraint="uq_notification_reads_user")
    )
    return len(targets)
