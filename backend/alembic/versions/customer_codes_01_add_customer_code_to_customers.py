"""Customer Code on an employee

An Employee Master row now carries a Customer Code beside its Account Code. Both are
inherited from the employee's corporate (services/party_inherit): picking a company on the
form fills them from that corporate's Corporate Master entry, and the import and re-link
do the same for blank cells. Optional and not unique, like corporates.customer_code.

Nothing is backfilled here. "Link employees to corporates" (POST /customers/relink-corporates)
fills the blank codes of employees already on file, the same way it fills their other terms.

Revision ID: customer_codes_01
Revises: agency_codes_02
Create Date: 2026-09-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'customer_codes_01'
down_revision: Union[str, None] = 'agency_codes_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('customer_code', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('customers', 'customer_code')
