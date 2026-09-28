"""What each workspace costs to run: OpenAI calls and stored files.

Both tables are LEDGERS, written by services/usage_meter.py from the two chokepoints every
feature already goes through — ``ai_client.call_json`` for OpenAI, ``gcs`` / ``file_store``
for object storage. No feature code writes here, so a new AI feature or upload screen is
metered the day it ships without anyone remembering to wire it.

ai_usage_events
    One row per completed chat completion — the unit OpenAI bills. Tokens are stored, not
    dollars: the price is applied at read time (services/ai_pricing.py), so correcting a
    price corrects history too. Model snapshots are fixed-price, so re-pricing an old row
    with today's table is right for every model this app pins.

    Failed attempts (429, timeout, connection reset) are not rows: they return no usage
    and are not billed.

stored_objects
    One row per object in storage, keyed by where it physically lives — (storage, bucket,
    object_name). A re-upload to the same name updates the row rather than adding one, so
    the live bytes are always what the bucket holds. Deleting the object stamps deleted_at
    rather than removing the row, which keeps "how many files did they upload" answerable
    after the files are gone.

    Rows written before this table existed come from scripts/sync_stored_objects.py, which
    lists the buckets and attributes each object by the ``{kind}/{tenant_id}/…`` path
    convention every upload already follows.

tenant_id is nullable on both: the platform admin belongs to no workspace, and a call it
makes is still a call someone pays for. Those rows show up as the unattributed remainder in
the console's platform totals.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

STORAGE_GCS = "gcs"
STORAGE_LOCAL = "local"

# A member put it there, or the product made it from something a member put there (a report
# workbook, a cached spreadsheet preview). Both occupy the bucket; only the first is an upload.
ORIGIN_UPLOAD = "upload"
ORIGIN_GENERATED = "generated"


class AiUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        # The console: one workspace's calls, and this month's slice of them.
        Index("ix_ai_usage_events_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    # SET NULL: removing a member must not erase what the workspace spent through them.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # The `label` call_json already takes: ai-extract, ai-narration, series-extract.
    feature: Mapped[str] = mapped_column(String(40), nullable=False)
    # What the response says it ran on, which for an alias is the resolved snapshot.
    model: Mapped[str] = mapped_column(String(80), nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # The part of prompt_tokens served from OpenAI's prompt cache, billed at the cached rate.
    cached_prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Includes reasoning_tokens — OpenAI bills hidden reasoning as output.
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Naive UTC from Python, like report_exports — never DB now().
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class StoredObject(Base):
    __tablename__ = "stored_objects"
    __table_args__ = (
        UniqueConstraint("storage", "bucket", "object_name", name="uq_stored_objects_location"),
        CheckConstraint(f"storage IN ('{STORAGE_GCS}', '{STORAGE_LOCAL}')", name="ck_stored_objects_storage"),
        CheckConstraint(f"origin IN ('{ORIGIN_UPLOAD}', '{ORIGIN_GENERATED}')", name="ck_stored_objects_origin"),
        Index("ix_stored_objects_tenant", "tenant_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    storage: Mapped[str] = mapped_column(String(8), nullable=False)
    # '' for local disk.
    bucket: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Exactly the name the object was written under — the same string the owning row keeps
    # in its file_url, so a delete can find it again. GCS caps names at 1024 bytes.
    object_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    # The path's first segment (bsp, deals, statements, …): which feature it belongs to.
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    origin: Mapped[str] = mapped_column(String(12), nullable=False, default=ORIGIN_UPLOAD)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
