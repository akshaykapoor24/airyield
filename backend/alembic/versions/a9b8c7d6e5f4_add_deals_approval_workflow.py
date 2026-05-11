"""add tenant deals approval workflow tables

Revision ID: a9b8c7d6e5f4
Revises: f7a8b9c0d1e2
Create Date: 2026-04-20 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_workflows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(length=7), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "module", name="uq_approval_workflows_tenant_module"),
    )
    op.create_index("ix_approval_workflows_tenant_id", "approval_workflows", ["tenant_id"], unique=False)

    op.create_table(
        "approval_workflow_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("approver_user_id", sa.Integer(), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approver_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_id"], ["approval_workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "step_order", name="uq_approval_workflow_steps_order"),
    )
    op.create_index("ix_approval_workflow_steps_workflow_id", "approval_workflow_steps", ["workflow_id"], unique=False)
    op.create_index("ix_approval_workflow_steps_approver_user_id", "approval_workflow_steps", ["approver_user_id"], unique=False)

    op.create_table(
        "deal_approvals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("current_step_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="pending"),
        sa.Column("submitted_by_id", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["approval_workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deal_id"),
    )
    op.create_index("ix_deal_approvals_deal_id", "deal_approvals", ["deal_id"], unique=True)
    op.create_index("ix_deal_approvals_status", "deal_approvals", ["status"], unique=False)

    op.create_table(
        "deal_approval_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_approval_id", sa.Integer(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("assigned_user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False, server_default="pending"),
        sa.Column("acted_by_id", sa.Integer(), nullable=True),
        sa.Column("acted_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["acted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_approval_id"], ["deal_approvals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deal_approval_id", "step_order", name="uq_deal_approval_steps_order"),
    )
    op.create_index("ix_deal_approval_steps_assigned_user_id", "deal_approval_steps", ["assigned_user_id"], unique=False)
    op.create_index("ix_deal_approval_steps_deal_approval_id", "deal_approval_steps", ["deal_approval_id"], unique=False)
    op.create_index("ix_deal_approval_steps_step_order", "deal_approval_steps", ["step_order"], unique=False)
    op.create_index("ix_deal_approval_steps_status", "deal_approval_steps", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_deal_approval_steps_status", table_name="deal_approval_steps")
    op.drop_index("ix_deal_approval_steps_step_order", table_name="deal_approval_steps")
    op.drop_index("ix_deal_approval_steps_deal_approval_id", table_name="deal_approval_steps")
    op.drop_index("ix_deal_approval_steps_assigned_user_id", table_name="deal_approval_steps")
    op.drop_table("deal_approval_steps")
    op.drop_index("ix_deal_approvals_status", table_name="deal_approvals")
    op.drop_index("ix_deal_approvals_deal_id", table_name="deal_approvals")
    op.drop_table("deal_approvals")
    op.drop_index("ix_approval_workflow_steps_approver_user_id", table_name="approval_workflow_steps")
    op.drop_index("ix_approval_workflow_steps_workflow_id", table_name="approval_workflow_steps")
    op.drop_table("approval_workflow_steps")
    op.drop_index("ix_approval_workflows_tenant_id", table_name="approval_workflows")
    op.drop_table("approval_workflows")
