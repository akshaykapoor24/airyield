"""deal incentive GST-inclusive flag

Adds deal_incentives.gst_inclusive: whether the incentive's rate / amount as agreed
already contains 18% GST (a vendor then pays it out net of GST — Brightsun prints
commission × 0.8475) or GST is charged on top of it. Set with the GST toggle beside the
incentive value on Create Deal.

NOT NULL with a false default, so existing deals read as GST-exclusive — what every
deal was treated as before the toggle existed.

Revision ID: deal_gst_01
Revises: internal_std_05
Create Date: 2026-10-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'deal_gst_01'
down_revision: Union[str, None] = 'internal_std_05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('deal_incentives', sa.Column(
        'gst_inclusive', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('deal_incentives', 'gst_inclusive')
