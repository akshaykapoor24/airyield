"""Payment Module: the vendor's bill against our own mid-office record, per ticket.

The question is "is what this consolidator is billing us what our books say, and what
should we actually pay once our deal's commission is applied?". The VENDOR side is one
upload of `third_party_gds` (the same rows Statements → Third Party → GDS and Commission
income read); the MO side is one upload of `mid_office_gds`. Both are netted per ticket
before they meet — see services/payment_reconciliation.py.

SIGN CONVENTION: `variance = vendor - mo`. Positive means the vendor billed MORE than our
books record — the direction a payer cares about. Different from both other engines on
purpose (`sell - buy` in sell_reconciliation, `expected - actual` in bsp_reconciliation);
the three never share a row.

COMMISSION: `commission_shortfall` is the deal-computed commission minus what the vendor
declared, taken from `commission_calculations` (source `tp-gds`) for rows a deal actually
priced. Positive = the vendor under-paid us commission, so `payable_after_commission =
vendor_net - commission_shortfall` is less than the bill.

`vendor_row_ids` / `mo_row_ids` carry NO foreign key, for the reason
`commission_calculations.source_row_id` doesn't: a statement row is re-inserted with new
ids on reprocess, and a derived report must never be the reason a statement cannot be
deleted. The run is a report, recomputed wholesale per (vendor upload, MO upload) pair.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Bumped when a change would make the same pair of uploads reconcile differently.
ENGINE_VERSION = "1.0"

# The verdicts. `vendor_only` / `mo_only` rather than buy_only / sell_only: both sides here
# are records of the SAME purchase, so neither "bought" nor "sold" describes either one.
STATUS_MATCHED = "matched"
STATUS_MINOR_DIFF = "minor_diff"
STATUS_MISMATCH = "mismatch"
STATUS_POSSIBLE = "possible_match"   # same serial, different airline — never auto-linked
STATUS_VENDOR_ONLY = "vendor_only"   # billed by the vendor, absent from our books
STATUS_MO_ONLY = "mo_only"           # in our books, not on the vendor's bill

PAYMENT_RECON_STATUSES = (
    STATUS_MATCHED, STATUS_MINOR_DIFF, STATUS_MISMATCH,
    STATUS_POSSIBLE, STATUS_VENDOR_ONLY, STATUS_MO_ONLY,
)

# How far the deal-computed commission reached a ticket. Per TICKET, rolled up from the
# vendor rows behind it — see payment_reconciliation._commission_for_group.
MO_VENDOR_OK = "ok"                     # paired within this vendor's own MO file
MO_VENDOR_OTHER = "other_vendor"        # found only in ANOTHER vendor's MO file (6C)
MO_VENDOR_CORRECTED = "corrected"       # was elsewhere; a correction now files it here
MO_VENDOR_NONE = "none"                 # no MO side (vendor-only) or an MO-only row

COMMISSION_PRICED = "priced"            # every sale row a deal priced, arithmetic closed
COMMISSION_PARTIAL = "partial"          # some rows priced, some not (needs data, no deal…)
COMMISSION_UNPRICED = "unpriced"        # commission ran, but no row of this ticket priced
COMMISSION_SKIPPED = "skipped"          # only non-sales (cancelled/void) — nothing to price
COMMISSION_NOT_RUN = "not_run"          # no commission figures for these rows at all
COMMISSION_NONE = "none"                # no vendor rows (an MO-only ticket)


class PaymentReconciliationRun(Base):
    """One reconciliation of one vendor upload against one MO upload.

    Totals are RECOMPUTED from the rows just written, never accumulated as the run goes,
    so the headline cannot drift from the grid.
    """
    __tablename__ = "payment_reconciliation_runs"
    __table_args__ = (
        Index("ix_payment_recon_runs_pair", "tenant_id", "created_by_id",
              "vendor_batch_id", "mo_batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    vendor_batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    mo_batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # processing | completed | failed
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="processing")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # ── counts ───────────────────────────────────────────────────────────────
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    matched_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    minor_diff_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mismatch_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    possible_match_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    vendor_only_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mo_only_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # ── money ────────────────────────────────────────────────────────────────
    # Every vendor ticket's net — the bill for the period, balance lines excluded.
    vendor_net_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    mo_net_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Paired rows only: vendor - mo.
    net_variance_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    vendor_only_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    mo_only_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    calc_commission_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    vendor_commission_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    shortfall_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    payable_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # The statement's own closing BALANCE line, when it prints one. NULL = none found.
    vendor_closing_balance: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    mo_closing_balance: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    # ── the commission figures this run read ─────────────────────────────────
    # So the screen can say "commission was recalculated after this reconciliation".
    commission_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    commission_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    commission_priced_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    commission_unpriced_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # The inputs and anything else worth reproducing later — file names, row counts,
    # balance lines found.
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaymentReconciliation(Base):
    """One reconciled ticket: a vendor group, an MO group, or the two paired.

        matched / minor_diff / mismatch / possible_match → both row-id lists set
        vendor_only → vendor_row_ids set, mo_row_ids empty
        mo_only     → mo_row_ids set, vendor_row_ids empty
    """
    __tablename__ = "payment_reconciliations"
    __table_args__ = (
        Index("ix_payment_recon_pair", "tenant_id", "created_by_id",
              "vendor_batch_id", "mo_batch_id"),
        Index("ix_payment_recon_pair_status", "tenant_id", "created_by_id",
              "vendor_batch_id", "mo_batch_id", "match_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    vendor_batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    mo_batch_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # No FK — see the module docstring. How many rows each side netted into this ticket.
    vendor_row_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    mo_row_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    vendor_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    mo_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # ── identity ─────────────────────────────────────────────────────────────
    # The serial, with the airline accounting code beside it — never joined into the key.
    ticket_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    ticket_prefix: Mapped[str | None] = mapped_column(String(4), nullable=True)
    airline_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    airline_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pax_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pnr: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # The group key ("k:<serial>", "p:<pnr|pax>", "r:<row id>") — what `payment_items` and
    # `mo_vendor_corrections` are keyed by, so a decision outlives the run that showed it.
    ticket_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)

    # ── verdict ──────────────────────────────────────────────────────────────
    match_status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # ok|warning|critical
    # ticket_number | pnr_pax | other_vendor | none
    match_method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")

    # ── process checks (steps 6A–6E) ─────────────────────────────────────────
    # 6D: the MO booking/invoice reference the ticket was billed under.
    booking_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 6D: paired with MO but MO shows no booking id (only flagged when that MO carries any).
    not_billed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # 6A/6B: a sale billed before (earlier upload) or twice in this one.
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    duplicate_info: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # 6C: ok | other_vendor (found in another vendor's MO file) | corrected | none
    mo_vendor_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    mo_vendor_info: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    # 6E: class / sector / travel date — what MO fills where the vendor prints nothing.
    enrichment: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)

    # ── headline money ───────────────────────────────────────────────────────
    vendor_gross: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    mo_gross: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    vendor_net: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    mo_net: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # vendor_net - mo_net, paired rows only.
    net_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # What the grid sorts on, worst first: |net_variance| on a paired row, the whole net
    # on a one-sided one (money nobody can account for), NULL on a possible match.
    abs_net_variance: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── commission ───────────────────────────────────────────────────────────
    # What the vendor printed (Agent Commission + Incentive), and what our MO says.
    vendor_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    mo_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Deal-computed (incentive + IATA) over the rows a deal priced. NULL = none priced.
    calc_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # calc - declared over priced rows whose arithmetic closed. Positive = they owe us.
    commission_shortfall: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    payable_after_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission_status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=COMMISSION_NONE)

    # ── detail ───────────────────────────────────────────────────────────────
    # [{key, label, vendor, mo, variance, match, severity}] — display order.
    field_diffs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    issues: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # One entry per vendor row: its commission status, deal, figures and reason.
    commission_detail: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    reconciled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
