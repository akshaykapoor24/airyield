from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class NotificationRead(BaseModel):
    id: int
    category: str
    kind: str
    severity: str
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    due_date: Optional[date] = None
    created_at: Optional[datetime] = None
    read: bool = False


class NotificationList(BaseModel):
    items: list[NotificationRead] = []
    unread_count: int = 0


class MarkRead(BaseModel):
    # None = every visible unread notification (optionally within `category`).
    ids: Optional[list[int]] = None
    category: Optional[str] = None
