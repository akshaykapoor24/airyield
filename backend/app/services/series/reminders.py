"""Contract reminders: deadlines and payments, raised into the notification bell.

WHY A SCAN AND NOT A SCHEDULER. There is no Celery beat or cron in this stack (see the
router docstring), so nothing wakes up on the morning a deposit falls due. Instead the
open deadlines are scanned whenever someone could see the result — the bell polling, the
Series page loading, a contract being saved — and each deadline raises one notification
per STAGE it reaches: a week out, three days out, the day itself, overdue. The
notification's dedupe key is (deadline, stage, date), so scanning a hundred times a day
writes each reminder once, and a deadline that moves raises its reminders afresh.

Payments are covered by the same scan: the payment schedule already raises a deadline per
unpaid instalment (services/series/deadlines.py::specs_from_payment_schedule), so reading
deadlines reads payments too. The instalment is looked up only to put the amount in the
message.

WHY OVERDUE STOPS AFTER TWO WEEKS. An old contract keyed in for the record — the Air
France sample departed in December 2023 — has every deadline years overdue. Raising those
would bury the bell in reminders nobody can act on. Two weeks of "overdue" is enough to be
seen; after that the contract's own screen still shows it in red.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.series import SeriesContract, SeriesDeadline, SeriesPaymentSchedule
from app.services.notifications import notify
from app.services.series import deadlines as dl
from app.services.series.rollups import days_until

WEEK_AHEAD = 7
OVERDUE_WINDOW = 14
# The scan is cheap but not free; per-process throttle per tenant. Idempotent writes make a
# second process scanning at the same time harmless.
_MIN_INTERVAL_SECONDS = 300
_last_scan: dict[int, float] = {}

_LABEL = {
    "ADVANCE_DEPOSIT": "Advance deposit",
    "DEPOSIT": "Deposit",
    "FINAL_PAYMENT": "Final payment",
    "NAME_LIST": "Name list",
    "SEAT_RELEASE": "Seat release",
    "TICKETING": "Ticketing",
    "NO_SHOW_CUTOFF": "No-show cut-off",
    "DEVIATION_CUTOFF": "Deviation cut-off",
    "OPTION_EXPIRY": "Offer expiry",
    "PENALTY_STEP": "Cancellation charge rises",
}
_PAYMENT_TYPES = {"ADVANCE_DEPOSIT": ("ADVANCE_DEPOSIT",), "DEPOSIT": ("DEPOSIT",),
                  "FINAL_PAYMENT": ("FINAL_PAYMENT", "BALANCE")}


def stage(days_remaining: int | None) -> str | None:
    """Which reminder a deadline this many days away has reached, if any."""
    if days_remaining is None:
        return None
    if days_remaining < -OVERDUE_WINDOW:
        return None
    if days_remaining < 0:
        return "overdue"
    if days_remaining == 0:
        return "today"
    if days_remaining <= 3:
        return "soon"
    if days_remaining <= WEEK_AHEAD:
        return "week"
    return None


_SEVERITY = {"overdue": "critical", "today": "critical", "soon": "warning", "week": "info"}


def _when(days_remaining: int) -> str:
    if days_remaining < 0:
        n = -days_remaining
        return f"overdue by {n} day{'s' if n != 1 else ''}"
    if days_remaining == 0:
        return "due today"
    return f"due in {days_remaining} day{'s' if days_remaining != 1 else ''}"


def _money(amount) -> str:
    return f"{float(amount):,.2f}"


def message(contract, deadline, days_remaining: int, outstanding=None) -> tuple[str, str]:
    """(title, body) for one reminder."""
    who = contract.contract_number or contract.group_name or f"Contract #{contract.id}"
    label = _LABEL.get(deadline.deadline_type or "", (deadline.deadline_type or "Deadline").replace("_", " ").title())
    if deadline.deadline_type == dl.TYPE_PENALTY_STEP:
        # The deadline date is the LAST day at today's price; it rises the day after.
        if days_remaining < 0:
            head = "Cancellation charge has risen"
        elif days_remaining == 0:
            head = "Last day at the current cancellation charge"
        else:
            head = f"Cancellation charge rises in {days_remaining + 1} days"
        title = f"{head} — {who}"
    else:
        title = f"{label} {_when(days_remaining)} — {who}"
    bits = [deadline.action_required]
    if outstanding:
        bits.append(f"Outstanding {contract.currency or 'INR'} {_money(outstanding)}.")
    context = " · ".join(filter(None, [contract.group_name if contract.contract_number else None,
                                       contract.airline_code,
                                       f"on {deadline.effective_date:%d %b %Y}" if deadline.effective_date else None]))
    if context:
        bits.append(context)
    return title[:200], " ".join(filter(None, bits))[:500]


def _outstanding(contract, deadline):
    kinds = _PAYMENT_TYPES.get(deadline.deadline_type or "")
    if not kinds:
        return None
    for row in contract.payment_schedule:
        if (row.kind or "") in kinds and row.due_date == deadline.stated_date \
                and row.allocation_id == deadline.allocation_id and row.status not in ("paid", "waived"):
            remaining = float(row.amount or 0) - float(row.paid_amount or 0)
            return remaining if remaining > 0 else None
    return None


async def sync_tenant(db: AsyncSession, tenant_id: int | None, *, today: date,
                      force: bool = False, contract_id: int | None = None) -> int:
    """Raise any reminder that is due and not yet raised. Returns how many were attempted.

    Does not commit — the caller owns the transaction.
    """
    if tenant_id is None:
        return 0
    if not force and contract_id is None:
        last = _last_scan.get(tenant_id)
        if last is not None and time.monotonic() - last < _MIN_INTERVAL_SECONDS:
            return 0
        _last_scan[tenant_id] = time.monotonic()

    query = (
        select(SeriesDeadline)
        .join(SeriesContract, SeriesContract.id == SeriesDeadline.contract_id)
        .where(
            SeriesDeadline.tenant_id == tenant_id,
            SeriesDeadline.status == "open",
            SeriesDeadline.deadline_type != dl.TYPE_DEPARTURE,
            SeriesDeadline.effective_date >= today - timedelta(days=OVERDUE_WINDOW),
            SeriesDeadline.effective_date <= today + timedelta(days=WEEK_AHEAD),
            SeriesContract.status.notin_(("cancelled", "closed")),
        )
    )
    if contract_id is not None:
        query = query.where(SeriesDeadline.contract_id == contract_id)
    deadlines = list((await db.execute(query)).scalars())
    if not deadlines:
        return 0

    contracts = {
        c.id: c for c in (await db.execute(
            select(SeriesContract)
            .where(SeriesContract.id.in_({d.contract_id for d in deadlines}))
            .options(selectinload(SeriesContract.payment_schedule)
                     .selectinload(SeriesPaymentSchedule.payments))
        )).scalars()
    }

    written = 0
    for deadline in deadlines:
        remaining = days_until(deadline.effective_date, today)
        reached = stage(remaining)
        contract = contracts.get(deadline.contract_id)
        if reached is None or contract is None:
            continue
        title, body = message(contract, deadline, remaining, _outstanding(contract, deadline))
        await notify(
            db,
            tenant_id=tenant_id,
            category="series",
            kind=(deadline.deadline_type or "deadline").lower(),
            severity=_SEVERITY[reached],
            title=title,
            body=body,
            link=f"/vendors/series-sit-mice/{contract.id}",
            due_date=deadline.effective_date,
            source_type="series_deadline",
            source_id=deadline.id,
            dedupe_key=f"series:deadline:{deadline.id}:{reached}:{deadline.effective_date.isoformat()}",
        )
        written += 1
    return written
