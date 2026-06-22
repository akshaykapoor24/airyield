"""airline_ticket_superset

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-06-19

Adds airline statement support:
- ticket_statements: statement_type column, statement_name made nullable
- uploaded_tickets: 35+ new airline-specific columns + tax_breakup/segments/raw_data JSONB
- ticket_calculations: new history table
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'k1l2m3n4o5p6'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ticket_statements ──────────────────────────────────────────────────
    op.add_column(
        "ticket_statements",
        sa.Column("statement_type", sa.String(10), nullable=False, server_default="B2B"),
    )
    op.alter_column("ticket_statements", "statement_name", nullable=True)

    # ── uploaded_tickets — identity ────────────────────────────────────────
    op.add_column("uploaded_tickets", sa.Column("statement_type", sa.String(10), nullable=True))

    # ── uploaded_tickets — airline passenger ──────────────────────────────
    op.add_column("uploaded_tickets", sa.Column("pax_name",        sa.String(300), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("air_pnr",         sa.String(50),  nullable=True))

    # ── uploaded_tickets — BSP booking metadata ───────────────────────────
    op.add_column("uploaded_tickets", sa.Column("pcc",                 sa.String(20),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("booking_signon",      sa.String(50),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("booking_pcc",         sa.String(20),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("booking_agency_name", sa.String(200), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("ticketing_signon",    sa.String(50),  nullable=True))

    # ── uploaded_tickets — document / trip ────────────────────────────────
    op.add_column("uploaded_tickets", sa.Column("document_type",        sa.String(50),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("fare_basis",           sa.String(100), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("fare_const_type",      sa.String(50),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("base_fare_currency",   sa.String(10),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("transaction_type",     sa.String(20),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("exchanged_for",        sa.String(100), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("stock_control_no",     sa.String(100), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("stp_no",               sa.String(100), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("void_date",            sa.String(50),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("coupon_status",        sa.String(200), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("refund_type",          sa.String(50),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("trip_id",              sa.String(100), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("ai_code",              sa.String(50),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("value_code",           sa.String(100), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("multiple_receivables", sa.String(100), nullable=True))

    # ── uploaded_tickets — airline financials ─────────────────────────────
    op.add_column("uploaded_tickets", sa.Column("wo_tax",               sa.Numeric(14, 2), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("other_tax",            sa.Numeric(14, 2), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("comm_percent",         sa.Numeric(8,  4), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("net_remit",            sa.Numeric(14, 2), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("net_fare",             sa.Numeric(14, 2), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("invoice_fare",         sa.Numeric(14, 2), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("total_refund_amount",  sa.Numeric(14, 2), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("roe",                  sa.Numeric(14, 6), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("nuc",                  sa.Numeric(14, 6), nullable=True))

    # ── uploaded_tickets — FOP ────────────────────────────────────────────
    op.add_column("uploaded_tickets", sa.Column("fop",          sa.String(20),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("fop_details",  sa.String(200), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("cc_auth",      sa.String(100), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("cc_do_expiry", sa.String(50),  nullable=True))

    # ── uploaded_tickets — flight details ─────────────────────────────────
    op.add_column("uploaded_tickets", sa.Column("flight_no",  sa.String(200), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("travel_dt",  sa.String(100), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("fare_ladder", sa.Text(),     nullable=True))

    # ── uploaded_tickets — customer / GST ────────────────────────────────
    op.add_column("uploaded_tickets", sa.Column("gstn",             sa.String(50),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("business_phone",   sa.String(50),  nullable=True))
    op.add_column("uploaded_tickets", sa.Column("business_email",   sa.String(200), nullable=True))
    op.add_column("uploaded_tickets", sa.Column("entity_address",   sa.String(500), nullable=True))

    # ── uploaded_tickets — JSONB ───────────────────────────────────────────
    op.add_column("uploaded_tickets", sa.Column("tax_breakup", JSONB, nullable=True))
    op.add_column("uploaded_tickets", sa.Column("segments",    JSONB, nullable=True))
    op.add_column("uploaded_tickets", sa.Column("raw_data",    JSONB, nullable=True))

    # ── ticket_calculations ────────────────────────────────────────────────
    op.create_table(
        "ticket_calculations",
        sa.Column("id",                  sa.Integer(),      nullable=False),
        sa.Column("ticket_id",           sa.Integer(),      nullable=False),
        sa.Column("batch_id",            sa.String(100),    nullable=False),
        sa.Column("tenant_id",           sa.Integer(),      nullable=False),
        sa.Column("deal_id",             sa.Integer(),      nullable=True),
        sa.Column("deal_type",           sa.String(20),     nullable=True),
        sa.Column("deal_name",           sa.String(300),    nullable=True),
        sa.Column("incentive_breakdown", JSONB,             nullable=True),
        sa.Column("total_incentive",     sa.Numeric(14, 2), nullable=True),
        sa.Column("ticket_status",       sa.String(10),     nullable=False),
        sa.Column("exclusion_reason",    sa.String(500),    nullable=True),
        sa.Column("calculated_at",       sa.DateTime(),     nullable=False),
        sa.Column("calculated_by_id",    sa.Integer(),      nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"],        ["uploaded_tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"],        ["tenants.id"],          ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["calculated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ticket_calculations_ticket_id", "ticket_calculations", ["ticket_id"])
    op.create_index("ix_ticket_calculations_batch_id",  "ticket_calculations", ["batch_id"])
    op.create_index("ix_ticket_calculations_tenant_id", "ticket_calculations", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_ticket_calculations_tenant_id", table_name="ticket_calculations")
    op.drop_index("ix_ticket_calculations_batch_id",  table_name="ticket_calculations")
    op.drop_index("ix_ticket_calculations_ticket_id", table_name="ticket_calculations")
    op.drop_table("ticket_calculations")

    for col in [
        "raw_data", "segments", "tax_breakup",
        "entity_address", "business_email", "business_phone", "gstn",
        "fare_ladder", "travel_dt", "flight_no",
        "cc_do_expiry", "cc_auth", "fop_details", "fop",
        "nuc", "roe", "total_refund_amount", "invoice_fare", "net_fare", "net_remit",
        "comm_percent", "other_tax", "wo_tax",
        "multiple_receivables", "value_code", "ai_code", "trip_id",
        "refund_type", "coupon_status", "void_date", "stp_no", "stock_control_no",
        "exchanged_for", "transaction_type", "base_fare_currency",
        "fare_const_type", "fare_basis", "document_type",
        "ticketing_signon", "booking_agency_name", "booking_pcc", "booking_signon", "pcc",
        "air_pnr", "pax_name",
        "statement_type",
    ]:
        op.drop_column("uploaded_tickets", col)

    op.drop_column("ticket_statements", "statement_type")
    op.alter_column("ticket_statements", "statement_name", nullable=False)
