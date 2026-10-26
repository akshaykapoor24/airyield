"""Remembering the column mapping a statement was saved with, for the vendor's next file.

A vendor sends the same spreadsheet layout statement after statement — TripJack prints
"Posting Date" and "Base Amount" every week — and the alias map cannot know that "Posting
Date" is the Booked / Issue Date. The user tells the mapping step once; this keeps the
answer (models/statement_column_mapping.py) and puts it back in front of them next time.

What a new file is proposed, best first (`propose`):

  1. VENDOR          this vendor's mapping for exactly this column layout — as saved;
  2. VENDOR_CHANGED  this vendor's mapping for a layout that has since changed — kept for
                     the columns still in the file; only the NEW columns are name-matched;
  3. LAYOUT          another vendor's mapping for exactly this layout — two consolidators
                     on the same mid-office software print the same "TICKET STATEMENT";
  4. by name         nothing saved fits: the alias map's own answer, as before.

A column the user SAW and left as "not in file" stays unmapped — name-matching is never
laid over a remembered mapping, only over columns the remembered layout did not have.
That is the difference between remembering a choice and second-guessing it.

Split like services/tp_airline_resolution.py: `propose` is pure and unit-tested without a
database; `load` and `remember` are the queries around it.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.statement_column_mapping import StatementColumnMapping
from app.services.statement_spec import norm

VENDOR = "vendor"
VENDOR_CHANGED = "vendor_changed"
LAYOUT = "layout"

# A changed layout reuses the vendor's mapping only when at least this share of the columns
# it mapped are still in the file. Below that it is a different report from the vendor, not
# a revision of the one it sends, and name-matching is the honest starting point.
_MIN_KEPT = 0.5

# How many of a user's saved mappings of one type are weighed. Far more than anyone keeps —
# one per vendor and layout — and a bound on what one extract reads.
_LOAD_LIMIT = 500


def signature(columns) -> str:
    """The column layout of a file: its column names, normalised ("Ticket No." and
    "ticket no" are one column) and sorted (a column moved is the same layout), hashed."""
    keys = sorted({norm(c) for c in columns if str(c).strip()})
    return hashlib.sha256("|".join(keys).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Saved:
    """One remembered mapping, as `propose` weighs it."""
    signature: str
    columns: tuple[str, ...]
    column_map: dict
    same_vendor: bool
    vendor_name: str | None = None
    source_file: str | None = None
    saved_at: datetime | None = None


@dataclass
class Proposal:
    mapping: dict[str, str]
    match: str | None = None                                # VENDOR / VENDOR_CHANGED / LAYOUT; None = by name
    saved: Saved | None = None
    new_columns: list[str] = field(default_factory=list)    # VENDOR_CHANGED: not in the saved layout
    gone_columns: list[str] = field(default_factory=list)   # VENDOR_CHANGED: mapped before, not in this file

    def info(self) -> dict | None:
        """What the mapping step says about it — None when nothing remembered was used."""
        if self.saved is None:
            return None
        return {
            "match": self.match,
            "vendor_name": self.saved.vendor_name,
            "source_file": self.saved.source_file,
            "saved_at": self.saved.saved_at.isoformat() if self.saved.saved_at else None,
            "fields": len(self.mapping),
            "new_columns": self.new_columns,
            "gone_columns": self.gone_columns,
        }


def propose(columns: list[str], fields: set[str], by_name: dict[str, str],
            saved: list[Saved], *, has_vendor: bool) -> Proposal:
    """The mapping to put in front of the user for a file with `columns`. PURE.

    `saved` newest first. `fields` — the type's fields today: a field dropped from the type
    since a mapping was saved is not carried. `by_name` — the alias map's answer
    ({field: column}). `has_vendor` False (a type that names none, NDC) reuses only an exact
    layout: two airlines' exports overlapping on "Ticket No" are not one layout revised.
    """
    in_file: dict[str, str] = {}
    for c in columns:
        in_file.setdefault(norm(c), c)

    def mapped(s: Saved) -> dict[str, str]:
        return {f: c for f, c in (s.column_map or {}).items() if f in fields and c}

    def carried(s: Saved) -> dict[str, str]:
        return {f: in_file[norm(c)] for f, c in mapped(s).items() if norm(c) in in_file}

    sig = signature(columns)
    mine = [s for s in saved if s.same_vendor] if has_vendor else []

    for s in mine:
        if s.signature == sig:
            return Proposal(carried(s), VENDOR, s)

    best: tuple[Saved, dict[str, str]] | None = None
    for s in mine:
        kept, wanted = carried(s), len(mapped(s))
        if wanted and len(kept) >= wanted * _MIN_KEPT and (best is None or len(kept) > len(best[1])):
            best = (s, kept)
    if best is not None:
        s, kept = best
        known = {norm(c) for c in s.columns}
        new = [c for c in columns if norm(c) not in known]
        used = set(kept.values())
        for f, c in by_name.items():
            if f in fields and f not in kept and c in new and c not in used:
                kept[f] = c
                used.add(c)
        gone = sorted({c for c in mapped(s).values() if norm(c) not in in_file})
        return Proposal(kept, VENDOR_CHANGED, s, new_columns=new, gone_columns=gone)

    # This vendor's own exact layout returned above, so an exact match here is another's.
    for s in saved:
        if s.signature == sig:
            return Proposal(carried(s), LAYOUT, s)

    return Proposal({f: c for f, c in by_name.items() if f in fields})


# ── the queries ──────────────────────────────────────────────────────────────

def _vendor_ids(supplier) -> tuple[int | None, int | None]:
    """(agency_id, supplier_id) of the upload's vendor — as statement_batch_suppliers keys it."""
    if supplier is None:
        return None, None
    return getattr(supplier, "agency_id", None), getattr(supplier, "id", None)


def _same_vendor(row: StatementColumnMapping, agency_id: int | None, supplier_id: int | None) -> bool:
    """By either id, like tp_gds_reupload.vendor_condition: an agency awaiting approval has no
    supplier id yet, and an agency re-onboarded keeps its supplier's."""
    return ((agency_id is not None and row.agency_id == agency_id)
            or (supplier_id is not None and row.supplier_id == supplier_id))


def _owned(user, slug: str):
    M = StatementColumnMapping
    return (M.tenant_id == user.tenant_id, M.created_by_id == user.id, M.slug == slug)


async def load(db: AsyncSession, user, slug: str, supplier) -> list[Saved]:
    """This user's remembered mappings of this type, newest first."""
    agency_id, supplier_id = _vendor_ids(supplier)
    M = StatementColumnMapping
    rows = (await db.execute(
        select(M).where(*_owned(user, slug)).order_by(M.updated_at.desc(), M.id.desc()).limit(_LOAD_LIMIT)
    )).scalars().all()
    return [Saved(signature=r.signature, columns=tuple(r.columns or ()), column_map=dict(r.column_map or {}),
                  same_vendor=_same_vendor(r, agency_id, supplier_id), vendor_name=r.vendor_name,
                  source_file=r.source_file, saved_at=r.updated_at)
            for r in rows]


async def propose_for(db: AsyncSession, user, slug: str, supplier, columns: list[str],
                      fields: set[str], by_name: dict[str, str]) -> Proposal:
    agency_id, supplier_id = _vendor_ids(supplier)
    saved = await load(db, user, slug, supplier)
    return propose(columns, fields, by_name, saved,
                   has_vendor=agency_id is not None or supplier_id is not None)


async def remember(db: AsyncSession, user, slug: str, supplier, columns: list[str],
                   column_map: dict, fields: set[str], *, source_file: str | None,
                   batch_id: str | None) -> StatementColumnMapping | None:
    """Keep the mapping a statement is being saved with. Called inside the save's own
    transaction, so a statement that fails to save leaves no mapping behind.

    Only fields of the type, mapped to a column the file has — a stale field or a column from
    another export would be proposed back as a mapping nobody made. None when nothing is left.
    """
    present = set(columns)
    mapping = {f: c for f, c in (column_map or {}).items()
               if f in fields and isinstance(c, str) and c in present}
    if not mapping:
        return None
    agency_id, supplier_id = _vendor_ids(supplier)
    sig = signature(columns)
    M = StatementColumnMapping
    rows = (await db.execute(
        select(M).where(*_owned(user, slug), M.signature == sig).order_by(M.updated_at.desc(), M.id.desc())
    )).scalars().all()
    if agency_id is None and supplier_id is None:
        row = next((r for r in rows if r.agency_id is None and r.supplier_id is None), None)
    else:
        row = next((r for r in rows if _same_vendor(r, agency_id, supplier_id)), None)

    now = datetime.utcnow()
    if row is None:
        row = M(tenant_id=user.tenant_id, created_by_id=user.id, slug=slug, signature=sig, created_at=now)
        db.add(row)
    # Whole new values, never edited in place: JSONB change tracking sees reassignment only.
    row.agency_id = agency_id if agency_id is not None else row.agency_id
    row.supplier_id = supplier_id if supplier_id is not None else row.supplier_id
    row.vendor_name = getattr(supplier, "name", None) if supplier is not None else None
    row.columns = list(columns)
    row.column_map = mapping
    row.source_file = source_file
    row.batch_id = batch_id
    row.updated_at = now
    return row
