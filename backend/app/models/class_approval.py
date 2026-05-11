from datetime import datetime
from sqlalchemy import String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ClassApproval(Base):
    __tablename__ = "class_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    airline_name: Mapped[str] = mapped_column(String(255), nullable=False)
    class_type: Mapped[str] = mapped_column(String(50), nullable=False)
    class_code: Mapped[str] = mapped_column(String(10), nullable=False)
    airline_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    class_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending")

    submitted_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    reviewed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_by: Mapped["User"] = relationship("User", foreign_keys=[submitted_by_id])  # noqa: F821
    reviewed_by: Mapped["User"] = relationship("User", foreign_keys=[reviewed_by_id])  # noqa: F821

    # new vs update distinction
    request_type:    Mapped[str]      = mapped_column(String(10), default="new")
    target_class_id: Mapped[int|None] = mapped_column(
        Integer, ForeignKey("airline_class_masters.id", ondelete="SET NULL"), nullable=True
    )
