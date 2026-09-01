"""Validating the set of airline ids an LCC Detailed upload is linked to.

An LCC export names no carrier, so the user declares it at upload by picking ids from
their Airline Master. They may pick SEVERAL — a statement routinely covers more than
one of their logins for the same carrier.

**Every id in one selection must belong to the same airline.** That is not a
convenience rule, it is what holds the schema together: the batch and every one of its
rows carry `airline_id / airline_name / airline_code`, stamped from this selection. The
file has no airline column and no way to attribute a row to one id rather than another,
so a selection spanning two carriers could not be stamped onto anything — every row
would end up with no carrier, and the reports, PLB accrual and commission matching that
read `LccDetailed.airline_code` would go blind.

`resolve_selection` is the rule itself — pure and session-free, so it can be unit-tested
without a database like `services/tenant_airline_catalog.py`. `resolve_for_upload` adds
the tenant lookup around it, and is shared by both upload paths (LCC Detailed's own
wizard router and the spec-driven statements router) so the two cannot drift apart.
Neither raises HTTPException: the routers map these errors to 400.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_airline import TenantAirline


class MixedAirlineSelection(ValueError):
    """The picked ids span more than one carrier. Carries a user-facing message."""


class UnknownAirlineId(ValueError):
    """An id that is not in this tenant's Airline Master."""


def resolve_selection(tenant_airlines: list) -> list:
    """The ids to link, de-duplicated and in pick order.

    Raises ``ValueError`` on an empty selection and ``MixedAirlineSelection`` when the
    ids belong to more than one airline, naming the carriers so the user can see which
    pick to drop.
    """
    seen: set[int] = set()
    ordered = []
    for ta in tenant_airlines:
        if ta.id in seen:
            continue
        seen.add(ta.id)
        ordered.append(ta)

    if not ordered:
        raise ValueError(
            "Select the airline ID this statement belongs to — the file itself doesn't say."
        )

    # dict, not set: preserves pick order so the message names the carriers in the
    # order the user chose them, and the first one is the airline they started from.
    by_airline: dict[int, str] = {}
    for ta in ordered:
        by_airline.setdefault(ta.airline_id, ta.airline_name or f"airline {ta.airline_id}")

    if len(by_airline) > 1:
        names = list(by_airline.values())
        raise MixedAirlineSelection(
            f"All the IDs on one statement must belong to the same airline, but these "
            f"span {' and '.join(names)}. An LCC file has no airline column, so a "
            f"statement can only be stamped with one carrier."
        )

    return ordered


async def resolve_for_upload(
    db: AsyncSession, tenant_id: int, tenant_airline_ids: list[int]
) -> list[TenantAirline]:
    """The Airline Master rows for an upload's selection, validated.

    One query for the lot, then the pure rule above. Raises ``ValueError`` on an empty
    selection, ``UnknownAirlineId`` for an id outside this tenant's master, and
    ``MixedAirlineSelection`` for a set spanning two carriers.
    """
    if not tenant_airline_ids:
        raise ValueError(
            "Select the airline ID this statement belongs to — the file itself doesn't say."
        )

    found = {
        ta.id: ta
        for ta in (await db.execute(
            select(TenantAirline).where(
                TenantAirline.id.in_(tenant_airline_ids),
                TenantAirline.tenant_id == tenant_id,
            )
        )).scalars().all()
    }
    if any(i not in found for i in tenant_airline_ids):
        raise UnknownAirlineId(
            "That airline is not in your Airline Master. Add it under User Master → Airline Master."
        )

    # Ordered by the user's picks, not by the IN clause, so the first one chosen is
    # the one recorded as primary.
    return resolve_selection([found[i] for i in tenant_airline_ids])
