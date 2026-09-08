"""One attempt at pricing one statement against the deals that cover it.

THIS TABLE IS THE MISSING BATCH HEADER. BSP has somewhere to keep run state — fifteen
`commission_*` columns on `bsp_statements` (models/bsp_statement.py) — because a BSP upload
is a real row. The spec-driven types have no such row: a "batch" is a shared `batch_id`
string across the rows table, derived with a GROUP BY. So status, progress, heartbeat and
the roll-up totals need a home, and this is it — for third-party GDS/LCC and LCC Detailed
now, and for BSP too once its figures are projected here (deliberately later, and as a
read-only projection; see docs).

ONE ROW PER ATTEMPT, not one per statement. The history is the point: `engine_version` and
`params` are what let someone answer "why did last Tuesday's run pay this and today's
doesn't" without archaeology. Readers take the latest by `started_at DESC`.

`batch_id` carries NO foreign key, for the same reason `statement_batch_agencies` doesn't:
the sources it points at share no header table between them. `source` is what says which
table `batch_id` means, and it is the statement slug wherever one exists.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Where a run's rows came from. The statement slug where there is one, so a reader never
# has to translate between two vocabularies.
SOURCE_TP_GDS = "tp-gds"
SOURCE_TP_LCC = "tp-lcc"
SOURCE_LCC_DETAILED = "lcc-detailed"
SOURCE_BSP = "bsp"

# Bumped when a change would make the same statement price differently. Stored on the run
# so an old figure stays explainable after the engine moves on.
ENGINE_VERSION = "1.0"


class CommissionRun(Base):
    __tablename__ = "commission_runs"
    __table_args__ = (
        Index("ix_commission_runs_lookup", "tenant_id", "created_by_id", "source", "batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True)

    source: Mapped[str] = mapped_column(String(24), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 'inbound' for every vendor run. Reserved so the customer-payout side (which prices
    # outgoing deals against the same ledger) does not need a second pair of tables.
    direction: Mapped[str] = mapped_column(String(10), nullable=False, server_default="inbound")
    engine_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # idle | queued | processing | completed | failed
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="queued")
    # queued = handed to the worker; inline = a hand-picked selection run in the request.
    mode: Mapped[str] = mapped_column(String(10), nullable=False, server_default="queued")

    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # Stamped on every progress flush. A run claiming to be alive with a stale heartbeat is
    # a dead worker — services/commission_core.is_stale — and the user is offered a release
    # rather than left watching a frozen bar.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Roll-ups, always RECOMPUTED from the ledger rather than accumulated as the run goes.
    # A selected-rows re-run would otherwise leave the headline disagreeing with the grid.
    calculated_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    needs_data_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    excluded_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reversed_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unmatched_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pending_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    total_incentive: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_iata: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    # What the VENDOR's own statement said it paid, and the gap against what the deals say.
    # NULL for BSP and LCC Detailed, which print no such figures — the columns exist once
    # rather than as a third-party-only side table.
    declared_commission_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    declared_incentive_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Positive = under-recovery: the consolidator owes you.
    variance_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Rows whose declared figures did not add up to their own Net Amount, and which are
    # therefore excluded from `variance_total` — a variance against arithmetic that does
    # not close is meaningless, and hiding that would be worse than showing it.
    variance_unverified_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # The inputs the run was given: agency, statement type, skip criteria. Not decoration —
    # it is what makes a figure reproducible after the statement or the deal has moved on.
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
