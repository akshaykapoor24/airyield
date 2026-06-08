"""add tour_code to uploaded_tickets

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f7
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('uploaded_tickets', sa.Column('tour_code', sa.String(100), nullable=True))


def downgrade():
    op.drop_column('uploaded_tickets', 'tour_code')
