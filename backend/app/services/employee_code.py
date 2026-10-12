"""Employee Code — the identifier for a person in Employee Master.

Same rules as the Agency and Corporate codes (services/agency_code.py), on its own
book: issued EMP-0001, EMP-0002 … unless typed in; a typed code with a number becomes
the pattern later auto codes continue (a payroll id E1042 makes the next one E1043).
Scoped like customers — one user within one workspace — and unique there, as the
partial index `uq_customers_employee_code` already required.

AN AUTO CODE DOES NOT TELL NAMESAKES APART. services/party_dedupe treats a coded
employee as a different person from an uncoded one of the same name under the same
employer — that is what the code is for. An auto code is handed out to everyone, so
it says nothing about who someone is: callers run the duplicate check on the code
the USER typed (None in auto mode) and only issue the auto code once that passes.
Otherwise every second "John Doe" at Acme would sail through as a different person.
"""
from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.user import User
from app.services.agency_code import Allocator, Pattern, parse

DEFAULT_PATTERN = Pattern("EMP-", "", 4)
MAX_LEN = 50     # customers.employee_code is String(50), and payroll ids run long


def _scope(user: User):
    return and_(Customer.tenant_id == user.tenant_id, Customer.created_by_id == user.id)


async def allocator(db: AsyncSession, user: User, exclude_id: int | None = None) -> Allocator:
    q = select(Customer.id, Customer.employee_code).where(
        _scope(user), Customer.employee_code.is_not(None),
    )
    if exclude_id is not None:
        q = q.where(Customer.id != exclude_id)
    rows = [(i, c) for i, c in (await db.execute(q.order_by(Customer.id))).all() if c]
    return Allocator(
        user.id, rows, {c: (f"#{i}", "") for i, c in rows},
        default=DEFAULT_PATTERN, label="employee", max_len=MAX_LEN,
    )


async def suggest(db: AsyncSession, user: User) -> tuple[str, str]:
    alloc = await allocator(db, user)
    code = alloc.resolve(None, "\x00preview", "")
    parsed = parse(code)
    return code, parsed[0].example if parsed else DEFAULT_PATTERN.example
