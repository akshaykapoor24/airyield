from datetime import date, datetime
from sqlalchemy import String, Text, DateTime, Date, Numeric, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class BspSummaryStatement(Base):
    """One BSP **summary** statement (IATA FCAGBILLSUMNG "Agent Billing Summary").

    Paired with a detailed statement (bsp_statements) via ``group_id``. The printed
    grand totals (gt_*) are reconciled line-by-line against the detailed statement's
    own grand totals; the result is stored on ``match_status`` / ``match_detail``.
    Scoped per user (tenant_id + created_by_id). Parsed asynchronously by Celery.
    """
    __tablename__ = "bsp_summary_statements"

    batch_id:       Mapped[str]        = mapped_column(String(100), primary_key=True)   # uuid4
    tenant_id:      Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id:  Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    group_id:       Mapped[str]        = mapped_column(String(100), nullable=False, index=True)   # links to the detailed statement

    # ── Header (extracted from the PDF; no airline/period asked at upload) ────
    agent_code:          Mapped[str | None] = mapped_column(String(40), nullable=True)
    agent_name:          Mapped[str | None] = mapped_column(String(300), nullable=True)
    reference:           Mapped[str | None] = mapped_column(String(60), nullable=True)
    billing_period_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    period_from:         Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to:           Mapped[date | None] = mapped_column(Date, nullable=True)
    currency:            Mapped[str | None] = mapped_column(String(8), nullable=True)

    file_name:      Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_url:       Mapped[str | None] = mapped_column(String(1000), nullable=True)   # GCS blob path

    # ── Async processing state ───────────────────────────────────────────────
    status:         Mapped[str]        = mapped_column(String(12), nullable=False, default="pending", server_default="pending", index=True)  # pending|processing|completed|failed
    total_pages:    Mapped[int]        = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processed_pages: Mapped[int]       = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error:          Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Printed grand totals (Numeric(16,2)) ─────────────────────────────────
    gt_issues:           Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_refunds:          Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_debit_memos:      Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_credit_memos:     Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_std_comm:         Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_sup_comm:         Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_tax_on_comm:      Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_balance_payable:  Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_doc_count:        Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Reconciliation result (summary grand totals vs detailed grand totals) ─
    match_status:   Mapped[str]        = mapped_column(String(12), nullable=False, default="pending", server_default="pending")  # pending|matched|mismatch
    matched_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    match_detail:   Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # per-line {summary, detail, variance, ok}

    created_at:     Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)


class BspSummaryRow(Base):
    """One per-airline (× category) line of a BSP summary statement."""
    __tablename__ = "bsp_summary_rows"

    id:             Mapped[int]        = mapped_column(primary_key=True)
    summary_id:     Mapped[str]        = mapped_column(String(100), ForeignKey("bsp_summary_statements.batch_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:      Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id:  Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    category:       Mapped[str | None] = mapped_column(String(30), nullable=True)   # BSP|WEBSALES-EDIS|WEBSALES-WEBL
    airline_code:   Mapped[str | None] = mapped_column(String(10), nullable=True)   # 001
    airline_iata:   Mapped[str | None] = mapped_column(String(10), nullable=True)   # AA
    airline_name:   Mapped[str | None] = mapped_column(String(200), nullable=True)
    fop:            Mapped[str | None] = mapped_column(String(10), nullable=True)   # TOTAL|CASH

    issues:         Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    refunds:        Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    debit_memos:    Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    credit_memos:   Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    std_comm:       Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    sup_comm:       Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    tax_on_comm:    Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    balance_payable: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    doc_count:      Mapped[int | None] = mapped_column(Integer, nullable=True)
