"""add supplier directory / member-list fields

Adds the member-directory columns (from the supplier master XLS) to both the
`suppliers` and `supplier_approvals` tables. Purely additive — existing columns
(esp. `name` / `code`) are untouched so name-reading queries and FKs keep working.

Revision ID: supp_directory_01
Revises: cust_stmt_01
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'supp_directory_01'
down_revision = 'cust_stmt_01'
branch_labels = None
depends_on = None


# (column_name, sqlalchemy type) for the 15 new directory fields
_COLUMNS = [
    ('region_chapter',      sa.Text()),
    ('membership_category', sa.String(100)),
    ('address_1',           sa.Text()),
    ('address_2',           sa.Text()),
    ('address_3',           sa.Text()),
    ('city',                sa.String(120)),
    ('pincode',             sa.String(20)),
    ('telephone_mobile',    sa.Text()),
    ('website',             sa.String(255)),
    ('email_address',       sa.Text()),
    ('alternate_email_id',  sa.Text()),
    ('accounts_email',      sa.Text()),
    ('fax_no',              sa.String(100)),
    ('representative_1',    sa.String(255)),
    ('representative_2',    sa.String(255)),
]

_TABLES = ('suppliers', 'supplier_approvals')


def upgrade() -> None:
    for table in _TABLES:
        for name, col_type in _COLUMNS:
            op.add_column(table, sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    for table in reversed(_TABLES):
        for name, _ in reversed(_COLUMNS):
            op.drop_column(table, name)
