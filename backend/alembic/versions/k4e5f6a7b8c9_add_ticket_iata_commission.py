"""add uploaded_tickets.iata_commission

Stores the IATA commission AMOUNT computed during a ticket Run/Run-All:
the matched deal's IATA commission % applied to the ticket's sell fare.
0 when there's no matched deal or no commission.

Revision ID: k4e5f6a7b8c9
Revises: j3d4e5f6a7b8
Create Date: 2026-06-28 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k4e5f6a7b8c9'
down_revision: Union[str, None] = 'j3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("uploaded_tickets", sa.Column("iata_commission", sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("uploaded_tickets", "iata_commission")
