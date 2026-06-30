import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum as SAEnum, Integer, inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class UserRole(str, enum.Enum):
    PLATFORM_ADMIN  = "platform_admin"   # one globally, manages master data, no tenant
    SUPER_ADMIN     = "super_admin"      # one per company, first signup from domain
    COMPANY_ADMIN   = "company_admin"
    OPERATIONS_USER = "operations_user"
    FINANCE_USER    = "finance_user"
    APPROVER        = "approver"
    VIEWER          = "viewer"


class User(Base):
    __tablename__ = "users"

    id:              Mapped[int]      = mapped_column(primary_key=True)
    email:           Mapped[str]      = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name:       Mapped[str]      = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str]      = mapped_column(String(255), nullable=False)
    role:            Mapped[UserRole] = mapped_column(
                                           SAEnum(UserRole, native_enum=False),
                                           default=UserRole.VIEWER,
                                       )
    department:      Mapped[str|None] = mapped_column(String(100), nullable=True)
    is_active:       Mapped[bool]     = mapped_column(Boolean, default=True)
    tenant_id:       Mapped[int|None] = mapped_column(
                                           Integer,
                                           ForeignKey("tenants.id", ondelete="SET NULL"),
                                           nullable=True,
                                           index=True,
                                       )
    created_at:      Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:      Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")  # noqa: F821

    @property
    def tenant_type(self) -> str | None:
        """Derived 'corporate'|'individual' from the related tenant.

        Returns None when the tenant relationship is not eager-loaded, so that
        serialization never triggers an (illegal) async lazy-load. Callers that
        need the value should load the user with selectinload(User.tenant).
        """
        if "tenant" in sa_inspect(self).unloaded:
            return None
        return self.tenant.tenant_type.value if self.tenant else None
