"""Turning an aggregator's booking row into something the deal engine can price.

A Third Party API statement is an aggregator's export — MakeMyTrip, TBO — and like its two
siblings on this router it is a B2B document: the aggregator sold to us, so the deal that
covers it is an INCOMING B2B deal, matched against the Supplier master row declared at
upload (`statement_batch_suppliers`).

ONLY FLIGHT ROWS ARE PRICED, AND THE REST ARE NOT HIDDEN. This is the only multi-product
source on the router: one file carries hotel, flight, train, bus and car bookings side by
side, and a hotel night has no airline deal to price it against. The temptation is to
filter them out of `load_rows` and quietly present a smaller statement; that is exactly
what this does not do. Every row is loaded and every non-flight row is returned as a
`skip` naming its product, so the grid's total still reconciles to the file's row count
and the gaps tab can say "412 hotel · 88 train" instead of losing 500 rows without a word.
It is the same discipline `tp_api_billing_projection` applies with its `bill_kind`s, and
the reasons here come from that module so one row cannot be out for one stated reason on
the billing worklist and a different one here.

What else this file decides, and why each is a judgement rather than a lookup:

  * **Classification is `tp_api_billing_projection.classify`, not a local status table.**
    That function already encodes the parts nobody would guess twice the same way: a TBO
    credit series is a refund even though the file carries no sign, a cancelled MMT
    booking with a refund kept only part of the money, "Refunded with no payment on this
    statement" is a different verdict from "Cancelled". Its seven verdicts collapse onto
    the engine's three — sale, refund, everything else is not a sale — and the verdict's
    own sentence is carried onto the row.

  * **The carrier is resolved BY NAME ONLY, and usually is not.** `statement_spec` gives
    this type no `resolve_airline`, and the reason is in `tp_api_billing_projection`: its
    one carrier field is `Airline/Property Name`, which holds a hotel's name on a hotel
    row and an operator's on a bus row. On a FLIGHT row it does hold the carrier, so it is
    looked up against the airline master by name — never by a code, because there is no
    code column and deriving one from free text is what that module already refuses. A
    name the master has never seen resolves to nothing and the row says "airline not
    recognised", which is the honest answer and the one the runner already prints.

  * **No YQ, no YR, and no ancillary sub-types.** The file prints one combined `Taxes`
    figure and no surcharge columns at all. `yq` and `yr` are therefore None, which
    UNDER-STATES the base for a deal calculating on Basic+YQ+YR — conservative, so you
    claim less than you might be owed, and the row says so rather than the shortfall being
    invisible. `Convenience Fee`, `Travel Insurance` and the rest are the aggregator's own
    charges to us, not ancillaries the airline sold, so none of them is claimed as one.

  * **No declared amounts.** An aggregator prints what a booking cost and what was paid
    for it — never a commission or an incentive it paid us. `Agent Markup` is OUR markup
    to our own customer, not the aggregator's payment to us, and treating it as a declared
    commission would invent a variance out of our own pricing. So `has_declared_amounts`
    is False and the variance report 404s for this source, exactly as it does for NDC.

  * **The refund key is the PNR, falling back to the booking id.** There is no ticket
    number on this export. A refund therefore reverses the issue it shares a PNR with,
    which is the closest thing to a document number the file has; `norm_tn` normalises
    both sides, as it does everywhere else.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission_run import SOURCE_TP_API
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import STATEMENT_MODELS
from app.services import tp_api_billing_projection as tpb
from app.services import tp_api_spec as tp_spec
from app.services import tp_airline_resolution as tp_airline
from app.services.commission.calc_row import (
    KIND_ISSUE, KIND_REFUND, KIND_SKIP, BatchInfo, CalcRow,
)
from app.services.deal_matching import SKIP_CLASS, SKIP_SEGMENT, segment_letter
from app.services.markup_categories import CATEGORY_AIR

# An aggregator sells to us, so its statement is priced against a B2B deal, and its
# incentives are earned on the sale — never on a Flown trigger.
STATEMENT_TYPE = "B2B"
INVOICE_TYPE = "Sales"

# `classify`'s verdicts, collapsed onto what the engine does with a row. Everything not
# named here is not a sale; the verdict's own sentence says why, so this map carries no
# copy of its own.
_KIND = {tpb.SALE: KIND_ISSUE, tpb.REFUND: KIND_REFUND}

# DELIBERATELY ONE SENTENCE PER PRODUCT, not per row. The gaps tab groups by
# (status, reason) and caps at 50 groups, so naming the booking here would turn one
# actionable bucket into one group per hotel night — the lesson `runner`'s refund branch
# spells out at length. Four products, four groups.
_NOT_AIR_REASON = (
    "{product} bookings have no airline deal to price them against — this statement's "
    "flight rows are the ones Commission income can cost."
)
_NO_PRODUCT_REASON = (
    "This row does not say which product it is, so there is no way to tell whether an "
    "airline deal could cover it."
)

NEEDS_DATA_REMEDY = (
    "This aggregator's export does not print it. Ask them to include the column, or "
    "narrow the deal so it does not depend on it."
)


def _s(data: dict, key: str) -> str | None:
    v = data.get(key)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _f(data: dict, key: str) -> float | None:
    """One money cell as a float. None — never 0 — when the vendor printed nothing."""
    v = tp_spec.to_decimal(data.get(key))
    return None if v is None else float(v)


def _d(data: dict, key: str) -> date | None:
    """`tp_api_spec.normalize` writes ISO into `data`; anything else is not a date."""
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


def _sector(data: dict) -> str | None:
    """'DEL/BOM' from the origin/destination pair, codes preferred over city names.

    The codes are what a deal's route rules are written in; the city names are the
    fallback so a file that ships only those is not left with no sector at all.
    """
    o = _s(data, "origin_code") or _s(data, "origin")
    d = _s(data, "destination_code") or _s(data, "destination")
    parts = [p.strip().upper() for p in (o, d) if p and p.strip()]
    if not parts:
        return None
    if len(parts) == 2 and parts[0] == parts[1]:
        return parts[0]
    return "/".join(parts)


def _classify(data: dict) -> tuple[str, str | None]:
    """(kind, reason) for one row: product first, then the billing verdict.

    PRODUCT FIRST, exactly as `classify` orders it. A cancelled hotel booking is out
    because it is a hotel, and "Hotel bookings have no airline deal" is a more useful
    sentence than anything about its status — and it keeps the four product buckets from
    fragmenting across every status the aggregator prints.
    """
    category = tpb.row_category(data)
    if category != CATEGORY_AIR:
        product = _s(data, "product_type")
        return KIND_SKIP, (_NOT_AIR_REASON.format(product=product) if product
                           else _NO_PRODUCT_REASON)

    kind, _amount = tpb.classify(data)
    mapped = _KIND.get(kind)
    if mapped is not None:
        return mapped, None
    return KIND_SKIP, tpb.reason_for(kind, _s(data, "product_type"))


def build_calc_row(row, supplier_name: str | None, supplier_id: int | None,
                   match: tp_airline.TpAirlineMatch | None) -> CalcRow:
    """One `third_party_api` row → a CalcRow."""
    data = dict(row.data or {})
    kind, kind_reason = _classify(data)
    booking_class = _s(data, "booking_class")

    ctx = CalcRow(
        source_row_id=row.id,
        # No ticket number on this export — see the module docstring. The PNR is what a
        # refund and the issue it reverses share.
        ticket_number=_s(data, "pnr") or _s(data, "booking_id"),
        document_number=_s(data, "invoice_number") or _s(data, "booking_id"),
        pnr=_s(data, "pnr"),
        passenger_name=tp_spec.strip_pax_suffix(data.get("passenger_name")),
        transaction_type=_s(data, "booking_status"),
        airline_name=(match.name if match and match.resolved else None),
        airline_id=(match.airline_id if match and match.resolved else None),
        issue_date=_d(data, "booking_date") or _d(data, "transaction_date"),
        travel_date=_d(data, "travel_date") or _d(data, "start_date"),
        segment_type=_s(data, "intl_dom"),
        booking_class=booking_class,
        sector=_sector(data),
        fare_amount=_f(data, "base_fare"),
        # No surcharge columns on this export — see the module docstring. Deliberately
        # None, never a share of the combined `Taxes` figure.
        yq=None,
        yr=None,
        # The aggregator's own charges to us are not ancillaries the airline sold, so none
        # of them is offered to the engine as one.
        seat_selection=None, excess_baggage=None, meals=None,
        kind=kind,
        kind_reason=kind_reason,
        statement_type=STATEMENT_TYPE,
        invoice_type=INVOICE_TYPE,
        supplier_agency=supplier_name,
        supplier_agency_id=supplier_id,
    )

    if kind_reason:
        ctx.note(kind_reason)

    # Per row, never per statement: the flight rows of this export DO print a class, and
    # skipping it on a row that has one would let an Economy-only deal pay a Business
    # booking.
    if not booking_class:
        ctx.skip_criteria.add(SKIP_CLASS)
        ctx._skip_rule_fields.add("class")
        ctx.skipped_labels.append("class")
    if not ctx.sector:
        ctx.skipped_labels.append("sector")
    if not ctx.travel_date:
        ctx.skipped_labels.append("travel_date")
    # READABILITY, not presence. An aggregator writes Intl/Dom in its own words, and a
    # spelling the engine's vocabulary does not know is not a mismatch — it is a fact we
    # do not have. Left as a mismatch it would drop every flight-type-restricted config
    # and report the row unmatched, which reads as "no deal covers this" rather than
    # "nobody could tell where it flew". See SKIP_SEGMENT.
    if segment_letter(ctx.segment_type) is None:
        ctx.skip_criteria.add(SKIP_SEGMENT)
        ctx.skipped_labels.append("segment_type")

    if kind != KIND_SKIP and ctx.fare_amount is not None:
        ctx.note("This export prints one combined Taxes figure and no YQ or YR column, so "
                 "a deal calculating on Basic+YQ+YR was paid on the base fare alone — less "
                 "than it may owe, never more.")
    if match is not None and match.conflict:
        ctx.note(f"The Airline / Property column resolved to {match.name}, which disagrees "
                 f"with {match.conflict_name}.")
    if data.get("date_parse_failed"):
        ctx.note("A date cell on this row could not be read, so the deal's validity window "
                 "was tested against whichever date did parse.")

    return ctx


class TpApiAdapter:
    """Loads one Third Party API batch and normalizes it."""

    source = SOURCE_TP_API
    label = "Third Party · API"
    statement_type = STATEMENT_TYPE
    has_declared_amounts = False
    requires_supplier = True
    needs_data_remedy = NEEDS_DATA_REMEDY
    model = STATEMENT_MODELS["tp-api"]

    async def list_batches(self, db: AsyncSession, tenant_id: int, user_id: int) -> list[BatchInfo]:
        """One entry per upload, derived with a GROUP BY — this type keeps no batch header.

        The period comes from `transaction_date`, which `tp_api_spec.normalize` wrote as
        ISO text; a value that is not a date sorts harmlessly and is dropped on the way
        out. Not `travel_date`: a hotel line's travel date is its check-in and a flight's
        is its departure, so the transaction date is the one fact every product shares.
        """
        m = self.model
        rows = (await db.execute(
            select(
                m.batch_id, m.source_file,
                func.max(m.uploaded_at).label("uploaded_at"),
                func.count().label("row_count"),
                func.min(m.data["transaction_date"].astext).label("period_from"),
                func.max(m.data["transaction_date"].astext).label("period_to"),
            )
            .where(m.tenant_id == tenant_id, m.created_by_id == user_id)
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
        """The aggregator declared at upload, or None for a batch that predates it.

        Read off the link row's SNAPSHOT rather than joined to `suppliers`, so a renamed
        vendor cannot silently re-label a run that already happened.
        """
        return (await db.execute(
            select(StatementBatchSupplier).where(
                StatementBatchSupplier.slug == self.source,
                StatementBatchSupplier.tenant_id == tenant_id,
                StatementBatchSupplier.batch_id == batch_id,
            )
        )).scalar_one_or_none()

    async def load_rows(self, db: AsyncSession, tenant_id: int, user_id: int,
                        batch_id: str, row_ids: list[int] | None = None) -> list:
        """EVERY row, including the hotels and trains — see the module docstring."""
        m = self.model
        conds = [m.batch_id == batch_id, m.tenant_id == tenant_id, m.created_by_id == user_id]
        if row_ids:
            conds.append(m.id.in_(row_ids))
        return list((await db.execute(select(m).where(*conds).order_by(m.id.asc()))).scalars().all())

    async def build_contexts(self, db: AsyncSession, rows: list, tenant_id: int,
                             user_id: int, batch_id: str) -> list[CalcRow]:
        link = await self.supplier_for_batch(db, tenant_id, batch_id)
        name = link.supplier_name if link else None
        supplier_id = link.supplier_id if link else None

        # Built once per batch, and only consulted for the flight rows — the airline master
        # is one query, not one per row. Same seam as `statements._airline_stamper`.
        index = await tp_airline.build_index(db)
        out: list[CalcRow] = []
        for r in rows:
            data = r.data or {}
            match = None
            if tpb.row_category(data) == CATEGORY_AIR:
                # By NAME only: there is no code column on this export, and on a non-flight
                # row this field holds a hotel or a bus operator — which is why the lookup
                # is behind the category check rather than in front of it.
                match = tp_airline.resolve_tp_airline(
                    None, None, data.get("airline_property_name"), index,
                )
            out.append(build_calc_row(r, name, supplier_id, match))
        return out

    async def cumulative_provider(self, db: AsyncSession, tenant_id: int, user_id: int):
        """None → the engine's default (a scan of uploaded tickets).

        One aggregator's statement is a slice of the year, not the whole of it, so summing
        only its own rows would understate every slab and quietly pay the bottom band.
        """
        return None
