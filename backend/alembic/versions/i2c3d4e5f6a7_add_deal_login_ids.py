"""add deals.login_ids (multiple login ids per deal)

The Create Deal "Airline Contract Details" form now lets users select multiple
Login IDs / IATA numbers (from the User Master). They're persisted as a JSON
array; the existing single-string login_id column keeps a joined display value
for backward compatibility.

Revision ID: i2c3d4e5f6a7
Revises: h1b2c3d4e5f6
Create Date: 2026-06-28 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'i2c3d4e5f6a7'
down_revision: Union[str, None] = 'h1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("login_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "login_ids")
