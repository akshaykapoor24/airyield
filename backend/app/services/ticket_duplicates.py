"""Internal Statement: a ticket loaded twice — the one check an upload makes.

THE RULE. A statement of any period, uploaded at any time, is checked ticket line by ticket
line against every ticket already loaded in Internal Statement — this user's (every read here
is scoped to tenant and creator), from every uploaded statement and every Create Ticket entry,
whatever its customer or period. A line is a DUPLICATE when these five are the same as on a
ticket already loaded:
  * Booked Date — the Ticket Date, else the Doc Date (a GLOBE statement has only that);
  * Ticket No — its last ten digits, so "157 5808758776" and "5808758776" agree;
  * Pax Name — case and spacing ignored;
  * Amount — the Total / Bill amount, to the paisa (float noise is not a change);
  * Travel Date.
A duplicate is not saved: the preview lists it, and where the ticket is already loaded, before
Save. A file of nothing but duplicates is not saved at all. The file being uploaded is NOT
checked against itself — a line it holds twice is saved twice; only what is already loaded
counts.

Two guards, so the rule never drops a line that is not a repeat:
  * a sale and its refund are never each other's duplicate — a refund printed with a positive
    amount would otherwise match its sale exactly. Sale or refund is read the way vendor ↔
    internal reconciliation reads it (services/vendor_internal_recon.py): an IS / IR Doc No
    says it outright; else a Credit Note or Refund invoice type, else a negative amount;
  * a line with neither a Ticket No nor a Pax Name is never a duplicate — nothing in it says
    which ticket it is, and two such lines alike in dates and amount are not shown to be one.

A saved ticket answers to two keys: the one stored on it when it was saved (`dedup_key`, so a
later edit of a cell does not hide the line it came from) and the one its columns give now (so
a ticket saved before the key was stored, or under an older rule, is found all the same).
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import statement_period

_CENT = Decimal("0.01")
# Lines listed back to the user. The counts, and the grid's marks, always cover every line.
MAX_LISTED = 200
# Keys per lookup query — well under the driver's bind-parameter limit.
_CHUNK = 5000
# The columns a saved ticket's key is worked out from.
KEY_COLUMNS = ("ticket_number", "pax_name", "last_name", "first_name", "ticket_date", "doc_date",
               "total_amt", "departure_datetime", "doc_no", "invoice_type")


# ── the line key ─────────────────────────────────────────────────────────────
def _get(row, name: str):
    if isinstance(row, Mapping):
        return row.get(name)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping.get(name)
    return getattr(row, name, None)


def _text(value) -> str:
    return " ".join(str(value or "").upper().split())


def _amount(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(Decimal(str(value).replace(",", "")).quantize(_CENT, ROUND_HALF_UP))
    except InvalidOperation:
        return _text(value)


def _number(value) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "")) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _day(value) -> str:
    """A date as its day — "2026-08-01", whether a date, a datetime or an ISO string."""
    return str(value or "")[:10]


def _serial(value) -> str:
    s = re.sub(r"[^0-9A-Z]", "", str(value or "").upper())
    return s[-10:] if s.isdigit() else s


def doc_no(value) -> str:
    """"IS26/   1094" → "IS26/1094": the padding varies with the number's width."""
    return re.sub(r"\s+", "", str(value or "")).upper()


def kind(row) -> str:
    """S(ale) or R(efund)."""
    doc = doc_no(_get(row, "doc_no"))
    if doc.startswith("IR"):
        return "R"
    if doc.startswith("IS"):
        return "S"
    it = str(_get(row, "invoice_type") or "").lower()
    if "credit" in it or "refund" in it:
        return "R"
    total = _number(_get(row, "total_amt"))
    return "R" if total is not None and total < 0 else "S"


def pax_name(row) -> str:
    return _text(_get(row, "pax_name") or " ".join(
        str(p) for p in (_get(row, "last_name"), _get(row, "first_name")) if p))


def booked_date(row) -> str:
    return _day(_get(row, "ticket_date") or _get(row, "doc_date"))


def ticket_key(row) -> str | None:
    """Which ticket this line is — see the module docstring — or None for a line nothing
    names (no Ticket No, no Pax Name), which is never a duplicate. `row` is a dict (an
    uploaded row), a selected result row, or a ticket object."""
    ticket, pax = _serial(_get(row, "ticket_number")), pax_name(row)
    if not ticket and not pax:
        return None
    parts = (booked_date(row), ticket, pax, _amount(_get(row, "total_amt")),
             _day(_get(row, "departure_datetime")), kind(row))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def lock_key(user) -> int:
    """A Postgres advisory-lock key for one user's Internal Statement tickets."""
    raw = hashlib.blake2b(f"internal-tickets:{user.tenant_id}:{user.id}".encode(), digest_size=8).digest()
    return int.from_bytes(raw, "big", signed=True)


# ── where a ticket is already loaded ─────────────────────────────────────────
@dataclass(frozen=True)
class Loaded:
    """The statement a ticket is already loaded in."""
    batch_id: str
    statement_name: str | None
    file_name: str | None
    valid_from: date | None
    valid_to: date | None
    created_at: datetime | None

    def as_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "statement_name": self.statement_name,
            "file_name": self.file_name,
            "period_label": statement_period.label(self.valid_from, self.valid_to),
            "uploaded_at": self.created_at.isoformat() if self.created_at else None,
        }


def _shown(row) -> dict:
    return {
        "doc_no": _get(row, "doc_no"), "ticket_number": _get(row, "ticket_number"),
        "pax_name": _get(row, "pax_name") or pax_name(row) or None,
        "booked_date": booked_date(row) or None,
        "travel_date": _day(_get(row, "departure_datetime")) or None,
        "total_amt": _get(row, "total_amt"),
    }


@dataclass
class Duplicates:
    """A file's ticket lines, split into the ones to save and the duplicates."""
    keys: list[str | None] = field(default_factory=list)   # one per line, in file order
    kept: list[int] = field(default_factory=list)          # positions of the lines to save
    # Each duplicate as shown to the user: its position, and the statement the ticket is
    # already loaded in (`batch_id`).
    lines: list[dict] = field(default_factory=list)
    amount: Decimal = Decimal("0")
    entries: int = 0
    loaded: dict[str, Loaded] = field(default_factory=dict)   # batch_id → statement
    matched: Counter = field(default_factory=Counter)        # batch_id → lines already in it

    @property
    def count(self) -> int:
        return len(self.lines)

    @property
    def new(self) -> int:
        return self.entries - self.count

    @property
    def duplicate_of(self) -> str | None:
        """The statement most of the duplicates are already loaded in."""
        return self.matched.most_common(1)[0][0] if self.matched else None

    def refusal(self) -> str | None:
        """Why this file will not be saved — every line is a duplicate — or None."""
        if not self.entries or self.new:
            return None
        return (f"All {self.entries} tickets of this file are duplicates of tickets already loaded"
                " — there is nothing new to save.")

    def summary(self) -> dict:
        return {
            "total": self.entries,
            "duplicates": self.count,
            "duplicates_amount": format(self.amount.quantize(_CENT, ROUND_HALF_UP), "f"),
            "new": self.new,
            "statements": [{**self.loaded[b].as_dict(), "matched": n}
                           for b, n in self.matched.most_common() if b in self.loaded],
            "lines": self.lines[:MAX_LISTED],
        }

    def preview(self) -> dict:
        reason = self.refusal()
        return {
            **self.summary(),
            # Every duplicate's grid row, so the review grid can mark each one.
            "rows": [{"index": d["index"], "batch_id": d["batch_id"]} for d in self.lines],
            "can_save": reason is None,
            "reason": reason,
        }


def partition(rows: list, keys: list[str | None], loaded: dict[str, Loaded]) -> Duplicates:
    """Split a file's lines: `loaded` is key → the statement a ticket with that key is
    already loaded in (the earliest). A line whose key is loaded is a duplicate; every other
    line is kept — a line repeated within the file included. Pure, so it is tested without a
    DB."""
    out = Duplicates(keys=list(keys))
    for i, (row, key) in enumerate(zip(rows, keys)):
        out.entries += 1
        where = loaded.get(key) if key else None
        if where is None:
            out.kept.append(i)
            continue
        out.lines.append({**_shown(row), "index": i, "batch_id": where.batch_id})
        out.loaded.setdefault(where.batch_id, where)
        out.matched[where.batch_id] += 1
        out.amount += _number(_get(row, "total_amt")) or Decimal("0")
    return out


def _serial_tail(column):
    """`_serial` in SQL, cut to its last ten characters — which saved tickets a file's ticket
    numbers could be. Exact matching is the key's, worked out from the columns read."""
    cleaned = func.regexp_replace(func.upper(func.coalesce(column, "")), "[^0-9A-Z]", "", "g")
    return func.right(cleaned, 10)


async def loaded_keys(db: AsyncSession, user, keys, serials, *, statements, tickets) -> dict[str, Loaded]:
    """key → the statement a ticket with it is already loaded in (the earliest), for the keys
    given. Read: this user's tickets in the section's two tables (`statements` / `tickets`)
    whose stored key is one of `keys`, or whose ticket number is one of `serials` — each then
    answers to its stored key and to the key of its columns as they stand."""
    wanted = {k for k in keys if k}
    if not wanted:
        return {}
    stamped = sorted(wanted)
    tails = sorted({t[-10:] for t in serials if t})
    S, T = statements, tickets
    hits = []
    for n in range(0, max(len(stamped), len(tails)), _CHUNK):
        match = []
        if stamped[n:n + _CHUNK]:
            match.append(T.dedup_key.in_(stamped[n:n + _CHUNK]))
        if tails[n:n + _CHUNK]:
            match.append(_serial_tail(T.ticket_number).in_(tails[n:n + _CHUNK]))
        hits += (await db.execute(
            select(T.id, T.dedup_key, *[getattr(T, c) for c in KEY_COLUMNS],
                   S.batch_id, S.statement_name, S.file_name, S.valid_from, S.valid_to, S.created_at)
            .join(S, (S.batch_id == T.batch_id) & (S.tenant_id == T.tenant_id))
            .where(T.tenant_id == user.tenant_id, T.created_by_id == user.id, or_(*match))
        )).all()
    out: dict[str, Loaded] = {}
    for r in sorted(hits, key=lambda r: (r.created_at or datetime.min, r.id)):
        where = Loaded(r.batch_id, r.statement_name, r.file_name, r.valid_from, r.valid_to, r.created_at)
        for key in (r.dedup_key, ticket_key(r)):
            if key in wanted:
                out.setdefault(key, where)
    return out


async def find(db: AsyncSession, user, rows: list, *, statements, tickets) -> Duplicates:
    """Key every line and split the file against the tickets already loaded."""
    keys = [ticket_key(r) for r in rows]
    serials = [_serial(_get(r, "ticket_number")) for r, k in zip(rows, keys) if k]
    loaded = await loaded_keys(db, user, keys, serials, statements=statements, tickets=tickets)
    return partition(rows, keys, loaded)
