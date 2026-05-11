"""add source_type to uploaded_deals

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-04-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploaded_deals",
        sa.Column(
            "source_type",
            sa.String(length=20),
            nullable=False,
            server_default="upload",
        ),
    )


def downgrade() -> None:
    op.drop_column("uploaded_deals", "source_type")
