from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Entity(Base):
    """A billing/legal entity maintained per tenant ("User Master → Entity").

    Tenant-scoped: queries always filter by tenant_id. code is unique within
    a tenant.
    """
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_entities_tenant_code"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    name:          Mapped[str]        = mapped_column(String(255), nullable=False)
    code:          Mapped[str]        = mapped_column(String(50),  nullable=False)
    address:       Mapped[str | None] = mapped_column(String(500), nullable=True)
    state:         Mapped[str | None] = mapped_column(String(100), nullable=True)
    city:          Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_active:     Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
