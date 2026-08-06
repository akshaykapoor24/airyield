from datetime import date, datetime
from sqlalchemy import String, DateTime, Date, Numeric, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SeriesContract(Base):
    """A Series / SIT / MICE block booking, and how much of it has actually ticketed.

    The agency commits to a batch of seats up front — one group PNR for N pax at a
    fixed fare, with the money due in instalments. Tickets are then issued against
    that PNR over time, so one PNR yields many ticket numbers.

    The bottom block is a rollup, not user input: `SeriesContractMatchingService`
    recomputes it wholesale from `uploaded_tickets` matched on PNR. It is stored
    rather than derived on read so lists stay cheap, and it is idempotent so a
    re-run can never double-count. Scoped per user (tenant_id + created_by_id).
    """
    __tablename__ = "series_contracts"

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    contract_type: Mapped[str | None] = mapped_column(String(10),  nullable=True)   # 'Series' | 'SIT' | 'MICE'
    # Which master the agent was picked from. AIRLINE reads the airline master,
    # B2B the supplier master — the airline pair below is filled either way,
    # because a B2B block booking still flies on somebody's metal.
    agent_type:    Mapped[str | None] = mapped_column(String(10),  nullable=True)   # 'AIRLINE' | 'B2B'
    agent_name:    Mapped[str | None] = mapped_column(String(200), nullable=True)
    airline_name:  Mapped[str | None] = mapped_column(String(200), nullable=True)
    airline_code:  Mapped[str | None] = mapped_column(String(10),  nullable=True)

    # The match key. Indexed because every matching run groups on it.
    pnr_no:        Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    pax_count:     Mapped[int | None]   = mapped_column(Integer, nullable=True)
    trip_type:     Mapped[str | None]   = mapped_column(String(10), nullable=True)  # 'ONE_WAY' | 'RETURN'
    date_of_travel: Mapped[date | None] = mapped_column(Date, nullable=True)
    fare_per_pax:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Defaults to pax_count * fare_per_pax on the form, but stored as sent: a block
    # deal carries taxes and negotiated totals that break the clean multiplication.
    total_fare:    Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    payment_terms: Mapped[list | None]  = mapped_column(JSONB, nullable=True)       # [{due_date, percent, amount}]

    # ── Issuance rollup — written by SeriesContractMatchingService ────────────
    tickets_issued:  Mapped[int]             = mapped_column(Integer, nullable=False, server_default="0", default=0)
    ticket_numbers:  Mapped[list | None]     = mapped_column(JSONB, nullable=True)  # ["0982512345678", ...]
    amount_issued:   Mapped[float]           = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)
    match_status:    Mapped[str | None]      = mapped_column(String(20), nullable=True)  # pending|partial|complete|over_issued
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
