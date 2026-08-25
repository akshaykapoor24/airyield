"""An agency's running account: balance, billing cycles, and the type-switch guard.

The rule this file exists to enforce:

    A type switch is only legal at a cycle boundary with a settled, zero balance.

Which holds in BOTH directions, because "settle" simply points opposite ways:

    cash -> credit   balance is POSITIVE (unused deposit). We owe him, so it is
                     cleared by a refund (money out) or an adjustment (written
                     back), whichever he asks for.
    credit -> cash   balance is NEGATIVE (outstanding). He owes us, so it is
                     cleared by a receipt. There is nothing to refund or adjust —
                     on credit he pays after the fact, so the money must arrive.

The consequence is worth stating plainly: every terms period opens at zero and
closes at zero, so no ledger period straddles a type change and no entry is ever
ambiguous about which arrangement it belongs to.

Cycles are computed here rather than stored. A cycle is billed when a `billings`
row overlaps it; storing that separately would only create something to drift.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agency import Agency
from app.models.agency_ledger import AgencyLedger
from app.models.agency_terms import AgencyTerms
from app.models.billing import Billing
from app.models.ticket_statement import TicketStatement
from app.models.uploaded_ticket import UploadedTicket
from app.models.user import User

ZERO = Decimal("0.00")

# GST rounding can strand a few paise on an otherwise settled account. Blocking a
# switch over ₹0.50 forever is worse than writing it off, so anything inside this
# is settled and gets a rounding adjustment posted for it.
SETTLE_TOLERANCE = Decimal("1.00")

CYCLE_DAYS = {"weekly": 7, "fortnightly": 14}   # monthly is calendar-based


def _add_month(d: date) -> date:
    """One calendar month on, clamped to the last valid day (31 Jan -> 28 Feb)."""
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    day = d.day
    while day > 1:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)


def cycle_end(start: date, billing_cycle: str) -> date:
    """Exclusive end of the cycle beginning at `start`."""
    days = CYCLE_DAYS.get((billing_cycle or "").lower())
    return start + timedelta(days=days) if days else _add_month(start)


def cycle_windows(terms: AgencyTerms, until: date) -> list[dict]:
    """Every cycle of this terms period that has started on or before `until`.

    Capped at 500 windows so a stale anchor date can never spin here.
    """
    out: list[dict] = []
    start = terms.cycle_anchor_date
    stop = min(until, terms.effective_to) if terms.effective_to else until
    seq = 1
    while start <= stop and seq <= 500:
        end = cycle_end(start, terms.billing_cycle)
        out.append({"seq": seq, "period_from": start, "period_to": end - timedelta(days=1), "elapsed": end <= until})
        start = end
        seq += 1
    return out


async def current_terms(db: AsyncSession, agency_id: int, channel: str) -> Optional[AgencyTerms]:
    """The arrangement in force on this channel.

    `channel` is required, never defaulted. An agency that is cash on GDS and
    credit on LCC has two open periods, and a function that guessed between them
    would return the wrong limit and the wrong balance to whoever asked. The
    endpoints resolve a default for single-channel agencies; this layer does not.
    `uq_agency_terms_current` makes .first() provably a single row — the order_by
    stays as belt-and-braces.
    """
    res = await db.execute(
        select(AgencyTerms)
        .where(
            AgencyTerms.agency_id == agency_id,
            AgencyTerms.channel == channel,
            AgencyTerms.effective_to.is_(None),
        )
        .order_by(AgencyTerms.effective_from.desc())
    )
    return res.scalars().first()


async def open_terms(db: AsyncSession, agency_id: int) -> list[AgencyTerms]:
    """Every channel's current arrangement, for the screens that show them side by side."""
    res = await db.execute(
        select(AgencyTerms)
        .where(AgencyTerms.agency_id == agency_id, AgencyTerms.effective_to.is_(None))
        .order_by(AgencyTerms.channel)
    )
    return list(res.scalars().all())


async def balance(db: AsyncSession, agency_id: int, channel: str, terms_id: int | None = None) -> Decimal:
    """SUM(amount) on one channel — positive means the agency holds credit with us."""
    q = select(func.coalesce(func.sum(AgencyLedger.amount), 0)).where(
        AgencyLedger.agency_id == agency_id,
        AgencyLedger.channel == channel,
    )
    if terms_id is not None:
        q = q.where(AgencyLedger.terms_id == terms_id)
    return Decimal(str((await db.execute(q)).scalar() or 0))


async def _sum_where(db: AsyncSession, agency_id: int, channel: str, terms_id: int | None, positive: bool) -> Decimal:
    q = select(func.coalesce(func.sum(AgencyLedger.amount), 0)).where(
        AgencyLedger.agency_id == agency_id,
        AgencyLedger.channel == channel,
    )
    q = q.where(AgencyLedger.amount > 0) if positive else q.where(AgencyLedger.amount < 0)
    if terms_id is not None:
        q = q.where(AgencyLedger.terms_id == terms_id)
    return Decimal(str((await db.execute(q)).scalar() or 0))


async def agency_statement_scope(db: AsyncSession, agency: Agency, current_user: User):
    """How to find this agency's ticket statements, and what we had to leave out.

    Returns (clause, unattributable_count). The clause always matches statements
    explicitly tagged with this agency's id; it additionally matches untagged
    statements naming this vendor only when the name is unambiguous. The count is
    how many untagged statements had to be excluded, so a screen can say why some
    tickets are missing instead of leaving the user to wonder.

    Statements carry `agency_id` when the upload picker sent one, and only a bare
    vendor NAME otherwise. Since a vendor is onboarded once per branch, that name
    can match several agencies — and the first one to bill would take the others'
    tickets, because `uploaded_tickets.billing_id` is a single FK and does not
    come back. So the name fallback applies ONLY when the name resolves to exactly
    one agency for this user. Refusing to bill an ambiguous statement is the
    correct failure; silently billing someone else's tickets is not.
    """
    name = (agency.name or "").strip().lower()
    if not name:
        return TicketStatement.agency_id == agency.id, 0

    siblings = (await db.execute(
        select(func.count()).select_from(Agency).where(
            Agency.user_id == current_user.id,
            func.lower(func.trim(Agency.name)) == name,
        )
    )).scalar() or 0

    if siblings > 1:
        # Untagged statements naming this vendor cannot be attributed to a branch.
        untagged = (await db.execute(
            select(func.count()).select_from(TicketStatement).where(
                TicketStatement.tenant_id == current_user.tenant_id,
                func.lower(func.trim(TicketStatement.agency)) == name,
                TicketStatement.agency_id.is_(None),
                # Same guard as the clause below: a corporate or direct-customer
                # statement that happens to share this vendor's name is not an
                # unattributed agency statement, so counting it would report a
                # problem the user cannot act on.
                or_(
                    TicketStatement.customer_type.is_(None),
                    TicketStatement.customer_type == "agency",
                ),
            )
        )).scalar() or 0
        return TicketStatement.agency_id == agency.id, untagged

    return or_(
        TicketStatement.agency_id == agency.id,
        and_(
            TicketStatement.agency_id.is_(None),
            func.lower(func.trim(TicketStatement.agency)) == name,
            # `agency` holds the counterparty's DISPLAY NAME whatever the customer
            # type, so a corporate or a walk-in customer can now sit in that column.
            # Without this an agency of the same name would claim their tickets —
            # and uploaded_tickets.billing_id is a single FK that does not come
            # back. NULL still matches: those rows predate customer tagging and
            # were all filed against agencies.
            or_(
                TicketStatement.customer_type.is_(None),
                TicketStatement.customer_type == "agency",
            ),
        ),
    ), 0


async def unbilled_exposure(db: AsyncSession, agency: Agency, current_user: User) -> Decimal:
    """Value of this agency's tickets that no billing has claimed yet.

    Deliberately NOT in the ledger — no money has moved and no invoice exists.
    But for a cash agency it is the difference between warning him now and
    warning him a week late, so the account summary reports it alongside.

    AGENCY-WIDE, NEVER PER CHANNEL, and that is a data limitation rather than a
    choice. Nothing on a ticket records GDS vs LCC: UploadedTicket has no channel
    column and TicketStatement.statement_type is B2B|AIRLINE, a different axis.
    Splitting this figure would mean inventing the split, so both channels report
    the same number and the screens label it as agency-wide. The consequence is
    that switch_blockers can refuse a legal GDS switch because of an unbilled LCC
    ticket — over-strict, but safe in the only direction that matters.
    """
    clause, _ambiguous = await agency_statement_scope(db, agency, current_user)
    q = (
        select(func.coalesce(func.sum(UploadedTicket.total_amt), 0))
        .join(TicketStatement, UploadedTicket.batch_id == TicketStatement.batch_id)
        .where(
            UploadedTicket.tenant_id == current_user.tenant_id,
            UploadedTicket.created_by_id == current_user.id,
            clause,
            UploadedTicket.is_billed.is_(False),
        )
    )
    return Decimal(str((await db.execute(q)).scalar() or 0))


async def cycles_with_status(db: AsyncSession, agency_id: int, terms: AgencyTerms, today: date) -> list[dict]:
    """Cycle windows annotated with the billing that covers them, if any.

    Filtered to this terms row's channel — without that, one LCC invoice would
    mark the overlapping GDS cycle "billed" as well, and a whole cycle's worth of
    GDS tickets would look settled when nothing had been raised for them.
    """
    rows = (await db.execute(
        select(Billing)
        .where(Billing.agency_id == agency_id, Billing.channel == terms.channel)
        .order_by(Billing.period_from)
    )).scalars().all()
    out = []
    for w in cycle_windows(terms, today):
        hit = next(
            (b for b in rows
             if b.period_from and b.period_to
             and b.period_from <= w["period_to"] and b.period_to >= w["period_from"]),
            None,
        )
        out.append({
            **w,
            "billing_id": hit.id if hit else None,
            "billing_name": hit.billing_name if hit else None,
            "billed_amount": float(hit.grand_total or 0) if hit else None,
            "status": "billed" if hit else ("unbilled" if w["elapsed"] else "open"),
        })
    return out


def settlement_plan(agency_type: str, bal: Decimal) -> Optional[dict]:
    """What has to happen to bring `bal` to zero, given the arrangement.

    Returns None when the account is already settled within tolerance.
    """
    if abs(bal) <= SETTLE_TOLERANCE:
        return None
    if bal > 0:
        # We hold his money. Only a cash agency can be in this position, and he
        # chooses whether it comes back or is written off.
        return {
            "direction": "outgoing",
            "amount": float(bal),
            "options": ["refund", "adjustment"],
            "message": f"₹{bal:,.2f} of unused deposit is left — refund it or adjust it off before switching.",
        }
    return {
        "direction": "incoming",
        "amount": float(-bal),
        "options": ["receipt"],
        "message": f"₹{-bal:,.2f} is outstanding — collect it and record the receipt before switching.",
    }


async def switch_blockers(
    db: AsyncSession, agency: Agency, terms: Optional[AgencyTerms], current_user: User,
    today: date, channel: str,
) -> list[dict]:
    """Everything standing between this agency and a type switch ON ONE CHANNEL.

    A list, not a boolean — "cannot switch" is useless to the person who has to
    unblock it. Each entry names the amount or the period at fault so the screen
    can render an action beside it.

    Cycle and balance are channel-scoped; unbilled exposure is not, because no
    ticket records a channel (see unbilled_exposure). That makes the guard
    over-strict — an unbilled LCC ticket blocks a GDS switch — which is the safe
    direction: it can refuse a legal switch, never permit an illegal one.
    """
    blockers: list[dict] = []
    if terms is None:
        blockers.append({
            "code": "no_terms",
            "message": f"This agency has no {channel} terms yet — set a type first.",
        })
        return blockers

    windows = cycle_windows(terms, today)
    elapsed = [w for w in windows if w["elapsed"]]
    bal = await balance(db, agency.id, channel, terms.id)
    entry_count = (await db.execute(
        select(func.count()).select_from(AgencyLedger).where(
            AgencyLedger.terms_id == terms.id,
            AgencyLedger.channel == channel,
        )
    )).scalar() or 0

    # An arrangement nothing ever happened under is a correction, not a switch —
    # blocking it for a week would only make people delete and re-add the agency.
    if entry_count == 0 and not elapsed:
        return blockers

    if not elapsed:
        nxt = windows[0]["period_to"] if windows else terms.cycle_anchor_date
        blockers.append({
            "code": "cycle_open",
            "message": f"The current {terms.billing_cycle} cycle runs to {nxt:%d %b %Y} — switch once it closes.",
        })

    # "Complete the cycle" means everything consumed has been billed — NOT that
    # every elapsed window carries a billing. A quiet week with no tickets needs
    # no invoice, and demanding one would block the switch forever.
    exposure = await unbilled_exposure(db, agency, current_user)
    if exposure > ZERO:
        blockers.append({
            "code": "tickets_unbilled",
            "message": (
                f"₹{exposure:,.2f} of tickets are not billed yet (across all channels — "
                f"ticket data does not record GDS/LCC) — raise the billing before switching."
            ),
        })

    plan = settlement_plan(terms.agency_type, bal)
    if plan:
        blockers.append({"code": "balance_nonzero", "message": plan["message"], "settlement": plan})

    return blockers


async def account_summary(
    db: AsyncSession, agency: Agency, current_user: User, today: date, channel: str
) -> dict:
    """Everything the account header needs for ONE channel, in one round trip.

    `balance` here is the channel's whole history; `period_bal` is the current
    terms period only. `unbilled_exposure` is the exception — it is agency-wide
    and reported identically on both channels, tagged `unbilled_exposure_scope`
    so the screen can say so rather than implying a split that does not exist.
    """
    terms = await current_terms(db, agency.id, channel)
    bal = await balance(db, agency.id, channel)
    period_bal = await balance(db, agency.id, channel, terms.id) if terms else ZERO
    paid_in = await _sum_where(db, agency.id, channel, terms.id if terms else None, positive=True)
    billed = -(await _sum_where(db, agency.id, channel, terms.id if terms else None, positive=False))
    exposure = await unbilled_exposure(db, agency, current_user)

    limit: Optional[Decimal] = None
    available: Optional[Decimal] = None
    used_pct: Optional[float] = None
    if terms and terms.agency_type == "cash":
        # On cash the limit IS the money on deposit — nothing to configure.
        limit = paid_in
        available = period_bal
        used_pct = float(billed / paid_in * 100) if paid_in > 0 else None
    elif terms and terms.agency_type == "credit":
        limit = Decimal(str(terms.credit_limit or 0))
        available = limit + period_bal          # period_bal is negative when owing
        used_pct = float(-period_bal / limit * 100) if limit > 0 else None

    threshold = float(terms.usage_percent) if terms and terms.usage_percent is not None else None
    breached = bool(threshold is not None and used_pct is not None and used_pct >= threshold)

    return {
        "agency_id": agency.id,
        "agency_name": agency.name,
        "branch_name": agency.branch_name,
        "agency_channels": agency.channels,
        "channel": channel,
        "agency_type": terms.agency_type if terms else None,
        "billing_cycle": terms.billing_cycle if terms else None,
        "cycle_anchor_date": terms.cycle_anchor_date if terms else None,
        "terms_id": terms.id if terms else None,
        "effective_from": terms.effective_from if terms else None,
        "balance": float(bal),
        "paid_in": float(paid_in),
        "billed": float(billed),
        "limit": float(limit) if limit is not None else None,
        "available": float(available) if available is not None else None,
        "used_percent": round(used_pct, 2) if used_pct is not None else None,
        "usage_threshold": threshold,
        "threshold_breached": breached,
        "unbilled_exposure": float(exposure),
        # Agency-wide, not this channel's — tickets carry no GDS/LCC marker.
        "unbilled_exposure_scope": "agency",
        "is_settled": abs(bal) <= SETTLE_TOLERANCE,
        "settlement": settlement_plan(terms.agency_type if terms else "", bal),
    }
