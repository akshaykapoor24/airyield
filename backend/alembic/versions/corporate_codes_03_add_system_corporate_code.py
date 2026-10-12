"""Add corporates.corporate_code — the system-issued corporate identifier

Distinct from customer_code / account_code (the user's references to other systems).
Issued CO-0001, CO-0002 … per owner (tenant_id + created_by_id) unless typed in by
hand. Existing rows are backfilled in creation order per owner, so none is left
without one.

Revision ID: corporate_codes_03
Revises: agency_codes_03
Create Date: 2026-10-09 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'corporate_codes_03'
down_revision: Union[str, None] = 'agency_codes_03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('corporates', sa.Column('corporate_code', sa.String(30), nullable=True))
    op.create_index('ix_corporates_corporate_code', 'corporates', ['corporate_code'])

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, tenant_id, created_by_id FROM corporates ORDER BY tenant_id, created_by_id, id"
    )).all()
    counters: dict[tuple, int] = {}
    for corporate_id, tenant_id, owner_id in rows:
        key = (tenant_id, owner_id)
        counters[key] = counters.get(key, 0) + 1
        conn.execute(
            sa.text("UPDATE corporates SET corporate_code = :c WHERE id = :i"),
            {"c": f"CO-{counters[key]:04d}", "i": corporate_id},
        )

    op.create_unique_constraint(
        'uq_corporates_owner_code', 'corporates', ['tenant_id', 'created_by_id', 'corporate_code'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_corporates_owner_code', 'corporates', type_='unique')
    op.drop_index('ix_corporates_corporate_code', table_name='corporates')
    op.drop_column('corporates', 'corporate_code')
