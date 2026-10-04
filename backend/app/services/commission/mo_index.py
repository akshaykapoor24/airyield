"""Class, sector and travel date from the mid-office (MO) statement, for pricing TP GDS rows.

Payment Module step 6E: "map class / sectors / date of travel for inclusion and exclusion
validation". A consolidator's GDS statement prints no class at all (blank on every row of
the real export), so every class-restricted deal comes back `needs_data`, and a blank
travel date silently tests travel windows against the issue date. The workspace's own MO
record of the same tickets usually has them.

Same shape as BSP's TGQ enrichment (services/bsp_tgq_enrichment.py): an index built ONCE
per commission run, looked up per row, applied in memory. Nothing is written back into
`third_party_gds.data` — a reprocess rebuilds that column from `raw_data` and would strand
anything stored there — and the values that were used land in the `commission_calculations`
snapshot, which is what the diagnosis and every report read.

WHICH MO TICKETS COUNT. The vendor's own MO uploads (one file per vendor, linked through
`statement_batch_suppliers` slug `mo-gds`), plus tickets a person has filed under this
vendor from another vendor's MO file (`mo_vendor_corrections`), minus tickets filed away
from it. Where a ticket appears in several uploads the newest wins, as in TGQ.

THE KEY is the normalised document serial — the same `_norm` the reconciliation joins on —
with the airline prefix as a CHECK: a serial is unique only within one airline.

Deliberately imports nothing from `services/payment_reconciliation.py`: that module imports
the commission runner, and this one is imported by the commission adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_ledger import MoVendorCorrection
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import STATEMENT_MODELS
from app.services import statement_balance
from app.services.reconciliation.adapters import _iso_date, _norm, _s, _split_joined

MO_SLUG = "mo-gds"


@dataclass(frozen=True)
class MoTicket:
    """What the MO record says about one ticket — only the fields pricing can use."""
    booking_class: str | None = None
    sector: str | None = None
    travel_date: date | None = None
    segment_type: str | None = None
    batch_id: str | None = None
    source_file: str | None = None


def ticket_parts(data: dict) -> tuple[str | None, str | None]:
    """(normalised serial, 3-digit prefix) — the reconciliation's own join key."""
    tn = _s(data.get("ticket_number"))
    prefix = _s(data.get("ticket_prefix"))
    if tn and not prefix:
        code, serial = _split_joined(tn)
        if code:
            prefix, tn = code, serial
    return _norm(tn), (prefix.zfill(3) if prefix else None)


class MoIndex:
    """serial → [(prefix, MoTicket)], newest upload first."""

    def __init__(self) -> None:
        self._by_serial: dict[str, list[tuple[str | None, MoTicket]]] = {}

    def __len__(self) -> int:
        return len(self._by_serial)

    def add(self, serial: str, prefix: str | None, ticket: MoTicket) -> None:
        self._by_serial.setdefault(serial, []).append((prefix, ticket))

    def lookup(self, data: dict) -> MoTicket | None:
        """The MO ticket for a vendor row's `data`, or None.

        A prefix on both sides that disagrees is a different airline's ticket under the same
        serial — never borrowed from."""
        serial, prefix = ticket_parts(data)
        if not serial:
            return None
        for mo_prefix, ticket in self._by_serial.get(serial, []):
            if prefix and mo_prefix and prefix != mo_prefix:
                continue
            return ticket
        return None


def fold_rows(rows) -> MoIndex:
    """`[(batch_id, source_file, data)]`, newest upload first → an index.

    A ticket's rows within its winning upload are merged field by field (an issue and its
    cancellation usually carry the same class and sector); an older upload of the same
    ticket is ignored.
    """
    index = MoIndex()
    merged: dict[str, dict] = {}
    winner: dict[str, str] = {}
    order: list[str] = []
    for batch_id, source_file, data in rows:
        data = data or {}
        if statement_balance.is_balance_row(data):
            continue
        serial, prefix = ticket_parts(data)
        if not serial:
            continue
        if serial in winner and winner[serial] != batch_id:
            continue                      # an older upload of a ticket already indexed
        winner[serial] = batch_id
        m = merged.get(serial)
        if m is None:
            m = merged[serial] = {"prefix": prefix, "batch_id": batch_id,
                                  "source_file": source_file}
            order.append(serial)
        for key in ("booking_class", "sector", "segment_type"):
            if not m.get(key) and _s(data.get(key)):
                m[key] = _s(data.get(key))
        if not m.get("travel_date"):
            m["travel_date"] = _iso_date(data.get("travel_date"))
    for serial in order:
        m = merged[serial]
        index.add(serial, m["prefix"], MoTicket(
            booking_class=m.get("booking_class"), sector=m.get("sector"),
            travel_date=m.get("travel_date"), segment_type=m.get("segment_type"),
            batch_id=m["batch_id"], source_file=m.get("source_file"),
        ))
    return index


async def load_mo_index(db: AsyncSession, tenant_id: int, user_id: int,
                        supplier_id: int | None) -> MoIndex:
    """Every MO ticket this vendor's statement rows may borrow class/sector/date from."""
    index = MoIndex()
    if supplier_id is None:
        return index
    m = STATEMENT_MODELS[MO_SLUG]
    own = set((await db.execute(
        select(StatementBatchSupplier.batch_id).where(
            StatementBatchSupplier.slug == MO_SLUG,
            StatementBatchSupplier.supplier_id == supplier_id,
            StatementBatchSupplier.tenant_id == tenant_id)
    )).scalars().all())

    corrections = (await db.execute(
        select(MoVendorCorrection.mo_batch_id, MoVendorCorrection.ticket_key,
               MoVendorCorrection.to_supplier_id).where(
            MoVendorCorrection.tenant_id == tenant_id,
            MoVendorCorrection.created_by_id == user_id)
    )).all()
    moved_away = {(b, k) for b, k, to in corrections if b in own and to != supplier_id}
    moved_in = {(b, k) for b, k, to in corrections if to == supplier_id and b not in own}

    batches = own | {b for b, _k in moved_in}
    if not batches:
        return index
    rows = (await db.execute(
        select(m.batch_id, m.source_file, m.data)
        .where(m.tenant_id == tenant_id, m.created_by_id == user_id,
               m.batch_id.in_(batches))
        .order_by(m.uploaded_at.desc(), m.id.asc())
    )).all()

    kept = []
    for batch_id, source_file, data in rows:
        serial, _prefix = ticket_parts(data or {})
        key = f"k:{serial}" if serial else None
        if batch_id in own:
            if key and (batch_id, key) in moved_away:
                continue
        elif not key or (batch_id, key) not in moved_in:
            continue
        kept.append((batch_id, source_file, data))
    return fold_rows(kept)
