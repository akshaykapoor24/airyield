from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Boolean, Integer, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class IataCommission(Base):
    """A per-airline IATA commission row maintained per tenant
    ("User Master → IATA Commission").

    Tenant-scoped. Airline name / code / numeric code are copied from the
    Airline master; the IATA commission % and validity window are user-filled.
    This is a standalone reference master — it does not drive ticket/deal
    calculation.
    """
    __tablename__ = "iata_commissions"

    id:                  Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:           Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id:       Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    airline_name:        Mapped[str]         = mapped_column(String(255), nullable=False, index=True)
    airline_code:        Mapped[str | None]  = mapped_column(String(20),  nullable=True)   # IATA code, e.g. "AI"
    iata_numeric_code:   Mapped[str | None]  = mapped_column(String(10),  nullable=True)   # e.g. "098"
    iata_commission_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    valid_from:          Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to:            Mapped[date | None] = mapped_column(Date, nullable=True)

    is_active:           Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at:          Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:          Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
