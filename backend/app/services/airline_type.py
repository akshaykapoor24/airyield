"""An airline's channel (GDS / LCC), read from the Classes & RBD master.

The Airline master has no type of its own. `airline_class_masters` carries
`airline_type` per class row and points at an airline by name only, so the
lookup is on the trimmed, lower-cased name — the same match
/classes/airlines-with-type and the agency login-id checks use, so every screen
agrees on which airlines are GDS and which are LCC.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airline_class_master import AirlineClassMaster


def name_key(name: str | None) -> str:
    return (name or "").strip().lower()


async def airline_types_by_name(db: AsyncSession) -> dict[str, str]:
    """{name_key: "GDS" | "LCC"} for every airline the class master types.

    An airline whose class rows disagree comes back as "GDS/LCC" rather than
    one of the two picked arbitrarily.
    """
    rows = (await db.execute(
        select(AirlineClassMaster.airline_name, func.upper(func.trim(AirlineClassMaster.airline_type)))
        .where(AirlineClassMaster.airline_type.is_not(None))
        .distinct()
    )).all()
    types: dict[str, set[str]] = {}
    for name, t in rows:
        if name and t:
            types.setdefault(name_key(name), set()).add(t)
    return {k: "/".join(sorted(v)) for k, v in types.items()}
