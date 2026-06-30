from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class IncomeSummary(Base):
    """A saved income summary for one ticket statement (one row per statement).

    Snapshot: the 11 incentive-type totals + grand total are computed on the
    backend at save time and stored as-is, so the summary stays stable even if
    the underlying tickets change later. UPSERT on (tenant_id, created_by_id,
    batch_id) — re-saving overwrites totals, name and updated_at.
    Scoped per user: queries filter by tenant_id + created_by_id.
    """
    __tablename__ = "income_summaries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "created_by_id", "batch_id",
            name="uq_income_summaries_tenant_user_batch",
        ),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    batch_id:      Mapped[str]        = mapped_column(String(100), ForeignKey("ticket_statements.batch_id", ondelete="CASCADE"), nullable=False, index=True)

    name:          Mapped[str]        = mapped_column(String(500), nullable=False)   # editable income-summary name (default = statement_name)

    # ── snapshot of statement metadata ───────────────────────────────────────
    statement_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    statement_type: Mapped[str]        = mapped_column(String(10), nullable=False, default="B2B")
    agency:         Mapped[str]        = mapped_column(String(200), nullable=False)
    valid_from:     Mapped[date]       = mapped_column(Date, nullable=False)
    valid_to:       Mapped[date]       = mapped_column(Date, nullable=False)
    ticket_count:   Mapped[int]        = mapped_column(Integer, nullable=False, default=0)

    # ── aggregated totals ────────────────────────────────────────────────────
    incentive_totals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # {<one of 11 incentive-type keys>: float}
    total_income:     Mapped[float]       = mapped_column(Numeric(14, 2), nullable=False, default=0)
    iata_commission_total: Mapped[float]  = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")  # sum of tickets' IATA commission

    created_at:    Mapped[datetime]    = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]    = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
