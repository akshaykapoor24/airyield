"""Every priced line, from every source, in the shape the income board reads

TWO STRUCTURAL FACTS FORCE A PROJECTION. Commission is already calculated correctly,
and this migration changes none of that arithmetic. What it changes is where the
answers can be READ from together:

  1. BSP writes onto its own settlement row (`bsp_statement_rows.calculated_incentive`
     and friends) while tp-gds, tp-lcc and lcc-detailed write to
     `commission_calculations`. BSP is not a registered commission adapter at all
     (services/commission/__init__.py), so no existing table holds all four.
  2. `commission_calculations` carries NO GROSS for any source. Its money columns are
     fare_amount / yq / yr / ancillary_amount. Any read wanting revenue must join back
     to `lcc_detailed.total`, or to `third_party_*.data->>'total_fare'` behind a regex
     guard, because services/flat_statement.py deliberately keeps the original text
     when a number fails to parse.

Re-deriving that union, and three sets of dimensions with it, on every page load is
the cost this table removes. It is paid once per commission run instead.

DERIVED AND REBUILDABLE, WHICH IS WHY THE DIMENSIONS CARRY NO FOREIGN KEYS.
`supplier_id`, `airline_id` and `vendor_agency_id` are plain integers here. A report
that can be reconstructed in full from its sources must never be the reason a supplier
or an airline cannot be deleted; `commission_calculations.source_row_id` already sets
that precedent ("no FK — a different table per source"). `tenant_id` and
`created_by_id` keep their keys, because those are the scope and not a dimension, and
`matched_deal_id` / `run_id` keep theirs as SET NULL, which blocks nothing.

`incentive` IS NULLABLE AND THAT IS LOAD-BEARING. NULL means a deal matched but pays
on something the document does not print, so nothing is claimed; zero means the deal
applied and earned nothing. models/commission_calculation.py states why collapsing
them is unacceptable: it "would turn 'we could not confirm what you are owed' into
'you are owed nothing'". Every roll-up over this table must therefore read
SUM(incentive) FILTER (WHERE status IN ('calculated','reversed')) and show the
needs_data count beside the figure. `iata_commission` is a separate entitlement and is
never summed into it, matching services/commission/runner.py.

`txn_class` AND `segment` ARE NORMALISED AT WRITE TIME, THROUGH EXISTING CONSTANTS.
`txn_class` comes from the _ISSUE_TXN / _REFUND_TXN / _SKIP_TXN sets in
services/bsp_commission.py — the same import services/plb_accrual.py already makes —
because an ADM or ACM has no fare, and letting memo value into a revenue denominator
corrupts every ratio on the board invisibly (memos are legitimately status='excluded',
so they show up in neither the matched nor the needs-data count). `segment` comes from
deal_matching.segment_letter, which returns 'I' | 'D' | None and does NOT accept a
bare 'I'/'D' as INPUT — so BSP's STAT column goes through bsp_commission.
stat_to_segment first, letter to word to letter. `segment_raw` keeps whatever the
document actually printed.

`supplier_id` IS NULLABLE HERE ALTHOUGH IT IS NOT NULL ON `statement_batch_suppliers`.
The column there is NOT NULL, but the ROW may not exist: batches uploaded before that
link existed have none, and the adapter says so ("or None for a batch that predates
it"). The projection LEFT JOINs, so those rows land in a visible "Unattributed
consolidator" bucket instead of being dropped by an inner join.

ALL PHASE-2 COLUMNS SHIP HERE, NULLABLE, AND NOTHING IS BACKFILLED. The customer-side
and markup columns are created now because all four composite indexes lead with
`direction`, and adding that column later would mean rebuilding every one of them on a
table that may by then hold millions of rows. The table is created EMPTY: every
existing priced batch reads as "never projected" on day one, which is correct and
visible, and POST /dashboard/income/rebuild is one click away. No stored row anywhere
changes meaning because of this migration, and nothing reads the table until the board
that needs it ships.

`downgrade()` IS GENUINELY SAFE. Dropping this table loses no information that cannot
be reconstructed by /rebuild from the sources it was projected from.

Revision ID: income_board_01
Revises: default_deal_workflow_01
Create Date: 2026-09-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "income_board_01"
down_revision: Union[str, None] = "default_deal_workflow_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "income_board_rows"

# Per-line money. Numeric(14, 2) matches every other per-line money column in this
# schema; the incentive pair below is Numeric(18, 2) to match
# commission_calculations, which it is projected from.
_LINE_MONEY = (
    "gross_amount", "fare_amount", "yq", "yr", "taxes_total", "ancillary_amount",
    "markup_amount", "additional_markup_amount",
    "declared_commission", "declared_incentive", "declared_tds", "declared_net",
)

# (name, columns). The first four serve the default per-user scope. The next two exist
# because a composite leading with created_by_id cannot serve a whole-agency query
# that omits it, and only the two dimensions the board groups by earn that second
# copy. The last is what re-projection and the orphan sweep delete by.
_INDEXES = (
    ("ix_income_board_airline",
     ["tenant_id", "created_by_id", "direction", "issue_ym", "airline_id"]),
    ("ix_income_board_supplier",
     ["tenant_id", "created_by_id", "direction", "issue_ym", "supplier_id"]),
    ("ix_income_board_travel",
     ["tenant_id", "created_by_id", "direction", "travel_ym"]),
    ("ix_income_board_status",
     ["tenant_id", "created_by_id", "direction", "status"]),
    ("ix_income_board_tenant_airline",
     ["tenant_id", "direction", "issue_ym", "airline_id"]),
    ("ix_income_board_tenant_supplier",
     ["tenant_id", "direction", "issue_ym", "supplier_id"]),
    ("ix_income_board_batch", ["tenant_id", "source", "batch_id"]),
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),

        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        # A different table per `source`, so no FK — the call
        # commission_calculations.source_row_id already makes.
        sa.Column("source_row_id", sa.BigInteger(), nullable=False),

        # ── Discriminators. `direction` is never a multiplier; see the model. ──
        sa.Column("direction", sa.String(length=10), nullable=False,
                  server_default="inbound"),
        sa.Column("counterparty_kind", sa.String(length=12), nullable=False,
                  server_default="airline"),

        # ── Carrier. No FK, deliberately. ──
        sa.Column("airline_id", sa.Integer(), nullable=True),
        sa.Column("airline_name", sa.String(length=255), nullable=True),
        sa.Column("airline_match_by", sa.String(length=16), nullable=True),

        # ── B2B counterparty. No FK, deliberately. ──
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("supplier_code", sa.String(length=50), nullable=True),
        sa.Column("supplier_branch", sa.String(length=255), nullable=True),
        sa.Column("supplier_match_by", sa.String(length=12), nullable=True),
        sa.Column("vendor_agency_id", sa.Integer(), nullable=True),

        # ── Customer party. Ships nullable; written in phase 2. ──
        sa.Column("customer_party_kind", sa.String(length=12), nullable=True),
        sa.Column("customer_party_id", sa.Integer(), nullable=True),
        sa.Column("billing_id", sa.Integer(), nullable=True),

        # ── Time, with provenance. ──
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("issue_ym", sa.String(length=7), nullable=True),
        sa.Column("issue_date_source", sa.String(length=16), nullable=True),
        sa.Column("travel_date", sa.Date(), nullable=True),
        sa.Column("travel_ym", sa.String(length=7), nullable=True),
        sa.Column("travel_date_source", sa.String(length=12), nullable=True),
        sa.Column("date_parse_failed", sa.Boolean(), nullable=False,
                  server_default="false"),

        # ── Deal-matching criteria. 'I' | 'D' | NULL. ──
        sa.Column("segment", sa.String(length=1), nullable=True),
        sa.Column("segment_raw", sa.String(length=40), nullable=True),
        sa.Column("booking_class", sa.String(length=30), nullable=True),

        sa.Column("txn_type", sa.String(length=24), nullable=True),
        sa.Column("txn_class", sa.String(length=12), nullable=False,
                  server_default="other"),

        # ── Money. Signed as the document prints it. ──
        *[sa.Column(c, sa.Numeric(14, 2), nullable=True) for c in _LINE_MONEY],
        sa.Column("gross_source", sa.String(length=12), nullable=True),

        # NULL = needs_data. Never collapse to zero.
        sa.Column("incentive", sa.Numeric(18, 2), nullable=True),
        # Never added to `incentive`, here or anywhere else.
        sa.Column("iata_commission", sa.Numeric(18, 2), nullable=True),

        # NULL means could not be judged, which is NOT False.
        sa.Column("declared_net_ok", sa.Boolean(), nullable=True),
        # Positive = under-recovery: the vendor owes us.
        sa.Column("variance_total", sa.Numeric(18, 2), nullable=True),

        # ── Why the figure is what it is. String status, never a DB enum, so an
        # eighth status is a code change and not a migration.
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="pending"),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("skipped_criteria", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("matched_deal_id", sa.BigInteger(),
                  sa.ForeignKey("deals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("matched_deal_type", sa.String(length=10), nullable=True),
        sa.Column("matched_deal_name", sa.String(length=255), nullable=True),
        sa.Column("matched_deal_no", sa.String(length=20), nullable=True),
        sa.Column("slab_dependent", sa.Boolean(), nullable=False,
                  server_default="false"),

        # ── Identity. ticket_key is materialised now; its index waits for phase 3.
        sa.Column("document_number", sa.String(length=40), nullable=True),
        sa.Column("ticket_number", sa.String(length=40), nullable=True),
        sa.Column("ticket_key", sa.String(length=40), nullable=True),
        sa.Column("pnr", sa.String(length=40), nullable=True),
        sa.Column("pax_count", sa.SmallInteger(), nullable=False, server_default="1"),

        # ── Bookkeeping. run_id is NULL for BSP and for tickets: neither goes
        # through commission_runs.
        sa.Column("run_id", sa.BigInteger(),
                  sa.ForeignKey("commission_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("engine_version", sa.String(length=20), nullable=True),
        sa.Column("projection_version", sa.String(length=10), nullable=True),
        # NOT NULL with a server_default, not a Python-side default: every row here is
        # written by an INSERT ... SELECT, where a model default would never fire.
        sa.Column("projected_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("now()")),
        # Never updated on re-projection — when this line was first priced, as opposed
        # to when it was last restated.
        sa.Column("first_seen_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("now()")),

        # One current row per source row, as commission_calculations and
        # sell_reconciliations already enforce.
        sa.UniqueConstraint("tenant_id", "created_by_id", "source", "source_row_id",
                            name="uq_income_board_source_row"),
    )

    for name, cols in _INDEXES:
        op.create_index(name, TABLE, cols)


def downgrade() -> None:
    # Safe in the full sense: this migration creates no column on any existing table
    # and backfills nothing, and every row in this table can be reconstructed from
    # commission_calculations and bsp_statement_rows by POST /dashboard/income/rebuild.
    for name, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=TABLE)
    op.drop_table(TABLE)
