"""What backing out of a group costs, today and on the day it gets worse.

The terms rows (models/series.py::SeriesTerm) are data; this file reads them. Two
questions, both asked per departure:

  * EXPOSURE — "if we cancelled the whole group today, what would it cost?" Air France,
    110 days out on 12 seats: the 120–101 band applies, 15% of the net fare, so
    15% × 64,600 × 12 = 116,280. That is the number an agency needs in front of it when a
    departure is selling badly, and the contract PDF makes it work it out by hand.

  * THE NEXT STEP — "until when does today's price hold?" The band ends 101 days out; from
    D-100 the same cancellation costs 30%. That date is a deadline in every sense that
    matters, so `penalty_step_specs` turns each band edge into one (type PENALTY_STEP) and
    the reminder machinery treats it like a name-list date.

Only whole-group cancellation (scope GROUP, or no scope) is priced here. A partial
release has a quota (Air India's free 20%) and prices per seat beyond it — its cost
depends on how many seats, which is a question for a what-if, not a standing figure.

Pure: no session. Takes term and fare-component rows, returns Decimals and dataclasses.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from app.services.series import bases
from app.services.series.rollups import money

ZERO = Decimal("0")

# Charge types a whole-group cancellation can be priced from. The rest (FARE_DIFFERENCE,
# NOT_PERMITTED) have no number, and pretending otherwise would put a confident zero on
# the screen.
_PRICEABLE = {
    "FREE", "PCT_OF_BASIS", "FIXED_PER_PAX", "FIXED_TOTAL", "DEPOSIT_FORFEIT",
    "NON_REFUNDABLE", "TAXES_ONLY_REFUNDABLE",
}

_BASIS_WORDS = {
    "NET_FARE": "net fare",
    "AI_RETENTION": "airline retention (base + YQ)",
    "FARE_PLUS_SURCHARGES": "fare + surcharges",
    "TOTAL": "total fare",
    "TAX_ONLY": "statutory taxes",
}

_RULE_WORDS = {
    "CANCELLATION": "Cancellation",
    "SEAT_RELEASE": "Seat release",
    "NAME_CHANGE": "Name change",
    "DEVIATION": "Deviation",
    "REISSUE": "Reissue",
    "NO_SHOW": "No-show",
    "REFUND": "Refund",
    "MATERIALIZATION": "Below materialisation",
}


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _upper(value) -> str:
    return (value or "").upper()


def _plain(value: Decimal) -> str:
    """30.00 -> "30", 12.50 -> "12.5". `normalize()` alone prints 30 as 3E+1."""
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def covers(term, days_before: int | None) -> bool:
    """Does this term's window include `days_before`? Both edges inclusive, open when NULL.

    A term with no window at all covers every day — Air India's "in case of group
    cancellation before ticketing, advance deposit will be forfeited" has none.
    """
    if days_before is None:
        return term.days_before_max is None and term.days_before_min is None
    upper = term.days_before_max
    lower = term.days_before_min
    if upper is not None and days_before > upper:
        return False
    if lower is not None and days_before < lower:
        return False
    return True


def _cabin_matches(term, cabin: str | None) -> bool:
    return not term.cabin or not cabin or _upper(term.cabin) == _upper(cabin)


def _is_group_cancellation(term) -> bool:
    return (_upper(term.rule_type) == "CANCELLATION"
            and _upper(term.scope) in ("", "GROUP"))


def _phase_applies(term, ticketed: bool) -> bool:
    phase = _upper(term.phase) or "ANY"
    if ticketed:
        return phase in ("ANY", "AFTER_TICKETING")
    return phase != "AFTER_TICKETING"


def charge_per_pax(term, components, *, seats: int, deposit_paid=ZERO) -> Decimal | None:
    """What one seat costs under `term`, or None when the term has no price.

    DEPOSIT_FORFEIT spreads the deposit actually paid over the seats: a forfeited deposit
    is money already gone, so an unpaid deposit forfeits nothing.
    """
    kind = _upper(term.charge_type)
    value = _dec(term.charge_value)
    components = list(components)
    if kind == "FREE":
        return ZERO
    if kind == "PCT_OF_BASIS":
        if value is None:
            return None
        base = bases.basis_amount(components, term.charge_basis or bases.BASIS_TOTAL)
        return money(base * value / Decimal(100))
    if kind == "FIXED_PER_PAX":
        return value
    if kind == "FIXED_TOTAL":
        if value is None or seats <= 0:
            return None
        return money(value / Decimal(seats))
    if kind == "DEPOSIT_FORFEIT":
        if seats <= 0:
            return None
        return money(_dec(deposit_paid) / Decimal(seats))
    if kind == "NON_REFUNDABLE":
        return bases.fare_per_pax(components)
    if kind == "TAXES_ONLY_REFUNDABLE":
        return bases.fare_per_pax(components) - bases.basis_amount(components, bases.BASIS_TAX_ONLY)
    return None


def describe(term) -> str:
    """One plain line for a term, for when the contract's own wording is not to hand."""
    if getattr(term, "description", None):
        return term.description
    kind = _upper(term.charge_type)
    value = _dec(term.charge_value)
    head = _RULE_WORDS.get(_upper(term.rule_type), (term.rule_type or "Term").title())
    if _upper(term.scope) == "PARTIAL":
        head = f"Partial {head.lower()}"

    window = ""
    upper, lower = term.days_before_max, term.days_before_min
    if upper is not None and lower is not None:
        window = f"{upper}–{lower} days before departure"
    elif upper is not None:
        window = f"within {upper} days of departure"
    elif lower is not None:
        window = f"{lower}+ days before departure"

    share = ""
    if term.share_max_pct is not None or term.share_min_pct is not None:
        lo = _dec(term.share_min_pct) or ZERO
        hi = _dec(term.share_max_pct)
        share = f"up to {_plain(hi)}% of seats" if lo == 0 and hi is not None else (
            f"{_plain(lo)}–{_plain(hi)}% of seats" if hi is not None else f"beyond {_plain(lo)}% of seats"
        )

    if kind == "FREE":
        price = "free"
    elif kind == "PCT_OF_BASIS" and value is not None:
        price = f"{_plain(value)}% of {_BASIS_WORDS.get(_upper(term.charge_basis), 'the fare')}"
    elif kind == "FIXED_PER_PAX" and value is not None:
        price = f"{value:,.0f} per passenger"
    elif kind == "FIXED_TOTAL" and value is not None:
        price = f"{value:,.0f} in total"
    else:
        price = {
            "DEPOSIT_FORFEIT": "deposit forfeited",
            "NON_REFUNDABLE": "non-refundable",
            "TAXES_ONLY_REFUNDABLE": "only statutory taxes refunded",
            "FARE_DIFFERENCE": "repriced at the airline's discretion",
            "NOT_PERMITTED": "not permitted",
        }.get(kind, kind.lower().replace("_", " "))

    parts = [p for p in (window, share) if p]
    tail = f" ({', '.join(parts)})" if parts else ""
    cabin = f" [{term.cabin.title()}]" if getattr(term, "cabin", None) else ""
    gst = " + GST" if getattr(term, "plus_gst", False) else ""
    return f"{head}{cabin}{tail}: {price}{gst}"


@dataclass(frozen=True)
class Exposure:
    """What cancelling a whole departure would cost today, and until when."""
    days_before: int | None
    description: str | None
    per_pax: Decimal | None
    seats: int
    amount: Decimal | None
    plus_gst: bool
    # The last day today's price holds, and what it becomes the day after.
    holds_until: date | None
    next_description: str | None
    next_per_pax: Decimal | None


def _group_bands(terms, *, ticketed: bool, cabin: str | None) -> list:
    """Candidate group-cancellation terms, the most specific first.

    Once seats are ticketed an after-ticketing rule outranks a date band that also covers
    the day: Air France's "from 30 days: 100% of the fare" and "after ticket issue: non
    refundable" both match D-5, and a ticketed seat is governed by the second.
    """
    bands = [
        t for t in terms
        if _is_group_cancellation(t) and _phase_applies(t, ticketed) and _cabin_matches(t, cabin)
        and _upper(t.charge_type) in _PRICEABLE
    ]
    if ticketed:
        bands.sort(key=lambda t: 0 if _upper(t.phase) == "AFTER_TICKETING" else 1)
    return bands


def cancellation_exposure(terms: Iterable, components: Iterable, *, departure_date: date | None,
                          today: date, seats: int, cabin: str | None = None,
                          ticketed: bool = False, deposit_paid=ZERO) -> Exposure | None:
    """Price a whole-group cancellation of one departure, as of `today`.

    Returns None when the contract has no priceable group-cancellation term at all — an
    unknown is shown as unknown, never as a zero.
    """
    components = list(components)
    days_before = (departure_date - today).days if departure_date else None
    bands = _group_bands(list(terms), ticketed=ticketed, cabin=cabin)
    if not bands:
        return None

    current = next((t for t in bands if covers(t, days_before)), None)
    if current is None:
        return Exposure(days_before, None, None, seats, None, False, None, None, None)

    per_pax = charge_per_pax(current, components, seats=seats, deposit_paid=deposit_paid)
    amount = money(per_pax * Decimal(seats)) if per_pax is not None else None

    holds_until = next_desc = next_per_pax = None
    if departure_date is not None and current.days_before_min not in (None, 0):
        holds_until = departure_date - timedelta(days=current.days_before_min)
        following = next((t for t in bands if covers(t, current.days_before_min - 1)), None)
        if following is not None:
            next_desc = describe(following)
            next_per_pax = charge_per_pax(following, components, seats=seats, deposit_paid=deposit_paid)

    return Exposure(
        days_before=days_before,
        description=describe(current),
        per_pax=per_pax,
        seats=seats,
        amount=amount,
        plus_gst=bool(getattr(current, "plus_gst", False)),
        holds_until=holds_until,
        next_description=next_desc,
        next_per_pax=next_per_pax,
    )


@dataclass(frozen=True)
class StepSpec:
    """One band edge, to be turned into a PENALTY_STEP deadline."""
    offset_days: int
    action_required: str
    allocation_id: int | None


def penalty_step_specs(terms: Iterable, *, cabin: str | None = None) -> list[StepSpec]:
    """A deadline on the last day of every group-cancellation band that is followed by a
    dearer one.

    Air France's four bands give three steps: D-121 (5% → 15%), D-101 (15% → 30%) and
    D-31 (30% → 100%). A band followed by a cheaper or equal one raises nothing — there is
    nothing to beat.
    """
    bands = _group_bands(list(terms), ticketed=False, cabin=cabin)
    steps: list[StepSpec] = []
    seen: set[tuple[int, int | None]] = set()
    for band in bands:
        edge = band.days_before_min
        if not edge:
            continue
        following = next((t for t in bands if covers(t, edge - 1)), None)
        if following is None or not _dearer(following, band):
            continue
        key = (edge, getattr(band, "allocation_id", None))
        if key in seen:
            continue
        seen.add(key)
        steps.append(StepSpec(
            offset_days=edge,
            action_required=(
                f"Last day at today's cancellation charge — {describe(band)}. "
                f"From tomorrow: {describe(following)}."
            )[:200],
            allocation_id=getattr(band, "allocation_id", None),
        ))
    steps.sort(key=lambda s: -s.offset_days)
    return steps


_SEVERITY_ORDER = {
    "FREE": 0, "FIXED_PER_PAX": 1, "FIXED_TOTAL": 1, "PCT_OF_BASIS": 1,
    "DEPOSIT_FORFEIT": 1, "TAXES_ONLY_REFUNDABLE": 2, "NON_REFUNDABLE": 3,
}


def _dearer(after, before) -> bool:
    """Is `after` a worse deal than `before`? Same charge type compares by value; different
    types compare by how much of the fare they can take."""
    a, b = _upper(after.charge_type), _upper(before.charge_type)
    if a == b:
        va, vb = _dec(after.charge_value), _dec(before.charge_value)
        if a in ("PCT_OF_BASIS", "FIXED_PER_PAX", "FIXED_TOTAL"):
            if va is None or vb is None:
                return False
            if a == "PCT_OF_BASIS" and _upper(after.charge_basis) != _upper(before.charge_basis):
                return True
            return va > vb
        return False
    return _SEVERITY_ORDER.get(a, 1) > _SEVERITY_ORDER.get(b, 1) or (
        _SEVERITY_ORDER.get(a, 1) == _SEVERITY_ORDER.get(b, 1)
    )
