"""Add agencies.agency_code — the system-issued agency identifier

Distinct from customer_code / account_code (the user's references to other systems).
Issued AG-0001, AG-0002 … per user unless typed in by hand; the GDS and LCC rows of
one vendor branch share a code. Existing rows are backfilled in creation order per
user, siblings sharing, so no agency is left without one.

Revision ID: agency_codes_03
Revises: mail_intake_04
Create Date: 2026-10-09 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'agency_codes_03'
down_revision: Union[str, None] = 'mail_intake_04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agencies', sa.Column('agency_code', sa.String(30), nullable=True))
    op.create_index('ix_agencies_agency_code', 'agencies', ['agency_code'])

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, user_id, name, branch_code FROM agencies ORDER BY user_id, id"
    )).all()
    counters: dict[int, int] = {}
    issued: dict[tuple[int, str, str], str] = {}
    for agency_id, user_id, name, branch in rows:
        key = (user_id, (name or "").strip().lower(), (branch or "").strip().lower())
        code = issued.get(key)
        if code is None:
            counters[user_id] = counters.get(user_id, 0) + 1
            code = issued[key] = f"AG-{counters[user_id]:04d}"
        conn.execute(
            sa.text("UPDATE agencies SET agency_code = :c WHERE id = :i"),
            {"c": code, "i": agency_id},
        )

    op.create_unique_constraint(
        'uq_agencies_user_code_channel', 'agencies', ['user_id', 'agency_code', 'channels'],
    )


def downgrade() -> None:
    op.drop_constraint('uq_agencies_user_code_channel', 'agencies', type_='unique')
    op.drop_index('ix_agencies_agency_code', table_name='agencies')
    op.drop_column('agencies', 'agency_code')
