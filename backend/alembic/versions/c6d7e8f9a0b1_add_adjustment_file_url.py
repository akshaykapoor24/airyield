"""store the uploaded ADM/ACM/RA XLS in GCS — add file_url to the adjustment tables

Adds a nullable ``file_url`` (GCS blob path of the uploaded spreadsheet) to
airline_adm / airline_acm / airline_ra so each upload's original file can be
downloaded/viewed. Additive and reversible.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-07-17 00:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6d7e8f9a0b1'
down_revision: Union[str, None] = 'b5c6d7e8f9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('airline_adm', 'airline_acm', 'airline_ra')


def upgrade() -> None:
    for t in _TABLES:
        op.add_column(t, sa.Column('file_url', sa.String(length=1000), nullable=True))


def downgrade() -> None:
    for t in _TABLES:
        op.drop_column(t, 'file_url')
