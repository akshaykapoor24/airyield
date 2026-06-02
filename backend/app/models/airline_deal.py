import enum
from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, ForeignKey, Text, Integer, JSON, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ManualDealStatus(str, enum.Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class DealLifecycleStatus(str, enum.Enum):
    DRAFT  = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class AirlineDeal(Base):
    __tablename__ = "airline_deals"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    status: Mapped[ManualDealStatus] = mapped_column(
        SAEnum(ManualDealStatus, native_enum=False,
               values_callable=lambda e: [m.value for m in e]),
        default=ManualDealStatus.PENDING_APPROVAL,
    )
    source_agent: Mapped[str] = mapped_column(String(255), nullable=False)
    deal_maker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    airline_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    airline_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_year: Mapped[str | None] = mapped_column(String(50), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    trigger_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payout_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iata_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_lcc: Mapped[str | None] = mapped_column(String(50), nullable=True)
    login_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    incentive_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    incentive_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    incl_excl_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    incl_excl_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    vice_versa: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deal_tag: Mapped[str] = mapped_column(String(50), nullable=False, server_default='standard')
    batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deal_lifecycle_status: Mapped[DealLifecycleStatus] = mapped_column(
        SAEnum(DealLifecycleStatus, native_enum=False,
               values_callable=lambda e: [m.value for m in e]),
        default=DealLifecycleStatus.DRAFT,
        server_default="draft",
    )

    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_id])  # noqa: F821
