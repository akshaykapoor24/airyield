"""Add deal_category to approval_workflows

Revision ID: a1b2c3d4e5f7
Revises: z3a4b5c6d7e8
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'z3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('approval_workflows', sa.Column(
        'deal_category',
        sa.String(length=50),
        nullable=False,
        server_default='enterprise',
    ))


def downgrade() -> None:
    op.drop_column('approval_workflows', 'deal_category')
