"""store inclusions/exclusions on uploaded deals

Revision ID: f1a2b3c4d5e6
Revises: e5b2c1d9f7a4
Create Date: 2026-04-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e5b2c1d9f7a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("uploaded_deals", sa.Column("incl_excl_types", sa.JSON(), nullable=True))
    op.add_column("uploaded_deals", sa.Column("incl_excl_data", sa.JSON(), nullable=True))
    op.add_column("uploaded_deals", sa.Column("vice_versa", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("uploaded_deals", "vice_versa")
    op.drop_column("uploaded_deals", "incl_excl_data")
    op.drop_column("uploaded_deals", "incl_excl_types")
