import enum
from datetime import datetime
from sqlalchemy import String, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TenantType(str, enum.Enum):
    CORPORATE  = "corporate"    # company workspace, discovered by work-email domain
    INDIVIDUAL = "individual"   # private single-person workspace (public email allowed)


class PlanStatus(str, enum.Enum):
    """Whether this workspace has paid for AirYield.

    Not to be confused with `app/models/billing.py`, which is the *product's*
    invoicing feature (an agency billing its own customers). This is the agency
    paying us.
    """
    FREE      = "free"        # signed up, never paid — frozen out of the product
    TRIAL     = "trial"        # reserved; no code path issues one yet
    ACTIVE    = "active"       # paying
    EXPIRED   = "expired"      # was active, lapsed
    SUSPENDED = "suspended"    # switched off deliberately (non-payment, abuse)


# Store the enum VALUE ("free"), not its NAME ("FREE"). users.role omits this and
# therefore stores names, which is why require_role has to compare seven case
# variants — see dependencies.py. Deal.status sets it; follow that one.
def _vals(e) -> list[str]:
    return [m.value for m in e]


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

    # ── Subscription ─────────────────────────────────────────────────────────
    # The tenant is the sellable unit: one agency signs up as super_admin and
    # invites its team, so the plan is bought once for the whole workspace.
    # A new signup lands on FREE and is frozen until a platform admin activates
    # it from /admin/subscriptions.
    plan_status: Mapped[PlanStatus] = mapped_column(
                                          SAEnum(PlanStatus, native_enum=False, values_callable=_vals),
                                          nullable=False,
                                          default=PlanStatus.FREE,
                                          server_default="free",
                                          index=True,
                                      )
    # NULL means "no expiry". Evaluated live in has_active_plan, so a lapsed plan
    # freezes on the next request without a cron job flipping the status.
    plan_expires_at:   Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    plan_activated_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    # internal note for whoever flipped it, e.g. "12m, invoice #1042". Never shown
    # to the tenant.
    plan_note:         Mapped[str|None]      = mapped_column(String(255), nullable=True)

    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship("User", back_populates="tenant")  # noqa: F821

    @property
    def has_active_plan(self) -> bool:
        """The single definition of "this workspace may use the product".

        Enforced server-side in get_current_user; everything else (the frozen
        screen, the admin console chips) only reports it.
        """
        if self.plan_status not in (PlanStatus.ACTIVE, PlanStatus.TRIAL):
            return False
        return self.plan_expires_at is None or self.plan_expires_at > datetime.utcnow()
