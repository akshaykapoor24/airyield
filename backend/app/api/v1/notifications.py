"""The header bell.

Reading the bell is also what raises due reminders: there is no scheduler in this stack,
so the moment someone could see a reminder is the moment it is worth writing one. The
scan is throttled per tenant and idempotent (services/series/reminders.py).
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.notification import MarkRead, NotificationList, NotificationRead
from app.services import notifications as svc
from app.services.series import reminders

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/", response_model=NotificationList)
async def list_notifications(
    category: Optional[str] = Query(None),
    unread_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        if await reminders.sync_tenant(db, current_user.tenant_id, today=datetime.utcnow().date()):
            await db.commit()
    except Exception:  # noqa: BLE001 — the bell must open even if the scan fails
        await db.rollback()
        logger.exception("reminder scan failed tenant=%s", current_user.tenant_id)

    rows, unread = await svc.list_for(
        db, current_user, category=category, unread_only=unread_only, limit=limit,
    )
    return NotificationList(
        items=[
            NotificationRead(
                id=n.id, category=n.category, kind=n.kind, severity=n.severity,
                title=n.title, body=n.body, link=n.link, due_date=n.due_date,
                created_at=n.created_at, read=is_read,
            )
            for n, is_read in rows
        ],
        unread_count=unread,
    )


@router.post("/read")
async def mark_read(
    payload: MarkRead,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark some (ids) or all visible notifications read for the current user."""
    count = await svc.mark_read(db, current_user, payload.ids, category=payload.category)
    await db.commit()
    return {"marked": count}
