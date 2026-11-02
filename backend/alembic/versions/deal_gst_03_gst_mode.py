"""deal incentive GST mode: exclusive / inclusive (÷1.18) / less 18%

The yes/no gst_inclusive flag becomes deal_incentives.gst_mode, because vendors take
the GST out of an inclusive rate in two different ways and the deal has to say which
(the user's call, 2026-10-31 — set per deal, not per vendor):
  inclusive  the rate holds 18% GST, 18/118 of it comes off (Brightsun: × 0.8475)
  less_18    18% of the commission comes off (TripJack: × 0.82)
  exclusive  GST is on top; the rate is paid in full
Every gst_inclusive = true row becomes 'inclusive', false becomes 'exclusive'; each
ancillary sub-type's "gstInclusive" becomes "gstMode" the same way. New rows default to
'inclusive'.

Revision ID: deal_gst_03
Revises: deal_gst_02
Create Date: 2026-10-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'deal_gst_03'
down_revision: Union[str, None] = 'deal_gst_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rewrite_ancillary(new_value_sql: str) -> None:
    """Rewrite each ancillary sub-type object with `new_value_sql`, an expression over
    its value `e.value`. Rows with no ancillary (SQL NULL, JSON null, {}) are left alone."""
    op.execute(f"""
        UPDATE deal_incentives
        SET ancillary_items = (
            SELECT jsonb_object_agg(
                e.key,
                CASE WHEN jsonb_typeof(e.value) = 'object' THEN {new_value_sql} ELSE e.value END)
            FROM jsonb_each(ancillary_items) AS e
        )
        WHERE jsonb_typeof(ancillary_items) = 'object'
          AND ancillary_items <> '{{}}'::jsonb
    """)


def upgrade() -> None:
    op.add_column('deal_incentives', sa.Column(
        'gst_mode', sa.String(10), nullable=False, server_default='inclusive'))
    op.execute("UPDATE deal_incentives SET gst_mode = CASE WHEN gst_inclusive THEN 'inclusive' ELSE 'exclusive' END")
    _rewrite_ancillary("""(e.value - 'gstInclusive') || jsonb_build_object('gstMode',
        CASE WHEN e.value->>'gstInclusive' = 'false' THEN 'exclusive' ELSE 'inclusive' END)""")
    op.drop_column('deal_incentives', 'gst_inclusive')


def downgrade() -> None:
    op.add_column('deal_incentives', sa.Column(
        'gst_inclusive', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.execute("UPDATE deal_incentives SET gst_inclusive = (gst_mode <> 'exclusive')")
    _rewrite_ancillary("""(e.value - 'gstMode') || jsonb_build_object('gstInclusive',
        COALESCE(e.value->>'gstMode', 'inclusive') <> 'exclusive')""")
    op.drop_column('deal_incentives', 'gst_mode')
