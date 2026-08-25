"""add iata_commission_approvals (System Master update queue)

IATA Commission joins the other four System Masters (suppliers, airlines,
airports, classes/RBD) in accepting tenant submissions: a tenant user proposes
a new row or an update to an existing one, and Master Governance approves,
edits or rejects it. This table is the queue — the business columns mirror
`iata_commissions` so approve can copy the row straight onto the master, plus
the workflow block (status / submitter / reviewer) and the admin-edit block
(`original_payload` / `edited_by_id` / `edited_at`) the other four already have.

Revision ID: iata_commission_approvals_01
Revises: cust_party_01
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "iata_commission_approvals_01"
down_revision: Union[str, None] = "cust_party_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "iata_commission_approvals",
        sa.Column("id",                  sa.Integer(),     nullable=False),

        # ── business columns, mirroring iata_commissions ──────────────────
        sa.Column("airline_name",        sa.String(255),   nullable=False),
        sa.Column("airline_code",        sa.String(20),    nullable=True),
        sa.Column("iata_numeric_code",   sa.String(10),    nullable=True),
        sa.Column("iata_commission_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("valid_from",          sa.Date(),        nullable=True),
        sa.Column("valid_to",            sa.Date(),        nullable=True),

        # ── workflow ──────────────────────────────────────────────────────
        sa.Column("status",              sa.String(20),    nullable=True),
        sa.Column("submitted_by_id",     sa.Integer(),     nullable=False),
        sa.Column("tenant_id",           sa.Integer(),     nullable=True),
        sa.Column("submitted_at",        sa.DateTime(),    nullable=True),
        sa.Column("reviewed_by_id",      sa.Integer(),     nullable=True),
        sa.Column("reviewed_at",         sa.DateTime(),    nullable=True),
        sa.Column("rejection_reason",    sa.Text(),        nullable=True),

        # ── platform-admin edit before approval ───────────────────────────
        sa.Column("original_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("edited_by_id",        sa.Integer(),     nullable=True),
        sa.Column("edited_at",           sa.DateTime(),    nullable=True),

        # ── new vs update ─────────────────────────────────────────────────
        sa.Column("request_type",              sa.String(10), nullable=True),
        sa.Column("target_iata_commission_id", sa.Integer(),  nullable=True),

        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"],   ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"],       ["tenants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"],  ["users.id"],   ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["edited_by_id"],    ["users.id"],   ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["target_iata_commission_id"], ["iata_commissions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # The two queries this table serves: the admin's pending list and a
    # submitter's own list.
    op.create_index(
        "ix_iata_commission_approvals_status",
        "iata_commission_approvals", ["status"],
    )
    op.create_index(
        "ix_iata_commission_approvals_submitted_by_id",
        "iata_commission_approvals", ["submitted_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_iata_commission_approvals_submitted_by_id",
        table_name="iata_commission_approvals",
    )
    op.drop_index(
        "ix_iata_commission_approvals_status",
        table_name="iata_commission_approvals",
    )
    # Dropping this discards every queued request along with the record of what
    # each submitter originally sent; there is nowhere else to move it.
    op.drop_table("iata_commission_approvals")
