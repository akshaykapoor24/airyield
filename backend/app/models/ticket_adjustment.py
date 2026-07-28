from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TicketAdjustment(Base):
    """An airline financial adjustment attached to a ticket — an EVENT LOG.

    Unlike the single-value `adm_acm_ra` flag on uploaded_tickets, one ticket can
    accrue many adjustments over time (ADM -> Refund -> ACM -> ADM). This table is
    ADDITIVE: it does not replace or read `adm_acm_ra`; the upload/matching path is
    untouched. Scoped per user: queries filter tenant_id + created_by_id.
    """
    __tablename__ = "ticket_adjustments"

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Link to the ticket — real FK, nullable (an adjustment may arrive before/without a matched ticket)
    ticket_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("uploaded_tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    ticket_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)   # heuristic join key

    type:          Mapped[str]        = mapped_column(String(12), nullable=False)   # 'ADM'|'ACM'|'Refund'|'RA'|'DebitNote'|'CreditNote'
    reference_no:  Mapped[str | None] = mapped_column(String(100), nullable=True)   # ADM/ACM document number
    amount:        Mapped[float]      = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    reason:        Mapped[str | None] = mapped_column(String(500), nullable=True)
    adjustment_date: Mapped[date | None] = mapped_column(Date, nullable=True)       # event date (the "over months" axis)
    remarks:       Mapped[str | None] = mapped_column(String(500), nullable=True)
    status:        Mapped[str]        = mapped_column(String(12), nullable=False, default="open", server_default="open")   # open|settled|disputed|void
    source:        Mapped[str]        = mapped_column(String(12), nullable=False, default="manual", server_default="manual")  # manual|bsp
    # Provenance when imported from a BSP statement (Phase 2). Plain string for now; a FK to
    # bsp_statements is added once that table exists.
    uploaded_statement_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
