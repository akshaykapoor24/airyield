import enum
from datetime import datetime
from sqlalchemy import String, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TenantType(str, enum.Enum):
    CORPORATE  = "corporate"    # company workspace, discovered by work-email domain
    INDIVIDUAL = "individual"   # private single-person workspace (public email allowed)


class Tenant(Base):
    __tablename__ = "tenants"

    id:          Mapped[int]      = mapped_column(primary_key=True)
    tenant_type: Mapped[TenantType] = mapped_column(
                                          SAEnum(TenantType, native_enum=False),
                                          nullable=False,
                                          default=TenantType.CORPORATE,   # name-based storage, like users.role
                                      )
    # corporate tenants are keyed on the company domain (unique); individual
    # tenants have no shared domain → NULL. Postgres treats NULLs as distinct
    # under the unique constraint, so many individual tenants can coexist.
    domain:      Mapped[str|None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    name:        Mapped[str|None] = mapped_column(String(255), nullable=True)
    pan_number:  Mapped[str|None] = mapped_column(String(20), nullable=True)
    gst_number:  Mapped[str|None] = mapped_column(String(20), nullable=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship("User", back_populates="tenant")  # noqa: F821
