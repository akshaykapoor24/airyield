"""Match issued tickets back to their Series / SIT / MICE block booking.

A contract books a group PNR for N pax and pays for it up front. Tickets are then
issued against that PNR over time, so the question the contract exists to answer
is "we bought 40 seats — how many actually ticketed, and for how much?"

The join key is the PNR, checked against BOTH `gds_pnr` and `air_pnr`: the two
columns come from two different upload templates, and an airline-format ticket
can carry the airline PNR in one and the GDS PNR in the other. Matching is
case-insensitive; `alembic/versions/series_contract_01_*` adds the functional
lower() indexes that keeps it off a sequential scan.

Recompute is wholesale and idempotent — every run rebuilds the rollup from the
tickets rather than adding to it, so running twice can never double-count. That
is what makes it safe to fire automatically after every ticket save.

Pure read of tickets, write of contracts. Never commits: the caller owns the
transaction, so a match that runs inside a ticket save shares its commit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.series_contract import SeriesContract
from app.models.uploaded_ticket import UploadedTicket

# Backstop so a pathological tenant cannot build an unbounded in-memory index.
# Mirrors MAX_TGQ_ROWS in bsp_tgq_enrichment.
MAX_TICKET_ROWS = 200_000

# Status vocabulary, derived from tickets issued vs pax booked.
PENDING = "pending"
PARTIAL = "partial"
COMPLETE = "complete"
OVER_ISSUED = "over_issued"


def norm_pnr(s) -> str | None:
    """Normalise a PNR for joining: drop non-alphanumerics, uppercase.

    Deliberately does NOT strip leading zeros the way `bsp_reconciliation.norm_tn`
    does. A ticket number is a numeric document id where "0098…" and "98…" are the
    same document; a PNR is a fixed-width record locator where "0ABCDE" and "ABCDE"
    are two different bookings.
    """
    if not s:
        return None
    core = re.sub(r"[^0-9A-Za-z]", "", str(s))
    return core.upper() or None


def _status(tickets_issued: int, pax_count: int | None) -> str:
    """Where this contract stands. Unknown pax count can only ever be pending or partial."""
    if tickets_issued == 0:
        return PENDING
    if not pax_count or pax_count <= 0:
        return PARTIAL
    if tickets_issued < pax_count:
        return PARTIAL
    if tickets_issued == pax_count:
        return COMPLETE
    return OVER_ISSUED


@dataclass
class RunSummary:
    contracts: int = 0
    pending: int = 0
    partial: int = 0
    complete: int = 0
    over_issued: int = 0
    tickets_matched: int = 0
    amount_matched: float = 0.0


class SeriesContractMatchingService:

    @staticmethod
    async def run(
        db:            AsyncSession,
        *,
        tenant_id:     int,
        created_by_id: int,
        contract_id:   int | None = None,
    ) -> RunSummary:
        """Recompute the issuance rollup for the user's contracts.

        `contract_id` narrows the run to one contract; omit it for all of them.
        Does not commit — the caller does.
        """
        summary = RunSummary()

        cq = select(SeriesContract).where(
            SeriesContract.tenant_id == tenant_id,
            SeriesContract.created_by_id == created_by_id,
        )
        if contract_id is not None:
            cq = cq.where(SeriesContract.id == contract_id)
        contracts = (await db.execute(cq)).scalars().all()
        if not contracts:
            return summary

        # Only pull tickets once, and only the columns the rollup needs.
        tickets = (await db.execute(
            select(
                UploadedTicket.gds_pnr,
                UploadedTicket.air_pnr,
                UploadedTicket.ticket_number,
                UploadedTicket.total_amt,
            ).where(
                UploadedTicket.tenant_id == tenant_id,
                UploadedTicket.created_by_id == created_by_id,
                # ADM/ACM/RA rows are credit notes and refund applications against
                # a ticket, not an issued ticket. Counting them would inflate the
                # contract twice over — once for the ticket, once for its memo.
                UploadedTicket.adm_acm_ra.is_(None),
            ).limit(MAX_TICKET_ROWS)
        )).all()

        # Index by PNR. A ticket is filed under both of its PNRs, so a contract
        # written against either one finds it — but into a set keyed by ticket
        # number, so a ticket whose two PNRs are equal is not counted twice.
        by_pnr: dict[str, dict[str, Decimal]] = {}
        for i, (gds_pnr, air_pnr, ticket_number, total_amt) in enumerate(tickets):
            keys = {k for k in (norm_pnr(gds_pnr), norm_pnr(air_pnr)) if k}
            if not keys:
                continue
            # A blank ticket number is still an issued seat, so it must count —
            # but it cannot dedupe by number. Key it by row position instead, or
            # every unnumbered ticket on the PNR would collapse into one.
            tn = (ticket_number or "").strip() or f"__row_{i}__"
            for key in keys:
                by_pnr.setdefault(key, {})[tn] = (
                    total_amt if total_amt is not None else Decimal("0")
                )

        now = datetime.utcnow()
        for contract in contracts:
            matched = by_pnr.get(norm_pnr(contract.pnr_no) or "", {})
            numbers = sorted(n for n in matched if not n.startswith("__row_"))
            amount = sum(matched.values(), Decimal("0"))

            contract.tickets_issued = len(matched)
            contract.ticket_numbers = numbers or None
            contract.amount_issued = amount
            contract.match_status = _status(len(matched), contract.pax_count)
            contract.last_matched_at = now

            summary.contracts += 1
            summary.tickets_matched += len(matched)
            summary.amount_matched += float(amount)
            setattr(summary, contract.match_status, getattr(summary, contract.match_status) + 1)

        summary.amount_matched = round(summary.amount_matched, 2)
        return summary
