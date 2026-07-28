"""LCC CTA/BTA Report — dedicated normalized table

One row per lodged-account (Central/Business Travel Account) settlement
transaction. Same normalized shape as the other spec-repo LCC statement tables
(data/taxes/segments/ssr/raw_data JSONB). See services/cta_bta_report.py.

Revision ID: lcc_ctabta_01
Revises: corporate_billing_01
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "lcc_ctabta_01"
down_revision: Union[str, None] = "corporate_billing_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lcc_cta_bta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("file_url", sa.String(length=1000), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("taxes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_format", sa.String(length=40), nullable=True),
        sa.Column("segments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ssr", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lcc_cta_bta_tenant_id", "lcc_cta_bta", ["tenant_id"])
    op.create_index("ix_lcc_cta_bta_created_by_id", "lcc_cta_bta", ["created_by_id"])
    op.create_index("ix_lcc_cta_bta_batch_id", "lcc_cta_bta", ["batch_id"])
    op.create_index("ix_lcc_cta_bta_uploaded_at", "lcc_cta_bta", ["uploaded_at"])


def downgrade() -> None:
    op.drop_index("ix_lcc_cta_bta_uploaded_at", table_name="lcc_cta_bta")
    op.drop_index("ix_lcc_cta_bta_batch_id", table_name="lcc_cta_bta")
    op.drop_index("ix_lcc_cta_bta_created_by_id", table_name="lcc_cta_bta")
    op.drop_index("ix_lcc_cta_bta_tenant_id", table_name="lcc_cta_bta")
    op.drop_table("lcc_cta_bta")
