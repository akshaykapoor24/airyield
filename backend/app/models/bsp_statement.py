from datetime import date, datetime
from sqlalchemy import String, Text, DateTime, Date, Numeric, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class BspStatement(Base):
    """One BSP settlement statement upload session (mirrors TicketStatement).

    BSP is a settlement DOCUMENT that references tickets — it is not a ticket and
    lives in its own table so the untouchable ticket repository stays BSP-free.
    Scoped per user: queries filter tenant_id + created_by_id.

    Large PDF statements (1000-2000 pages) are parsed asynchronously by a Celery
    worker; `status` + the processed/total counters drive the frontend progress UI.
    """
    __tablename__ = "bsp_statements"

    batch_id:       Mapped[str]        = mapped_column(String(100), primary_key=True)   # uuid4, groups the upload session
    tenant_id:      Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id:  Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    statement_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    airline_code:   Mapped[str | None] = mapped_column(String(20), nullable=True)
    airline_name:   Mapped[str | None] = mapped_column(String(200), nullable=True)
    period_from:    Mapped[date | None] = mapped_column(Date, nullable=True)
    period_to:      Mapped[date | None] = mapped_column(Date, nullable=True)
    file_name:      Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_url:       Mapped[str | None] = mapped_column(String(1000), nullable=True)   # GCS blob path
    row_count:      Mapped[int]        = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Async processing state (set by the Celery parse task).
    status:         Mapped[str]        = mapped_column(String(12), nullable=False, default="pending", server_default="pending", index=True)  # pending|processing|completed|failed
    total_pages:    Mapped[int]        = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processed_pages: Mapped[int]       = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_rows:     Mapped[int]        = mapped_column(Integer, nullable=False, default=0, server_default="0")
    processed_rows: Mapped[int]        = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error:          Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Summary/Detailed pairing + printed grand totals (Numeric(16,2)) ───────
    # group_id links this detailed statement to its BSP summary; gt_* are the
    # statement grand totals accumulated while parsing (used to reconcile against
    # the summary's own grand totals — see bsp_summary.py).
    group_id:            Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    gt_issues:           Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_refunds:          Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_debit_memos:      Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_credit_memos:     Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_std_comm:         Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_sup_comm:         Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_tax_on_comm:      Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_balance_payable:  Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    gt_doc_count:        Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Commission-income run state (Vendors → Commission income) ────────────
    # A commission run matches every settlement row against the user's approved
    # AIRLINE deals and stores the estimated incentive on the row. The run is a
    # Celery job (statements reach ~50k rows), so it carries its own progress +
    # roll-up totals, exactly like the parse `status`/`processed_rows` pair above.
    commission_status:          Mapped[str] = mapped_column(String(12), nullable=False, default="idle", server_default="idle", index=True)  # idle|queued|processing|completed|failed
    commission_total_rows:      Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    commission_processed_rows:  Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    commission_error:           Mapped[str | None] = mapped_column(Text, nullable=True)
    # Liveness of the current run: stamped when queued and refreshed on every
    # progress flush. A queued/processing run whose heartbeat has gone quiet has
    # lost its worker, and the API lets a new run take over — so the UI can never
    # wedge on a run that will never finish. A genuinely slow run keeps beating.
    commission_heartbeat_at:    Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    commission_calculated_at:   Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    commission_total_incentive: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    commission_iata_total:      Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    commission_matched_rows:    Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    commission_unmatched_rows:  Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    commission_excluded_rows:   Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    commission_skipped_rows:    Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # A deal matched, but it pays only on a cabin class / travel window / route
    # this settlement row does not carry, so the amount could not be verified.
    # Counted separately from `unmatched` because the answer is different: a
    # matched deal is on file and the fix is to upload the TGQ HMPR, not to write
    # a new deal.
    commission_needs_data_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Rows no run has touched. Previously these fell into NO bucket, so a
    # statement whose run had never happened reported "8 matched, 0 unmatched"
    # over 15,204 rows and read as calculated-but-poor rather than uncalculated.
    commission_pending_rows:    Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # How many rows found a TGQ HMPR counterpart, so the UI can distinguish "the deals
    # don't apply" from "the other half of the data hasn't been uploaded".
    commission_enriched_rows:   Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at:     Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)


class BspStatementRow(Base):
    """One row of a BSP statement (one settlement transaction). Linked to an
    uploaded ticket by BOTH a real (nullable) FK and ticket_number, because
    BSP↔ticket matching is heuristic (filled in Phase 2).

    Taxes/fees are NOT stored as columns here — each fare component is a row in
    bsp_tax_breakups, so new airline tax codes never require a schema migration.
    """
    __tablename__ = "bsp_statement_rows"

    id:             Mapped[int]        = mapped_column(primary_key=True)
    statement_id:   Mapped[str]        = mapped_column(String(100), ForeignKey("bsp_statements.batch_id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:      Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id:  Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # ── Identity ────────────────────────────────────────────────────────────
    ticket_number:  Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)   # heuristic join key (== document_number)
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)              # BSP "document number" (ticket number)
    spdr_no:        Mapped[str | None] = mapped_column(String(100), nullable=True)               # on a CANX row: the parent SPDR's document number (bulk-cancel link)
    airline_code:   Mapped[str | None] = mapped_column(String(20), nullable=True)
    airline_accounting_code: Mapped[str | None] = mapped_column(String(10), nullable=True)        # e.g. 141
    transaction_type: Mapped[str | None] = mapped_column(String(10), nullable=True)               # TKTT/ADM/ACM/RFND/EMD/EXCH (also legacy tktt/rfnd/...)
    issue_date:     Mapped[date | None] = mapped_column(Date, nullable=True)
    cpui:           Mapped[str | None] = mapped_column(String(20), nullable=True)
    nr_code:        Mapped[str | None] = mapped_column(String(20), nullable=True)
    stat:           Mapped[str | None] = mapped_column(String(4), nullable=True)                  # I = International, D = Domestic
    form_of_payment: Mapped[str | None] = mapped_column(String(20), nullable=True)                # CA / CC ...

    # ── Financials (from the BSP statement) ─────────────────────────────────
    transaction_amount:       Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    fare_amount:              Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    penalty_amount:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_sales:                Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    standard_commission_rate: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    standard_commission_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    supplier_discount_rate:   Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    supplier_discount_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    tax_on_commission:        Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    balance_payable:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── Detailed-PDF enrichment (airline name + tour/rtdn/esac/wavr/associated docs) ─
    airline_name:          Mapped[str | None]  = mapped_column(String(200), nullable=True)   # resolved from airline master by 3-digit code
    tour:                  Mapped[list | None] = mapped_column(JSONB, nullable=True)          # ["INGBAFF500", ...] — a ticket can carry multiple
    alt_document_numbers:  Mapped[list | None] = mapped_column(JSONB, nullable=True)          # +TKTT conjunction doc numbers ["4846715097", ...]
    rtdn:                  Mapped[str | None]  = mapped_column(String(100), nullable=True)    # +RTDN related/refund document number
    esac:                  Mapped[str | None]  = mapped_column(String(50), nullable=True)     # ESAC authority code
    wavr:                  Mapped[str | None]  = mapped_column(String(50), nullable=True)      # WAVR waiver code
    # Full structured continuation-line detail (RTDN ref/EX + conjunction date/cpui):
    #   {"rtdn": {"doc","ref","indicator"}, "conjunctions": [{"doc","issue_date","cpui"}]}
    associated_docs:       Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Legacy columns (Excel/CSV extract path — kept nullable, dropped later) ─
    gross:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission:     Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    adm:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    acm:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    refund:         Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_due:        Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── Matching (Phase 2) ──────────────────────────────────────────────────
    matched_ticket_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("uploaded_tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    match_status:   Mapped[str]        = mapped_column(String(12), nullable=False, default="unmatched", server_default="unmatched")  # matched|unmatched|ambiguous

    # ── Commission income (deal match + estimated incentive) ────────────────
    # Mirrors the derived block on uploaded_tickets. BSP prints no cabin class,
    # no sector and no travel date, so the criteria that could not be evaluated
    # are listed in `skipped_criteria` rather than silently defaulted.
    matched_deal_id:      Mapped[int | None]   = mapped_column(Integer, nullable=True, index=True)   # no FK — deals may be deleted (same as uploaded_tickets)
    matched_deal_type:    Mapped[str | None]   = mapped_column(String(20), nullable=True)            # always 'airline' for BSP
    matched_deal_name:    Mapped[str | None]   = mapped_column(String(300), nullable=True)
    calculated_incentive: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)        # negative on a refund reversal
    iata_commission:      Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)        # deal IATA % × fare_amount; NOT part of the total
    incentive_breakdown:  Mapped[dict | None]  = mapped_column(JSONB, nullable=True)                 # {incentive_type: amount}
    commission_status:    Mapped[str]          = mapped_column(String(12), nullable=False, default="pending", server_default="pending", index=True)  # pending|calculated|excluded|reversed|skipped|unmatched
    commission_reason:    Mapped[str | None]   = mapped_column(String(500), nullable=True)
    skipped_criteria:     Mapped[list | None]  = mapped_column(JSONB, nullable=True)                 # what this row could NOT evaluate; [] = nothing skipped
    commission_calculated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── TGQ HMPR enrichment — the three fields BSP does not print ───────────
    # Resolved at run time by joining tgq_hmpr on (airline accounting code, ticket no) and
    # folding the ticket's N flown sectors back into one journey. Persisted so the grid can
    # show what the match was actually based on and a past run stays auditable.
    # enrichment_source NULL = no TGQ counterpart, and the three criteria stay skipped.
    enriched_sector:             Mapped[str | None]  = mapped_column(String(200), nullable=True)  # 'BOM/DEL/MNL/DEL/BOM'
    enriched_booking_class:      Mapped[str | None]  = mapped_column(String(60), nullable=True)   # 'L/U' (distinct across legs)
    enriched_travel_date:        Mapped[date | None] = mapped_column(Date, nullable=True)         # first leg
    enriched_travel_date_source: Mapped[str | None]  = mapped_column(String(12), nullable=True)   # explicit|inferred
    enriched_leg_count:          Mapped[int | None]  = mapped_column(Integer, nullable=True)
    enrichment_source:           Mapped[str | None]  = mapped_column(String(20), nullable=True)   # None | 'tgq_hmpr'
    enrichment_ref:              Mapped[str | None]  = mapped_column(String(100), nullable=True)  # winning tgq_hmpr.batch_id

    raw_data:       Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at:     Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)


class BspTaxBreakup(Base):
    """One fare component of a BSP row. Generic by design — a new tax/fee code is
    just another row, never a new column. component_type buckets the code so the
    deal engine can query e.g. SUM(amount) WHERE component_code = 'YQ'."""
    __tablename__ = "bsp_tax_breakups"

    id:             Mapped[int]        = mapped_column(primary_key=True)
    bsp_row_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("bsp_statement_rows.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:      Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)

    component_type: Mapped[str | None] = mapped_column(String(20), nullable=True)   # BASE_FARE|TAX|FEE|PENALTY|COMMISSION
    component_code: Mapped[str | None] = mapped_column(String(20), nullable=True)   # YQ/YR/GZ/IN ...
    amount:         Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)


class BspParseError(Base):
    """A single page/parse failure captured during async processing, so one bad
    page never fails the whole statement. Surfaced read-only in the UI."""
    __tablename__ = "bsp_parse_errors"

    id:             Mapped[int]        = mapped_column(primary_key=True)
    statement_id:   Mapped[str]        = mapped_column(String(100), ForeignKey("bsp_statements.batch_id", ondelete="CASCADE"), nullable=False, index=True)
    page_number:    Mapped[int | None] = mapped_column(Integer, nullable=True)
    error:          Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_snippet:    Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at:     Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
