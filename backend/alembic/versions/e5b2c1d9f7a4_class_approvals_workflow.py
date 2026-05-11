"""add class approvals workflow table

Revision ID: e5b2c1d9f7a4
Revises: d4a7b9c2e1f0
Create Date: 2026-04-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5b2c1d9f7a4"
down_revision: Union[str, None] = "d4a7b9c2e1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "class_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("airline_name", sa.String(length=255), nullable=False),
        sa.Column("class_type", sa.String(length=50), nullable=False),
        sa.Column("class_code", sa.String(length=10), nullable=False),
        sa.Column("airline_type", sa.String(length=20), nullable=True),
        sa.Column("class_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("submitted_by_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("class_approvals")
