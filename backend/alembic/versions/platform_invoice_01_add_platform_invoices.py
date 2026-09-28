"""Platform admin → Subscriptions: invoices the platform raises to a workspace

  platform_invoices   One issued invoice per row: a numbered, dated snapshot of who billed
                      whom for what, with the GST split and grand total stored. Never
                      deleted — cancelled, with a reason, keeping its number.

See app/models/platform_invoice.py for why the row is a snapshot, how numbers are allocated
and why billed_tenant_id is SET NULL rather than CASCADE.

Hand-written: autogenerate on this repo proposes ~240 unrelated drops.

Revision ID: platform_invoice_01
Revises: usage_meter_01
Create Date: 2026-09-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "platform_invoice_01"
down_revision: Union[str, None] = "usage_meter_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_invoices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("invoice_number", sa.String(32), nullable=False, unique=True),
        sa.Column("financial_year", sa.String(5), nullable=False),
        sa.Column("serial", sa.Integer(), nullable=False),
        sa.Column("billed_tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("issuer", postgresql.JSONB(), nullable=False),
        sa.Column("bill_to", postgresql.JSONB(), nullable=False),
        sa.Column("gst_treatment", sa.String(12), nullable=False),
        sa.Column("place_of_supply_code", sa.String(2), nullable=True),
        sa.Column("gst_rate", sa.Numeric(5, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("line_items", postgresql.JSONB(), nullable=False),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
        sa.Column("cgst", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("sgst", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("igst", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_tax", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("grand_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.Date(), nullable=True),
        sa.Column("payment_reference", sa.String(120), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_reason", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("sent_to", sa.String(255), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("financial_year", "serial", name="uq_platform_invoices_fy_serial"),
        sa.CheckConstraint("status IN ('issued', 'paid', 'cancelled')", name="ck_platform_invoices_status"),
        sa.CheckConstraint("gst_treatment IN ('cgst_sgst', 'igst', 'none')", name="ck_platform_invoices_treatment"),
    )
    op.create_index("ix_platform_invoices_tenant_date", "platform_invoices", ["billed_tenant_id", "invoice_date"])


def downgrade() -> None:
    op.drop_index("ix_platform_invoices_tenant_date", table_name="platform_invoices")
    op.drop_table("platform_invoices")
