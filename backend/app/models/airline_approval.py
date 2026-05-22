from datetime import datetime
from sqlalchemy import String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AirlineApproval(Base):
    __tablename__ = "airline_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    iata_code: Mapped[str] = mapped_column(String(3), nullable=False)
    icao_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    contract_year: Mapped[str | None] = mapped_column(String(2), nullable=True)

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
    request_type:     Mapped[str]      = mapped_column(String(10), default="new")
    target_airline_id: Mapped[int|None] = mapped_column(
        Integer, ForeignKey("airlines.id", ondelete="SET NULL"), nullable=True
    )
