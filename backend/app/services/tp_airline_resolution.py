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

from sqlalchemy import or_, select
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


_DIGITS_ONLY = re.compile(r"\d{1,3}")


def numeric_code(value) -> str | None:
    """An Airline Code cell holding the carrier's 3-digit accounting code ("465") rather than
    its 2-letter designator — TripJack prints its "Supplier Code" that way, and that is the
    column mapped to Airline Code. None for anything else.

    The WHOLE cell must be digits: "6E" is IndiGo's designator, and stripping its letter
    (as `normalize_prefix` would) reads it as 006, which is Delta.
    """
    s = str(value or "").strip()
    return normalize_prefix(s) if _DIGITS_ONLY.fullmatch(s) else None


# One master row as the index holds it: (id, IATA code, name, 3-digit numeric code). The
# numeric code is None for a carrier with none — its ICAO key is never a ticket prefix.
Carrier = tuple


@dataclass(frozen=True)
class TpAirlineIndex:
    """The airline master, keyed the three ways a statement row can name a carrier.

    A key whose value is None resolved to more than one master row: two carriers sharing a
    normalized name key are not a match, they are an ambiguity, and guessing between them
    would attribute a whole statement's commission to the wrong airline.

    Each value is (id, IATA code, name, 3-digit numeric code or None) — `Carrier`.
    """
    by_numeric: dict[str, Carrier | None] = field(default_factory=dict)
    by_code: dict[str, Carrier | None] = field(default_factory=dict)
    by_name_key: dict[str, Carrier | None] = field(default_factory=dict)

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
    # The master's 3-digit accounting code ("098") — what a ticket prefix is.
    numeric_code: str | None = None
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
    """PURE. Ticket prefix, then the code, then the name. See the module docstring.

    The code is the 2-letter designator, or — where the file prints the 3-digit accounting
    code in that column (`numeric_code`) — that, looked up as a prefix is."""
    by_prefix = _lookup(index.by_numeric, normalize_prefix(prefix))

    numeric = numeric_code(airline_code)
    if numeric:
        by_code = _lookup(index.by_numeric, numeric)
    else:
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
        numeric_code=winner[3] if len(winner) > 3 else None,
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

    by_numeric: dict[str, Carrier | None] = {}
    by_code: dict[str, Carrier | None] = {}
    by_name_key: dict[str, Carrier | None] = {}

    def put(table: dict, key: str | None, value: Carrier) -> None:
        if not key:
            return
        existing = table.get(key, ...)
        if existing is ...:
            table[key] = value
        elif existing is not None and existing[0] != value[0]:
            table[key] = None     # two carriers share this key — refuse to choose

    for pk, numeric, icao, iata, name in rows:
        digits = (numeric or "").strip()
        value = (pk, (iata or "").strip().upper(), name, digits.zfill(3) if digits.isdigit() else None)
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
    matching may use. The three ways a file names its carrier — `airline_name`,
    `airline_code` (the 2-letter designator, "AI") and `ticket_prefix` (the 3-digit
    accounting code, "098") — are each filled in from the master only when blank: map any
    one of them and the other two come from the Airline Master; a file that prints its own
    keeps it.

    An Airline Code that is the 3-digit accounting code (`numeric_code`) is not one: PLB
    accrual joins `airlines.iata_code` to it and would drop the row. The designator takes
    its place, and the number moves to Ticket Prefix, where it belongs, unless the file
    printed one there.
    """
    if not match.resolved:
        return False
    data[MASTER_NAME_FIELD] = match.name
    data[AIRLINE_ID_FIELD] = str(match.airline_id)
    numeric = numeric_code(data.get("airline_code"))
    if numeric and match.iata_code:
        if not data.get("ticket_prefix"):
            data["ticket_prefix"] = numeric
        data["airline_code"] = match.iata_code
    if not data.get("airline_code") and match.iata_code:
        data["airline_code"] = match.iata_code
    if not data.get("airline_name") and match.name:
        data["airline_name"] = match.name
    if not data.get("ticket_prefix") and match.numeric_code:
        data["ticket_prefix"] = match.numeric_code
    if match.conflict:
        data[CONFLICT_FIELD] = (
            f"Ticket prefix says {match.name}; the Airline Name column says "
            f"{match.conflict_name}. The prefix was used."
        )
    return True


# Saved lines whose carrier did not resolve, whose Airline Code is a 3-digit accounting code
# (TripJack uploads before `numeric_code` existed), or that lack one of the three carrier
# fields `stamp` fills (lines saved before it filled them all).
_NUMERIC_SQL = r"^\s*\d{1,3}\s*$"
_CARRIER_FIELDS = ("airline_name", "airline_code", "ticket_prefix")


async def restamp_saved(db: AsyncSession, model, index: TpAirlineIndex) -> tuple[int, set[tuple[int, int, str]]]:
    """Resolve the carrier of the SAVED lines of `model` again, against `index`.

    For lines saved before a rule here changed, or before the Airline Master had their
    carrier: an upload is stamped once, at ingest, and nothing else revisits it. Only lines
    that are unresolved, carry a numeric Airline Code or miss one of the three carrier
    fields are read; the rest are as this would leave them.

    Returns (lines changed, {(tenant_id, created_by_id, batch_id)} they belong to) — the
    caller re-projects those statements (income_board.refresh), which copy the carrier.
    Writes through `data`, so a typed table (third_party_gds) and a JSONB one alike.
    """
    rows = (await db.execute(
        select(model).where(
            model.data["row_kind"].astext.is_(None),        # a balance line has no carrier
            or_(
                model.data["airline_id"].astext.is_(None),
                model.data["airline_code"].astext.op("~")(_NUMERIC_SQL),
                *[model.data[f].astext.is_(None) for f in _CARRIER_FIELDS],
            ),
        ).order_by(model.id)
    )).scalars().all()
    changed, batches = 0, set()
    for row in rows:
        data = dict(row.data or {})
        before = dict(data)
        if not stamp(data, resolve_tp_airline(
                data.get("ticket_prefix"), data.get("airline_code"), data.get("airline_name"), index)):
            continue
        if data != before:
            row.data = data
            changed += 1
            batches.add((row.tenant_id, row.created_by_id, row.batch_id))
    return changed, batches
