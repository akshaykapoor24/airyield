"""Per-sector row expansion for airline ticket statements (TGQ HMPR / NDC).

An airline statement carries ONE line per ticket, even when the passenger flew several
sectors::

    Sectors       BOM/DEL DEL/MNL MNL/DEL DEL/BOM
    FlightNo      AI-2928 AI-2362 AI-2361 AI-2975
    TravelDt      28APR   28APR   14MAY   15MAY
    Class         L       L       U       U
    Coupon_Status OPEN    OPEN    OPEN    OPEN
    Base_Fare     293475            <- the WHOLE ticket

This module turns that into one row per flown sector, with every money column allocated
across the legs so each column re-sums to the original **exactly** (largest remainder, so
no paisa is invented or lost).

Two deliberate design rules:

* **Fail closed.** If the sector string does not parse into an unambiguous list of legs,
  the row is returned untouched with ``split_status="unparsed"`` and NOTHING is divided.
  Dividing by a leg count we are not sure of would silently corrupt money. Same discipline
  as ``workers/bsp_tasks._distribute_spdr_canx``, which refuses to split on a remainder.
* **Strings in, strings out.** ``api/v1/statements._clean`` stores every cell as ``str``
  or ``None``; this module preserves that invariant so the JSONB ``data`` blob stays
  homogeneous. Non-numeric values are copied verbatim, never coerced.

Pure functions only — no DB, no FastAPI, no config imports.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# "CCU/BKK" — one flown sector. The airline grammar joins these with spaces.
_PAIR_RE = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
# "DEL/BOM/MAA" — the B2B slash-chain grammar (see api/v1/tickets._SECTOR_B2B_RE).
_CHAIN_RE = re.compile(r"^[A-Z]{3}(/[A-Z]{3})+$")
_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")

# split_status values
SINGLE = "single"          # one leg — row untouched
SPLIT = "split"            # cleanly expanded into N legs
SPLIT_PARTIAL = "split_partial"   # expanded, but a parallel field had the wrong token count
UNPARSED = "unparsed"      # sector string not understood — row untouched, nothing divided
TOTAL = "total"            # the file's declared grand-total line


def leg_sectors(sectors: str | None) -> tuple[list[str], str]:
    """``"CCU/BKK BKK/CCU"`` -> ``(["CCU/BKK", "BKK/CCU"], "split")``.

    Returns ``([], SINGLE)`` for a blank sector string (the grand-total line and
    sector-less refunds), and ``([], UNPARSED)`` for anything not understood.
    """
    s = (sectors or "").strip().upper()
    if not s:
        return [], SINGLE

    tokens = s.split()

    # Airline grammar: space-separated ORG/DST pairs.
    if all(_PAIR_RE.match(t) for t in tokens):
        return (tokens, SINGLE if len(tokens) == 1 else SPLIT)

    # B2B grammar: a single slash-chain, DEL/BOM/MAA -> DEL/BOM, BOM/MAA.
    if len(tokens) == 1 and _CHAIN_RE.match(tokens[0]):
        airports = tokens[0].split("/")
        pairs = [f"{airports[i]}/{airports[i + 1]}" for i in range(len(airports) - 1)]
        return (pairs, SINGLE if len(pairs) == 1 else SPLIT)

    # Fare-construction markers ("X/SIN"), mixed grammars, junk — do not guess.
    return [], UNPARSED


def tokens(value: str | None, n: int) -> list[str]:
    """Tokenize a parallel field into per-leg tokens.

    HMPR delimits ``Class`` with spaces (``"V V"``, ``"L L U U"``, ``"J J C C"``), but
    some GDS exports use slashes (``"V/V"``). Whitespace wins; the slash split is only
    tried when it produces exactly ``n`` tokens, so ``"Y/B"`` on a 1-leg ticket is left
    alone as a single fare-class string.
    """
    if not value:
        return []
    parts = str(value).strip().split()
    if len(parts) == 1 and "/" in parts[0]:
        alt = [p for p in parts[0].split("/") if p]
        if len(alt) == n:
            return alt
    return parts


def _fmt(d: Decimal) -> str:
    """Render a Decimal the way the source file would: ``146738``, not ``146738.00``."""
    q = d.normalize()
    if q == q.to_integral_value():
        return str(q.quantize(Decimal(1)))
    return format(q, "f")


def allocate(raw: str | None, n: int, precision: int = 2) -> list[str | None]:
    """Split ``raw`` into ``n`` parts that re-sum to ``raw`` EXACTLY at ``precision`` dp.

    Uses largest-remainder allocation on integer minor units, so there is never a rounding
    residue::

        allocate("6395", 3)     -> ["2131.67", "2131.67", "2131.66"]   sum 6395
        allocate("-100.01", 3)  -> ["-33.34", "-33.34", "-33.33"]      sum -100.01
        allocate("293475", 2)   -> ["146737.5", "146737.5"]            sum 293475

    Blank or non-numeric input is copied verbatim to every leg — we never coerce a value
    we cannot interpret.
    """
    if n <= 1:
        return [raw]
    if raw is None or str(raw).strip() == "":
        return [raw] * n

    text = str(raw).replace(",", "").strip()
    if not _NUMERIC_RE.match(text):
        return [raw] * n
    try:
        d = Decimal(text)
    except InvalidOperation:
        return [raw] * n

    scale = Decimal(10) ** precision
    units = int((d * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    sign = -1 if units < 0 else 1
    base, rem = divmod(abs(units), n)
    # The first `rem` legs carry one extra minor unit — deterministic and sum-preserving.
    return [_fmt(Decimal(sign * (base + (1 if i < rem else 0))) / scale) for i in range(n)]


# "098 5805708071" / "618 5800920932-933" — 3-digit airline accounting code, then the
# document serial (which may be a conjunction range).
_TKT_SPLIT_RE = re.compile(r"^(\d{3})[\s\-]+(\d[\d\s\-]*)$")
# Same thing with no separator: 3-digit code + 10-digit serial run together.
_TKT_JOINED_RE = re.compile(r"^(\d{3})(\d{10})$")


def split_ticket_no(value: str | None) -> tuple[str | None, str | None]:
    """``"098 5805708071"`` -> ``("098", "5805708071")``.

    A ticket number is an IATA airline accounting code (098 = Air India, 217 = Thai,
    618 = Singapore Airlines) followed by the 10-digit document serial, and GDS exports
    put both in one cell. Returns ``(None, value)`` when the shape isn't recognised — a
    value we can't read confidently is left whole rather than guessed at.
    """
    if value is None:
        return None, value
    s = str(value).strip()
    if not s:
        return None, value
    m = _TKT_SPLIT_RE.match(s) or _TKT_JOINED_RE.match(s)
    if not m:
        return None, value
    return m.group(1), m.group(2).strip()


def apply_ticket_no(data: dict, cfg: dict | None) -> tuple[dict, bool]:
    """Lift the airline accounting code out of the ticket-number cell into its own field.

    Returns ``(data, changed)`` and never mutates the input. When the cell doesn't parse
    the row is handed back untouched, which also makes this idempotent: re-running against
    an already-split ``"5805708071"`` is a no-op instead of blanking the code.
    """
    if not cfg:
        return data, False
    src = cfg.get("source", "ticket_no")
    code, serial = split_ticket_no(data.get(src))
    if not code:
        return data, False
    out = dict(data)
    out[cfg.get("code_field", "airline_code")] = code
    out[src] = serial
    return out, True


def is_total_row(data: dict, cfg: dict | None) -> bool:
    """Is this the statement's declared grand-total line rather than a ticket?

    Both conditions must hold, so a real PCC or agency literally named "TOTAL" is never
    swallowed: some cell's value is one of ``value_in``, AND every ``require_blank`` field
    is empty. All fields are scanned because exports move the literal "Total" between
    ``Booking_PCC`` / ``PCC`` / ``SNO``.
    """
    if not cfg or not data:
        return False
    wanted = {str(v).strip().lower() for v in cfg.get("value_in", [])}
    if not wanted:
        return False
    if not any(str(v).strip().lower() in wanted for v in data.values() if v is not None):
        return False
    for field in cfg.get("require_blank", []):
        if (data.get(field) or "").strip():
            return False
    return True


def split_row(
    data: dict,
    taxes: list[dict] | None,
    cfg: dict,
) -> list[tuple[dict, list[dict], int, int, str]]:
    """Expand one statement row into one row per flown sector.

    Returns ``[(leg_data, leg_taxes, sector_index, sector_count, split_status), ...]``.
    A single-leg or unparsed row returns exactly one tuple holding the ORIGINAL dicts —
    an identity path, so enabling the config can never alter a single-sector ticket.
    """
    taxes = taxes or []
    sectors, status = leg_sectors(data.get(cfg.get("sector_field", "sectors")))
    n = len(sectors)

    if n <= 1 or status == UNPARSED:
        return [(data, taxes, 1, 1, status)]

    precision = int(cfg.get("precision", 2))

    # Per-leg tokens for the fields that run parallel to Sectors.
    parallel: dict[str, list[str | None]] = {}
    partial = False
    for pf in cfg.get("parallel_fields", []):
        field = pf["field"]
        toks = tokens(data.get(field), n)
        if len(toks) == n:
            vals: list[str | None] = list(toks)
        elif len(toks) == 1 and pf.get("on_short") == "broadcast":
            # "V" across 4 legs genuinely means V on every leg.
            vals = [toks[0]] * n
        elif not toks:
            vals = [None] * n
        else:
            # Wrong token count: pad or truncate rather than mis-align, and flag it.
            # Fabricating a flight number would be worse than leaving it blank.
            vals = [toks[i] if i < len(toks) else None for i in range(n)]
            partial = True
        parallel[field] = vals

    # Allocate each money column across the legs.
    divided: dict[str, list[str | None]] = {
        field: allocate(data.get(field), n, precision)
        for field in cfg.get("divide_fields", [])
        if field in data
    }

    # And every tax amount, or a leg's taxes would no longer sum to its Total_Tax.
    leg_taxes: list[list[dict]] = [[] for _ in range(n)]
    if cfg.get("divide_taxes", False) and taxes:
        for t in taxes:
            parts = allocate(t.get("amount"), n, precision)
            for i in range(n):
                leg_taxes[i].append({**t, "amount": parts[i]})
    else:
        leg_taxes = [[dict(t) for t in taxes] for _ in range(n)]

    out: list[tuple[dict, list[dict], int, int, str]] = []
    leg_status = SPLIT_PARTIAL if partial else SPLIT
    for i in range(n):
        leg = dict(data)
        leg[cfg.get("sector_field", "sectors")] = sectors[i]
        for field, vals in parallel.items():
            leg[field] = vals[i]
        for field, vals in divided.items():
            leg[field] = vals[i]
        out.append((leg, leg_taxes[i], i + 1, n, leg_status))
    return out
