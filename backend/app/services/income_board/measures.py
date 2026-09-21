"""The board's arithmetic, in one place, so no endpoint can invent its own.

THREE RULES, AND EVERY ENDPOINT GETS THEM BY CONSTRUCTION RATHER THAN BY REMEMBERING.

1. AN INCENTIVE SUM IS ALWAYS FILTERED BY STATUS. `incentive` is NULL when the status
   is `needs_data` — a deal matched but pays on something the document does not print,
   so nothing is claimed. Postgres's SUM ignores NULLs, so an unfiltered sum happens to
   give the right total today; it is filtered anyway, because the moment somebody adds
   `coalesce(incentive, 0)` to "fix the NULL" the unfiltered version silently starts
   counting unconfirmable rows as zero-earning ones. The filter makes the intent
   structural.

2. THE SIGN IS APPLIED HERE AND NOWHERE ELSE. Measures are stored exactly as the engine
   wrote them: the customer side's `incentive` is a commission we PAY but it is stored
   positive, so a drill-through row matches the ticket screen byte for byte. `direction`
   is a discriminator, never a multiplier. A stored `net_income` or `direction_sign`
   column would be applied twice by the first person who forgot it already had been.

3. REVENUE EXCLUDES MEMOS. An ADM or ACM has no fare. Letting memo value into a gross
   denominator corrupts every ratio on the board, invisibly — memos are legitimately
   `status='excluded'`, so they appear in neither the matched nor the needs-data count
   and nothing looks wrong.

`iata_commission` is never folded into an incentive total, here or anywhere else.
"""
from __future__ import annotations

from sqlalchemy import and_, func

from app.models.income_board import (
    DIRECTION_INBOUND, DIRECTION_OUTBOUND, MATCHED_STATUSES, REVENUE_TXN_CLASSES,
    IncomeBoardRow as R,
)


def _claimable(direction: str | None = None):
    """The rows whose `incentive` is a settled claim."""
    conds = [R.status.in_(MATCHED_STATUSES)]
    if direction is not None:
        conds.append(R.direction == direction)
    return and_(*conds)


def incentive_sum(direction: str | None = None):
    """SUM(incentive) over claimable rows only. See rule 1."""
    return func.sum(R.incentive).filter(_claimable(direction))


def iata_sum(direction: str | None = None):
    """SUM(iata_commission), kept apart from the incentive. See the module docstring."""
    return func.sum(R.iata_commission).filter(_claimable(direction))


def needs_data_count(direction: str | None = None):
    """How many rows could not be confirmed.

    Always rendered beside an incentive total. A figure without this count invites the
    reader to treat "could not confirm" as "nothing owed".
    """
    conds = [R.status == "needs_data"]
    if direction is not None:
        conds.append(R.direction == direction)
    return func.count().filter(and_(*conds))


def gross_revenue(direction: str | None = None):
    """SUM(gross_amount) over sales and refunds only — never memos. See rule 3."""
    conds = [R.txn_class.in_(REVENUE_TXN_CLASSES)]
    if direction is not None:
        conds.append(R.direction == direction)
    return func.sum(R.gross_amount).filter(and_(*conds))


def memo_exposure(txn_class: str):
    """SUM(gross_amount) for one memo class — ADM exposure is a number people act on."""
    return func.sum(R.gross_amount).filter(R.txn_class == txn_class)


def markup_sum():
    """Customer-side markup income. Phase 2; NULL-safe because the columns ship empty."""
    return func.sum(
        func.coalesce(R.markup_amount, 0) + func.coalesce(R.additional_markup_amount, 0)
    ).filter(R.direction == DIRECTION_OUTBOUND)


# ── The spread ────────────────────────────────────────────────────────────────

def vendor_income():
    """What the airlines and consolidators owe us."""
    return incentive_sum(DIRECTION_INBOUND)


def commission_paid():
    """What we owe our sub-agencies. Stored positive; subtracted below."""
    return incentive_sum(DIRECTION_OUTBOUND)


def spread_expr():
    """vendor income − commission paid + markup charged.

    THE THREE TERMS ARE NOT NEGOTIABLE. "Vendor income minus customer income" reads
    like a subtraction of two things, but the customer side is two different things
    with opposite signs: the outbound deal commission is a COST, and the markup on the
    invoice is INCOME. Dropping the markup term understates the spread; treating the
    outbound commission as income inverts it.

    coalesce at the outside only: each term is NULL when nothing qualified, and NULL
    here means "no rows", not "zero rupees" — but a spread of NULL is useless to a
    caller, so the arithmetic is made total at the last step.
    """
    return (
        func.coalesce(vendor_income(), 0)
        - func.coalesce(commission_paid(), 0)
        + func.coalesce(markup_sum(), 0)
    )
