"""add request_type and target_id to approval tables

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-04-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h2i3j4k5l6m7"
down_revision: Union[str, None] = "g1h2i3j4k5l6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("airport_approvals", sa.Column("request_type", sa.String(10), nullable=False, server_default="new"))
    op.add_column("airport_approvals", sa.Column("target_airport_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_airport_approvals_target_airport",
        "airport_approvals", "airports",
        ["target_airport_id"], ["id"],
        ondelete="SET NULL",
    )

    op.add_column("airline_approvals", sa.Column("request_type", sa.String(10), nullable=False, server_default="new"))
    op.add_column("airline_approvals", sa.Column("target_airline_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_airline_approvals_target_airline",
        "airline_approvals", "airlines",
        ["target_airline_id"], ["id"],
        ondelete="SET NULL",
    )

    op.add_column("class_approvals", sa.Column("request_type", sa.String(10), nullable=False, server_default="new"))
    op.add_column("class_approvals", sa.Column("target_class_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_class_approvals_target_class",
        "class_approvals", "airline_class_masters",
        ["target_class_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_class_approvals_target_class", "class_approvals", type_="foreignkey")
    op.drop_column("class_approvals", "target_class_id")
    op.drop_column("class_approvals", "request_type")

    op.drop_constraint("fk_airline_approvals_target_airline", "airline_approvals", type_="foreignkey")
    op.drop_column("airline_approvals", "target_airline_id")
    op.drop_column("airline_approvals", "request_type")

    op.drop_constraint("fk_airport_approvals_target_airport", "airport_approvals", type_="foreignkey")
    op.drop_column("airport_approvals", "target_airport_id")
    op.drop_column("airport_approvals", "request_type")
