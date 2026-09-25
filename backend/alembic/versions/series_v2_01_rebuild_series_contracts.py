"""Rebuild Series/SIT/MICE as a contract graph, and add Group

WHY A REBUILD RATHER THAN A WIDENING. The first version of this feature was one flat table
whose organising idea was a PNR: `series_contracts.pnr_no` held the record locator and the
matching service counted tickets against it. Almost every column that follows from that
idea is wrong once a real airline contract is in front of you — a group covers several
departures, several flight legs and several PNRs, and the commercial terms belong to the
agreement rather than to any one locator. Widening the table would have meant keeping
`pnr_no`, `date_of_travel`, `fare_per_pax` and `trip_type` alive as columns that are only
correct for the simplest possible contract, and writing every reader to prefer the child
tables when they exist. The table carries no production data, so the honest move is to
drop it and model the thing properly.

WHAT THE SHAPE IS NOW

    series_contracts            the commercial agreement
      └── series_allocations    one per departure — a SIT has one, a series has many
            ├── series_sectors  flight legs
            └── series_bookings PNRs, many per departure; the ticket match key
                  └── series_passengers
      ├── series_fare_components    typed fare, so a penalty can name its base
      ├── series_payment_schedule   instalments, with the base a percentage applies to
      │     └── series_payments     money actually sent
      ├── series_deadlines          dates, with the airline's own date kept beside ours
      └── series_events             audit

WHY FARE IS ROWS AND NOT COLUMNS. Two real contracts disagree about what a percentage is a
percentage of. Air India charges penalties on "AI retention", which it defines as Base +
YQ. Air France charges on "the fare" — and its own deposits prove that means the net fare,
because 38,760 and 193,800 are exactly 5% and 25% of 775,200, the net-fare total, and not
of the 1,095,072 grand total. A `fare_per_pax` column can express neither.

WHY THE FUNCTIONAL INDEXES ON uploaded_tickets CHANGE. `series_contract_01` added
lower(gds_pnr) and lower(air_pnr) indexes for the old matcher, which compared
case-insensitively but normalised punctuation only in Python — so it had to read every
ticket row and filter in memory, capped at 200,000. The new matcher knows its exact PNR set
before it queries, and normalises in SQL with the same rule Python uses
(`services/series/matching.py::PNR_NORM_SQL`), so these indexes replace the lower() pair
and the table is no longer scanned. The old two are dropped because nothing else used them.

DOWNGRADE restores the original flat table and its three indexes, plus the lower() pair,
and drops everything this migration added. It is lossless only in the schema sense — rows
written into the new graph have nowhere to go in a single-PNR table and are not migrated
back.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "series_v2_01"
down_revision: Union[str, None] = "income_board_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept as literals rather than imported from the model: a migration must keep describing
# the schema it wrote even after the model moves on.
CONTRACT_TYPES = ("SERIES", "SIT", "MICE", "GROUP")
SOURCE_TYPES = ("AIRLINE", "B2B")
CONTRACT_STATUSES = ("draft", "pending_review", "active", "closed", "cancelled")
ALLOCATION_STATUSES = (
    "planned", "held", "deposit_paid", "names_due", "ticketed", "departed", "cancelled",
)
DIRECTIONS = ("OUTBOUND", "INBOUND")
BOOKING_STATUSES = ("held", "ticketed", "partially_ticketed", "cancelled")
PAX_TYPES = ("ADT", "CHD", "INF_SEAT", "INF_LAP")
NAME_STATUSES = ("pending", "named", "confirmed", "replaced", "cancelled")
COMPONENT_CODES = ("BASE", "YQ", "YR_I", "YR_F", "TAX_STATUTORY", "OT", "FEE")
PAYMENT_KINDS = ("ADVANCE_DEPOSIT", "DEPOSIT", "BALANCE", "FINAL_PAYMENT")
SCHEDULE_STATUSES = ("pending", "partial", "paid", "waived")
DEADLINE_TYPES = (
    "ADVANCE_DEPOSIT", "DEPOSIT", "NAME_LIST", "SEAT_RELEASE", "FINAL_PAYMENT",
    "TICKETING", "NO_SHOW_CUTOFF", "DEVIATION_CUTOFF", "DEPARTURE",
)
DEADLINE_ANCHORS = ("DEPARTURE", "CONTRACT_DATE", "ADVANCE_DEPOSIT")
DEADLINE_STATUSES = ("open", "met", "missed", "waived")

# Must stay character-for-character identical to PNR_NORM_SQL in
# services/series/matching.py, or the planner will not use these indexes.
_GDS_NORM = "regexp_replace(upper(gds_pnr), '[^0-9A-Z]', '', 'g')"
_AIR_NORM = "regexp_replace(upper(air_pnr), '[^0-9A-Z]', '', 'g')"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def _tenant_fk():
    return sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)


def _contract_fk(nullable: bool = False):
    return sa.Column(
        "contract_id", sa.Integer(),
        sa.ForeignKey("series_contracts.id", ondelete="CASCADE"), nullable=nullable,
    )


def _allocation_fk(nullable: bool = False):
    return sa.Column(
        "allocation_id", sa.Integer(),
        sa.ForeignKey("series_allocations.id", ondelete="CASCADE"), nullable=nullable,
    )


def _timestamps():
    return (
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def upgrade() -> None:
    # ── Out with the old ──────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS ix_uploaded_tickets_gds_pnr_lower")
    op.execute("DROP INDEX IF EXISTS ix_uploaded_tickets_air_pnr_lower")
    op.drop_index("ix_series_contracts_pnr_no", table_name="series_contracts")
    op.drop_index("ix_series_contracts_created_by_id", table_name="series_contracts")
    op.drop_index("ix_series_contracts_tenant_id", table_name="series_contracts")
    op.drop_table("series_contracts")

    # ── series_contracts ──────────────────────────────────────────────────────
    op.create_table(
        "series_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("contract_type", sa.String(length=10), nullable=True),
        sa.Column("contract_number", sa.String(length=80), nullable=True),
        sa.Column("group_reference", sa.String(length=80), nullable=True),
        sa.Column("group_name", sa.String(length=200), nullable=True),
        sa.Column("source_type", sa.String(length=10), nullable=True),
        sa.Column("agent_name", sa.String(length=200), nullable=True),
        sa.Column("airline_code", sa.String(length=10), nullable=True),
        sa.Column("airline_name", sa.String(length=200), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("contracted_pax", sa.Integer(), nullable=True),
        sa.Column("minimum_pax", sa.Integer(), nullable=True),
        sa.Column("cabin", sa.String(length=20), nullable=True),
        sa.Column("contract_date", sa.Date(), nullable=True),
        sa.Column("travel_from", sa.Date(), nullable=True),
        sa.Column("travel_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("allocations_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("seats_allocated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("seats_ticketed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("contract_cost", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("amount_issued", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("penalty_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("margin", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("match_status", sa.String(length=20), nullable=True),
        sa.Column("last_matched_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("contract_type", CONTRACT_TYPES), name="ck_series_contracts_type"),
        sa.CheckConstraint(_in("source_type", SOURCE_TYPES), name="ck_series_contracts_source"),
        sa.CheckConstraint(_in("status", CONTRACT_STATUSES), name="ck_series_contracts_status"),
    )
    op.create_index("ix_series_contracts_tenant_id", "series_contracts", ["tenant_id"])
    op.create_index("ix_series_contracts_created_by_id", "series_contracts", ["created_by_id"])
    op.create_index("ix_series_contracts_tenant_created", "series_contracts", ["tenant_id", "created_at"])
    op.create_index("ix_series_contracts_tenant_type", "series_contracts", ["tenant_id", "contract_type"])

    # ── series_allocations ────────────────────────────────────────────────────
    op.create_table(
        "series_allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _contract_fk(),
        sa.Column("allocation_ref", sa.String(length=60), nullable=True),
        sa.Column("departure_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="planned", nullable=False),
        sa.Column("requested_pax", sa.Integer(), nullable=True),
        sa.Column("firmed_pax", sa.Integer(), nullable=True),
        sa.Column("minimum_pax", sa.Integer(), nullable=True),
        sa.Column("maximum_pax", sa.Integer(), nullable=True),
        sa.Column("booked_pax", sa.Integer(), server_default="0", nullable=False),
        sa.Column("named_pax", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ticketed_pax", sa.Integer(), server_default="0", nullable=False),
        sa.Column("released_pax", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancelled_pax", sa.Integer(), server_default="0", nullable=False),
        sa.Column("materialization_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("amount_issued", sa.Numeric(14, 2), server_default="0", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("status", ALLOCATION_STATUSES), name="ck_series_allocations_status"),
        sa.UniqueConstraint("contract_id", "allocation_ref", name="uq_series_allocations_ref"),
    )
    op.create_index("ix_series_allocations_tenant_id", "series_allocations", ["tenant_id"])
    op.create_index("ix_series_allocations_tenant_contract", "series_allocations", ["tenant_id", "contract_id"])
    op.create_index("ix_series_allocations_tenant_departure", "series_allocations", ["tenant_id", "departure_date"])

    # ── series_sectors ────────────────────────────────────────────────────────
    op.create_table(
        "series_sectors",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _allocation_fk(),
        sa.Column("segment_no", sa.SmallInteger(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=True),
        sa.Column("origin", sa.String(length=3), nullable=True),
        sa.Column("destination", sa.String(length=3), nullable=True),
        sa.Column("airline_code", sa.String(length=3), nullable=True),
        sa.Column("flight_number", sa.String(length=10), nullable=True),
        sa.Column("departure_at", sa.DateTime(), nullable=True),
        sa.Column("arrival_at", sa.DateTime(), nullable=True),
        sa.Column("cabin", sa.String(length=20), nullable=True),
        sa.Column("rbd", sa.String(length=4), nullable=True),
        sa.Column("allocated_pax", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("direction", DIRECTIONS), name="ck_series_sectors_direction"),
        sa.UniqueConstraint("allocation_id", "segment_no", name="uq_series_sectors_segment"),
    )
    op.create_index("ix_series_sectors_tenant_id", "series_sectors", ["tenant_id"])
    op.create_index("ix_series_sectors_tenant_allocation", "series_sectors", ["tenant_id", "allocation_id"])

    # ── series_bookings ───────────────────────────────────────────────────────
    op.create_table(
        "series_bookings",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _contract_fk(),
        _allocation_fk(),
        sa.Column("pnr", sa.String(length=50), nullable=False),
        sa.Column("airline_pnr", sa.String(length=50), nullable=True),
        sa.Column("tour_code", sa.String(length=100), nullable=True),
        sa.Column("booking_status", sa.String(length=20), server_default="held", nullable=False),
        sa.Column("seats", sa.Integer(), nullable=True),
        sa.Column("tickets_issued", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ticket_numbers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("amount_issued", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("last_matched_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("booking_status", BOOKING_STATUSES), name="ck_series_bookings_status"),
        # One PNR cannot be filed under two contracts. Multiple PNRs covering one group is
        # the condition airlines write policy about; refusing the duplicate at write time
        # is cheaper than a report that finds it later.
        sa.UniqueConstraint("tenant_id", "pnr", name="uq_series_bookings_tenant_pnr"),
    )
    op.create_index("ix_series_bookings_tenant_id", "series_bookings", ["tenant_id"])
    op.create_index("ix_series_bookings_tenant_pnr", "series_bookings", ["tenant_id", "pnr"])
    op.create_index("ix_series_bookings_tenant_allocation", "series_bookings", ["tenant_id", "allocation_id"])
    op.create_index("ix_series_bookings_tenant_tour_code", "series_bookings", ["tenant_id", "tour_code"])

    # ── series_passengers ─────────────────────────────────────────────────────
    op.create_table(
        "series_passengers",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _contract_fk(),
        _allocation_fk(),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("series_bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=10), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("middle_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("pax_type", sa.String(length=10), server_default="ADT", nullable=False),
        sa.Column("occupies_seat", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("counts_for_materialization", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=10), nullable=True),
        sa.Column("nationality", sa.String(length=50), nullable=True),
        sa.Column("passport_number", sa.String(length=50), nullable=True),
        sa.Column("passport_expiry", sa.Date(), nullable=True),
        sa.Column("name_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("ticket_number", sa.String(length=50), nullable=True),
        sa.Column("ticket_status", sa.String(length=20), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("pax_type", PAX_TYPES), name="ck_series_passengers_pax_type"),
        sa.CheckConstraint(_in("name_status", NAME_STATUSES), name="ck_series_passengers_name_status"),
    )
    op.create_index("ix_series_passengers_tenant_id", "series_passengers", ["tenant_id"])
    op.create_index("ix_series_passengers_tenant_booking", "series_passengers", ["tenant_id", "booking_id"])
    op.create_index("ix_series_passengers_tenant_allocation", "series_passengers", ["tenant_id", "allocation_id"])
    op.create_index("ix_series_passengers_tenant_ticket", "series_passengers", ["tenant_id", "ticket_number"])

    # ── series_fare_components ────────────────────────────────────────────────
    op.create_table(
        "series_fare_components",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _contract_fk(),
        _allocation_fk(nullable=True),
        sa.Column("component_code", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("amount_per_pax", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("is_guaranteed_until_ticketing", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_refundable_on_noshow", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("component_code", COMPONENT_CODES), name="ck_series_fare_components_code"),
        sa.UniqueConstraint("contract_id", "allocation_id", "component_code", name="uq_series_fare_components_code"),
    )
    op.create_index("ix_series_fare_components_tenant_id", "series_fare_components", ["tenant_id"])
    op.create_index("ix_series_fare_components_tenant_contract", "series_fare_components", ["tenant_id", "contract_id"])

    # ── series_payment_schedule ───────────────────────────────────────────────
    op.create_table(
        "series_payment_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _contract_fk(),
        _allocation_fk(nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=True),
        sa.Column("seq", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("pct", sa.Numeric(6, 3), nullable=True),
        # The base a percentage applies to. Without it, 5% is a number that happens to be
        # right today — see the module docstring for why Air France proves this.
        sa.Column("pct_basis", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("paid_amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=300), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("kind", PAYMENT_KINDS), name="ck_series_payment_schedule_kind"),
        sa.CheckConstraint(_in("status", SCHEDULE_STATUSES), name="ck_series_payment_schedule_status"),
    )
    op.create_index("ix_series_payment_schedule_tenant_id", "series_payment_schedule", ["tenant_id"])
    op.create_index("ix_series_payment_schedule_tenant_contract", "series_payment_schedule", ["tenant_id", "contract_id"])
    op.create_index("ix_series_payment_schedule_tenant_due", "series_payment_schedule", ["tenant_id", "due_date"])

    # ── series_payments ───────────────────────────────────────────────────────
    op.create_table(
        "series_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _contract_fk(),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("series_payment_schedule.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("method", sa.String(length=40), nullable=True),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_series_payments_tenant_id", "series_payments", ["tenant_id"])
    op.create_index("ix_series_payments_tenant_contract", "series_payments", ["tenant_id", "contract_id"])
    op.create_index("ix_series_payments_schedule", "series_payments", ["schedule_id"])

    # ── series_deadlines ──────────────────────────────────────────────────────
    op.create_table(
        "series_deadlines",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _contract_fk(),
        _allocation_fk(nullable=True),
        sa.Column("deadline_type", sa.String(length=30), nullable=True),
        sa.Column("anchor", sa.String(length=20), nullable=True),
        sa.Column("offset_days", sa.Integer(), nullable=True),
        # Air India's no-show cut-off is D-24 HOURS. Rounding that to a day is wrong by up
        # to twenty-three hours on a rule that decides whether the taxes come back.
        sa.Column("offset_hours", sa.Integer(), nullable=True),
        sa.Column("computed_date", sa.Date(), nullable=True),
        sa.Column("stated_date", sa.Date(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("has_divergence", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("met_on", sa.Date(), nullable=True),
        sa.Column("action_required", sa.String(length=200), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_in("deadline_type", DEADLINE_TYPES), name="ck_series_deadlines_type"),
        sa.CheckConstraint(_in("anchor", DEADLINE_ANCHORS), name="ck_series_deadlines_anchor"),
        sa.CheckConstraint(_in("status", DEADLINE_STATUSES), name="ck_series_deadlines_status"),
    )
    op.create_index("ix_series_deadlines_tenant_id", "series_deadlines", ["tenant_id"])
    op.create_index("ix_series_deadlines_tenant_effective", "series_deadlines", ["tenant_id", "effective_date"])
    op.create_index("ix_series_deadlines_tenant_contract", "series_deadlines", ["tenant_id", "contract_id"])

    # ── series_events ─────────────────────────────────────────────────────────
    op.create_table(
        "series_events",
        sa.Column("id", sa.Integer(), nullable=False),
        _tenant_fk(),
        _contract_fk(),
        # No FK on these two: an event names things that may since have been deleted, and
        # the record of what happened must outlive them.
        sa.Column("allocation_id", sa.Integer(), nullable=True),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_series_events_tenant_id", "series_events", ["tenant_id"])
    op.create_index("ix_series_events_tenant_contract", "series_events", ["tenant_id", "contract_id", "occurred_at"])

    # ── The join the matcher rides ────────────────────────────────────────────
    # Same normalisation as services/series/matching.py::norm_pnr, so the planner can use
    # these for the IN-list the matcher builds from series_bookings.pnr.
    op.execute(f"CREATE INDEX ix_uploaded_tickets_gds_pnr_norm ON uploaded_tickets (({_GDS_NORM}))")
    op.execute(f"CREATE INDEX ix_uploaded_tickets_air_pnr_norm ON uploaded_tickets (({_AIR_NORM}))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_uploaded_tickets_air_pnr_norm")
    op.execute("DROP INDEX IF EXISTS ix_uploaded_tickets_gds_pnr_norm")

    for table in (
        "series_events", "series_deadlines", "series_payments", "series_payment_schedule",
        "series_fare_components", "series_passengers", "series_bookings",
        "series_sectors", "series_allocations", "series_contracts",
    ):
        op.drop_table(table)

    # Restore the original flat table exactly as series_contract_01 created it.
    op.create_table(
        "series_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("contract_type", sa.String(length=10), nullable=True),
        sa.Column("agent_type", sa.String(length=10), nullable=True),
        sa.Column("agent_name", sa.String(length=200), nullable=True),
        sa.Column("airline_name", sa.String(length=200), nullable=True),
        sa.Column("airline_code", sa.String(length=10), nullable=True),
        sa.Column("pnr_no", sa.String(length=50), nullable=True),
        sa.Column("pax_count", sa.Integer(), nullable=True),
        sa.Column("trip_type", sa.String(length=10), nullable=True),
        sa.Column("date_of_travel", sa.Date(), nullable=True),
        sa.Column("fare_per_pax", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_fare", sa.Numeric(14, 2), nullable=True),
        sa.Column("payment_terms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tickets_issued", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ticket_numbers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("amount_issued", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("match_status", sa.String(length=20), nullable=True),
        sa.Column("last_matched_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_series_contracts_tenant_id", "series_contracts", ["tenant_id"])
    op.create_index("ix_series_contracts_created_by_id", "series_contracts", ["created_by_id"])
    op.create_index("ix_series_contracts_pnr_no", "series_contracts", ["pnr_no"])
    op.execute("CREATE INDEX ix_uploaded_tickets_gds_pnr_lower ON uploaded_tickets (lower(gds_pnr))")
    op.execute("CREATE INDEX ix_uploaded_tickets_air_pnr_lower ON uploaded_tickets (lower(air_pnr))")
