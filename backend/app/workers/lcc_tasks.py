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
    import pandas as pd
    name = (filename or "").lower()
    if name.endswith(".csv"):
        # index_col=False keeps columns positionally aligned even when data rows end with a
        # trailing delimiter (otherwise pandas steals the first column as an index and every
        # value shifts left). MUST match the extract-time reader in api/v1/lcc_detailed.py.
        return pd.read_csv(io.BytesIO(content), dtype=str, sep=None, engine="python",
                           header=header_row, index_col=False)
    if name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(content), dtype=str, header=header_row)
    return pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl", header=header_row)


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
    from app.services import gcs
    from app.services import lcc_detailed_spec as spec

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
                file_url = batch.file_url
                header_row = batch.header_row or 0
                column_map = dict(batch.column_map or {})
                source_file = batch.source_file or ""
                batch.status = "processing"
                batch.error = None
                batch.processed_rows = 0
                await db.execute(delete(LccDetailed).where(LccDetailed.batch_id == batch_id))

            if not file_url:
                await _fail(db, batch_id, "No file attached to this upload.")
                return
            if not column_map:
                await _fail(db, batch_id, "No column mapping was confirmed for this upload.")
                return

            # ── Download + parse (using the header row detected at extract) ──
            content = await gcs.download_bytes(file_url, _bucket())
            df = _read_df(content, source_file, header_row)
            df.dropna(how="all", inplace=True)

            inserted = 0     # rows durably written
            seen = 0         # non-blank rows attempted (for skip accounting)
            buf: list[dict] = []
            for _, row in df.iterrows():
                raw = {str(k): v for k, v in row.to_dict().items()}
                built = spec.build_typed_row(raw, column_map)
                if built is None:
                    continue
                built["tenant_id"] = tenant_id
                built["created_by_id"] = user_id
                built["batch_id"] = batch_id
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
            logger.info("LCC batch %s completed: %d rows inserted, %d skipped", batch_id, inserted, skipped)
    finally:
        await engine.dispose()
