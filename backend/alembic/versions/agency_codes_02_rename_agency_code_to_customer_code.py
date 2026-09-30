"""Rename agencies.agency_code to customer_code

The Agency Master's "Agency Code" is now called "Customer Code" on the form, the template
and the agency screens, so the column carries the same name — matching
corporates.customer_code. A rename, not a drop + add: every value already entered is kept.

Revision ID: agency_codes_02
Revises: corporate_codes_02
Create Date: 2026-09-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'agency_codes_02'
down_revision: Union[str, None] = 'corporate_codes_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('agencies', 'agency_code', new_column_name='customer_code')


def downgrade() -> None:
    op.alter_column('agencies', 'customer_code', new_column_name='agency_code')
