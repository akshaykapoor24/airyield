from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AgencyLoginId(Base):
    """An airline-portal login id / IATA code belonging to one of a user's
    agencies ("Agency Profile → Agency Onboarding → Agency Login IDs").

    User-scoped. Each login id belongs to one agency (one agency -> many login
    ids) and optionally to one of that agency's entities (one entity -> many
    login ids). vendor_id references the (global) suppliers master.
    """
    __tablename__ = "agency_login_ids"

    id:            Mapped[int]        = mapped_column(primary_key=True)
    user_id:       Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    agency_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_entities.id", ondelete="SET NULL"), nullable=True, index=True)

    login_id:      Mapped[str]        = mapped_column(String(100), nullable=False, index=True)  # "Login ID / IATA Code"
    airline_name:  Mapped[str | None] = mapped_column(String(255), nullable=True)
    airline_code:  Mapped[str | None] = mapped_column(String(20),  nullable=True)
    lob:           Mapped[str | None] = mapped_column(String(100), nullable=True)               # line of business (free text)
    vendor_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)

    is_active:     Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor: Mapped["Supplier"]      = relationship("Supplier", lazy="raise")        # noqa: F821
    entity: Mapped["AgencyEntity"]  = relationship("AgencyEntity", lazy="raise")    # noqa: F821
    agency: Mapped["Agency"]        = relationship("Agency", lazy="raise")          # noqa: F821

    @property
    def vendor_name(self) -> str | None:
        """Resolved supplier name; None when vendor isn't eager-loaded (avoids an
        illegal async lazy-load). Load with selectinload(AgencyLoginId.vendor)."""
        if "vendor" in sa_inspect(self).unloaded:
            return None
        return self.vendor.name if self.vendor else None

    @property
    def entity_name(self) -> str | None:
        """Resolved entity name; None when entity isn't eager-loaded."""
        if "entity" in sa_inspect(self).unloaded:
            return None
        return self.entity.name if self.entity else None

    @property
    def entity_code(self) -> str | None:
        """Resolved entity code; None when entity isn't eager-loaded."""
        if "entity" in sa_inspect(self).unloaded:
            return None
        return self.entity.code if self.entity else None

    @property
    def agency_name(self) -> str | None:
        """Resolved agency name; None when agency isn't eager-loaded."""
        if "agency" in sa_inspect(self).unloaded:
            return None
        return self.agency.name if self.agency else None
