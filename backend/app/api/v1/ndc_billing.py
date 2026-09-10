"""Billing endpoints for NDC statements: resolve a party, review, send to billing.

Mounted at `/statements` with LITERAL `/ndc/...` paths, so the public URLs are
`/api/v1/statements/ndc/**` and the frontend's `apiBase` is unchanged.

WHY THIS IS ITS OWN ROUTER AND NOT PART OF `statements.py`. That file is ~1500 lines
serving nine slugs, and every route in it is `/{slug}/…`. A billing route there would
answer for all nine and 404 for eight at request time, and it would double the file every
other statement type is read from. A literal path is refused by the router itself and comes
out right in OpenAPI. It must be registered BEFORE `statements.router` so `/ndc/batches/…`
is not swallowed by `/{slug}/batches/…`.

WHAT IS COPIED FROM `lcc_detailed.py` RATHER THAN IMPORTED. `_resolve_bill_party`,
`_status_counts`, `_recount`, `_owned_row_ids`, `_checked_ids` and the three caps are
fifteen-line functions bound to a different model. Importing them would make the LCC router
a dependency of this one — a change to LCC's worklist would then be a change to NDC's — so
they are reimplemented against `Ndc` with the same shapes and the same error copy.

WHAT IS GENUINELY NEW IS `_owned_header`. NDC keeps no batch header row, so ownership is
proved from the ROWS and the billing header is created lazily on the first write.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database import get_db
from app.dependencies import get_current_user
from app.models.corporate import Corporate
from app.models.customer import Customer
from app.models.statement_batch_billing import StatementBatchBilling
from app.models.statement_row import Ndc
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User
from app.services import customer_resolver as cres
from app.services import ndc_billing_projection as proj
from app.services import ticket_retag as retag

router = APIRouter()

SLUG = proj.SLUG

# The same three caps LCC uses, for the same reasons: a bounded selection, a bounded
# id list behind "select all matching", and a bounded gaps response.
MAX_SEND_ROWS = 500
MAX_BILLING_SELECT_IDS = 500
MAX_GAP_GROUPS = 50

# An NDC statement bills a customer or a corporate. 'agency' is deliberately absent —
# Agency Billing claims tickets through their statement header, not through this link, and
# `_ensure_statement` forces `customer_type='direct'` precisely so it cannot.
_BILL_PARTY_TYPES = ("corporate", "direct")

_BILLING_STATE_PATTERN = "^(" + "|".join((*proj.BILLING_STATES, "sendable")) + ")$"
_LATCH_PATTERN = "^(" + "|".join(proj.LATCH_STATUSES) + "|unlatched)$"

_BILLABLE = proj.BILLABLE_STATUSES


def _scope(model, user: User):
    """Exactly statements.py::_scope — an NDC upload belongs to one user of one tenant."""
    return (model.tenant_id == user.tenant_id, model.created_by_id == user.id)


def _like(value: str) -> str:
    """`%value%` with LIKE wildcards escaped, so a literal `_` searches for itself.
    PNRs and document numbers carry underscores, so this is not decorative."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ══════════════════════════════════════════════════════════════════════════════
# OWNERSHIP + THE LAZY HEADER
# ══════════════════════════════════════════════════════════════════════════════

async def _owned_header(
    db: AsyncSession, batch_id: str, user: User, *, create: bool = False,
) -> StatementBatchBilling:
    """Prove the caller owns this NDC upload, and hand back its billing header.

    NDC keeps no batch header row of its own — an upload is the rows sharing a `batch_id`
    (see api/v1/statements.py::list_batches, which derives the list with a GROUP BY). So
    ownership is proved from the ROWS, under exactly the scope every other NDC endpoint
    enforces, and the billing header is a separate row created LAZILY.

    `create=False` on the read endpoints is what stops merely opening the worklist writing
    to the database. They get a detached in-memory stand-in with the zeroed defaults, which
    reads identically to a batch nobody has resolved yet — because that is what it is.

    404 "Upload not found." matches the generic router's copy exactly, so a stale bookmark
    reads the same on both screens.
    """
    exists = await db.scalar(
        select(func.count()).select_from(Ndc)
        .where(Ndc.batch_id == batch_id, *_scope(Ndc, user))
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Upload not found.")

    header = await db.scalar(
        select(StatementBatchBilling).where(
            StatementBatchBilling.slug == SLUG,
            StatementBatchBilling.batch_id == batch_id,
            *_scope(StatementBatchBilling, user),
        )
    )
    if header is not None:
        return header
    header = StatementBatchBilling(
        tenant_id=user.tenant_id, created_by_id=user.id, slug=SLUG, batch_id=batch_id,
    )
    if create:
        db.add(header)
        await db.flush()
    return header


async def _resolve_bill_party(
    db: AsyncSession, user: User,
    customer_type: str | None, customer_id: int | None, corporate_id: int | None,
    *, upgrade_employee: bool = True,
) -> tuple[str | None, int | None, int | None]:
    """Authorise a party against the master rather than trusting the ids sent.

    Mirrors lcc_detailed.py::_resolve_bill_party. Returns the normalised triple with the
    ids that do not belong to the chosen type nulled — the same discipline as the frontend's
    `buildTagPayload`, enforced server-side so a stale id from a previously chosen type can
    never travel attached to the wrong one.

    `upgrade_employee` turns a picked customer who belongs to a corporate into a 'corporate'
    tag carrying BOTH ids, so the employer can bill their employee's ticket. True for the
    automatic resolver, which is guessing from a passenger name; False wherever a HUMAN
    picked the party, because there it would silently overrule the choice.
    """
    ct = (customer_type or "").strip().lower() or None
    if ct is None:
        return None, None, None
    if ct not in _BILL_PARTY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=("An NDC statement bills a customer or a corporate. Agency billing "
                    "claims tickets through their statement, not through this link."),
        )

    if ct == "corporate":
        if not corporate_id:
            raise HTTPException(status_code=400, detail="Pick a corporate.")
        row = await db.scalar(select(Corporate).where(
            Corporate.id == corporate_id, *_scope(Corporate, user)))
        if not row:
            raise HTTPException(status_code=400,
                                detail=f"Corporate id {corporate_id} is not in your corporates.")
        cust_id = None
        if customer_id:
            cust = await db.scalar(select(Customer).where(
                Customer.id == customer_id, *_scope(Customer, user)))
            if not cust:
                raise HTTPException(status_code=400,
                                    detail=f"Customer id {customer_id} is not in your customers.")
            cust_id = cust.id
        return retag.derive_party("corporate", cust_id, row.id,
                                  upgrade_employee=upgrade_employee)

    if not customer_id:
        raise HTTPException(status_code=400, detail="Pick a customer.")
    cust = await db.scalar(select(Customer).where(
        Customer.id == customer_id, *_scope(Customer, user)))
    if not cust:
        raise HTTPException(status_code=400,
                            detail=f"Customer id {customer_id} is not in your customers.")
    return retag.derive_party("direct", cust.id, None,
                              employee_corporate_id=cust.corporate_id,
                              upgrade_employee=upgrade_employee)


async def _owned_row_ids(db: AsyncSession, batch_id: str, user: User, ids: list[int]) -> None:
    """Every id must be a row of THIS batch, owned by this caller, or nothing runs.

    `project_batch` filters on batch_id alone, so this is where the tenant boundary is
    enforced for any endpoint taking hand-picked ids. Refusing the whole call rather than
    quietly narrowing it also stops the endpoint being used to probe which ids exist.
    """
    found = await db.scalar(
        select(func.count()).select_from(Ndc)
        .where(Ndc.id.in_(ids), Ndc.batch_id == batch_id, *_scope(Ndc, user))
    ) or 0
    if found != len(ids):
        raise HTTPException(status_code=400,
                            detail=f"{len(ids) - found} of the selected rows are not in this upload.")


def _checked_ids(row_ids: list[int] | None, action: str) -> list[int] | None:
    """Normalise a hand-picked selection. None means "the whole upload"."""
    if row_ids is None:
        return None
    ids = list(dict.fromkeys(row_ids))          # dedupe, keep the caller's order
    if not ids:
        # An EXPLICIT empty list is a mistake, not "do everything" — the None/[] split is
        # what keeps a bug in the caller from silently acting on the whole upload.
        raise HTTPException(status_code=400, detail=f"Tick at least one row, or {action}.")
    if len(ids) > MAX_SEND_ROWS:
        raise HTTPException(status_code=400,
                            detail=f"Select at most {MAX_SEND_ROWS} rows at a time, or {action}.")
    return ids


# ══════════════════════════════════════════════════════════════════════════════
# COUNTERS
# ══════════════════════════════════════════════════════════════════════════════

async def _status_counts(db: AsyncSession, batch_id: str) -> dict[str, int]:
    """`{bill_status: n}` for one batch — the chips' source, and _recount's."""
    rows = (await db.execute(
        select(Ndc.bill_status, func.count())
        .where(Ndc.batch_id == batch_id).group_by(Ndc.bill_status)
    )).all()
    return {s: n for s, n in rows}


async def _latch_counts(db: AsyncSession, batch_id: str) -> dict[str, int]:
    """`{bill_latch_status: n}` — how the roll-up landed. No LCC counterpart."""
    rows = (await db.execute(
        select(Ndc.bill_latch_status, func.count())
        .where(Ndc.batch_id == batch_id).group_by(Ndc.bill_latch_status)
    )).all()
    return {s: n for s, n in rows if s}


async def _billing_state_counts(db: AsyncSession, batch_id: str) -> dict[str, int]:
    """`{billing_state: n}` for one batch, over the same LEFT JOIN billing-rows uses.

    Every state in one round trip via COUNT(*) FILTER (WHERE …) rather than nine queries.
    Deliberately NOT narrowed by the caller's filters: this drives header counts, which
    must hold still while you page and search rather than re-describing the filter you
    just typed.
    """
    T = aliased(UploadedTicket)
    row = (await db.execute(
        select(*[func.count().filter(proj.billing_state_cond(s, T)).label(s)
                 for s in proj.BILLING_STATES])
        .select_from(Ndc)
        .outerjoin(T, T.id == Ndc.projected_ticket_id)
        .where(Ndc.batch_id == batch_id)
    )).one()
    return {s: getattr(row, s) or 0 for s in proj.BILLING_STATES}


async def _recount(db: AsyncSession, header: StatementBatchBilling) -> None:
    """Refresh the header's counters from its rows.

    `billable_rows` counts the rows that could carry a party — everything but the payment
    movements AND the latched ones, since a latched row's money is billed on its anchor's
    ticket and counting it would make "41 / 78 billable" read as though half the upload
    were unresolved.
    """
    latch = await _latch_counts(db, header.batch_id)

    header.latched_rows = latch.get(proj.LATCHED, 0)
    header.unlatched_rows = sum(latch.get(s, 0) for s in
                                (proj.ORPHAN, proj.AMBIGUOUS, proj.UNIDENTIFIED))
    header.group_count = await db.scalar(
        select(func.count(func.distinct(Ndc.bill_group_key)))
        .where(Ndc.batch_id == header.batch_id, Ndc.bill_group_key.isnot(None))
    ) or 0

    own_line = await db.scalar(
        select(func.count()).select_from(Ndc).where(
            Ndc.batch_id == header.batch_id,
            or_(Ndc.bill_latch_status.is_(None), Ndc.bill_latch_status != proj.LATCHED),
            or_(Ndc.bill_kind.is_(None), Ndc.bill_kind != "payment"),
        )
    ) or 0
    resolved_own_line = await db.scalar(
        select(func.count()).select_from(Ndc).where(
            Ndc.batch_id == header.batch_id,
            or_(Ndc.bill_latch_status.is_(None), Ndc.bill_latch_status != proj.LATCHED),
            or_(Ndc.bill_kind.is_(None), Ndc.bill_kind != "payment"),
            Ndc.bill_status.in_(_BILLABLE),
        )
    ) or 0

    header.billable_rows = own_line
    header.resolved_rows = resolved_own_line
    header.unresolved_rows = own_line - resolved_own_line
    header.projected_rows = await db.scalar(
        select(func.count()).select_from(Ndc)
        .where(Ndc.batch_id == header.batch_id, Ndc.projected_ticket_id.isnot(None))
    ) or 0
    header.projected_tickets = await db.scalar(
        select(func.count(func.distinct(Ndc.projected_ticket_id))).select_from(Ndc)
        .where(Ndc.batch_id == header.batch_id, Ndc.projected_ticket_id.isnot(None))
    ) or 0


async def _summary(db: AsyncSession, header: StatementBatchBilling, *,
                   customers_in_scope: int, summary: dict[str, int] | None = None,
                   latch: dict[str, int] | None = None) -> dict:
    """The worklist's header, in one shape.

    Returned by both `resolve-customers` (which has just recomputed these in memory) and
    the read-only `billing-summary`, so the frontend has one type and one setter for the
    chips no matter which call refreshed them.
    """
    return {
        "batch_id": header.batch_id,
        "customers_in_scope": customers_in_scope,
        "summary": summary if summary is not None else await _status_counts(db, header.batch_id),
        "latch": latch if latch is not None else await _latch_counts(db, header.batch_id),
        "state_counts": await _billing_state_counts(db, header.batch_id),
        "billable_rows": header.billable_rows,
        "resolved_rows": header.resolved_rows,
        "unresolved_rows": header.unresolved_rows,
        "projected_rows": header.projected_rows,
        "projected_tickets": header.projected_tickets,
        "group_count": header.group_count,
        "latched_rows": header.latched_rows,
        "unlatched_rows": header.unlatched_rows,
        "resolution_status": header.resolution_status,
        "default_customer_type": header.default_customer_type,
        "default_customer_id": header.default_customer_id,
        "default_corporate_id": header.default_corporate_id,
        # Risk 1 in the plan: an upload made before `Payment Amount` was a column has its
        # amounts derived from Total Fare. The screen says so rather than letting the user
        # assume they are reading the airline's own settled figures.
        "settled_amount_rows": await db.scalar(
            select(func.count()).select_from(Ndc).where(
                Ndc.batch_id == header.batch_id,
                Ndc.data["payment_amount"].astext.isnot(None),
            )
        ) or 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. RESOLVE — the roll-up, then the party
# ══════════════════════════════════════════════════════════════════════════════

class ResolvePayload(BaseModel):
    # A human's pick is the most authoritative thing on the row, so a re-run keeps it
    # unless the caller explicitly says otherwise.
    reset_overrides: bool = False


@router.post("/ndc/batches/{batch_id}/resolve-customers")
async def resolve_customers(
    batch_id: str,
    payload: ResolvePayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Roll the rows up per ticket, then match each anchor's passenger to the Customer master.

    ONE PASS, TWO JOBS, IN THAT ORDER. The roll-up has to come first because a latched row
    does not get a party of its own — it inherits its anchor's, so that the worklist reads
    sensibly and so the projection cannot bill an ancillary to someone else.

    This is the only place the grouping is computed. `send-to-billing` reads the columns
    written here, which is what makes "what you saw on the worklist is what you sent" true;
    re-grouping is a deliberate act, and it is this button.
    """
    payload = payload or ResolvePayload()
    header = await _owned_header(db, batch_id, current_user, create=True)

    index = await cres.CustomerIndex.load(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id
    )
    rows = (await db.execute(
        select(Ndc).where(Ndc.batch_id == batch_id, Ndc.is_total.is_(False),
                          *_scope(Ndc, current_user))
        .order_by(func.coalesce(Ndc.row_seq, Ndc.id).asc())
    )).scalars().all()

    now = datetime.utcnow()
    default_set = bool(header.default_customer_type)
    groups = proj.build_groups(rows)
    by_id = {r.id: r for r in rows}
    updates: list[dict] = []
    summary: dict[str, int] = {}
    latch: dict[str, int] = {}

    for group in groups:
        anchor = group.anchor
        row = by_id[anchor.id]
        kind = anchor.kind

        # ── the anchor's party ────────────────────────────────────────────────
        keep_override = (not payload.reset_overrides
                         and row.bill_status == cres.OVERRIDDEN and kind != "payment")
        if keep_override:
            match = cres.CustomerMatch(
                status=cres.OVERRIDDEN, customer_id=row.bill_customer_id,
                corporate_id=row.bill_corporate_id, customer_type=row.bill_customer_type,
                note=row.bill_match_reason,
            )
        elif kind == "payment":
            match = cres.CustomerMatch(status=cres.EXCLUDED, note=cres.REASON[cres.EXCLUDED])
        else:
            match = index.resolve(anchor.data.get("passenger_name"))
            if match.status == cres.UNRESOLVED and default_set:
                # The batch fallback is the primary path in practice: an airline export's
                # passenger names rarely overlap the Customer master at all.
                match = cres.CustomerMatch(
                    status=cres.DEFAULTED,
                    customer_id=header.default_customer_id,
                    corporate_id=header.default_corporate_id,
                    customer_type=header.default_customer_type,
                    display_name=(anchor.data.get("passenger_name") or "").strip(),
                    note="Billed to this upload's default party.",
                )

        for line in group.lines:
            is_anchor = line is anchor
            # A LATCHED line inherits the anchor's party so the worklist reads sensibly,
            # but `is_projectable` still refuses to give it a ticket of its own.
            # Every non-anchor line in a group is LATCHED by construction — an unlatched
            # ancillary is the anchor of a group of its own.
            status = match.status
            reason = (match.note if is_anchor
                      else f"Billed on ticket {anchor.doc or 'the flight line'}.")

            summary[status] = summary.get(status, 0) + 1
            latch[line.latch_status] = latch.get(line.latch_status, 0) + 1
            amount = line.amount
            updates.append({
                "id": line.id,
                "bill_kind": line.kind,
                "bill_status": status,
                "bill_customer_type": match.customer_type,
                "bill_customer_id": match.customer_id,
                "bill_corporate_id": match.corporate_id,
                "bill_match_reason": reason,
                "bill_group_key": line.group_key,
                "bill_is_anchor": is_anchor,
                "bill_latch_status": line.latch_status,
                "bill_amount": amount,
                "resolved_at": now,
                "resolved_by_id": current_user.id,
            })

        # An unlatched ancillary is real money with nowhere to go yet. It keeps whatever
        # party it resolved to but reads as `unlatched` until a human confirms it — see
        # ndc_billing_projection.is_projectable.
        if anchor.latch_status in (proj.ORPHAN, proj.AMBIGUOUS, proj.UNIDENTIFIED):
            updates[-1]["bill_match_reason"] = proj.LATCH_REASON[anchor.latch_status]

    if updates:
        await db.execute(update(Ndc), updates)

    header.resolved_at = now
    if header.resolution_status != "projected":
        header.resolution_status = "resolved"
    await _recount(db, header)
    await db.commit()

    return await _summary(db, header, customers_in_scope=len(index),
                          summary=summary, latch=latch)


# ══════════════════════════════════════════════════════════════════════════════
# 2. SUMMARY — read-only
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/ndc/batches/{batch_id}/billing-summary")
async def billing_summary(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What `resolve-customers` returns, WITHOUT resolving anything.

    The worklist needs these counts every time it opens and after every edit. Getting them
    from the POST meant that merely looking at the screen re-grouped and re-matched every
    row — which, on an upload already sent to billing, could silently re-point a row
    billing already sees. This is the read-only way to ask.
    """
    header = await _owned_header(db, batch_id, current_user)
    in_scope = await db.scalar(
        select(func.count()).select_from(Customer).where(*_scope(Customer, current_user))
    ) or 0
    return await _summary(db, header, customers_in_scope=in_scope)


# ══════════════════════════════════════════════════════════════════════════════
# 3. ROWS — the worklist
# ══════════════════════════════════════════════════════════════════════════════

def _txt(model_field, value: str):
    return model_field.astext.ilike(_like(value), escape="\\")


@router.get("/ndc/batches/{batch_id}/billing-rows")
async def list_billing_rows(
    batch_id: str,
    status_filter: str | None = Query(None, alias="status"),
    billing_state: str | None = Query(None, pattern=_BILLING_STATE_PATTERN),
    latch: str | None = Query(None, pattern=_LATCH_PATTERN),
    group: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=100),
    kind: str | None = Query(None),
    include_latched: bool = Query(False),
    ids_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The resolution worklist, paginated.

    THREE independent filters, because they answer three different questions: `status` is
    the row's MATCH status (does it have a party?), `billing_state` is where it has got to
    on its way into billing, and `latch` is how the roll-up placed it. A row can be "Set by
    you", "Ready to send" and an anchor all at once, so they are never merged.

    ONE LINE PER BILLABLE TICKET BY DEFAULT. Latched rows are hidden because their money is
    on their anchor's line and showing both would read as double-counting; each anchor
    carries `latched_count` and `latched_amount` instead. `include_latched=true` (or
    `group=<key>`) opens one up.

    `ids_only=true` returns just the matching ids, capped, for the "select all N matching"
    affordance. It lives on this endpoint rather than a sibling so the ids can only ever
    come from the same predicate builder as the visible page.
    """
    await _owned_header(db, batch_id, current_user)

    # The join is 1:1 — T.id is a primary key and projected_ticket_id is a FK to it — so a
    # COUNT over the subquery cannot fan out. Do not "fix" it with DISTINCT. UploadedTicket
    # needs no _scope of its own: it is reachable only through projected_ticket_id, which
    # this same scoped pipeline is the only writer of.
    T = aliased(UploadedTicket)
    base = (select(Ndc, T)
            .outerjoin(T, T.id == Ndc.projected_ticket_id)
            .where(Ndc.batch_id == batch_id, Ndc.is_total.is_(False),
                   *_scope(Ndc, current_user)))
    if group:
        base = base.where(Ndc.bill_group_key == group)
    elif not include_latched:
        base = base.where(or_(Ndc.bill_latch_status.is_(None),
                              Ndc.bill_latch_status != proj.LATCHED))
    if status_filter:
        base = base.where(Ndc.bill_status == status_filter)
    if kind:
        base = base.where(Ndc.bill_kind == kind)
    if latch == "unlatched":
        base = base.where(Ndc.bill_latch_status.in_(
            (proj.ORPHAN, proj.AMBIGUOUS, proj.UNIDENTIFIED)))
    elif latch:
        base = base.where(Ndc.bill_latch_status == latch)
    if billing_state:
        base = base.where(proj.billing_state_cond(billing_state, T))
    if q and q.strip():
        # One box over the three identities a user has to hand. `_like` escapes the LIKE
        # wildcards, which matters here: document numbers and PNRs carry underscores.
        term = q.strip()
        base = base.where(or_(_txt(Ndc.data["passenger_name"], term),
                              _txt(Ndc.data["airline_pnr"], term),
                              _txt(Ndc.data["document_no"], term)))

    # Narrowed to the id before counting: the subquery would otherwise carry every column
    # of both tables for no reason.
    total = await db.scalar(
        select(func.count()).select_from(base.with_only_columns(Ndc.id).subquery())
    ) or 0

    order = (func.coalesce(Ndc.row_seq, Ndc.id).asc(), Ndc.id.asc())
    if ids_only:
        ids = (await db.execute(
            base.with_only_columns(Ndc.id).order_by(*order).limit(MAX_BILLING_SELECT_IDS)
        )).scalars().all()
        return {"total": total, "ids": list(ids), "truncated": total > len(ids)}

    pairs = (await db.execute(base.order_by(*order).limit(limit).offset(offset))).all()
    rows = [r for r, _t in pairs]
    tickets = {r.id: t for r, t in pairs}

    # What each anchor rolled up, in ONE grouped query rather than one per row — so
    # "+2 ancillaries · ₹1,400" costs no extra request.
    keys = {r.bill_group_key for r in rows if r.bill_group_key}
    rolled: dict[str, tuple[int, float | None]] = {}
    if keys:
        for key, n, amount in (await db.execute(
            select(Ndc.bill_group_key, func.count(), func.sum(Ndc.bill_amount))
            .where(Ndc.batch_id == batch_id, Ndc.bill_group_key.in_(keys),
                   Ndc.bill_latch_status == proj.LATCHED)
            .group_by(Ndc.bill_group_key)
        )).all():
            rolled[key] = (n, float(amount) if amount is not None else None)

    # Party names for display, in one query rather than per row. The id sets carry the
    # TICKET's party as well as the row's, so a stale row can name both.
    cust_ids = {r.bill_customer_id for r in rows if r.bill_customer_id}
    corp_ids = {r.bill_corporate_id for r in rows if r.bill_corporate_id}
    cust_ids |= {t.customer_id for t in tickets.values() if t is not None and t.customer_id}
    corp_ids |= {t.corporate_id for t in tickets.values() if t is not None and t.corporate_id}
    cust_names = dict((await db.execute(
        select(Customer.id,
               func.concat(Customer.first_name, " ", func.coalesce(Customer.last_name, "")))
        .where(Customer.id.in_(cust_ids or {-1}))
    )).all())
    corp_names = dict((await db.execute(
        select(Corporate.id, Corporate.company).where(Corporate.id.in_(corp_ids or {-1}))
    )).all())

    def _party_name(ct, cust_id, corp_id):
        if ct == "corporate":
            return corp_names.get(corp_id)
        return (cust_names.get(cust_id) or "").strip() or None

    def _row(r):
        t = tickets.get(r.id)
        state = proj.billing_state(r, t)
        data = r.data or {}
        n, amount = rolled.get(r.bill_group_key or "", (0, None))
        return {
            "id": r.id,
            "passenger": data.get("passenger_name"),
            "document_no": data.get("document_no"),
            "airline_pnr": data.get("airline_pnr"),
            "product": data.get("product"),
            "txn_type": data.get("txn_type"),
            "ticket_date": data.get("date_of_issue") or data.get("date_of_booking"),
            "departure_date": data.get("departure_date"),
            "amount": float(r.bill_amount) if r.bill_amount is not None else None,
            "base_fare": data.get("basic_fare"),
            "total_tax": data.get("total_tax"),
            "bill_kind": r.bill_kind,
            "bill_status": r.bill_status,
            "bill_latch_status": r.bill_latch_status,
            "bill_group_key": r.bill_group_key,
            "is_anchor": bool(r.bill_is_anchor),
            "latched_count": n,
            "latched_amount": amount,
            "bill_customer_type": r.bill_customer_type,
            "bill_customer_id": r.bill_customer_id,
            "bill_corporate_id": r.bill_corporate_id,
            "party_name": _party_name(r.bill_customer_type, r.bill_customer_id,
                                      r.bill_corporate_id),
            "customer_name": (cust_names.get(r.bill_customer_id) or "").strip() or None,
            "bill_match_reason": r.bill_match_reason,
            "projected_ticket_id": r.projected_ticket_id,
            "billing_state": state,
            "billing_id": t.billing_id if t is not None else None,
            # Only for a stale row, and it is the whole point of that state: the screen can
            # say "sent as X, now billed to Y" instead of an unexplained warning.
            "billed_party_name": (_party_name(t.customer_type, t.customer_id, t.corporate_id)
                                  if state == "stale" else None),
            "sendable": state in proj.SENDABLE_STATES,
        }

    # No state_counts here on purpose: they cover the whole batch, so recomputing them per
    # page would put a full-batch aggregate behind every search keystroke. The header gets
    # them from billing-summary, which is called after mutations instead.
    return {"total": total, "limit": limit, "offset": offset,
            "rows": [_row(r) for r in rows]}


# ══════════════════════════════════════════════════════════════════════════════
# 4. GAPS — why rows are not ready
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/ndc/batches/{batch_id}/billing-gaps")
async def billing_gaps(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The two independent reasons a row is not ready, grouped with example rows.

    TWO SECTIONS, because they need different things from the user. `party` is "we do not
    know who to bill" and is fixed with a picker. `latch` is "we do not know which ticket
    this ancillary belongs to" and is fixed either by accepting it as its own line or by
    leaving it out. Merging them into one list would ask one question about two problems.

    These only collapse into groups because the reason strings are identical per gap type —
    see customer_resolver.REASON and ndc_billing_projection.LATCH_REASON.
    """
    await _owned_header(db, batch_id, current_user)
    scope = (Ndc.batch_id == batch_id, Ndc.is_total.is_(False), *_scope(Ndc, current_user))

    party = (await db.execute(
        select(Ndc.bill_status, Ndc.bill_match_reason, func.count().label("n"),
               func.array_agg(func.coalesce(Ndc.data["passenger_name"].astext, "—")).label("samples"))
        .where(*scope, Ndc.bill_status.notin_(_BILLABLE),
               or_(Ndc.bill_latch_status.is_(None), Ndc.bill_latch_status != proj.LATCHED))
        .group_by(Ndc.bill_status, Ndc.bill_match_reason)
        .order_by(func.count().desc()).limit(MAX_GAP_GROUPS)
    )).all()

    unlatched = (await db.execute(
        select(Ndc.bill_latch_status, func.count().label("n"),
               func.array_agg(func.coalesce(Ndc.data["airline_pnr"].astext, "—")).label("samples"))
        .where(*scope, Ndc.bill_latch_status.in_(
            (proj.ORPHAN, proj.AMBIGUOUS, proj.UNIDENTIFIED)))
        .group_by(Ndc.bill_latch_status)
        .order_by(func.count().desc())
    )).all()

    return {
        "party": [{
            "status": s, "reason": reason, "count": n,
            # Dedup then cap: one passenger can hold several rows in the same gap.
            "sample_passengers": list(dict.fromkeys(samples or []))[:5],
        } for s, reason, n, samples in party],
        "latch": [{
            "latch_status": s, "reason": proj.LATCH_REASON.get(s), "count": n,
            "sample_pnrs": list(dict.fromkeys(samples or []))[:5],
        } for s, n, samples in unlatched],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5-7. THE PARTY PICKERS
# ══════════════════════════════════════════════════════════════════════════════

class BillingPartyPayload(BaseModel):
    customer_type: str | None = None      # corporate | direct
    customer_id: int | None = None
    corporate_id: int | None = None


@router.patch("/ndc/batches/{batch_id}/billing-default")
async def set_billing_default(
    batch_id: str,
    payload: BillingPartyPayload,
    apply_to: str = Query("unresolved", pattern="^(unresolved|all)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set the upload's fallback party and stamp it onto the rows that need one.

    `apply_to=unresolved` (the default) leaves rows a human or the resolver already settled;
    `all` re-stamps every billable row, overrides included.

    LATCHED ROWS ARE STAMPED TOO, deliberately: they inherit their anchor's party, and a
    default that skipped them would leave the two disagreeing about who a ticket belongs to.
    """
    header = await _owned_header(db, batch_id, current_user, create=True)
    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id,
        # A HUMAN picked this party, so store the one they picked. The employee upgrade
        # belongs to the automatic resolver, which is guessing from a passenger name; here
        # it would silently overrule the choice — pick an employee and the row comes back
        # reading as their corporate, with no way to bill them directly.
        upgrade_employee=False,
    )
    header.default_customer_type = ct
    header.default_customer_id = cust_id
    header.default_corporate_id = corp_id

    rows_updated = 0
    if ct:
        conds = [Ndc.batch_id == batch_id, *_scope(Ndc, current_user),
                 or_(Ndc.bill_kind.is_(None), Ndc.bill_kind != "payment")]
        if apply_to == "unresolved":
            conds.append(Ndc.bill_status.notin_(_BILLABLE))
        result = await db.execute(
            update(Ndc).where(*conds).values(
                bill_status=cres.DEFAULTED,
                bill_customer_type=ct,
                bill_customer_id=cust_id,
                bill_corporate_id=corp_id,
                bill_match_reason="Billed to this upload's default party.",
                resolved_at=datetime.utcnow(),
                resolved_by_id=current_user.id,
            )
        )
        rows_updated = result.rowcount or 0

    if header.resolution_status == "none":
        header.resolution_status = "resolved"
    await _recount(db, header)
    await db.commit()

    return {"batch_id": batch_id, "customer_type": ct, "customer_id": cust_id,
            "corporate_id": corp_id, "rows_updated": rows_updated,
            "resolved_rows": header.resolved_rows,
            "unresolved_rows": header.unresolved_rows}


@router.patch("/ndc/rows/{row_id}/billing-party")
async def set_row_billing_party(
    row_id: int,
    payload: BillingPartyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A human's pick for one row. Survives a re-match unless reset explicitly.

    For an ORPHAN or AMBIGUOUS ancillary this is also the act that makes it projectable —
    see ndc_billing_projection.is_projectable. That is why it is not refused for those.
    """
    row = await db.scalar(select(Ndc).where(Ndc.id == row_id, *_scope(Ndc, current_user)))
    if not row:
        raise HTTPException(status_code=404, detail="Row not found.")
    if row.bill_kind == "payment":
        raise HTTPException(
            status_code=409,
            detail="No money moved on this row, so there is nothing to bill.",
        )
    # A latched row has no line of its own in billing — its money is on the anchor's
    # ticket. Re-pointing it here would change nothing anyone bills and would leave the two
    # permanently disagreeing about the same ticket.
    if row.bill_latch_status == proj.LATCHED:
        doc = (row.data or {}).get("document_no") or "the flight line"
        raise HTTPException(
            status_code=409,
            detail=(f"This row is billed on ticket {doc}. Change that ticket's party "
                    f"instead — this line has no invoice of its own."),
        )
    # Once a row is in billing the TICKET is the thing that exists, and its party is what
    # billing reads; this row is only the record of how it got there.
    if row.projected_ticket_id is not None:
        raise HTTPException(
            status_code=409,
            detail=("This row is already in billing. Change who it is billed to from "
                    "Billing → Sold Tickets, not here."),
        )

    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id,
        upgrade_employee=False,   # a human's pick — see set_billing_default
    )
    row.bill_customer_type = ct
    row.bill_customer_id = cust_id
    row.bill_corporate_id = corp_id
    row.bill_status = cres.OVERRIDDEN if ct else cres.UNRESOLVED
    row.bill_match_reason = None if ct else cres.REASON[cres.UNRESOLVED]
    row.resolved_at = datetime.utcnow()
    row.resolved_by_id = current_user.id

    header = await _owned_header(db, row.batch_id, current_user, create=True)
    await _recount(db, header)
    await db.commit()

    return {"id": row.id, "bill_status": row.bill_status, "customer_type": ct,
            "customer_id": cust_id, "corporate_id": corp_id}


class BulkBillingPartyPayload(BillingPartyPayload):
    row_ids: list[int]


@router.patch("/ndc/batches/{batch_id}/billing-party-bulk")
async def set_rows_billing_party(
    batch_id: str,
    payload: BulkBillingPartyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One party for a hand-picked set of rows — the per-row picker, in bulk.

    Stamped as OVERRIDDEN, exactly like the single-row endpoint, so a human's pick survives
    the next re-match.

    Rows that cannot take a party are SKIPPED and counted, not refused: a payment movement,
    a row already in billing, and a latched row whose money is on its anchor's ticket. The
    single-row endpoint 409s on each because there that row IS the request; here, failing
    forty good rows over one is the wrong trade. Counted separately because the three need
    different things from the user.
    """
    header = await _owned_header(db, batch_id, current_user, create=True)
    ids = _checked_ids(payload.row_ids, "use the default party above")
    await _owned_row_ids(db, batch_id, current_user, ids)

    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id,
        upgrade_employee=False,   # a human's pick — see set_billing_default
    )
    if not ct:
        raise HTTPException(status_code=400, detail="Pick a customer or corporate.")

    picked = (Ndc.id.in_(ids), Ndc.batch_id == batch_id, *_scope(Ndc, current_user))
    result = await db.execute(
        update(Ndc).where(
            *picked,
            # NULL-safe: `bill_kind != 'payment'` would drop never-resolved rows, whose
            # kind is still NULL. See ndc_billing_projection's note on the same trap.
            or_(Ndc.bill_kind.is_(None), Ndc.bill_kind != "payment"),
            or_(Ndc.bill_latch_status.is_(None), Ndc.bill_latch_status != proj.LATCHED),
            Ndc.projected_ticket_id.is_(None),
        ).values(
            bill_status=cres.OVERRIDDEN,
            bill_customer_type=ct,
            bill_customer_id=cust_id,
            bill_corporate_id=corp_id,
            bill_match_reason=None,
            resolved_at=datetime.utcnow(),
            resolved_by_id=current_user.id,
        )
    )
    rows_updated = result.rowcount or 0

    async def _count(*conds) -> int:
        return await db.scalar(
            select(func.count()).select_from(Ndc).where(*picked, *conds)) or 0

    skipped_in_billing = await _count(Ndc.projected_ticket_id.isnot(None))
    skipped_latched = await _count(Ndc.bill_latch_status == proj.LATCHED,
                                  Ndc.projected_ticket_id.is_(None))
    skipped_payments = await _count(Ndc.bill_kind == "payment",
                                    Ndc.projected_ticket_id.is_(None),
                                    or_(Ndc.bill_latch_status.is_(None),
                                        Ndc.bill_latch_status != proj.LATCHED))

    if header.resolution_status == "none":
        header.resolution_status = "resolved"
    await _recount(db, header)
    await db.commit()

    return {"batch_id": batch_id, "customer_type": ct, "customer_id": cust_id,
            "corporate_id": corp_id, "rows_updated": rows_updated,
            "skipped_in_billing": skipped_in_billing,
            "skipped_latched": skipped_latched,
            "skipped_payments": skipped_payments,
            "billable_rows": header.billable_rows,
            "resolved_rows": header.resolved_rows,
            "unresolved_rows": header.unresolved_rows}


# ══════════════════════════════════════════════════════════════════════════════
# 8. SEND
# ══════════════════════════════════════════════════════════════════════════════

class SendToBillingPayload(BaseModel):
    """No body / null → the whole upload, synced. `row_ids` → those rows, added only."""
    row_ids: list[int] | None = Field(default=None)


@router.post("/ndc/batches/{batch_id}/send-to-billing")
async def send_to_billing(
    batch_id: str,
    payload: SendToBillingPayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Project the resolved groups into `uploaded_tickets` so billing can see them.

    Idempotent: re-running syncs rather than duplicates, and any ticket already on an
    invoice is left exactly as it was.

    With `row_ids`, only the groups those rows belong to are touched and nothing is ever
    removed — see project_batch's docstring for why a selective send is additive.
    Withdrawing a ticket from billing stays the whole-upload send's job.
    """
    header = await _owned_header(db, batch_id, current_user, create=True)
    if header.resolution_status == "none":
        raise HTTPException(
            status_code=409,
            detail="Resolve this upload's customers first — nothing here has a party to bill yet.",
        )

    ids = _checked_ids(payload.row_ids if payload else None, "send the whole upload")
    if ids:
        await _owned_row_ids(db, batch_id, current_user, ids)

    result = await proj.project_batch(db, header, row_ids=ids)
    await _recount(db, header)
    await db.commit()
    return {"batch_id": batch_id, **result}
