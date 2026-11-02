"""every deal incentive GST-inclusive

The user's call (2026-10-31): deals are GST-inclusive by default, and every deal saved
before the toggle existed is moved to inclusive too — deal_gst_01 had left them all
exclusive.
  - deal_incentives.gst_inclusive → true on every row, and its server default → true.
  - deal_incentives.ancillary_items: each sub-type object gets "gstInclusive": true.
    Rows holding SQL NULL or JSON null (no ancillary) are left as they are.

Downgrade puts the server default back to false and every flag back to false — the
state deal_gst_01 left. A choice made through the toggle in between is not restored.

Revision ID: deal_gst_02
Revises: deal_gst_01
Create Date: 2026-10-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'deal_gst_02'
down_revision: Union[str, None] = 'deal_gst_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _set_ancillary_flag(value: str) -> None:
    op.execute(f"""
        UPDATE deal_incentives
        SET ancillary_items = (
            SELECT jsonb_object_agg(
                e.key,
                CASE WHEN jsonb_typeof(e.value) = 'object'
                     THEN e.value || '{{"gstInclusive": {value}}}'::jsonb
                     ELSE e.value END)
            FROM jsonb_each(ancillary_items) AS e
        )
        WHERE jsonb_typeof(ancillary_items) = 'object'
          AND ancillary_items <> '{{}}'::jsonb
    """)


def upgrade() -> None:
    op.alter_column('deal_incentives', 'gst_inclusive', server_default=sa.true())
    op.execute("UPDATE deal_incentives SET gst_inclusive = true WHERE gst_inclusive = false")
    _set_ancillary_flag("true")


def downgrade() -> None:
    _set_ancillary_flag("false")
    op.execute("UPDATE deal_incentives SET gst_inclusive = false WHERE gst_inclusive = true")
    op.alter_column('deal_incentives', 'gst_inclusive', server_default=sa.false())
