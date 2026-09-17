"""What one ticket was BOUGHT at versus what it was SOLD at, and the margin between.

A different question from `ticket_reconciliation`, which asks "did BSP settle what we
expected" and compares one internal ticket against one airline settlement row. This asks
"what did this ticket cost us and what did we get for it" — the vendor's statement row is
the BUY side, the customer-side `uploaded_tickets` rows are the SELL side.

SIGN CONVENTION: `margin = sell - buy`. Positive means the sale earned money. That is the
OPPOSITE of bsp_reconciliation's `expected - actual`, deliberately: there the question is
"who is short", here it is "what did we make". The two engines never share a row, so the
two conventions never meet.

WHY A SECOND TABLE RATHER THAN A `source` COLUMN ON `ticket_reconciliation`. That table's
recompute is `delete(...).where(tenant_id, created_by_id)` with no source discriminator, so
a second source running against it would silently wipe BSP's results. It also carries a real
FK to `bsp_statement_rows`, which none of these sources have. Keeping them apart leaves the
only engine ever run against real settlement data untouched.

`source_row_id` carries NO foreign key, for the same reason `commission_calculations.
source_row_id` doesn't: it points at a different table per `source` — `third_party_gds`,
`third_party_lcc`, `ndc` or `lcc_detailed`. `source` is what says which table it means.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Statement slugs this engine can reconcile. The slug wherever one exists, so a reader
# never has to translate between two vocabularies — same rule as commission_run.SOURCE_*.
SOURCE_TP_GDS = "tp-gds"
SOURCE_TP_LCC = "tp-lcc"
SOURCE_NDC = "ndc"
SOURCE_LCC_DETAILED = "lcc-detailed"

# Bumped when a change would make the same pair of statements reconcile differently.
ENGINE_VERSION = "1.0"

# The verdicts. Deliberately NOT bsp_reconciliation's missing_bsp/extra_bsp: those words
# are meaningless on an LCC or NDC tab, and this engine is asked the same question by five
# different sources.
STATUS_MATCHED = "matched"
STATUS_MINOR_DIFF = "minor_diff"
STATUS_MISMATCH = "mismatch"
STATUS_BUY_ONLY = "buy_only"          # on the vendor's statement, never sold to anyone
STATUS_SELL_ONLY = "sell_only"        # sold to a customer, no vendor row to pay for it
STATUS_POSSIBLE = "possible_match"    # a fallback-key hit, NEVER auto-linked

SELL_RECON_STATUSES = {
    STATUS_MATCHED, STATUS_MINOR_DIFF, STATUS_MISMATCH,
    STATUS_BUY_ONLY, STATUS_SELL_ONLY, STATUS_POSSIBLE,
}

# Every money field compared. Each becomes a buy_/sell_/_variance/_match quadruple below.
MONEY_FIELDS = ("fare", "yq", "yr", "tax", "gross", "commission", "net")


class SellReconciliationRun(Base):
    """One attempt at reconciling one source's buy side against the sell side.

    The missing batch header, exactly as `commission_runs` is for commission: these sources
    keep no header row of their own — a "batch" is a shared `batch_id` string across the
    rows table — so status, progress and the roll-ups need a home. `batch_id` is NULLABLE
    here because the screen is a flat list across every statement of a source, so the
    normal run covers all of them; a value means the run was narrowed to one upload.
    """
    __tablename__ = "sell_reconciliation_runs"
    __table_args__ = (
        Index("ix_sell_recon_runs_lookup", "tenant_id", "created_by_id", "source", "batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    source: Mapped[str] = mapped_column(String(24), nullable=False)
    # NULL = every batch of this source (the default, because the grid is flat).
    batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    engine_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # idle | queued | processing | completed | failed
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="queued")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # Stamped on every progress flush, so a run claiming to be alive with a stale heartbeat
    # can be recognised as a dead worker rather than left spinning — commission_core.is_stale.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Roll-ups, always RECOMPUTED from the ledger rather than accumulated as the run goes,
    # so a re-run can never leave the headline disagreeing with the grid.
    matched_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    minor_diff_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mismatch_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    buy_only_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sell_only_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    possible_match_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    total_buy: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_sell: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Positive = the sales earned more than the purchases cost.
    total_margin: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    # The inputs the run was given. Not decoration — it is what makes a figure reproducible
    # after the statement or the ticket file has moved on.
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SellReconciliation(Base):
    """One reconciled unit: a vendor row, a sold ticket, or the two paired.

        matched / minor_diff / mismatch / possible_match -> source_row_id + ticket_id
        buy_only   -> source_row_id set, ticket_id NULL
        sell_only  -> ticket_id set, source_row_id NULL

    Recomputed wholesale per run (delete in scope, re-insert), so it is a report, not a
    source of truth. The delete scope INCLUDES `source` — without that, running one tab
    would wipe another's results.
    """
    __tablename__ = "sell_reconciliations"
    __table_args__ = (
        # One current answer per vendor row per source. `sell_only` rows carry a NULL
        # source_row_id and Postgres treats NULLs as distinct, so they are exempt — which
        # is correct: they are keyed by ticket, not by a vendor row.
        UniqueConstraint("tenant_id", "created_by_id", "source", "source_row_id",
                         name="uq_sell_recon_source_row"),
        Index("ix_sell_recon_scope", "tenant_id", "created_by_id", "source"),
        Index("ix_sell_recon_scope_status", "tenant_id", "created_by_id", "source", "match_status"),
        Index("ix_sell_recon_batch", "source", "batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # No FK: points at a different table per `source`. NULL on a sell_only row.
    source_row_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    ticket_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("uploaded_tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    # How many rows each side summed. Both sides routinely carry several rows per ticket
    # and a reader needs to know a figure came from more than one before going to look for
    # it: the sell side splits a multi-sector ticket into one row per leg with the money
    # divided across them, and the buy side prints a cancellation as a second, negative row
    # against the same ticket number. Netting both is what makes the two comparable.
    sell_legs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    buy_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # ── denormalised identity / filter columns ───────────────────────────────
    # The serial, with the airline accounting code beside it — the two halves the
    # statement prints as "235 4848358656". Stored apart so the grid can show both
    # without the join key ever being the joined string.
    ticket_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    ticket_prefix: Mapped[str | None] = mapped_column(String(4), nullable=True)
    airline_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    airline_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    pax_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ── verdict ──────────────────────────────────────────────────────────────
    match_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # ok|warning|critical
    # ticket_number = the exact prefix-aware key; alt10 = the last-10 fallback, which is
    # never auto-linked; none = nothing to join on.
    match_method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="none", server_default="none")

    # ── buy / sell / variance / match quadruples ─────────────────────────────
    buy_fare: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_fare: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    fare_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    fare_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    buy_yq: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_yq: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yq_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yq_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    buy_yr: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_yr: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yr_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yr_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    buy_tax: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_tax: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    tax_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    tax_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    buy_gross: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_gross: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    gross_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    gross_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    buy_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    buy_net: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_net: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── rollups ──────────────────────────────────────────────────────────────
    # sell_net - buy_net. The headline number on the grid.
    margin: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # abs(margin), for sorting worst-first and for summing into the tile.
    abs_margin: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── extensible ───────────────────────────────────────────────────────────
    # A LIST, order-preserving: [{key, label, buy, sell, variance, match, severity}].
    # Typed as a list because that is what the engine writes — ticket_reconciliation
    # annotates the same column as a dict and is wrong about its own contents.
    field_diffs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    issues: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    reconciled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
