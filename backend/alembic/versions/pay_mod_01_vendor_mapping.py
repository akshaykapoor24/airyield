"""Payment Module: Vendor Mapping decisions, and payments kept per vendor

The Payment Module's MO is now Internal Statement's Booking / MO uploads, and its Payments tab
is organised by vendor (services/vendor_mapping.py):

* vendor_mapping_decisions — what the user decided about a vendor line that does not map onto
  the MO: the vendor is wrong (claimed), the MO is wrong, or accepted. Keyed by the line's
  content key; the figures are the snapshot it was decided on (models/vendor_mapping.py).
* vendor_payments.vendor_key / vendor_name / agency_id — the vendor a payment was made to, as
  Agency Master names it (one name and branch); NULL on the per-ticket payments made before.

Revision ID: pay_mod_01
Revises: internal_std_03
Create Date: 2026-10-29 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'pay_mod_01'
down_revision: Union[str, None] = 'internal_std_03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vendor_mapping_decisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('item_key', sa.String(500), nullable=False),
        sa.Column('ticket_number', sa.String(100), nullable=True),
        sa.Column('kind', sa.String(16), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('vendor_fare', sa.Numeric(18, 2), nullable=True),
        sa.Column('mo_fare', sa.Numeric(18, 2), nullable=True),
        sa.Column('vendor_net', sa.Numeric(18, 2), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'created_by_id', 'item_key', name='uq_vendor_mapping_decision_key'),
    )
    op.create_index('ix_vendor_mapping_decisions_tenant_id', 'vendor_mapping_decisions', ['tenant_id'])
    op.create_index('ix_vendor_mapping_decisions_created_by_id', 'vendor_mapping_decisions', ['created_by_id'])

    op.add_column('vendor_payments', sa.Column('vendor_key', sa.String(600), nullable=True))
    op.add_column('vendor_payments', sa.Column('vendor_name', sa.String(300), nullable=True))
    op.add_column('vendor_payments', sa.Column(
        'agency_id', sa.Integer(), sa.ForeignKey('agencies.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_vendor_payments_vendor_key', 'vendor_payments', ['vendor_key'])


def downgrade() -> None:
    op.drop_index('ix_vendor_payments_vendor_key', table_name='vendor_payments')
    op.drop_column('vendor_payments', 'agency_id')
    op.drop_column('vendor_payments', 'vendor_name')
    op.drop_column('vendor_payments', 'vendor_key')
    op.drop_index('ix_vendor_mapping_decisions_created_by_id', table_name='vendor_mapping_decisions')
    op.drop_index('ix_vendor_mapping_decisions_tenant_id', table_name='vendor_mapping_decisions')
    op.drop_table('vendor_mapping_decisions')
