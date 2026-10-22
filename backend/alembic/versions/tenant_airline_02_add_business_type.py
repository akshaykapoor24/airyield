"""Airline Master: business type per airline id

* tenant_airlines.business_type — the line of business (B2B / B2C / B2E / MICE) an
  airline id is opened for. Asked for every new id; nullable because the ids already
  saved were added before it was asked, and there is nothing to derive it from.

Revision ID: tenant_airline_02
Revises: tp_gds_dedup_01
Create Date: 2026-10-16 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tenant_airline_02'
down_revision: Union[str, None] = 'tp_gds_dedup_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenant_airlines', sa.Column('business_type', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('tenant_airlines', 'business_type')
