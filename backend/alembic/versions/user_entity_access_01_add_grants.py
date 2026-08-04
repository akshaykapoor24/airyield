"""Assign an admin's entities to the team members they add

`user_entities` rows are private to the person who created them (the Super Admin,
during onboarding). Adding a team member under the same tenant now lets the admin
pick which of those entities the member works on — that grant lives here, so the
entity stays owned by one user while access to it is many-to-many.

Revision ID: user_entity_access_01
Revises: user_entity_tax_01
Create Date: 2026-07-29 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "user_entity_access_01"
down_revision: Union[str, None] = "user_entity_tax_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_entity_access",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("user_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "entity_id", name="uq_user_entity_access_user_entity"),
    )
    op.create_index("ix_user_entity_access_user_id", "user_entity_access", ["user_id"])
    op.create_index("ix_user_entity_access_entity_id", "user_entity_access", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_user_entity_access_entity_id", table_name="user_entity_access")
    op.drop_index("ix_user_entity_access_user_id", table_name="user_entity_access")
    op.drop_table("user_entity_access")
