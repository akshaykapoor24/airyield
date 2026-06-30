"""tenant_type + pan/gst on tenants, nullable domain

Adds account-type support to tenants so signup can be either:
  - corporate  (work-email domain → company tenant, unique domain), or
  - individual (private single-person tenant, domain = NULL).

Also adds PAN/GST columns (the tenant is the billing/legal entity).

Revision ID: f9a1b2c3d4e5
Revises: e7f8a9b0c1d2
Create Date: 2026-06-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9a1b2c3d4e5'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # tenant_type: VARCHAR (native_enum=False stores the enum MEMBER NAME, like
    # users.role). server_default backfills existing rows so the NOT NULL add
    # succeeds; the name 'CORPORATE' matches what the ORM persists/reads.
    op.add_column(
        "tenants",
        sa.Column("tenant_type", sa.String(length=20), nullable=False, server_default="CORPORATE"),
    )
    op.add_column("tenants", sa.Column("pan_number", sa.String(length=20), nullable=True))
    op.add_column("tenants", sa.Column("gst_number", sa.String(length=20), nullable=True))

    # individual tenants have no shared company domain → allow NULL. The existing
    # unique constraint (tenants_domain_key, NULLS DISTINCT) permits many NULLs.
    op.alter_column("tenants", "domain", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # NOTE: fails if any individual tenants (domain IS NULL) exist — backfill/remove first.
    op.alter_column("tenants", "domain", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("tenants", "gst_number")
    op.drop_column("tenants", "pan_number")
    op.drop_column("tenants", "tenant_type")
