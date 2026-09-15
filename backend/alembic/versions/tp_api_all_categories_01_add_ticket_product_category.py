"""Bill every category from Third Party API statements: product category on uploaded_tickets

`uploaded_tickets` has held airline tickets only, so nothing on it said what a line WAS.
Aggregator statements (TBO, MakeMyTrip) also carry hotels, trains, buses and cars, and each
of those bills at its own markup (customers/corporates.category_markups). Two columns:

  product_category  the markup_categories slug — 'air' | 'hotel' | 'train' | 'bus' | 'car'.
                    services/party_markup.category_of reads it to pick the markup, and the
                    flight-only readers (BSP reconciliation, the income summary, series
                    contract matching, the deal calculator) filter on it.
  service_details   what a non-air line is — property and stay dates, train and route —
                    for the billing pages and the invoice. Display only, never calculated on.

NOT NULL WITH server_default 'air', AND THAT IS THE BACKFILL. Every existing row is a flight
(LCC, NDC, B2B and the one TP-API flight), and every existing writer keeps writing flights
without being touched. A NULL category would send legacy lines down markup_for's
unknown-category branch — the party DEFAULT, not its air override — and silently re-price
invoices that have not been raised yet.

No CHECK constraint: the vocabulary lives in markup_categories.py, which states the house rule
("plain lowercase slugs, not a DB enum").

Revision ID: tp_api_all_categories_01
Revises: employee_code_01
Create Date: 2026-09-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'tp_api_all_categories_01'
down_revision: Union[str, None] = 'employee_code_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'uploaded_tickets',
        sa.Column('product_category', sa.String(12), nullable=False, server_default='air'),
    )
    op.add_column(
        'uploaded_tickets',
        sa.Column('service_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # The billing pages filter by category within a workspace.
    op.create_index(
        'ix_uploaded_tickets_tenant_product_category',
        'uploaded_tickets', ['tenant_id', 'product_category'],
    )


def downgrade() -> None:
    op.drop_index('ix_uploaded_tickets_tenant_product_category', table_name='uploaded_tickets')
    op.drop_column('uploaded_tickets', 'service_details')
    op.drop_column('uploaded_tickets', 'product_category')
