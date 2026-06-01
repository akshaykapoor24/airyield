from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class DealBatch(Base):
    __tablename__ = "deal_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    deal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    incentive_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_id])  # noqa: F821
