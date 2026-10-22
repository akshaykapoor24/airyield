"""Vendor ↔ Internal reconciliation: vendor_internal_resolutions — the user's decisions

One row per reconciliation line the user resolved: which side is wrong (or that the
difference is accepted), a note, and the figures the line showed at the time. The
reconciliation itself stays computed on request; see models/vendor_internal_recon.py.

Revision ID: vendor_internal_01
Revises: ticket_comm_sheet_03
Create Date: 2026-10-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'vendor_internal_01'
down_revision: Union[str, None] = 'ticket_comm_sheet_03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vendor_internal_resolutions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('item_key', sa.String(500), nullable=False),
        sa.Column('ticket_number', sa.String(100), nullable=True),
        sa.Column('kind', sa.String(16), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('decision', sa.String(20), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('vendor_net', sa.Numeric(18, 2), nullable=True),
        sa.Column('internal_net', sa.Numeric(18, 2), nullable=True),
        sa.Column('difference', sa.Numeric(18, 2), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'created_by_id', 'item_key', name='uq_vendor_internal_resolution_key'),
    )
    op.create_index('ix_vendor_internal_resolutions_tenant_id', 'vendor_internal_resolutions', ['tenant_id'])
    op.create_index('ix_vendor_internal_resolutions_created_by_id', 'vendor_internal_resolutions', ['created_by_id'])


def downgrade() -> None:
    op.drop_index('ix_vendor_internal_resolutions_created_by_id', table_name='vendor_internal_resolutions')
    op.drop_index('ix_vendor_internal_resolutions_tenant_id', table_name='vendor_internal_resolutions')
    op.drop_table('vendor_internal_resolutions')
