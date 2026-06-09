"""add file_url to deal_batches and ticket_statements

Revision ID: e4f5a6b7c8d9
Revises: c1d2e3f4a5b6
Create Date: 2026-06-08

"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('deal_batches',      sa.Column('file_url', sa.String(1000), nullable=True))
    op.add_column('ticket_statements', sa.Column('file_url', sa.String(1000), nullable=True))


def downgrade():
    op.drop_column('ticket_statements', 'file_url')
    op.drop_column('deal_batches',      'file_url')
