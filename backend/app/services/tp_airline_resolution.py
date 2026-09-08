"""Which carrier a third-party statement row is for.

A consolidator's GDS export identifies the carrier three ways, and in the real sample the
most obvious one is empty:

    Airline Name   "TURKISH AIRLINES"   present, but the file's spelling, not the master's
    TicketPrefix   "235"                the 3-digit IATA numeric — the plating carrier
    Airline Code   ""                   blank on every row

Two things depend on getting this right, and both fail silently if it is wrong rather than
loudly:

  * **Deal matching** compares `lower(deals.airline_name)` to the row's airline
    (services/deal_matching.py). `deals.airline_name` holds the MASTER's spelling, so the
    file's "TURKISH AIRLINES" has to become "Turkish Airlines" or nothing matches.
  * **PLB accrual** joins `upper(airlines.iata_code)` to `data->>'airline_code'`
    (services/plb_accrual.py). A blank code means the row is simply absent from the
    accrual — no error, no zero row, just missing revenue.

WHY THE TICKET PREFIX WINS OVER THE NAME. services/airline_resolver.py resolves DEAL
SHEETS name-first and says so emphatically, because a deal sheet's code cell is typed by a
human and is demonstrably wrong ("AIR CANADA" in the code column, "American Airline / AI").
None of that applies here: a ticket prefix is machine-generated stock and it identifies the
carrier whose document this is and whose commission we are claiming. It is also exactly
what BSP already does — api/v1/bsp.py::_airline_iata_name_map keys the master by accounting
code and services/bsp_commission.py reads the accounting code before the IATA code.

When the prefix and the name resolve to DIFFERENT carriers the prefix still wins, but the
match is flagged `conflict=True` so the row can say so instead of quietly picking one.

Split pure-rule / DB-adapter like services/lcc_airline_selection.py: `resolve_tp_airline`
is a pure function over an index and is unit-tested without a database; `build_index` is
the one query that fills it, run once per upload rather than once per row.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airline import Airline
from app.services.airline_resolver import airline_match_key, clean_airline_code

# A ticket/document prefix is the 3-digit IATA numeric (235 Turkish, 157 Qatar, 607 Etihad,
# 098 Air India). Exports print it with or without the leading zero, so both are indexed.
_DIGITS = re.compile(r"\D+")


def normalize_prefix(value) -> str | None:
    """'235' / ' 0235 ' / '235-' -> '235'. None when there is no 3-digit code in the cell.

    A ticket NUMBER may arrive here by mistake (4848358656). Anything longer than 3 digits
    is rejected rather than truncated — taking the first three of a ticket number would
    resolve to a real but wrong carrier, which is worse than not resolving at all.
    """
    s = _DIGITS.sub("", str(value or ""))
    if not s:
        return None
    s = s.lstrip("0") or "0"
    return s.zfill(3) if len(s) <= 3 else None


@dataclass(frozen=True)
class TpAirlineIndex:
    """The airline master, keyed the three ways a statement row can name a carrier.

    A key whose value is None resolved to more than one master row: two carriers sharing a
    normalized name key are not a match, they are an ambiguity, and guessing between them
    would attribute a whole statement's commission to the wrong airline.
    """
    by_numeric: dict[str, tuple[int, str, str] | None] = field(default_factory=dict)
    by_code: dict[str, tuple[int, str, str] | None] = field(default_factory=dict)
    by_name_key: dict[str, tuple[int, str, str] | None] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.by_numeric or self.by_code or self.by_name_key)


# `source` values — which cell actually identified the carrier.
BY_PREFIX = "prefix"
BY_CODE = "code"
BY_NAME = "name"


@dataclass(frozen=True)
class TpAirlineMatch:
    airline_id: int | None = None
    iata_code: str | None = None
    name: str | None = None
    source: str | None = None
    # The prefix and the name each resolved, to different carriers. The prefix is used.
    conflict: bool = False
    conflict_name: str | None = None

    @property
    def resolved(self) -> bool:
        return self.airline_id is not None


def _lookup(table: dict, key: str | None):
    return table.get(key) if key else None


def resolve_tp_airline(
    prefix: str | None,
    airline_code: str | None,
    airline_name: str | None,
    index: TpAirlineIndex,
) -> TpAirlineMatch:
    """PURE. Ticket prefix, then the 2-letter code, then the name. See the module docstring."""
    by_prefix = _lookup(index.by_numeric, normalize_prefix(prefix))

    code, _multi = clean_airline_code(airline_code)
    by_code = _lookup(index.by_code, code)

    key = airline_match_key(airline_name)
    by_name = _lookup(index.by_name_key, key)

    winner, source = None, None
    for candidate, label in ((by_prefix, BY_PREFIX), (by_code, BY_CODE), (by_name, BY_NAME)):
        if candidate is not None:
            winner, source = candidate, label
            break

    if winner is None:
        return TpAirlineMatch()

    # Only a disagreement between two things that BOTH resolved is a conflict. A name the
    # master has never seen is silence, not contradiction.
    other = by_name if source in (BY_PREFIX, BY_CODE) else None
    conflict = other is not None and other[0] != winner[0]

    return TpAirlineMatch(
        airline_id=winner[0], iata_code=winner[1], name=winner[2], source=source,
        conflict=conflict, conflict_name=(other[2] if conflict else None),
    )


async def build_index(db: AsyncSession) -> TpAirlineIndex:
    """One query over the airline master → the lookup tables `resolve_tp_airline` reads.

    Keyed like api/v1/bsp.py::_airline_iata_name_map — numeric preferred, ICAO as the
    fallback for a carrier with no accounting code, zero-padded to three.
    """
    rows = (await db.execute(
        select(Airline.id, Airline.iata_numeric_code, Airline.icao_code,
               Airline.iata_code, Airline.name)
        .where(Airline.is_active.is_(True))
    )).all()

    by_numeric: dict[str, tuple[int, str, str] | None] = {}
    by_code: dict[str, tuple[int, str, str] | None] = {}
    by_name_key: dict[str, tuple[int, str, str] | None] = {}

    def put(table: dict, key: str | None, value: tuple[int, str, str]) -> None:
        if not key:
            return
        existing = table.get(key, ...)
        if existing is ...:
            table[key] = value
        elif existing is not None and existing[0] != value[0]:
            table[key] = None     # two carriers share this key — refuse to choose

    for pk, numeric, icao, iata, name in rows:
        value = (pk, (iata or "").strip().upper(), name)
        code = (numeric or icao or "").strip()
        if code:
            put(by_numeric, code.zfill(3) if code.isdigit() else code.upper(), value)
        put(by_code, (iata or "").strip().upper() or None, value)
        put(by_name_key, airline_match_key(name) or None, value)

    return TpAirlineIndex(by_numeric=by_numeric, by_code=by_code, by_name_key=by_name_key)


# Keys written into the row's `data` so every downstream reader — deal matching, PLB
# accrual, the drill-in table — sees the same resolution, and so the file's own spelling
# is never overwritten.
MASTER_NAME_FIELD = "airline_master_name"
AIRLINE_ID_FIELD = "airline_id"
CONFLICT_FIELD = "airline_conflict"


def stamp(data: dict, match: TpAirlineMatch) -> bool:
    """Write a resolution onto a parsed row. Returns whether anything resolved.

    `airline_name` keeps the FILE's spelling — it is what the vendor sent and the drill-in
    should show it. `airline_master_name` is the canonical one, and it is the only one deal
    matching may use. `airline_code` is filled in only when blank, so a file that states
    its own code keeps it.
    """
    if not match.resolved:
        return False
    data[MASTER_NAME_FIELD] = match.name
    data[AIRLINE_ID_FIELD] = str(match.airline_id)
    if not data.get("airline_code") and match.iata_code:
        data["airline_code"] = match.iata_code
    if match.conflict:
        data[CONFLICT_FIELD] = (
            f"Ticket prefix says {match.name}; the Airline Name column says "
            f"{match.conflict_name}. The prefix was used."
        )
    return True
