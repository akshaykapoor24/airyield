"""PLB accrual board — overrides, per-airline settings and frozen periods

Three additive tables behind Dashboard → PLB Accrual. Nothing is backfilled and
no existing table is touched, so this is safe to run and to roll back.

The grain columns (airline_key, entity_key, channel_key, lob_key) are NOT NULL
with a '' default on purpose. They are part of a UNIQUE constraint, and Postgres
treats NULLs as distinct — with nullable columns two "no LOB" rows for the same
airline would both insert and the override would silently double.

REVISION ID. Deliberately descriptive rather than the usual generated hex: this
repo has reused hex-pattern ids that collide, so new migrations spell out what
they are.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "plb_accrual_01"
down_revision: Union[str, None] = "corp_link_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plb_accrual_inputs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("airline_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("entity_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("channel_key", sa.String(20), nullable=False, server_default=""),
        sa.Column("lob_key", sa.String(100), nullable=False, server_default=""),
        sa.Column("ym", sa.String(7), nullable=False),
        sa.Column("deflator_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("plb_rate_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("manual_flown", sa.Numeric(16, 2), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "tenant_id", "created_by_id", "airline_key", "entity_key",
            "channel_key", "lob_key", "ym",
            name="uq_plb_accrual_inputs_cell",
        ),
    )
    op.create_index("ix_plb_accrual_inputs_tenant_id", "plb_accrual_inputs", ["tenant_id"])
    op.create_index("ix_plb_accrual_inputs_created_by_id", "plb_accrual_inputs", ["created_by_id"])
    # The board loads a window of months for one owner in one query, then indexes
    # the result in Python by cell key — so scope + month is the access path.
    op.create_index(
        "ix_plb_accrual_inputs_scope_ym", "plb_accrual_inputs",
        ["tenant_id", "created_by_id", "ym"],
    )

    op.create_table(
        "plb_airline_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("airline_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("entity_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("channel_key", sa.String(20), nullable=False, server_default=""),
        sa.Column("flown_confirmed_through", sa.Date(), nullable=True),
        sa.Column("default_deflator_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "tenant_id", "created_by_id", "airline_key", "entity_key", "channel_key",
            name="uq_plb_airline_settings_scope",
        ),
    )
    op.create_index("ix_plb_airline_settings_tenant_id", "plb_airline_settings", ["tenant_id"])
    op.create_index("ix_plb_airline_settings_created_by_id", "plb_airline_settings", ["created_by_id"])

    op.create_table(
        "plb_accrual_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("period_key", sa.String(20), nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("grid", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("totals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_accrual", sa.Numeric(16, 2), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("frozen_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("frozen_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "tenant_id", "created_by_id", "period_key",
            name="uq_plb_accrual_snapshots_period",
        ),
    )
    op.create_index("ix_plb_accrual_snapshots_tenant_id", "plb_accrual_snapshots", ["tenant_id"])
    op.create_index("ix_plb_accrual_snapshots_created_by_id", "plb_accrual_snapshots", ["created_by_id"])


def downgrade() -> None:
    op.drop_table("plb_accrual_snapshots")
    op.drop_table("plb_airline_settings")
    op.drop_index("ix_plb_accrual_inputs_scope_ym", table_name="plb_accrual_inputs")
    op.drop_table("plb_accrual_inputs")
