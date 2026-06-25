from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Numeric, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Customer(Base):
    """A customer maintained privately by an agency user ("My Customers").

    Scoped per user: queries always filter by tenant_id + created_by_id.
    Markup config (type/value) is applied to the customer's sold tickets.
    """
    __tablename__ = "customers"

    id:            Mapped[int]      = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    first_name:    Mapped[str]        = mapped_column(String(200), nullable=False)
    last_name:     Mapped[str | None] = mapped_column(String(200), nullable=True)
    company:       Mapped[str | None] = mapped_column(String(255), nullable=True)
    title:         Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone:         Mapped[str | None] = mapped_column(String(50),  nullable=True)
    email:         Mapped[str | None] = mapped_column(String(255), nullable=True)
    gst_no:        Mapped[str | None] = mapped_column(String(30),  nullable=True)

    markup_type:   Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'percentage' | 'fixed'
    markup_value:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    billing_type:  Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'reseller' | 'agency'

    is_active:     Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
