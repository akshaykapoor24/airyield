"""The invoice-date rule: a new bill is never dated before the user's last bill.

An invoice series is kept in date order — a bill raised today may not be dated before
one already issued. The series here is the user's whole set of bills, every party
type: customer, corporate and agency bills share one numbering (billing_pdf's
`_invoice_number`), so a bill for one company can bound the date of the next bill for
another. The same day is allowed — several bills on one date is ordinary.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Billing


@dataclass(frozen=True)
class LastBilling:
    billing_date: date
    billing_name: str


async def last_billing(db: AsyncSession, user) -> LastBilling | None:
    """The user's latest-dated bill for anyone, or None when they have raised none."""
    row = (await db.execute(
        select(Billing.billing_date, Billing.billing_name)
        .where(Billing.tenant_id == user.tenant_id, Billing.created_by_id == user.id)
        .order_by(Billing.billing_date.desc(), Billing.id.desc())
        .limit(1)
    )).first()
    return LastBilling(row.billing_date, row.billing_name) if row else None


def date_error(chosen: date, last: LastBilling | None) -> str | None:
    """Why `chosen` cannot be a new bill's date, or None when it can. Pure."""
    if last is None or chosen >= last.billing_date:
        return None
    return (f"The billing date can't be before your last bill, dated "
            f"{last.billing_date:%d-%m-%Y} ({last.billing_name}). "
            f"Pick {last.billing_date:%d-%m-%Y} or later.")
