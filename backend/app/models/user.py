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


def role_matches(role, *targets: UserRole) -> bool:
    """Compare a user's role against one or more UserRole members, tolerantly.

    The users.role column is SAEnum(native_enum=False) with no values_callable,
    so it persists the enum NAME ("PLATFORM_ADMIN") rather than its value. Most
    reads come back as a UserRole member, but raw-SQL paths (create_platform_admin.py)
    and a few call sites hand back a bare string in either casing. This collapses
    all of that, and is the same reasoning behind require_role's token sets.
    """
    if role is None:
        return False
    tokens = {role}
    if isinstance(role, UserRole):
        tokens |= {role.name, role.value, role.name.lower(), role.value.lower(),
                   role.name.upper(), role.value.upper()}
    else:
        s = str(role)
        tokens |= {s, s.lower(), s.upper()}

    for target in targets:
        if not tokens.isdisjoint({
            target, target.name, target.value,
            target.name.lower(), target.value.lower(),
            target.name.upper(), target.value.upper(),
        }):
            return True
    return False


def _is_platform_admin_role(role) -> bool:
    return role_matches(role, UserRole.PLATFORM_ADMIN)


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
    # Instant this user's password last changed. get_current_user rejects any
    # access token whose `iat` predates it, so a password change signs out every
    # other session. NULL means "never observed" and the check is skipped — which
    # is why deploying this signed nobody out.
    # Always write it truncated to whole seconds (microsecond=0): jose floors the
    # `iat` claim, so sub-second precision here would make a token minted just
    # AFTER the change compare as older and log out the session that made it.
    password_changed_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    # email verification: signup creates an unverified account; login is blocked
    # until the emailed verification link flips this to True.
    is_verified:     Mapped[bool]     = mapped_column(Boolean, default=False, nullable=False)
    # first-login onboarding wizard (user info → entities → login ids) completion.
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
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

    # ── Subscription, derived from the tenant ────────────────────────────────
    # The plan is bought per workspace, so these three just read through to the
    # tenant. They exist so UserRead can carry the state to the browser in the
    # login response and on /users/me.
    @property
    def plan_active(self) -> bool:
        """Whether this user's workspace may use the product.

        A platform admin has no tenant by design and is never subject to the
        paywall — it owns global master data, not a customer workspace.

        Returns True when `tenant` is unloaded. This property is a *display*
        value; the enforcing check lives in get_current_user, which always
        eager-loads the tenant. Failing open here only affects endpoints that
        serialize other people's users (the admin list), where the field is
        cosmetic — it never widens access.
        """
        if _is_platform_admin_role(self.role):
            return True
        if "tenant" in sa_inspect(self).unloaded:
            return True
        return bool(self.tenant and self.tenant.has_active_plan)

    @property
    def plan_status(self) -> str | None:
        if "tenant" in sa_inspect(self).unloaded or not self.tenant:
            return None
        status = self.tenant.plan_status
        return getattr(status, "value", status)

    @property
    def plan_expires_at(self) -> datetime | None:
        if "tenant" in sa_inspect(self).unloaded:
            return None
        return self.tenant.plan_expires_at if self.tenant else None
