"""normalize tenant_type to enum member names

The previous migration (f9a1b2c3d4e5) backfilled tenants.tenant_type with the
lowercase enum *value* ('corporate'), but SAEnum(native_enum=False) stores and
looks up by the enum *member name* ('CORPORATE'/'INDIVIDUAL') — same as
users.role. Reading the lowercase rows raised LookupError. This migration
normalizes existing data to member names and drops the server_default (the ORM
supplies the value on insert, like users.role).

Revision ID: g0a1b2c3d4e5
Revises: f9a1b2c3d4e5
Create Date: 2026-06-28 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'g0a1b2c3d4e5'
down_revision: Union[str, None] = 'f9a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE tenants SET tenant_type = 'CORPORATE'  WHERE tenant_type = 'corporate'")
    op.execute("UPDATE tenants SET tenant_type = 'INDIVIDUAL' WHERE tenant_type = 'individual'")
    # ORM provides the value on insert (matches users.role) — no server default needed
    op.alter_column("tenants", "tenant_type", server_default=None)


def downgrade() -> None:
    op.alter_column("tenants", "tenant_type", server_default="corporate")
    op.execute("UPDATE tenants SET tenant_type = 'corporate'  WHERE tenant_type = 'CORPORATE'")
    op.execute("UPDATE tenants SET tenant_type = 'individual' WHERE tenant_type = 'INDIVIDUAL'")
