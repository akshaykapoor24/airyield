"""Vendors data → Payment Module: MO statement + vendor-vs-MO reconciliation

  mid_office_gds               The workspace's own mid-office (MO) record of what a
                               consolidator billed, uploaded under Payment Module → MO
                               Statement. Exactly the shape of `third_party_gds`: it is
                               parsed by the same Third Party GDS builder.

  payment_reconciliation_runs  One reconciliation of one vendor upload against one MO
                               upload, with totals recomputed from its rows and a snapshot
                               of the commission run it read.

  payment_reconciliations      One reconciled ticket — a vendor group, an MO group, or the
                               two paired — with vendor/MO/variance figures, the deal
                               commission, the shortfall and the payable.

Row-id lists into the statement tables carry no FK, as in `commission_calculations`: a
reprocess re-inserts statement rows with new ids, and a derived report must never block a
statement delete.

Hand-written: autogenerate on this repo proposes ~240 unrelated drops.

Revision ID: payment_module_01
Revises: billing_date_01
Create Date: 2026-10-04 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "payment_module_01"
down_revision: Union[str, None] = "billing_date_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MO = "mid_office_gds"
_RUNS = "payment_reconciliation_runs"
_ROWS = "payment_reconciliations"


def _money(name: str, scale: int = 18):
    return sa.Column(name, sa.Numeric(scale, 2), nullable=True)


def _count(name: str):
    return sa.Column(name, sa.Integer(), nullable=False, server_default="0")


def upgrade() -> None:
    # ── MO statement rows: same columns and indexes as tp_gds_lcc_01._create ──
    op.create_table(
        _MO,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("file_url", sa.String(length=1000), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("data", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("taxes", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_format", sa.String(length=40), nullable=True),
        sa.Column("segments", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ssr", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_data", JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("tenant_id", "created_by_id", "batch_id", "uploaded_at"):
        op.create_index(f"ix_{_MO}_{col}", _MO, [col])

    # ── runs ─────────────────────────────────────────────────────────────────
    op.create_table(
        _RUNS,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("vendor_batch_id", sa.String(length=100), nullable=False),
        sa.Column("mo_batch_id", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="processing"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        _count("total_rows"), _count("matched_rows"), _count("minor_diff_rows"),
        _count("mismatch_rows"), _count("possible_match_rows"), _count("vendor_only_rows"),
        _count("mo_only_rows"),
        _money("vendor_net_total"), _money("mo_net_total"), _money("net_variance_total"),
        _money("vendor_only_total"), _money("mo_only_total"), _money("calc_commission_total"),
        _money("vendor_commission_total"), _money("shortfall_total"), _money("payable_total"),
        _money("vendor_closing_balance"), _money("mo_closing_balance"),
        sa.Column("commission_run_id", sa.BigInteger(), nullable=True),
        sa.Column("commission_completed_at", sa.DateTime(), nullable=True),
        _count("commission_priced_rows"), _count("commission_unpriced_rows"),
        sa.Column("params", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("tenant_id", "created_by_id", "completed_at"):
        op.create_index(f"ix_{_RUNS}_{col}", _RUNS, [col])
    op.create_index("ix_payment_recon_runs_pair", _RUNS,
                    ["tenant_id", "created_by_id", "vendor_batch_id", "mo_batch_id"])

    # ── reconciled tickets ───────────────────────────────────────────────────
    op.create_table(
        _ROWS,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("vendor_batch_id", sa.String(length=100), nullable=False),
        sa.Column("mo_batch_id", sa.String(length=100), nullable=False),
        sa.Column("vendor_row_ids", JSONB(), nullable=True),
        sa.Column("mo_row_ids", JSONB(), nullable=True),
        _count("vendor_rows"), _count("mo_rows"),
        sa.Column("ticket_number", sa.String(length=100), nullable=True),
        sa.Column("ticket_prefix", sa.String(length=4), nullable=True),
        sa.Column("airline_name", sa.String(length=200), nullable=True),
        sa.Column("airline_code", sa.String(length=20), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("pax_name", sa.String(length=300), nullable=True),
        sa.Column("sector", sa.String(length=200), nullable=True),
        sa.Column("pnr", sa.String(length=40), nullable=True),
        sa.Column("match_status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("match_method", sa.String(length=16), nullable=False, server_default="none"),
        _money("vendor_gross", 14), _money("mo_gross", 14),
        _money("vendor_net", 14), _money("mo_net", 14),
        _money("net_variance", 14), _money("abs_net_variance", 14),
        _money("vendor_commission", 14), _money("mo_commission", 14),
        _money("calc_commission", 14), _money("commission_shortfall", 14),
        _money("payable_after_commission", 14),
        sa.Column("commission_status", sa.String(length=12), nullable=False,
                  server_default="none"),
        sa.Column("field_diffs", JSONB(), nullable=True),
        sa.Column("issues", JSONB(), nullable=True),
        sa.Column("notes", JSONB(), nullable=True),
        sa.Column("commission_detail", JSONB(), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("tenant_id", "created_by_id", "run_id", "ticket_number", "match_status",
                "reconciled_at"):
        op.create_index(f"ix_{_ROWS}_{col}", _ROWS, [col])
    op.create_index("ix_payment_recon_pair", _ROWS,
                    ["tenant_id", "created_by_id", "vendor_batch_id", "mo_batch_id"])
    op.create_index("ix_payment_recon_pair_status", _ROWS,
                    ["tenant_id", "created_by_id", "vendor_batch_id", "mo_batch_id",
                     "match_status"])


def downgrade() -> None:
    op.drop_index("ix_payment_recon_pair_status", table_name=_ROWS)
    op.drop_index("ix_payment_recon_pair", table_name=_ROWS)
    for col in ("tenant_id", "created_by_id", "run_id", "ticket_number", "match_status",
                "reconciled_at"):
        op.drop_index(f"ix_{_ROWS}_{col}", table_name=_ROWS)
    op.drop_table(_ROWS)

    op.drop_index("ix_payment_recon_runs_pair", table_name=_RUNS)
    for col in ("tenant_id", "created_by_id", "completed_at"):
        op.drop_index(f"ix_{_RUNS}_{col}", table_name=_RUNS)
    op.drop_table(_RUNS)

    for col in ("tenant_id", "created_by_id", "batch_id", "uploaded_at"):
        op.drop_index(f"ix_{_MO}_{col}", table_name=_MO)
    op.drop_table(_MO)
