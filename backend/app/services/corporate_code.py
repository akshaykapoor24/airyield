"""Corporate Code — the system's own identifier for a corporate in Corporate Master.

Same rules as the Agency Code (services/agency_code.py), on its own book:
  Auto (default) → the next number in the user's current pattern, CO-0001 to start.
  Manual         → normalised, padded to the current pattern if it is in it, and
                   unique; a code with a number becomes the pattern later auto
                   codes continue (type CORP/105 and the next is CORP/106).

Scoped like corporates themselves — one user within one workspace (tenant_id +
created_by_id) — and NOT shared between rows: a corporate is one row, so there is
no sibling to share with. Distinct from `customer_code` / `account_code`, which are
the user's references to other systems and stay optional and non-unique.
"""
from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import Corporate
from app.models.user import User
from app.services.agency_code import Allocator, Pattern, parse

DEFAULT_PATTERN = Pattern("CO-", "", 4)


def _scope(user: User):
    return and_(Corporate.tenant_id == user.tenant_id, Corporate.created_by_id == user.id)


def holder_key(company: str | None) -> tuple[str, str]:
    # A corporate's name is unique per workspace (CorporateDuplicates), so it is a
    # sound holder key; the second slot exists only to match the agency shape.
    return ((company or "").strip().lower(), "")


async def allocator(db: AsyncSession, user: User, exclude_id: int | None = None) -> Allocator:
    """Every coded corporate of this user, oldest first. `exclude_id` drops the row
    being edited, so its own code is neither a clash nor the "current pattern"."""
    q = select(Corporate.id, Corporate.corporate_code, Corporate.company).where(
        _scope(user), Corporate.corporate_code.is_not(None),
    )
    if exclude_id is not None:
        q = q.where(Corporate.id != exclude_id)
    rows = [(i, c, n) for i, c, n in (await db.execute(q.order_by(Corporate.id))).all() if c]
    return Allocator(
        user.id,
        [(i, c) for i, c, _n in rows],
        # Keyed by id, not name: no two corporates may share a code, so every
        # existing holder must differ from any new row's key.
        {c: (f"#{i}", "") for i, c, _n in rows},
        default=DEFAULT_PATTERN,
        label="corporate",
    )


async def suggest(db: AsyncSession, user: User) -> tuple[str, str]:
    """(next code, pattern as AG-#### style) — what auto mode would issue now."""
    alloc = await allocator(db, user)
    code = alloc.resolve(None, "\x00preview", "")
    parsed = parse(code)
    return code, parsed[0].example if parsed else DEFAULT_PATTERN.example
