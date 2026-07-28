"""
Repair BSP statements parsed under the OLD SPDR->CANX distribution rule.

The old pass filled CANX rows from their parent SPDR's bulk cancellation charge but left
the SPDR row at its full amount — so the charge was counted twice by the live
"Summary (Calculated from detailed)" aggregation, and any airline with an SPDR showed a
red variance against the uploaded summary. It also filled *partially* when the group had
fewer zero-amount CANX rows than the charge covered, which never re-adds to the original.

This script undoes that distribution and re-applies the current all-or-nothing rule
(`app.workers.bsp_tasks._distribute_spdr_canx`) WITHOUT re-parsing the source PDF.

Undoing is lossless: the old pass only overwrote `document_number`, and for a CANX row
`derive_ticket_number()` had already copied the printed document number into
`ticket_number`, which was deliberately left untouched. So `document_number` is restored
from `ticket_number`.

The grand totals (`bsp_statements.gt_*`) are NOT recomputed — they are snapshotted during
parsing, before any distribution, so they already hold the correct pre-split values.

Safe to run repeatedly: both the undo and the re-apply are idempotent.

Caveat: the undo finds previously-filled CANX rows by `spdr_no IS NOT NULL`. A statement
parsed before the `spdr_no` column existed (migration bsp_detailed_enrich_03) was filled
without that stamp and cannot be identified here — re-parse those from the UI instead.

    cd backend
    python backfill_spdr_canx.py --dry-run           # report only, no writes
    python backfill_spdr_canx.py                     # repair every statement
    python backfill_spdr_canx.py --batch-id <uuid>   # repair one statement
"""

import argparse
import asyncio
import logging

from sqlalchemy import Numeric, Text, cast, func, select, update

from app.database import AsyncSessionLocal
from app.models.bsp_statement import BspStatement, BspStatementRow
from app.workers.bsp_tasks import _distribute_spdr_canx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
# The app engine is built with echo=settings.DEBUG; a full SQL dump would bury the report.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def _stats(db, batch_id: str) -> dict:
    """Split-state counters for one statement, for the before/after report."""
    R = BspStatementRow
    row = (await db.execute(
        select(
            func.count().filter(R.transaction_type == "SPDR").label("spdrs"),
            func.count().filter(
                (R.transaction_type == "SPDR") & (R.transaction_amount == 0)
            ).label("spdrs_split"),
            func.count().filter(
                (R.transaction_type == "CANX") & (R.spdr_no.isnot(None))
            ).label("canx_filled"),
            func.coalesce(func.sum(R.transaction_amount).filter(
                R.transaction_type.in_(("SPDR", "CANX"))
            ), 0).label("combined_total"),
        ).where(R.statement_id == batch_id)
    )).one()
    return dict(row._mapping)


async def _undo(db, batch_id: str) -> tuple[int, int]:
    """Revert a previous distribution back to the printed statement, returning
    ``(canx_reverted, spdr_restored)``.

    Both halves must be undone together. Reverting the CANX rows without putting the charge
    back on a zeroed SPDR would destroy it — which is why the distribution records the
    original amount in ``raw_data['spdr_split']``.
    """
    R = BspStatementRow

    canx = await db.execute(
        update(R)
        .where(
            R.statement_id == batch_id,
            R.transaction_type == "CANX",
            R.spdr_no.isnot(None),
        )
        .values(
            # ticket_number holds the printed document number for a CANX; fall back to the
            # current value rather than nulling it if that were ever missing.
            document_number=func.coalesce(R.ticket_number, R.document_number),
            transaction_amount=0,
            spdr_no=None,
            raw_data=(R.raw_data
                      .op("-")(cast("settlement_section", Text))
                      .op("-")(cast("settlement_category", Text))),
        )
    )

    # Older statements were filled before `spdr_split` was recorded; those SPDRs were never
    # zeroed, so there is simply nothing to restore and this UPDATE matches no rows.
    spdr = await db.execute(
        update(R)
        .where(
            R.statement_id == batch_id,
            R.transaction_type == "SPDR",
            R.raw_data.has_key("spdr_split"),
        )
        .values(
            transaction_amount=cast(R.raw_data[("spdr_split", "amount")].astext, Numeric(14, 2)),
            raw_data=R.raw_data.op("-")(cast("spdr_split", Text)),
        )
    )
    return (canx.rowcount or 0), (spdr.rowcount or 0)


async def main(batch_id: str | None, dry_run: bool) -> None:
    async with AsyncSessionLocal() as db:
        q = select(BspStatement.batch_id).order_by(BspStatement.created_at)
        if batch_id:
            q = q.where(BspStatement.batch_id == batch_id)
        batches = (await db.execute(q)).scalars().all()

        if not batches:
            print("[!] No BSP statements found" + (f" for batch {batch_id}." if batch_id else "."))
            return

        print(f"[*] {len(batches)} statement(s) to process"
              f"{' — DRY RUN, no writes' if dry_run else ''}\n")

        for bid in batches:
            before = await _stats(db, bid)
            if not before["spdrs"] and not before["canx_filled"]:
                continue   # no SPDR/CANX activity in this statement

            if dry_run:
                print(f"  {bid}  SPDRs={before['spdrs']} split={before['spdrs_split']} "
                      f"CANX filled={before['canx_filled']} "
                      f"SPDR+CANX total={before['combined_total']}")
                continue

            reverted, restored = await _undo(db, bid)
            await db.commit()

            # Baseline: the undone state is the printed truth (charge whole on each SPDR,
            # CANX rows at 0). Re-applying the rule must leave this total untouched.
            undone = await _stats(db, bid)
            # `_distribute_spdr_canx` opens its own `db.begin()`, which would raise if the
            # read above left a transaction auto-begun — so close it first.
            await db.commit()

            await _distribute_spdr_canx(db, bid)

            after = await _stats(db, bid)
            await db.commit()

            print(f"  {bid}  CANX reverted={reverted} SPDR restored={restored}  "
                  f"SPDRs split {before['spdrs_split']} -> {after['spdrs_split']}  "
                  f"CANX filled {before['canx_filled']} -> {after['canx_filled']}  "
                  f"SPDR+CANX total {before['combined_total']} -> {after['combined_total']}"
                  f" (printed: {undone['combined_total']})")

            if undone["combined_total"] != after["combined_total"]:
                print(f"    [!] TOTAL CHANGED for {bid}: {undone['combined_total']} -> "
                      f"{after['combined_total']}. The distribution must be sum-preserving; "
                      f"investigate before trusting this statement.")

        print("\n[+] Done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--batch-id", default=None, help="repair a single statement")
    ap.add_argument("--dry-run", action="store_true", help="report current state, write nothing")
    args = ap.parse_args()
    asyncio.run(main(args.batch_id, args.dry_run))
