"""Which airline an agency credential may name, by channel.

A GDS credential (mirror id) can only be for a GDS airline and an LCC one (portal
login) only for an LCC airline. The type comes from the platform's Classes & RBD
master (`airline_class_masters.airline_type`), the name and code from the Airline
master — the same two sources the Add Login IDs form filters its dropdown by, so the
API and the XLS upload enforce what the form offers rather than trusting it.

An airline with classes of both types is valid on both channels. One with no type
tagged is valid on neither: until the platform admin types it, nobody can say which
channel it belongs to.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airline import Airline
from app.models.airline_class_master import AirlineClassMaster

# Agency Master is the B2B book (Employee Master is B2C, Corporate Master B2E), so
# every agency credential is B2B.
AGENCY_LOB = "B2B"


def lob_error(raw) -> str | None:
    v = (str(raw).strip().upper() if raw is not None else "")
    if v and v != AGENCY_LOB:
        return f"Agency login IDs are always {AGENCY_LOB} — LoB '{raw}' is not allowed here."
    return None


class AirlineCatalog:
    """Airline master + per-channel type sets, loaded once per request."""

    def __init__(self, by_name: dict[str, tuple[str, str]], by_code: dict[str, tuple[str, str]],
                 types: dict[str, set[str]]):
        self.by_name = by_name          # lower name -> (name, iata)
        self.by_code = by_code          # IATA upper -> (name, iata)
        self.types = types              # channel -> {lower airline name}

    @classmethod
    async def load(cls, db: AsyncSession) -> "AirlineCatalog":
        rows = (await db.execute(select(Airline.name, Airline.iata_code))).all()
        by_name = {n.strip().lower(): (n, c) for n, c in rows if n}
        by_code = {c.strip().upper(): (n, c) for n, c in rows if c}
        typed = (await db.execute(
            select(AirlineClassMaster.airline_name, func.upper(AirlineClassMaster.airline_type))
            .where(AirlineClassMaster.airline_type.is_not(None))
            .distinct()
        )).all()
        types: dict[str, set[str]] = {"GDS": set(), "LCC": set()}
        for name, t in typed:
            if t in types and name:
                types[t].add(name.strip().lower())
        return cls(by_name, by_code, types)

    def resolve(self, name_raw, code_raw, channel: str) -> tuple[str | None, str | None]:
        """(name, code) from the master for a credential on `channel`.

        Either cell may be given; the master fills the other. Both blank is fine —
        an airline is optional on a credential. Raises ValueError otherwise.
        """
        name = (str(name_raw).strip() if name_raw is not None else "")
        code = (str(code_raw).strip().upper() if code_raw is not None else "")
        if not name and not code:
            return None, None
        hit = self.by_name.get(name.lower()) if name else None
        if hit is None and code:
            hit = self.by_code.get(code)
        if hit is None:
            raise ValueError(f"airline '{name or code}' is not in the Airline master.")
        if name and code and hit[1].upper() != code:
            raise ValueError(f"airline '{name}' has code {hit[1]}, not {code}.")
        if hit[0].strip().lower() not in self.types.get(channel, set()):
            raise ValueError(
                f"{hit[0]} is not a {channel} airline in the Classes & RBD master — "
                f"a {channel} credential can only be for a {channel} airline."
            )
        return hit
