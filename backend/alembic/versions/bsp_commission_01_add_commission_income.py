"""Commission income on BSP statements — per-row deal match + estimated incentive

Adds the derived calculation block to bsp_statement_rows (mirroring the one on
uploaded_tickets) and the run state / roll-up totals to bsp_statements.

A commission run matches every settlement row against the user's approved AIRLINE
deals. BSP prints no cabin class, no sector and no travel date, so the criteria
that could not be evaluated are listed per row in `skipped_criteria` instead of
being silently defaulted.

Revision ID: bsp_commission_01
Revises: lcc_ctabta_01
Create Date: 2026-07-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "bsp_commission_01"
down_revision: Union[str, None] = "lcc_ctabta_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (name, type, nullable, server_default) for bsp_statement_rows
_ROW_COLS = [
    ("matched_deal_id",          sa.Integer(),                    True,  None),
    ("matched_deal_type",        sa.String(length=20),            True,  None),
    ("matched_deal_name",        sa.String(length=300),           True,  None),
    ("calculated_incentive",     sa.Numeric(14, 2),               True,  None),
    ("iata_commission",          sa.Numeric(14, 2),               True,  None),
    ("incentive_breakdown",      postgresql.JSONB(),              True,  None),
    ("commission_status",        sa.String(length=12),            False, "pending"),
    ("commission_reason",        sa.String(length=500),           True,  None),
    ("skipped_criteria",         postgresql.JSONB(),              True,  None),
    ("commission_calculated_at", sa.DateTime(),                   True,  None),
]

# (name, type, nullable, server_default) for bsp_statements
_STMT_COLS = [
    ("commission_status",          sa.String(length=12), False, "idle"),
    ("commission_total_rows",      sa.Integer(),         False, "0"),
    ("commission_processed_rows",  sa.Integer(),         False, "0"),
    ("commission_error",           sa.Text(),            True,  None),
    ("commission_calculated_at",   sa.DateTime(),        True,  None),
    ("commission_total_incentive", sa.Numeric(16, 2),    True,  None),
    ("commission_iata_total",      sa.Numeric(16, 2),    True,  None),
    ("commission_matched_rows",    sa.Integer(),         False, "0"),
    ("commission_unmatched_rows",  sa.Integer(),         False, "0"),
    ("commission_excluded_rows",   sa.Integer(),         False, "0"),
    ("commission_skipped_rows",    sa.Integer(),         False, "0"),
]


def upgrade() -> None:
    for name, type_, nullable, default in _ROW_COLS:
        op.add_column(
            "bsp_statement_rows",
            sa.Column(name, type_, nullable=nullable, server_default=default),
        )
    for name, type_, nullable, default in _STMT_COLS:
        op.add_column(
            "bsp_statements",
            sa.Column(name, type_, nullable=nullable, server_default=default),
        )

    # Indexed: the results grid filters by status, and the refund-reversal lookup
    # walks back to a prior row's matched deal.
    op.create_index("ix_bsp_statement_rows_commission_status", "bsp_statement_rows", ["commission_status"])
    op.create_index("ix_bsp_statement_rows_matched_deal_id", "bsp_statement_rows", ["matched_deal_id"])
    op.create_index("ix_bsp_statements_commission_status", "bsp_statements", ["commission_status"])


def downgrade() -> None:
    op.drop_index("ix_bsp_statements_commission_status", table_name="bsp_statements")
    op.drop_index("ix_bsp_statement_rows_matched_deal_id", table_name="bsp_statement_rows")
    op.drop_index("ix_bsp_statement_rows_commission_status", table_name="bsp_statement_rows")

    for name, _type, _nullable, _default in _STMT_COLS:
        op.drop_column("bsp_statements", name)
    for name, _type, _nullable, _default in _ROW_COLS:
        op.drop_column("bsp_statement_rows", name)
