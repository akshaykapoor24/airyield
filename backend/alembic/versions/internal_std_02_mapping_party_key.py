"""Remembered column mappings: who an Internal Statement was for

statement_column_mappings keeps the mapping a statement was saved with, keyed by the vendor
(agency_id / supplier_id) and the file's column layout (services/saved_mapping.py). Internal
Statement uses it too, and its statements are filed under a customer — a B2B agency, a
corporate, a direct customer — or under "All vendors", which no id column can hold:

* party_key — "agency:12", "corporate:5", "direct:3", "direct", "all-vendors"; NULL for the
              vendor-keyed types (Third Party GDS …), which are unchanged

Nothing is backfilled: no Internal Statement mapping was kept before.

Revision ID: internal_std_02
Revises: internal_std_01
Create Date: 2026-10-28 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'internal_std_02'
down_revision: Union[str, None] = 'internal_std_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('statement_column_mappings', sa.Column('party_key', sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column('statement_column_mappings', 'party_key')
