from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class UserEntity(Base):
    """A billing/legal entity owned by a single user ("My Profile → Entities").

    User-scoped: every user maintains their OWN entities, visible only to them —
    unlike the tenant-shared `entities` table used by User Master / deals.

    WHAT MAKES TWO ENTITIES THE SAME. Code, ignoring case, and GSTIN — both unique per
    owner (migration profile_entity_login_01). NOT the name: a group's entities often share
    one ("yatra" TSI, "yatra" YOL, "yatra" MICE). NOT the PAN either: a GSTIN is the state
    code + the PAN + a 13th character counting that PAN's registrations in that state, so
    one PAN legitimately appears on an entity per state — and even twice in one state.
    """
    __tablename__ = "user_entities"
    __table_args__ = (
        Index("uq_user_entities_user_code_ci", "user_id", text("lower(code)"), unique=True),
        # Partial: rows saved before GST was mandatory still carry NULL.
        Index(
            "uq_user_entities_user_gstin", "user_id", "gst_number", unique=True,
            postgresql_where=text("gst_number IS NOT NULL"),
        ),
    )

    id:         Mapped[int]        = mapped_column(primary_key=True)
    user_id:    Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)

    name:       Mapped[str]        = mapped_column(String(255), nullable=False)
    code:       Mapped[str]        = mapped_column(String(50),  nullable=False)
    address:    Mapped[str | None] = mapped_column(String(500), nullable=True)
    # A GST state name as app.core.india_tax.STATE_NAMES spells it — the form offers only
    # those, and the API canonicalises whatever else arrives. Required on every write that
    # touches it, because the GSTIN's first two characters are checked against it.
    state:      Mapped[str | None] = mapped_column(String(100), nullable=True)
    city:       Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Tax registration, per entity. An entity is a billing/legal unit, so each one
    # carries its own GSTIN (state-specific) and PAN — they are not inherited from
    # the tenant, which only records the signup's own numbers.
    #
    # MANDATORY, and cross-checked (state ↔ GSTIN chars 1-2, PAN ↔ chars 3-12, check
    # digit) — but enforced in api/v1/user_entities.py, not as NOT NULL: rows saved before
    # the rule have neither, and their owner must still be able to open and fix them.
    gst_number: Mapped[str | None] = mapped_column(String(15),  nullable=True)
    pan_number: Mapped[str | None] = mapped_column(String(10),  nullable=True)

    is_active:  Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
