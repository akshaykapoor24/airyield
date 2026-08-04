from datetime import datetime
from sqlalchemy import DateTime, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class UserEntityAccess(Base):
    """Which of the admin's entities a team member is assigned to.

    `user_entities` rows are private to the person who created them (the Super
    Admin, during onboarding). When that admin adds a team member under the same
    tenant they pick which of those entities the member works on — that grant is
    this table, so the entity itself stays owned by one user while access to it
    is many-to-many.

    Both sides cascade: deleting the member or the entity drops the grant.
    """
    __tablename__ = "user_entity_access"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_id", name="uq_user_entity_access_user_entity"),
    )

    id:         Mapped[int]      = mapped_column(primary_key=True)
    user_id:    Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("user_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    # Who granted it — the entity's owner. Kept so the grants can be re-scoped or
    # cleaned up if the admin's own entity list changes.
    granted_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
