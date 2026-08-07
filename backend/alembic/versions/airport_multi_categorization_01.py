"""widen airport categorization for multi-group selection

An airport can belong to several country groups at once. The value is stored
slash-joined ("MEAI/SAARC"), which the exclusion evaluator already splits — but
selecting every group yields ~72 characters, so String(50) truncates. Widen both
the master table and the approval queue to 255.

Revision ID: airport_multi_categorization_01
Revises: series_contract_01
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'airport_multi_categorization_01'
down_revision: Union[str, None] = 'series_contract_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'airports', 'categorization',
        existing_type=sa.String(50), type_=sa.String(255),
        existing_nullable=True,
    )
    op.alter_column(
        'airport_approvals', 'categorization',
        existing_type=sa.String(50), type_=sa.String(255),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Narrowing would truncate any multi-group value written since the upgrade,
    # so trim to 50 explicitly first rather than letting the DB error or cut.
    op.execute("UPDATE airports SET categorization = LEFT(categorization, 50) "
               "WHERE categorization IS NOT NULL AND LENGTH(categorization) > 50")
    op.execute("UPDATE airport_approvals SET categorization = LEFT(categorization, 50) "
               "WHERE categorization IS NOT NULL AND LENGTH(categorization) > 50")
    op.alter_column(
        'airport_approvals', 'categorization',
        existing_type=sa.String(255), type_=sa.String(50),
        existing_nullable=True,
    )
    op.alter_column(
        'airports', 'categorization',
        existing_type=sa.String(255), type_=sa.String(50),
        existing_nullable=True,
    )
