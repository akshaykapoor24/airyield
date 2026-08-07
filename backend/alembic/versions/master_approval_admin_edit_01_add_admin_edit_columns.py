"""record platform-admin edits on master approval requests

A platform admin can now correct a pending System Master request (supplier,
airline, airport, class/RBD) before approving it. The approve endpoints already
copy the approval row onto the master field-by-field, so the correction lands
with no change to them — but the submitter must be able to see what was altered.

`original_payload` holds a JSONB snapshot of the request's business columns as
the submitter left them. It is written lazily, on the first admin edit only, so
NULL means "no admin changed anything" — which doubles as the flag saying there
is nothing extra to show, and means the requests already sitting in the queue
need no backfill. A second edit never overwrites it, so the submitter always
diffs against their own values rather than an intermediate admin draft.

Revision ID: master_approval_admin_edit_01
Revises: airport_multi_categorization_01
Create Date: 2026-08-06 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "master_approval_admin_edit_01"
down_revision: Union[str, None] = "airport_multi_categorization_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All four master queues share the same workflow block, so they get the same
# three columns. Order is fixed so upgrade/downgrade mirror each other.
_TABLES = (
    "airport_approvals",
    "airline_approvals",
    "class_approvals",
    "supplier_approvals",
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("original_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
        op.add_column(table, sa.Column("edited_by_id", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("edited_at", sa.DateTime(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_edited_by",
            table, "users",
            ["edited_by_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_constraint(f"fk_{table}_edited_by", table, type_="foreignkey")
        op.drop_column(table, "edited_at")
        op.drop_column(table, "edited_by_id")
        # Dropping this discards the record of what each submitter originally
        # sent; there is nowhere else to move it, so the loss is intentional.
        op.drop_column(table, "original_payload")
