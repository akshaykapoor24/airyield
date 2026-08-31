"""LCC Detailed Statement — scalable batch-header + typed-rows schema.

Replaces the old single JSONB-blob ``lcc_detailed`` table with:

  * ``lcc_detailed_batch`` — one row per uploaded file: provenance, the confirmed
    column mapping, and the async processing state (status/progress) the frontend polls.
  * ``lcc_detailed``       — one row per statement line, with the 27 core fields promoted
    to TYPED, INDEXED columns (fast PNR/date/agent lookups + correct SUM), and the
    long tail (named taxes, legs, ssr) folded into JSONB.

Ingestion is async (see ``workers/lcc_tasks.py``), mirroring the BSP pipeline
(``models/bsp_statement.py``). Scoped per user: queries filter tenant_id + created_by_id.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric,
    SmallInteger, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class LccDetailedBatch(Base):
    """One LCC Detailed upload session. Created at /extract (status='staged'),
    confirmed at /confirm (status='pending' + enqueue), and driven to completion by
    the Celery ingest task via the status/processed_rows counters."""
    __tablename__ = "lcc_detailed_batch"

    batch_id:      Mapped[str]        = mapped_column(String(100), primary_key=True)   # uuid4
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    source_file:   Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url:      Mapped[str | None] = mapped_column(String(1000), nullable=True)   # GCS blob path of the uploaded file
    source_format: Mapped[str | None] = mapped_column(String(40), nullable=True)     # detected export format

    # ── Airline, declared at upload ──────────────────────────────────────────
    # An LCC export identifies no carrier — no airline column, and bare flight numbers
    # in `segments` (e.g. "2571"), so nothing can be derived from the file. The user
    # picks one of their Airline Master ids in the upload wizard; see models/tenant_airline.py.
    # Nullable because batches uploaded before this existed have no airline until
    # PATCH /lcc-detailed/batches/{batch_id}/airline backfills them.
    tenant_airline_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tenant_airlines.id", ondelete="SET NULL"), nullable=True, index=True)
    airline_id:        Mapped[int | None] = mapped_column(Integer, ForeignKey("airlines.id", ondelete="SET NULL"), nullable=True, index=True)
    airline_name:      Mapped[str | None] = mapped_column(String(255), nullable=True)
    airline_code:      Mapped[str | None] = mapped_column(String(20), nullable=True)
    airline_ref_id:    Mapped[str | None] = mapped_column(String(100), nullable=True)   # the id the user selected
    header_row:    Mapped[int]        = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    column_map:    Mapped[dict | None] = mapped_column(JSONB, nullable=True)          # {standard_field: xls_column}

    # User-declared expected record count (optional), entered in the upload wizard. Lets
    # the user confirm every record they expected actually landed in the DB after import.
    expected_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Async processing state (set by the Celery ingest task).
    status:        Mapped[str]        = mapped_column(String(12), nullable=False, default="staged", server_default="staged", index=True)  # staged|pending|processing|completed|failed
    total_rows:    Mapped[int]        = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processed_rows: Mapped[int]       = mapped_column(Integer, nullable=False, default=0, server_default="0")
    matched_columns: Mapped[int]      = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error:         Mapped[str | None] = mapped_column(Text, nullable=True)

    uploaded_at:   Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── Billing: who these rows are sold to, and where they were projected ────
    # An LCC statement names no customer either (only a passenger per row), so the
    # rows are resolved to a Customer/Corporate and then projected into
    # `uploaded_tickets`, which is the only table the billing screens read.
    # See services/customer_resolver.py and services/lcc_billing_projection.py.
    billable_rows:   Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    resolved_rows:   Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unresolved_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    projected_rows:  Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Batch-level fallback party, applied to every row the resolver could not match.
    # The primary path in practice: an LCC export's passenger names rarely overlap
    # the Customer master, so "bill this whole file to X" is what usually resolves it.
    default_customer_type: Mapped[str | None] = mapped_column(String(12), nullable=True)   # agency|corporate|direct
    default_customer_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    default_corporate_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True)

    resolution_status: Mapped[str] = mapped_column(String(12), nullable=False, default="none", server_default="none", index=True)  # none|resolved|projected
    # The `ticket_statements.batch_id` this batch projects into. Allocated once and
    # REUSED on every re-projection — that is what keeps one stable statement header
    # instead of a new one per run.
    billing_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    projected_at:     Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LccDetailed(Base):
    """One normalized LCC Detailed statement line. The 27 core fields are typed
    columns; named taxes / legs / ssr fold into JSONB; raw_data keeps the original
    row verbatim for audit."""
    __tablename__ = "lcc_detailed"

    id:            Mapped[int]        = mapped_column(BigInteger, primary_key=True)
    batch_id:      Mapped[str]        = mapped_column(String(100), ForeignKey("lcc_detailed_batch.batch_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # ── Airline, denormalised from the batch at ingest ────────────────────────
    # Copied onto every row so commission matching and the PLB accrual board read one
    # table instead of joining back to the batch header. No FK on airline_id (same
    # convention as BspStatementRow.matched_deal_id) to keep the chunked bulk insert cheap.
    airline_id:   Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    airline_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    airline_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Core typed columns (promoted for fast, indexed querying) ──────────────
    transaction_date:        Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    name:                    Mapped[str | None]      = mapped_column(String(255), nullable=True)
    payment_datetime:        Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payment_method_code:     Mapped[str | None]      = mapped_column(String(40), nullable=True)
    payment_amount:          Mapped[float | None]    = mapped_column(Numeric(14, 2), nullable=True)
    payment_number:          Mapped[str | None]      = mapped_column(String(60), nullable=True)
    booking_date:            Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    record_locator:          Mapped[str | None]      = mapped_column(String(20), nullable=True)
    source_organization_code: Mapped[str | None]     = mapped_column(String(40), nullable=True)
    booking_promo_code:      Mapped[str | None]      = mapped_column(String(60), nullable=True)
    received_by:             Mapped[str | None]      = mapped_column(String(120), nullable=True)
    source_agent_code:       Mapped[str | None]      = mapped_column(String(60), nullable=True)
    international:           Mapped[bool | None]     = mapped_column(Boolean, nullable=True)
    currency_code:           Mapped[str | None]      = mapped_column(String(8), nullable=True)
    product_class:           Mapped[str | None]      = mapped_column(String(40), nullable=True)
    pax_count:               Mapped[int | None]      = mapped_column(SmallInteger, nullable=True)
    name1:                   Mapped[str | None]      = mapped_column(String(255), nullable=True)
    email_address:           Mapped[str | None]      = mapped_column(String(255), nullable=True)
    home_phone:              Mapped[str | None]      = mapped_column(String(60), nullable=True)
    gds_record_code:         Mapped[str | None]      = mapped_column(String(40), nullable=True)
    gds_record_locator:      Mapped[str | None]      = mapped_column(String(20), nullable=True)
    gds_booking_system_code: Mapped[str | None]      = mapped_column(String(40), nullable=True)
    payment_status:          Mapped[str | None]      = mapped_column(String(40), nullable=True)
    total:                   Mapped[float | None]    = mapped_column(Numeric(14, 2), nullable=True)
    base_fare:               Mapped[float | None]    = mapped_column(Numeric(14, 2), nullable=True)
    other_fee_total:         Mapped[float | None]    = mapped_column(Numeric(14, 2), nullable=True)
    other_ssr_total:         Mapped[float | None]    = mapped_column(Numeric(14, 2), nullable=True)

    # ── Derived typed columns ────────────────────────────────────────────────
    departure_date:          Mapped[date | None]     = mapped_column(Date, nullable=True)
    taxes_total:             Mapped[float | None]    = mapped_column(Numeric(14, 2), nullable=True)

    # ── Folded / audit JSONB ─────────────────────────────────────────────────
    taxes:                   Mapped[list | None]     = mapped_column(JSONB, nullable=True)   # [{code, amount}]
    segments:                Mapped[list | None]     = mapped_column(JSONB, nullable=True)   # [{leg, route, flight_no, dep_date}]
    ssr:                     Mapped[list | None]     = mapped_column(JSONB, nullable=True)   # [{code, amount}]
    extra:                   Mapped[dict | None]     = mapped_column(JSONB, nullable=True)   # reserved / unmapped mapped fields
    raw_data:                Mapped[dict | None]     = mapped_column(JSONB, nullable=True)   # original row verbatim

    # ── Billing resolution + projection state ────────────────────────────────
    # `bill_kind` is classified from `total`, NOT `base_fare`: a fee-only row
    # (no-show, seat, PSFR/UDFR re-charge) has base_fare 0 but real money in total,
    # and a change fee can exceed a fare refund and flip the sign of the row.
    bill_kind:   Mapped[str | None] = mapped_column(String(12), nullable=True)   # sale|refund|payment
    bill_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved", server_default="unresolved")
    bill_customer_type: Mapped[str | None] = mapped_column(String(12), nullable=True)   # agency|corporate|direct
    bill_customer_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    bill_corporate_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True)
    # Deliberately IDENTICAL per gap type — the gaps endpoint groups on it, and
    # naming the passenger here would make one group per row.
    bill_match_reason:  Mapped[str | None] = mapped_column(String(300), nullable=True)

    # The idempotency key for re-projection. A real FK, not a bare int like
    # BspStatementRow.matched_deal_id, because a deleted ticket must clear it —
    # a natural key is impossible here (record_locator repeats per PNR and LCC
    # issues no ticket number).
    projected_ticket_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("uploaded_tickets.id", ondelete="SET NULL"), nullable=True)

    resolved_at:    Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_id: Mapped[int | None]      = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
