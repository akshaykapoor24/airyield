"""Billing endpoints for Third Party API statements: resolve a party, review, send to billing.

Mounted at `/statements` with LITERAL `/tp-api/...` paths, so the public URLs are
`/api/v1/statements/tp-api/**` and the frontend's `apiBase` is unchanged. It must be
registered BEFORE `statements.router` — every route in that file is `/{slug}/…` and would
swallow these.

A COPY OF `ndc_billing.py`, NOT A GENERALISATION OF IT, and the same deliberate choice that
file made of `lcc_detailed.py`. NDC is the right ancestor because what it invented over LCC is
`_owned_header`: a spec-driven type keeps no batch header row, so ownership is proved from the
ROWS and the billing header is created lazily — exactly this type's situation, and something
LCC has no version of. Generalising the two would mean parameterising the model, the `data`
key names, the state vocabulary, the gaps sections and every counter: a framework in Python
for two callers.

WHAT IS DIFFERENT FROM NDC, and it is all one difference. An NDC export writes ancillaries as
document-less lines that must be LATCHED onto the flight they belong to; an aggregator booking
is one line and one ticket. So `ThirdPartyApi` carries no `_RollUpMixin`, and everything
downstream of that goes: the `latch` / `include_latched` / `group` filters, `_latch_counts`,
the group counters, the rolled-up amount on each row, and the latch half of `billing-gaps`.

WHAT IS NEW. This is the only billable type whose file carries more than one product. Every
CATEGORY bills — flight, hotel, train, bus and car each become a ticket carrying its
`product_category`, and billing prices it under the party's markup for that category — but a
row can still be out for a reason that has nothing to do with its product: a refund with no
payment on this statement (`needs_review`), a pending payment, a cancellation that netted to
nothing, a product no markup category covers (`no_category`, e.g. Visa). So `bill_kind` has
several not-billable values instead of one, `billing-gaps` gains an `excluded` section grouped
by kind and product and carrying the MONEY, and the summary reports `total_rows` /
`category_counts` / `not_billable_rows` so no screen can state a numerator without its
denominator. TBO's cancellation and refund-memo lines are CREDITS, not exclusions — see
`tp_api_billing_projection.TBO_CREDIT_SERIES`.

AN UPLOAD CLASSIFIED BEFORE CATEGORIES BILLED still has its hotel and train rows stored as
`not_flight`. Nothing migrates them: the summary counts them as `needs_rematch`, the worklist
offers a Re-match, and re-classifying is exactly what `resolve-customers` already does.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

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
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import ThirdPartyApi
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User
from app.services import customer_resolver as cres
from app.services import employee_from_passenger as emp
from app.services import markup_categories as mc
from app.services import ticket_retag as retag
from app.services import tp_api_billing_projection as proj
from app.services import tp_api_itinerary as itin
from app.services import tp_api_spec as tp

router = APIRouter()

SLUG = proj.SLUG

# The same three caps LCC and NDC use, for the same reasons.
MAX_SEND_ROWS = 500
MAX_BILLING_SELECT_IDS = 500
MAX_GAP_GROUPS = 50

# An aggregator statement bills a customer or a corporate. 'agency' is deliberately absent —
# Agency Billing claims tickets through their statement header, not through this link, and
# `_ensure_statement` forces `customer_type='direct'` precisely so it cannot.
_BILL_PARTY_TYPES = ("corporate", "direct")

_BILLING_STATE_PATTERN = "^(" + "|".join((*proj.BILLING_STATES, "sendable")) + ")$"
_KIND_PATTERN = "^(" + "|".join(proj.BILL_KINDS) + "|billable|not_billable)$"

_BILLABLE = proj.BILLABLE_STATUSES


def _scope(model, user: User):
    """Exactly statements.py::_scope — a tp-api upload belongs to one user of one tenant."""
    return (model.tenant_id == user.tenant_id, model.created_by_id == user.id)


def _like(value: str) -> str:
    """`%value%` with LIKE wildcards escaped, so a literal `_` searches for itself.
    Booking ids and invoice numbers carry underscores and slashes, so this is not decorative."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _txt(model_field, value: str):
    return model_field.astext.ilike(_like(value), escape="\\")


# ══════════════════════════════════════════════════════════════════════════════
# OWNERSHIP + THE LAZY HEADER
# ══════════════════════════════════════════════════════════════════════════════

async def _owned_header(
    db: AsyncSession, batch_id: str, user: User, *, create: bool = False,
) -> StatementBatchBilling:
    """Prove the caller owns this upload, and hand back its billing header.

    A spec-driven type keeps no batch header row of its own — an upload is the rows sharing a
    `batch_id` (see api/v1/statements.py::list_batches, which derives the list with a GROUP
    BY). So ownership is proved from the ROWS, under exactly the scope every other endpoint
    on this type enforces, and the billing header is a separate row created LAZILY.

    `create=False` on the read endpoints is what stops merely opening the worklist writing to
    the database. They get a detached in-memory stand-in with the zeroed defaults, which
    reads identically to a batch nobody has resolved yet — because that is what it is.

    `statement_batch_billing` needs no change to serve this slug: it is keyed `(slug,
    batch_id)` with no foreign key, named for the slug space rather than for NDC.
    """
    exists = await db.scalar(
        select(func.count()).select_from(ThirdPartyApi)
        .where(ThirdPartyApi.batch_id == batch_id, *_scope(ThirdPartyApi, user))
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


async def _batch_context(db: AsyncSession, batch_id: str, user: User) -> dict:
    """The file name, the detected vendor and the declared consolidator, for the projection.

    The consolidator is the one the UPLOADER declared (tp-api is `requires_supplier`), which
    is who actually issued the statement; the detected vendor label is the fallback for a file
    whose header row matched no known aggregator.
    """
    row = await db.scalar(
        select(ThirdPartyApi)
        .where(ThirdPartyApi.batch_id == batch_id, *_scope(ThirdPartyApi, user))
        .order_by(ThirdPartyApi.id.asc()).limit(1)
    )
    supplier = await db.scalar(
        select(StatementBatchSupplier).where(
            StatementBatchSupplier.slug == SLUG,
            StatementBatchSupplier.batch_id == batch_id,
        )
    )
    vendor = None
    if row is not None:
        vendor = (row.data or {}).get("vendor") or tp.format_label(row.source_format)
    return {
        "source_file": row.source_file if row is not None else None,
        "vendor": vendor,
        "supplier_name": supplier.supplier_name if supplier is not None else None,
    }


async def _resolve_bill_party(
    db: AsyncSession, user: User,
    customer_type: str | None, customer_id: int | None, corporate_id: int | None,
    *, upgrade_employee: bool = True,
) -> tuple[str | None, int | None, int | None]:
    """Authorise a party against the master rather than trusting the ids sent.

    Mirrors ndc_billing.py::_resolve_bill_party. Returns the normalised triple with the ids
    that do not belong to the chosen type nulled, so a stale id from a previously chosen type
    can never travel attached to the wrong one.

    `upgrade_employee` turns a picked customer who belongs to a corporate into a 'corporate'
    tag carrying BOTH ids. True for the automatic resolver, which is guessing from a passenger
    name; False wherever a HUMAN picked the party, because there it would overrule the choice.
    """
    ct = (customer_type or "").strip().lower() or None
    if ct is None:
        return None, None, None
    if ct not in _BILL_PARTY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=("An aggregator statement bills a customer or a corporate. Agency billing "
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
        select(func.count()).select_from(ThirdPartyApi)
        .where(ThirdPartyApi.id.in_(ids), ThirdPartyApi.batch_id == batch_id,
               *_scope(ThirdPartyApi, user))
    ) or 0
    if found != len(ids):
        raise HTTPException(status_code=400,
                            detail=f"{len(ids) - found} of the selected rows are not in this upload.")


def _checked_ids(row_ids: list[int] | None, action: str) -> list[int] | None:
    """Normalise a hand-picked selection. None means "the whole upload"."""
    if row_ids is None:
        return None
    ids = list(dict.fromkeys(row_ids))
    if not ids:
        # An EXPLICIT empty list is a mistake, not "do everything".
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
        select(ThirdPartyApi.bill_status, func.count())
        .where(ThirdPartyApi.batch_id == batch_id).group_by(ThirdPartyApi.bill_status)
    )).all()
    return {s: n for s, n in rows}


async def _category_counts(db: AsyncSession, batch_id: str) -> dict[str, dict]:
    """`{category slug: {rows, amount, credit_rows}}` over the BILLABLE rows only.

    What the worklist's category strip is drawn from — "40 train · ₹62,929". Grouped on the
    raw product text and folded onto slugs in Python, so "Flight" and "flight" land in one
    bucket without a CASE expression that would have to be repeated in the GROUP BY.
    """
    col = ThirdPartyApi.data["product_type"].astext
    rows = (await db.execute(
        select(col, ThirdPartyApi.bill_kind, func.count(),
               func.coalesce(func.sum(ThirdPartyApi.bill_amount), 0))
        .where(ThirdPartyApi.batch_id == batch_id,
               ThirdPartyApi.bill_kind.in_(proj.BILLABLE_KINDS))
        .group_by(col, ThirdPartyApi.bill_kind)
    )).all()
    out: dict[str, dict] = {}
    for product, kind, n, amount in rows:
        slug = mc.category_slug(product)
        if slug is None:
            continue
        bucket = out.setdefault(slug, {"label": mc.CATEGORY_LABELS.get(slug, slug),
                                       "rows": 0, "amount": 0.0, "credit_rows": 0})
        bucket["rows"] += n
        bucket["amount"] = round(bucket["amount"] + float(amount or 0), 2)
        if kind == proj.REFUND:
            bucket["credit_rows"] += n
    # In the order the markup form renders the categories, so the strip never reshuffles.
    return {s: out[s] for s in mc.CATEGORY_SLUGS if s in out}


async def _kind_counts(db: AsyncSession, batch_id: str) -> dict[str, int]:
    """`{bill_kind: n}` — sale/refund and every reason a row is out.

    No NDC counterpart worth the name: there, three kinds and one of them unbillable. Here it
    is what the coverage banner and the send toast are built from.
    """
    rows = (await db.execute(
        select(ThirdPartyApi.bill_kind, func.count())
        .where(ThirdPartyApi.batch_id == batch_id).group_by(ThirdPartyApi.bill_kind)
    )).all()
    return {s: n for s, n in rows if s}


async def _product_counts(db: AsyncSession, batch_id: str) -> dict[str, int]:
    """`{product_type: n}` — how the whole file splits across Flight / Hotel / Train / Bus / Car,
    billable or not."""
    # GROUP BY the bare JSON accessor, not a coalesce of it: an expression built twice
    # renders as two different expressions with two different bind params, and Postgres then
    # refuses the select as not-in-the-GROUP-BY. The NULL bucket is named in Python instead.
    col = ThirdPartyApi.data["product_type"].astext
    rows = (await db.execute(
        select(col, func.count())
        .where(ThirdPartyApi.batch_id == batch_id).group_by(col)
    )).all()
    return {(s or "—"): n for s, n in rows}


async def _billing_state_counts(db: AsyncSession, batch_id: str) -> dict[str, int]:
    """`{billing_state: n}` for one batch, over the same LEFT JOIN billing-rows uses.

    Every state in one round trip via COUNT(*) FILTER (WHERE …). Deliberately NOT narrowed by
    the caller's filters: this drives header counts, which must hold still while you page and
    search rather than re-describing the filter you just typed.
    """
    T = aliased(UploadedTicket)
    row = (await db.execute(
        select(*[func.count().filter(proj.billing_state_cond(s, T)).label(s)
                 for s in proj.BILLING_STATES])
        .select_from(ThirdPartyApi)
        .outerjoin(T, T.id == ThirdPartyApi.projected_ticket_id)
        .where(ThirdPartyApi.batch_id == batch_id)
    )).one()
    return {s: getattr(row, s) or 0 for s in proj.BILLING_STATES}


async def _recount(db: AsyncSession, header: StatementBatchBilling) -> None:
    """Refresh the header's counters from its rows.

    `billable_rows` counts the rows that COULD carry a party — every category's sales and
    credits, but not the pending, the nil and the uncategorised. That is what makes "60 / 62
    billable" honest on a 64-row upload, and it is why `total_rows` is reported alongside it:
    the denominator of the Billing column and the size of the file are different numbers, and
    the screens have to show both.
    """
    billable = await db.scalar(
        select(func.count()).select_from(ThirdPartyApi).where(
            ThirdPartyApi.batch_id == header.batch_id,
            proj._billable_kind_cond(),
        )
    ) or 0
    resolved = await db.scalar(
        select(func.count()).select_from(ThirdPartyApi).where(
            ThirdPartyApi.batch_id == header.batch_id,
            proj._billable_kind_cond(),
            ThirdPartyApi.bill_status.in_(_BILLABLE),
        )
    ) or 0

    header.billable_rows = billable
    header.resolved_rows = resolved
    header.unresolved_rows = billable - resolved
    header.projected_rows = await db.scalar(
        select(func.count()).select_from(ThirdPartyApi)
        .where(ThirdPartyApi.batch_id == header.batch_id,
               ThirdPartyApi.projected_ticket_id.isnot(None))
    ) or 0
    # One row is one ticket here, unlike NDC where several rows roll up onto one.
    header.projected_tickets = header.projected_rows
    # No latching on this type. Zeroed explicitly rather than left stale, because the shared
    # uploads-list cell renders "· N unattached" whenever this is non-zero.
    header.group_count = 0
    header.latched_rows = 0
    header.unlatched_rows = 0


async def _summary(db: AsyncSession, header: StatementBatchBilling, *,
                   customers_in_scope: int, summary: dict[str, int] | None = None,
                   kinds: dict[str, int] | None = None) -> dict:
    """The worklist's header, in one shape.

    Returned by both `resolve-customers` and the read-only `billing-summary`, so the frontend
    has one type and one setter for the chips no matter which call refreshed them.
    """
    kinds = kinds if kinds is not None else await _kind_counts(db, header.batch_id)
    products = await _product_counts(db, header.batch_id)
    total_rows = await db.scalar(
        select(func.count()).select_from(ThirdPartyApi)
        .where(ThirdPartyApi.batch_id == header.batch_id)
    ) or 0

    return {
        "batch_id": header.batch_id,
        "customers_in_scope": customers_in_scope,
        "summary": summary if summary is not None else await _status_counts(db, header.batch_id),
        "state_counts": await _billing_state_counts(db, header.batch_id),
        "billable_rows": header.billable_rows,
        "resolved_rows": header.resolved_rows,
        "unresolved_rows": header.unresolved_rows,
        "projected_rows": header.projected_rows,
        "projected_tickets": header.projected_tickets,
        "resolution_status": header.resolution_status,
        "default_customer_type": header.default_customer_type,
        "default_customer_id": header.default_customer_id,
        "default_corporate_id": header.default_corporate_id,
        # ── the coverage figures. Every screen that shows a numerator shows these too, so
        # "2 tickets in billing" can never read as "all of it" on a five-row file.
        "total_rows": total_rows,
        "not_billable_rows": sum(kinds.get(k, 0) for k in proj.NOT_BILLABLE_KINDS),
        "kind_counts": kinds,
        "product_counts": products,
        "category_counts": await _category_counts(db, header.batch_id),
        "credit_rows": kinds.get(proj.REFUND, 0),
        # Rows still carrying the verdict from before every category billed. Only a Re-match
        # moves them — see the module docstring for why nothing does it silently.
        "needs_rematch": sum(kinds.get(k, 0) for k in proj.LEGACY_KINDS),
        # Cancelled bookings that still BILL, because the vendor kept a cancellation charge.
        # Not an error — Total Paid − Refund is exactly what is owed — but it is worth a look
        # before invoicing, and nothing else on the screen would surface it.
        "cancelled_positive_rows": await db.scalar(
            select(func.count()).select_from(ThirdPartyApi).where(
                ThirdPartyApi.batch_id == header.batch_id,
                ThirdPartyApi.data["booking_status"].astext.in_(("Cancelled", "Refunded")),
                ThirdPartyApi.bill_kind == proj.SALE,
            )
        ) or 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. RESOLVE — classify, then match
# ══════════════════════════════════════════════════════════════════════════════

class ResolvePayload(BaseModel):
    # A human's pick is the most authoritative thing on the row, so a re-run keeps it unless
    # the caller explicitly says otherwise.
    reset_overrides: bool = False


@router.post("/tp-api/batches/{batch_id}/resolve-customers")
async def resolve_customers(
    batch_id: str,
    payload: ResolvePayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Classify every row, then match each billable one's passenger to the Customer master.

    ONE PASS, TWO JOBS, IN THAT ORDER — but a much simpler order than NDC's, because there is
    no roll-up: a row is its own ticket, so classification is per row and nothing inherits a
    party from anything else.

    EVERY ROW IS CLASSIFIED AND PRICED, including the ones that will never be billed. A pending
    or uncategorised line gets its not-billable `bill_kind`, the reason, and its parsed
    `bill_amount` — so `billing-gaps` can report "1 visa · ₹3,280" instead of a silent
    absence. Filtering them out here would make the exclusion invisible, which is the exact
    failure this type has to avoid.

    Re-running it is also how an upload classified before every category billed (its hotel
    and train rows stored as `not_flight`) becomes billable — see the module docstring.
    """
    payload = payload or ResolvePayload()
    header = await _owned_header(db, batch_id, current_user, create=True)

    index = await cres.CustomerIndex.load(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id
    )
    rows = (await db.execute(
        select(ThirdPartyApi)
        .where(ThirdPartyApi.batch_id == batch_id, *_scope(ThirdPartyApi, current_user))
        # No row_seq on this model — it carries no _SplitMixin, so ingest order IS file order.
        .order_by(ThirdPartyApi.id.asc())
    )).scalars().all()

    now = datetime.utcnow()
    default_set = bool(header.default_customer_type)
    updates: list[dict] = []
    summary: dict[str, int] = {}
    kinds: dict[str, int] = {}

    for row in rows:
        data = row.data or {}
        kind, amount = proj.classify(data)
        kinds[kind] = kinds.get(kind, 0) + 1

        keep_override = (not payload.reset_overrides
                         and row.bill_status == cres.OVERRIDDEN
                         and kind in proj.BILLABLE_KINDS)
        if keep_override:
            match = cres.CustomerMatch(
                status=cres.OVERRIDDEN, customer_id=row.bill_customer_id,
                corporate_id=row.bill_corporate_id, customer_type=row.bill_customer_type,
                note=row.bill_match_reason,
            )
            reason = row.bill_match_reason
        elif kind in proj.NOT_BILLABLE_KINDS:
            match = cres.CustomerMatch(status=cres.EXCLUDED)
            reason = proj.reason_for(kind, data.get("product_type"))
        else:
            # The pax suffix is stripped BEFORE matching, not just for display: TBO writes
            # "lovekush singh X 1", and the stray "X" reads as a dropped initial, which
            # enables the resolver's strict-subset fallback and can turn a clean row into a
            # false INITIALS_ONLY. See tp_api_spec.strip_pax_suffix.
            match = index.resolve(tp.strip_pax_suffix(data.get("passenger_name")))
            if match.status == cres.UNRESOLVED and default_set:
                match = cres.CustomerMatch(
                    status=cres.DEFAULTED,
                    customer_id=header.default_customer_id,
                    corporate_id=header.default_corporate_id,
                    customer_type=header.default_customer_type,
                    display_name=(tp.strip_pax_suffix(data.get("passenger_name")) or ""),
                    note="Billed to this upload's default party.",
                )
            reason = match.note

        summary[match.status] = summary.get(match.status, 0) + 1
        # The pax a human typed is kept, like their party; everything else is re-read.
        if not payload.reset_overrides and row.bill_pax_source == proj.PAX_USER and row.bill_pax_count:
            pax, pax_source = row.bill_pax_count, proj.PAX_USER
        else:
            pax, pax_source = proj.parse_pax(data)
        updates.append({
            "id": row.id,
            "bill_pax_count": pax,
            "bill_pax_source": pax_source,
            "bill_kind": kind,
            "bill_status": match.status,
            "bill_customer_type": match.customer_type,
            "bill_customer_id": match.customer_id,
            "bill_corporate_id": match.corporate_id,
            "bill_match_reason": reason,
            "bill_amount": amount,
            "resolved_at": now,
            "resolved_by_id": current_user.id,
        })

    if updates:
        await db.execute(update(ThirdPartyApi), updates)

    header.resolved_at = now
    if header.resolution_status != "projected":
        header.resolution_status = "resolved"
    await _recount(db, header)
    await db.commit()

    return await _summary(db, header, customers_in_scope=len(index),
                          summary=summary, kinds=kinds)


# ══════════════════════════════════════════════════════════════════════════════
# 2. SUMMARY — read-only
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tp-api/batches/{batch_id}/billing-summary")
async def billing_summary(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What `resolve-customers` returns, WITHOUT resolving anything.

    The worklist needs these counts every time it opens and after every edit; getting them
    from the POST would mean merely looking at the screen re-classified and re-matched every
    row.
    """
    header = await _owned_header(db, batch_id, current_user)
    customers = await db.scalar(
        select(func.count()).select_from(Customer).where(*_scope(Customer, current_user))
    ) or 0
    return await _summary(db, header, customers_in_scope=customers)


# ══════════════════════════════════════════════════════════════════════════════
# 3. ROWS — the worklist
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tp-api/batches/{batch_id}/billing-rows")
async def list_billing_rows(
    batch_id: str,
    status_filter: str | None = Query(None, alias="status"),
    billing_state: str | None = Query(None, pattern=_BILLING_STATE_PATTERN),
    kind: str | None = Query(None, pattern=_KIND_PATTERN),
    product: str | None = Query(None, max_length=40),
    category: str | None = Query(None, max_length=20),
    booking_status: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=100),
    ids_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The resolution worklist, paginated.

    `status` is the row's MATCH status (does it have a party?), `billing_state` is where it
    has got to on its way into billing, and `kind`/`product`/`booking_status` are what the
    row IS — three different questions, never merged.

    `category` is a markup category slug ('hotel', 'air', …) and matches every spelling of the
    product that bills under it; `product` is the file's own text, exactly.

    NOTHING IS HIDDEN BY DEFAULT. NDC hides its latched rows because their money is counted on
    another line; here a not-billable row's money is counted nowhere, and hiding it would
    recreate exactly the silent-drop this type exists to avoid. Not-billable rows come back
    with `sendable: false` and a reason, and the client dims them.
    """
    await _owned_header(db, batch_id, current_user)

    # The join is 1:1 — T.id is a primary key and projected_ticket_id is a FK to it — so a
    # COUNT over the subquery cannot fan out. UploadedTicket needs no _scope of its own: it is
    # reachable only through projected_ticket_id, which this scoped pipeline solely writes.
    T = aliased(UploadedTicket)
    base = (select(ThirdPartyApi, T)
            .outerjoin(T, T.id == ThirdPartyApi.projected_ticket_id)
            .where(ThirdPartyApi.batch_id == batch_id, *_scope(ThirdPartyApi, current_user)))

    if status_filter:
        base = base.where(ThirdPartyApi.bill_status == status_filter)
    if kind == "billable":
        base = base.where(ThirdPartyApi.bill_kind.in_(proj.BILLABLE_KINDS))
    elif kind == "not_billable":
        base = base.where(ThirdPartyApi.bill_kind.in_(proj.NOT_BILLABLE_KINDS))
    elif kind:
        base = base.where(ThirdPartyApi.bill_kind == kind)
    if product:
        base = base.where(ThirdPartyApi.data["product_type"].astext == product)
    if category:
        slug = mc.category_slug(category)
        if slug is None:
            raise HTTPException(status_code=400, detail=f"Unknown category '{category}'.")
        base = base.where(func.lower(func.trim(ThirdPartyApi.data["product_type"].astext))
                          .in_(proj.category_product_values(slug)))
    if booking_status:
        base = base.where(ThirdPartyApi.data["booking_status"].astext == booking_status)
    if billing_state:
        base = base.where(proj.billing_state_cond(billing_state, T))
    if q and q.strip():
        term = q.strip()
        base = base.where(or_(
            _txt(ThirdPartyApi.data["passenger_name"], term),
            _txt(ThirdPartyApi.data["booking_id"], term),
            _txt(ThirdPartyApi.data["invoice_number"], term),
            _txt(ThirdPartyApi.data["pnr"], term),
        ))

    total = await db.scalar(
        select(func.count()).select_from(base.with_only_columns(ThirdPartyApi.id).subquery())
    ) or 0

    order = (ThirdPartyApi.id.asc(),)
    if ids_only:
        ids = (await db.execute(
            base.with_only_columns(ThirdPartyApi.id).order_by(*order)
            .limit(MAX_BILLING_SELECT_IDS)
        )).scalars().all()
        return {"total": total, "ids": list(ids), "truncated": total > len(ids)}

    pairs = (await db.execute(base.order_by(*order).limit(limit).offset(offset))).all()
    rows = [r for r, _t in pairs]
    tickets = {r.id: t for r, t in pairs}

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
        slug = proj.row_category(data)
        return {
            "id": r.id,
            # Stripped for display too, so the worklist and the projected ticket agree on
            # what the passenger is called. The raw cell is the tooltip's job.
            "passenger": tp.strip_pax_suffix(data.get("passenger_name")),
            "passenger_raw": data.get("passenger_name"),
            "product_type": data.get("product_type"),
            # The markup category this row bills under, and what it is — the same one-line
            # description its ticket will carry into billing and onto the invoice.
            "category": slug,
            "category_label": mc.CATEGORY_LABELS.get(slug) if slug else None,
            "service_summary": itin.summary(data, slug),
            "invoice_series": proj.invoice_series(data),
            # What this row bills with, where that came from, and what the file says — so a
            # corrected figure can show what it replaced.
            "pax_count": proj.row_pax(r),
            "pax_source": r.bill_pax_source or proj.parse_pax(data)[1],
            "pax_in_file": proj.parse_pax(data)[0],
            "ticket_pax_count": t.pax_count if t is not None else None,
            "booking_status": data.get("booking_status"),
            "booking_ref": data.get("booking_id") or data.get("invoice_number"),
            "pnr": data.get("pnr"),
            "vendor": data.get("vendor"),
            "booked_date": data.get("transaction_date") or data.get("booking_date"),
            "travel_date": data.get("travel_date") or data.get("start_date"),
            "amount": float(r.bill_amount) if r.bill_amount is not None else None,
            "bill_kind": r.bill_kind,
            "bill_status": r.bill_status,
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
            "billed_party_name": (_party_name(t.customer_type, t.customer_id, t.corporate_id)
                                  if state == "stale" else None),
            "sendable": state in proj.SENDABLE_STATES,
        }

    return {"total": total, "limit": limit, "offset": offset,
            "rows": [_row(r) for r in rows]}


# ══════════════════════════════════════════════════════════════════════════════
# 4. GAPS — why rows are not ready, and why rows are out entirely
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/tp-api/batches/{batch_id}/billing-gaps")
async def billing_gaps(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Two sections, because they need different things from the user.

    `party` is "we do not know who to bill" and is fixed with a picker. `excluded` is "this
    row will never be billed from here", which is not fixable and is not meant to be — it is
    reported so that a five-row file billing two of its rows says so out loud.

    THE TWO ARE DISJOINT. A not-billable row is stamped `bill_status='excluded'`, which would
    also satisfy the party query's `notin_(_BILLABLE)`; without the extra `bill_kind` clause a
    hotel row would appear in both lists and be counted twice.

    `excluded` CARRIES THE MONEY. A count alone lets ₹3,280 of train travel hide behind the
    word "1", which is the whole failure this section exists to prevent.
    """
    await _owned_header(db, batch_id, current_user)
    scope = (ThirdPartyApi.batch_id == batch_id, *_scope(ThirdPartyApi, current_user))

    party = (await db.execute(
        select(ThirdPartyApi.bill_status, ThirdPartyApi.bill_match_reason,
               func.count().label("n"),
               func.array_agg(func.coalesce(
                   ThirdPartyApi.data["passenger_name"].astext, "—")).label("samples"))
        .where(*scope, ThirdPartyApi.bill_status.notin_(_BILLABLE),
               proj._billable_kind_cond())
        .group_by(ThirdPartyApi.bill_status, ThirdPartyApi.bill_match_reason)
        .order_by(func.count().desc()).limit(MAX_GAP_GROUPS)
    )).all()

    # The bare accessor, for the same reason as _product_counts: the NULL bucket is named
    # in Python so the select and the GROUP BY are literally the same expression.
    product_col = ThirdPartyApi.data["product_type"].astext
    excluded = (await db.execute(
        select(ThirdPartyApi.bill_kind, product_col.label("product"),
               func.count().label("n"),
               func.coalesce(func.sum(ThirdPartyApi.bill_amount), 0).label("amount"),
               func.array_agg(func.coalesce(
                   ThirdPartyApi.data["booking_id"].astext,
                   ThirdPartyApi.data["invoice_number"].astext, "—")).label("samples"))
        .where(*scope, ThirdPartyApi.bill_kind.in_(proj.NOT_BILLABLE_KINDS))
        .group_by(ThirdPartyApi.bill_kind, product_col)
        .order_by(func.count().desc()).limit(MAX_GAP_GROUPS)
    )).all()

    return {
        "party": [{
            "status": s, "reason": reason, "count": n,
            # Dedup then cap: one passenger can hold several rows in the same gap.
            "sample_passengers": list(dict.fromkeys(samples or []))[:5],
        } for s, reason, n, samples in party],
        "excluded": [{
            "bill_kind": k,
            "product": p,
            "reason": proj.reason_for(k, p),
            "count": n,
            "amount": float(amount) if amount is not None else 0.0,
            "sample_refs": list(dict.fromkeys(samples or []))[:5],
        } for k, p, n, amount, samples in excluded],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5-7. THE PARTY PICKERS
# ══════════════════════════════════════════════════════════════════════════════

class BillingPartyPayload(BaseModel):
    customer_type: str | None = None      # corporate | direct
    customer_id: int | None = None
    corporate_id: int | None = None


@router.patch("/tp-api/batches/{batch_id}/billing-default")
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

    NOT-BILLABLE ROWS ARE NEVER STAMPED. A pending line with a default party would read as
    "ready" on a screen that then refuses to send it.
    """
    header = await _owned_header(db, batch_id, current_user, create=True)
    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id,
        # A HUMAN picked this party, so store the one they picked. The employee upgrade
        # belongs to the automatic resolver; here it would silently overrule the choice.
        upgrade_employee=False,
    )
    header.default_customer_type = ct
    header.default_customer_id = cust_id
    header.default_corporate_id = corp_id

    rows_updated = 0
    if ct:
        conds = [ThirdPartyApi.batch_id == batch_id, *_scope(ThirdPartyApi, current_user),
                 proj._billable_kind_cond()]
        if apply_to == "unresolved":
            conds.append(ThirdPartyApi.bill_status.notin_(_BILLABLE))
        result = await db.execute(
            update(ThirdPartyApi).where(*conds).values(
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


@router.patch("/tp-api/rows/{row_id}/billing-party")
async def set_row_billing_party(
    row_id: int,
    payload: BillingPartyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A human's pick for one row. Survives a re-match unless reset explicitly."""
    row = await db.scalar(select(ThirdPartyApi).where(
        ThirdPartyApi.id == row_id, *_scope(ThirdPartyApi, current_user)))
    if not row:
        raise HTTPException(status_code=404, detail="Row not found.")
    if proj._is_not_billable(row.bill_kind):
        raise HTTPException(
            status_code=409,
            detail=proj.reason_for(row.bill_kind, (row.data or {}).get("product_type")),
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


class PaxCountPayload(BaseModel):
    # None puts the row back on the statement's own figure.
    pax_count: int | None = Field(default=None, ge=1, le=proj.MAX_PAX)


@router.patch("/tp-api/rows/{row_id}/pax-count")
async def set_row_pax_count(
    row_id: int,
    payload: PaxCountPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Correct how many passengers one booking bills for. Survives a re-match.

    A party's FIXED markup is charged per passenger, so this is a price, not a label — which
    is why it follows the party picker's rules exactly: refused on a row that is not billable,
    and refused once the row is in billing, where the ticket is the thing billing reads.
    """
    row = await db.scalar(select(ThirdPartyApi).where(
        ThirdPartyApi.id == row_id, *_scope(ThirdPartyApi, current_user)))
    if not row:
        raise HTTPException(status_code=404, detail="Row not found.")
    if proj._is_not_billable(row.bill_kind):
        raise HTTPException(
            status_code=409,
            detail=proj.reason_for(row.bill_kind, (row.data or {}).get("product_type")),
        )
    if row.projected_ticket_id is not None:
        raise HTTPException(
            status_code=409,
            detail=("This row is already in billing, so its pax is locked. Change it before "
                    "sending, or take the row out of billing first."),
        )

    if payload.pax_count is None:
        row.bill_pax_count, row.bill_pax_source = proj.parse_pax(row.data or {})
    else:
        row.bill_pax_count, row.bill_pax_source = payload.pax_count, proj.PAX_USER

    await db.commit()
    return {"id": row.id, "pax_count": row.bill_pax_count, "pax_source": row.bill_pax_source,
            "pax_in_file": proj.parse_pax(row.data or {})[0]}


class BulkBillingPartyPayload(BillingPartyPayload):
    row_ids: list[int]


@router.patch("/tp-api/batches/{batch_id}/billing-party-bulk")
async def set_rows_billing_party(
    batch_id: str,
    payload: BulkBillingPartyPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One party for a hand-picked set of rows — the per-row picker, in bulk.

    Rows that cannot take a party are SKIPPED and counted, not refused: a not-billable line
    and a row already in billing. The single-row endpoint 409s on each because there that row
    IS the request; here, failing forty good rows over one is the wrong trade.
    """
    header = await _owned_header(db, batch_id, current_user, create=True)
    ids = _checked_ids(payload.row_ids, "use the default party above")
    await _owned_row_ids(db, batch_id, current_user, ids)

    ct, cust_id, corp_id = await _resolve_bill_party(
        db, current_user, payload.customer_type, payload.customer_id, payload.corporate_id,
        upgrade_employee=False,
    )
    if not ct:
        raise HTTPException(status_code=400, detail="Pick a customer or corporate.")

    picked = (ThirdPartyApi.id.in_(ids), ThirdPartyApi.batch_id == batch_id,
              *_scope(ThirdPartyApi, current_user))
    result = await db.execute(
        update(ThirdPartyApi).where(
            *picked,
            proj._billable_kind_cond(),          # NULL-safe; see the projection's note
            ThirdPartyApi.projected_ticket_id.is_(None),
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
            select(func.count()).select_from(ThirdPartyApi).where(*picked, *conds)) or 0

    skipped_in_billing = await _count(ThirdPartyApi.projected_ticket_id.isnot(None))
    skipped_not_billable = await _count(
        ThirdPartyApi.bill_kind.in_(proj.NOT_BILLABLE_KINDS),
        ThirdPartyApi.projected_ticket_id.is_(None))

    if header.resolution_status == "none":
        header.resolution_status = "resolved"
    await _recount(db, header)
    await db.commit()

    return {"batch_id": batch_id, "customer_type": ct, "customer_id": cust_id,
            "corporate_id": corp_id, "rows_updated": rows_updated,
            "skipped_in_billing": skipped_in_billing,
            "skipped_not_billable": skipped_not_billable,
            "billable_rows": header.billable_rows,
            "resolved_rows": header.resolved_rows,
            "unresolved_rows": header.unresolved_rows}


# ══════════════════════════════════════════════════════════════════════════════
# 8-9. ADDING A PASSENGER TO THE EMPLOYEE MASTER
# ══════════════════════════════════════════════════════════════════════════════
# The creation rule is SHARED — services/employee_from_passenger — because it decides what
# lands in the master and on what terms, and a third copy would drift. The guards below are
# this type's own.

class CreateEmployeePayload(BaseModel):
    corporate_id: int | None = None


class CreateEmployeesBulkPayload(BaseModel):
    row_ids: list[int]
    corporate_id: int | None = None


async def _corporate_for(db: AsyncSession, user: User, corporate_id: int | None) -> Corporate:
    corp = (await db.execute(select(Corporate).where(
        Corporate.id == corporate_id,
        Corporate.tenant_id == user.tenant_id,
        Corporate.created_by_id == user.id,
    ))).scalar_one_or_none()
    if corp is None:
        raise HTTPException(
            status_code=404,
            detail=f"Corporate id {corporate_id} is not in your corporates.",
        )
    return corp


def _guard_row_for_employee(row: ThirdPartyApi) -> str | None:
    """Why this row cannot take an employee, or None. Mirrors set_row_billing_party."""
    if proj._is_not_billable(row.bill_kind):
        return proj.reason_for(row.bill_kind, (row.data or {}).get("product_type"))
    if row.projected_ticket_id is not None:
        return "This row is already in billing. Remove it from the billing first."
    return None


async def _add_row_passenger_to_master(
    db: AsyncSession, user: User, row: ThirdPartyApi, corp: Corporate, dupes, index=None,
):
    """File this row's passenger under `corp`, then point the row at them."""
    outcome = await emp.create_employee_from_passenger(
        db, user, tp.strip_pax_suffix((row.data or {}).get("passenger_name")),
        corp, dupes, index)
    if not outcome.created:
        return outcome

    # Both ids together: the employer is invoiced, the employee is recorded as who travelled.
    row.bill_customer_type = "corporate"
    row.bill_customer_id = outcome.customer_id
    row.bill_corporate_id = corp.id
    row.bill_status = cres.OVERRIDDEN
    row.bill_match_reason = None
    row.resolved_at = datetime.utcnow()
    row.resolved_by_id = user.id
    return outcome


@router.post("/tp-api/rows/{row_id}/create-employee", status_code=201)
async def create_employee_from_row(
    row_id: int,
    payload: CreateEmployeePayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add this row's passenger to the Employee Master under a corporate, and bill the row
    to them."""
    from app.services.party_dedupe import CustomerDuplicates

    payload = payload or CreateEmployeePayload()
    row = await db.scalar(select(ThirdPartyApi).where(
        ThirdPartyApi.id == row_id, *_scope(ThirdPartyApi, current_user)))
    if not row:
        raise HTTPException(status_code=404, detail="Row not found.")
    blocked = _guard_row_for_employee(row)
    if blocked:
        raise HTTPException(status_code=409, detail=blocked)

    corporate_id = payload.corporate_id or row.bill_corporate_id
    if not corporate_id:
        raise HTTPException(
            status_code=400,
            detail="Pick the corporate this passenger works for first.",
        )
    corp = await _corporate_for(db, current_user, corporate_id)

    dupes = await CustomerDuplicates.load(db, current_user)
    index = await cres.CustomerIndex.load(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id)
    outcome = await _add_row_passenger_to_master(db, current_user, row, corp, dupes, index)
    if not outcome.created:
        raise HTTPException(status_code=409, detail=outcome.reason)

    header = await _owned_header(db, row.batch_id, current_user, create=True)
    await _recount(db, header)
    await db.commit()

    return {
        "customer_id": outcome.customer_id,
        "passenger": outcome.display_name,
        "corporate_id": corp.id,
        "company": corp.company,
        "inherited": list(outcome.inherited),
        "row_id": row.id,
        "bill_status": row.bill_status,
    }


@router.post("/tp-api/batches/{batch_id}/create-employees", status_code=201)
async def create_employees_from_rows(
    batch_id: str,
    payload: CreateEmployeesBulkPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The same, for a hand-picked selection. Rows that cannot take an employee are SKIPPED
    and reported, not failed."""
    from app.services.party_dedupe import CustomerDuplicates

    header = await _owned_header(db, batch_id, current_user, create=True)
    ids = _checked_ids(payload.row_ids, "tick the rows to add")
    await _owned_row_ids(db, batch_id, current_user, ids)

    rows = (await db.execute(
        select(ThirdPartyApi)
        .where(ThirdPartyApi.id.in_(ids), *_scope(ThirdPartyApi, current_user))
        .order_by(ThirdPartyApi.id)
    )).scalars().all()

    dupes = await CustomerDuplicates.load(db, current_user)
    # Loaded ONCE. It does not see employees created earlier in this same loop — `dupes` is
    # what catches those, claiming each identity as it goes.
    index = await cres.CustomerIndex.load(
        db, tenant_id=current_user.tenant_id, created_by_id=current_user.id)
    corps: dict[int, Corporate] = {}
    created: list[dict] = []
    skipped: list[dict] = []

    for row in rows:
        passenger = tp.strip_pax_suffix((row.data or {}).get("passenger_name"))
        blocked = _guard_row_for_employee(row)
        if blocked:
            skipped.append({"row_id": row.id, "passenger": passenger, "reason": blocked})
            continue
        corporate_id = payload.corporate_id or row.bill_corporate_id
        if not corporate_id:
            skipped.append({"row_id": row.id, "passenger": passenger,
                            "reason": "No corporate picked for this row."})
            continue
        if corporate_id not in corps:
            corps[corporate_id] = await _corporate_for(db, current_user, corporate_id)
        outcome = await _add_row_passenger_to_master(
            db, current_user, row, corps[corporate_id], dupes, index)
        if outcome.created:
            created.append({"row_id": row.id, "customer_id": outcome.customer_id,
                            "passenger": outcome.display_name,
                            "company": corps[corporate_id].company})
        else:
            skipped.append({"row_id": row.id, "passenger": passenger,
                            "reason": outcome.reason})

    await _recount(db, header)
    await db.commit()

    return {
        "batch_id": batch_id,
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 10. SEND
# ══════════════════════════════════════════════════════════════════════════════

class SendToBillingPayload(BaseModel):
    """No body / null → the whole upload, synced. `row_ids` → those rows, added only."""
    row_ids: list[int] | None = Field(default=None)


@router.post("/tp-api/batches/{batch_id}/send-to-billing")
async def send_to_billing(
    batch_id: str,
    payload: SendToBillingPayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Project the resolved rows — every category — into `uploaded_tickets` so Corporate and
    Customer billing can see them.

    Idempotent: re-running syncs rather than duplicates, and any ticket already on an invoice
    is left exactly as it was.

    The response carries `sent_by_category` and `skipped_by_reason` per `bill_kind`, so the
    client can say "40 train, 5 hotel sent · 3 pending" rather than a bare count — on a
    multi-product file that difference is the whole feature.
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

    ctx = await _batch_context(db, batch_id, current_user)
    result = await proj.project_batch(db, header, row_ids=ids, **ctx)
    await _recount(db, header)
    await db.commit()
    return {"batch_id": batch_id, **result}
