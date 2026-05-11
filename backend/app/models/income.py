from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Numeric, Boolean, Text, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class IncomeRecord(Base):
    __tablename__ = "income_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), unique=True, nullable=False)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), nullable=False)

    base_fare: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # Calculated components
    commission_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    override_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    incentive_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total_income: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    currency: Mapped[str] = mapped_column(String(3), default="USD")

    # Manual override support
    is_manual_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    ticket: Mapped["Ticket"] = relationship("Ticket", back_populates="income_record")  # noqa: F821
    deal: Mapped["UploadedDeal"] = relationship("UploadedDeal")  # noqa: F821
    override_by: Mapped["User"] = relationship("User", foreign_keys=[override_by_id])  # noqa: F821
    approved_by: Mapped["User"] = relationship("User", foreign_keys=[approved_by_id])  # noqa: F821
