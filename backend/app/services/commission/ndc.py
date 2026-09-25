"""Turning an NDC statement row into something the deal engine can price.

An NDC export is the AIRLINE's own sales ledger, downloaded from its own portal, so it is
priced against `deal_type='airline'` deals — the same pool BSP and LCC Detailed use, and
the opposite of the third-party adapter beside it. There is no consolidator: the carrier
is the counterparty on its own document.

THIS IS THE BEST-EVIDENCE SOURCE ON THE ROUTER, and the comparison is worth stating
because it decides how much is withheld. An unenriched BSP row knows neither class nor
sector; an LCC Detailed row prints a fare family rather than an RBD; a consolidator's GDS
row leaves Class blank. An NDC row prints `Class Of Booking` (a real RBD), `Sectors`,
`Departure Date`, `Basic Fare`, `YQ Tax` and `YR Tax` as their own columns. So nothing is
skipped wholesale here — every skip below is per row, on a cell the airline left blank.

What this file decides, and why each is a judgement rather than a lookup:

  * **Ancillaries are priced as ancillaries, per sub-type.** This is the ONLY source that
    can. A consolidator prints one combined "SSR Amount" and LCC Detailed one combined
    `other_ssr_total`, so both must claim nothing for it (see their module docstrings);
    an NDC portal writes a paid seat, a bag and a meal as their own lines and says which
    is which in `Product` / `TXN Type`. `ndc_billing_projection._bucket_for` already maps
    that to a named column, so the same call routes the money to `seat_selection` /
    `excess_baggage` / `meals` — exactly the three bases
    `deal_matching._compute_ancillary_from_items` pays on. A product that maps to neither
    (lounge access, an unrecognised EMD) lands in the default bucket, which is NOT an
    incentive base, so nothing is claimed for it and the row says why.

  * **An add-on contributes NO fare components.** A latched ancillary line REPEATS the
    ticket's `Total Fare`, `Basic Fare` and taxes while carrying only its own `Payment
    Amount` — so reading the components off it would pay the flight's incentive twice,
    once on the ticket and once per add-on. `fare_amount`, `yq` and `yr` are therefore
    None on an ancillary row, which is the same rule `income_board/project._component`
    applies in SQL.

  * **The carrier is resolved HERE, not at ingest.** `statement_spec` gives NDC no
    `resolve_airline` — its file names the carrier with usable codes, so nothing needed
    stamping — but `deals.airline_name` holds the MASTER's spelling and the match is a
    lowercase equality, so "AI" will never equal "Air India". The lookup runs once per
    batch off the same index the third-party types use, preferring the 3-digit accounting
    code over the 2-letter designator. Resolving at build time rather than at ingest also
    means every NDC statement already uploaded prices without being re-imported.

  * **Segment type is NOT derived from `Sectors`.** The file prints no domestic/
    international flag. A route could be classified against an airport master, but that
    master is not consulted anywhere else on this router, and a guess the deal engine then
    MATCHES on is worse than an honest skip — so flight-type-restricted deals withhold
    rather than pay. `income_board/project._ndc_select` refuses the same derivation for
    the same reason.

  * **Classification is `TXN Type`, never the sign.** Shared with billing, via
    `ndc_billing_projection.bill_kind`, so a row cannot be a refund on one screen and a
    sale on the other. `EXCLUDED_TXN_TYPES` already dropped the unpaid holds and free
    seats at ingest, so what reaches here is the six types where money moved.

  * **No declared amounts.** An airline's own sales export prints what the ticket cost and
    what was settled for it — never a commission or an incentive it paid us. There is
    nothing to compare against, so `has_declared_amounts` is False and the variance report
    404s for this source rather than rendering a column of zeros.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission_run import SOURCE_NDC
from app.models.statement_row import STATEMENT_MODELS
from app.services import ndc_billing_projection as ndc_proj
from app.services import ndc_spec
from app.services import tp_airline_resolution as tp_airline
from app.services.commission.calc_row import (
    KIND_ISSUE, KIND_REFUND, KIND_SKIP, BatchInfo, CalcRow,
)
from app.services.deal_matching import SKIP_CLASS, SKIP_SEGMENT

# An NDC export is a sales ledger: incentives are earned on the sale, so a deal whose
# trigger is "Flown" correctly does not match here — same as BSP and LCC Detailed.
INVOICE_TYPE = "Sales"
STATEMENT_TYPE = "AIRLINE"

# `bill_kind` is already the airline's own word for what happened, read off `TXN Type` by
# the billing projection. Reusing it rather than re-deriving keeps one row from being a
# refund on the billing worklist and a sale here.
_KIND = {"sale": KIND_ISSUE, "refund": KIND_REFUND, "payment": KIND_SKIP}

# Which CalcRow ancillary base each of `ndc_billing_projection`'s buckets feeds. The
# fourth bucket it can return — `booking_fee_sell` — is deliberately absent: it is a
# recorded, NON-base column on `uploaded_tickets` precisely because an unrecognised
# product must not silently inflate an incentive, and the same restraint applies to a
# deal's ancillary rates. Such a row keeps its `ancillary_amount` for display and claims
# nothing.
_ANCILLARY_BASE = {
    "seat_selection": "seat_selection",
    "excess_baggage": "excess_baggage",
    "meals": "meals",
}

NEEDS_DATA_REMEDY = (
    "This airline's NDC export does not print it on this row. Ask the airline to include "
    "the column, or narrow the deal so it does not depend on it."
)


def _s(data: dict, key: str) -> str | None:
    v = data.get(key)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _f(data: dict, key: str) -> float | None:
    """One money cell as a float. None — never 0 — when the airline printed nothing."""
    v = ndc_spec.to_decimal(data.get(key))
    return None if v is None else float(v)


def _d(data: dict, key: str) -> date | None:
    """The spec normalizer writes ISO into `data`; anything else is not a date we trust."""
    raw = _s(data, key)
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _iso(v) -> date | None:
    if not v:
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _sector(raw: str | None) -> str | None:
    """'DEL-BOM-MAA' / 'DEL/BOM' → 'DEL/BOM/MAA', the spelling every other source uses.

    Collapses a repeated airport where one leg's arrival is the next leg's departure, the
    same normalisation `lcc_detailed._sector` performs on its folded legs.
    """
    if not raw:
        return None
    parts: list[str] = []
    for p in str(raw).replace("-", "/").replace(",", "/").split("/"):
        p = p.strip().upper()
        if p and (not parts or parts[-1] != p):
            parts.append(p)
    return "/".join(parts) or None


def build_calc_row(row, match: tp_airline.TpAirlineMatch | None) -> CalcRow:
    """One `ndc` row → a CalcRow."""
    data = dict(row.data or {})
    kind = _KIND.get(ndc_proj.bill_kind(data), KIND_ISSUE)
    is_ancillary = ndc_proj._looks_ancillary(data)
    booking_class = _s(data, "class_of_booking")

    ctx = CalcRow(
        source_row_id=row.id,
        # `Document No` is the 13-digit ticket number, airline prefix included. It is what
        # a REFUND line carries too, which is what lets the runner find the issue it
        # reverses.
        ticket_number=_s(data, "document_no"),
        document_number=_s(data, "document_no"),
        pnr=_s(data, "airline_pnr"),
        passenger_name=_s(data, "passenger_name"),
        transaction_type=_s(data, "txn_type"),
        # The master's spelling, resolved per batch below. The file's own 2-letter code is
        # kept in `data` for display but must never reach the matcher: the deal holds the
        # master's name and the compare is an equality.
        airline_name=(match.name if match and match.resolved else None),
        airline_id=(match.airline_id if match and match.resolved else None),
        issue_date=_d(data, "date_of_issue") or _d(data, "date_of_booking"),
        travel_date=_d(data, "departure_date"),
        # See the module docstring: the file prints no dom/intl flag and deriving one from
        # the route would be a guess the engine then matches on.
        segment_type=None,
        booking_class=booking_class,
        sector=_sector(_s(data, "sectors")),
        tour_code=_s(data, "tour_code"),
        kind=kind,
        statement_type=STATEMENT_TYPE,
        invoice_type=INVOICE_TYPE,
    )

    if is_ancillary:
        # An add-on repeats the ticket's fare columns — see the module docstring — so it
        # contributes none of them and carries its own settled figure instead.
        settled = ndc_proj.signed_total(data)
        amount = None if settled is None else abs(float(settled))
        ctx.ancillary_amount = amount
        bucket = ndc_proj._bucket_for(data)
        base = _ANCILLARY_BASE.get(bucket)
        product = _s(data, "product") or _s(data, "txn_type") or "This add-on"
        if base and amount:
            setattr(ctx, base, amount)
        elif amount:
            ctx.note(
                f"{product} is an add-on the deal rates do not name — a deal pays Ancillary "
                f"as baggage, meals or seat — so its {amount:,.2f} is shown but nothing was "
                f"claimed for it."
            )
    else:
        ctx.fare_amount = _f(data, "basic_fare")
        ctx.yq = _f(data, "yq_tax")
        ctx.yr = _f(data, "yr_tax")

    if kind == KIND_SKIP:
        ctx.kind_reason = "Nothing settled on this line — no money moved, so it is not a sale"
        ctx.note(ctx.kind_reason)

    # Per row, never per statement: an NDC export DOES print the booking class, and
    # skipping it on a row that has one would let an Economy-only deal pay a Business
    # ticket. Only the rows that genuinely left it blank bypass the class rules — an
    # ancillary line, which has no cabin of its own, usually among them.
    if not booking_class:
        ctx.skip_criteria.add(SKIP_CLASS)
        ctx._skip_rule_fields.add("class")
        ctx.skipped_labels.append("class")
    if not ctx.sector:
        ctx.skipped_labels.append("sector")
    if not ctx.travel_date:
        ctx.skipped_labels.append("travel_date")
    # Named on EVERY row, because it is a property of the file rather than of the row: an
    # NDC export prints no domestic/international column at all. Without this the engine
    # answers "can't determine, allow" and a Domestic-only deal pays every International
    # ticket in the statement — see SKIP_SEGMENT.
    ctx.skip_criteria.add(SKIP_SEGMENT)
    ctx.skipped_labels.append("segment_type")

    if match is not None and match.conflict:
        ctx.note(
            f"The accounting code says {match.name}; the Airline column says "
            f"{match.conflict_name}. The accounting code was used."
        )
    return ctx


class NdcAdapter:
    """Loads one NDC batch and normalizes it."""

    source = SOURCE_NDC
    label = "NDC"
    statement_type = STATEMENT_TYPE
    has_declared_amounts = False
    requires_supplier = False
    needs_data_remedy = NEEDS_DATA_REMEDY
    model = STATEMENT_MODELS["ndc"]

    async def list_batches(self, db: AsyncSession, tenant_id: int, user_id: int) -> list[BatchInfo]:
        """One entry per upload, derived with a GROUP BY — this type keeps no batch header.

        `is_total = false` throughout: the file's own declared grand-total line is stored
        as a row (`_SplitMixin.is_total`), and counting it would add the statement's total
        to the statement's own rows. The same predicate guards `load_rows`, so the entry
        count here is the number of rows a run will actually price.
        """
        m = self.model
        rows = (await db.execute(
            select(
                m.batch_id, m.source_file,
                func.max(m.uploaded_at).label("uploaded_at"),
                func.count().label("row_count"),
                func.min(m.data["date_of_issue"].astext).label("period_from"),
                func.max(m.data["date_of_issue"].astext).label("period_to"),
            )
            .where(m.tenant_id == tenant_id, m.created_by_id == user_id,
                   m.is_total.is_(False))
            .group_by(m.batch_id, m.source_file)
            .order_by(func.max(m.uploaded_at).desc())
        )).all()
        return [
            BatchInfo(
                batch_id=r.batch_id, source_file=r.source_file, uploaded_at=r.uploaded_at,
                row_count=r.row_count or 0,
                period_from=_iso(r.period_from), period_to=_iso(r.period_to),
            )
            for r in rows
        ]

    async def supplier_for_batch(self, db: AsyncSession, tenant_id: int, batch_id: str):
        """No consolidator: the carrier is the counterparty on its own statement."""
        return None

    async def load_rows(self, db: AsyncSession, tenant_id: int, user_id: int,
                        batch_id: str, row_ids: list[int] | None = None) -> list:
        m = self.model
        conds = [m.batch_id == batch_id, m.tenant_id == tenant_id,
                 m.created_by_id == user_id, m.is_total.is_(False)]
        if row_ids:
            conds.append(m.id.in_(row_ids))
        return list((await db.execute(select(m).where(*conds).order_by(m.id.asc()))).scalars().all())

    async def build_contexts(self, db: AsyncSession, rows: list, tenant_id: int,
                             user_id: int, batch_id: str) -> list[CalcRow]:
        """Resolve the carrier once for the whole batch, then normalize every row.

        ONE INDEX, NOT ONE QUERY PER ROW — the airline master is small and the resolution
        is pure, so it is built once here exactly as `statements._airline_stamper` builds
        it once per upload. The per-row call is a dict lookup.
        """
        index = await tp_airline.build_index(db)
        out: list[CalcRow] = []
        for r in rows:
            data = r.data or {}
            # Accounting code first, designator second — the order
            # `ndc_billing_projection.airline_names` and the income board both prefer, and
            # the order `resolve_tp_airline` already implements. No name is passed: NDC
            # prints codes, and its `airline` column IS the 2-letter code.
            match = tp_airline.resolve_tp_airline(
                data.get("airline_iata_code"), data.get("airline"), None, index,
            )
            out.append(build_calc_row(r, match))
        return out

    async def cumulative_provider(self, db: AsyncSession, tenant_id: int, user_id: int):
        """None → the engine's default. One portal's export is a slice of the year, so
        summing only its own rows would understate every slab and pay the bottom band."""
        return None
