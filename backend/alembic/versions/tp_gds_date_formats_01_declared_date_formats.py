"""Third Party GDS: the date format each upload declares

* third_party_statements.date_formats — the order the uploader declared each date column
  of the file is written in, {field: "DMY" | "MDY" | "YMD"} (Booked Date and Date of
  Travel for Third Party GDS — statement_spec.date_format_fields). The record of how the
  upload's dates were read, and what pre-fills the agency's next upload.
  Not backfilled: every upload before this was read day-first, and NULL says so.

Revision ID: tp_gds_date_formats_01
Revises: ticket_payable_01
Create Date: 2026-10-20 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'tp_gds_date_formats_01'
down_revision: Union[str, None] = 'ticket_payable_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('third_party_statements', sa.Column('date_formats', JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('third_party_statements', 'date_formats')
