"""Turning a contract's deadline rules into dates, and keeping the airline's arithmetic
visible when it disagrees with ours.

WHY TWO DATES PER DEADLINE. Air France's agreement states the rule and the answer in the
same sentence, twice:

    "The complete Passenger Name List must be sent to our Groups department no later than
     30 days before departure date, which is 27 November 2023."
    "All tickets must be paid in full and issued no later than 8 days before departure
     date, which is 19 December 2023."

Departure is 27 December 2023, so both check out. They do not always. A contract is typed
by a person under time pressure and dates get transposed, and when the rule and the printed
date disagree the airline enforces the one it printed. Recomputing silently would hide
that; refusing the stated date would be wrong. So the row keeps `computed_date` (ours),
`stated_date` (theirs), `effective_date` (what we act on — theirs when present), and a
flag saying they differed.

WHAT THIS FILE DOES NOT DO. It does not decide which deadlines a contract has. That is a
rule question, and rules land in a later phase; until then the specs come from the payment
schedule and from what the user entered. This file resolves specs to dates, and nothing
else — which is why it is pure and has no session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.models.series import (
    PAYMENT_ADVANCE_DEPOSIT, PAYMENT_BALANCE, PAYMENT_DEPOSIT, PAYMENT_FINAL,
)

ANCHOR_DEPARTURE = "DEPARTURE"
ANCHOR_CONTRACT_DATE = "CONTRACT_DATE"
ANCHOR_ADVANCE_DEPOSIT = "ADVANCE_DEPOSIT"

TYPE_ADVANCE_DEPOSIT = "ADVANCE_DEPOSIT"
TYPE_DEPOSIT = "DEPOSIT"
TYPE_NAME_LIST = "NAME_LIST"
TYPE_SEAT_RELEASE = "SEAT_RELEASE"
TYPE_FINAL_PAYMENT = "FINAL_PAYMENT"
TYPE_TICKETING = "TICKETING"
TYPE_NO_SHOW_CUTOFF = "NO_SHOW_CUTOFF"
TYPE_DEVIATION_CUTOFF = "DEVIATION_CUTOFF"
TYPE_DEPARTURE = "DEPARTURE"
TYPE_OPTION_EXPIRY = "OPTION_EXPIRY"
TYPE_PENALTY_STEP = "PENALTY_STEP"

# Types a contract can carry more than one of per departure. Air France's cancellation
# table has three band edges, so three PENALTY_STEP rows on the same departure are three
# different deadlines — the offset is what tells them apart.
_MULTI_PER_ALLOCATION = {TYPE_PENALTY_STEP}

# Which instalment kind raises which deadline. A balance payment is a FINAL_PAYMENT for
# deadline purposes because it is the one that gates ticketing, whatever it is called.
_DEADLINE_FOR_PAYMENT_KIND = {
    PAYMENT_ADVANCE_DEPOSIT: TYPE_ADVANCE_DEPOSIT,
    PAYMENT_DEPOSIT: TYPE_DEPOSIT,
    PAYMENT_BALANCE: TYPE_FINAL_PAYMENT,
    PAYMENT_FINAL: TYPE_FINAL_PAYMENT,
}

_ACTION_TEXT = {
    TYPE_ADVANCE_DEPOSIT: "Pay the advance deposit — the group size firms on this date.",
    TYPE_DEPOSIT: "Pay the deposit instalment.",
    TYPE_NAME_LIST: "Send the complete passenger name list.",
    TYPE_SEAT_RELEASE: "Release unsold seats before the free-release window closes.",
    TYPE_FINAL_PAYMENT: "Pay the balance in full.",
    TYPE_TICKETING: "Issue all tickets.",
    TYPE_NO_SHOW_CUTOFF: "Cancel any non-travelling passenger to avoid a no-show.",
    TYPE_DEVIATION_CUTOFF: "Last date to request a deviation or re-route.",
    TYPE_DEPARTURE: "Departure.",
    TYPE_OPTION_EXPIRY: "Accept the offer (sign and return it with the deposit) before it lapses.",
    TYPE_PENALTY_STEP: "Cancellation charge rises after this date.",
}


@dataclass(frozen=True)
class DeadlineSpec:
    """A deadline before it has been resolved to a date.

    Either an offset from an anchor, or a stated date, or both. Both is the normal case
    for a well-written contract and is what makes divergence detectable at all.
    """
    deadline_type: str
    anchor: str | None = None
    offset_days: int | None = None
    offset_hours: int | None = None
    stated_date: date | None = None
    action_required: str | None = None
    allocation_id: int | None = None


@dataclass(frozen=True)
class BuiltDeadline:
    """A resolved deadline, shaped for writing straight onto a `SeriesDeadline`."""
    deadline_type: str
    anchor: str | None
    offset_days: int | None
    offset_hours: int | None
    computed_date: date | None
    stated_date: date | None
    effective_date: date | None
    has_divergence: bool
    action_required: str | None
    allocation_id: int | None

    def as_columns(self) -> dict:
        return {
            "deadline_type": self.deadline_type,
            "anchor": self.anchor,
            "offset_days": self.offset_days,
            "offset_hours": self.offset_hours,
            "computed_date": self.computed_date,
            "stated_date": self.stated_date,
            "effective_date": self.effective_date,
            "has_divergence": self.has_divergence,
            "action_required": self.action_required,
            "allocation_id": self.allocation_id,
        }


def resolve_offset(anchor_date: date | None, offset_days: int | None,
                   offset_hours: int | None, anchor_at: datetime | None = None) -> date | None:
    """Apply an offset backwards from an anchor.

    Offsets count BACK: "D-30" is thirty days before, so a positive `offset_days` subtracts.
    That matches how every contract in hand writes it and how an agent says it out loud.

    An hours offset resolves against the anchor DATETIME when one is known — Air India's
    no-show cut-off is "at least D-24 hours before departure", and on an 08:30 departure
    that is 08:30 the previous day, not midnight. With only a date to work from, the hours
    are converted to whole days rounded UP, which errs toward acting early. The original
    hours are kept on the row either way, so a later simulator can still compute the exact
    instant.
    """
    if offset_hours:
        if anchor_at is not None:
            return (anchor_at - timedelta(hours=offset_hours)).date()
        if anchor_date is not None:
            whole_days = -(-offset_hours // 24)  # ceiling division
            return anchor_date - timedelta(days=whole_days)
        return None
    if offset_days is not None and anchor_date is not None:
        return anchor_date - timedelta(days=offset_days)
    return None


def build(spec: DeadlineSpec, *, departure_date: date | None = None,
          departure_at: datetime | None = None, contract_date: date | None = None,
          advance_deposit_date: date | None = None) -> BuiltDeadline:
    """Resolve one spec against the dates a contract knows.

    `effective_date` prefers the stated date. The airline enforces what it wrote, so when
    the two disagree ours is the one that loses — but it is kept beside it, and the flag
    makes the disagreement visible rather than letting the better-looking number win
    quietly.
    """
    anchor = (spec.anchor or "").upper() or None
    anchor_date = {
        ANCHOR_DEPARTURE: departure_date,
        ANCHOR_CONTRACT_DATE: contract_date,
        ANCHOR_ADVANCE_DEPOSIT: advance_deposit_date,
    }.get(anchor)
    anchor_at = departure_at if anchor == ANCHOR_DEPARTURE else None

    computed = resolve_offset(anchor_date, spec.offset_days, spec.offset_hours, anchor_at)
    stated = spec.stated_date

    effective = stated or computed
    diverges = bool(computed and stated and computed != stated)

    return BuiltDeadline(
        deadline_type=spec.deadline_type,
        anchor=anchor,
        offset_days=spec.offset_days,
        offset_hours=spec.offset_hours,
        computed_date=computed,
        stated_date=stated,
        effective_date=effective,
        has_divergence=diverges,
        action_required=spec.action_required or _ACTION_TEXT.get(spec.deadline_type),
        allocation_id=spec.allocation_id,
    )


def build_all(specs, *, departure_date: date | None = None,
              departure_at: datetime | None = None, contract_date: date | None = None,
              advance_deposit_date: date | None = None) -> list[BuiltDeadline]:
    """Resolve many specs, dropping any that resolve to no date at all.

    A deadline with neither a computed nor a stated date is not a deadline — it is a rule
    waiting for a departure date. Writing it as a row with a NULL date would put an
    undated item at the top of every sorted list.
    """
    built = [
        build(spec, departure_date=departure_date, departure_at=departure_at,
              contract_date=contract_date, advance_deposit_date=advance_deposit_date)
        for spec in specs
    ]
    return [b for b in built if b.effective_date is not None]


def specs_from_payment_schedule(rows) -> list[DeadlineSpec]:
    """A deadline for every instalment the contract owes.

    The due date on a schedule row IS the airline's stated date — Air France prints
    "38 760.00 INR required before 06 January 2023" and nothing derives that from the
    departure. So these carry a stated date and no offset, and can never diverge.

    Rows already settled are skipped: a paid deposit is not something anyone needs to be
    reminded about, and leaving it in would bury the live items.
    """
    specs: list[DeadlineSpec] = []
    for row in rows:
        if getattr(row, "due_date", None) is None:
            continue
        if (getattr(row, "status", None) or "") in ("paid", "waived"):
            continue
        kind = (getattr(row, "kind", None) or "").upper()
        specs.append(DeadlineSpec(
            deadline_type=_DEADLINE_FOR_PAYMENT_KIND.get(kind, TYPE_DEPOSIT),
            anchor=ANCHOR_CONTRACT_DATE,
            stated_date=row.due_date,
            allocation_id=getattr(row, "allocation_id", None),
        ))
    return specs


def departure_spec(allocation_id: int | None = None) -> DeadlineSpec:
    """Departure itself, as the last row on the timeline.

    Not a thing anyone must DO, but the timeline reads wrong without it — every other date
    is expressed relative to this one and a reader needs to see what they are counting back
    from.
    """
    return DeadlineSpec(
        deadline_type=TYPE_DEPARTURE,
        anchor=ANCHOR_DEPARTURE,
        offset_days=0,
        allocation_id=allocation_id,
    )


# Which fields identify "the same deadline" across a regeneration. Two rows of the same
# type on the same allocation are the same deadline even if the date moved — that is
# precisely the case where the old row must be updated rather than duplicated.
def identity(deadline_type: str | None, allocation_id: int | None,
             offset_days: int | None = None) -> tuple:
    kind = (deadline_type or "").upper()
    if kind in _MULTI_PER_ALLOCATION:
        return (kind, allocation_id, offset_days)
    return (kind, allocation_id)


def row_identity(row) -> tuple:
    """`identity` for anything with the three attributes — a stored row or a built one."""
    return identity(row.deadline_type, row.allocation_id, getattr(row, "offset_days", None))


def merge_preserving_overrides(built: list[BuiltDeadline], existing) -> tuple[list[BuiltDeadline], list]:
    """Reconcile freshly built deadlines against the rows already stored.

    Regeneration is wholesale — the whole set is rebuilt whenever the contract changes —
    so it has to be careful about two things a person may have done to a row by hand:

      * `stated_date`: if someone typed the date the airline actually gave, that is better
        information than any offset and it survives.
      * `met` / `waived`: a settled deadline stays settled. Recomputing it back to `open`
        would ask somebody to redo work they have already done.

    Returns (rows to write, rows to delete) — deletes being deadlines the contract no
    longer has, e.g. after an instalment was paid.
    """
    by_identity = {row_identity(d): d for d in existing}
    keep: set[tuple] = set()
    out: list[BuiltDeadline] = []

    for candidate in built:
        key = row_identity(candidate)
        keep.add(key)
        prior = by_identity.get(key)
        if prior is None:
            out.append(candidate)
            continue

        # A hand-entered stated date outranks a generated one.
        stated = prior.stated_date or candidate.stated_date
        computed = candidate.computed_date
        out.append(BuiltDeadline(
            deadline_type=candidate.deadline_type,
            anchor=candidate.anchor,
            offset_days=candidate.offset_days,
            offset_hours=candidate.offset_hours,
            computed_date=computed,
            stated_date=stated,
            effective_date=stated or computed,
            has_divergence=bool(computed and stated and computed != stated),
            action_required=candidate.action_required,
            allocation_id=candidate.allocation_id,
        ))

    # Anything settled is never swept, even if the contract stopped generating it: the
    # record that it WAS met is worth more than a tidy list.
    stale = [
        row for row in existing
        if row_identity(row) not in keep
        and (row.status or "open") == "open"
    ]
    return out, stale
