"""Which uploads a report may read: the owner-verified selection.

WHY A SEPARATE STEP. The request names uploads by id, and those ids come from the browser.
Every later query of the build filters by tenant and user anyway, but the child tables the
builder joins (tax breakups, batch → supplier / airline links) are keyed by batch id alone,
so an id must be PROVEN to belong to the caller before anything is looked up by it. This
module is that proof: one owner-scoped query per source type over the ids the request named,
returning ``OwnedUpload`` records. Every other module receives an ``OwnedSelection`` and never
a raw id list.

It runs twice for one report — when the API accepts the request (so a foreign or missing id
is a 422 the user sees immediately) and again in the worker before the build (an upload may
have been deleted, or re-processed, while the report waited in the queue).

Rules:

* An included id that is unknown, belongs to someone else, or no longer exists raises
  ``SelectionError`` — the report would otherwise silently be smaller than requested.
* BSP, BSP Summary and LCC Detailed are parsed asynchronously in chunks; while they are not
  ``completed`` their rows are partial, so including one is refused.
* Unticked ids are informational (Read Me lists them; unticked TGQ uploads are kept out of
  the enrichment index). One that no longer exists is dropped rather than failing the report,
  and a not-completed one is fine — it is not being read.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import String, any_, func, literal, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.bsp_statement import BspStatement
from app.models.bsp_summary import BspSummaryRow, BspSummaryStatement
from app.models.lcc_detailed import LccDetailedBatch
from app.services.report_download.columns import COMBINED_COLUMNS
from app.services.report_download.registry import SOURCE_BY_KEY, SOURCES, ReportSource
from app.services.report_download.types import ReportOptions

STATUS_COMPLETED = "completed"
#: Cells per Combined row, for the size estimate (detail sheets are of similar width).
CELLS_PER_ROW = len(COMBINED_COLUMNS)


class SelectionError(ValueError):
    """The requested uploads cannot be read as asked. The message is shown to the user."""


@dataclass(frozen=True)
class OwnedUpload:
    source_key: str
    upload_id: str
    file_name: Optional[str]
    uploaded_at: Optional[datetime]
    status: Optional[str]
    total_rows: int
    reference: Optional[str] = None


def _newest_first(u: OwnedUpload) -> tuple:
    # Newest upload first; an upload with no timestamp last; the id keeps the order total.
    ts = u.uploaded_at
    return (ts is None, -(ts.timestamp()) if ts is not None else 0.0, u.upload_id)


@dataclass(frozen=True)
class OwnedSelection:
    tenant_id: int
    user_id: int
    uploads: tuple[OwnedUpload, ...]
    unticked: tuple[OwnedUpload, ...] = ()
    _by_source: dict = field(default=None, init=False, repr=False, compare=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        grouped: dict[str, list[OwnedUpload]] = {}
        for u in self.uploads:
            grouped.setdefault(u.source_key, []).append(u)
        object.__setattr__(self, "_by_source", {k: sorted(v, key=_newest_first) for k, v in grouped.items()})

    def for_source(self, source_key: str) -> list[OwnedUpload]:
        """Included uploads of one type, newest first (the de-duplication order)."""
        return list(self._by_source.get(source_key, ()))

    def ids(self, source_key: str) -> list[str]:
        return [u.upload_id for u in self.for_source(source_key)]

    def unticked_ids(self, source_key: str) -> list[str]:
        return [u.upload_id for u in self.unticked if u.source_key == source_key]


def _ids_param(ids: Sequence[str]):
    return literal(list(ids), ARRAY(String))


def _owned_statement(src: ReportSource, tenant_id: int, user_id: int, ids: Sequence[str]):
    """One query returning (upload_id, file_name, uploaded_at, status, total_rows, reference)."""
    arr = _ids_param(ids)
    if src.storage == "bsp":
        S = BspStatement
        return select(
            S.batch_id, S.file_name, S.created_at, S.status,
            func.greatest(S.row_count, S.total_rows), S.statement_name,
        ).where(S.tenant_id == tenant_id, S.created_by_id == user_id, S.batch_id == any_(arr))
    if src.storage == "bsp_summary":
        S, R = BspSummaryStatement, BspSummaryRow
        rows = (
            select(func.count()).where(
                R.summary_id == S.batch_id, R.tenant_id == tenant_id, R.created_by_id == user_id,
            ).scalar_subquery()
        )
        return select(S.batch_id, S.file_name, S.created_at, S.status, rows, S.agent_name).where(
            S.tenant_id == tenant_id, S.created_by_id == user_id, S.batch_id == any_(arr))
    if src.storage == "lcc_detailed":
        B = LccDetailedBatch
        return select(B.batch_id, B.source_file, B.uploaded_at, B.status, B.total_rows, B.airline_name).where(
            B.tenant_id == tenant_id, B.created_by_id == user_id, B.batch_id == any_(arr))
    # adjustment / spec tables: an upload is the set of rows sharing a batch_id
    m = src.model
    count = func.count().filter(m.is_total.is_(False)) if src.exclude_totals else func.count()
    return (
        select(m.batch_id, func.max(m.source_file), func.max(m.uploaded_at), literal(None, String), count,
               literal(None, String))
        .where(m.tenant_id == tenant_id, m.created_by_id == user_id, m.batch_id == any_(arr))
        .group_by(m.batch_id)
    )


async def _owned(conn: AsyncConnection, src: ReportSource, tenant_id: int, user_id: int,
                 ids: Sequence[str]) -> dict[str, OwnedUpload]:
    rows = (await conn.execute(_owned_statement(src, tenant_id, user_id, ids))).all()
    return {
        r[0]: OwnedUpload(
            source_key=src.key, upload_id=r[0], file_name=r[1], uploaded_at=r[2], status=r[3],
            total_rows=int(r[4] or 0), reference=r[5],
        )
        for r in rows
    }


def _group(pairs: Sequence[tuple[str, str]], what: str) -> "OrderedDict[str, list[str]]":
    grouped: OrderedDict[str, list[str]] = OrderedDict()
    for source_key, upload_id in pairs:
        key = (source_key or "").strip()
        uid = (upload_id or "").strip()
        if key not in SOURCE_BY_KEY:
            raise SelectionError(f"Unknown source type '{source_key}'.")
        if not uid:
            raise SelectionError(f"{what} {SOURCE_BY_KEY[key].label} upload has no id.")
        ids = grouped.setdefault(key, [])
        if uid not in ids:
            ids.append(uid)
    return grouped


async def resolve_selection(
    conn: AsyncConnection,
    tenant_id: int,
    user_id: int,
    included: Sequence[tuple[str, str]],
    unticked: Sequence[tuple[str, str]] = (),
) -> OwnedSelection:
    """Prove every included ``(source_type, upload_id)`` belongs to the caller.

    Raises ``SelectionError`` for an unknown source type, an id that is missing or not the
    caller's, or a BSP / BSP Summary / LCC Detailed upload that is not completed.
    """
    inc = _group(included, "An included")
    unt = _group(unticked, "An unticked")
    both = {(k, i) for k, ids in inc.items() for i in ids} & {(k, i) for k, ids in unt.items() for i in ids}
    if both:
        k, i = sorted(both)[0]
        raise SelectionError(f"{SOURCE_BY_KEY[k].label} upload {i} cannot be both included and unticked.")

    uploads: list[OwnedUpload] = []
    unticked_out: list[OwnedUpload] = []
    for src in SOURCES:                      # registry order keeps error messages stable
        wanted = inc.get(src.key, [])
        skipped = unt.get(src.key, [])
        if not wanted and not skipped:
            continue
        owned = await _owned(conn, src, tenant_id, user_id, wanted + skipped)
        for uid in wanted:
            up = owned.get(uid)
            if up is None:
                raise SelectionError(
                    f"{src.label} upload {uid} was not found among your uploads. "
                    "It may have been deleted — refresh the list and try again."
                )
            if src.completed_only and (up.status or "").lower() != STATUS_COMPLETED:
                name = up.file_name or uid
                raise SelectionError(
                    f"{src.label} upload '{name}' is {up.status or 'not processed'}, not completed, "
                    "so it cannot be included yet."
                )
            uploads.append(up)
        unticked_out.extend(owned[uid] for uid in skipped if uid in owned)
    if not uploads:
        raise SelectionError("Pick at least one upload to include.")
    return OwnedSelection(tenant_id=tenant_id, user_id=user_id, uploads=tuple(uploads),
                          unticked=tuple(unticked_out))


def estimate(sel: OwnedSelection, options: ReportOptions) -> tuple[int, int]:
    """Upper bound ``(rows, cells)`` for the size caps: every row of every included upload
    (the period filter can only remove rows), doubled when detail sheets repeat them."""
    rows = sum(max(0, u.total_rows) for u in sel.uploads)
    if options.include_detail_sheets:
        rows *= 2
    return rows, rows * CELLS_PER_ROW
