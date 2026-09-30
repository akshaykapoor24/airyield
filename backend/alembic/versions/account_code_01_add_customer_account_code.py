"""Account Code on an employee (customers)

The ledger / account code a person is booked under in the customer's own accounts, entered
on Employee Master next to Employee Code. Optional.

NOT AN IDENTIFIER, unlike employee_code: several people can be booked to one account, so
there is no unique index and party_dedupe ignores it. Nothing is backfilled.

Revision ID: account_code_01
Revises: user_verification_01
Create Date: 2026-09-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'account_code_01'
down_revision: Union[str, None] = 'user_verification_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('account_code', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('customers', 'account_code')
