"""add ticket exclusion reason

Revision ID: t4u5v6w7x8y9
Revises: 23f7d53e7e14
Create Date: 2026-05-27
"""
from alembic import op
import sqlalchemy as sa

revision = 't4u5v6w7x8y9'
down_revision = '23f7d53e7e14'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('uploaded_tickets', sa.Column('exclusion_reason', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('uploaded_tickets', 'exclusion_reason')
