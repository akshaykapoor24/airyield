"""Internal Statement: the date format each upload declares

* ticket_statements.date_formats / internal_ticket_statements.date_formats — the order the
  file's Ticket Date and Travel Date are written in, {field: "DMY" | "MDY" | "YMD"}
  (services/ticket_extraction.py DATE_FORMAT_FIELDS). The record of how the upload's dates
  were read, and what pre-fills the customer's next upload. Asked on Internal Statement only.
  Added to BOTH tables: the internal model is mapped from the customer table's own
  metadata (models/internal_ticket.py), so it expects every column the customer one has.
  Not backfilled: every statement before this was read day-first, and NULL says so.

Revision ID: ticket_date_formats_01
Revises: tp_gds_date_formats_01
Create Date: 2026-10-20 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'ticket_date_formats_01'
down_revision: Union[str, None] = 'tp_gds_date_formats_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATEMENTS = ('ticket_statements', 'internal_ticket_statements')


def upgrade() -> None:
    for table in _STATEMENTS:
        op.add_column(table, sa.Column('date_formats', JSONB(), nullable=True))


def downgrade() -> None:
    for table in _STATEMENTS:
        op.drop_column(table, 'date_formats')
