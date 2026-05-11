from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    domain:     Mapped[str]      = mapped_column(String(255), unique=True, nullable=False, index=True)
    name:       Mapped[str|None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship("User", back_populates="tenant")  # noqa: F821
