"""Add billings.agency_id and make customer_id nullable (agency billing)

A billing now belongs to EITHER a customer or an agency. Adds a nullable
`agency_id` FK to `agencies` (CASCADE) and relaxes `customer_id` to nullable so
agency billings (customer_id NULL) can be stored in the same table. Existing
customer billings are unaffected.

Revision ID: agency_billing_01
Revises: lcc_detailed_expected_01
Create Date: 2026-07-27 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "agency_billing_01"
down_revision: Union[str, None] = "lcc_detailed_expected_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("billings", sa.Column("agency_id", sa.Integer(), nullable=True))
    op.create_index("ix_billings_agency_id", "billings", ["agency_id"])
    op.create_foreign_key(
        "fk_billings_agency_id_agencies",
        "billings", "agencies",
        ["agency_id"], ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("billings", "customer_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("billings", "customer_id", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("fk_billings_agency_id_agencies", "billings", type_="foreignkey")
    op.drop_index("ix_billings_agency_id", table_name="billings")
    op.drop_column("billings", "agency_id")
