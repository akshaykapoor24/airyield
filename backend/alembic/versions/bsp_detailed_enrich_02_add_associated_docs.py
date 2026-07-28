"""Add bsp_statement_rows.associated_docs (structured continuation-line detail)

Captures the full detail of the BSP detailed-PDF continuation sub-lines that the
flat columns can't hold:
  * +RTDN related document: {doc, ref, indicator}   (ref = the 1230/0034 reference,
    indicator = "EX" exchange marker)
  * +TKTT conjunction tickets: [{doc, issue_date, cpui}, ...]

Shape: {"rtdn": {...}, "conjunctions": [...]}. Nullable — existing rows stay NULL
until re-parsed.

Revision ID: bsp_detailed_enrich_02
Revises: bsp_detailed_enrich_01
Create Date: 2026-07-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "bsp_detailed_enrich_02"
down_revision: Union[str, None] = "bsp_detailed_enrich_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bsp_statement_rows",
        sa.Column("associated_docs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bsp_statement_rows", "associated_docs")
