"""Add contract_year to airlines and airline_approvals tables

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'o9p0q1r2s3t4'
down_revision: Union[str, None] = 'n8o9p0q1r2s3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('airlines', sa.Column('contract_year', sa.String(length=2), nullable=True))
    op.add_column('airline_approvals', sa.Column('contract_year', sa.String(length=2), nullable=True))


def downgrade() -> None:
    op.drop_column('airlines', 'contract_year')
    op.drop_column('airline_approvals', 'contract_year')
