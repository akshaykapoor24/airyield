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

from collections.abc import Collection

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.models.ticket_statement import TicketStatement
from app.models.uploaded_ticket import UploadedTicket
from app.services import customer_resolver as cres

__all__ = [
    "BILLABLE_STATUSES", "BILLING_STATES", "SENDABLE_STATES",
    "billing_state", "billing_state_cond", "project_batch", "projected_ticket_ids",
]

# The statuses that mean "a party has been settled for this row".
BILLABLE_STATUSES = (cres.RESOLVED, cres.DEFAULTED, cres.OVERRIDDEN)

# Where a row stands on its way INTO BILLING — a different question from `bill_status`,
# which says where it stands on its way to a PARTY. Deliberately two vocabularies: a row
# can be "Set by you" and still "Ready to send", and the worklist shows both columns
# because settling one does not settle the other.
#
# Listed in evaluation order. `invoiced` wins over everything because it is the only
# state this system cannot undo — see the frozen-ticket rule in project_batch.
BILLING_STATES = (
    "invoiced",      # on an invoice; frozen, whatever the row now says
    "not_billable",  # a payment movement — no fare, so nothing to bill
    "no_party",      # not in billing, and still has nobody to bill
    "ready",         # has a party, not yet in billing
    "withdrawn",     # in billing, but the row is no longer billable
    "stale",         # in billing, but under a different party than the row now names
    "sent",          # in billing, and billing agrees with the row
)

# Filter-only aggregate: exactly the rows a "send these" would act on.
SENDABLE_STATES = ("ready", "sent", "stale")

_STATEMENT_TYPE = "LCC"          # `statement_type` is String(10); no CHECK on it.
_MAX_SECTOR = 200                # UploadedTicket.sector / .flight_no are String(200)


# ── billing state: one definition, written twice ─────────────────────────────
# `billing_state` classifies a row in Python for the response; `billing_state_cond`
# says the same thing in SQL so the worklist can filter on it. They live together
# because keeping them apart is exactly how they drift.
#
# THE NULL TRAP. A row imported but never resolved has `bill_kind IS NULL`. In Python
# `None != "payment"` is True; in SQL `NULL != 'payment'` is NULL, so the naive
# predicate silently drops those rows out of every result set. That divergence already
# exists in this codebase — lcc_detailed.py's billing-default excludes them, while
# project_batch below includes them — so everything here goes through `_is_payment` and
# its `_not_payment_cond` twin, and the two answers finally agree.


def _is_payment(bill_kind: str | None) -> bool:
    return bill_kind == "payment"


def _not_payment_cond():
    """The SQL twin of `not _is_payment(...)`. Explicitly NULL-safe; see the note above."""
    return or_(LccDetailed.bill_kind.is_(None), LccDetailed.bill_kind != "payment")


def billing_state(row, ticket) -> str:
    """Where one row stands on its way into billing. Pure — no session, no I/O.

    `ticket` is the UploadedTicket this row was projected into, or None. A row whose
    `projected_ticket_id` was nulled underneath it (the FK is ON DELETE SET NULL) also
    arrives here as None and correctly falls back to ready/no_party, rather than
    claiming to be in billing when the ticket is gone.
    """
    projected = ticket is not None
    if projected and ticket.billing_id is not None:
        return "invoiced"
    if _is_payment(row.bill_kind):
        return "not_billable"

    billable = row.bill_status in BILLABLE_STATUSES
    if not projected:
        return "ready" if billable else "no_party"
    if not billable:
        return "withdrawn"

    same_party = (
        ticket.customer_type == row.bill_customer_type
        and ticket.customer_id == row.bill_customer_id
        and ticket.corporate_id == row.bill_corporate_id
    )
    return "sent" if same_party else "stale"


def billing_state_cond(state: str, T):
    """A `billing_state` value (or the `sendable` aggregate) as a SQL condition.

    `T` is an aliased UploadedTicket already LEFT JOINed on `projected_ticket_id`.
    Returns None for an unknown state, so a caller can treat it as "no filter".
    """
    projected = T.id.isnot(None)
    invoiced = and_(projected, T.billing_id.isnot(None))
    not_payment = _not_payment_cond()
    billable = and_(not_payment, LccDetailed.bill_status.in_(BILLABLE_STATUSES))
    # IS NOT DISTINCT FROM, never `=`: two NULL corporate_ids are a MATCH, but
    # `NULL = NULL` is NULL, which would report every direct-billed row as stale.
    same_party = and_(
        T.customer_type.is_not_distinct_from(LccDetailed.bill_customer_type),
        T.customer_id.is_not_distinct_from(LccDetailed.bill_customer_id),
        T.corporate_id.is_not_distinct_from(LccDetailed.bill_corporate_id),
    )
    live = not_(invoiced)          # `invoiced` is built from IS NOT NULL, never NULL itself

    return {
        "invoiced": invoiced,
        "not_billable": and_(live, LccDetailed.bill_kind == "payment"),
        "no_party": and_(live, not_payment, not_(projected), not_(billable)),
        "ready": and_(live, not_(projected), billable),
        "withdrawn": and_(live, not_payment, projected, not_(billable)),
        "stale": and_(live, projected, billable, not_(same_party)),
        "sent": and_(live, projected, billable, same_party),
        # ready ∪ sent ∪ stale collapses to "billable and not frozen", because
        # `billable` already excludes payments and the projected/not split falls away.
        "sendable": and_(live, billable),
    }.get(state)


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


async def project_batch(
    db: AsyncSession, batch: LccDetailedBatch, *, row_ids: Collection[int] | None = None
) -> dict:
    """Sync `uploaded_tickets` to the batch's current resolution. Caller commits.

    Two modes, and the difference is deletion:

      * `row_ids=None` — a full-batch SYNC. Rows that are no longer billable have their
        projections DELETED, which is how a ticket leaves billing.
      * a set of ids — an ADDITIVE, SCOPED pass. Rows outside the set are never read,
        never updated and never deleted; a selected row that has since lost its party is
        reported in `skipped_no_party` rather than un-billed. Withdrawing a projection
        stays the job of the whole-upload send, so that "send these five" can never be
        the thing that quietly removed a sixth.

    The scoping is applied to the row SELECT rather than to the delete branch, so the
    no-cross-deletion guarantee is structural: unselected rows are not in `should` or
    `already`, and there is no code path that could reach them.
    """
    now = datetime.utcnow()
    scoped = row_ids is not None
    if not batch.billing_batch_id:
        # Allocated once and reused forever, so the statement header is stable across
        # every re-projection instead of a new one appearing per run.
        batch.billing_batch_id = str(uuid.uuid4())
        await db.flush()

    await _ensure_statement(db, batch)

    q = select(LccDetailed).where(LccDetailed.batch_id == batch.batch_id)
    if scoped:
        q = q.where(LccDetailed.id.in_(row_ids))
    rows = (await db.execute(q)).scalars().all()

    should = {r.id: r for r in rows
              if r.bill_status in BILLABLE_STATUSES and not _is_payment(r.bill_kind)}
    already = {r.id: r.projected_ticket_id for r in rows if r.projected_ticket_id}

    # Why a selected row did nothing, so the toast can say so instead of reporting a
    # silent "0 added". In unscoped mode these two overlap with `deleted` — they are
    # different axes: "had no party" versus "had a projection that has now gone".
    skipped_not_billable = sum(1 for r in rows if _is_payment(r.bill_kind))
    skipped_no_party = sum(
        1 for r in rows
        if not _is_payment(r.bill_kind) and r.bill_status not in BILLABLE_STATUSES
    )

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
            if scoped:
                # ADDITIVE: the user ticked a row that has since lost its party. That is
                # a request to send it, not to withdraw it — leave the ticket alone and
                # let `skipped_no_party` explain why nothing happened.
                continue
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

    batch.projected_at = now
    # Always the whole batch, both modes — it is the count the uploads list shows.
    batch.projected_rows = await db.scalar(
        select(func.count()).select_from(LccDetailed)
        .where(LccDetailed.batch_id == batch.batch_id,
               LccDetailed.projected_ticket_id.isnot(None))
    ) or 0
    # A scoped send that projected nothing must not claim the batch is in billing.
    if not scoped or batch.projected_rows:
        batch.resolution_status = "projected"

    return {
        "statement_batch_id": batch.billing_batch_id,
        "scoped": scoped,
        "requested": len(rows),
        "created": created,
        "updated": updated,
        # Always 0 when scoped — the delete branch above cannot be reached. The
        # frontend's "N removed" copy relies on that.
        "deleted": deleted,
        "skipped_billed": skipped_billed,
        "skipped_no_party": skipped_no_party,
        "skipped_not_billable": skipped_not_billable,
        "projected_rows": batch.projected_rows,
    }
