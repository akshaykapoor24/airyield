from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Date, DateTime, Integer, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AgencyTerms(Base):
    """One row per commercial arrangement an agency has had, PER CHANNEL, effective-dated.

    `effective_to IS NULL` marks the arrangement in force now. This table is the
    ONLY source of truth for terms — the denormalised copy that used to sit on
    `agencies` is gone, because it had two disagreeing writers and, once an agency
    could be cash on one channel and credit on the other, no single correct value.

    CHANNEL IS THE POINT OF THIS TABLE. Lords is cash on GDS (he pays up front
    because we carry the BSP liability) and credit on LCC (exposure is capped by
    each airline's wallet). Those are two arrangements, two limits, two cycles and
    two balances under one agency, so `channel` is NOT NULL and
    `uq_agency_terms_current` — UNIQUE (agency_id, channel) WHERE effective_to IS
    NULL — makes "one open period per channel" a database fact rather than an
    assumption. current_terms() used to order-by and take the first row; with two
    channels that would have quietly returned the wrong one's limit.

    A period may only be closed (and the next one opened) at a cycle boundary
    with a settled, zero balance — see app.services.agency_account.switch_blockers.
    That invariant is what keeps each period a self-contained account: a cash
    period and a credit period never share a rupee, and neither does a GDS period
    and an LCC one.

    cash   -> usage_percent is the notify-at threshold; the limit is simply the
              money on deposit, so credit_limit is unused and stored NULL.
    credit -> credit_limit is the sanctioned line; usage_percent is unused.
    """
    __tablename__ = "agency_terms"

    id:         Mapped[int]        = mapped_column(primary_key=True)
    agency_id:  Mapped[int]        = mapped_column(Integer, ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id:    Mapped[int]        = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)

    # GDS | LCC — never BOTH. An arrangement is with one channel; an agency that
    # trades on both has two rows.
    channel:        Mapped[str]         = mapped_column(String(10), nullable=False)

    effective_from: Mapped[date]        = mapped_column(Date, nullable=False)
    effective_to:   Mapped[date | None] = mapped_column(Date, nullable=True)   # None = current

    agency_type:   Mapped[str]           = mapped_column(String(10), nullable=False)   # cash | credit
    credit_limit:  Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    usage_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    billing_cycle: Mapped[str]           = mapped_column(String(20), nullable=False)
    # Cycles are computed from here, not stored — "monthly" alone cannot say when
    # a month starts, and "the cycle is complete" is the switch precondition.
    cycle_anchor_date: Mapped[date]      = mapped_column(Date, nullable=False)

    note:          Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
