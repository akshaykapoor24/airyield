"""add all missing columns to uploaded_deals (incentives + deal header fields)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # incentive JSON blobs
    op.add_column("uploaded_deals", sa.Column("incentive_types", sa.JSON(),        nullable=True))
    op.add_column("uploaded_deals", sa.Column("incentive_data",  sa.JSON(),        nullable=True))

    # deal header fields
    op.add_column("uploaded_deals", sa.Column("airline_type",    sa.String(20),    nullable=True))
    op.add_column("uploaded_deals", sa.Column("airline_name",    sa.String(255),   nullable=True))
    op.add_column("uploaded_deals", sa.Column("contract_year",   sa.String(50),    nullable=True))
    op.add_column("uploaded_deals", sa.Column("valid_from",      sa.Date(),        nullable=True))
    op.add_column("uploaded_deals", sa.Column("valid_to",        sa.Date(),        nullable=True))
    op.add_column("uploaded_deals", sa.Column("trigger_type",    sa.String(50),    nullable=True))
    op.add_column("uploaded_deals", sa.Column("payout_type",     sa.String(50),    nullable=True))
    op.add_column("uploaded_deals", sa.Column("entity",          sa.String(50),    nullable=True))
    op.add_column("uploaded_deals", sa.Column("remark",          sa.Text(),        nullable=True))
    op.add_column("uploaded_deals", sa.Column("iata_number",     sa.String(50),    nullable=True))
    op.add_column("uploaded_deals", sa.Column("business_type",   sa.String(50),    nullable=True))
    op.add_column("uploaded_deals", sa.Column("entity_lcc",      sa.String(50),    nullable=True))
    op.add_column("uploaded_deals", sa.Column("login_id",        sa.String(100),   nullable=True))
    op.add_column("uploaded_deals", sa.Column("deal_maker_name", sa.String(255),   nullable=True))


def downgrade() -> None:
    op.drop_column("uploaded_deals", "deal_maker_name")
    op.drop_column("uploaded_deals", "login_id")
    op.drop_column("uploaded_deals", "entity_lcc")
    op.drop_column("uploaded_deals", "business_type")
    op.drop_column("uploaded_deals", "iata_number")
    op.drop_column("uploaded_deals", "remark")
    op.drop_column("uploaded_deals", "entity")
    op.drop_column("uploaded_deals", "payout_type")
    op.drop_column("uploaded_deals", "trigger_type")
    op.drop_column("uploaded_deals", "valid_to")
    op.drop_column("uploaded_deals", "valid_from")
    op.drop_column("uploaded_deals", "contract_year")
    op.drop_column("uploaded_deals", "airline_name")
    op.drop_column("uploaded_deals", "airline_type")
    op.drop_column("uploaded_deals", "incentive_data")
    op.drop_column("uploaded_deals", "incentive_types")
