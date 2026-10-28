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
    rule_payload,
)
from app.services.deal_matching import SKIP_CLASS, SKIP_SEGMENT, SKIP_TRAVEL_DATE
from app.services.exclusion_evaluator import (
    MISSING_AIRPORT,
    MISSING_ISSUE_DATE,
    MISSING_SECTOR,
    MISSING_TOUR_CODE,
    RuleFacts,
    evaluate_rule,
    load_facts,
)

__all__ = [
    "SECTOR_RULE_FIELDS",
    "STALE_AFTER",
    "TRAVEL_RULE_FIELDS",
    "PayoutRuleOutcome",
    "RowCalcResult",
    "RowContext",
    "apply_payout_rules",
    "is_stale",
    "judge_payout_rules",
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


_PAYOUT_CATEGORIES = ("payout_inclusion", "payout_exclusion")


async def _payout_rules(db: AsyncSession, deal_id: int) -> list[tuple[str, bool, dict, bool]] | None:
    """[(incentive_type, is_inclusion, rule_dict, vice_versa)] for one deal's payout rules,
    or None when the deal is gone.

    Memoised per session: the runner now judges every candidate deal for every row, not just
    the winner, and a deal's rules do not change mid-run. Plain tuples only — never ORM rows,
    which the run's periodic commits would expire.
    """
    cache: dict[int, list | None] = db.info.setdefault("_payout_rule_cache", {})
    if deal_id in cache:
        return cache[deal_id]
    deal = (await db.execute(
        select(UnifiedDeal)
        .options(
            selectinload(UnifiedDeal.incentives)
            .selectinload(DealIncentiveConfig.rules)
            .selectinload(DealRule.conditions)
        )
        .where(UnifiedDeal.id == deal_id)
    )).scalar_one_or_none()
    rules = None if deal is None else [
        (config.incentive_type, rule.rule_category == "payout_inclusion",
         rule_payload(rule), bool(rule.vice_versa))
        for config in deal.incentives
        for rule in sorted(config.rules, key=lambda r: r.rule_order)
        if rule.rule_category in _PAYOUT_CATEGORIES
    ]
    cache[deal_id] = rules
    return rules


@dataclass
class PayoutRuleOutcome:
    """What a deal's payout rules did to one row, incentive by incentive.

    Rules belong to ONE incentive (deal_rules.incentive_id), so a PLB exclusion takes the
    PLB out and leaves a Super PLB that has no such rule standing. It used to zero the row.
    """
    kept: dict[str, float] = field(default_factory=dict)       # paid, after the rules
    blocked: dict[str, str] = field(default_factory=dict)      # incentive → why not
    # Criteria a rule needed and the row could not supply — on an incentive still standing.
    unconfirmed: set[str] = field(default_factory=set)
    had_inclusion: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str | None:
        return "; ".join(f"{t}: {r}" for t, r in self.blocked.items()) or None


async def judge_payout_rules(
    db: AsyncSession,
    deal_id: int,
    breakdown: dict[str, float],
    ctx: RowContext,
    facts: RuleFacts | None = None,
) -> PayoutRuleOutcome:
    """Run a deal's payout inclusion / exclusion rules against one row.

    Each incentive in `breakdown` is judged by its own rules (exclusion_evaluator):
      blocked     — outside its inclusion rule, or inside its exclusion rule → not paid
      undecided   — a rule needed what the row does not carry → still listed in `kept`, but
                    its missing criteria land in `unconfirmed` and the caller withholds
      otherwise   — paid.

    `facts` lets a caller judging several deals for one row resolve its route and cabin once.

    NOTE: `find_all_deals` does NOT run these — payout rules have always been the caller's
    pass. Any new source runner must call this too, or its rows are paid on terms nobody
    checked.
    """
    rules = await _payout_rules(db, deal_id)
    out = PayoutRuleOutcome()
    if rules is None:
        out.kept = dict(breakdown)
        return out

    for inc_type, amount in breakdown.items():
        missing: set[str] = set()
        for rule_inc, inclusion, rule_dict, vice_versa in rules:
            if rule_inc != inc_type or not rule_dict:
                continue
            if facts is None:
                facts = await load_facts(
                    db, sector=ctx.sector, booking_class=ctx.booking_class,
                    issue_date=ctx.issue_date, travel_date=ctx.travel_date,
                    airline_name=ctx.airline_name, tour_code=ctx.tour_code,
                    skip_fields=ctx.skip_rule_fields,
                    tour_code_known=getattr(ctx, "tour_code_known", True))
            verdict = evaluate_rule(rule_dict, facts, inclusion=inclusion, vice_versa=vice_versa)
            if verdict.empty:
                continue
            out.had_inclusion |= inclusion
            if verdict.blocks:
                out.blocked[inc_type] = verdict.reason()
                break
            if verdict.undecided:
                missing |= verdict.missing
        if inc_type in out.blocked:
            continue
        out.kept[inc_type] = amount
        out.unconfirmed |= missing

    if MISSING_AIRPORT in out.unconfirmed and facts is not None and facts.route is not None:
        out.notes.append(
            f"{', '.join(facts.route.missing)} not in the Airport Master — add "
            f"{'it' if len(facts.route.missing) == 1 else 'them'} under Platform admin → "
            f"Airport master so this deal's route rule can be checked.")
    return out


async def apply_payout_rules(
    db: AsyncSession,
    deal_id: int,
    breakdown: dict[str, float],
    ctx: RowContext,
) -> tuple[bool, bool, str | None, set[str]]:
    """BSP's whole-row contract over `judge_payout_rules`: (blocked, had_inclusion_rule,
    reason, unconfirmed), blocked when ANY incentive is. BSP prices a row against one deal
    and keeps or drops it whole; the third-party runner reads the per-incentive outcome."""
    out = await judge_payout_rules(db, deal_id, breakdown, ctx)
    return bool(out.blocked), out.had_inclusion, out.reason, out.unconfirmed


NEEDS_DATA_LABEL = {
    SKIP_CLASS: "cabin class",
    SKIP_TRAVEL_DATE: "travel date",
    SKIP_SEGMENT: "flight type",
    MISSING_SECTOR: "sector",
    MISSING_ISSUE_DATE: "issue date",
}


def needs_data_reason(deal_no: str, unconfirmed: list[str], remedy: str | None = None) -> str:
    """Say what is missing, why it matters, and what to do about it.

    DELIBERATELY IDENTICAL FOR EVERY ROW WITH THE SAME GAP. The "Unmatched & skipped" tab
    groups rows by (status, reason), so naming the ticket here — as an earlier version did —
    gave 9,021 rows 9,021 distinct reasons and turned one actionable bucket into 12,088
    groups and a 959 KB response. The tab already carries sample document numbers per
    bucket; that is where the specifics live (the row's notes name the airport codes).

    `remedy` is the only per-source part: a BSP row is fixed by uploading the TGQ HMPR, a
    third-party row by the consolidator printing the column at all. An airport missing from
    the Airport Master is not the document's gap, so it gets its own sentence and remedy.
    """
    parts: list[str] = []
    data = [c for c in unconfirmed if c not in (MISSING_AIRPORT, MISSING_TOUR_CODE)]
    if data:
        missing = ", ".join(NEEDS_DATA_LABEL.get(c, c) for c in data)
        tail = remedy or "Upload the TGQ HMPR covering this period and re-run."
        parts.append(f"{missing.capitalize()} not known — deal {deal_no} pays only on "
                     f"specific {missing}. {tail}")
    if MISSING_TOUR_CODE in unconfirmed:
        parts.append(f"Tour code not known — deal {deal_no} has a Tour Code or Corporate / "
                     f"Excursion / Tour fare-type rule, and this statement prints no tour "
                     f"code. Map its Tour Code column when uploading the statement (or the "
                     f"vendor's MO statement) and re-run.")
    if MISSING_AIRPORT in unconfirmed:
        parts.append(f"Deal {deal_no} has a route rule, and an airport on this sector is not "
                     f"in the Airport Master. Add it under Platform admin → Airport master "
                     f"and re-run.")
    return " ".join(parts)[:500]
