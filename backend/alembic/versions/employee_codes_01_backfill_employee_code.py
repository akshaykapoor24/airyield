"""Backfill customers.employee_code — every employee now has one

The column already exists (optional, unique per owner when set). It is now issued by
the system when not typed, so rows created without one get EMP-0001, EMP-0002 … per
owner (tenant_id + created_by_id) in creation order, skipping any code the owner
already uses by hand. Typed codes are left exactly as they are.

Downgrade is a no-op: a backfilled code cannot be told apart from one somebody typed,
and the column itself predates this revision.

Revision ID: employee_codes_01
Revises: corporate_codes_03
Create Date: 2026-10-09 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'employee_codes_01'
down_revision: Union[str, None] = 'corporate_codes_03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    used: dict[tuple, set[str]] = {}
    for tenant_id, owner_id, code in conn.execute(sa.text(
        "SELECT tenant_id, created_by_id, employee_code FROM customers WHERE employee_code IS NOT NULL"
    )).all():
        used.setdefault((tenant_id, owner_id), set()).add(code.upper())

    counters: dict[tuple, int] = {}
    for customer_id, tenant_id, owner_id in conn.execute(sa.text(
        "SELECT id, tenant_id, created_by_id FROM customers "
        "WHERE employee_code IS NULL ORDER BY tenant_id, created_by_id, id"
    )).all():
        key = (tenant_id, owner_id)
        taken = used.setdefault(key, set())
        n = counters.get(key, 0)
        while True:
            n += 1
            code = f"EMP-{n:04d}"
            if code not in taken:
                break
        counters[key] = n
        taken.add(code)
        conn.execute(
            sa.text("UPDATE customers SET employee_code = :c WHERE id = :i"),
            {"c": code, "i": customer_id},
        )


def downgrade() -> None:
    pass
