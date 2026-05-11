"""airline class master table

Revision ID: c3f1f5d9a8a2
Revises: b3e1c2d4a5f6
Create Date: 2026-04-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3f1f5d9a8a2"
down_revision: Union[str, None] = "b3e1c2d4a5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "airline_class_masters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("airline_name", sa.String(length=255), nullable=False),
        sa.Column("class_type", sa.String(length=50), nullable=False),
        sa.Column("class_code", sa.String(length=10), nullable=False),
        sa.Column("airline_type", sa.String(length=20), nullable=True),
        sa.Column("class_note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_unique_constraint(
        "uq_airline_class_masters_airline_class",
        "airline_class_masters",
        ["airline_name", "class_type", "class_code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_airline_class_masters_airline_class",
        "airline_class_masters",
        type_="unique",
    )
    op.drop_table("airline_class_masters")

