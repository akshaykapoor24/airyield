"""Turning an LCC Detailed statement row into something the deal engine can price.

An LCC Detailed statement comes from the CARRIER, not from a consolidator, so it is priced
against `deal_type='airline'` deals — the same pool BSP uses, and the opposite of the
third-party adapter beside it.

Unlike BSP, this source has typed columns: `base_fare`, `departure_date`, an `international`
flag and a `taxes` JSONB array. Almost everything the engine wants is printed. Two things
are not:

  * **Cabin class.** `product_class` is a FARE FAMILY ("Value", "Flexi", "SME"), not an RBD.
    Feeding it to the class resolver would come back `{"Economy"}` for every row — see
    `_resolve_cabin_groups`, which defaults an unknown code to Economy — and quietly pay
    Economy rates on Business tickets while making Business-only deals unmatchable. So
    SKIP_CLASS applies to every row, exactly as it does on an unenriched BSP row. Mapping
    fare families to cabins needs a master that does not exist yet.

  * **A consolidator.** There isn't one; the carrier is the counterparty. `supplier_agency`
    stays None and the airline deal's own trigger does the discriminating.

Everything else — travel date, segment type, sector, YQ, YR — is real, so an LCC row is
better evidence than an unenriched BSP row and only class-restricted deals withhold.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission_run import SOURCE_LCC_DETAILED
from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.services.commission.calc_row import (
    KIND_ISSUE, KIND_REFUND, KIND_SKIP, BatchInfo, CalcRow,
)
from app.services.deal_matching import SKIP_CLASS

# An LCC statement is a sales ledger: incentives are earned on the sale, so a deal whose
# trigger is "Flown" correctly does not match here — same as BSP.
INVOICE_TYPE = "Sales"
STATEMENT_TYPE = "AIRLINE"

# `bill_kind` is already classified at ingest from the row's own total
# (services/lcc_detailed_spec.py), so the transaction policy reads that rather than
# re-deriving it from a payment-status string that varies per carrier.
_KIND = {"sale": KIND_ISSUE, "refund": KIND_REFUND, "payment": KIND_SKIP}

NEEDS_DATA_REMEDY = (
    "An LCC Detailed statement prints a fare family rather than a booking class, so a "
    "class-restricted deal cannot be verified against it. Narrow the deal by flight type "
    "instead, or price these tickets from your own internal statement."
)


def _tax(row: LccDetailed, code: str) -> float | None:
    """One named tax out of the folded `taxes` array. None when the file did not print it —
    never 0, which the engine would read as "the carrier charged nothing"."""
    for t in (row.taxes or []):
        if str(t.get("code") or "").strip().upper() == code:
            try:
                return float(t.get("amount"))
            except (TypeError, ValueError):
                return None
    return None


def _sector(row: LccDetailed) -> str | None:
    """The journey as the deal rules read it: 'DEL/BOM/MAA' from the folded legs."""
    routes = [str(s.get("route")).strip() for s in (row.segments or []) if s.get("route")]
    if not routes:
        return None
    # Legs are already in order; join on "/" like every other source's sector string, and
    # collapse a repeated airport where one leg's arrival is the next leg's departure.
    parts: list[str] = []
    for r in routes:
        for p in r.replace("-", "/").split("/"):
            p = p.strip().upper()
            if p and (not parts or parts[-1] != p):
                parts.append(p)
    return "/".join(parts) or None


def _as_date(v) -> date | None:
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


def _f(v) -> float | None:
    return float(v) if v is not None else None


def build_calc_row(row: LccDetailed, airline_name: str | None) -> CalcRow:
    kind = _KIND.get((row.bill_kind or "").lower(), KIND_ISSUE)
    ctx = CalcRow(
        source_row_id=row.id,
        ticket_number=row.record_locator or row.gds_record_locator,
        document_number=row.record_locator,
        pnr=row.record_locator or row.gds_record_locator,
        passenger_name=row.name or row.name1,
        transaction_type=row.bill_kind or row.payment_status,
        # The batch's declared carrier, not the row's: an LCC export names no carrier and
        # the uploader declares it from their Airline Master (services/lcc_airline_selection).
        airline_name=airline_name or row.airline_name,
        airline_id=row.airline_id,
        issue_date=_as_date(row.booking_date) or _as_date(row.transaction_date),
        travel_date=row.departure_date,
        segment_type=(None if row.international is None
                      else ("International" if row.international else "Domestic")),
        # See the module docstring: product_class is a fare family, not an RBD.
        booking_class=None,
        sector=_sector(row),
        fare_amount=_f(row.base_fare),
        yq=_tax(row, "YQ"),
        yr=_tax(row, "YR"),
        # `other_ssr_total` is one combined figure and a deal pays Ancillary per sub-type,
        # so it is shown but never claimed — same reasoning as the third-party SSR column.
        seat_selection=None, excess_baggage=None, meals=None,
        ancillary_amount=_f(row.other_ssr_total),
        kind=kind,
        kind_reason=("Deposit or payment line — not a sale" if kind == KIND_SKIP else None),
        statement_type=STATEMENT_TYPE,
        invoice_type=INVOICE_TYPE,
    )
    ctx.skip_criteria.add(SKIP_CLASS)
    ctx._skip_rule_fields.add("class")
    ctx.skipped_labels.append("class")
    if not ctx.sector:
        ctx.skipped_labels.append("sector")
    if not ctx.travel_date:
        ctx.skipped_labels.append("travel_date")
    if ctx.kind_reason:
        ctx.note(ctx.kind_reason)
    if row.product_class:
        ctx.note(f"The statement prints the fare family '{row.product_class}', not a booking "
                 f"class, so class-restricted deals were not evaluated for this row.")
    return ctx


class LccDetailedAdapter:
    """Loads one LCC Detailed batch and normalizes it."""

    source = SOURCE_LCC_DETAILED
    label = "LCC Detailed"
    statement_type = STATEMENT_TYPE
    has_declared_amounts = False
    requires_supplier = False
    needs_data_remedy = NEEDS_DATA_REMEDY
    model = LccDetailed

    async def list_batches(self, db: AsyncSession, tenant_id: int, user_id: int) -> list:
        """One entry per ingested batch. Unlike the spec-driven types this source HAS a
        header row, so the period and carrier come off it rather than a GROUP BY."""
        rows = (await db.execute(
            select(
                LccDetailedBatch.batch_id,
                LccDetailedBatch.source_file,
                LccDetailedBatch.uploaded_at,
                LccDetailedBatch.airline_name,
                LccDetailedBatch.airline_code,
                LccDetailedBatch.status,
                func.count(LccDetailed.id).label("row_count"),
                func.min(LccDetailed.departure_date).label("period_from"),
                func.max(LccDetailed.departure_date).label("period_to"),
            )
            .outerjoin(LccDetailed, LccDetailed.batch_id == LccDetailedBatch.batch_id)
            .where(LccDetailedBatch.tenant_id == tenant_id,
                   LccDetailedBatch.created_by_id == user_id)
            .group_by(LccDetailedBatch.batch_id, LccDetailedBatch.source_file,
                      LccDetailedBatch.uploaded_at, LccDetailedBatch.airline_name,
                      LccDetailedBatch.airline_code, LccDetailedBatch.status)
            .order_by(LccDetailedBatch.uploaded_at.desc())
        )).all()
        return [
            BatchInfo(
                batch_id=r.batch_id, source_file=r.source_file, uploaded_at=r.uploaded_at,
                row_count=r.row_count or 0, period_from=r.period_from, period_to=r.period_to,
                airline_name=r.airline_name, airline_code=r.airline_code,
                # The ingest is asynchronous here, so a batch can exist with no rows yet.
                parse_status=r.status or "completed",
            )
            for r in rows
        ]

    async def supplier_for_batch(self, db: AsyncSession, tenant_id: int, batch_id: str):
        """No consolidator: the carrier is the counterparty on its own statement."""
        return None


    async def load_rows(self, db: AsyncSession, tenant_id: int, user_id: int,
                        batch_id: str, row_ids: list[int] | None = None) -> list:
        conds = [LccDetailed.batch_id == batch_id, LccDetailed.tenant_id == tenant_id,
                 LccDetailed.created_by_id == user_id]
        if row_ids:
            conds.append(LccDetailed.id.in_(row_ids))
        return list((await db.execute(
            select(LccDetailed).where(*conds).order_by(LccDetailed.id.asc())
        )).scalars().all())

    async def build_contexts(self, db: AsyncSession, rows: list, tenant_id: int,
                             user_id: int, batch_id: str) -> list[CalcRow]:
        batch = (await db.execute(
            select(LccDetailedBatch).where(LccDetailedBatch.batch_id == batch_id)
        )).scalar_one_or_none()
        airline = batch.airline_name if batch else None
        return [build_calc_row(r, airline) for r in rows]

    async def cumulative_provider(self, db: AsyncSession, tenant_id: int, user_id: int):
        """None → the engine's default. One carrier's statement is a slice of the year, so
        summing only its own rows would understate every slab and pay the bottom band."""
        return None
