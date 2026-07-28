"""add direction to deals and deal_statements

inbound  = deal received (airline / big agency) — income you EARN
outbound = deal floated to a sub-agency — commission you PAY (supplier_name = whom)

Stored as String(10) to match the native_enum=False DealDirection column on the
models. All existing rows back-fill to 'inbound' via the server_default, so nothing
that exists today changes behaviour.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('deals', 'deal_statements'):
        op.add_column(table, sa.Column(
            'direction',
            sa.String(length=10),
            nullable=False,
            server_default='inbound',
        ))
        op.create_index(f'ix_{table}_direction', table, ['direction'])


def downgrade() -> None:
    for table in ('deals', 'deal_statements'):
        op.drop_index(f'ix_{table}_direction', table_name=table)
        op.drop_column(table, 'direction')
