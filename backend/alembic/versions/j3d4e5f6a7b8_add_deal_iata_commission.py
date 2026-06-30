"""add deals.iata_commission

IATA commission (%) entered in the Create Deal "Airline Contract Details" form.
Stored as a string like the other commission columns (eco/peco/bus_commission).

Revision ID: j3d4e5f6a7b8
Revises: i2c3d4e5f6a7
Create Date: 2026-06-28 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j3d4e5f6a7b8'
down_revision: Union[str, None] = 'i2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("iata_commission", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "iata_commission")
