from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import String, DateTime, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TicketStatement(Base):
    """Metadata for a batch of uploaded tickets (one row per upload session).

    `agency` is the bare vendor NAME as picked at upload time, and on its own it
    can no longer identify who to bill: a vendor may be onboarded once per branch,
    so "Lords Travels" matches both Lords Delhi and Lords Mumbai. Whichever billed
    first would take the other's tickets, because `uploaded_tickets.billing_id` is
    a single FK. `agency_id` is the fix — Agency Billing and unbilled_exposure
    resolve by it when it is set, and fall back to the name match ONLY when that
    name resolves to exactly one agency. An ambiguous name refuses to bill.
    Nullable because statements uploaded before the picker sent an id have none.
    """
    __tablename__ = "ticket_statements"

    batch_id:        Mapped[str]          = mapped_column(String(100), primary_key=True)
    tenant_id:       Mapped[int]          = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    statement_type:  Mapped[str]          = mapped_column(String(10), nullable=False, default="B2B")
    statement_name:  Mapped[str | None]   = mapped_column(String(500), nullable=True)
    agency:          Mapped[str]          = mapped_column(String(300), nullable=False)
    agency_id:       Mapped[int | None]   = mapped_column(Integer, ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True, index=True)
    valid_from:     Mapped[date]     = mapped_column(Date, nullable=False)
    valid_to:       Mapped[date]     = mapped_column(Date, nullable=False)
    file_name:      Mapped[str]      = mapped_column(String(500), nullable=False)
    file_url:       Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # ── WHO this statement was sold to ───────────────────────────────────────
    # The batch default; each ticket carries its own copy, which is what the
    # commission run reads (one upload can hold rows for different customers, and
    # Create Tickets files them one at a time).
    #
    # `agency` above keeps holding the party's DISPLAY NAME whatever the type, so
    # Agency Billing, reports and the income-summary export keep working; only an
    # agency-typed statement sets `agency_id`.
    customer_type:      Mapped[str | None] = mapped_column(String(12), nullable=True)   # agency | corporate | direct
    customer_agency_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("agencies.id", ondelete="SET NULL"), nullable=True)
    corporate_id:       Mapped[int | None] = mapped_column(Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True)
    customer_id:        Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
