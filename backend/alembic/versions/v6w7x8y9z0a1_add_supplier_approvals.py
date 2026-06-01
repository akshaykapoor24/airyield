"""add supplier approvals table

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'v6w7x8y9z0a1'
down_revision = 'u5v6w7x8y9z0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'supplier_approvals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('vendor_type', sa.String(100), nullable=True),
        sa.Column('branch', sa.String(255), nullable=True),
        sa.Column('contact_phone', sa.String(50), nullable=True),
        sa.Column('alternate_phone', sa.String(50), nullable=True),
        sa.Column('contact_email', sa.String(255), nullable=True),
        sa.Column('alternate_email', sa.String(255), nullable=True),
        sa.Column('gst_number', sa.String(20), nullable=True),
        sa.Column('pan_number', sa.String(20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('submitted_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('request_type', sa.String(10), nullable=False, server_default='new'),
        sa.Column('target_supplier_id', sa.Integer(), sa.ForeignKey('suppliers.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('supplier_approvals')
