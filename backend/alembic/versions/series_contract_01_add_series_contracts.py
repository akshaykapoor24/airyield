"""Add series_contracts table (Series / SIT / MICE block bookings)

Records a block booking — a group PNR for N pax at a fixed fare, with a payment
schedule in JSONB — plus the issuance rollup (tickets issued, ticket numbers,
amount issued) that `SeriesContractMatchingService` recomputes from the tickets
actually issued on that PNR.

Also adds functional lower() indexes on uploaded_tickets.gds_pnr / air_pnr.
Neither column was indexed and contract matching is case-insensitive, so without
these every matching run is a sequential scan of the ticket table.

Revision ID: series_contract_01
Revises: bsp_commission_03
Create Date: 2026-08-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "series_contract_01"
down_revision: Union[str, None] = "bsp_commission_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "series_contracts",
        sa.Column("id",              sa.Integer(),      nullable=False),
        sa.Column("tenant_id",       sa.Integer(),      nullable=True),
        sa.Column("created_by_id",   sa.Integer(),      nullable=False),
        sa.Column("contract_type",   sa.String(10),     nullable=True),
        sa.Column("agent_type",      sa.String(10),     nullable=True),
        sa.Column("agent_name",      sa.String(200),    nullable=True),
        sa.Column("airline_name",    sa.String(200),    nullable=True),
        sa.Column("airline_code",    sa.String(10),     nullable=True),
        sa.Column("pnr_no",          sa.String(50),     nullable=True),
        sa.Column("pax_count",       sa.Integer(),      nullable=True),
        sa.Column("trip_type",       sa.String(10),     nullable=True),
        sa.Column("date_of_travel",  sa.Date(),         nullable=True),
        sa.Column("fare_per_pax",    sa.Numeric(14, 2), nullable=True),
        sa.Column("total_fare",      sa.Numeric(14, 2), nullable=True),
        sa.Column("payment_terms",   postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tickets_issued",  sa.Integer(),      nullable=False, server_default="0"),
        sa.Column("ticket_numbers",  postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("amount_issued",   sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("match_status",    sa.String(20),     nullable=True),
        sa.Column("last_matched_at", sa.DateTime(),     nullable=True),
        sa.Column("created_at",      sa.DateTime(),     nullable=True),
        sa.Column("updated_at",      sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"],     ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_series_contracts_tenant_id", "series_contracts", ["tenant_id"])
    op.create_index("ix_series_contracts_created_by_id", "series_contracts", ["created_by_id"])
    op.create_index("ix_series_contracts_pnr_no", "series_contracts", ["pnr_no"])

    # Expression indexes — op.create_index() cannot express lower(col).
    op.execute("CREATE INDEX ix_uploaded_tickets_gds_pnr_lower ON uploaded_tickets (lower(gds_pnr))")
    op.execute("CREATE INDEX ix_uploaded_tickets_air_pnr_lower ON uploaded_tickets (lower(air_pnr))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_uploaded_tickets_air_pnr_lower")
    op.execute("DROP INDEX IF EXISTS ix_uploaded_tickets_gds_pnr_lower")

    op.drop_index("ix_series_contracts_pnr_no", table_name="series_contracts")
    op.drop_index("ix_series_contracts_created_by_id", table_name="series_contracts")
    op.drop_index("ix_series_contracts_tenant_id", table_name="series_contracts")
    op.drop_table("series_contracts")
