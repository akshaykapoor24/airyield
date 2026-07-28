from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Agency(Base):
    """An agency owned by a single user ("Agency Profile → Agency Onboarding → Agency Info").

    User-scoped: every user maintains their OWN set of agencies (the ones they
    work with), visible only to them. Agency details are COPIED from the global
    suppliers master at add-time — there is no live foreign key back to a supplier.
    `name` is unique per owning user so the "add from Supplier Master" multi-pick
    is idempotent (re-adding an existing agency is skipped, not duplicated).
    """
    __tablename__ = "agencies"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_agencies_user_name"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    user_id:       Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)

    name:          Mapped[str]        = mapped_column(String(255), nullable=False)   # copied from supplier.name
    vendor_type:   Mapped[str | None] = mapped_column(String(100), nullable=True)
    gst_number:    Mapped[str | None] = mapped_column(String(20),  nullable=True)
    pan_number:    Mapped[str | None] = mapped_column(String(20),  nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50),  nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes:         Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active:     Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
