from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import String, DateTime, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TicketStatement(Base):
    """Metadata for a batch of uploaded tickets (one row per upload session)."""
    __tablename__ = "ticket_statements"

    batch_id:        Mapped[str]          = mapped_column(String(100), primary_key=True)
    tenant_id:       Mapped[int]          = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    statement_type:  Mapped[str]          = mapped_column(String(10), nullable=False, default="B2B")
    statement_name:  Mapped[str | None]   = mapped_column(String(500), nullable=True)
    agency:          Mapped[str]          = mapped_column(String(200), nullable=False)
    valid_from:     Mapped[date]     = mapped_column(Date, nullable=False)
    valid_to:       Mapped[date]     = mapped_column(Date, nullable=False)
    file_name:      Mapped[str]      = mapped_column(String(500), nullable=False)
    file_url:       Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
