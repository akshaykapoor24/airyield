"""drop unused LCC commission columns from deals

Removes six per-airline LCC columns from the deals table that are 100% NULL and
no longer persisted (the upload-confirm handler no longer writes them). The deal
extraction pipeline still parses these into the intermediate ExtractedRow, but
they are not stored on the deal:
    variant, eco_commission, peco_commission, bus_commission, base_type, valid_on

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLS = [
    ('variant',         sa.String(length=100)),
    ('eco_commission',  sa.String(length=50)),
    ('peco_commission', sa.String(length=50)),
    ('bus_commission',  sa.String(length=50)),
    ('base_type',       sa.String(length=20)),
    ('valid_on',        sa.String(length=20)),
]


def upgrade() -> None:
    for name, _ in _COLS:
        op.drop_column('deals', name)


def downgrade() -> None:
    for name, coltype in _COLS:
        op.add_column('deals', sa.Column(name, coltype, nullable=True))
