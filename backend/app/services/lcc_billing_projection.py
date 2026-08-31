"""Project resolved LCC statement rows into `uploaded_tickets` so they can be billed.

Customer and Corporate Billing read exactly one table — `uploaded_tickets` — written
from exactly one place, `api/v1/tickets.py::_build_uploaded_tickets`. LCC rows live in
`lcc_detailed` and are invisible to it. This module is the bridge: it turns the rows a
user has resolved to a Customer/Corporate into tickets carrying that party link, under
one `TicketStatement` header per LCC batch.

Follows `_build_uploaded_tickets`' contract (tickets.py:336-341): rows are BUILT, not
added to the session; the caller owns the transaction; and `ticket_status`,
`is_billed`/`billing_id` and the whole `matched_deal_*` / incentive block are left
unset because they belong to run-calculation, not to import.

Two invariants worth stating up front:

  * **Idempotency is keyed on the stored `projected_ticket_id` FK**, not on a natural
    key. LCC issues no ticket number and `record_locator` repeats up to four times per
    PNR, so there is nothing else stable to match on.
  * **A ticket that carries a `billing_id` is frozen.** Re-resolving a batch must never
    edit or delete a row that is already on an invoice.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.models.ticket_statement import TicketStatement
from app.models.uploaded_ticket import UploadedTicket
from app.services import customer_resolver as cres

__all__ = ["BILLABLE_STATUSES", "project_batch", "projected_ticket_ids"]

# The statuses that mean "a party has been settled for this row".
BILLABLE_STATUSES = (cres.RESOLVED, cres.DEFAULTED, cres.OVERRIDDEN)

_STATEMENT_TYPE = "LCC"          # `statement_type` is String(10); no CHECK on it.
_MAX_SECTOR = 200                # UploadedTicket.sector / .flight_no are String(200)


def _iso_date(value) -> str | None:
    """UploadedTicket stores every date as a string, parsed lazily by
    billing_calc.safe_date. Normalise to ISO so `safe_date`'s fast path hits."""
    if value is None:
        return None
    d = value.date() if isinstance(value, datetime) else value
    try:
        return d.isoformat()
    except AttributeError:
        return str(value)


def _join_segments(segments, slot: str) -> str | None:
    if not segments:
        return None
    parts = [str(s.get(slot)).strip() for s in segments if isinstance(s, dict) and s.get(slot)]
    if not parts:
        return None
    return " / ".join(parts)[:_MAX_SECTOR]


def _tax_breakup(taxes) -> dict | None:
    """`lcc_detailed.taxes` is `[{code, amount}]`; UploadedTicket.tax_breakup is a dict.

    Note the column holds the JSON `null` LITERAL rather than SQL NULL for rows with no
    taxes, so `or []` is doing real work here — any SQL predicate on this column has to
    use `jsonb_typeof(...)`, never `IS NULL`.
    """
    out = {}
    for t in (taxes or []):
        if isinstance(t, dict) and t.get("code"):
            out[str(t["code"])] = t.get("amount")
    return out or None


def _build_ticket(row: LccDetailed, batch: LccDetailedBatch, *, now: datetime) -> dict:
    """The LCC → UploadedTicket field map, as a dict of column values.

    Returned as a mapping rather than an ORM object so the same function serves both
    the INSERT and the in-place UPDATE of an already-projected ticket.
    """
    first, last = cres.split_person_name(row.name1)
    kind = row.bill_kind or ""

    return {
        # provenance
        "batch_id": batch.billing_batch_id,
        "file_name": batch.source_file or "LCC Statement",
        "tenant_id": row.tenant_id,
        "created_by_id": row.created_by_id,
        "created_at": now,
        "statement_type": _STATEMENT_TYPE,

        # money — `total_amt` IS the billing base: customers.py:521 reads it first and
        # falls back to sell_fare only when it is NULL. Signed, so a refund projects
        # as a negative line with no extra negation step.
        "total_amt": row.total,
        "net_amt": row.total,
        "sell_fare": row.base_fare,
        "sell_tax": row.taxes_total,
        "booking_fee_sell": row.other_fee_total,
        # LCC's SSR money is the scalar column; `lcc_detailed.ssr` is hard-nulled at
        # ingest (lcc_detailed_spec.py) and must not be read.
        "seat_selection": row.other_ssr_total,

        # identity — name1 is the only per-row identity in an LCC export. first/last
        # are populated too so a row that ends up with no party link is still findable
        # by the billing screens' passenger-name fallback.
        "pax_name": row.name1,
        "first_name": first,
        "last_name": last,
        # LCC issues no ticket number. Do NOT synthesise one: _find_original_ticket and
        # BSP reconciliation both key on it.
        "ticket_number": None,
        "booking_ref": row.record_locator,
        "air_pnr": row.record_locator,
        "gds_pnr": row.gds_record_locator,

        # flight
        "airline_name": row.airline_name,
        "airlines_code": row.airline_code,
        "sector": _join_segments(row.segments, "route"),
        "flight_no": _join_segments(row.segments, "flight_no"),
        "booking_class": row.product_class,
        "segment_type": None if row.international is None else ("International" if row.international else "Domestic"),
        "ticket_date": _iso_date(row.transaction_date),
        "departure_datetime": _iso_date(row.departure_date),
        "travel_dt": _iso_date(row.departure_date),

        # classification. `invoice_type` is deliberately left None:
        # tickets.py::_CANCELLED_INVOICE_TYPES drives cancellation matching off
        # "refund"/"credit note", and the sign of total_amt already carries that
        # meaning here — setting it would perturb an unrelated path.
        "transaction_type": "REFUND" if kind == "refund" else "SALE",
        "document_type": _STATEMENT_TYPE,
        "invoice_type": None,
        "currency": None,

        # party
        "customer_type": row.bill_customer_type,
        "customer_id": row.bill_customer_id,
        "corporate_id": row.bill_corporate_id,
        "customer_agency_id": None,
        "sold_to": "customer",

        # audit
        "tax_breakup": _tax_breakup(row.taxes),
        "segments": row.segments,
        "raw_data": {
            "lcc_detailed_id": row.id,
            "lcc_batch_id": row.batch_id,
            "bill_kind": row.bill_kind,
            "bill_status": row.bill_status,
            "bill_match_reason": row.bill_match_reason,
        },
    }


# `currency` is not a column on UploadedTicket; drop it rather than let a typo ride.
_TICKET_COLUMNS = {c.key for c in UploadedTicket.__table__.columns}


def _clean(values: dict) -> dict:
    return {k: v for k, v in values.items() if k in _TICKET_COLUMNS}


async def projected_ticket_ids(db: AsyncSession, batch_id: str) -> dict[int, int]:
    """`{lcc_detailed.id: uploaded_tickets.id}` for everything already projected."""
    rows = (await db.execute(
        select(LccDetailed.id, LccDetailed.projected_ticket_id)
        .where(LccDetailed.batch_id == batch_id, LccDetailed.projected_ticket_id.isnot(None))
    )).all()
    return {lcc_id: tid for lcc_id, tid in rows}


async def _ensure_statement(db: AsyncSession, batch: LccDetailedBatch) -> TicketStatement:
    """One statement header per LCC batch, created once and refreshed thereafter.

    THE AGENCY GUARD. `services/agency_account.py::agency_statement_scope` claims a
    statement when either `agency_id == <agency>` OR (`agency_id IS NULL` AND the
    `agency` text equals an agency's name AND `customer_type IN (NULL, 'agency')`).

      * `agency_id = None` is set EXPLICITLY — tickets.py:511 shows a payload can leak
        an agency_id onto a non-agency statement, so the type alone is not a guard.
      * `customer_type = 'direct'` is the actual guarantee: it fails the third
        conjunct regardless of what the `agency` text happens to say.
      * The "LCC …" prefix on `agency` is defence in depth, not the proof.

    The same three-way test appears in api/v1/reports.py, so this header is excluded
    from supplier income reports too.
    """
    stmt = await db.scalar(
        select(TicketStatement).where(TicketStatement.batch_id == batch.billing_batch_id)
    )

    period = (await db.execute(
        select(func.min(LccDetailed.transaction_date), func.max(LccDetailed.transaction_date))
        .where(LccDetailed.batch_id == batch.batch_id)
    )).one()
    today = datetime.utcnow().date()
    valid_from = (period[0].date() if isinstance(period[0], datetime) else period[0]) or today
    valid_to = (period[1].date() if isinstance(period[1], datetime) else period[1]) or today

    airline = batch.airline_name or "Statement"
    name = f"LCC - {airline} - {batch.source_file or batch.batch_id}"
    agency_label = f"LCC {batch.airline_code or ''} {airline}".replace("  ", " ").strip()

    if stmt is None:
        stmt = TicketStatement(
            batch_id=batch.billing_batch_id,
            tenant_id=batch.tenant_id,
            created_by_id=batch.created_by_id,
            created_at=datetime.utcnow(),
            statement_type=_STATEMENT_TYPE,
            file_name=batch.source_file or "LCC Statement",
            file_url=None,
        )
        db.add(stmt)

    stmt.statement_name = name
    stmt.agency = agency_label
    stmt.agency_id = None
    stmt.customer_type = "direct"
    stmt.customer_agency_id = None
    stmt.corporate_id = None
    stmt.customer_id = None
    stmt.valid_from = valid_from
    stmt.valid_to = valid_to
    return stmt


async def project_batch(db: AsyncSession, batch: LccDetailedBatch) -> dict:
    """Sync `uploaded_tickets` to the batch's current resolution. Caller commits."""
    now = datetime.utcnow()
    if not batch.billing_batch_id:
        # Allocated once and reused forever, so the statement header is stable across
        # every re-projection instead of a new one appearing per run.
        batch.billing_batch_id = str(uuid.uuid4())
        await db.flush()

    await _ensure_statement(db, batch)

    rows = (await db.execute(
        select(LccDetailed).where(LccDetailed.batch_id == batch.batch_id)
    )).scalars().all()

    should = {r.id: r for r in rows
              if r.bill_status in BILLABLE_STATUSES and r.bill_kind != "payment"}
    already = {r.id: r.projected_ticket_id for r in rows if r.projected_ticket_id}

    tickets = {}
    if already:
        found = (await db.execute(
            select(UploadedTicket).where(UploadedTicket.id.in_(set(already.values())))
        )).scalars().all()
        tickets = {t.id: t for t in found}

    created = updated = deleted = skipped_billed = 0

    # ── update or free the rows already projected ────────────────────────────
    for lcc_id, ticket_id in already.items():
        ticket = tickets.get(ticket_id)
        if ticket is None:
            # The ticket was deleted underneath us; the FK already nulled the link.
            continue
        if ticket.billing_id is not None:
            # FROZEN: on an invoice. Never edited, never removed, whatever the
            # resolution now says.
            skipped_billed += 1
            should.pop(lcc_id, None)
            continue
        row = should.pop(lcc_id, None)
        if row is None:
            await db.delete(ticket)
            deleted += 1
            continue
        for key, value in _clean(_build_ticket(row, batch, now=now)).items():
            if key != "created_at":          # keep the original import timestamp
                setattr(ticket, key, value)
        updated += 1

    # ── insert what is newly billable ────────────────────────────────────────
    for row in should.values():
        ticket = UploadedTicket(**_clean(_build_ticket(row, batch, now=now)))
        db.add(ticket)
        await db.flush()                     # assign the PK before linking back
        row.projected_ticket_id = ticket.id
        created += 1

    batch.resolution_status = "projected"
    batch.projected_at = now
    batch.projected_rows = await db.scalar(
        select(func.count()).select_from(LccDetailed)
        .where(LccDetailed.batch_id == batch.batch_id,
               LccDetailed.projected_ticket_id.isnot(None))
    ) or 0

    return {
        "statement_batch_id": batch.billing_batch_id,
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "skipped_billed": skipped_billed,
        "projected_rows": batch.projected_rows,
    }
