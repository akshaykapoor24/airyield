"""Add split_type column to uploaded_tickets

Revision ID: s3t4u5v6w7x8
Revises: q1r2s3t4u5v6
Create Date: 2026-05-27 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 's3t4u5v6w7x8'
down_revision: Union[str, None] = 'q1r2s3t4u5v6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('uploaded_tickets', sa.Column('split_type', sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column('uploaded_tickets', 'split_type')
