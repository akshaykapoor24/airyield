from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AgencyLoginId(Base):
    """A booking credential belonging to one of a user's agencies
    ("Agency Profile → Agency Onboarding → Agency Login IDs").

    User-scoped. Each login id belongs to one agency (one agency -> many login
    ids) and optionally to one of that agency's entities (one entity -> many
    login ids). vendor_id references the (global) suppliers master.

    `channel` IS GDS OR LCC, NEVER BOTH — note the asymmetry with AgencyEntity,
    because it is the thing a reader trips over. An entity may trade on both
    channels; a credential cannot. A mirror id is a GDS artifact and an airline
    portal login is an LCC artifact, and they are not interchangeable.

    `login_id` IS THE CREDENTIAL FOR BOTH CHANNELS, relabelled in the UI —
    "Mirror ID" on GDS, "Login ID / Airline ID" on LCC. It is deliberately not
    split into a `mirror_id` sibling column: this column is NOT NULL and indexed,
    it is the order-by key and the primary display column, it is the option value
    in the deals form (landing in `Deal.login_id` / `Deal.login_ids`), and it is
    snapshotted into `CustomerStatement.login_ids`. Making it nullable so a
    parallel column could exist would break every one of those. `Deal.entity_lcc`
    is the repo's own worked example of that mistake — a per-channel sibling
    column beside `Deal.entity`, now dead code.
    """
    __tablename__ = "agency_login_ids"

    id:            Mapped[int]        = mapped_column(primary_key=True)
    user_id:       Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    agency_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("agency_entities.id", ondelete="SET NULL"), nullable=True, index=True)

    channel:       Mapped[str]        = mapped_column(String(10),  nullable=False)  # GDS | LCC — never BOTH
    login_id:      Mapped[str]        = mapped_column(String(100), nullable=False, index=True)  # mirror id (GDS) | portal login / airline id (LCC)
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
