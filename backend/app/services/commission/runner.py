"""Pricing a statement against the deals that cover it, whatever the statement is.

Structurally this is `bsp_commission.BspCommissionService._process`, generalised: the same
order of operations, the same statuses, the same withholding rule. What changed is where
the answers go — into `commission_calculations` rather than onto the source row — because
the third-party and LCC tables hold the vendor's document and a figure we derived is not
part of it.

Three things here are not obvious and are load-bearing:

  1. **Issues first, refunds last.** A refund reverses the row it refunds, and the two can
     sit in the same file. Running in document order would meet the refund before the issue
     it cancels and report "no previously calculated issue found" for a ticket that is right
     there. This is not an optimisation.

  2. **Payout rules are the caller's job.** `find_all_deals` does not evaluate a deal's
     inclusion/exclusion rules — BSP has always run that pass itself. Skipping it here would
     pay third-party rows on terms nobody checked.

  3. **Totals are recomputed from the ledger, never accumulated.** A "run selected rows"
     that added its own deltas to the header would leave the headline disagreeing with the
     grid the moment anyone ran a subset twice.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commission_calculation import CommissionCalculation
from app.models.commission_run import CommissionRun
from app.services import commission_core as core
from app.services.bsp_reconciliation import norm_tn
from app.services.commission.calc_row import KIND_REFUND, KIND_SKIP, CalcRow
from app.services.deal_matching import DealMatchingService

logger = logging.getLogger(__name__)

# Rows between progress flushes. Matches bsp_commission.CHUNK: small enough that the bar
# moves, large enough that the commit is not the bottleneck.
CHUNK = 200

# Statuses that count as "a deal applied". `reversed` belongs here — a reversal IS a match,
# and leaving it out makes the header disagree with the grid by the refund count.
MATCHED_STATUSES = ("calculated", "reversed")


def _pct(raw) -> float:
    """A deal's IATA commission cell ('2', '2%', ' 2.5 ') as a number."""
    if not raw:
        return 0.0
    try:
        return float(str(raw).strip().rstrip("%").strip())
    except (TypeError, ValueError):
        return 0.0


def _variance(ctx: CalcRow, computed_incentive: float | None,
              computed_iata: float | None) -> dict:
    """Deal-computed minus vendor-declared. Positive = under-recovery: they owe you.

    GROSS TO GROSS. The declared commission is before TDS (see calc_row.DeclaredAmounts)
    and a deal's rates are gross, so no netting happens on either side.

    A row whose declared figures do not add up to its own Net Amount gets no variance at
    all: comparing against arithmetic that does not close is worse than saying nothing.
    """
    d = ctx.declared
    if d is None or not d.any_declared() or d.net_ok is False:
        return {}
    v_comm = round((computed_iata or 0.0) - (d.commission or 0.0), 2)
    v_inc = round((computed_incentive or 0.0) - (d.incentive or 0.0), 2)
    return {
        "variance_commission": v_comm,
        "variance_incentive": v_inc,
        "variance_total": round(v_comm + v_inc, 2),
    }


class CommissionRunner:
    """Runs one adapter's batch. Stateless — the run row carries the state."""

    def __init__(self, adapter):
        self.adapter = adapter

    # ── The per-row calculation ──────────────────────────────────────────────
    async def calculate_row(self, db: AsyncSession, ctx: CalcRow, tenant_id: int,
                            created_by_id: int, cumulative_provider=None,
                            original_index: dict | None = None) -> core.RowCalcResult:
        """Mirrors bsp_commission.calculate_row step for step, on a CalcRow."""
        rid = ctx.source_row_id

        # 1. Never a sale.
        if ctx.kind == KIND_SKIP:
            return core.RowCalcResult(row_id=rid, status="skipped", incentive=0,
                                      reason=ctx.kind_reason or "Not a sale")

        # 2. Refund → reverse what the original earned.
        if ctx.kind == KIND_REFUND:
            key = norm_tn(ctx.ticket_number) if ctx.ticket_number else None
            original = (original_index or {}).get(key) if key else None
            # Exclude self: a ticket issued and refunded in the same file appears twice
            # under one number, and a row must never reverse itself.
            if original is not None and original.source_row_id != rid \
                    and original.incentive is not None:
                breakdown = {k: -float(v) for k, v in (original.incentive_breakdown or {}).items()}
                return core.RowCalcResult(
                    row_id=rid, status="reversed",
                    incentive=-float(original.incentive),
                    iata_commission=-float(original.iata_commission or 0),
                    deal_id=original.matched_deal_id,
                    deal_type=original.matched_deal_type,
                    deal_name=original.matched_deal_name,
                    breakdown=breakdown,
                    reason=(f"Reversal of ticket {original.ticket_number or '—'} — "
                            f"original incentive {original.incentive}"),
                )
            # DELIBERATELY THE SAME SENTENCE FOR EVERY SUCH ROW. The gaps tab groups by
            # (status, reason) and caps at 50 groups, so naming the ticket here turns one
            # actionable bucket into one group per refund: a real 203-row LCC batch
            # produced 48 groups from 53 refunds and pushed every other reason off the
            # screen. The ticket numbers are not lost — the gaps response carries sample
            # documents per bucket, and the row's own grid cell shows its ticket.
            # (`needs_data_reason` in commission_core spells out the same lesson.)
            return core.RowCalcResult(
                row_id=rid, status="skipped", incentive=0,
                reason="Refund with no matching issue in this statement — nothing to reverse.",
            )

        # 3. An issue needs a carrier and a date.
        if not ctx.airline_name:
            return core.RowCalcResult(
                row_id=rid, status="unmatched",
                reason="Airline not recognised — this row's carrier is not in the airline master.")
        if ctx.issue_date is None:
            return core.RowCalcResult(row_id=rid, status="unmatched",
                                      reason="Row has no issue or booking date.")

        # 4. Deal search. `statement_type` is what confines a third-party row to B2B deals
        #    and an LCC one to airline deals; `supplier_agency_id` is what tells two
        #    channels of one consolidator apart.
        match = await DealMatchingService.find_best_deal(
            db=db,
            airline_name=ctx.airline_name,
            travel_date=ctx.travel_date or ctx.issue_date,
            tenant_id=tenant_id,
            created_by_id=created_by_id,
            issue_date=ctx.issue_date,
            segment_type=ctx.segment_type,
            booking_class=ctx.booking_class,
            invoice_type=ctx.invoice_type,
            sell_fare=ctx.fare_amount,
            sell_tax_yq=ctx.yq,
            sale_yr=ctx.yr,
            seat_selection=ctx.seat_selection,
            excess_baggage=ctx.excess_baggage,
            meals=ctx.meals,
            supplier_agency=ctx.supplier_agency,
            supplier_agency_id=ctx.supplier_agency_id,
            statement_type=ctx.statement_type,
            skip_criteria=ctx.skip_criteria,
            cumulative_provider=cumulative_provider,
        )
        if match is None:
            reason = ("No matching approved B2B deal found for this consolidator."
                      if ctx.statement_type == "B2B"
                      else "No matching approved airline deal found.")
            return core.RowCalcResult(row_id=rid, status="unmatched", reason=reason)

        breakdown = match.incentive_breakdown or {}
        total = round(sum(breakdown.values()), 2) if breakdown else match.calculated_incentive
        # The deal's own % on the settled fare. Its own column, deliberately NOT part of
        # the incentive total — the two are different entitlements.
        iata = round(_pct(match.iata_commission) / 100.0 * float(ctx.fare_amount or 0), 2)

        # A deal that pays Ancillary cannot be honoured from one combined SSR figure.
        if ctx.ancillary_amount and "Ancillary" in breakdown:
            ctx.note(f"This deal pays an Ancillary incentive per sub-type (baggage / meals / "
                     f"seat), but the statement prints one combined SSR amount of "
                     f"{ctx.ancillary_amount:,.2f} — the split is unknown, so none was claimed.")

        blocked, _had_inclusion, reason, rule_unconfirmed = await core.apply_payout_rules(
            db, match.deal_id, breakdown, ctx)
        if blocked:
            return core.RowCalcResult(
                row_id=rid, status="excluded", incentive=0, iata_commission=iata,
                deal_id=match.deal_id, deal_type=match.deal_type, deal_name=match.deal_name,
                reason=reason)

        # Did we actually check everything this deal pays on? A criterion the document does
        # not print was SKIPPED by the matcher, not satisfied by it. Where the deal
        # restricts by such a criterion the figure is a guess, so nothing is claimed and
        # nothing is shown — a column reading ₹245.40 on a row that pays nothing is read as
        # money however the status is labelled.
        unconfirmed = sorted(set(match.unconfirmed_criteria) | rule_unconfirmed)
        if unconfirmed:
            return core.RowCalcResult(
                row_id=rid, status="needs_data", incentive=None,
                reason=core.needs_data_reason(
                    match.deal_no, unconfirmed,
                    remedy=getattr(self.adapter, "needs_data_remedy", None)),
            )

        return core.RowCalcResult(
            row_id=rid, status="calculated", incentive=total, iata_commission=iata,
            deal_id=match.deal_id, deal_type=match.deal_type, deal_name=match.deal_name,
            breakdown=breakdown,
            reason=getattr(match, "supplier_match_by", None) == "name" and (
                "Matched by supplier NAME only — this deal names no Supplier master branch, "
                "and 141 of the master's names cover more than one branch."
            ) or None,
        )

    # ── Persistence ──────────────────────────────────────────────────────────
    def _to_calculation(self, ctx: CalcRow, res: core.RowCalcResult, run: CommissionRun,
                        match_by: str | None) -> dict:
        d = ctx.declared
        values = dict(
            run_id=run.id, tenant_id=run.tenant_id, created_by_id=run.created_by_id,
            source=run.source, batch_id=run.batch_id, source_row_id=ctx.source_row_id,
            status=res.status, reason=res.reason,
            matched_deal_id=res.deal_id, matched_deal_type=res.deal_type,
            matched_deal_name=res.deal_name,
            matched_deal_no=(f"{'B2B' if res.deal_type == 'b2b' else 'AIR'}-{res.deal_id:06d}"
                             if res.deal_id else None),
            supplier_match_by=match_by,
            incentive=res.incentive, iata_commission=res.iata_commission,
            incentive_breakdown=res.breakdown or {},
            skipped_criteria=ctx.skipped_labels or [],
            unconfirmed_criteria=[],
            notes=ctx.notes or [],
            airline_name=ctx.airline_name, airline_id=ctx.airline_id,
            issue_date=ctx.issue_date, travel_date=ctx.travel_date,
            segment_type=ctx.segment_type, booking_class=ctx.booking_class,
            sector=ctx.sector, fare_amount=ctx.fare_amount, yq=ctx.yq, yr=ctx.yr,
            ancillary_amount=ctx.ancillary_amount,
            document_number=ctx.document_number, ticket_number=ctx.ticket_number,
            pnr=ctx.pnr, passenger_name=ctx.passenger_name,
            transaction_type=ctx.transaction_type,
            calculated_at=datetime.utcnow(),
        )
        if d is not None:
            values.update(declared_commission=d.commission, declared_incentive=d.incentive,
                          declared_tds=d.tds, declared_net=d.net, declared_net_ok=d.net_ok)
            values.update(_variance(ctx, res.incentive, res.iata_commission))
        return values

    async def _upsert(self, db: AsyncSession, run: CommissionRun, values_list: list[dict]) -> None:
        """One CURRENT answer per source row — replace, never accumulate.

        A plain delete-then-insert on the touched ids rather than an ON CONFLICT: it keeps
        the same shape whether the run covers a whole batch or a hand-picked selection, and
        the unique index makes a mistake here loud rather than silent.
        """
        if not values_list:
            return
        ids = [v["source_row_id"] for v in values_list]
        await db.execute(delete(CommissionCalculation).where(
            CommissionCalculation.tenant_id == run.tenant_id,
            CommissionCalculation.created_by_id == run.created_by_id,
            CommissionCalculation.source == run.source,
            CommissionCalculation.source_row_id.in_(ids),
        ))
        db.add_all([CommissionCalculation(**v) for v in values_list])

    # ── The run ──────────────────────────────────────────────────────────────
    async def run(self, db: AsyncSession, run: CommissionRun,
                  row_ids: list[int] | None = None) -> CommissionRun:
        adapter = self.adapter
        run.status = "processing"
        run.started_at = run.started_at or datetime.utcnow()
        run.heartbeat_at = datetime.utcnow()
        await db.commit()

        try:
            rows = await adapter.load_rows(db, run.tenant_id, run.created_by_id,
                                           run.batch_id, row_ids)
            contexts = await adapter.build_contexts(db, rows, run.tenant_id,
                                                    run.created_by_id, run.batch_id)
            provider = await adapter.cumulative_provider(db, run.tenant_id, run.created_by_id)

            run.total_rows = len(contexts)
            run.processed_rows = 0
            await db.commit()

            original_index = await self._build_original_index(db, run)

            # ISSUES FIRST, REFUNDS LAST — see the module docstring.
            ordered = ([c for c in contexts if c.kind != KIND_REFUND]
                       + [c for c in contexts if c.kind == KIND_REFUND])

            pending: list[dict] = []
            done = 0
            for ctx in ordered:
                try:
                    res = await self.calculate_row(
                        db, ctx, run.tenant_id, run.created_by_id,
                        cumulative_provider=provider, original_index=original_index)
                    match_by = None
                    if res.status == "calculated" and ctx.statement_type == "B2B":
                        match_by = "id" if ctx.supplier_agency_id else "name"
                except Exception as exc:  # noqa: BLE001 — one bad row must not kill the run
                    logger.exception("commission row %s failed", ctx.source_row_id)
                    res = core.RowCalcResult(row_id=ctx.source_row_id, status="unmatched",
                                             reason=f"Calculation error: {exc}"[:500])
                    match_by = None

                values = self._to_calculation(ctx, res, run, match_by)
                pending.append(values)
                # A reversal must be able to find an issue calculated moments ago in this
                # same run, so the index is updated as we go rather than only at the start.
                if res.status == "calculated" and ctx.ticket_number:
                    original_index[norm_tn(ctx.ticket_number)] = _Original(values)

                done += 1
                if len(pending) >= CHUNK:
                    await self._upsert(db, run, pending)
                    pending = []
                    run.processed_rows = done
                    run.heartbeat_at = datetime.utcnow()
                    await db.commit()

            await self._upsert(db, run, pending)
            run.processed_rows = done
            run.heartbeat_at = datetime.utcnow()
            await db.commit()

            await self.refresh_totals(db, run)
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            run.status = "failed"
            run.error = str(exc)[:2000]
            run.completed_at = datetime.utcnow()
            await db.commit()
            raise
        return run

    async def _build_original_index(self, db: AsyncSession, run: CommissionRun) -> dict:
        """Issues in this batch that already have a figure, keyed for refund lookup.

        Keyed with `norm_tn` — the same normalisation BSP reconciliation and TGQ enrichment
        use — so a refund printed with a different prefix or leading zeros still finds its
        issue.
        """
        rows = (await db.execute(
            select(CommissionCalculation).where(
                CommissionCalculation.tenant_id == run.tenant_id,
                CommissionCalculation.created_by_id == run.created_by_id,
                CommissionCalculation.source == run.source,
                CommissionCalculation.batch_id == run.batch_id,
                CommissionCalculation.status.in_(("calculated", "excluded")),
                CommissionCalculation.incentive.is_not(None),
            ).order_by(CommissionCalculation.issue_date.asc().nullslast(),
                       CommissionCalculation.id.asc())
        )).scalars().all()
        index: dict = {}
        for r in rows:
            if r.ticket_number:
                index[norm_tn(r.ticket_number)] = r
        return index

    async def refresh_totals(self, db: AsyncSession, run: CommissionRun) -> None:
        """Recompute the run header from the ledger. Derived, never accumulated."""
        C = CommissionCalculation
        scope = (C.tenant_id == run.tenant_id, C.created_by_id == run.created_by_id,
                 C.source == run.source, C.batch_id == run.batch_id)
        agg = (await db.execute(select(
            func.count().label("total"),
            func.count().filter(C.status == "calculated"),
            func.count().filter(C.status == "needs_data"),
            func.count().filter(C.status == "excluded"),
            func.count().filter(C.status == "reversed"),
            func.count().filter(C.status == "skipped"),
            func.count().filter(C.status == "unmatched"),
            func.count().filter(C.status == "pending"),
            func.coalesce(func.sum(C.incentive).filter(C.status.in_(MATCHED_STATUSES)), 0),
            func.coalesce(func.sum(C.iata_commission).filter(C.status.in_(MATCHED_STATUSES)), 0),
            func.coalesce(func.sum(C.declared_commission), 0),
            func.coalesce(func.sum(C.declared_incentive), 0),
            # Only rows whose declared arithmetic closed contribute to the headline gap.
            func.coalesce(func.sum(C.variance_total).filter(C.declared_net_ok.is_(True)), 0),
            func.count().filter(C.declared_net_ok.is_(False)),
        ).where(*scope))).one()

        (run.total_rows, run.calculated_rows, run.needs_data_rows, run.excluded_rows,
         run.reversed_rows, run.skipped_rows, run.unmatched_rows, run.pending_rows,
         run.total_incentive, run.total_iata, run.declared_commission_total,
         run.declared_incentive_total, run.variance_total,
         run.variance_unverified_rows) = agg


class _Original:
    """The subset of a just-written calculation a later refund needs, without a re-read."""

    __slots__ = ("source_row_id", "incentive", "iata_commission", "incentive_breakdown",
                 "matched_deal_id", "matched_deal_type", "matched_deal_name", "ticket_number")

    def __init__(self, values: dict):
        for k in self.__slots__:
            setattr(self, k, values.get(k))
