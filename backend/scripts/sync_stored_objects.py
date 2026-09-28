"""Bring stored_objects in line with what the buckets actually hold.

WHEN TO RUN
  * Once, right after deploying migration usage_meter_01. Every file uploaded before it has
    no row, so without this the console's Files column reads 0 for workspaces that have
    been uploading for months.
  * Then periodically (nightly is plenty) if any bucket has a lifecycle rule. An object a
    rule removes never passes through gcs.delete_blob, so its row would keep counting it.

WHAT IT DOES
  1. Lists every configured bucket — and, with --local, the three local-fallback roots.
  2. Adds a row for each object that has none, attributed by the ``{kind}/{tenant_id}/…``
     path convention every upload follows (usage_meter.classify / tenant_from_path) and,
     where a feature table still names the file, to the member who uploaded it.
     Objects whose first path segment is not a known upload kind are skipped and counted:
     a bucket shared with something else must not be billed to a workspace.
  3. Stamps deleted_at on rows whose object is gone. Only for locations that were listed
     successfully — an unreachable bucket never marks its whole contents deleted.

Rows the live hook already wrote are left alone.

LOCAL FILES ARE OPT-IN. The API and the Celery workers need not share a disk, so a host
that simply does not have another host's fallback files would otherwise mark them deleted.
Run --local on the host that holds them.

    python -m scripts.sync_stored_objects --dry-run     # report, write nothing
    python -m scripts.sync_stored_objects               # GCS buckets
    python -m scripts.sync_stored_objects --local       # GCS buckets + this host's disk
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# app.database builds its engine with echo=settings.DEBUG; this script prints a summary.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from sqlalchemy import select, update                                    # noqa: E402
from sqlalchemy.dialects.postgresql import insert                        # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine   # noqa: E402
from sqlalchemy.pool import NullPool                                     # noqa: E402

from app.config import settings                                          # noqa: E402
import app.models  # noqa: F401,E402 — every mapper registered before the ORM classes are used
from app.database import Base                                            # noqa: E402
from app.models.report_export import ReportExport                        # noqa: E402
from app.models.tenant import Tenant                                     # noqa: E402
from app.models.usage_meter import STORAGE_GCS, STORAGE_LOCAL, StoredObject  # noqa: E402
from app.services import file_store, usage_meter                         # noqa: E402
from app.services.tenant_resources import SOURCE_LABELS                  # noqa: E402
from app.services.uploaded_documents import SOURCES                      # noqa: E402

_BATCH = 500
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


@dataclass
class Found:
    name: str
    size: int
    content_type: str | None
    created_at: datetime


@dataclass
class Location:
    storage: str
    bucket: str
    label: str
    objects: list[Found] | None = None   # None = could not be listed
    error: str | None = None


def _naive_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.utcnow()
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _buckets() -> list[str]:
    """Every bucket some feature writes to, fallbacks resolved the way the features do."""
    names = [
        settings.GCS_DEALS_BUCKET_NAME,
        settings.GCS_TICKETS_BUCKET_NAME,
        settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME,
        settings.GCS_LOGOS_BUCKET_NAME,
        settings.GCS_SERIES_BUCKET_NAME or settings.GCS_DEALS_BUCKET_NAME,
        settings.GCS_REPORTS_BUCKET_NAME or settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME,
    ]
    return sorted({n for n in names if n})


def _local_roots() -> list[Path]:
    from app.services.report_download import storage as report_storage
    from app.services.series import documents as series_documents

    roots = [file_store._root(), report_storage.local_root(), series_documents.local_root()]
    return list(dict.fromkeys(r.resolve() for r in roots))


def _list_bucket(bucket: str) -> list[Found]:
    from app.services.gcs import _get_client

    return [
        Found(b.name, int(b.size or 0), b.content_type, _naive_utc(b.time_created))
        for b in _get_client().list_blobs(bucket)
        if not b.name.endswith("/")          # console-created "folders"
    ]


def _list_local(root: Path) -> list[Found]:
    if not root.is_dir():
        return []
    out = []
    for path in root.rglob("*"):
        if path.is_file():
            st = path.stat()
            out.append(Found(path.relative_to(root).as_posix(), st.st_size, None,
                             _naive_utc(datetime.fromtimestamp(st.st_mtime, timezone.utc))))
    return out


@dataclass
class Uploaders:
    by_name: dict[str, int]
    by_batch: dict[str, int]

    def get(self, object_name: str) -> int | None:
        """Exact file match first; else the upload session named in the path. Most kinds
        write ``{kind}/{tenant}/{batch_id}/…``, and several never record the path itself —
        deal uploads keep it on neither deal_statements nor deal_batches."""
        if object_name in self.by_name:
            return self.by_name[object_name]
        for seg in re.split(r"[\\/]+", object_name):
            if _UUID.match(seg) and seg in self.by_batch:
                return self.by_batch[seg]
        return None


async def _batch_owners(conn: AsyncConnection) -> dict[str, int]:
    """{batch_id: created_by_id} from every table that has both columns."""
    out: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        if "batch_id" in table.c and "created_by_id" in table.c:
            rows = (await conn.execute(
                select(table.c.batch_id, table.c.created_by_id)
                .where(table.c.created_by_id.isnot(None)).distinct()
            )).all()
            for batch_id, uid in rows:
                if batch_id:
                    out.setdefault(str(batch_id), uid)
    return out


async def _uploaders(conn: AsyncConnection) -> Uploaders:
    """Who uploaded what, from every table that still names its file or its batch."""
    out: dict[str, int] = {}
    for src in SOURCES:
        m = src.model
        by = getattr(m, src.by_col)
        rows = (await conn.execute(select(m.file_url, by).where(m.file_url.isnot(None)).distinct())).all()
        for locator, uid in rows:
            if locator and uid:
                out[locator.removeprefix(file_store.LOCAL_PREFIX)] = uid
    rows = (await conn.execute(
        select(ReportExport.file_locator, ReportExport.created_by_id).where(ReportExport.file_locator.isnot(None))
    )).all()
    for locator, uid in rows:
        out[locator.removeprefix(file_store.LOCAL_PREFIX)] = uid
    return Uploaders(by_name=out, by_batch=await _batch_owners(conn))


async def _known(conn: AsyncConnection, storage: str, bucket: str) -> dict[str, tuple[int, bool, int | None]]:
    """{object name: (row id, live, uploader)} already recorded for one location."""
    rows = (await conn.execute(
        select(StoredObject.object_name, StoredObject.id, StoredObject.deleted_at, StoredObject.user_id)
        .where(StoredObject.storage == storage, StoredObject.bucket == bucket)
    )).all()
    return {name: (rid, deleted_at is None, uid) for name, rid, deleted_at, uid in rows}


async def _sync(conn: AsyncConnection, loc: Location, objects: list[Found], tenants: set[int],
                uploaders: Uploaders, dry_run: bool) -> dict[str, int]:
    known = await _known(conn, loc.storage, loc.bucket)
    present = {o.name for o in objects}
    stats = {"listed": len(objects), "added": 0, "known": 0, "skipped": 0, "gone": 0,
             "bytes_added": 0, "owners": 0}

    new_rows = []
    revive_ids = []
    owners: list[tuple[int, int]] = []   # (row id, uploader) for rows that had none
    for o in objects:
        if o.name in known:
            stats["known"] += 1
            rid, live, uid = known[o.name]
            if not live:                 # marked deleted, but the object is there
                revive_ids.append(rid)
            if uid is None and (found := uploaders.get(o.name)) is not None:
                owners.append((rid, found))
            continue
        source, origin = usage_meter.classify(o.name)
        if source not in SOURCE_LABELS:
            stats["skipped"] += 1
            continue
        tid = usage_meter.tenant_from_path(o.name)
        new_rows.append({
            "tenant_id": tid if tid in tenants else None,
            "user_id": uploaders.get(o.name),
            "storage": loc.storage,
            "bucket": loc.bucket,
            "object_name": o.name,
            "source": source,
            "origin": origin,
            "size_bytes": o.size,
            "content_type": (o.content_type or None) and o.content_type[:255],
            "created_at": o.created_at,
        })
    stats["added"] = len(new_rows)
    stats["bytes_added"] = sum(r["size_bytes"] for r in new_rows)

    gone_ids = [rid for name, (rid, live, _) in known.items() if live and name not in present]
    stats["gone"] = len(gone_ids)
    stats["owners"] = len(owners)

    if not dry_run:
        for i in range(0, len(new_rows), _BATCH):
            await conn.execute(
                insert(StoredObject).values(new_rows[i:i + _BATCH])
                .on_conflict_do_nothing(constraint="uq_stored_objects_location")
            )
        now = datetime.utcnow()
        for i in range(0, len(gone_ids), _BATCH):
            await conn.execute(
                update(StoredObject).where(StoredObject.id.in_(gone_ids[i:i + _BATCH])).values(deleted_at=now)
            )
        for i in range(0, len(revive_ids), _BATCH):
            await conn.execute(
                update(StoredObject).where(StoredObject.id.in_(revive_ids[i:i + _BATCH])).values(deleted_at=None)
            )
        for rid, uid in owners:
            await conn.execute(
                update(StoredObject).where(StoredObject.id == rid, StoredObject.user_id.is_(None)).values(user_id=uid)
            )
    return stats


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:,.1f} MB"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    ap.add_argument("--local", action="store_true", help="also sync this host's local-fallback files")
    args = ap.parse_args()

    locations = [Location(STORAGE_GCS, b, f"gs://{b}") for b in _buckets()]
    for loc in locations:
        try:
            loc.objects = await asyncio.to_thread(_list_bucket, loc.bucket)
        except Exception as exc:  # noqa: BLE001 — reported, and its rows left untouched
            loc.error = str(exc)
    if not locations:
        print("No GCS bucket is configured.")

    local_objects: list[Found] | None = None
    if args.local:
        # One location: every local root records bucket=''. Object names cannot collide
        # across roots — each feature writes under its own first segment.
        local_objects = []
        for root in _local_roots():
            local_objects += _list_local(root)

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            tenants = set((await conn.execute(select(Tenant.id))).scalars().all())
            uploaders = await _uploaders(conn)

            for loc in locations:
                if loc.objects is None:
                    print(f"{loc.label}: NOT LISTED ({loc.error}) - left untouched")
                    continue
                s = await _sync(conn, loc, loc.objects, tenants, uploaders, args.dry_run)
                print(f"{loc.label}: {s['listed']} objects | {s['added']} added ({_mb(s['bytes_added'])})"
                      f" | {s['known']} already recorded | {s['skipped']} skipped (not an upload path)"
                      f" | {s['gone']} marked deleted | {s['owners']} uploaders filled in")

            if local_objects is not None:
                loc = Location(STORAGE_LOCAL, "", "local disk")
                s = await _sync(conn, loc, local_objects, tenants, uploaders, args.dry_run)
                print(f"{loc.label}: {s['listed']} files | {s['added']} added ({_mb(s['bytes_added'])})"
                      f" | {s['known']} already recorded | {s['skipped']} skipped | {s['gone']} marked deleted"
                      f" | {s['owners']} uploaders filled in")

            if args.dry_run:
                await conn.rollback()
                print("Dry run - nothing written.")
    finally:
        await engine.dispose()
    return 1 if any(loc.error for loc in locations) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
