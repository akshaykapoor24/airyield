"""Rename corporates.corporate_code to customer_code

The Corporate Master's "Corporate Code" is now called "Customer Code" on the form, the
template and the import wizard, so the column carries the same name. A rename, not a
drop + add: every value already entered is kept.

Revision ID: corporate_codes_02
Revises: corporate_codes_01
Create Date: 2026-09-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'corporate_codes_02'
down_revision: Union[str, None] = 'corporate_codes_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('corporates', 'corporate_code', new_column_name='customer_code')


def downgrade() -> None:
    op.alter_column('corporates', 'customer_code', new_column_name='corporate_code')
