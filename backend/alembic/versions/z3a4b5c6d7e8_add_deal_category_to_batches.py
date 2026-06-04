"""Add deal_category to deal_batches

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'z3a4b5c6d7e8'
down_revision: Union[str, None] = 'y2z3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('deal_batches', sa.Column(
        'deal_category',
        sa.String(length=50),
        nullable=False,
        server_default='enterprise',
    ))


def downgrade() -> None:
    op.drop_column('deal_batches', 'deal_category')
