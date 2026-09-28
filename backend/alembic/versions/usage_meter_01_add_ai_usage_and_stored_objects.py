"""Platform admin → Subscriptions: per-workspace OpenAI and storage metering

  ai_usage_events   One row per completed OpenAI chat completion — tokens, model, feature,
                    who and which workspace. Priced at read time (services/ai_pricing.py).
  stored_objects    One row per object in GCS or the local fallback, keyed by its location,
                    with its size and who put it there. deleted_at is stamped, not the row
                    removed, so the upload count survives the file.

See app/models/usage_meter.py for why each field exists. Both start empty: new usage is
recorded from the moment this deploys, and scripts/sync_stored_objects.py fills in the
objects already sitting in the buckets. There is no history to recover for OpenAI calls —
nothing recorded them before.

Hand-written: autogenerate on this repo proposes ~240 unrelated drops.

Revision ID: usage_meter_01
Revises: series_v2_02
Create Date: 2026-09-28 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "usage_meter_01"
down_revision: Union[str, None] = "series_v2_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("feature", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_usage_events_tenant_created", "ai_usage_events", ["tenant_id", "created_at"])
    op.create_index("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"])

    op.create_table(
        "stored_objects",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage", sa.String(8), nullable=False),
        sa.Column("bucket", sa.String(255), nullable=False, server_default=""),
        sa.Column("object_name", sa.String(1024), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("origin", sa.String(12), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("storage", "bucket", "object_name", name="uq_stored_objects_location"),
        sa.CheckConstraint("storage IN ('gcs', 'local')", name="ck_stored_objects_storage"),
        sa.CheckConstraint("origin IN ('upload', 'generated')", name="ck_stored_objects_origin"),
    )
    op.create_index("ix_stored_objects_tenant", "stored_objects", ["tenant_id", "deleted_at"])
    op.create_index("ix_stored_objects_user_id", "stored_objects", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_stored_objects_user_id", table_name="stored_objects")
    op.drop_index("ix_stored_objects_tenant", table_name="stored_objects")
    op.drop_table("stored_objects")
    op.drop_index("ix_ai_usage_events_user_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_tenant_created", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
