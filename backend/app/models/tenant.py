import enum
from datetime import datetime
from sqlalchemy import String, DateTime, Integer, Text, Enum as SAEnum
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
    # Which GST BASIS this workspace bills on — 'abatement' | 'normal', see
    # GST_SCHEMES in models/gst_configuration.py. An election, not a rate: the
    # rates live in the global master, so a platform-side revision reaches every
    # workspace without touching this column.
    # It does not name a single rule. Each scheme spans two, and what picks
    # between them is not stored here: a ticket's SECTOR for abatement, and the
    # customer's own billing_type ('agency' | 'reseller') for normal.
    # NULL means "not elected yet" and must never be read as a scheme.
    # A plain String, matching corporates.billing_type rather than the SAEnum
    # used by tenant_type/plan_status — adding a fourth scheme stays a code change.
    gst_scheme:  Mapped[str|None] = mapped_column(String(20), nullable=True)

    # ── Letterhead: what a printed document says about the workspace ─────────
    # The workspace's own registered address — the FROM block of an invoice, as
    # opposed to the BILL TO block that comes from the customer/corporate row.
    # Named to match corporates.address / city / state / pincode / country so
    # the two sides of an invoice are read the same way.
    address:     Mapped[str|None] = mapped_column(Text, nullable=True)
    city:        Mapped[str|None] = mapped_column(String(120), nullable=True)
    state:       Mapped[str|None] = mapped_column(String(100), nullable=True)
    pincode:     Mapped[str|None] = mapped_column(String(20), nullable=True)
    country:     Mapped[str|None] = mapped_column(String(100), nullable=True)
    # The business's line, printed at the head of an invoice. Free text and wide
    # enough for two numbers, which is how a letterhead usually carries them —
    # distinct from users.email, which identifies a person rather than the firm.
    phone:       Mapped[str|None] = mapped_column(String(100), nullable=True)

    # The logo IMAGE is not in this row — only a locator for it. get_current_user
    # selectinloads User.tenant on every authenticated request, so an inline
    # base64 column would ride along with all of them. `logo_path` is a
    # services/file_store locator (a GCS blob name, or "local://…" when GCS is
    # unavailable); the other three are what the UI needs to describe the file
    # and what the download endpoint replies with, without fetching the bytes.
    logo_path:   Mapped[str|None] = mapped_column(String(500), nullable=True)
    logo_name:   Mapped[str|None] = mapped_column(String(255), nullable=True)
    logo_mime:   Mapped[str|None] = mapped_column(String(100), nullable=True)
    logo_size:   Mapped[int|None] = mapped_column(Integer, nullable=True)

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
