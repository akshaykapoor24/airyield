"""Series / SIT / MICE / Group contracts — the commercial agreement, its inventory and its money.

WHAT REPLACED WHAT. The first version of this feature was one flat table whose primary
idea was a PNR: a contract held `pnr_no` and the matching service counted the tickets
issued against it. That cannot hold a real contract. An airline group agreement covers
several departures, several flight legs and several PNRs, carries a deposit schedule and
a name-list deadline, and exists before any PNR does. So the PNR moved from the root to a
leaf:

    Contract → Allocation → Sector
                   ↓
                Booking (PNR) → Passenger → Ticket (uploaded_tickets)

with fare components, a payment schedule and deadlines running beside that spine.

WHY FARE IS A SET OF TYPED ROWS RATHER THAN A `fare_per_pax` COLUMN. Two real contracts
drove this, and they do not agree on what a percentage is a percentage OF. Air India
charges penalties on "AI retention", which its own text defines as Base + YQ. Air France
charges on "the fare", which its deposit arithmetic proves is the net fare alone — its two
deposits are exactly 5% and 25% of the net-fare total, not of the grand total. A single
`penalty_percent` column can express neither, because the number is meaningless without
the base it applies to. Storing fare as typed components makes a basis a named sum over
them (see `services/series/bases.py`), and two further clauses then fall out for free:
Air India's "for No-Show passengers only statutory taxes are refundable" is
`is_refundable_on_noshow`, and Air France's "YR-F and YR-I/YQ guaranteed until ticketing"
is `is_guaranteed_until_ticketing`.

The component codes are deliberately the vocabulary `uploaded_tickets` already uses
(`sell_fare`, `sell_tax_yq`, `sale_yr`, `sell_tax`), so contracted and actual can be
compared per component rather than only in total.

WHY `requested_pax` AND `firmed_pax` ARE TWO COLUMNS. Air India: "the group size would be
firmed up from the day of the advance deposit ... treated as sacrosanct viz 100% of the
group size." Materialization is measured against the size firmed at deposit, not the size
originally requested, so collapsing the two would compute the 80% floor off the wrong
denominator.

SCOPE IS THE TENANT, NOT THE CREATOR. Every other record in this codebase filters on
`tenant_id AND created_by_id`. These tables deliberately do not: a sixty-seat group with
a deposit due and a D-8 ticketing cut-off is an agency asset, and if the person who keyed
it in is on leave the deadline must not be invisible to everyone else. `created_by_id` is
kept as provenance and is not part of any scope filter. The matching service had to follow
— see the note in `services/series/matching.py` about why the ticket query drops the
creator too.

Status columns are plain strings with a CHECK, not an Enum type, so adding a state is a
CHECK-constraint migration rather than an ALTER TYPE. Same reasoning as `report_export`.
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, SmallInteger, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _check(column: str, values: tuple[str, ...]) -> str:
    """A CHECK body pinning a column to its vocabulary. NULL passes — every one of these
    columns is nullable on purpose, because a contract is keyed in over several steps and
    a half-filled draft must still save."""
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


# ── Vocabularies ──────────────────────────────────────────────────────────────

# GROUP is the one this rewrite adds. A one-off block for a single departure is not a
# Series: a series is repeated space across a period, and only it generates more than one
# allocation. The distinction is commercial, not cosmetic — it decides whether release
# management and utilisation apply.
CONTRACT_SERIES = "SERIES"
CONTRACT_SIT = "SIT"
CONTRACT_MICE = "MICE"
CONTRACT_GROUP = "GROUP"
CONTRACT_TYPES: tuple[str, ...] = (CONTRACT_SERIES, CONTRACT_SIT, CONTRACT_MICE, CONTRACT_GROUP)

SOURCE_AIRLINE = "AIRLINE"
SOURCE_B2B = "B2B"
SOURCE_TYPES: tuple[str, ...] = (SOURCE_AIRLINE, SOURCE_B2B)

CONTRACT_STATUSES: tuple[str, ...] = (
    "draft", "pending_review", "active", "closed", "cancelled",
)

# An allocation's life. `deposit_paid` is the one with teeth: Air India firms the group
# size on that day and the free-release window opens only between it and final payment.
ALLOCATION_STATUSES: tuple[str, ...] = (
    "planned", "held", "deposit_paid", "names_due", "ticketed", "departed", "cancelled",
)

DIRECTION_OUTBOUND = "OUTBOUND"
DIRECTION_INBOUND = "INBOUND"
DIRECTIONS: tuple[str, ...] = (DIRECTION_OUTBOUND, DIRECTION_INBOUND)

BOOKING_STATUSES: tuple[str, ...] = (
    "held", "ticketed", "partially_ticketed", "cancelled",
)

# INF_SEAT vs INF_LAP is load-bearing, not pedantry. Air India: "an infant occupying seat
# is to be treated as a Child", "an infant without a seat - ticket will be similar to
# normal infant ticket", and "one child would be counted as one adult to fulfil the
# minimum materialization". So a lap infant occupies no seat and counts toward no floor,
# while everything else does both.
PAX_ADT = "ADT"
PAX_CHD = "CHD"
PAX_INF_SEAT = "INF_SEAT"
PAX_INF_LAP = "INF_LAP"
PAX_TYPES: tuple[str, ...] = (PAX_ADT, PAX_CHD, PAX_INF_SEAT, PAX_INF_LAP)

NAME_STATUSES: tuple[str, ...] = (
    "pending", "named", "confirmed", "replaced", "cancelled",
)

# Fare components. BASE and YQ are separate because "AI retention (Base + YQ)" needs to
# add exactly those two. YR_I and YR_F are separate because Air France prints them as two
# guaranteed lines with different names and one of them (the Sustainable Fuel
# Contribution) is new enough that folding it into YR would lose it.
COMPONENT_BASE = "BASE"
COMPONENT_YQ = "YQ"
COMPONENT_YR_I = "YR_I"
COMPONENT_YR_F = "YR_F"
COMPONENT_TAX = "TAX_STATUTORY"
COMPONENT_OT = "OT"
COMPONENT_FEE = "FEE"
COMPONENT_CODES: tuple[str, ...] = (
    COMPONENT_BASE, COMPONENT_YQ, COMPONENT_YR_I, COMPONENT_YR_F,
    COMPONENT_TAX, COMPONENT_OT, COMPONENT_FEE,
)

# Instalment kinds. ADVANCE_DEPOSIT is distinguished from a plain DEPOSIT because Air
# India hangs two different rules off it: the group size firms on the day it is paid, and
# if it was a 100% advance deposit then no free seat release is permitted at all.
PAYMENT_ADVANCE_DEPOSIT = "ADVANCE_DEPOSIT"
PAYMENT_DEPOSIT = "DEPOSIT"
PAYMENT_BALANCE = "BALANCE"
PAYMENT_FINAL = "FINAL_PAYMENT"
PAYMENT_KINDS: tuple[str, ...] = (
    PAYMENT_ADVANCE_DEPOSIT, PAYMENT_DEPOSIT, PAYMENT_BALANCE, PAYMENT_FINAL,
)

# `overdue` is NOT here, deliberately. There is no scheduler in this stack to flip a row
# into it, and a stored flag that nothing updates is a lie with a timestamp. Overdue is
# `due_date < today`, computed when the row is read.
SCHEDULE_STATUSES: tuple[str, ...] = ("pending", "partial", "paid", "waived")

# OPTION_EXPIRY is the date an unsigned offer lapses — Air France's covering letter wants
# the signed agreement and the deposit back "no later than 06 January 2023". PENALTY_STEP
# is the last day a cancellation band still applies: the day after it, cancelling the same
# seat costs more. It is the reminder that saves an agency money, so it gets a row.
DEADLINE_TYPES: tuple[str, ...] = (
    "ADVANCE_DEPOSIT", "DEPOSIT", "NAME_LIST", "SEAT_RELEASE", "FINAL_PAYMENT",
    "TICKETING", "NO_SHOW_CUTOFF", "DEVIATION_CUTOFF", "DEPARTURE",
    "OPTION_EXPIRY", "PENALTY_STEP",
)
DEADLINE_ANCHORS: tuple[str, ...] = ("DEPARTURE", "CONTRACT_DATE", "ADVANCE_DEPOSIT")
# Same reasoning as SCHEDULE_STATUSES: `missed` is set by an action or a human, never by
# the clock, so that a deadline nobody looked at does not silently rewrite itself.
DEADLINE_STATUSES: tuple[str, ...] = ("open", "met", "missed", "waived")

# ── Terms: what it costs to change or cancel ──────────────────────────────────
#
# One vocabulary for every clause the two reference contracts price. Air France's is a
# pair of date-banded tables (total and partial cancellation); Air India's is a set of
# quotas and flat per-cabin grids (free seat release up to 20%, name replacement up to
# 20%, 4000/6000/9000 per pax by cabin). Both reduce to "in this window, for this share of
# the group, this change costs this much of that base".
TERM_RULE_TYPES: tuple[str, ...] = (
    "CANCELLATION",      # giving seats back — scope says whole group or part of it
    "SEAT_RELEASE",      # a free or discounted reduction allowance (attrition)
    "NAME_CHANGE",       # replacing or correcting a name
    "DEVIATION",         # date / routing change for part of the group
    "REISSUE",           # re-issuing a ticket after a change
    "NO_SHOW",
    "REFUND",            # what comes back on a ticketed-and-unused seat
    "MATERIALIZATION",   # what happens when the group falls below its floor
)
TERM_SCOPES: tuple[str, ...] = ("GROUP", "PARTIAL", "PER_PAX")
# When in the booking's life the rule applies. The two contracts anchor on different
# events: Air France on days-to-departure and ticket issue, Air India on the advance
# deposit and the final payment.
TERM_PHASES: tuple[str, ...] = (
    "ANY", "BEFORE_DEPOSIT", "AFTER_DEPOSIT_BEFORE_FINAL", "AFTER_FINAL_PAYMENT",
    "BEFORE_TICKETING", "AFTER_TICKETING",
)
TERM_CHARGE_TYPES: tuple[str, ...] = (
    "FREE",                    # permitted at no charge
    "PCT_OF_BASIS",            # charge_value % of charge_basis, per affected seat
    "FIXED_PER_PAX",           # charge_value per affected passenger
    "FIXED_TOTAL",             # charge_value once
    "DEPOSIT_FORFEIT",         # the deposit is kept
    "NON_REFUNDABLE",          # nothing comes back
    "TAXES_ONLY_REFUNDABLE",   # only statutory taxes come back
    "FARE_DIFFERENCE",         # repriced at the airline's discretion
    "NOT_PERMITTED",
)

DOCUMENT_KINDS: tuple[str, ...] = ("QUOTATION", "CONTRACT", "AMENDMENT", "NAME_LIST", "OTHER")
EXTRACTION_STATUSES: tuple[str, ...] = ("stored", "processing", "done", "failed", "skipped")


class SeriesContract(Base):
    """The commercial agreement. One row per contract, whatever it covers.

    Identity is three separate fields because the two contracts in hand label themselves
    differently and an agency searches by whichever one the airline quoted at it: Air
    India prints a request id (GRP123003) and a group name (DELATQDEL); Air France prints
    an agreement number (A 5854811-1/1), a group reference (L64E9A) and a group name
    ("Direct Canada DEC").

    The bottom block is a rollup, not user input. `services/series/rollups.py` recomputes
    it wholesale from the level below, so running twice cannot double-count.
    """
    __tablename__ = "series_contracts"
    __table_args__ = (
        CheckConstraint(_check("contract_type", CONTRACT_TYPES), name="ck_series_contracts_type"),
        CheckConstraint(_check("source_type", SOURCE_TYPES), name="ck_series_contracts_source"),
        CheckConstraint(_check("status", CONTRACT_STATUSES), name="ck_series_contracts_status"),
        # The list screen: one workspace's contracts, newest first.
        Index("ix_series_contracts_tenant_created", "tenant_id", "created_at"),
        # Filtering the list by kind, and the Series-only screens.
        Index("ix_series_contracts_tenant_type", "tenant_id", "contract_type"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    # Provenance only. Not part of any scope filter — see the module docstring.
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    contract_type:   Mapped[str | None] = mapped_column(String(10),  nullable=True)
    contract_number: Mapped[str | None] = mapped_column(String(80),  nullable=True)
    group_reference: Mapped[str | None] = mapped_column(String(80),  nullable=True)
    group_name:      Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Which master the counterparty came from. AIRLINE reads the airline master, B2B the
    # supplier master — but the airline pair is filled either way, because a block bought
    # from a consolidator still flies on somebody's metal.
    source_type:   Mapped[str | None] = mapped_column(String(10),  nullable=True)
    agent_name:    Mapped[str | None] = mapped_column(String(200), nullable=True)
    airline_code:  Mapped[str | None] = mapped_column(String(10),  nullable=True)
    airline_name:  Mapped[str | None] = mapped_column(String(200), nullable=True)

    currency:       Mapped[str]        = mapped_column(String(3), nullable=False, server_default="INR", default="INR")
    contracted_pax: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Air France: "agreed upon for minimum 10 passengers". Air India expresses the same
    # idea as a per-cabin floor instead; both land here once the cabin is known.
    minimum_pax:    Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Air India: "groups are permitted for Economy, Premium Economy and Business
    # separately & no mixed cabin itineraries are permitted." One cabin per contract is
    # therefore a rule, not a simplification.
    cabin:          Mapped[str | None] = mapped_column(String(20), nullable=True)

    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    travel_from:   Mapped[date | None] = mapped_column(Date, nullable=True)
    travel_to:     Mapped[date | None] = mapped_column(Date, nullable=True)
    # When an unaccepted offer lapses. Raises an OPTION_EXPIRY deadline.
    option_expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    # B2B: the consolidator's own reference, which is what their accounts team quotes back.
    supplier_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Air India: "minimum group materialisation should be 80% of group size". Per contract,
    # because the figure is the airline's and not every airline says 80. NULL falls back to
    # the market default in the router.
    materialization_floor_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Tour-conductor seats: one free seat per this many paid. NULL = none offered.
    foc_per_paid:      Mapped[int | None] = mapped_column(Integer, nullable=True)
    baggage_allowance: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # MICE / SIT: the event or purpose the movement exists for.
    event_name:        Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft", default="draft")

    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # ── Rollup — written by services/series/rollups.py, never accepted on input ────
    allocations_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    seats_allocated:   Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    seats_ticketed:    Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)

    # Buy side: fare components × seats. Sell side: what the tickets actually went out at.
    # Sign convention follows `sell_reconciliation`, NOT `bsp_reconciliation` — a positive
    # margin means the sale earned money.
    contract_cost:  Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)
    amount_issued:  Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)
    # Sum of series_charges. Stays 0 until the rule engine lands; the column exists now so
    # margin does not change meaning when it does.
    penalty_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)
    margin:         Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)

    match_status:    Mapped[str | None]      = mapped_column(String(20), nullable=True)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    allocations: Mapped[list["SeriesAllocation"]] = relationship(
        "SeriesAllocation", back_populates="contract",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="SeriesAllocation.departure_date",
    )
    fare_components: Mapped[list["SeriesFareComponent"]] = relationship(
        "SeriesFareComponent", back_populates="contract",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="SeriesFareComponent.sort_order",
    )
    payment_schedule: Mapped[list["SeriesPaymentSchedule"]] = relationship(
        "SeriesPaymentSchedule", back_populates="contract",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="SeriesPaymentSchedule.seq",
    )
    deadlines: Mapped[list["SeriesDeadline"]] = relationship(
        "SeriesDeadline", back_populates="contract",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="SeriesDeadline.effective_date",
    )
    terms: Mapped[list["SeriesTerm"]] = relationship(
        "SeriesTerm", back_populates="contract",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="SeriesTerm.sort_order",
    )


class SeriesAllocation(Base):
    """One departure's worth of contracted space.

    This is the table that makes a Series a Series. A SIT, a MICE movement or a one-off
    group has exactly one allocation; a series contract has one per departure date, and
    every count that matters — booked, named, ticketed, released — is per departure, not
    per contract. Air India says so directly: its release, deviation and name-replacement
    quotas are all "per departure".
    """
    __tablename__ = "series_allocations"
    __table_args__ = (
        CheckConstraint(_check("status", ALLOCATION_STATUSES), name="ck_series_allocations_status"),
        Index("ix_series_allocations_tenant_contract", "tenant_id", "contract_id"),
        # The series calendar: every departure in a window, across contracts.
        Index("ix_series_allocations_tenant_departure", "tenant_id", "departure_date"),
        UniqueConstraint("contract_id", "allocation_ref", name="uq_series_allocations_ref"),
    )

    id:          Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id: Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)

    allocation_ref: Mapped[str | None]  = mapped_column(String(60), nullable=True)
    departure_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status:         Mapped[str]         = mapped_column(String(20), nullable=False, server_default="planned", default="planned")

    # As asked for at request time.
    requested_pax: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Air India: "the group size would be firmed up from the day of the advance deposit
    # ... and the same would be treated as sacrosanct viz 100% of the group size." This is
    # the materialization denominator, and it is NOT requested_pax.
    firmed_pax:    Mapped[int | None] = mapped_column(Integer, nullable=True)
    minimum_pax:   Mapped[int | None] = mapped_column(Integer, nullable=True)
    maximum_pax:   Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Rollup — written by services/series/rollups.py ────────────────────────────
    booked_pax:    Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    named_pax:     Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    ticketed_pax:  Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    released_pax:  Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    cancelled_pax: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    # Stored rather than derived on read so the list can sort and filter on it. Null when
    # there is no denominator yet — a contract with no firmed or requested size has no
    # meaningful percentage, and 0 would read as "failing" rather than "unknown".
    materialization_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    amount_issued: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract: Mapped["SeriesContract"] = relationship("SeriesContract", back_populates="allocations")
    sectors: Mapped[list["SeriesSector"]] = relationship(
        "SeriesSector", back_populates="allocation",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="SeriesSector.segment_no",
    )
    bookings: Mapped[list["SeriesBooking"]] = relationship(
        "SeriesBooking", back_populates="allocation",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class SeriesSector(Base):
    """One flight leg of one allocation.

    An itinerary is never stored as a string here. Air India's round trip is two rows
    (DEL-ATQ on AI-495, ATQ-DEL on AI-462) and Air France's is two rows (DEL-CDG on AF225,
    CDG-YYZ on AF356) — a one-way/return flag could describe the first and not the second.

    `direction` exists because Air India treats the two halves differently: "out bound
    travel must be together", while deviation and re-routing are permitted on the inbound.
    """
    __tablename__ = "series_sectors"
    __table_args__ = (
        CheckConstraint(_check("direction", DIRECTIONS), name="ck_series_sectors_direction"),
        Index("ix_series_sectors_tenant_allocation", "tenant_id", "allocation_id"),
        UniqueConstraint("allocation_id", "segment_no", name="uq_series_sectors_segment"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    allocation_id: Mapped[int]        = mapped_column(Integer, ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=False)

    segment_no: Mapped[int]         = mapped_column(SmallInteger, nullable=False, default=1)
    direction:  Mapped[str | None]  = mapped_column(String(10), nullable=True)

    origin:        Mapped[str | None] = mapped_column(String(3), nullable=True)
    destination:   Mapped[str | None] = mapped_column(String(3), nullable=True)
    airline_code:  Mapped[str | None] = mapped_column(String(3), nullable=True)
    flight_number: Mapped[str | None] = mapped_column(String(10), nullable=True)

    departure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrival_at:   Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    cabin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Air France books this group in class U. The RBD is what a fare is actually filed
    # against, so it is kept beside the cabin rather than folded into it.
    rbd:   Mapped[str | None] = mapped_column(String(4), nullable=True)

    allocated_pax: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    allocation: Mapped["SeriesAllocation"] = relationship("SeriesAllocation", back_populates="sectors")


class SeriesBooking(Base):
    """A PNR held against an allocation. The match key, demoted from root to leaf.

    One allocation can carry several PNRs — an airline splits a large group as a matter of
    course, and a reissue mints a new locator. That is exactly what the old single
    `pnr_no` column could not express.

    UNIQUE ON (tenant_id, pnr) IS DELIBERATE. It makes it impossible to file one PNR under
    two contracts. That is not just hygiene: multiple PNRs covering one group is the
    "hidden group" condition airlines write policy about, and a constraint that refuses to
    record it twice is cheaper than a report that finds it later.

    `tour_code` is a second key, not decoration. Group and series fares are routinely filed
    against one, `uploaded_tickets.tour_code` already carries it, and it survives some of
    the cases where a PNR does not.
    """
    __tablename__ = "series_bookings"
    __table_args__ = (
        CheckConstraint(_check("booking_status", BOOKING_STATUSES), name="ck_series_bookings_status"),
        # Every matching run groups on this.
        Index("ix_series_bookings_tenant_pnr", "tenant_id", "pnr"),
        Index("ix_series_bookings_tenant_allocation", "tenant_id", "allocation_id"),
        Index("ix_series_bookings_tenant_tour_code", "tenant_id", "tour_code"),
        UniqueConstraint("tenant_id", "pnr", name="uq_series_bookings_tenant_pnr"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)
    allocation_id: Mapped[int]        = mapped_column(Integer, ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=False)

    # Stored normalised (uppercase, alphanumerics only) because it is a join key and the
    # cheapest way to keep a join honest is to store the value the way it will be compared.
    pnr:         Mapped[str]        = mapped_column(String(50), nullable=False)
    airline_pnr: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tour_code:   Mapped[str | None] = mapped_column(String(100), nullable=True)

    booking_status: Mapped[str]        = mapped_column(String(20), nullable=False, server_default="held", default="held")
    seats:          Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Rollup — written by services/series/matching.py ───────────────────────────
    tickets_issued:  Mapped[int]             = mapped_column(Integer, nullable=False, server_default="0", default=0)
    ticket_numbers:  Mapped[list | None]     = mapped_column(JSONB, nullable=True)
    amount_issued:   Mapped[float]           = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    allocation: Mapped["SeriesAllocation"] = relationship("SeriesAllocation", back_populates="bookings")
    passengers: Mapped[list["SeriesPassenger"]] = relationship(
        "SeriesPassenger", back_populates="booking",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class SeriesPassenger(Base):
    """One name on one booking.

    `occupies_seat` and `counts_for_materialization` are derived from `pax_type` and then
    stored, because both are filtered and summed on every rollup and neither is worth a
    CASE expression in four queries. `services/series/rollups.py` owns the derivation;
    nothing else should set them.
    """
    __tablename__ = "series_passengers"
    __table_args__ = (
        CheckConstraint(_check("pax_type", PAX_TYPES), name="ck_series_passengers_pax_type"),
        CheckConstraint(_check("name_status", NAME_STATUSES), name="ck_series_passengers_name_status"),
        Index("ix_series_passengers_tenant_booking", "tenant_id", "booking_id"),
        Index("ix_series_passengers_tenant_allocation", "tenant_id", "allocation_id"),
        # Links a roster name to the ticket that was issued for it.
        Index("ix_series_passengers_tenant_ticket", "tenant_id", "ticket_number"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)
    allocation_id: Mapped[int]        = mapped_column(Integer, ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=False)
    booking_id:    Mapped[int]        = mapped_column(Integer, ForeignKey("series_bookings.id", ondelete="CASCADE"), nullable=False)

    title:       Mapped[str | None] = mapped_column(String(10), nullable=True)
    first_name:  Mapped[str | None] = mapped_column(String(100), nullable=True)
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name:   Mapped[str | None] = mapped_column(String(100), nullable=True)

    pax_type:                   Mapped[str]  = mapped_column(String(10), nullable=False, server_default=PAX_ADT, default=PAX_ADT)
    occupies_seat:              Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)
    counts_for_materialization: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", default=True)

    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender:        Mapped[str | None]  = mapped_column(String(10), nullable=True)
    nationality:   Mapped[str | None]  = mapped_column(String(50), nullable=True)

    # International SIT and MICE need these; a domestic group never fills them.
    passport_number: Mapped[str | None]  = mapped_column(String(50), nullable=True)
    passport_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)

    name_status:   Mapped[str]        = mapped_column(String(20), nullable=False, server_default="pending", default="pending")
    ticket_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ticket_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    booking: Mapped["SeriesBooking"] = relationship("SeriesBooking", back_populates="passengers")


class SeriesFareComponent(Base):
    """One priced element of the contracted fare, per passenger.

    Air France's contract is four rows: net 64,600 + YR-F 249 + YR-I/YQ 19,050 + taxes
    7,357. Air India's is two that freeze (Base, YQ) and one that does not (statutory
    taxes). Storing them separately is what lets a penalty name the base it applies to.

    `allocation_id` NULL means "the contract default"; set means this departure was
    repriced. A series that reprices mid-season is ordinary, and overwriting the contract
    figure would silently restate every earlier departure.
    """
    __tablename__ = "series_fare_components"
    __table_args__ = (
        CheckConstraint(_check("component_code", COMPONENT_CODES), name="ck_series_fare_components_code"),
        Index("ix_series_fare_components_tenant_contract", "tenant_id", "contract_id"),
        UniqueConstraint("contract_id", "allocation_id", "component_code", name="uq_series_fare_components_code"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)
    allocation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=True)

    component_code: Mapped[str]        = mapped_column(String(20), nullable=False)
    # What the airline called it, kept verbatim so the screen can echo the contract's own
    # words — "Sustainable Fuel Contribution (YR-F)" rather than "YR_F".
    label:          Mapped[str | None] = mapped_column(String(80), nullable=True)
    amount_per_pax: Mapped[float]      = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)

    # Air France: YR-F and YR-I/YQ are "guaranteed until date of ticketing or until
    # contract is reissued"; taxes are "subject to change at date of ticketing". Air India
    # says the same thing the other way round: "only AI retention (Base + YQ) will freeze."
    is_guaranteed_until_ticketing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    # Air India: "for No-Show passengers – only statutory taxes are refundable", and the
    # same for partially utilised tickets.
    is_refundable_on_noshow:       Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)

    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0", default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract: Mapped["SeriesContract"] = relationship("SeriesContract", back_populates="fare_components")


class SeriesPaymentSchedule(Base):
    """One instalment the contract says is due.

    WHY `pct` CARRIES A `pct_basis`. Air France's two deposits are 38,760 and 193,800.
    Those are 5% and 25% of the net-fare total (775,200) — not of the 1,095,072 grand
    total. A percentage with no base is a number that happens to be right today: renegotiate
    the fare and the instalments silently stop matching the contract.

    `amount` is stored alongside the percentage rather than always recomputed, so the
    schedule still reads the way the airline wrote it after someone edits the fare. Which
    one wins is the API's decision, not the column's.
    """
    __tablename__ = "series_payment_schedule"
    __table_args__ = (
        CheckConstraint(_check("kind", PAYMENT_KINDS), name="ck_series_payment_schedule_kind"),
        CheckConstraint(_check("status", SCHEDULE_STATUSES), name="ck_series_payment_schedule_status"),
        Index("ix_series_payment_schedule_tenant_contract", "tenant_id", "contract_id"),
        # The money-due view: everything outstanding across the workspace, by date.
        Index("ix_series_payment_schedule_tenant_due", "tenant_id", "due_date"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)
    allocation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=True)

    kind:      Mapped[str | None]  = mapped_column(String(20), nullable=True)
    seq:       Mapped[int]         = mapped_column(SmallInteger, nullable=False, server_default="0", default=0)
    due_date:  Mapped[date | None] = mapped_column(Date, nullable=True)

    amount:    Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    pct:       Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    pct_basis: Mapped[str | None]   = mapped_column(String(20), nullable=True)

    # "Payable ... and used as a partial payment of the total amount for this Group less
    # penalties where applicable" (Air France) vs "advance deposit will be forfeited"
    # (Air India). NULL = the contract does not say.
    is_refundable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # "Final payment 8 days before departure" when no date was printed. Resolved against the
    # first departure into `due_date` on write, and kept so an edited travel date can move it.
    due_offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status:      Mapped[str]         = mapped_column(String(20), nullable=False, server_default="pending", default="pending")
    # Derived cache: the sum of series_payments against this row. Recomputed wholesale.
    paid_amount: Mapped[float]       = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)
    paid_on:     Mapped[date | None] = mapped_column(Date, nullable=True)

    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract: Mapped["SeriesContract"] = relationship("SeriesContract", back_populates="payment_schedule")
    payments: Mapped[list["SeriesPayment"]] = relationship(
        "SeriesPayment", back_populates="schedule",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="SeriesPayment.paid_on",
    )


class SeriesPayment(Base):
    """Money actually sent, against one scheduled instalment.

    Separate from the schedule because an instalment is frequently paid in more than one
    transfer, and because "what was agreed" and "what happened" must stay independently
    auditable. The schedule's `paid_amount` is a cache of the sum of these.
    """
    __tablename__ = "series_payments"
    __table_args__ = (
        Index("ix_series_payments_tenant_contract", "tenant_id", "contract_id"),
        Index("ix_series_payments_schedule", "schedule_id"),
    )

    id:          Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id: Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)
    schedule_id: Mapped[int]        = mapped_column(Integer, ForeignKey("series_payment_schedule.id", ondelete="CASCADE"), nullable=False)

    amount:    Mapped[float]       = mapped_column(Numeric(14, 2), nullable=False, server_default="0", default=0)
    paid_on:   Mapped[date | None] = mapped_column(Date, nullable=True)
    method:    Mapped[str | None]  = mapped_column(String(40), nullable=True)
    reference: Mapped[str | None]  = mapped_column(String(120), nullable=True)
    notes:     Mapped[str | None]  = mapped_column(String(300), nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at:    Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)

    schedule: Mapped["SeriesPaymentSchedule"] = relationship("SeriesPaymentSchedule", back_populates="payments")


class SeriesDeadline(Base):
    """A date the contract makes the agency responsible for.

    WHY TWO DATES. Air France's agreement states both the rule and the answer: the name
    list is due "no later than 30 days before departure date, which is 27 November 2023",
    ticketing "no later than 8 days before departure date, which is 19 December 2023". In
    this contract they agree. When they do not — and contracts do contain arithmetic
    errors — the agency needs to see which is which, because the airline will enforce the
    date it printed. `computed_date` is ours, `stated_date` is theirs, `effective_date` is
    what we act on, and `has_divergence` says the two disagreed.

    WHY `offset_hours` EXISTS SEPARATELY. Air India's no-show rule is "fails to cancel the
    booking at least D-24 hours before departure". Rounding that to one day is wrong by up
    to twenty-three hours on a rule that decides whether the taxes come back.

    `status` is only ever set by an action or a person. There is no scheduler in this
    stack, so nothing would flip a row to `missed` on the day — and a stored status that
    nothing maintains is worse than no status. Overdue is derived when the row is read.
    """
    __tablename__ = "series_deadlines"
    __table_args__ = (
        CheckConstraint(_check("deadline_type", DEADLINE_TYPES), name="ck_series_deadlines_type"),
        CheckConstraint(_check("anchor", DEADLINE_ANCHORS), name="ck_series_deadlines_anchor"),
        CheckConstraint(_check("status", DEADLINE_STATUSES), name="ck_series_deadlines_status"),
        # The action centre: what is due across the workspace, soonest first.
        Index("ix_series_deadlines_tenant_effective", "tenant_id", "effective_date"),
        Index("ix_series_deadlines_tenant_contract", "tenant_id", "contract_id"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)
    allocation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=True)

    deadline_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    anchor:        Mapped[str | None] = mapped_column(String(20), nullable=True)
    offset_days:   Mapped[int | None] = mapped_column(Integer, nullable=True)
    offset_hours:  Mapped[int | None] = mapped_column(Integer, nullable=True)

    computed_date:  Mapped[date | None] = mapped_column(Date, nullable=True)
    stated_date:    Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    has_divergence: Mapped[bool]        = mapped_column(Boolean, nullable=False, server_default="false", default=False)

    status:  Mapped[str]         = mapped_column(String(20), nullable=False, server_default="open", default="open")
    met_on:  Mapped[date | None] = mapped_column(Date, nullable=True)

    action_required: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract: Mapped["SeriesContract"] = relationship("SeriesContract", back_populates="deadlines")


class SeriesTerm(Base):
    """One priced clause: what a cancellation, release, name change or deviation costs.

    The window is expressed in days before departure and read as an inclusive band —
    `days_before_max` is the far edge, `days_before_min` the near edge, NULL meaning open.
    Air France's "From 120 to 101 days prior to departure: penalty of 15% of the fare" is
    (max=120, min=101, PCT_OF_BASIS, 15, NET_FARE); "up to 121 days prior" is (max=NULL,
    min=121); "from 30 days prior" is (max=30, min=0).

    `share_min_pct` / `share_max_pct` carry the quota rules. Air France: "20% of seats ...
    can be cancelled without penalty. Over and above: penalty of 5%" is two rows, FREE for
    0–20% and 5% beyond 20%. Air India: "additional seat release up to maximum 50% ... with
    penalty of 50% of AI retention" is share 20–50.

    `source_text` and `source_page` keep the clause as the airline wrote it. A person
    reviewing an extracted rule has to be able to see what it was read from, and the
    airline will argue from its own words, not from ours.
    """
    __tablename__ = "series_terms"
    __table_args__ = (
        CheckConstraint(_check("rule_type", TERM_RULE_TYPES), name="ck_series_terms_rule_type"),
        CheckConstraint(_check("scope", TERM_SCOPES), name="ck_series_terms_scope"),
        CheckConstraint(_check("phase", TERM_PHASES), name="ck_series_terms_phase"),
        CheckConstraint(_check("charge_type", TERM_CHARGE_TYPES), name="ck_series_terms_charge_type"),
        Index("ix_series_terms_tenant_contract", "tenant_id", "contract_id"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)
    # NULL = applies to every departure on the contract.
    allocation_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=True)

    rule_type: Mapped[str]        = mapped_column(String(20), nullable=False)
    scope:     Mapped[str | None] = mapped_column(String(10), nullable=True)
    phase:     Mapped[str]        = mapped_column(String(30), nullable=False, server_default="ANY", default="ANY")

    days_before_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_before_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    share_min_pct:   Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    share_max_pct:   Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    charge_type:  Mapped[str]          = mapped_column(String(30), nullable=False)
    charge_value: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # One of services/series/bases.BASES when charge_type is PCT_OF_BASIS.
    charge_basis: Mapped[str | None]   = mapped_column(String(30), nullable=True)
    # Air India prices one grid per cabin: 4000 / 6000 / 9000. NULL = any cabin.
    cabin:        Mapped[str | None]   = mapped_column(String(20), nullable=True)
    # "Applicable GST would be additionally charged over and above penalty."
    plus_gst:     Mapped[bool]         = mapped_column(Boolean, nullable=False, server_default="false", default=False)

    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_page: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    sort_order:  Mapped[int]        = mapped_column(SmallInteger, nullable=False, server_default="0", default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract: Mapped["SeriesContract"] = relationship("SeriesContract", back_populates="terms")


class SeriesDocument(Base):
    """The paper the contract came from: quotation, signed agreement, amendment, name list.

    Uploaded BEFORE the contract exists — the AI reads it to fill the form — so
    `contract_id` is NULL until the reviewed form is saved, and set then. A draft someone
    abandoned keeps its row, which is what lets the notification "your contract has been
    read, review it" reopen the review instead of paying for a second read.

    `extraction_json` is the normalised draft the review screen was filled from. Kept after
    the save on purpose: diffing it against what the person actually saved is the only
    honest measure of how often the reader gets a field wrong.
    """
    __tablename__ = "series_documents"
    __table_args__ = (
        CheckConstraint(_check("doc_kind", DOCUMENT_KINDS), name="ck_series_documents_kind"),
        CheckConstraint(_check("extraction_status", EXTRACTION_STATUSES), name="ck_series_documents_status"),
        Index("ix_series_documents_tenant_contract", "tenant_id", "contract_id"),
        Index("ix_series_documents_tenant_created", "tenant_id", "created_at"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id:   Mapped[int | None] = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    doc_kind:     Mapped[str]        = mapped_column(String(20), nullable=False, server_default="CONTRACT", default="CONTRACT")
    file_name:    Mapped[str]        = mapped_column(String(255), nullable=False)
    # A GCS blob path, or `local://…` when the bucket was unreachable (services/file_store).
    file_url:     Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size:    Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Same file uploaded twice is almost always a mistake worth one line of warning.
    sha256:       Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    page_count:   Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Pages with no text layer, read as images. Both reference contracts are phone photos.
    scanned_pages: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    extraction_status: Mapped[str]         = mapped_column(String(20), nullable=False, server_default="stored", default="stored")
    extraction_error:  Mapped[str | None]  = mapped_column(String(1000), nullable=True)
    extraction_json:   Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction_model:  Mapped[str | None]  = mapped_column(String(60), nullable=True)
    extraction_ms:     Mapped[int | None]  = mapped_column(Integer, nullable=True)
    extracted_at:      Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SeriesEvent(Base):
    """Append-only record of what happened to a contract.

    Here from the first version rather than added later, because recording a payment and
    waiving a deadline are money-affecting acts from day one and an audit trail cannot be
    back-filled — the history it would need was never written down.

    No FK on `actor_user_id` deliberately: an event outlives the account that caused it,
    and deleting a user must not delete the record of what they did.
    """
    __tablename__ = "series_events"
    __table_args__ = (
        Index("ix_series_events_tenant_contract", "tenant_id", "contract_id", "occurred_at"),
    )

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    contract_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=False)
    allocation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    booking_id:    Mapped[int | None] = mapped_column(Integer, nullable=True)

    event_type: Mapped[str]         = mapped_column(String(40), nullable=False)
    payload:    Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at:   Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow)
