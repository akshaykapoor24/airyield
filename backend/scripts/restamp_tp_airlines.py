"""Resolve the carrier of third-party statement lines already saved, again.

WHEN TO RUN
  * Once, after deploying the change that reads a 3-digit accounting code printed in the
    Airline Code column ("465") as the carrier (services/tp_airline_resolution.numeric_code).
    TripJack's uploads before it have that number as their Airline Code and no Airline Name,
    so Commission income and PLB accrual cannot see their carrier.
  * Again after carriers are added to the platform Airline Master, for the lines that named
    one it did not have yet. A line is stamped once, at upload, and nothing else revisits it.

WHAT IT DOES
  For every type that resolves its carrier (Third Party GDS — saved and left-out lines —,
  Third Party LCC, MO statement): the lines left unresolved, or with a numeric Airline Code,
  are resolved against the Airline Master exactly as an upload is now. Each statement that
  changed is re-projected onto the income board, which copies the carrier. Commission
  already calculated for those statements is NOT redone — re-run it to price them.

    python -m scripts.restamp_tp_airlines --dry-run     # report, write nothing
    python -m scripts.restamp_tp_airlines
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# app.database builds its engine with echo=settings.DEBUG; this script prints a summary.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from app.database import AsyncSessionLocal, engine                             # noqa: E402
from app.models.statement_row import STATEMENT_MODELS, ThirdPartyGdsLeftOut    # noqa: E402
from app.services import income_board, statement_spec as spec                 # noqa: E402
from app.services import tp_airline_resolution as tp_airline                   # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()
    engine.echo = False

    async with AsyncSessionLocal() as db:
        index = await tp_airline.build_index(db)
        touched: set[tuple[str, int, int, str]] = set()
        for slug, model in STATEMENT_MODELS.items():
            if not spec.resolves_airline(slug):
                continue
            # The left-out lines are copies of saved ones, kept apart and never projected.
            for m, projected in [(model, True)] + ([(ThirdPartyGdsLeftOut, False)] if slug == "tp-gds" else []):
                changed, batches = await tp_airline.restamp_saved(db, m, index)
                print(f"{m.__tablename__}: {changed} line(s) re-resolved in {len(batches)} statement(s)")
                if projected:
                    touched |= {(slug, *b) for b in batches}

        if args.dry_run:
            await db.rollback()
            print("Dry run - nothing written.")
            return 0

        await db.flush()
        for slug, tenant_id, user_id, batch_id in sorted(touched):
            await income_board.refresh(db, tenant_id=tenant_id, user_id=user_id, source=slug, batch_id=batch_id)
        await db.commit()
        print(f"Re-projected {len(touched)} statement(s) onto the income board.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
