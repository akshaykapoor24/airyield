from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, Index, text, inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class UserLoginId(Base):
    """A login ID / IATA number held by one of the user's entities
    ("My Profile → Login IDs / IATA").

    User-scoped: visible only to its owner. One entity → many login IDs; the form picks
    the entity first and adds any number under it.

    LOCATED BY ITS ENTITY. An IATA code is issued to an accredited LOCATION, so a login
    carries where it is — but only half of that is its own:
      * STATE is the entity's, always, and is not stored here. An entity is one GST
        registration and a GSTIN belongs to one state, so an office in another state is
        another registration — another entity. A stored copy could only drift.
      * CITY may be its own. One entity can run IATA-coded offices in several cities of its
        state (Mumbai and Pune under one Maharashtra GSTIN). NULL means "the entity's
        city", so fixing the entity's city fixes every login that never overrode it.

    NO AIRLINE, LOB OR VENDOR any more (dropped in profile_entity_login_01): nothing
    outside My Profile read them, and a login is now identified by entity alone.

    `login_id` IS UNIQUE per owner ignoring case, across ALL their entities — an IATA code
    belongs to one office of one entity, so a second copy is always a mistake.
    """
    __tablename__ = "user_login_ids"
    __table_args__ = (
        Index("uq_user_login_ids_user_login_ci", "user_id", text("lower(login_id)"), unique=True),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    user_id:       Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)

    login_id:      Mapped[str]        = mapped_column(String(100), nullable=False, index=True)  # "Login ID / IATA Number"
    # Required on every create and edit (API-enforced). Nullable only because a row saved
    # before the rule may have none. CASCADE (profile_login_cascade_01): a login ID belongs
    # to its entity, so deleting the entity deletes it — SET NULL used to leave orphans with
    # no entity and no state.
    entity_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("user_entities.id", ondelete="CASCADE"), nullable=True, index=True)
    city:          Mapped[str | None] = mapped_column(String(100), nullable=True)   # NULL = the entity's city

    is_active:     Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    entity: Mapped["UserEntity"]  = relationship("UserEntity", lazy="raise")   # noqa: F821

    def _entity_attr(self, attr: str) -> str | None:
        """One attribute of the entity; None when it isn't eager-loaded (avoids an illegal
        async lazy-load — load with selectinload(UserLoginId.entity)) or there is none."""
        if "entity" in sa_inspect(self).unloaded or self.entity is None:
            return None
        return getattr(self.entity, attr)

    @property
    def entity_name(self) -> str | None:
        return self._entity_attr("name")

    @property
    def entity_code(self) -> str | None:
        return self._entity_attr("code")

    @property
    def entity_state(self) -> str | None:
        """This login's state — always its entity's (see the class docstring)."""
        return self._entity_attr("state")

    @property
    def entity_city(self) -> str | None:
        """The city this login falls back to when `city` is NULL."""
        return self._entity_attr("city")
