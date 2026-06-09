"""add adm_acm_ra to uploaded_tickets

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-06-09

"""
from alembic import op
import sqlalchemy as sa

revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('uploaded_tickets', sa.Column('adm_acm_ra', sa.String(10), nullable=True))


def downgrade():
    op.drop_column('uploaded_tickets', 'adm_acm_ra')
