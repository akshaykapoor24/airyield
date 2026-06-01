"""add supplier new fields

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'u5v6w7x8y9z0'
down_revision = 't4u5v6w7x8y9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('suppliers', sa.Column('vendor_type', sa.String(100), nullable=True))
    op.add_column('suppliers', sa.Column('branch', sa.String(255), nullable=True))
    op.add_column('suppliers', sa.Column('alternate_phone', sa.String(50), nullable=True))
    op.add_column('suppliers', sa.Column('alternate_email', sa.String(255), nullable=True))
    op.add_column('suppliers', sa.Column('gst_number', sa.String(20), nullable=True))
    op.add_column('suppliers', sa.Column('pan_number', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('suppliers', 'pan_number')
    op.drop_column('suppliers', 'gst_number')
    op.drop_column('suppliers', 'alternate_email')
    op.drop_column('suppliers', 'alternate_phone')
    op.drop_column('suppliers', 'branch')
    op.drop_column('suppliers', 'vendor_type')
