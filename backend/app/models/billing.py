from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Billing(Base):
    """A saved billing for a customer over a date period.

    Snapshot: line_items + totals are computed at save time and stored as-is,
    so a billing stays stable even if the underlying tickets change later.
    Scoped per user: queries filter by tenant_id + created_by_id.
    """
    __tablename__ = "billings"

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    customer_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)

    billing_name:  Mapped[str]        = mapped_column(String(200), nullable=False)
    period_from:   Mapped[date]       = mapped_column(Date, nullable=False)
    period_to:     Mapped[date]       = mapped_column(Date, nullable=False)
    billing_type:  Mapped[str | None] = mapped_column(String(20), nullable=True)   # snapshot: 'reseller' | 'agency'

    total_base:              Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_markup:            Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_additional_markup: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    total_gst:               Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    grand_total:             Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    line_items:    Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at:    Mapped[datetime]    = mapped_column(DateTime, default=datetime.utcnow)
