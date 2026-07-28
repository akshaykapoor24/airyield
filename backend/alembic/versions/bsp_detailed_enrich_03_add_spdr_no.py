"""Add bsp_statement_rows.spdr_no (CANX -> parent SPDR document-number link)

SPDR rows carry a bulk cancellation charge that is distributed across the paired
zero-amount CANX rows (300 Intl / 100 Dom each). This column stamps each filled
CANX row with the document number of the SPDR it was derived from, so a CANX is
traceable back to its parent SPDR. Nullable — set only on CANX rows during the
SPDR->CANX distribution step; existing rows stay NULL until re-parsed.

Revision ID: bsp_detailed_enrich_03
Revises: bsp_detailed_enrich_02
Create Date: 2026-07-24 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "bsp_detailed_enrich_03"
down_revision: Union[str, None] = "bsp_detailed_enrich_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bsp_statement_rows", sa.Column("spdr_no", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("bsp_statement_rows", "spdr_no")
