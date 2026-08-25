from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, UniqueConstraint, inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AgencyEntity(Base):
    """A billing/legal entity belonging to one of a user's agencies
    ("Agency Profile → Agency Onboarding → Agency Entities").

    User-scoped and parented to an Agency: one agency -> many entities
    (e.g. Lords Delhi has a head office and a sales office). `code` is unique per
    agency, so two agencies can each reuse the same code.

    `channels` IS A SCOPE, NOT A DISCRIMINATOR — and the difference matters.
    A legal entity does not acquire a second GSTIN because a booking went through
    a GDS, so one entity says which channels it trades on (GDS | LCC | BOTH)
    rather than being duplicated once per channel. Duplicating would have meant
    widening `uq_agency_entities_agency_code` to include the channel, and two
    live consumers cannot survive that: the bulk `entity_lookup` in
    agency_login_ids.py is keyed (agency_id, code|name) with .setdefault, so
    duplicate codes would silently attach every LCC login id to the GDS entity;
    and deals/new resolves an entity by NAME, because `Deal.entity` stores a name
    and not an id. An entity's scope must be covered by its agency's — see
    scope_covers in app.models.agency.
    """
    __tablename__ = "agency_entities"
    __table_args__ = (
        UniqueConstraint("agency_id", "code", name="uq_agency_entities_agency_code"),
    )

    id:         Mapped[int]        = mapped_column(primary_key=True)
    user_id:    Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    agency_id:  Mapped[int]        = mapped_column(Integer, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)

    name:       Mapped[str]        = mapped_column(String(255), nullable=False)
    code:       Mapped[str]        = mapped_column(String(50),  nullable=False)
    channels:   Mapped[str]        = mapped_column(String(10),  nullable=False)   # GDS | LCC | BOTH
    address:    Mapped[str | None] = mapped_column(String(500), nullable=True)
    state:      Mapped[str | None] = mapped_column(String(100), nullable=True)
    city:       Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_active:  Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agency: Mapped["Agency"] = relationship("Agency", lazy="raise")   # noqa: F821

    @property
    def agency_name(self) -> str | None:
        """Resolved agency name; None when agency isn't eager-loaded (avoids an
        illegal async lazy-load). Load with selectinload(AgencyEntity.agency)."""
        if "agency" in sa_inspect(self).unloaded:
            return None
        return self.agency.name if self.agency else None
