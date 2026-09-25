"""What a percentage in a group contract is a percentage OF.

This is the smallest file in the module and the one the rest of it turns on.

Two real contracts, two different answers. Air India writes its penalties against "AI
retention", and defines it in its own text: "only AI retention (Base +YQ) will freeze."
Air France writes its penalties against "the fare" — and its deposit arithmetic proves
which fare it means, because 38,760 and 193,800 are exactly 5% and 25% of 775,200, the
net-fare total, and not of the 1,095,072 grand total.

So "30% penalty" is not a number this system can store on its own. It is a number and a
base, and the two contracts do not share a base. A basis here is a named sum over typed
fare components, which makes both expressible without either one knowing the other exists.

Pure: no database, no session, no network. Every function takes component rows and returns
a Decimal, so the whole file is testable the way this repo tests things.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Protocol

from app.models.series import (
    COMPONENT_BASE, COMPONENT_CODES, COMPONENT_FEE, COMPONENT_OT,
    COMPONENT_TAX, COMPONENT_YQ, COMPONENT_YR_F, COMPONENT_YR_I,
)

ZERO = Decimal("0")


class ComponentLike(Protocol):
    """What a basis needs off a fare component. `SeriesFareComponent` satisfies it, and so
    does any stand-in a test builds — which is the point of typing it structurally rather
    than importing the model."""
    component_code: str
    amount_per_pax: object
    is_refundable_on_noshow: bool
    is_guaranteed_until_ticketing: bool


# The named sums. Adding a contract whose wording does not fit one of these means adding a
# row here and nothing else — the penalty engine reads this map, it does not hard-code any
# component name.
BASIS_NET_FARE = "NET_FARE"
BASIS_AI_RETENTION = "AI_RETENTION"
BASIS_FARE_PLUS_SURCHARGES = "FARE_PLUS_SURCHARGES"
BASIS_TOTAL = "TOTAL"
BASIS_TAX_ONLY = "TAX_ONLY"

BASIS_COMPONENTS: dict[str, tuple[str, ...]] = {
    # Air France: "Penalty of 5% of the fare." Its own deposits price off this.
    BASIS_NET_FARE: (COMPONENT_BASE,),
    # Air India: "AI retention (Base +YQ)". The one that freezes, and the one every AI
    # penalty above a flat grid is quoted against.
    BASIS_AI_RETENTION: (COMPONENT_BASE, COMPONENT_YQ),
    # Everything the airline guarantees, taxes excluded. Not used by either contract in
    # hand; here because "fare plus carrier-imposed charges" is a common third wording.
    BASIS_FARE_PLUS_SURCHARGES: (COMPONENT_BASE, COMPONENT_YQ, COMPONENT_YR_I, COMPONENT_YR_F),
    BASIS_TOTAL: COMPONENT_CODES,
    # Air India: "for 'No-Show' passengers – only statutory taxes are refundable", and the
    # same for cancelling a partly-flown ticket.
    BASIS_TAX_ONLY: (COMPONENT_TAX,),
}

BASES: tuple[str, ...] = tuple(BASIS_COMPONENTS)


def _amount(component: ComponentLike) -> Decimal:
    """A component's per-pax amount as a Decimal.

    Numeric columns arrive as Decimal, but a Pydantic payload or a test fixture may hand
    over a float or a string, and money must never be added as a float. Converting via
    `str` keeps 249.00 at 249.00 instead of 248.99999999999997.
    """
    value = getattr(component, "amount_per_pax", None)
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def basis_amount(components: Iterable[ComponentLike], basis: str) -> Decimal:
    """Per-passenger value of a named basis.

    An unknown basis returns zero rather than raising. A penalty of 30% of nothing is
    visibly wrong on screen and costs nobody money; a 500 in the middle of saving a
    contract loses the contract.
    """
    codes = BASIS_COMPONENTS.get((basis or "").upper())
    if not codes:
        return ZERO
    return sum((_amount(c) for c in components if c.component_code in codes), ZERO)


def fare_per_pax(components: Iterable[ComponentLike]) -> Decimal:
    """Everything the passenger pays — the figure that multiplies by seats to give cost."""
    return sum((_amount(c) for c in components), ZERO)


def refundable_on_noshow(components: Iterable[ComponentLike]) -> Decimal:
    """What comes back when a passenger simply does not travel.

    Reads the per-component flag rather than assuming the tax basis, because the two are
    not the same claim. `BASIS_TAX_ONLY` says "statutory taxes"; this says "whatever this
    contract marked refundable", and a contract that also refunds a fee is then right
    without a new basis.
    """
    return sum((_amount(c) for c in components if c.is_refundable_on_noshow), ZERO)


def guaranteed_total(components: Iterable[ComponentLike]) -> Decimal:
    """The part of the fare that is frozen until ticketing.

    Air France guarantees YR-F and YR-I/YQ; Air India freezes Base and YQ. Both say the
    taxes float. The difference between this and `fare_per_pax` is the agency's exposure
    to a tax movement between contract and ticketing.
    """
    return sum((_amount(c) for c in components if c.is_guaranteed_until_ticketing), ZERO)


def exposed_to_tax_movement(components: Iterable[ComponentLike]) -> Decimal:
    """The complement of `guaranteed_total` — what can still move under the agency."""
    return fare_per_pax(components) - guaranteed_total(components)


def split_by_code(components: Iterable[ComponentLike]) -> dict[str, Decimal]:
    """Per-pax amount keyed by component code.

    The codes are deliberately the vocabulary `uploaded_tickets` already stores
    (`sell_fare`, `sell_tax_yq`, `sale_yr`, `sell_tax`), so this dict lines up against a
    real ticket component by component. That is what turns "taxes are subject to change at
    date of ticketing" from a footnote into a number somebody can look at.
    """
    out: dict[str, Decimal] = {}
    for component in components:
        code = component.component_code
        if code:
            out[code] = out.get(code, ZERO) + _amount(component)
    return out


# Which ticket column answers which contract component. Used when comparing contracted
# terms against what the ticket actually went out at.
#
# The map is many-to-one on purpose: a ticket carries ONE `sale_yr`, while Air France
# splits YR into two contracted lines (YR-I/YQ and the Sustainable Fuel Contribution
# YR-F). So a comparison sums the contract side per ticket column, never the reverse.
# `OT` and `FEE` have no single counterpart — a consolidator spreads them over several
# columns — so they are absent rather than mapped to something merely close.
TICKET_COLUMN_FOR_COMPONENT: dict[str, str] = {
    COMPONENT_BASE: "sell_fare",
    COMPONENT_YQ: "sell_tax_yq",
    COMPONENT_YR_I: "sale_yr",
    COMPONENT_YR_F: "sale_yr",
    COMPONENT_TAX: "sell_tax",
}
