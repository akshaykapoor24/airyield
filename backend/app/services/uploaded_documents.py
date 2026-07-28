"""Combined "Uploaded Documents" view.

Every upload feature stores its source file in GCS and keeps the blob path in a
``file_url`` column on its own table (across several buckets). This service unions all
of those into ONE list — the Workspace → Uploaded documents page — with normalized
metadata (source, file name, reference, uploaded by/at) and a safe blob resolver for
signing (the client never gets raw blob paths; it passes back the source key + id and
we re-resolve from the DB, tenant/user-scoped).

Adding a new upload source = one DocSource entry here. No schema changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy import select, func, null
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.models.ticket_statement import TicketStatement
from app.models.customer_statement import CustomerStatement
from app.models.bsp_statement import BspStatement
from app.models.bsp_summary import BspSummaryStatement
from app.models.airline_adjustment import AirlineADM, AirlineACM, AirlineRA
from app.models.statement_row import STATEMENT_MODELS
from app.models.deal import DealStatement
from app.services.statement_spec import STATEMENT_SPECS


def _tickets_bucket() -> str:
    return settings.GCS_TICKETS_BUCKET_NAME


def _bsp_bucket() -> str:
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _deals_bucket() -> str:
    return settings.GCS_DEALS_BUCKET_NAME


@dataclass
class DocSource:
    key: str                       # stable unique key (used by the file-url resolver)
    label: str                     # human source label
    category: str                  # UI grouping
    model: type                    # ORM model
    bucket: Callable[[], str]      # which GCS bucket holds its blobs
    id_col: str                    # identifier column (batch_id or id)
    name_col: str                  # file-name column
    at_col: str                    # uploaded-at column
    by_col: str                    # created_by column
    ref_col: Optional[str]         # a human reference column (agency / airline / supplier)
    per_row: bool                  # True → the file_url repeats on every row; dedupe by id_col
    id_is_int: bool = False        # identifier is an int PK (vs a string batch_id)
    link_tpl: Optional[str] = None # optional frontend deep-link, {id} substituted


SOURCES: list[DocSource] = [
    DocSource("tickets",     "Internal Statement", "Internal",    TicketStatement,      _tickets_bucket, "batch_id", "file_name",   "created_at",  "created_by_id", "agency",        False, link_tpl="/tickets/{id}"),
    DocSource("customer",    "Customer Statement", "Customer",    CustomerStatement,    _tickets_bucket, "batch_id", "file_name",   "created_at",  "created_by_id", "agency",        False, link_tpl="/customers/statements/{id}"),
    DocSource("bsp",         "BSP Statement",      "BSP",         BspStatement,         _bsp_bucket,     "batch_id", "file_name",   "created_at",  "created_by_id", "airline_name",  False),
    DocSource("bsp-summary", "BSP Summary",        "BSP",         BspSummaryStatement,  _bsp_bucket,     "batch_id", "file_name",   "created_at",  "created_by_id", "agent_name",    False),
    DocSource("adm",         "ADM",                "Adjustments", AirlineADM,           _bsp_bucket,     "batch_id", "source_file", "uploaded_at", "created_by_id", None,            True),
    DocSource("acm",         "ACM",                "Adjustments", AirlineACM,           _bsp_bucket,     "batch_id", "source_file", "uploaded_at", "created_by_id", None,            True),
    DocSource("ra",          "RA",                 "Adjustments", AirlineRA,            _bsp_bucket,     "batch_id", "source_file", "uploaded_at", "created_by_id", None,            True),
    DocSource("deals",       "Deal",               "Deals",       DealStatement,        _deals_bucket,   "id",       "file_name",   "created_at",  "created_by_id", "supplier_name", False, id_is_int=True),
]

# Vendor statement types (TGQ HMPR / NDC / LCC* / Third-Party) — one dedicated table each,
# rows repeat the file_url so dedupe by batch_id.
for _slug, _model in STATEMENT_MODELS.items():
    _label = STATEMENT_SPECS.get(_slug, {}).get("label", _slug)
    SOURCES.append(
        DocSource(f"stmt:{_slug}", _label, "Vendor", _model, _bsp_bucket,
                  "batch_id", "source_file", "uploaded_at", "created_by_id", None, per_row=True)
    )

SOURCE_BY_KEY: dict[str, DocSource] = {s.key: s for s in SOURCES}


async def list_uploaded(db: AsyncSession, current_user: User) -> list[dict]:
    """Union every upload source into one metadata list, scoped to the current tenant+user,
    newest first. Only rows that actually have a GCS file are included."""
    items: list[dict] = []
    by_ids: set[int] = set()

    for s in SOURCES:
        M = s.model
        idc  = getattr(M, s.id_col)
        namec = getattr(M, s.name_col)
        atc  = getattr(M, s.at_col)
        byc  = getattr(M, s.by_col)
        refc = getattr(M, s.ref_col) if s.ref_col else null()
        where = [M.tenant_id == current_user.tenant_id, byc == current_user.id, M.file_url.isnot(None)]

        if s.per_row:
            q = select(idc, func.max(namec), func.max(atc), func.max(byc), null()).where(*where).group_by(idc)
        else:
            q = select(idc, namec, atc, byc, refc).where(*where)

        for idv, name, at, by, ref in (await db.execute(q)).all():
            by_ids.add(by)
            items.append({
                "id":            f"{s.key}::{idv}",
                "source_key":    s.key,
                "ref_id":        str(idv),
                "source_label":  s.label,
                "category":      s.category,
                "file_name":     name or "(unnamed)",
                "reference":     ref,
                "uploaded_at":   at,
                "link":          s.link_tpl.format(id=idv) if s.link_tpl else None,
                "_by":           by,
            })

    names: dict[int, str] = {}
    if by_ids:
        rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(by_ids)))).all()
        names = {uid: full for uid, full in rows}

    for it in items:
        it["uploaded_by"] = names.get(it.pop("_by"))

    items.sort(key=lambda x: x["uploaded_at"] or datetime.min, reverse=True)
    return items


async def resolve_blob(db: AsyncSession, current_user: User, key: str, ref_id: str) -> Optional[tuple[str, str]]:
    """Re-resolve (blob_path, bucket) for one document, tenant/user-scoped. Returns None if
    the source key is unknown or the row isn't the caller's / has no file."""
    s = SOURCE_BY_KEY.get(key)
    if not s:
        return None
    M = s.model
    idc = getattr(M, s.id_col)
    byc = getattr(M, s.by_col)
    try:
        idval: object = int(ref_id) if s.id_is_int else ref_id
    except (TypeError, ValueError):
        return None
    row = await db.scalar(
        select(M).where(
            idc == idval,
            M.tenant_id == current_user.tenant_id,
            byc == current_user.id,
            M.file_url.isnot(None),
        ).limit(1)
    )
    if not row:
        return None
    return row.file_url, s.bucket()
