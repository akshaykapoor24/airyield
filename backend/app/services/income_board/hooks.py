"""The one call site every ingest path uses to keep the board current.

Until the board held only priced lines, two hooks were enough: the end of a BSP
commission calculation and the end of a commission run. Every other write to a statement
table was invisible to it by design, because an unpriced row had nothing to project.

That is no longer true. A statement is sale the moment it is ingested, so the board now
has to be refreshed on upload, on re-parse, on reprocess, on re-split and on delete —
about a dozen places across three routers and two workers. One helper rather than a
dozen copies of the same try/except, for the reason the count implies: a hook per caller
is a hook someone forgets, and the twelfth copy is the one that drops the `except`.

BEST EFFORT, DELIBERATELY, exactly as `commission/runner._project_income_board` is. A
projection failure must never fail an upload — the statement rows are already committed
and correct, and the board is derived from them. The consequence is not silent:
GET /dashboard/income/freshness compares each batch's last projection against the
batch's own timestamps, and the page shows a blocking banner with a Rebuild button.

NEITHER FUNCTION COMMITS. Both are called inside the caller's transaction, before its
own commit, so an upload that rolls back does not leave a projection of rows that never
landed.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.income_board.overlap import OVERLAP_SOURCES, stamp_bsp_ndc_overlap
from app.services.income_board.project import (
    PROJECTED_SOURCES, clear_batch, project_batch,
)

logger = logging.getLogger(__name__)


async def refresh(
    db: AsyncSession, *, tenant_id: int, user_id: int, source: str, batch_id: str,
    engine_version: str | None = None,
) -> int:
    """Re-project one batch. Returns rows written, or 0 if anything went wrong.

    Safe to call for a source that has no arm — a type this module cannot project is
    not an error, it is a type whose sale nobody has asked for yet, and raising here
    would turn every TGQ HMPR upload into a 500.
    """
    if source not in PROJECTED_SOURCES:
        return 0
    try:
        written = await project_batch(
            db, tenant_id=tenant_id, user_id=user_id, source=source,
            batch_id=batch_id, engine_version=engine_version,
        )
        # Only when this projection can have changed the answer. Running the
        # workspace-wide re-stamp after every LCC upload would be a table scan for a
        # verdict that cannot have moved.
        if source in OVERLAP_SOURCES:
            await stamp_bsp_ndc_overlap(db, tenant_id=tenant_id)
        return written
    except Exception:  # noqa: BLE001
        logger.exception(
            "income_board: projection failed for %s/%s; the statement rows are "
            "unaffected and /dashboard/income/freshness will report this batch stale",
            source, batch_id,
        )
        return 0


async def forget(
    db: AsyncSession, *, tenant_id: int, user_id: int, source: str, batch_id: str,
) -> int:
    """Drop a deleted batch's projected rows. Returns rows removed, or 0 on failure.

    `source_row_id` carries no foreign key — deliberately, so that a derived report can
    never be the reason a master row cannot be deleted — which means nothing cascades
    and this has to be explicit. Before it existed, `clear_batch` had no callers at all:
    deleting a statement left its projected income behind as a figure nothing would ever
    restate, and the only way to clear it was a full Rebuild.
    """
    if source not in PROJECTED_SOURCES:
        return 0
    try:
        removed = await clear_batch(
            db, tenant_id=tenant_id, user_id=user_id, source=source, batch_id=batch_id,
        )
        if source in OVERLAP_SOURCES:
            # A deleted BSP upload gives its NDC tickets back: they are no longer
            # settled anywhere, so they are sale again.
            await stamp_bsp_ndc_overlap(db, tenant_id=tenant_id)
        return removed
    except Exception:  # noqa: BLE001
        logger.exception(
            "income_board: clearing %s/%s failed; its projected rows will survive "
            "until the next Rebuild", source, batch_id,
        )
        return 0
