"""Where a ticket goes — origin and destination read off a statement's Sector.

Inclusion / exclusion rules are written in places (origin continent, destination country,
country group, city, airport) but a statement only prints a Sector, and consolidators print
it as the whole itinerary:

    TripJack    DEL/ALA/DEL · BOM/ALA/TAS/ALA/BOM · DEL/KUL/AKL · EMD
    Brightsun   KEF/FRA/ MXP · DEL/HAN/ DAD/ SGN/ HAN/ DEL · YYZ/DEL/ YYZ

So "the destination" is not simply the last airport. The rule this file applies:

  * ORIGIN is the first airport.
  * A trip that comes BACK HOME — ends where it started, or ends in the origin's country
    after visiting another — is a round trip, and its DESTINATION is the turnaround: the
    middle stop (DEL/ALA/DEL → ALA, BOM/ALA/TAS/ALA/BOM → TAS). The old evaluator took the
    last airport, so every round trip's destination was its own origin and every
    destination rule judged DEL.
  * Anything else is one-way, and the DESTINATION is the last airport (DEL/KUL/AKL → AKL;
    KUL is a connection, not where the passenger is going).

A Sector that is not a list of 3-letter codes is not a route. "EMD" (an EMD line) is one
token, and it happens to be a real airport — Emerald, Australia — which is exactly why a
single token is refused rather than looked up.

Each airport is read from the Airport Master (Platform admin), which carries its country,
continent, categorization (country group) and city. An airport the master does not hold is
reported, never guessed: a rule that needs it cannot be judged.

`parse_points` and `build_route` are pure and unit-tested; `resolve_route` is the one DB
adapter, memoised per session like the class-master lookup.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airport import Airport, city_of

# Separators seen in real Sector cells: "/", "/ " (Brightsun pads), "-", spaces, "→".
_SPLIT = re.compile(r"[\s/\-–—>→,|]+")
_IATA = re.compile(r"[A-Z]{3}")


@dataclass(frozen=True)
class AirportView:
    """The fields a rule reads off one Airport Master row.

    A plain value object rather than the ORM row: the cache below outlives the periodic
    commits inside a commission run, and an expired instance would be a landmine.
    """
    iata_code: str
    country: str | None
    categorization: str | None
    continent: str | None
    city_airport_name: str | None

    @property
    def city(self) -> str | None:
        return city_of(self.city_airport_name)


@dataclass(frozen=True)
class Route:
    points: tuple[str, ...]
    origin: str
    destination: str
    round_trip: bool
    # code → its master row, or None when the master does not hold it.
    airports: Mapping[str, AirportView | None] = field(default_factory=dict, compare=False)

    def airport(self, code: str) -> AirportView | None:
        return self.airports.get(code)

    @property
    def missing(self) -> tuple[str, ...]:
        """Codes on this route the Airport Master does not hold, in route order."""
        seen: list[str] = []
        for p in self.points:
            if self.airports.get(p) is None and p not in seen:
                seen.append(p)
        return tuple(seen)

    @property
    def label(self) -> str:
        """'DEL → ALA (round trip)' — what the rules were judged on, for display."""
        return f"{self.origin} → {self.destination}" + (" (round trip)" if self.round_trip else "")


def parse_points(sector) -> tuple[str, ...] | None:
    """'DEL/HAN/ DAD/ SGN' → ('DEL', 'HAN', 'DAD', 'SGN'). None when the cell is not a route:
    blank, a single token, or anything that is not a 3-letter code. A repeated point
    (DEL/DEL/BOM) is one stop."""
    if not sector:
        return None
    tokens = [t for t in _SPLIT.split(str(sector).strip().upper()) if t]
    if not tokens or not all(_IATA.fullmatch(t) for t in tokens):
        return None
    points: list[str] = []
    for t in tokens:
        if not points or points[-1] != t:
            points.append(t)
    return tuple(points) if len(points) >= 2 else None


def _country(apt: AirportView | None) -> str | None:
    c = (apt.country or "").strip().lower() if apt else ""
    return c or None


def build_route(points: tuple[str, ...], airports: Mapping[str, AirportView | None]) -> Route:
    """Origin, destination and round-trip-ness for a parsed itinerary. See the module note."""
    origin, last = points[0], points[-1]
    destination, round_trip = last, False
    if len(points) >= 3:
        home = _country(airports.get(origin))
        went_abroad = any(_country(airports.get(p)) not in (None, home) for p in points[1:-1])
        back_home = last == origin or (
            home is not None and _country(airports.get(last)) == home and went_abroad)
        if back_home:
            round_trip = True
            mid = (len(points) - 1) // 2
            # The middle stop, or the nearest one to it that is not the origin itself.
            order = sorted(range(1, len(points) - 1), key=lambda i: (abs(i - mid), i))
            destination = next((points[i] for i in order if points[i] != origin), last)
    return Route(points=points, origin=origin, destination=destination,
                 round_trip=round_trip, airports=dict(airports))


async def get_airport(db: AsyncSession, iata: str) -> AirportView | None:
    """Airport Master lookup, memoised for the life of the session.

    Bounded by the master itself (~1.2k airports), so a long commission run does at most one
    query per distinct code. `db.info` is per-session — per run in the worker, per request
    in the API. Misses are cached too: an unknown code must not be re-queried on every row.
    """
    key = (iata or "").strip().upper()
    if not key:
        return None
    cache: dict[str, AirportView | None] = db.info.setdefault("_airport_cache", {})
    if key in cache:
        return cache[key]
    apt = (await db.execute(
        select(Airport).where(func.upper(Airport.iata_code) == key)
    )).scalar_one_or_none()
    view = AirportView(
        iata_code=apt.iata_code, country=apt.country, categorization=apt.categorization,
        continent=apt.continent, city_airport_name=apt.city_airport_name,
    ) if apt is not None else None
    cache[key] = view
    return view


async def resolve_route(db: AsyncSession, sector) -> Route | None:
    """The route a Sector describes, with every stop's master row. None when the Sector is
    not a route (see `parse_points`)."""
    points = parse_points(sector)
    if points is None:
        return None
    airports = {p: await get_airport(db, p) for p in dict.fromkeys(points)}
    return build_route(points, airports)
