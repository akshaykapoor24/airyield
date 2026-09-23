"""Every statement line, from every source, in the shape the dashboards read.

TWO BOARDS, ONE TABLE. `/dashboard/income` asks what the PRICED statements earned;
`/dashboard/revenue` asks what every loaded statement SOLD and what that sale earned.
They are the same rows seen through two predicates, so they share this table rather than
two projections that would drift:

  * the income board filters `priced = TRUE`, and its counts keep meaning priced lines;
  * the revenue board filters `counts_in_net = TRUE`, which is what stops a statement
    that merely restates another one from being added to a sale total twice.

A row is written whether or not commission has ever been run on it. `priced=False` with
a NULL `incentive` says "not costed yet", which is a different claim from an unmatched
row, and both are different from a confirmed zero — see invariant 1.

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

THE SEVEN INVARIANTS THIS TABLE EXISTS TO ENFORCE

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
  6. `txn_class` is read through EACH SOURCE'S OWN vocabulary, never through one. This
     one was learned the hard way: dimensions.txn_class_sql was generated from BSP's
     transaction types alone, while commission_calculations.transaction_type holds a
     ticket STATUS for tp-gds/tp-lcc ("CONFIRMED", "REFUNDED") and a bill_kind for
     lcc-detailed ("sale", "refund"). None of those is in BSP's set, so every non-BSP
     row classified as 'other' and `gross_revenue()` — which filters on sale|refund —
     silently returned BSP-only figures from the day the table shipped. Nothing errored.
     Each arm now derives its CASE from its own engine's constants, and a test feeds the
     Python classifier and the compiled SQL the same literals per source.
  7. `counts_in_net` is the Report Download's rule set, not a second opinion. The
     vocabulary and the reasons are services/report_download/columns.COUNTS_IN_NET_RULES,
     rendered into SQL here. Two independently-written definitions of "does this line
     count" would give finance two authoritative sale figures and no way to tell which
     is right; a reconciliation test runs both over one batch for that reason.

THE DIRECTION SIGN IS NOT STORED. `direction` is a discriminator, never a multiplier,
and no measure is negated on the way in for it. The customer side's `incentive` is a
commission we PAY, but it is stored exactly as the ticket screen shows it so that a
drill-through matches byte for byte. That sign is applied once, in the aggregate, in
services/income_board/measures.py. A stored `net_income` or `direction_sign` column
would be applied twice by the first person who forgot it already had been.

THE TRANSACTION SIGN IS A DIFFERENT THING AND IT *IS* NORMALISED HERE. A refund must
reduce gross, and the sources disagree about how they say so: BSP and LCC Detailed print
a negative, while NDC, TGQ, the memos and every third-party type print a magnitude and
leave the direction to the transaction type — that is exactly the `sign_mode`
`native`/`type_signed` split in services/report_download/registry.py. The projection
applies `columns.TYPE_SIGN` to the type-signed arms so that every row reaching this table
is signed the same way. Not doing so is not a cosmetic bug: a refund would ADD to the
sale total, and the total would still look plausible.

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
    SmallInteger, String, UniqueConstraint, func, text,
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

# `source` — which store the row was projected from. Spelled identically to
# services/report_download/registry.SOURCES[].key, so the two registries can be asserted
# equal rather than kept equal by hand; `test_income_board` does exactly that.
SOURCE_BSP = "bsp"
SOURCE_NDC = "ndc"
SOURCE_TP_GDS = "tp-gds"
SOURCE_TP_LCC = "tp-lcc"
SOURCE_TP_API = "tp-api"
SOURCE_LCC_DETAILED = "lcc-detailed"
SOURCE_TICKETS = "uploaded-ticket"

VENDOR_SOURCES = (SOURCE_BSP, SOURCE_NDC, SOURCE_TP_GDS, SOURCE_TP_LCC,
                  SOURCE_TP_API, SOURCE_LCC_DETAILED)

# The six statement types whose gross IS the agency's sale. Everything else a tenant
# uploads — TGQ HMPR, ADM/ACM/RA, the four LCC ledgers — restates one of these six: a TGQ
# line is the same ticket as its BSP row, a memo counts through the BSP ADMA row, a flown
# report line is the same booking as its LCC Detailed row. Those are projected too (so
# they can be read airline-wise) but always with `counts_in_net=False`, which is what
# keeps them out of every sale total. The rule set is
# services/report_download/columns.COUNTS_IN_NET_RULES, and this tuple is the same
# decision expressed as the sources that survive it.
SALE_SOURCES = (SOURCE_BSP, SOURCE_NDC, SOURCE_LCC_DETAILED,
                SOURCE_TP_GDS, SOURCE_TP_LCC, SOURCE_TP_API)

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
#
# 2.0 — the table stopped being "every priced line" and became every statement line.
# Three things changed at once and none of them is backward compatible: `source_row_id`
# now points at the STATEMENT row rather than the calculation row for tp-gds / tp-lcc /
# lcc-detailed; unpriced rows are projected, carrying `priced=False` and a NULL
# incentive; and ndc / tp-api joined the arms. The migration empties the table for that
# reason — every row is derived, so the cost is one Rebuild.
PROJECTION_VERSION = "2.0"


class IncomeBoardRow(Base):
    __tablename__ = "income_board_rows"
    __table_args__ = (
        # One current row per source row — the same uniqueness commission_calculations
        # and sell_reconciliations already enforce. `source` separates the selling
        # side from the vendor sources, so `direction` is not needed in the key.
        UniqueConstraint("tenant_id", "created_by_id", "source", "source_row_id",
                         name="uq_income_board_source_row"),

        # ── The income board's six, all PARTIAL on `priced` ───────────────────
        # Every one of these exists for /dashboard/income, and every read there now
        # carries `priced = TRUE`. Partial rather than adding the column to the key: the
        # table roughly doubles once unpriced statements land in it, and an index that
        # only ever serves priced reads should not carry the other half.
        Index("ix_income_board_airline",
              "tenant_id", "created_by_id", "direction", "issue_ym", "airline_id",
              postgresql_where=text("priced")),
        Index("ix_income_board_supplier",
              "tenant_id", "created_by_id", "direction", "issue_ym", "supplier_id",
              postgresql_where=text("priced")),
        Index("ix_income_board_travel",
              "tenant_id", "created_by_id", "direction", "travel_ym",
              postgresql_where=text("priced")),
        Index("ix_income_board_status",
              "tenant_id", "created_by_id", "direction", "status",
              postgresql_where=text("priced")),

        # Whole-agency reads. A composite leading with created_by_id cannot serve a
        # query that omits it, so the tenant-wide mode needs its own pair. Only the two
        # dimensions the board actually groups by get one; travel and status fall back
        # to the scope index, which is acceptable on the rarer path.
        Index("ix_income_board_tenant_airline",
              "tenant_id", "direction", "issue_ym", "airline_id",
              postgresql_where=text("priced")),
        Index("ix_income_board_tenant_supplier",
              "tenant_id", "direction", "issue_ym", "supplier_id",
              postgresql_where=text("priced")),

        # ── The revenue board's two, PARTIAL on `counts_in_net` ───────────────
        # Sale by statement type and month, and sale by carrier. Partial for the mirror
        # of the reason above: a revenue read never wants a row that restates another
        # one, and the restating sources (TGQ, the memos, the LCC ledgers) are bulky.
        # No `created_by_id`: this board defaults to agency scope.
        Index("ix_income_board_sale",
              "tenant_id", "direction", "issue_ym", "source",
              postgresql_where=text("counts_in_net")),
        Index("ix_income_board_sale_airline",
              "tenant_id", "direction", "airline_id", "issue_ym",
              postgresql_where=text("counts_in_net")),

        # The NDC-settled-through-BSP join. Both columns NULL on a document that cannot
        # be linked, and Postgres leaves NULLs out of the scan, so the index is only as
        # big as the rows that can actually match.
        Index("ix_income_board_doc", "tenant_id", "doc_code", "doc_serial"),

        # Re-projection and the orphan sweep delete by this. NOT partial: it has to find
        # every row of a batch, priced or not, counted or not.
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
    # Air | Hotel | Train | Bus | Car. NULL means air, and only tp-api ever sets it:
    # one aggregator file carries five products side by side and a hotel night has no
    # carrier, so an airline-wise view has to be able to say "not carrier-attributed"
    # rather than bucket it beside a genuine resolution failure.
    product: Mapped[str | None] = mapped_column(String(12), nullable=True)

    # ── May this row enter a sale total? ─────────────────────────────────────
    # PER ROW, NOT PER SOURCE, and that is the whole reason it is a column. An LCC
    # payment movement with no fare, a cancelled aggregator booking and the statement's
    # own footer line all sit in the same table beside real sales, and an NDC ticket
    # that also settled through BSP is counted once on the BSP side. The rule set is
    # services/report_download/columns.COUNTS_IN_NET_RULES; `counts_in_net_reason` holds
    # whichever NET_* string applied, so the screen can say WHY a row is out instead of
    # silently omitting it. Default TRUE: a row is money until something says otherwise.
    counts_in_net: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true")
    counts_in_net_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # ── Money ────────────────────────────────────────────────────────────────
    # TOTALS ARE PER CURRENCY AND ARE NEVER CONVERTED OR ADDED ACROSS THEM — the rule
    # services/report_download/summary.py already holds every report to. Without the
    # column a board cannot honour it, and the failure is silent: two currencies simply
    # add. BSP rows carry no currency of their own (theirs is on the summary header), so
    # they are stamped 'INR' the way mappers/bsp.py already assumes, and `gross_source`
    # records that it was assumed rather than read.
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Signed so that a refund subtracts. Sources differ in how they say so and the
    # projection normalises it: BSP, LCC Detailed and the LCC ledgers print their own
    # sign, while NDC, TGQ, the memos and every third-party type print a magnitude and
    # leave the direction to the transaction type (registry.sign_mode='type_signed').
    # Both arrive here already signed. 'printed' when the source stated a total,
    # 'derived' when it was assembled from components.
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
    # {incentive_type: amount}, carried verbatim off commission_calculations /
    # bsp_statement_rows. It is the only way "how much PLB did this airline earn" is a
    # GROUP BY rather than a loop over every priced row in Python, and the keys are open
    # on purpose — deal_incentives.incentive_type is a String, so a new incentive type
    # must show up on the board without a code change. Its values always sum to
    # `incentive` for a claimable row; it is NULL wherever `incentive` is.
    incentive_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    # Has the commission engine ever seen this row? FALSE means the statement is loaded
    # but has not been costed, so `incentive` is NULL for a reason that has nothing to
    # do with the deal — which is a third thing, distinct from 'unmatched' (ran, matched
    # no deal) and from a confirmed zero. The income board filters on it so its "priced
    # lines" counts keep meaning what they meant before unpriced rows existed.
    priced: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
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
    # The document identity, split the way report_download/normalize.doc_key splits it:
    # a 3-digit accounting code and a 10-digit serial, WITH the leading zeros kept.
    #
    # NOT `ticket_key`, and the difference is the whole point of the pair. `norm_tn`
    # strips leading zeros, which is harmless when joining BSP to internal tickets but
    # wrong for linking two vendor documents — "098 0123456789" and "098 123456789" are
    # different documents, and normalize.py's header says so. The NDC-settled-through-BSP
    # test joins on this pair; joining on `ticket_key` would over-match and zero out NDC
    # sale that BSP never settled.
    #
    # NULL where the printed number is neither 13 digits nor a bare serial with a known
    # carrier code — a document that cannot be linked, rather than one linked wrongly.
    doc_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    doc_serial: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
