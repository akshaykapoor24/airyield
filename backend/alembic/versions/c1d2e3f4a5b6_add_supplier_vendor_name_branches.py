"""add supplier vendor_name and branches

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6g7
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('suppliers',          sa.Column('vendor_name', sa.String(255), nullable=True))
    op.add_column('suppliers',          sa.Column('branches',    sa.JSON,        nullable=True))
    op.add_column('supplier_approvals', sa.Column('vendor_name', sa.String(255), nullable=True))
    op.add_column('supplier_approvals', sa.Column('branches',    sa.JSON,        nullable=True))


def downgrade() -> None:
    op.drop_column('supplier_approvals', 'branches')
    op.drop_column('supplier_approvals', 'vendor_name')
    op.drop_column('suppliers',          'branches')
    op.drop_column('suppliers',          'vendor_name')
