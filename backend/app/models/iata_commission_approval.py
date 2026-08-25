from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Integer, Numeric, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class IataCommissionApproval(Base):
    """A tenant user's pending request against the IATA Commission master.

    Same shape as the other four System Master queues (suppliers, airlines,
    airports, classes/RBD): the business columns are mirrored from
    IataCommission so approve can copy the row straight onto the master, and a
    platform admin may correct the row before approving it — `original_payload`
    keeps what the submitter actually sent so they can see what changed.
    """
    __tablename__ = "iata_commission_approvals"

    id:                  Mapped[int]          = mapped_column(primary_key=True)

    airline_name:        Mapped[str]          = mapped_column(String(255), nullable=False)
    airline_code:        Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    iata_numeric_code:   Mapped[str | None]   = mapped_column(String(10),  nullable=True)
    iata_commission_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    valid_from:          Mapped[date | None]  = mapped_column(Date, nullable=True)
    valid_to:            Mapped[date | None]  = mapped_column(Date, nullable=True)

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
    reviewed_at:      Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None]      = mapped_column(Text, nullable=True)

    # ── platform-admin edit before approval ────────────────────────────────
    # Snapshot of the business columns as the submitter left them, written on
    # the FIRST admin edit only. NULL means no admin changed anything.
    original_payload: Mapped[dict | None]     = mapped_column(JSONB, nullable=True)
    edited_by_id:     Mapped[int | None]      = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    edited_at:        Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    submitted_by: Mapped["User"] = relationship("User", foreign_keys=[submitted_by_id])  # noqa: F821
    reviewed_by:  Mapped["User"] = relationship("User", foreign_keys=[reviewed_by_id])   # noqa: F821
    edited_by:    Mapped["User"] = relationship("User", foreign_keys=[edited_by_id])     # noqa: F821

    # new vs update distinction
    request_type: Mapped[str] = mapped_column(String(10), default="new")
    target_iata_commission_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("iata_commissions.id", ondelete="SET NULL"), nullable=True
    )
