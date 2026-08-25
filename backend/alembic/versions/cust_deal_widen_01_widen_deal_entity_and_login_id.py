"""Widen deals.entity and deals.login_id to fit what the form already offers

Both columns are too narrow for values the Create Deal form has been putting in
them since B2B Standard deals gained the agency chain:

  * `deals.entity` is VARCHAR(50), but for a B2B Standard deal the form offers
    `agency_entities.name` — VARCHAR(255). A long agency entity name raises
    StringDataRightTruncation on save.

  * `deals.login_id` is VARCHAR(100), and the form writes ", ".join(loginIds)
    into it (a back-compat display copy of the `login_ids` JSONB array). Each
    individual `agency_login_ids.login_id` is itself VARCHAR(100), so selecting
    two credentials already overflows.

Widening only — no data is rewritten and no behaviour changes. The downgrade
truncates, so it is guarded: it will fail loudly rather than silently cutting a
value in half.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "cust_deal_widen_01"
down_revision: Union[str, None] = "agency_channel_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "deals", "entity",
        existing_type=sa.String(50),
        type_=sa.String(255),
        existing_nullable=True,
    )
    op.alter_column(
        "deals", "login_id",
        existing_type=sa.String(100),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Narrowing would truncate. Refuse rather than corrupt.
    conn = op.get_bind()
    over = conn.execute(sa.text(
        "SELECT count(*) FROM deals "
        "WHERE length(entity) > 50 OR length(login_id) > 100"
    )).scalar() or 0
    if over:
        raise RuntimeError(
            f"{over} deal(s) have an entity or login_id longer than the old limits. "
            "Shorten them before downgrading, or the values would be truncated."
        )
    op.alter_column(
        "deals", "login_id",
        existing_type=sa.Text(),
        type_=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "deals", "entity",
        existing_type=sa.String(255),
        type_=sa.String(50),
        existing_nullable=True,
    )
