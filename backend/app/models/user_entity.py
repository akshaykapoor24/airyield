from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class UserEntity(Base):
    """A billing/legal entity owned by a single user ("My Profile → Entities").

    User-scoped: every user maintains their OWN entities, visible only to them —
    unlike the tenant-shared `entities` table used by User Master / deals. `code`
    is unique per owning user.
    """
    __tablename__ = "user_entities"
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_user_entities_user_code"),
    )

    id:         Mapped[int]        = mapped_column(primary_key=True)
    user_id:    Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)

    name:       Mapped[str]        = mapped_column(String(255), nullable=False)
    code:       Mapped[str]        = mapped_column(String(50),  nullable=False)
    address:    Mapped[str | None] = mapped_column(String(500), nullable=True)
    state:      Mapped[str | None] = mapped_column(String(100), nullable=True)
    city:       Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_active:  Mapped[bool]       = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
