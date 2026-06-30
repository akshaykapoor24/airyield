from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class LoginId(Base):
    """An airline-portal login id / IATA code maintained per tenant
    ("User Master → Login IDs / IATA").

    Tenant-scoped. vendor_id references a row in the (global) suppliers master.
    """
    __tablename__ = "login_ids"

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    login_id:      Mapped[str]        = mapped_column(String(100), nullable=False, index=True)  # "Login ID / IATA Code"
    airline_name:  Mapped[str | None] = mapped_column(String(255), nullable=True)
    airline_code:  Mapped[str | None] = mapped_column(String(20),  nullable=True)
    lob:           Mapped[str | None] = mapped_column(String(100), nullable=True)               # line of business (free text)
    vendor_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)

    is_active:     Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor: Mapped["Supplier"] = relationship("Supplier", lazy="raise")  # noqa: F821

    @property
    def vendor_name(self) -> str | None:
        """Resolved supplier name; None when vendor isn't eager-loaded (avoids
        an illegal async lazy-load). Load with selectinload(LoginId.vendor)."""
        if "vendor" in sa_inspect(self).unloaded:
            return None
        return self.vendor.name if self.vendor else None
