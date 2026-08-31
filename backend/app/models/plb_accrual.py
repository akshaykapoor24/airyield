"""PLB accrual board — the persisted inputs behind Dashboard → PLB Accrual.

The board itself is DERIVED, not stored: flown revenue is aggregated live from
`bsp_statement_rows` / `lcc_detailed` / `third_party_*`, the deflator is derived
from the fare components on those same rows, and the PLB rate comes off the deal.
Re-uploading a statement therefore moves the number, which is correct while a
period is still open.

Three things cannot be derived, and those are what live here:

  1. plb_accrual_inputs    — a human's override of a single cell. A negotiated
     deflator the observed data does not show, a rate agreed off-contract, or the
     provisional flown figure the airline emailed before any statement arrived.
     NULL means "no override, use the derived value" — the row exists as soon as
     ANY of the three is set, so one row can carry all three.

  2. plb_airline_settings  — the sheet's "Flown Confirmation Status" column: the
     last month this airline has CONFIRMED flown data for. Everything after it is
     provisional, and the board says so instead of implying the airline agrees.

  3. plb_accrual_snapshots — a frozen period. Once finance books an accrual, a
     late statement upload must not silently restate last quarter. Freezing copies
     the whole grid into JSONB and the board renders from it until re-opened.

GRAIN. The first two are keyed by the identity columns of a board row —
(airline_name, entity, channel, lob) — as normalised text, NOT by deal id. A deal
gets superseded and re-issued every contract year; the assumption about how much
of KLM's YFB flown revenue is commissionable outlives any one contract row, and
should not have to be re-entered when the deal rolls over.

Because those four are part of a UNIQUE constraint and Postgres does not dedupe
NULLs, every one of them is NOT NULL with a '' default. `norm_key()` in
services/plb_accrual.py is the single place that maps a value to its stored form.
"""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlbAccrualInput(Base):
    """One overridden cell of the accrual grid, for one month.

    All three value columns are nullable and independent: setting `manual_flown`
    for a month the statements do not cover does not also pin that month's
    deflator. A row where all three are NULL is a no-op and is deleted rather
    than stored.
    """
    __tablename__ = "plb_accrual_inputs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "created_by_id", "airline_key", "entity_key",
            "channel_key", "lob_key", "ym",
            name="uq_plb_accrual_inputs_cell",
        ),
    )

    id:            Mapped[int]        = mapped_column(BigInteger, primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # ── Grain — normalised, never NULL (see module docstring) ────────────────
    airline_key:   Mapped[str]        = mapped_column(String(255), nullable=False, server_default="")
    entity_key:    Mapped[str]        = mapped_column(String(255), nullable=False, server_default="")
    channel_key:   Mapped[str]        = mapped_column(String(20),  nullable=False, server_default="")
    lob_key:       Mapped[str]        = mapped_column(String(100), nullable=False, server_default="")
    ym:            Mapped[str]        = mapped_column(String(7),   nullable=False)   # 'YYYY-MM'

    # ── The overrides. NULL = fall back to the derived value ─────────────────
    # 7,4 holds 100.0000 down to 0.0001% — the sheet quotes deflators to two
    # decimals (81.18) and rates to two (1.40), with headroom either way.
    deflator_pct:  Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    plb_rate_pct:  Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    # Signed: a month can be net negative when refunds outweigh issues, exactly
    # as GULF AIR's April (-1,82,631) is in the source sheet.
    manual_flown:  Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)

    note:          Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlbAirlineSetting(Base):
    """Per (airline × entity × channel) settings that are not month-specific."""
    __tablename__ = "plb_airline_settings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "created_by_id", "airline_key", "entity_key", "channel_key",
            name="uq_plb_airline_settings_scope",
        ),
    )

    id:            Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id:     Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    airline_key:   Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    entity_key:    Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    channel_key:   Mapped[str] = mapped_column(String(20),  nullable=False, server_default="")

    # The sheet's "Flown Confirmation Status" — stored as the FIRST day of the
    # confirmed month so it compares cleanly against a month bucket. A month
    # later than this is provisional and the board flags it UNCONFIRMED.
    flown_confirmed_through: Mapped[date | None]  = mapped_column(Date, nullable=True)
    # Used when a month has no statement data of its own to derive a deflator
    # from, and no trailing-3-month history either.
    default_deflator_pct:    Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)

    note:          Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlbAccrualSnapshot(Base):
    """A frozen period. `grid` is the exact response the board rendered at freeze
    time, so re-opening it later shows what was booked, not what today's data
    would produce."""
    __tablename__ = "plb_accrual_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "created_by_id", "period_key",
            name="uq_plb_accrual_snapshots_period",
        ),
    )

    id:            Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id:     Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    period_key:    Mapped[str] = mapped_column(String(20), nullable=False)   # 'AMJ-26', '2026-04', 'FY26'
    period_from:   Mapped[date] = mapped_column(Date, nullable=False)
    period_to:     Mapped[date] = mapped_column(Date, nullable=False)

    grid:          Mapped[dict] = mapped_column(JSONB, nullable=False)
    totals:        Mapped[dict] = mapped_column(JSONB, nullable=False)
    row_count:     Mapped[int]  = mapped_column(Integer, nullable=False, default=0)
    total_accrual: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)

    note:          Mapped[str | None] = mapped_column(String(500), nullable=True)
    frozen_by_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    frozen_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
