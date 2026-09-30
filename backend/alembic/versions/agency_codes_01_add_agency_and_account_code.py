"""Agency Code and Account Code on an agency

The user's own references for an Agency Master row, entered on the Add / Edit Agency form
and the agency template: `agency_code` (their code for the vendor) and `account_code` (the
ledger it is booked under). Both optional.

NOT IDENTIFIERS: a vendor branch is one row per channel (GDS, LCC) and both rows usually
carry the same codes, so there is no unique index. Nothing is backfilled.

Revision ID: agency_codes_01
Revises: account_code_01
Create Date: 2026-09-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'agency_codes_01'
down_revision: Union[str, None] = 'account_code_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agencies', sa.Column('agency_code', sa.String(length=50), nullable=True))
    op.add_column('agencies', sa.Column('account_code', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('agencies', 'account_code')
    op.drop_column('agencies', 'agency_code')
