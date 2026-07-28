"""Add lcc_detailed_batch.expected_rows (user-declared expected record count)

Lets the uploader enter how many records they expect in the file; after ingestion the
UI compares it against the rows actually saved so the user can confirm nothing was
dropped. Nullable — optional, unset on existing/older uploads.

Revision ID: lcc_detailed_expected_01
Revises: bsp_detailed_enrich_03
Create Date: 2026-07-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "lcc_detailed_expected_01"
down_revision: Union[str, None] = "bsp_detailed_enrich_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lcc_detailed_batch", sa.Column("expected_rows", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("lcc_detailed_batch", "expected_rows")
