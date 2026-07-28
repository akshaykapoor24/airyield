"""deal travel-date + date-wise slab columns

Adds the date columns that B2B Standard deals need for matching:
  - deal_incentives.travel_valid_from / travel_valid_to
      Per-incentive Travel Date window. When both set, a ticket matches the
      incentive only if its TRAVEL/departure date falls within.
  - deal_incentive_slabs.valid_from / valid_to
      Date-wise slab window, replacing the Quarterly/Half-Yearly frequency
      qualifier for the band's period.

All nullable so existing rows are unaffected (NULL ⇒ no travel filter / slab
stays frequency-based).

Revision ID: e5f6a7b8c9d0
Revises: dd44ee55ff66
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'dd44ee55ff66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('deal_incentives', sa.Column('travel_valid_from', sa.Date(), nullable=True))
    op.add_column('deal_incentives', sa.Column('travel_valid_to',   sa.Date(), nullable=True))
    op.add_column('deal_incentive_slabs', sa.Column('valid_from', sa.Date(), nullable=True))
    op.add_column('deal_incentive_slabs', sa.Column('valid_to',   sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('deal_incentive_slabs', 'valid_to')
    op.drop_column('deal_incentive_slabs', 'valid_from')
    op.drop_column('deal_incentives', 'travel_valid_to')
    op.drop_column('deal_incentives', 'travel_valid_from')
