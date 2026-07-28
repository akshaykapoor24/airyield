"""Rebuild LCC Detailed as a scalable batch-header + typed-rows schema

Drops the old single JSONB-blob ``lcc_detailed`` table and recreates it as:
  * ``lcc_detailed_batch`` — one row per upload (provenance + column_map + async status/progress)
  * ``lcc_detailed``       — one row per statement line, 27 core fields as TYPED indexed
    columns + folded taxes/segments/ssr/extra/raw_data JSONB.

Start-clean: existing lcc_detailed rows are test data and are discarded.

Revision ID: lcc_detailed_v2_01
Revises: supp_directory_01
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "lcc_detailed_v2_01"
down_revision: Union[str, None] = "supp_directory_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── drop the old single-table design (start clean) ───────────────────────
    op.drop_table("lcc_detailed")

    # ── batch header ─────────────────────────────────────────────────────────
    op.create_table(
        "lcc_detailed_batch",
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("file_url", sa.String(length=1000), nullable=True),
        sa.Column("source_format", sa.String(length=40), nullable=True),
        sa.Column("header_row", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("column_map", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="staged"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_columns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    op.create_index("ix_lcc_detailed_batch_tenant_id", "lcc_detailed_batch", ["tenant_id"])
    op.create_index("ix_lcc_detailed_batch_created_by_id", "lcc_detailed_batch", ["created_by_id"])
    op.create_index("ix_lcc_detailed_batch_status", "lcc_detailed_batch", ["status"])
    op.create_index("ix_lcc_detailed_batch_uploaded_at", "lcc_detailed_batch", ["uploaded_at"])

    # ── rows (typed core columns + folded JSONB) ─────────────────────────────
    op.create_table(
        "lcc_detailed",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.String(length=100), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        # core typed columns
        sa.Column("transaction_date", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("payment_datetime", sa.DateTime(), nullable=True),
        sa.Column("payment_method_code", sa.String(length=40), nullable=True),
        sa.Column("payment_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("payment_number", sa.String(length=60), nullable=True),
        sa.Column("booking_date", sa.DateTime(), nullable=True),
        sa.Column("record_locator", sa.String(length=20), nullable=True),
        sa.Column("source_organization_code", sa.String(length=40), nullable=True),
        sa.Column("booking_promo_code", sa.String(length=60), nullable=True),
        sa.Column("received_by", sa.String(length=120), nullable=True),
        sa.Column("source_agent_code", sa.String(length=60), nullable=True),
        sa.Column("international", sa.Boolean(), nullable=True),
        sa.Column("currency_code", sa.String(length=8), nullable=True),
        sa.Column("product_class", sa.String(length=40), nullable=True),
        sa.Column("pax_count", sa.SmallInteger(), nullable=True),
        sa.Column("name1", sa.String(length=255), nullable=True),
        sa.Column("email_address", sa.String(length=255), nullable=True),
        sa.Column("home_phone", sa.String(length=60), nullable=True),
        sa.Column("gds_record_code", sa.String(length=40), nullable=True),
        sa.Column("gds_record_locator", sa.String(length=20), nullable=True),
        sa.Column("gds_booking_system_code", sa.String(length=40), nullable=True),
        sa.Column("payment_status", sa.String(length=40), nullable=True),
        sa.Column("total", sa.Numeric(14, 2), nullable=True),
        sa.Column("base_fare", sa.Numeric(14, 2), nullable=True),
        sa.Column("other_fee_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("other_ssr_total", sa.Numeric(14, 2), nullable=True),
        # derived typed columns
        sa.Column("departure_date", sa.Date(), nullable=True),
        sa.Column("taxes_total", sa.Numeric(14, 2), nullable=True),
        # folded / audit JSONB
        sa.Column("taxes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("segments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ssr", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["lcc_detailed_batch.batch_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lcc_detailed_batch_fk", "lcc_detailed", ["batch_id"])
    op.create_index("ix_lcc_detailed_tenant_id", "lcc_detailed", ["tenant_id"])
    op.create_index("ix_lcc_detailed_created_by_id", "lcc_detailed", ["created_by_id"])
    op.create_index("ix_lcc_detailed_tenant_record_locator", "lcc_detailed", ["tenant_id", "record_locator"])
    op.create_index("ix_lcc_detailed_tenant_gds_locator", "lcc_detailed", ["tenant_id", "gds_record_locator"])
    op.create_index("ix_lcc_detailed_tenant_departure", "lcc_detailed", ["tenant_id", "departure_date"])
    op.create_index("ix_lcc_detailed_tenant_booking", "lcc_detailed", ["tenant_id", "booking_date"])
    op.create_index("ix_lcc_detailed_tenant_agent", "lcc_detailed", ["tenant_id", "source_agent_code"])


def downgrade() -> None:
    # drop the new schema
    op.drop_table("lcc_detailed")
    op.drop_index("ix_lcc_detailed_batch_uploaded_at", table_name="lcc_detailed_batch")
    op.drop_index("ix_lcc_detailed_batch_status", table_name="lcc_detailed_batch")
    op.drop_index("ix_lcc_detailed_batch_created_by_id", table_name="lcc_detailed_batch")
    op.drop_index("ix_lcc_detailed_batch_tenant_id", table_name="lcc_detailed_batch")
    op.drop_table("lcc_detailed_batch")

    # recreate the old single-table lcc_detailed shape (from a0b1c2d3e4f5)
    op.create_table(
        "lcc_detailed",
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
    op.create_index("ix_lcc_detailed_tenant_id", "lcc_detailed", ["tenant_id"])
    op.create_index("ix_lcc_detailed_created_by_id", "lcc_detailed", ["created_by_id"])
    op.create_index("ix_lcc_detailed_batch_id", "lcc_detailed", ["batch_id"])
    op.create_index("ix_lcc_detailed_uploaded_at", "lcc_detailed", ["uploaded_at"])
