"""Celery task for async LCC Detailed statement ingestion.

An LCC Detailed export can be ~30,000 rows — far too large to insert inside an HTTP
request. `POST /lcc-detailed/confirm` stores the confirmed column mapping and enqueues
`ingest_lcc_detailed`, which downloads the file from GCS, applies the mapping row-by-row
(routing values into typed columns + folded taxes/segments/ssr JSONB via
`lcc_detailed_spec.build_typed_row`), and bulk-inserts in chunks while advancing the
progress counters the frontend polls.

Mirrors the BSP pipeline (`workers/bsp_tasks.py`):
  * per-task NullPool async engine (the FastAPI pool isn't safe across the fresh
    event loop `asyncio.run` builds, nor across a prefork);
  * idempotent — every run re-claims the batch and deletes its existing rows first,
    so a retry can never duplicate data;
  * run a worker with:  celery -A app.workers.celery_app.celery_app worker -l info -Q lcc
    (add --pool=solo on Windows dev).
"""
import asyncio
import io
import logging
from datetime import datetime

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

CHUNK_ROWS = 1000   # bulk-insert rows in batches of this size


@celery_app.task(bind=True, max_retries=3, acks_late=True, queue="lcc")
def ingest_lcc_detailed(self, batch_id: str, tenant_id: int, user_id: int):
    try:
        asyncio.run(_ingest(batch_id, tenant_id, user_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("LCC ingest failed for batch %s", batch_id)
        try:
            asyncio.run(_mark_failed(batch_id, tenant_id, str(exc)))
        except Exception:  # noqa: BLE001
            logger.exception("could not mark LCC batch %s failed", batch_id)
        raise self.retry(exc=exc, countdown=min(60 * (self.request.retries + 1), 600))


# ── helpers ─────────────────────────────────────────────────────────────────
def _new_engine():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return engine, Session


def _bucket() -> str:
    from app.config import settings
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _read_df(content: bytes, filename: str, header_row: int):
    """The worker's reader, which MUST agree with the extract-time one in
    api/v1/lcc_detailed.py — it re-reads the same file at the pinned header row.

    Both now call the same function, so they cannot drift apart. That is a stronger
    guarantee than the comment that used to say they must not.
    """
    from app.services import spreadsheet
    return spreadsheet.read_df(content, filename, header_row)


async def _mark_failed(batch_id: str, tenant_id: int, message: str):
    from sqlalchemy import update
    from app.models.lcc_detailed import LccDetailedBatch

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            async with db.begin():
                await db.execute(
                    update(LccDetailedBatch)
                    .where(LccDetailedBatch.batch_id == batch_id, LccDetailedBatch.tenant_id == tenant_id)
                    .values(status="failed", error=(message or "")[:2000])
                )
    finally:
        await engine.dispose()


async def _fail(db, batch_id: str, message: str):
    from sqlalchemy import update
    from app.models.lcc_detailed import LccDetailedBatch
    async with db.begin():
        await db.execute(
            update(LccDetailedBatch).where(LccDetailedBatch.batch_id == batch_id)
            .values(status="failed", error=message[:2000])
        )
    logger.warning("LCC batch %s failed: %s", batch_id, message)


async def _flush(db, rows: list[dict], batch_id: str, running_before: int) -> int:
    """Insert a chunk and advance processed_rows — in ONE transaction, so the frontend
    never sees progress ahead of durable rows. Returns how many rows were inserted.

    If the fast bulk insert fails (e.g. one row has a value that violates a column
    constraint), fall back to row-by-row inserts with per-row SAVEPOINTs so a single
    bad row is skipped instead of failing the whole 30k-row batch."""
    from sqlalchemy import insert, update
    from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
    try:
        async with db.begin():
            await db.execute(insert(LccDetailed), rows)
            await db.execute(
                update(LccDetailedBatch).where(LccDetailedBatch.batch_id == batch_id)
                .values(processed_rows=running_before + len(rows))
            )
        return len(rows)
    except Exception as e:  # noqa: BLE001 — one bad row shouldn't nuke the chunk
        logger.warning("LCC batch %s: bulk insert failed (%s) — retrying row-by-row", batch_id, e)

    ok = 0
    async with db.begin():
        for r in rows:
            try:
                async with db.begin_nested():   # SAVEPOINT — a failure rolls back only this row
                    await db.execute(insert(LccDetailed), [r])
                ok += 1
            except Exception as ex:  # noqa: BLE001
                logger.warning("LCC batch %s: skipping bad row: %s", batch_id, ex)
        await db.execute(
            update(LccDetailedBatch).where(LccDetailedBatch.batch_id == batch_id)
            .values(processed_rows=running_before + ok)
        )
    return ok


async def _ingest(batch_id: str, tenant_id: int, user_id: int):
    from sqlalchemy import select, delete, update
    from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
    from app.models.lcc_detailed_batch_file import LccDetailedBatchFile
    from app.api.v1.lcc_detailed import _bill_kind
    from app.services import customer_resolver as cres
    from app.services import gcs
    from app.services import lcc_detailed_spec as spec
    from app.services import lcc_merge

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            # ── Claim + idempotent reset (one tx) ───────────────────────────
            async with db.begin():
                batch = (await db.execute(
                    select(LccDetailedBatch).where(
                        LccDetailedBatch.batch_id == batch_id,
                        LccDetailedBatch.tenant_id == tenant_id,
                    ).with_for_update()
                )).scalar_one_or_none()
                if batch is None:
                    logger.warning("LCC batch %s not found (tenant %s)", batch_id, tenant_id)
                    return
                if batch.status == "completed":
                    logger.info("LCC batch %s already completed — skipping", batch_id)
                    return
                if batch.resolution_status == "projected":
                    # Re-ingest DELETEs every row below and re-inserts with new PKs,
                    # which would strand the projected tickets pointing at rows that
                    # no longer exist. Unreachable through the API today, but the
                    # consequence is permanent, so refuse rather than rely on that.
                    logger.warning(
                        "LCC batch %s has been sent to billing — refusing to re-ingest", batch_id
                    )
                    batch.error = (
                        "This upload has already been sent to billing, so its rows cannot be "
                        "re-imported. Delete the billing and the upload, then upload again."
                    )
                    return
                # Every source file, each with its OWN header row and column map — the
                # two halves of a split export share no headers, so one map could not
                # describe both. Loaded inside the claim tx with everything else.
                files = [
                    {"role": f.role, "file_url": f.file_url, "header_row": f.header_row or 0,
                     "column_map": dict(f.column_map or {}), "source_file": f.source_file or ""}
                    for f in (await db.execute(
                        select(LccDetailedBatchFile)
                        .where(LccDetailedBatchFile.batch_id == batch_id)
                    )).scalars().all()
                ]
                # A batch staged before the child table existed has no file rows; its
                # scalars still describe the single file it was.
                if not files:
                    files = [{"role": lcc_merge.ROLE_SINGLE, "file_url": batch.file_url,
                              "header_row": batch.header_row or 0,
                              "column_map": dict(batch.column_map or {}),
                              "source_file": batch.source_file or ""}]
                # Denormalised onto every row: an LCC export names no carrier, so the
                # airline the user declared at upload is the only source of it.
                airline_id = batch.airline_id
                airline_name = batch.airline_name
                airline_code = batch.airline_code
                batch.status = "processing"
                batch.error = None
                batch.processed_rows = 0
                await db.execute(delete(LccDetailed).where(LccDetailed.batch_id == batch_id))

            for f in files:
                if not f["file_url"]:
                    await _fail(db, batch_id,
                                f"No {f['role']} file is attached to this upload.")
                    return
                if not f["column_map"]:
                    await _fail(db, batch_id,
                                f"No column mapping was confirmed for the {f['role']} file.")
                    return

            # ── Download + parse (each at the header row pinned at extract) ──
            frames: dict[str, list[dict]] = {}
            columns: dict[str, list[str]] = {}
            maps: dict[str, dict] = {f["role"]: f["column_map"] for f in files}
            source_rows = 0
            for f in files:
                content = await gcs.download_bytes(f["file_url"], _bucket())
                df = _read_df(content, f["source_file"], f["header_row"])
                df.dropna(how="all", inplace=True)
                frames[f["role"]] = [{str(k): v for k, v in row.to_dict().items()}
                                     for _, row in df.iterrows()]
                columns[f["role"]] = [str(c) for c in df.columns]
                source_rows += len(df)

            # ── Merge ────────────────────────────────────────────────────────
            # A `single` file is passed through untouched. Anything else goes through
            # the merge even when only one half was uploaded: a passenger file still
            # needs its segments folded, and an account file still needs its movement
            # kinds classified from the note.
            single = frames.get(lcc_merge.ROLE_SINGLE)
            if single is not None:
                merged = [
                    lcc_merge.MergedRow(role=lcc_merge.ROLE_SINGLE,
                                        row_kind=lcc_merge.ROW_KIND_PAX, data=r)
                    for r in single
                ]
                stats = None
            else:
                merged, stats = lcc_merge.merge(
                    frames.get(lcc_merge.ROLE_PAX, []), columns.get(lcc_merge.ROLE_PAX, []),
                    frames.get(lcc_merge.ROLE_ACCOUNT, []), columns.get(lcc_merge.ROLE_ACCOUNT, []),
                    airline_code=airline_code,
                )

            # The merge writes FEWER rows than it reads, so the count set at extract is
            # the wrong denominator. Correct it before the first flush or the progress
            # bar climbs past its own target and then jumps back.
            async with db.begin():
                await db.execute(
                    update(LccDetailedBatch).where(LccDetailedBatch.batch_id == batch_id)
                    .values(total_rows=len(merged), source_rows=source_rows,
                            merge_stats=(stats.as_dict() if stats else None))
                )

            inserted = 0     # rows durably written
            seen = 0         # non-blank rows attempted (for skip accounting)
            buf: list[dict] = []
            for row in merged:
                built = spec.build_typed_row(row.data, maps.get(row.role, {}))
                if built is None:
                    continue
                built["tenant_id"] = tenant_id
                built["created_by_id"] = user_id
                built["batch_id"] = batch_id
                built["airline_id"] = airline_id
                built["airline_name"] = airline_name
                built["airline_code"] = airline_code
                built["row_kind"] = row.row_kind
                built["movement_kind"] = row.movement_kind
                if row.extra:
                    built["extra"] = {**(built.get("extra") or {}), **row.extra}
                # Classified at INSERT rather than left to `resolve-customers`:
                # until something sets bill_kind, the commission engine reads NULL as
                # an ISSUE and prices the row as a fare-less sale, so leaving it null
                # opens a window where a commission run is wrong. `_bill_kind` is the
                # same function `resolve-customers` will apply, so this only closes
                # that window early — it never decides anything differently.
                #
                # Set on EVERY row, not just some: the chunked executemany below needs
                # one key set across the batch, and a dict that gains keys on some
                # rows would drop the whole chunk into the slow row-by-row fallback.
                kind = _bill_kind(built.get("total"))
                built["bill_kind"] = kind
                built["bill_status"] = (
                    cres.EXCLUDED if kind == "payment" else cres.UNRESOLVED
                )
                buf.append(built)
                seen += 1
                if len(buf) >= CHUNK_ROWS:
                    inserted += await _flush(db, buf, batch_id, inserted)
                    buf = []
            if buf:
                inserted += await _flush(db, buf, batch_id, inserted)

            # ── Mark completed ──────────────────────────────────────────────
            skipped = seen - inserted
            async with db.begin():
                await db.execute(
                    update(LccDetailedBatch).where(LccDetailedBatch.batch_id == batch_id)
                    .values(status="completed", total_rows=inserted, processed_rows=inserted,
                            completed_at=datetime.utcnow())
                )
            logger.info("LCC batch %s completed: %d source lines, %d rows inserted, %d skipped",
                        batch_id, source_rows, inserted, skipped)
    finally:
        await engine.dispose()
