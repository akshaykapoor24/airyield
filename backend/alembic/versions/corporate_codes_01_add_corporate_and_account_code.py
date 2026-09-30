"""Corporate Code and Account Code on a corporate

The user's own references for a Corporate Master row, entered on the Add / Edit Corporate
form and the corporate template: `corporate_code` (their code for the corporate) and
`account_code` (the ledger it is booked under). Both optional, neither unique — `company`
is what identifies a corporate. Nothing is backfilled.

Revision ID: corporate_codes_01
Revises: agency_codes_01
Create Date: 2026-09-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'corporate_codes_01'
down_revision: Union[str, None] = 'agency_codes_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('corporates', sa.Column('corporate_code', sa.String(length=50), nullable=True))
    op.add_column('corporates', sa.Column('account_code', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('corporates', 'account_code')
    op.drop_column('corporates', 'corporate_code')
