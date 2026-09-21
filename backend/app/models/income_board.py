"""Every priced line, from every source, in the shape the income board reads.

WHY THIS TABLE EXISTS. Commission is already calculated correctly, but two structural
facts make a dashboard impossible to write without projecting it first:

  1. BSP writes its answers onto its own settlement row (`bsp_statement_rows`), while
     tp-gds, tp-lcc and lcc-detailed write to `commission_calculations`. BSP is not a
     registered commission adapter at all (services/commission/__init__.py), so there
     is no one table holding all four.
  2. `commission_calculations` carries no gross for any source. Every read that wants
     revenue has to join back to `lcc_detailed.total` or to `third_party_*.data`, and
     the latter needs a regex guard because services/flat_statement.py deliberately
     keeps the original text when a number fails to parse.

Doing that union per request means re-deriving three sets of dimensions on every page
load. Doing it once, when a run finishes, is this table.

IT IS A PROJECTION, NOT A SOURCE OF TRUTH. Every row is derived and fully rebuildable
from `commission_calculations` + `bsp_statement_rows` (+ `uploaded_tickets` and
`billings` on the customer side). Nothing is hand-edited and nothing reads back into
the engines, which is why the dimension ids carry NO foreign keys: a derived report
must never be the reason a supplier or an airline cannot be deleted. `tenant_id` and
`created_by_id` keep theirs, because those are the scope, not a dimension.

THE FIVE INVARIANTS THIS TABLE EXISTS TO ENFORCE

  1. `incentive` is NULL, never 0, when `status='needs_data'`. NULL means a deal
     matched but pays on something the document does not print, so nothing is claimed;
     zero means the deal applied and earned nothing. Collapsing them "would turn 'we
     could not confirm what you are owed' into 'you are owed nothing'"
     (models/commission_calculation.py). Every roll-up reads
     SUM(incentive) FILTER (WHERE status IN ('calculated','reversed')).
  2. `iata_commission` is a separate entitlement and is never summed into `incentive`.
     That separation is deliberate in services/commission/runner.py and
     models/bsp_statement.py; breaking it here would make this table disagree with both.
  3. `txn_class` keeps memos out of every revenue denominator. An ADM or ACM has no
     fare. Counting its value as gross corrupts every ratio on the board, and does it
     invisibly, because memos are legitimately `status='excluded'` and so appear in
     neither the matched nor the needs-data count.
  4. `segment` is normalised at write time through deal_matching.segment_letter, which
     returns 'I' | 'D' | None and does NOT accept a bare 'I'/'D' as input. BSP's STAT
     column therefore goes through bsp_commission.stat_to_segment FIRST — letter to
     word to letter. Feeding raw STAT straight in yields None for every BSP row.
     `segment_raw` keeps whatever the document actually printed, for drill-down.
  5. `airline_name` and `supplier_name` are label snapshots. Grouping is ALWAYS on the
     id. 141 of 2,340 supplier names repeat across branches, so grouping on the name
     merges branches that bill separately; and BSP's carrier name is free text, so
     grouping on it splits one airline across several rows.

SIGN IS NOT STORED. `direction` is a discriminator, never a multiplier, and no measure
is negated on the way in. The customer side's `incentive` is a commission we PAY, but
it is stored exactly as the ticket screen shows it so that a drill-through matches byte
for byte. The sign is applied once, in the aggregate, in services/income_board/
measures.py. A stored `net_income` or `direction_sign` column would be applied twice by
the first person who forgot it already had been.

NOT STORED, DELIBERATELY: any rate (non-additive), any accrual figure (services/
plb_accrual.py remains the accrual authority), and any `ticket_id`. The vendor/customer
relation is many-to-many in both directions at once — a multi-sector ticket is N
`uploaded_tickets` rows sharing one number with the money divided between them, while
one ticket attracts many vendor rows (TKTT, ADM, ACM, RFND, EMD, EXCH all key on one
document number) — so the difference is taken by subtracting aggregates, never by
joining rows.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    SmallInteger, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# `direction` — the deal that produced the figure. inbound = income we EARN,
# outbound = commission we PAY. Mirrors models/deal.DealDirection.
DIRECTION_INBOUND = "inbound"
DIRECTION_OUTBOUND = "outbound"

# `counterparty_kind` — who the money is with, which is what the board groups by.
KIND_AIRLINE = "airline"      # bsp, lcc-detailed: the carrier IS the counterparty
KIND_SUPPLIER = "supplier"    # tp-gds, tp-lcc: a consolidator we bought through
KIND_CUSTOMER = "customer"    # the selling side (phase 2)

# `source` — which store the row was projected from.
SOURCE_BSP = "bsp"
SOURCE_TP_GDS = "tp-gds"
SOURCE_TP_LCC = "tp-lcc"
SOURCE_LCC_DETAILED = "lcc-detailed"
SOURCE_TICKETS = "uploaded-ticket"

VENDOR_SOURCES = (SOURCE_BSP, SOURCE_TP_GDS, SOURCE_TP_LCC, SOURCE_LCC_DETAILED)

# `txn_class` — what kind of event the line is. Derived from the transaction-type sets
# in services/bsp_commission.py, which services/plb_accrual.py already imports the same
# way. Only `sale` and `refund` carry revenue; the memo classes must stay out of every
# denominator.
TXN_SALE = "sale"
TXN_REFUND = "refund"
TXN_DEBIT_MEMO = "debit_memo"
TXN_CREDIT_MEMO = "credit_memo"
TXN_ADJUSTMENT = "adjustment"
TXN_OTHER = "other"

REVENUE_TXN_CLASSES = (TXN_SALE, TXN_REFUND)

# The only statuses whose `incentive` may be summed. Mirrors
# services/commission/runner.MATCHED_STATUSES — if that changes, so must this.
MATCHED_STATUSES = ("calculated", "reversed")

# Bumped when the projection's arithmetic changes, so a half-reprojected table is
# visible rather than quietly inconsistent.
PROJECTION_VERSION = "1.0"


class IncomeBoardRow(Base):
    __tablename__ = "income_board_rows"
    __table_args__ = (
        # One current row per source row — the same uniqueness commission_calculations
        # and sell_reconciliations already enforce. `source` separates the selling
        # side from the vendor sources, so `direction` is not needed in the key.
        UniqueConstraint("tenant_id", "created_by_id", "source", "source_row_id",
                         name="uq_income_board_source_row"),

        # Per-user reads (the default scope, matching every other screen).
        Index("ix_income_board_airline",
              "tenant_id", "created_by_id", "direction", "issue_ym", "airline_id"),
        Index("ix_income_board_supplier",
              "tenant_id", "created_by_id", "direction", "issue_ym", "supplier_id"),
        Index("ix_income_board_travel",
              "tenant_id", "created_by_id", "direction", "travel_ym"),
        Index("ix_income_board_status",
              "tenant_id", "created_by_id", "direction", "status"),

        # Whole-agency reads. A composite leading with created_by_id cannot serve a
        # query that omits it, so the tenant-wide mode needs its own pair. Only the two
        # dimensions the board actually groups by get one; travel and status fall back
        # to the scope index, which is acceptable on the rarer path.
        Index("ix_income_board_tenant_airline",
              "tenant_id", "direction", "issue_ym", "airline_id"),
        Index("ix_income_board_tenant_supplier",
              "tenant_id", "direction", "issue_ym", "supplier_id"),

        # Re-projection and the orphan sweep delete by this.
        Index("ix_income_board_batch", "tenant_id", "source", "batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False)

    source: Mapped[str] = mapped_column(String(24), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Points at a different table per `source`, so no FK — the same call
    # commission_calculations.source_row_id makes.
    source_row_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # ── Discriminators ───────────────────────────────────────────────────────
    direction: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=DIRECTION_INBOUND)
    counterparty_kind: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=KIND_AIRLINE)

    # ── Carrier. No FK: this table must never block a master-data delete. ────
    airline_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Label only, never a grouping key.
    airline_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # numeric_code | declared | resolved | NULL — how the carrier was arrived at, so an
    # unattributed-carrier bucket can explain itself rather than just being a gap.
    airline_match_by: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # ── B2B counterparty (tp-* only) ─────────────────────────────────────────
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supplier_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 'id' | 'name' | 'unrestricted'. A name match cannot tell two branches of one
    # vendor apart, so supplier-wise income built on it carries a caveat.
    supplier_match_by: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # Secondary attribute only. deals.vendor_agency_id is explicitly NOT the match key
    # and is not backfilled — see its own migration. Never group on it.
    vendor_agency_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Customer party. Ships nullable now; written in phase 2. ──────────────
    customer_party_kind: Mapped[str | None] = mapped_column(String(12), nullable=True)
    customer_party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    billing_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Time ─────────────────────────────────────────────────────────────────
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    issue_ym: Mapped[str | None] = mapped_column(String(7), nullable=True)
    # Third-party statements carry no ticketing date; issue_date falls back to the
    # booking date and the source says which, so the board can say so too.
    issue_date_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    travel_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    travel_ym: Mapped[str | None] = mapped_column(String(7), nullable=True)
    travel_date_source: Mapped[str | None] = mapped_column(String(12), nullable=True)
    # The source kept unparseable date text rather than blanking it, "so nobody reads a
    # blank accrual bucket as 'no sales'" (services/flat_statement.py). Carried here for
    # the same reason.
    date_parse_failed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false")

    # ── Deal-matching criteria ───────────────────────────────────────────────
    # 'I' | 'D' | NULL, via deal_matching.segment_letter. See invariant 4.
    segment: Mapped[str | None] = mapped_column(String(1), nullable=True)
    segment_raw: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # NULL on every lcc-detailed row by design: its product_class is a fare family
    # ("Flexi"), not an RBD, and the adapter refuses to present it as one.
    booking_class: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # ── Transaction ──────────────────────────────────────────────────────────
    txn_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    txn_class: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=TXN_OTHER)

    # ── Money ────────────────────────────────────────────────────────────────
    # Signed, as the document prints it: a refund is negative. 'printed' when the
    # source stated a total, 'derived' when it was assembled from components.
    gross_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    gross_source: Mapped[str | None] = mapped_column(String(12), nullable=True)
    fare_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yq: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yr: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    taxes_total: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    ancillary_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # NULLABLE AND LOAD-BEARING — invariant 1. Never collapse to zero.
    incentive: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Invariant 2. Never added to `incentive`.
    iata_commission: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Phase 2: the markup actually charged, off billings.line_items[] per line. NOT off
    # the invoice total — one invoice covers many tickets, and spreading its total onto
    # each would book the markup once per ticket.
    markup_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    additional_markup_amount: Mapped[float | None] = mapped_column(
        Numeric(14, 2), nullable=True)

    # ── What the vendor SAYS it paid. NULL for BSP and lcc-detailed. ─────────
    declared_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    declared_incentive: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    declared_tds: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    declared_net: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # NULL means could not be judged, which is NOT False.
    declared_net_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Positive = under-recovery: the vendor owes us.
    variance_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    # ── Why the figure is what it is ─────────────────────────────────────────
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    skipped_criteria: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    matched_deal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    matched_deal_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    matched_deal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matched_deal_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # This line's incentive depends on a slab that may not have been reached yet, so it
    # is not additive across time the way a flat-rate line is. Any month bucket holding
    # one gets a "restated" marker; plb_accrual stays the authority for PLB at risk.
    slab_dependent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false")

    # ── Identity ─────────────────────────────────────────────────────────────
    document_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ticket_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # norm_tn() materialised once. The column is free — the value is already in hand —
    # but it stays unindexed until phase 3 gives it a join to serve.
    ticket_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pnr: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pax_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")

    # ── Bookkeeping ──────────────────────────────────────────────────────────
    # NULL for BSP and for tickets: neither runs through commission_runs.
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commission_runs.id", ondelete="SET NULL"), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    projection_version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # server_default rather than a Python default: every row is written by an
    # INSERT ... SELECT, where a model-side default would never fire.
    projected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now())
    # Never updated on re-projection: when this line was first priced, as opposed to
    # when it was last restated.
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now())
