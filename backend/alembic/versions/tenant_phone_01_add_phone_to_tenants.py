"""An invoice letterhead needs a phone number to print.

`tenants` carried the whole rest of the letterhead — name, address, city, state,
pincode, country, PAN, GSTIN and a logo — but no telephone. A printed tax
invoice heads with the supplier's contact details, and the only number anywhere
near the workspace was `users.email`, which is a person's login, not the
business's line.

Free text and not one number: the reference invoice this was modelled on carries
two, stacked. Splitting them into columns would be inventing a structure nobody
asked for, so a newline-separated string is what the letterhead prints.

Revision ID: tenant_phone_01
Revises: billing_gst_split_01
"""
from alembic import op
import sqlalchemy as sa


revision = "tenant_phone_01"
down_revision = "billing_gst_split_01"
branch_labels = None
depends_on = None


# (column, type) pairs, so upgrade and downgrade cannot drift apart.
# 100 rather than corporates.phone's 50: two numbers and a separator do not fit
# in a field sized for one.
_COLUMNS = (
    ("phone", sa.String(length=100)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("tenants", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("tenants", name)
