import enum
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Integer, BigInteger, Enum as SAEnum, Boolean, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkflowModule(str, enum.Enum):
    DEALS = "deals"
    TICKETS = "tickets"


# What a DEALS workflow does with a new deal. Plain strings, like every other choice
# column in this schema, and named here so the signup default, the API and the deal
# approval path all mean the same thing by them.
#
#   proprietary → no approval steps at all; a deal is approved the moment it is created.
#   enterprise  → the deal waits on the workflow's steps, in order.
#
# PROPRIETARY IS WHAT A NEW WORKSPACE GETS (services/auth_service.signup). Without a
# workflow at all, creating a deal fails outright — "Deals approval workflow is not
# configured" — so the useful default is the one that lets someone work on day one, and
# a Super Admin who wants sign-offs switches to Enterprise and adds the steps.
DEAL_CATEGORY_PROPRIETARY = "proprietary"
DEAL_CATEGORY_ENTERPRISE = "enterprise"


class ApprovalActionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class ApprovalWorkflow(Base):
    __tablename__ = "approval_workflows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "module", name="uq_approval_workflows_tenant_module"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    module: Mapped[WorkflowModule] = mapped_column(
        SAEnum(
            WorkflowModule,
            native_enum=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deal_category: Mapped[str] = mapped_column(String(50), nullable=False, server_default='enterprise')
    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps: Mapped[list["ApprovalWorkflowStep"]] = relationship(
        "ApprovalWorkflowStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ApprovalWorkflowStep.step_order",
    )


class ApprovalWorkflowStep(Base):
    __tablename__ = "approval_workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_order", name="uq_approval_workflow_steps_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("approval_workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    reviewer_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workflow: Mapped["ApprovalWorkflow"] = relationship("ApprovalWorkflow", back_populates="steps")
    approvers: Mapped[list["ApprovalWorkflowStepApprover"]] = relationship(
        "ApprovalWorkflowStepApprover",
        back_populates="workflow_step",
        cascade="all, delete-orphan",
    )

    @property
    def approver_user_ids(self) -> list[int]:
        return [a.user_id for a in (self.approvers or [])]


class ApprovalWorkflowStepApprover(Base):
    __tablename__ = "approval_workflow_step_approvers"
    __table_args__ = (
        UniqueConstraint("workflow_step_id", "user_id", name="uq_workflow_step_approver_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_step_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("approval_workflow_steps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workflow_step: Mapped["ApprovalWorkflowStep"] = relationship("ApprovalWorkflowStep", back_populates="approvers")


class DealApproval(Base):
    __tablename__ = "deal_approvals"
    __table_args__ = (
        UniqueConstraint("deal_type", "deal_id", name="uq_deal_approvals_type_deal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Polymorphic reference: 'upload'|'airline'|'b2b' → legacy tables, 'unified' → new deals table
    deal_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="upload")
    deal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # Phase 4 FK: populated when deal_type='unified'; will replace deal_type+deal_id in Phase 5
    unified_deal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("approval_workflows.id", ondelete="CASCADE"), nullable=False)
    current_step_order: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ApprovalActionStatus] = mapped_column(
        SAEnum(
            ApprovalActionStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ApprovalActionStatus.PENDING,
    )
    submitted_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps: Mapped[list["DealApprovalStep"]] = relationship(
        "DealApprovalStep",
        back_populates="deal_approval",
        cascade="all, delete-orphan",
        order_by="DealApprovalStep.step_order",
    )


class DealApprovalStep(Base):
    __tablename__ = "deal_approval_steps"
    __table_args__ = (
        UniqueConstraint("deal_approval_id", "step_order", "assigned_user_id", name="uq_deal_approval_steps_order_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    deal_approval_id: Mapped[int] = mapped_column(Integer, ForeignKey("deal_approvals.id", ondelete="CASCADE"), nullable=False, index=True)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    assigned_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[ApprovalActionStatus] = mapped_column(
        SAEnum(
            ApprovalActionStatus,
            native_enum=False,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ApprovalActionStatus.PENDING,
    )
    acted_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deal_approval: Mapped["DealApproval"] = relationship("DealApproval", back_populates="steps")
