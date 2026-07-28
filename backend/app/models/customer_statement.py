from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import String, DateTime, Date, ForeignKey, Numeric, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class CustomerStatement(Base):
    """Metadata for a batch of customer-statement tickets (one row per upload session).

    A *customer* statement is the B2B statement an agency issues for one of the
    sub-agencies it onboards in the Customer Directory. Deliberately separate from
    ``ticket_statements`` (the internal/vendor statement repo). Always ``B2B``.
    The picked agency + its entities/login-ids are stored as JSONB snapshots so the
    repo/detail render without joins and survive later directory edits.
    """
    __tablename__ = "customer_statements"

    batch_id:        Mapped[str]          = mapped_column(String(100), primary_key=True)
    tenant_id:       Mapped[int]          = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    statement_type:  Mapped[str]          = mapped_column(String(10), nullable=False, default="B2B")
    statement_name:  Mapped[str | None]   = mapped_column(String(500), nullable=True)
    agency:          Mapped[str]          = mapped_column(String(200), nullable=False)   # agency name snapshot
    agency_id:       Mapped[int | None]   = mapped_column(Integer, nullable=True)         # Customer-Directory agency id
    entities:        Mapped[list | None]  = mapped_column(JSONB, nullable=True)           # [{id, name, code}]
    login_ids:       Mapped[list | None]  = mapped_column(JSONB, nullable=True)           # [{id, login_id, airline_name, entity_id, entity_name}]
    valid_from:      Mapped[date]         = mapped_column(Date, nullable=False)
    valid_to:        Mapped[date]         = mapped_column(Date, nullable=False)
    file_name:       Mapped[str]          = mapped_column(String(500), nullable=False)
    file_url:        Mapped[str | None]   = mapped_column(String(1000), nullable=True)
    created_by_id:   Mapped[int]          = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at:      Mapped[datetime]     = mapped_column(DateTime, default=datetime.utcnow)


class CustomerStatementTicket(Base):
    """One parsed row from a customer-statement XLS upload. Mirrors the shared + B2B
    columns of ``uploaded_tickets`` only — no airline-only / deal-matching / incentive /
    billing columns (customer statements are view/edit only for now)."""
    __tablename__ = "customer_statement_tickets"

    id:             Mapped[int]      = mapped_column(primary_key=True)
    batch_id:       Mapped[str]      = mapped_column(String(100), nullable=False, index=True)
    file_name:      Mapped[str]      = mapped_column(String(500), nullable=False)
    tenant_id:      Mapped[int]      = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    statement_type: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ── XLS columns (B2B) ──────────────────────────────────────────────────
    booking_ref:         Mapped[str | None] = mapped_column(String(100), nullable=True)
    segment_type:        Mapped[str | None] = mapped_column(String(50),  nullable=True)
    invoice_type:        Mapped[str | None] = mapped_column(String(50),  nullable=True)
    invoice_no:          Mapped[str | None] = mapped_column(String(100), nullable=True)
    ticket_date:         Mapped[str | None] = mapped_column(String(50),  nullable=True)
    last_name:           Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_name:          Mapped[str | None] = mapped_column(String(200), nullable=True)
    sector:              Mapped[str | None] = mapped_column(String(200), nullable=True)
    booking_class:       Mapped[str | None] = mapped_column(String(20),  nullable=True)
    departure_datetime:  Mapped[str | None] = mapped_column(String(100), nullable=True)
    gds_pnr:             Mapped[str | None] = mapped_column(String(50),  nullable=True)
    airlines_code:       Mapped[str | None] = mapped_column(String(20),  nullable=True)
    ticket_number:       Mapped[str | None] = mapped_column(String(50),  nullable=True)

    # ── Fare / Charge columns ──────────────────────────────────────────────
    sell_fare:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_tax:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_tax_yq:         Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sale_yr:             Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sale_k3:             Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    rei_sell:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    seat_selection:      Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    excess_baggage:      Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    meals:               Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    rfd_sell:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    can_charge:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    booking_fee_sell:    Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    cgst_sell:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sgst_sell:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    igst_sell:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    comm_sell:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    adm:                 Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    incentive_sell:      Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    dis_sell:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    tds_sell:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_amt:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    paid_by_credit_card: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_amt:             Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    cc:                  Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    acc_code:            Mapped[str | None]   = mapped_column(String(100), nullable=True)
    sold_to:             Mapped[str | None]   = mapped_column(String(20),  nullable=True)   # 'customer' | 'agency'
    customer_name:       Mapped[str | None]   = mapped_column(String(300), nullable=True)
    tour_code:           Mapped[str | None]   = mapped_column(String(100), nullable=True)

    # ── JSONB ──────────────────────────────────────────────────────────────
    tax_breakup:         Mapped[dict | None]  = mapped_column(JSONB, nullable=True)
    segments:            Mapped[list | None]  = mapped_column(JSONB, nullable=True)
    raw_data:            Mapped[dict | None]  = mapped_column(JSONB, nullable=True)

    # ── Derived / status ───────────────────────────────────────────────────
    airline_name:        Mapped[str | None]   = mapped_column(String(200), nullable=True)
    ticket_status:       Mapped[str]          = mapped_column(String(10), nullable=False, server_default="draft")
    split_type:          Mapped[str | None]   = mapped_column(String(10), nullable=True)

    created_by: Mapped["User"] = relationship("User")  # noqa: F821
