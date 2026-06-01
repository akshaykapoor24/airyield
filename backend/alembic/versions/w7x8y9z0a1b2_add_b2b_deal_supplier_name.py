"""add b2b deal supplier name

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = 'w7x8y9z0a1b2'
down_revision = 'v6w7x8y9z0a1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('b2b_deals', sa.Column('supplier_name', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('b2b_deals', 'supplier_name')
