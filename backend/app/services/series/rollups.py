"""The arithmetic a block booking is judged by — materialization, margin, and the two
statuses this stack refuses to store.

Pure functions only: no session, no network, no clock of its own. Every function that
needs to know what day it is takes `today` as an argument, which is what makes the
deadline and payment rules testable at all — "overdue" is a question about a date, and a
function that reads the system clock cannot be asked it twice.

WHY `overdue` AND `missed` ARE NOT COLUMNS. There is no scheduler anywhere in this
codebase — no Celery beat, no cron, no APScheduler. A stored `overdue` flag would need
something to flip it on the morning it became true, and nothing would. The house already
decided this question elsewhere: `Tenant.has_active_plan` is evaluated live "so a lapsed
plan freezes on the next request without a cron job flipping the status." Deadlines follow
the same rule. Dates are stored because they are facts; lateness is computed on read
because it is a comparison.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.series import PAX_INF_LAP

ZERO = Decimal("0")
_CENTS = Decimal("0.01")
_PCT = Decimal("0.01")


def _dec(value) -> Decimal:
    """Money as Decimal, never float. None reads as zero."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value) -> Decimal:
    """Round to paise, half-up. Bankers' rounding is the Python default and is not what an
    invoice does."""
    return _dec(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


# ── Passenger classification ──────────────────────────────────────────────────

def seat_flags(pax_type: str | None) -> tuple[bool, bool]:
    """(occupies_seat, counts_for_materialization) for a passenger type.

    Air India spells out every case and they collapse to one distinction:

      "An infant occupying seat - is to be treated as a Child."
      "An infant without a seat - ticket will be similar to normal infant ticket."
      "One child would be counted as one adult to fulfil the minimum materialization."

    So a lap infant is the only type that neither takes a seat nor counts toward the 80%
    floor. Everything else does both — including a child, which is the clause people get
    wrong because a child pays a child fare almost everywhere else and does not here
    ("Child discount is not applicable– Adult group fare and conditions will apply").
    """
    is_lap_infant = (pax_type or "").upper() == PAX_INF_LAP
    return (not is_lap_infant, not is_lap_infant)


# ── Materialization ───────────────────────────────────────────────────────────

def materialization_denominator(firmed_pax: int | None, requested_pax: int | None) -> int | None:
    """The 100% a group is measured against.

    Air India: "The group size would be firmed up from the day of the advance deposit (in
    each of the respective departure date) and the same would be treated as sacrosanct viz
    100% of the group size."

    So once a deposit is paid the firmed size IS the denominator, and the originally
    requested size stops mattering. Before that there is no firmed size and the request is
    the best estimate available. Falling back rather than returning None keeps the figure
    useful on a contract that has not reached deposit yet.
    """
    if firmed_pax and firmed_pax > 0:
        return firmed_pax
    if requested_pax and requested_pax > 0:
        return requested_pax
    return None


def materialization_pct(counting_pax: int, firmed_pax: int | None, requested_pax: int | None) -> Decimal | None:
    """Percentage materialised, or None when there is no denominator.

    None rather than 0 is deliberate: a contract nobody has sized yet has an UNKNOWN
    materialization, and rendering that as 0% would light up every "below 80%" warning on
    a screen full of drafts.
    """
    denominator = materialization_denominator(firmed_pax, requested_pax)
    if not denominator:
        return None
    pct = (Decimal(counting_pax) / Decimal(denominator)) * Decimal(100)
    return pct.quantize(_PCT, rounding=ROUND_HALF_UP)


def meets_materialization(pct: Decimal | None, floor_pct: Decimal | int | None) -> bool | None:
    """Whether the floor is met. None when either side is unknown — an unmeasurable
    contract is not a failing one, and the caller must be able to tell the two apart."""
    if pct is None or floor_pct is None:
        return None
    return pct >= _dec(floor_pct)


def seats_needed_for_floor(firmed_pax: int | None, requested_pax: int | None,
                           floor_pct: Decimal | int | None) -> int | None:
    """How many seat-passengers the floor actually requires.

    Rounded UP, because 80% of 60 is 48 exactly but 80% of 59 is 47.2 and a group does not
    materialise on a fifth of a passenger. Air India's own text rounds seat counts off
    ("Number of seats released would be based on rounding off"); for a minimum, the only
    safe direction is up.
    """
    denominator = materialization_denominator(firmed_pax, requested_pax)
    if not denominator or floor_pct is None:
        return None
    needed = (_dec(floor_pct) / Decimal(100)) * Decimal(denominator)
    whole = int(needed)
    return whole if Decimal(whole) == needed else whole + 1


# ── Money ─────────────────────────────────────────────────────────────────────

def contract_cost(fare_per_pax, seats: int | None) -> Decimal:
    """The buy side: what the agency owes the airline for the space it took."""
    if not seats or seats <= 0:
        return ZERO
    return money(_dec(fare_per_pax) * Decimal(seats))


def margin(amount_issued, cost, penalties) -> Decimal:
    """Sell minus buy minus penalties.

    SIGN CONVENTION: positive means the sale earned money. This matches
    `sell_reconciliation` ("margin = sell - buy. Positive means the sale earned money")
    and is the OPPOSITE of `bsp_reconciliation`'s convention. Getting it backwards inverts
    every figure on the screen while still looking plausible, which is why it is stated
    here and asserted in the tests.
    """
    return money(_dec(amount_issued) - _dec(cost) - _dec(penalties))


# ── Statuses derived on read ──────────────────────────────────────────────────

def schedule_status(amount, paid_amount, current: str | None) -> str:
    """Where an instalment stands, from the money alone.

    `waived` is a decision a person made and is never recomputed away — that is the one
    state the arithmetic must not overrule.

    A schedule row with no amount yet stays `pending`: a percentage whose base has not been
    entered is not a paid instalment, and calling it `paid` because zero of zero is
    satisfied would mark an unfunded contract as settled.
    """
    if (current or "") == "waived":
        return "waived"
    due = _dec(amount)
    paid = _dec(paid_amount)
    if due <= ZERO:
        return "pending"
    if paid <= ZERO:
        return "pending"
    if paid >= due:
        return "paid"
    return "partial"


def schedule_paid_amount(payments) -> Decimal:
    """What has actually been sent against one instalment.

    A derived cache, recomputed wholesale from the payment rows rather than incremented,
    for the same reason the ticket rollup is: an increment that runs twice is wrong, and
    this one runs whenever a payment is added, edited or deleted.
    """
    return money(sum((_dec(getattr(p, "amount", None)) for p in payments), ZERO))


def is_overdue(due_date: date | None, today: date, status: str | None) -> bool:
    """Past its date and still owed.

    Derived, never stored — see the module docstring. A paid or waived row is never
    overdue however old it is.
    """
    if due_date is None:
        return False
    if (status or "") in ("paid", "waived"):
        return False
    return due_date < today


def days_until(target: date | None, today: date) -> int | None:
    """Signed days to a date: positive is future, negative is past, 0 is today."""
    if target is None:
        return None
    return (target - today).days


def deadline_urgency(effective_date: date | None, today: date, status: str | None) -> str:
    """A bucket for the action centre.

    `settled` covers both met and waived, because neither needs anybody to do anything and
    keeping them apart here would only push the distinction into every caller.
    """
    if (status or "") in ("met", "waived"):
        return "settled"
    remaining = days_until(effective_date, today)
    if remaining is None:
        return "undated"
    if remaining < 0:
        return "overdue"
    if remaining == 0:
        return "today"
    if remaining <= 3:
        return "critical"
    if remaining <= 14:
        return "soon"
    return "scheduled"


# ── Issuance status ───────────────────────────────────────────────────────────

# Kept from the first version of this feature, vocabulary unchanged, because the screen and
# its colour map already speak it.
PENDING = "pending"
PARTIAL = "partial"
COMPLETE = "complete"
OVER_ISSUED = "over_issued"


def issuance_status(tickets_issued: int, seats: int | None) -> str:
    """Where issuance stands against the space taken.

    `over_issued` is not a rounding artefact to be hidden — more tickets than seats means
    either a PNR is filed under the wrong contract or the airline let the group grow, and
    both need a human.
    """
    if tickets_issued == 0:
        return PENDING
    if not seats or seats <= 0:
        return PARTIAL
    if tickets_issued < seats:
        return PARTIAL
    if tickets_issued == seats:
        return COMPLETE
    return OVER_ISSUED


def worst_status(statuses) -> str | None:
    """The status a parent should show given its children's.

    Ordered by how much attention it wants, not alphabetically: anything over-issued
    outranks anything else, and a single unstarted booking keeps the contract off
    `complete`.
    """
    order = (OVER_ISSUED, PENDING, PARTIAL, COMPLETE)
    present = {s for s in statuses if s}
    if not present:
        return None
    for candidate in order:
        if candidate in present:
            # `pending` only wins outright when nothing has issued at all; a mix of
            # pending and issued bookings is a partly-issued contract.
            if candidate is PENDING and present - {PENDING}:
                return PARTIAL
            return candidate
    return None
