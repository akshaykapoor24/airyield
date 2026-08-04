"""Heartbeat for a BSP commission run, so a lost run can be recovered

Without one, a run that never reaches a worker (broker down, task dropped, worker
killed mid-job) stays 'queued'/'processing' forever: the UI polls indefinitely and
the Run button can never be pressed again. The heartbeat is stamped when the run
is queued and refreshed on every progress flush, so a slow-but-alive run is
distinguishable from a dead one.

Revision ID: bsp_commission_02
Revises: bsp_commission_01
Create Date: 2026-07-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "bsp_commission_02"
down_revision: Union[str, None] = "bsp_commission_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bsp_statements", sa.Column("commission_heartbeat_at", sa.DateTime(), nullable=True))
    # Any run already wedged in queued/processing predates this column and has no
    # worker behind it — release it so the UI is usable again.
    op.execute(
        "UPDATE bsp_statements SET commission_status = 'idle' "
        "WHERE commission_status IN ('queued', 'processing')"
    )


def downgrade() -> None:
    op.drop_column("bsp_statements", "commission_heartbeat_at")
