"""Vendors → Reconciliation: buy (vendor statement) vs sell (customer tickets)

  sell_reconciliation_runs  One attempt per source. The missing batch header — these
                            sources keep no header row, so status, progress and the
                            roll-ups need a home. Modelled on `commission_runs`.

  sell_reconciliations      One reconciled unit: a vendor row, a sold ticket, or the two
                            paired, with a buy/sell/variance/match quadruple per money
                            field and a `margin` headline.

  ix_uploaded_tickets_tn_norm   Functional index on the NORMALISED ticket number.

THE FUNCTIONAL INDEX IS NOT OPTIONAL. `uploaded_tickets.ticket_number` carries no index at
all today, and this engine joins on `upper(ltrim(regexp_replace(...)))` of it — the same
expression `bsp_reconciliation.norm_tn` and `ticket_details._norm_sql` already agree on.
Without the index every reconciliation run sequentially scans every ticket the workspace
has ever uploaded.

It is built CONCURRENTLY, for the reason the report_exports migration gives about
`bsp_statement_rows`: a plain CREATE INDEX takes a SHARE lock that blocks every ticket
upload for the length of the build. CREATE INDEX CONCURRENTLY cannot run inside a
transaction, hence the autocommit block — the table DDL above it is committed first, on
purpose. A concurrent build that fails leaves an INVALID index behind under the real name,
which IF NOT EXISTS would then skip forever while the planner ignored it, so an invalid
leftover is dropped and rebuilt rather than trusted.

Hand-written: autogenerate on this repo proposes ~240 unrelated drops.

Revision ID: sell_recon_01
Revises: report_exports_01
Create Date: 2026-09-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "sell_recon_01"
down_revision: Union[str, None] = "report_exports_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The index name and the expression it is built on, used by both directions.
TN_INDEX = "ix_uploaded_tickets_tn_norm"
TN_EXPR = "(upper(ltrim(regexp_replace(ticket_number, '[^0-9A-Za-z]', '', 'g'), '0')))"

MONEY_FIELDS = ("fare", "yq", "yr", "tax", "gross", "commission", "net")


def _money(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(14, 2), nullable=True)


def upgrade() -> None:
    op.create_table(
        "sell_reconciliation_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),

        sa.Column("source", sa.String(length=24), nullable=False),
        # NULL = every batch of this source. The screen is a flat list across statements,
        # so covering all of them is the normal run, not the exception.
        sa.Column("batch_id", sa.String(length=100), nullable=True),
        sa.Column("engine_version", sa.String(length=20), nullable=True),

        sa.Column("status", sa.String(length=12), nullable=False, server_default="queued"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),

        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),

        sa.Column("matched_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minor_diff_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mismatch_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buy_only_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sell_only_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("possible_match_rows", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("total_buy", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_sell", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_margin", sa.Numeric(18, 2), nullable=True),

        sa.Column("params", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_sell_reconciliation_runs_tenant_id", "sell_reconciliation_runs", ["tenant_id"])
    op.create_index("ix_sell_reconciliation_runs_created_by_id", "sell_reconciliation_runs", ["created_by_id"])
    op.create_index("ix_sell_reconciliation_runs_batch_id", "sell_reconciliation_runs", ["batch_id"])
    op.create_index("ix_sell_reconciliation_runs_started_at", "sell_reconciliation_runs", ["started_at"])
    op.create_index("ix_sell_recon_runs_lookup", "sell_reconciliation_runs",
                    ["tenant_id", "created_by_id", "source", "batch_id"])

    quadruples: list[sa.Column] = []
    for f in MONEY_FIELDS:
        quadruples += [
            _money(f"buy_{f}"), _money(f"sell_{f}"), _money(f"{f}_variance"),
            sa.Column(f"{f}_match", sa.Boolean(), nullable=True),
        ]

    op.create_table(
        "sell_reconciliations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),

        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=True),

        # No FK: it points at a different table per `source`.
        sa.Column("source_row_id", sa.BigInteger(), nullable=True),
        sa.Column("ticket_id", sa.Integer(),
                  sa.ForeignKey("uploaded_tickets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sell_legs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buy_rows", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("ticket_number", sa.String(length=100), nullable=True),
        sa.Column("ticket_prefix", sa.String(length=4), nullable=True),
        sa.Column("airline_name", sa.String(length=200), nullable=True),
        sa.Column("airline_code", sa.String(length=20), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("pax_name", sa.String(length=300), nullable=True),
        sa.Column("sector", sa.String(length=200), nullable=True),

        sa.Column("match_status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("match_method", sa.String(length=16), nullable=False, server_default="none"),

        *quadruples,

        sa.Column("margin", sa.Numeric(14, 2), nullable=True),
        sa.Column("abs_margin", sa.Numeric(14, 2), nullable=True),

        sa.Column("field_diffs", JSONB, nullable=True),
        sa.Column("issues", JSONB, nullable=True),
        sa.Column("notes", JSONB, nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),

        sa.Column("reconciled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),

        # One current answer per vendor row per source. `sell_only` rows carry a NULL
        # source_row_id and Postgres treats NULLs as distinct, so they are exempt — which
        # is right: they are keyed by ticket, not by a vendor row.
        sa.UniqueConstraint("tenant_id", "created_by_id", "source", "source_row_id",
                            name="uq_sell_recon_source_row"),
    )
    for col in ("tenant_id", "created_by_id", "run_id", "batch_id", "source_row_id",
                "ticket_id", "ticket_number", "issue_date", "match_status", "severity",
                "reconciled_at"):
        op.create_index(f"ix_sell_reconciliations_{col}", "sell_reconciliations", [col])
    op.create_index("ix_sell_recon_scope", "sell_reconciliations",
                    ["tenant_id", "created_by_id", "source"])
    op.create_index("ix_sell_recon_scope_status", "sell_reconciliations",
                    ["tenant_id", "created_by_id", "source", "match_status"])
    op.create_index("ix_sell_recon_batch", "sell_reconciliations", ["source", "batch_id"])

    # ── the join-key index, outside the transaction ──────────────────────────
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        invalid = conn.exec_driver_sql(
            "SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
            "WHERE c.relname = %(n)s AND NOT i.indisvalid",
            {"n": TN_INDEX},
        ).scalar()
        if invalid:
            conn.exec_driver_sql(f"DROP INDEX IF EXISTS {TN_INDEX}")
        conn.exec_driver_sql(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {TN_INDEX} "
            f"ON uploaded_tickets {TN_EXPR}"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.get_bind().exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS {TN_INDEX}")
    op.drop_table("sell_reconciliations")
    op.drop_table("sell_reconciliation_runs")
