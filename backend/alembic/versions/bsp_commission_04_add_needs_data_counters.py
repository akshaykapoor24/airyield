"""Count the two commission outcomes that had nowhere to go

`refresh_totals` bucketed rows as matched / unmatched / excluded / skipped. Two
populations fell through it:

  pending    — rows no run has touched. A statement whose whole-statement run had
               never happened reported 8 matched and 0 of everything else across
               15,204 rows, which reads as "calculated, poor result" rather than
               "never calculated". The 15,196 untouched rows were invisible.

  needs_data — a deal matched, but it pays only on a cabin class / travel window
               / route that a BSP settlement row does not print. Previously such a
               row was paid on a criterion nobody checked; it is now withheld and
               has to be counted somewhere the user can see it.

Additive, both defaulting to 0. Existing statements report 0 for both until their
next run, which recomputes every counter from the rows anyway.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "bsp_commission_04"
down_revision: Union[str, None] = "agency_master_request_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bsp_statements",
        sa.Column("commission_needs_data_rows", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "bsp_statements",
        sa.Column("commission_pending_rows", sa.Integer(), nullable=False, server_default="0"),
    )
    # Every row parsed before this migration has never been through a run whose
    # engine knew about `needs_data`, so seed the pending count from the rows
    # rather than leaving a zero that claims the statement is fully calculated.
    op.execute("""
        UPDATE bsp_statements s
           SET commission_pending_rows = (
                 SELECT count(*) FROM bsp_statement_rows r
                  WHERE r.statement_id = s.batch_id
                    AND r.commission_status = 'pending'
               )
    """)


def downgrade() -> None:
    op.drop_column("bsp_statements", "commission_pending_rows")
    op.drop_column("bsp_statements", "commission_needs_data_rows")
