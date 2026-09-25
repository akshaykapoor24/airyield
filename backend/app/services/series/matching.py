"""Match issued tickets back to the block booking that bought the seats, and price the
result.

THE QUESTION THIS ANSWERS. A contract commits the agency to N seats at a negotiated fare,
paid for up front. Tickets are then issued against its PNRs over weeks. So: how many of
those seats actually ticketed, for how much, and did the contract make money?

WHAT MOVED SINCE THE FIRST VERSION. The match key used to live on the contract — one
`pnr_no` column, one PNR per contract. It now lives on `series_bookings`, many per
allocation, because airlines split large groups as a matter of course and a reissue mints
a new locator. Rollups therefore cascade: tickets sum into a booking, bookings into an
allocation, allocations into the contract.

WHY THE QUERY IS NARROW NOW. The old service loaded up to 200,000 tickets into a Python
dict and indexed the lot, because with the PNR scattered across contract rows there was
nothing to narrow by. With bookings as rows the exact PNR set is known before the query
runs, so it asks for those and nothing else — riding functional indexes that normalise the
PNR in the database exactly the way `norm_pnr` does in Python (see `PNR_NORM_SQL`). Same
answer, without reading the table.

WHY THE TICKET QUERY IS NOT SCOPED TO A USER. Every other reader in this codebase filters
`tenant_id AND created_by_id`. This one filters on the tenant alone, and it has to:
contracts are visible workspace-wide, so a contract entered by one person must be able to
match a statement uploaded by another. Scoping the tickets per-creator while the contracts
are per-tenant would produce a feature that silently finds nothing whenever two people
share the work. A ticket issued on a group PNR belongs to the agency's contract regardless
of who loaded the file.

RECOMPUTE IS WHOLESALE AND IDEMPOTENT. Every run rebuilds the rollup from the tickets
rather than adding to it, so running twice cannot double-count. That is what makes it safe
to fire automatically after every ticket save.

NEVER COMMITS. The caller owns the transaction, so a match that runs inside a ticket save
shares its commit. Pure read of tickets; writes only to the series tables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.series import (
    SeriesAllocation, SeriesBooking, SeriesContract, SeriesFareComponent, SeriesPassenger,
)
from app.models.uploaded_ticket import UploadedTicket
from app.services.markup_categories import CATEGORY_AIR
from app.services.series import bases, rollups

ZERO = Decimal("0")

# How many PNRs go into one IN-list. Postgres copes with far more, but a bounded chunk
# keeps the plan stable and the statement readable in a log.
PNR_CHUNK = 1_000

# The database's version of `norm_pnr`. These two MUST agree — the functional indexes in
# `series_v2_01` are built on this expression, and Python re-checks with the function
# below, so a divergence would mean the index finds rows the code then discards (slow) or
# misses rows the code would have kept (wrong).
#
# upper() before stripping rather than after is deliberate: it makes the expression
# IMMUTABLE for the index, and for ASCII the two orders give the same string.
PNR_NORM_SQL = "regexp_replace(upper({col}), '[^0-9A-Z]', '', 'g')"


def norm_pnr(value) -> str | None:
    """Normalise a PNR for joining: drop non-alphanumerics, uppercase.

    Deliberately does NOT strip leading zeros the way `bsp_reconciliation.norm_tn` does. A
    ticket number is a numeric document id where "0098…" and "98…" are the same document;
    a PNR is a fixed-width record locator where "0ABCDE" and "ABCDE" are two different
    bookings.
    """
    if not value:
        return None
    core = re.sub(r"[^0-9A-Za-z]", "", str(value))
    return core.upper() or None


def _norm_column(column):
    """The SQL normalisation, as a clause matching `PNR_NORM_SQL` and its index."""
    return func.regexp_replace(func.upper(column), "[^0-9A-Z]", "", "g")


@dataclass
class _Issued:
    """One ticket as the rollup sees it."""
    pax: int
    amount: Decimal


@dataclass
class RunSummary:
    """What a matching run did — counters, not rows, like BatchRunCalculationResult."""
    contracts: int = 0
    allocations: int = 0
    bookings: int = 0
    pending: int = 0
    partial: int = 0
    complete: int = 0
    over_issued: int = 0
    tickets_matched: int = 0
    amount_matched: float = 0.0
    margin_total: float = 0.0
    _statuses: list = field(default_factory=list, repr=False)


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


class SeriesMatchingService:

    @staticmethod
    async def run(
        db: AsyncSession,
        *,
        tenant_id: int,
        contract_id: int | None = None,
    ) -> RunSummary:
        """Recompute the issuance and margin rollups for a workspace's contracts.

        `contract_id` narrows the run to one contract; omit it for all of them. Does not
        commit — the caller does.
        """
        summary = RunSummary()

        query = (
            select(SeriesContract)
            .where(SeriesContract.tenant_id == tenant_id)
            .options(
                selectinload(SeriesContract.allocations)
                .selectinload(SeriesAllocation.bookings)
                .selectinload(SeriesBooking.passengers),
                selectinload(SeriesContract.fare_components),
            )
        )
        if contract_id is not None:
            query = query.where(SeriesContract.id == contract_id)
        contracts = (await db.execute(query)).scalars().unique().all()
        if not contracts:
            return summary

        # Every PNR this run could possibly care about, normalised once.
        wanted: dict[str, list[SeriesBooking]] = {}
        for contract in contracts:
            for allocation in contract.allocations:
                for booking in allocation.bookings:
                    key = norm_pnr(booking.pnr)
                    if key:
                        wanted.setdefault(key, []).append(booking)

        issued = await SeriesMatchingService._load_issued(db, tenant_id, list(wanted))
        now = datetime.utcnow()

        for contract in contracts:
            SeriesMatchingService._apply_contract(contract, issued, now, summary)

        summary.amount_matched = round(summary.amount_matched, 2)
        summary.margin_total = round(summary.margin_total, 2)
        for status in summary._statuses:
            setattr(summary, status, getattr(summary, status) + 1)
        return summary

    # ── Reading tickets ───────────────────────────────────────────────────────

    @staticmethod
    async def _load_issued(
        db: AsyncSession, tenant_id: int, pnrs: list[str]
    ) -> dict[str, dict[str, _Issued]]:
        """Tickets issued on any of these PNRs, indexed PNR → ticket number → figures.

        A ticket is filed under BOTH of its PNRs, because the two columns come from two
        different upload templates and an airline-format ticket can carry the airline PNR
        in one and the GDS PNR in the other. Filing it twice is safe: the inner dict is
        keyed by ticket number, so a ticket whose two PNRs are equal is not counted twice.
        """
        if not pnrs:
            return {}

        gds_norm = _norm_column(UploadedTicket.gds_pnr)
        air_norm = _norm_column(UploadedTicket.air_pnr)

        index: dict[str, dict[str, _Issued]] = {}
        row_counter = 0

        for chunk in _chunks(pnrs, PNR_CHUNK):
            rows = (await db.execute(
                select(
                    gds_norm.label("gds_norm"),
                    air_norm.label("air_norm"),
                    UploadedTicket.ticket_number,
                    UploadedTicket.total_amt,
                    UploadedTicket.pax_count,
                ).where(
                    UploadedTicket.tenant_id == tenant_id,
                    # ADM/ACM/RA rows are credit notes and refund applications against a
                    # ticket, not an issued ticket. Counting them would inflate the
                    # contract twice over — once for the ticket, once for its memo.
                    UploadedTicket.adm_acm_ra.is_(None),
                    # Seats on a group PNR are airline seats. A train booking from the
                    # Third Party API projection carries a 10-digit IRCTC PNR of its own;
                    # filtering here means a future writer that lets one reach gds_pnr
                    # cannot count berths as seats.
                    UploadedTicket.product_category == CATEGORY_AIR,
                    or_(gds_norm.in_(chunk), air_norm.in_(chunk)),
                )
            )).all()

            for gds_key, air_key, ticket_number, total_amt, pax_count in rows:
                keys = {k for k in (gds_key, air_key) if k}
                if not keys:
                    continue
                # A blank ticket number is still an issued seat, so it must count — but it
                # cannot dedupe by number. Key it by row position instead, or every
                # unnumbered ticket on the PNR would collapse into one.
                row_counter += 1
                number = (ticket_number or "").strip() or f"__row_{row_counter}__"
                # A ticket line can cover more than one passenger: the Third Party API
                # projection reads pax_count off the statement. Counting rows instead of
                # passengers understates any such contract — the bug the first version had.
                entry = _Issued(
                    pax=max(int(pax_count or 1), 1),
                    amount=Decimal(str(total_amt)) if total_amt is not None else ZERO,
                )
                for key in keys:
                    index.setdefault(key, {})[number] = entry

        return index

    # ── Writing rollups ───────────────────────────────────────────────────────

    @staticmethod
    def _apply_contract(contract: SeriesContract, issued, now: datetime, summary: RunSummary) -> None:
        """Cascade booking → allocation → contract for one contract."""
        components = list(contract.fare_components)
        # Contract-level components are the default; an allocation may override them.
        contract_level = [c for c in components if c.allocation_id is None]

        contract_tickets = 0
        contract_amount = ZERO
        contract_cost = ZERO
        seats_allocated = 0
        statuses: list[str] = []

        for allocation in contract.allocations:
            override = [c for c in components if c.allocation_id == allocation.id]
            per_pax = bases.fare_per_pax(override or contract_level)

            alloc_tickets = 0
            alloc_amount = ZERO
            booked = 0

            for booking in allocation.bookings:
                matched = issued.get(norm_pnr(booking.pnr) or "", {})
                numbers = sorted(n for n in matched if not n.startswith("__row_"))
                pax = sum(entry.pax for entry in matched.values())
                amount = sum((entry.amount for entry in matched.values()), ZERO)

                booking.tickets_issued = pax
                booking.ticket_numbers = numbers or None
                booking.amount_issued = amount
                booking.last_matched_at = now

                SeriesMatchingService._mark_passengers(booking, set(numbers))

                alloc_tickets += pax
                alloc_amount += amount
                booked += booking.seats or 0
                statuses.append(rollups.issuance_status(pax, booking.seats))
                summary.bookings += 1

            # Only passengers who take a seat and count toward the floor. Air India counts
            # a child as an adult here and a lap infant as nobody.
            counting = sum(
                1
                for booking in allocation.bookings
                for passenger in booking.passengers
                if passenger.counts_for_materialization
            )
            # With no roster keyed in, the ticket count is the best evidence of how many
            # people actually materialised — better than reporting zero.
            counting_pax = counting or alloc_tickets

            allocation.booked_pax = booked
            allocation.named_pax = sum(
                1
                for booking in allocation.bookings
                for passenger in booking.passengers
                if (passenger.name_status or "") in ("named", "confirmed")
            )
            allocation.ticketed_pax = alloc_tickets
            allocation.amount_issued = alloc_amount
            allocation.materialization_pct = rollups.materialization_pct(
                counting_pax, allocation.firmed_pax, allocation.requested_pax
            )

            seats = rollups.materialization_denominator(
                allocation.firmed_pax, allocation.requested_pax
            ) or 0
            seats_allocated += seats
            contract_cost += rollups.contract_cost(per_pax, seats)
            contract_tickets += alloc_tickets
            contract_amount += alloc_amount
            summary.allocations += 1

        contract.allocations_count = len(contract.allocations)
        contract.seats_allocated = seats_allocated
        contract.seats_ticketed = contract_tickets
        contract.amount_issued = rollups.money(contract_amount)
        contract.contract_cost = rollups.money(contract_cost)
        # penalty_amount is owned by the charges engine, which does not exist yet. Read it
        # rather than zeroing it, so this service never clobbers a figure it does not own.
        contract.margin = rollups.margin(
            contract_amount, contract_cost, contract.penalty_amount
        )
        contract.match_status = rollups.worst_status(statuses) or rollups.PENDING
        contract.last_matched_at = now

        summary.contracts += 1
        summary.tickets_matched += contract_tickets
        summary.amount_matched += float(contract_amount)
        summary.margin_total += float(contract.margin)
        summary._statuses.append(contract.match_status)

    @staticmethod
    def _mark_passengers(booking: SeriesBooking, numbers: set[str]) -> None:
        """Flag roster names whose ticket has turned up.

        Only passengers whose ticket number was entered by hand can be matched — nothing
        in a statement says which of sixty names a given document belongs to, and guessing
        by position would be wrong the first time a group is split. So this confirms what
        somebody already asserted rather than inventing the link.
        """
        if not numbers:
            return
        for passenger in booking.passengers:
            if passenger.ticket_number and passenger.ticket_number.strip() in numbers:
                passenger.ticket_status = "issued"
