"""The parts of a commission run that do not depend on WHICH statement it reads.

Extracted from `services/bsp_commission.py`, which keeps importing them — this is a move,
not a fork. The BSP engine's behaviour is unchanged and must stay so: it is the only
implementation that has ever run against real settlement data, and a regression there is a
wrong money figure on the product's flagship screen. New sources (third-party GDS/LCC, LCC
Detailed) reuse these pieces rather than growing near-copies of them.

What lives here is everything a row-level calculation needs once a row has been reduced to
"an airline, some dates, a fare, and what the document could not tell us":

  * `RowContext`   — the shape `apply_payout_rules` reads. BspRowContext and CalcRow both
                     satisfy it; neither imports the other.
  * `RowCalcResult`— the per-row outcome, including the seven statuses.
  * `apply_payout_rules` — the deal's payout inclusion/exclusion rules, and (just as
                     importantly) which of them could not be judged at all.
  * `needs_data_reason`  — the grouped, deliberately identical wording for a withheld row.
  * `is_stale`     — whether a run's worker has gone quiet.

NOT here: anything that reads a BSP table, the TGQ enrichment, the refund-lookup keys, or
the cumulative provider. Those are BSP's, and they stay BSP's.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.deal import (
    Deal as UnifiedDeal,
    DealIncentiveConfig,
    DealRule,
    build_rule_dict,
)
from app.services.deal_matching import SKIP_CLASS, SKIP_TRAVEL_DATE
from app.services.exclusion_evaluator import (
    evaluate_exclusion_for_payout_values,
    evaluate_inclusion_for_payout_values,
)

__all__ = [
    "SECTOR_RULE_FIELDS",
    "STALE_AFTER",
    "TRAVEL_RULE_FIELDS",
    "RowCalcResult",
    "RowContext",
    "apply_payout_rules",
    "is_stale",
    "needs_data_reason",
]


# A run heartbeats on every progress flush. Past this the worker is assumed dead and the
# user is offered "Release this run" rather than being left staring at a frozen bar.
STALE_AFTER = timedelta(minutes=5)


def is_stale(status: str | None, heartbeat_at: datetime | None) -> bool:
    """Is this run claiming to be alive while its worker has gone quiet?"""
    if status not in ("queued", "processing"):
        return False
    if heartbeat_at is None:
        return True
    return (datetime.utcnow() - heartbeat_at) > STALE_AFTER


@runtime_checkable
class RowContext(Protocol):
    """What a payout-rule pass needs from one statement row, whatever the source.

    Deliberately a Protocol rather than a base class: `BspRowContext` predates this and
    must not have to inherit from anything, and `CalcRow` is a plain dataclass in another
    module. Both satisfy this structurally.
    """
    airline_name: str | None
    issue_date: date | None
    travel_date: date | None
    booking_class: str | None
    sector: str | None
    tour_code: str | None

    @property
    def skip_rule_fields(self) -> set[str]: ...


@dataclass
class RowCalcResult:
    row_id: int
    # calculated | needs_data | excluded | reversed | skipped | unmatched | pending
    #
    # needs_data: a deal matched, but it restricts by a criterion this row does not carry,
    # so the figure could not be verified. `incentive` is None there — NOT 0. The
    # difference is "we could not confirm what you are owed" versus "you are owed nothing",
    # and only one of those is a number someone should act on.
    status: str
    incentive: float | None = None
    iata_commission: float = 0.0
    deal_id: int | None = None
    deal_type: str | None = None
    deal_name: str | None = None
    breakdown: dict[str, float] = field(default_factory=dict)
    reason: str | None = None


# Rule-condition fields that can only be answered from a SECTOR, and from a TRAVEL DATE.
# A BSP row prints neither, so a rule built on one of these is not evaluated at all —
# exclusion_evaluator self-skips a field it cannot resolve. Silently passing such a rule is
# how a row gets paid on terms nobody checked, so the caller is told which went unchecked.
SECTOR_RULE_FIELDS = {
    "continent", "originAirport", "destAirport", "originCountry", "destCountry",
    "domesticCountry", "city", "soto", "route", "sector",
}
TRAVEL_RULE_FIELDS = {"departure", "departureFrom", "departureTo", "travelDate"}


async def apply_payout_rules(
    db: AsyncSession,
    deal_id: int,
    breakdown: dict[str, float],
    ctx: RowContext,
) -> tuple[bool, bool, str | None, set[str]]:
    """Run the matched deal's payout inclusion/exclusion rules.

    Returns (blocked, had_inclusion_rule, reason, unconfirmed).

    `unconfirmed` names the criteria a rule DEPENDS ON that this row could not supply. A
    rule keyed on route cannot be judged against a settlement row with no sector; reporting
    that is the difference between "these terms were met" and "these terms were never
    looked at".

    NOTE: `find_all_deals` does NOT run these — payout rules have always been the caller's
    pass. Any new source runner must call this too, or its rows are paid on terms nobody
    checked.
    """
    res = await db.execute(
        select(UnifiedDeal)
        .options(
            selectinload(UnifiedDeal.incentives)
            .selectinload(DealIncentiveConfig.rules)
            .selectinload(DealRule.conditions)
        )
        .where(UnifiedDeal.id == deal_id)
    )
    deal = res.scalar_one_or_none()
    if deal is None:
        # Four values, matching every other return. This branch used to yield three, so a
        # deal deleted between the match and this pass raised ValueError inside the
        # per-row try/except and surfaced as "Calculation error" on an unmatched row.
        return False, False, None, set()

    issue_raw = ctx.issue_date.isoformat() if ctx.issue_date else None
    # ISO, never the bare '14MAY' — exclusion_evaluator parses with dayfirst=True, which is
    # inert on YYYY-MM-DD, and a year-less token would silently assume the current year.
    travel_raw = ctx.travel_date.isoformat() if ctx.travel_date else None
    skip_fields = ctx.skip_rule_fields
    had_inclusion = False
    unconfirmed: set[str] = set()

    for config in deal.incentives:
        if config.incentive_type not in breakdown:
            continue
        for rule in config.rules:
            rule_dict = build_rule_dict(rule.conditions)
            if not rule_dict:
                continue
            # Note what this rule needed and the row could not give it, BEFORE running it —
            # the evaluator answers "not blocked" either way.
            fields = set(rule_dict)
            if ctx.sector is None and (fields & SECTOR_RULE_FIELDS):
                unconfirmed.add("sector")
            if ctx.travel_date is None and (fields & TRAVEL_RULE_FIELDS):
                unconfirmed.add(SKIP_TRAVEL_DATE)
            if ctx.booking_class is None and "class" in fields:
                unconfirmed.add(SKIP_CLASS)

            if rule.rule_category == "payout_inclusion":
                had_inclusion = True
                ok, reason = await evaluate_inclusion_for_payout_values(
                    db, rule_dict,
                    sector=ctx.sector, booking_class=ctx.booking_class,
                    ticket_date_raw=issue_raw, departure_raw=travel_raw,
                    airline_name=ctx.airline_name, tour_code=ctx.tour_code,
                    skip_fields=skip_fields,
                )
                if not ok:
                    return True, had_inclusion, reason, unconfirmed
            elif rule.rule_category == "payout_exclusion":
                excluded, reason = await evaluate_exclusion_for_payout_values(
                    db, rule_dict,
                    sector=ctx.sector, booking_class=ctx.booking_class,
                    ticket_date_raw=issue_raw, departure_raw=travel_raw,
                    airline_name=ctx.airline_name, tour_code=ctx.tour_code,
                    skip_fields=skip_fields,
                )
                if excluded:
                    return True, had_inclusion, reason, unconfirmed
    return False, had_inclusion, None, unconfirmed


NEEDS_DATA_LABEL = {
    SKIP_CLASS: "cabin class",
    SKIP_TRAVEL_DATE: "travel date",
    "sector": "sector",
}


def needs_data_reason(deal_no: str, unconfirmed: list[str], remedy: str | None = None) -> str:
    """Say what is missing, why it matters, and what to do about it.

    DELIBERATELY IDENTICAL FOR EVERY ROW WITH THE SAME GAP. The "Unmatched & skipped" tab
    groups rows by (status, reason), so naming the ticket here — as an earlier version did —
    gave 9,021 rows 9,021 distinct reasons and turned one actionable bucket into 12,088
    groups and a 959 KB response. The tab already carries sample document numbers per
    bucket; that is where the specifics live.

    `remedy` is the only per-source part: a BSP row is fixed by uploading the TGQ HMPR, a
    third-party row by the consolidator printing the column at all.
    """
    missing = ", ".join(NEEDS_DATA_LABEL.get(c, c) for c in unconfirmed)
    tail = remedy or "Upload the TGQ HMPR covering this period and re-run."
    return (
        f"{missing.capitalize()} not known — deal {deal_no} pays only on specific "
        f"{missing}. {tail}"
    )[:500]
