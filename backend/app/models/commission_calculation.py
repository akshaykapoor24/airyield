"""What one statement row earned, and how that was decided.

BSP writes its answers onto the settlement row itself (`bsp_statement_rows.calculated_
incentive` and friends). That works because BSP owns its rows. The third-party and LCC
tables hold the vendor's document, and a figure WE derived is not part of their document —
so the new sources write here instead.

ONE CURRENT ROW PER SOURCE ROW, upserted on re-run: `uq_commission_calc_source_row`. The
tempting alternative — append-only, keyed by run — forces every roll-up through a
"latest run" subquery and double-counts the first time anyone forgets one. Run HISTORY is
kept in `commission_runs`, which is what you actually look back at; `run_id` here is just a
pointer to whichever run wrote the current answer.

`incentive` IS NULLABLE AND THAT IS LOAD-BEARING. NULL means a deal matched but pays on
something this document does not print, so nothing is claimed. Zero means the deal applied
and earned nothing. Collapsing the two would turn "we could not confirm what you are owed"
into "you are owed nothing", which is a number someone would act on.

The INPUTS block is a snapshot, not a join. A source row can be reprocessed under a new
column spec, and a deal can be edited or deleted; without the snapshot, last week's figure
would silently start explaining itself with this week's inputs.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CommissionCalculation(Base):
    __tablename__ = "commission_calculations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "created_by_id", "source", "source_row_id",
                         name="uq_commission_calc_source_row"),
        Index("ix_commission_calc_batch", "source", "batch_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # SET NULL, not CASCADE: the calculation outlives the run that produced it — deleting
    # run history must not delete the money.
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commission_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    # Denormalised so every read scopes without a join back to the run.
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    source: Mapped[str] = mapped_column(String(24), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # third_party_gds.id / lcc_detailed.id / … — no FK, because it points at a different
    # table per `source`. Deleting a batch or a row clears these explicitly
    # (api/v1/statements.py), and so does a reprocess, whose new rows get new ids.
    source_row_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # calculated | needs_data | excluded | reversed | skipped | unmatched | pending
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    matched_deal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    matched_deal_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    matched_deal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matched_deal_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 'id' | 'name' | 'unrestricted' — how the B2B counterparty was matched. A NAME match
    # is real but unverified: it cannot tell two channels of one vendor apart, so the UI
    # flags it rather than presenting it like an id match. See deal_matching._supplier_guard.
    supplier_match_by: Mapped[str | None] = mapped_column(String(12), nullable=True)

    incentive: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    iata_commission: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    incentive_breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # What this row genuinely could not evaluate, and what the deal wanted but nobody
    # checked. Kept apart: the first is about the document, the second about the contract.
    skipped_criteria: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    unconfirmed_criteria: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Free-text notes about THIS row's calculation — a missing YR column, an undifferentiated
    # SSR amount, a carrier resolved against a disagreeing name. Shown, not swallowed.
    notes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Inputs snapshot: what the match actually saw ─────────────────────────
    airline_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    airline_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    travel_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    segment_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    booking_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fare_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yq: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    yr: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    ancillary_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # ── Declared: what the vendor SAYS it paid. NULL for BSP / LCC Detailed ──
    # Gross of TDS, because a deal's rates are gross too — netting the TDS off first would
    # print a phantom shortfall on every commission-bearing row.
    declared_commission: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    declared_incentive: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    declared_tds: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    declared_net: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Did the vendor's own components add up to its own Net Amount? NULL = could not be
    # judged, which is NOT the same as False — see services/commission/third_party.py.
    declared_net_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ── Variance: positive = under-recovery, the vendor owes you ─────────────
    variance_commission: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    variance_incentive: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    variance_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    # ── Identity, for the grid and the export ────────────────────────────────
    document_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ticket_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pnr: Mapped[str | None] = mapped_column(String(40), nullable=True)
    passenger_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(String(24), nullable=True)

    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
