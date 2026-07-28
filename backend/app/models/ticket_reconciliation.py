from datetime import date, datetime

from sqlalchemy import String, DateTime, Date, Numeric, Integer, Text, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TicketReconciliation(Base):
    """Result of comparing one internal UploadedTicket (EXPECTED) against its
    matched BSP settlement row (ACTUAL) — the "did BSP settle what I expected?"
    engine output. One row per reconciled unit:

      matched / minor_diff / mismatch / possible_match → ticket_id + bsp_row_id
      missing_bsp  → ticket_id set, bsp_row_id NULL (ticket never settled)
      extra_bsp    → bsp_row_id set, ticket_id NULL (BSP row with no ticket)

    Recomputed wholesale per run (delete-in-scope + re-insert), so it is a
    report/cache, not a source of truth. Scoped per user: tenant_id + created_by_id.
    Headline field pairs are explicit columns (summary/sorting); the full
    comprehensive comparison lives in the `field_diffs` JSONB so new fields never
    need a migration.
    """
    __tablename__ = "ticket_reconciliation"

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    run_id:        Mapped[str]        = mapped_column(String(100), nullable=False, index=True)          # uuid of the run that produced it
    statement_id:  Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)           # bsp_statements.batch_id (scope hint)

    ticket_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("uploaded_tickets.id", ondelete="CASCADE"), nullable=True, index=True)
    bsp_row_id:    Mapped[int | None] = mapped_column(Integer, ForeignKey("bsp_statement_rows.id", ondelete="SET NULL"), nullable=True, index=True)

    # ── denormalised identity / filter columns ───────────────────────────────
    ticket_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    airline_name:  Mapped[str | None] = mapped_column(String(200), nullable=True)
    airline_code:  Mapped[str | None] = mapped_column(String(20),  nullable=True)
    issue_date:    Mapped[date | None] = mapped_column(Date, nullable=True, index=True)   # BSP issue_date, else parsed ticket_date
    txn_type:      Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)  # TKTT/ADM/ACM/RA/RFND/EMD/EXCH
    pax_name:      Mapped[str | None] = mapped_column(String(300), nullable=True)

    # ── verdict ──────────────────────────────────────────────────────────────
    match_status:  Mapped[str]        = mapped_column(String(16), nullable=False, index=True)  # matched|minor_diff|mismatch|missing_bsp|extra_bsp|possible_match
    severity:      Mapped[str]        = mapped_column(String(10), nullable=False, index=True)  # ok|warning|critical
    match_method:  Mapped[str]        = mapped_column(String(16), nullable=False, default="none", server_default="none")  # ticket_number|heuristic|none

    # ── headline expected / actual / variance / match pairs ──────────────────
    expected_fare:        Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    actual_fare:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    fare_variance:        Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    fare_match:           Mapped[bool | None]  = mapped_column(Boolean, nullable=True)

    expected_yq:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    actual_yq:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yq_variance:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yq_match:             Mapped[bool | None]  = mapped_column(Boolean, nullable=True)

    expected_yr:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    actual_yr:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yr_variance:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yr_match:             Mapped[bool | None]  = mapped_column(Boolean, nullable=True)

    expected_tax:         Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)   # total tax
    actual_tax:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    tax_variance:         Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    tax_match:            Mapped[bool | None]  = mapped_column(Boolean, nullable=True)

    expected_transaction: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    actual_transaction:   Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    transaction_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    transaction_match:    Mapped[bool | None]  = mapped_column(Boolean, nullable=True)

    expected_commission:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    actual_commission:    Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_variance:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_match:     Mapped[bool | None]  = mapped_column(Boolean, nullable=True)
    commission_source:    Mapped[str | None]   = mapped_column(String(12), nullable=True)   # 'reported' | 'iata'

    expected_balance:     Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    actual_balance:       Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    balance_variance:     Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    balance_match:        Mapped[bool | None]  = mapped_column(Boolean, nullable=True)

    # ── rollups ──────────────────────────────────────────────────────────────
    net_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)   # signed headline diff (expected_transaction - actual_transaction)
    abs_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)   # abs(net_variance) for sorting/summing

    # ── extensible ───────────────────────────────────────────────────────────
    field_diffs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # {field: {label, expected, actual, variance, match, severity}} — full comparison
    issues:      Mapped[list | None] = mapped_column(JSONB, nullable=True)   # [{rule_id, field, severity, message, expected, actual, variance}]
    related_bsp: Mapped[list | None] = mapped_column(JSONB, nullable=True)   # same-ticket ADM/ACM/RFND rows [{bsp_row_id, txn_type, amount}]
    remarks:     Mapped[str | None]  = mapped_column(Text, nullable=True)

    reconciled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


Index("ix_ticket_reconciliation_scope", TicketReconciliation.tenant_id, TicketReconciliation.created_by_id)
Index("ix_ticket_reconciliation_scope_status", TicketReconciliation.tenant_id, TicketReconciliation.created_by_id, TicketReconciliation.match_status)
