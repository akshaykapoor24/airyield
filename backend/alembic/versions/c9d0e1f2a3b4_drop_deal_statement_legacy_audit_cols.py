"""drop legacy audit columns from deal_statements

Removes the migration-audit columns that pointed at the now-removed legacy deal
tables. Both are 100% NULL and unreferenced in code:
    legacy_table, legacy_id

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('deal_statements', 'legacy_table')
    op.drop_column('deal_statements', 'legacy_id')


def downgrade() -> None:
    op.add_column('deal_statements', sa.Column('legacy_id', sa.BigInteger(), nullable=True))
    op.add_column('deal_statements', sa.Column('legacy_table', sa.String(length=50), nullable=True))
