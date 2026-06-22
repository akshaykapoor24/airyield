from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Numeric, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TicketCalculation(Base):
    """History record for each calculation run on an uploaded ticket."""
    __tablename__ = "ticket_calculations"

    id:                  Mapped[int]          = mapped_column(primary_key=True)
    ticket_id:           Mapped[int]          = mapped_column(Integer, ForeignKey("uploaded_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    batch_id:            Mapped[str]          = mapped_column(String(100), nullable=False, index=True)
    tenant_id:           Mapped[int]          = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    deal_id:             Mapped[int | None]   = mapped_column(Integer, nullable=True)
    deal_type:           Mapped[str | None]   = mapped_column(String(20), nullable=True)
    deal_name:           Mapped[str | None]   = mapped_column(String(300), nullable=True)
    incentive_breakdown: Mapped[dict | None]  = mapped_column(JSONB, nullable=True)
    total_incentive:     Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    ticket_status:       Mapped[str]          = mapped_column(String(10), nullable=False)
    exclusion_reason:    Mapped[str | None]   = mapped_column(String(500), nullable=True)
    calculated_at:       Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)
    calculated_by_id:    Mapped[int | None]   = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
