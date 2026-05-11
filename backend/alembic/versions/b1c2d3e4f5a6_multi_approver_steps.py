"""add multi approver support for approval workflow steps

Revision ID: b1c2d3e4f5a6
Revises: a9b8c7d6e5f4
Create Date: 2026-04-21 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_workflow_step_approvers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_step_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_step_id"], ["approval_workflow_steps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_step_id", "user_id", name="uq_workflow_step_approver_user"),
    )
    op.create_index(
        "ix_approval_workflow_step_approvers_workflow_step_id",
        "approval_workflow_step_approvers",
        ["workflow_step_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_workflow_step_approvers_user_id",
        "approval_workflow_step_approvers",
        ["user_id"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO approval_workflow_step_approvers (workflow_step_id, user_id, created_at)
        SELECT id, approver_user_id, NOW()
        FROM approval_workflow_steps
        WHERE approver_user_id IS NOT NULL
        """
    )

    op.drop_index("ix_approval_workflow_steps_approver_user_id", table_name="approval_workflow_steps")
    op.drop_column("approval_workflow_steps", "approver_user_id")

    op.drop_constraint("uq_deal_approval_steps_order", "deal_approval_steps", type_="unique")
    op.create_unique_constraint(
        "uq_deal_approval_steps_order_user",
        "deal_approval_steps",
        ["deal_approval_id", "step_order", "assigned_user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_deal_approval_steps_order_user", "deal_approval_steps", type_="unique")
    op.create_unique_constraint("uq_deal_approval_steps_order", "deal_approval_steps", ["deal_approval_id", "step_order"])

    op.add_column("approval_workflow_steps", sa.Column("approver_user_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE approval_workflow_steps s
        SET approver_user_id = src.user_id
        FROM (
          SELECT workflow_step_id, MIN(user_id) AS user_id
          FROM approval_workflow_step_approvers
          GROUP BY workflow_step_id
        ) src
        WHERE s.id = src.workflow_step_id
        """
    )
    op.alter_column("approval_workflow_steps", "approver_user_id", nullable=False)
    op.create_foreign_key(
        None,
        "approval_workflow_steps",
        "users",
        ["approver_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_approval_workflow_steps_approver_user_id", "approval_workflow_steps", ["approver_user_id"], unique=False)

    op.drop_index("ix_approval_workflow_step_approvers_user_id", table_name="approval_workflow_step_approvers")
    op.drop_index("ix_approval_workflow_step_approvers_workflow_step_id", table_name="approval_workflow_step_approvers")
    op.drop_table("approval_workflow_step_approvers")
