import enum
from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, ForeignKey, Text, Integer, JSON, Enum as SAEnum, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.airline_deal import DealLifecycleStatus  # noqa: F401 — re-exported for convenience


class UploadedDealStatus(str, enum.Enum):
    EXTRACTED = "extracted"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"  # backward-compat for existing rows


class UploadedDealSourceType(str, enum.Enum):
    UPLOAD = "upload"   # imported from a file (PDF / Excel / Word / image)
    MANUAL = "manual"   # entered manually via the New Deal form


class UploadedDeal(Base):
    __tablename__ = "deals"

    id:           Mapped[int]                  = mapped_column(primary_key=True)
    source_type:  Mapped[UploadedDealSourceType] = mapped_column(
                      SAEnum(UploadedDealSourceType, native_enum=False),
                      default=UploadedDealSourceType.UPLOAD,
                  )
    source_agent: Mapped[str]                  = mapped_column(String(255), nullable=False)
    issue_date:   Mapped[date | None]          = mapped_column(Date, nullable=True)
    file_name:    Mapped[str]                  = mapped_column(String(500), nullable=False)
    file_type:    Mapped[str]                  = mapped_column(String(20), nullable=False)  # pdf / excel / word / image / manual
    status:       Mapped[UploadedDealStatus]   = mapped_column(
                      SAEnum(UploadedDealStatus, native_enum=False),
                      default=UploadedDealStatus.EXTRACTED,
                  )
    notes:            Mapped[str | None]       = mapped_column(Text, nullable=True)
    # same fields as manual new deal — stored as JSON so schema stays flexible
    incentive_types:  Mapped[list | None]      = mapped_column(JSON, nullable=True)   # e.g. ["PLB","Super PLB"]
    incentive_data:   Mapped[dict | None]      = mapped_column(JSON, nullable=True)   # {PLB: {validFrom:..., frequency:...}}
    incl_excl_types:  Mapped[list | None]      = mapped_column(JSON, nullable=True)   # e.g. ["Inclusion For Trigger", ...]
    incl_excl_data:   Mapped[dict | None]      = mapped_column(JSON, nullable=True)   # {Inclusion For Trigger: {...}}
    vice_versa:       Mapped[dict | None]      = mapped_column(JSON, nullable=True)   # {Inclusion For Trigger: true}
    # deal header fields (same as new deal form)
    airline_type:     Mapped[str | None]       = mapped_column(String(20), nullable=True)   # GDS / LCC
    airline_name:     Mapped[str | None]       = mapped_column(String(255), nullable=True)
    contract_year:    Mapped[str | None]       = mapped_column(String(50), nullable=True)
    valid_from:       Mapped[date | None]      = mapped_column(Date, nullable=True)
    valid_to:         Mapped[date | None]      = mapped_column(Date, nullable=True)
    trigger_type:     Mapped[str | None]       = mapped_column(String(50), nullable=True)
    payout_type:      Mapped[str | None]       = mapped_column(String(50), nullable=True)
    entity:           Mapped[str | None]       = mapped_column(String(50), nullable=True)
    remark:           Mapped[str | None]       = mapped_column(Text, nullable=True)
    # GDS-specific
    iata_number:      Mapped[str | None]       = mapped_column(String(50), nullable=True)
    # LCC-specific
    business_type:    Mapped[str | None]       = mapped_column(String(50), nullable=True)
    entity_lcc:       Mapped[str | None]       = mapped_column(String(50), nullable=True)
    login_id:         Mapped[str | None]       = mapped_column(String(100), nullable=True)
    variant:          Mapped[str | None]       = mapped_column(String(100), nullable=True)
    eco_commission:   Mapped[str | None]       = mapped_column(String(50), nullable=True)
    peco_commission:  Mapped[str | None]       = mapped_column(String(50), nullable=True)
    bus_commission:   Mapped[str | None]       = mapped_column(String(50), nullable=True)
    base_type:        Mapped[str | None]       = mapped_column(String(20), nullable=True)
    valid_on:         Mapped[str | None]       = mapped_column(String(20), nullable=True)
    validity_raw:     Mapped[str | None]       = mapped_column(String(255), nullable=True)
    # deal maker
    deal_maker_name:  Mapped[str | None]       = mapped_column(String(255), nullable=True)
    tenant_id:        Mapped[int | None]       = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    created_by_id:Mapped[int]                  = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at:   Mapped[datetime]             = mapped_column(DateTime, default=datetime.utcnow)
    deal_lifecycle_status: Mapped[DealLifecycleStatus] = mapped_column(
        SAEnum(DealLifecycleStatus, native_enum=False,
               values_callable=lambda e: [m.value for m in e]),
        default=DealLifecycleStatus.DRAFT,
        server_default="draft",
    )
    incentives:   Mapped[list["DealIncentive"]] = relationship("DealIncentive", back_populates="deal", cascade="all, delete-orphan")
    incl_excl_rules: Mapped[list["DealInclusionExclusion"]] = relationship(
        "DealInclusionExclusion", back_populates="deal", cascade="all, delete-orphan"
    )
    created_by:   Mapped["User"]               = relationship("User", foreign_keys=[created_by_id])  # noqa: F821

    @property
    def incentive_types(self) -> list[str]:
        return [i.incentive_type for i in (self.incentives or [])]

    @property
    def incentive_data(self) -> dict:
        return {i.incentive_type: (i.data or {}) for i in (self.incentives or [])}

    @property
    def incl_excl_types(self) -> list[str]:
        return [r.rule_type for r in (self.incl_excl_rules or [])]

    @property
    def incl_excl_data(self) -> dict:
        return {r.rule_type: (r.data or {}) for r in (self.incl_excl_rules or [])}

    @property
    def vice_versa(self) -> dict:
        return {r.rule_type: bool(r.vice_versa) for r in (self.incl_excl_rules or [])}


class DealIncentive(Base):
    __tablename__ = "deal_incentives"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(Integer, ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    incentive_type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    deal: Mapped["UploadedDeal"] = relationship("UploadedDeal", back_populates="incentives")


class DealInclusionExclusion(Base):
    __tablename__ = "deal_incl_excl_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(Integer, ForeignKey("deals.id", ondelete="CASCADE"), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(100), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    vice_versa: Mapped[bool] = mapped_column(Boolean, default=False)

    deal: Mapped["UploadedDeal"] = relationship("UploadedDeal", back_populates="incl_excl_rules")
