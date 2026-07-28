"""Add corporates table and billings.corporate_id (corporate billing)

Corporate Billing mirrors Customer Billing for a separate directory of corporate
clients. Adds the `corporates` table (same shape as `customers`) and a nullable
`corporate_id` FK on `billings` so a billing can belong to a customer, an agency,
or a corporate. Existing billings are unaffected.

Revision ID: corporate_billing_01
Revises: agency_billing_01
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "corporate_billing_01"
down_revision: Union[str, None] = "agency_billing_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corporates",
        sa.Column("id",             sa.Integer(),      nullable=False),
        sa.Column("tenant_id",      sa.Integer(),      nullable=True),
        sa.Column("created_by_id",  sa.Integer(),      nullable=False),
        sa.Column("first_name",     sa.String(200),    nullable=False),
        sa.Column("last_name",      sa.String(200),    nullable=True),
        sa.Column("company",        sa.String(255),    nullable=True),
        sa.Column("title",          sa.String(100),    nullable=True),
        sa.Column("phone",          sa.String(50),     nullable=True),
        sa.Column("email",          sa.String(255),    nullable=True),
        sa.Column("gst_registered", sa.Boolean(),      nullable=False, server_default="false"),
        sa.Column("gst_no",         sa.String(30),     nullable=True),
        sa.Column("pan_no",         sa.String(20),     nullable=True),
        sa.Column("markup_type",    sa.String(20),     nullable=True),
        sa.Column("markup_value",   sa.Numeric(14, 2), nullable=True),
        sa.Column("billing_type",   sa.String(20),     nullable=True),
        sa.Column("is_active",      sa.Boolean(),      nullable=True),
        sa.Column("created_at",     sa.DateTime(),     nullable=True),
        sa.Column("updated_at",     sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"],     ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_corporates_tenant_id", "corporates", ["tenant_id"])
    op.create_index("ix_corporates_created_by_id", "corporates", ["created_by_id"])

    op.add_column("billings", sa.Column("corporate_id", sa.Integer(), nullable=True))
    op.create_index("ix_billings_corporate_id", "billings", ["corporate_id"])
    op.create_foreign_key(
        "fk_billings_corporate_id_corporates",
        "billings", "corporates",
        ["corporate_id"], ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_billings_corporate_id_corporates", "billings", type_="foreignkey")
    op.drop_index("ix_billings_corporate_id", table_name="billings")
    op.drop_column("billings", "corporate_id")

    op.drop_index("ix_corporates_created_by_id", table_name="corporates")
    op.drop_index("ix_corporates_tenant_id", table_name="corporates")
    op.drop_table("corporates")
