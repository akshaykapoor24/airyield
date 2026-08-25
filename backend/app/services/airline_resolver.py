"""Resolve a deal sheet's airline cell against the `airlines` master.

Supplier sheets name a carrier the way a ticketing desk talks about it, not the
way the master stores it: "Virgin Atlantic (XO SALE)", "AIR INDIA (INTL) (OB/IB
till 31 Mar 2026)", "ETIHAD (T/E/G & GCC SECTOR) LORDS ISSUANCE". The trailing
qualifier says who ISSUES the ticket, not which airline it is, so it must not be
part of the airline's identity — a deal saved as "Virgin Atlantic (XO SALE)" can
never match a ticket, because `deal_matching` joins on
`lower(deals.airline_name) == lower(airlines.name)`.

The one rule that shapes everything here: **resolution is name-first, never
code-first.** The Lords sheet prints, verbatim in its own table,

    ['American Airline', 'AI (1st Apr 2026) (LORDS ISSUANCE)', '2.00%', ...]

— the code cell is wrong in the source document. A code-first resolver (the
precedence `tickets.py` uses) silently renames American Airlines to AIR INDIA and
attaches a 2% AA deal to Air India, and it looks perfectly normal in the review
table. So a code-only match renames only when the two names are demonstrably
compatible; otherwise the row is flagged for the reviewer, never renamed and
never used to create a master row.

The string functions are pure and the DB layer is a thin adapter on purpose —
the same split `pdf_table_rows` uses — so every cleaner is unit-testable with no
database and no network.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airline import Airline
from app.models.airline_approval import AirlineApproval
from app.services.pdf_table_rows import NOISE_RE

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CHANNEL VOCABULARY
# ══════════════════════════════════════════════════════════════════════════════

# One vocabulary, three consumers — parenthesised removal, trailing-bare removal
# and the match key — so they cannot drift apart. Sheets print the same qualifier
# all three ways on the same page.
_CHANNEL = r"""(?:
      x\s*[.\-/]?\s*o(?:\s*(?:sale|sales))?      # XO, X.O, XO SALE, Xo SALES
    | lord'?s?\s*(?:issuance|sale|sales)         # LORDS ISSUANCE, LORD'S SALE
    | (?:self|own|agent)?\s*issuance             # ISSUANCE, SELF ISSUANCE
)"""

# Deletes a parenthetical only when its ENTIRE contents are channel words. That
# is the whole reason this is two passes and not one: "(INTL)", "(S&T CLS )",
# "(PRIVATE FARES )", "(NDC )" and "(Pure AC flts)" are meaningful and become
# structurally impossible to remove.
_PAREN_CHANNEL = re.compile(r"\(\s*(?:" + _CHANNEL + r")\s*[.,]?\s*\)", re.I | re.X)
# The unparenthesised trailing form, which the same sheets also print:
# "ETIHAD (T/E/G & GCC SECTOR) LORDS ISSUANCE".
_TRAIL_CHANNEL = re.compile(r"[\s,\-–]*\b(?:" + _CHANNEL + r")\b\s*[.,]?\s*$", re.I | re.X)
_BARE_CHANNEL = re.compile(r"\b(?:" + _CHANNEL + r")\b", re.I | re.X)

_WS = re.compile(r"\s+")
_SPACE_IN_PARENS = re.compile(r"\(\s+|\s+\)")


def _squeeze(text: str) -> str:
    """Collapse whitespace, tidy "( INTL )" -> "(INTL)", drop dangling separators
    and any parenthesis left empty by a removal."""
    out = re.sub(r"\(\s*\)", " ", text)
    out = _SPACE_IN_PARENS.sub(lambda m: "(" if "(" in m.group() else ")", out)
    return _WS.sub(" ", out).strip(" ,-–;:")


def strip_channel_qualifier(text: str | None) -> str:
    """Remove sales-channel / issuance qualifiers, keep every meaningful one.

    "Virgin Atlantic (XO SALE)"                 -> "Virgin Atlantic"
    "INDIGO ( INTL ) (XO SALE)"                 -> "INDIGO (INTL)"
    "ETIHAD (T/E/G & GCC SECTOR) LORDS ISSUANCE"-> "ETIHAD (T/E/G & GCC SECTOR)"
    "BIMAN BANGLADESH"                          -> unchanged

    This is the DISPLAY name, used only when nothing resolves. When a row does
    resolve, the master's own name replaces it.
    """
    out = _PAREN_CHANNEL.sub(" ", (text or "").replace("\n", " "))
    prev = None
    while prev != out:                      # "(XO SALE) (LORDS ISSUANCE)" stacks
        prev = out
        out = _TRAIL_CHANNEL.sub("", out).rstrip()
    return _squeeze(out)


# ══════════════════════════════════════════════════════════════════════════════
# MATCH KEY  — lookup only. Never displayed, never saved.
# ══════════════════════════════════════════════════════════════════════════════

_ALL_PARENS = re.compile(r"\([^)]*\)")
# Akbar prints "AIR NEWZELAND( SIN/CHC or AKL & V.V" with no closing paren;
# without this the row can never match anything.
_OPEN_PAREN = re.compile(r"\(.*$", re.S)
_NON_KEY = re.compile(r"[^A-Z0-9& ]+")

# Words that name a VARIANT of a carrier's deal rather than a carrier: the sheet
# lists "Etihad" and "Etihad INCENTIVE" as two rows of the same airline.
_MODIFIERS = frozenset({
    "INCENTIVE", "PLB", "ADDITIONAL", "EXTRA", "DEAL", "BONUS",
    "SPECIAL", "SLAB", "PART",
})

# Words carried by so many carrier names that they cannot distinguish two of them.
_GENERIC = frozenset({
    "AIR", "AIRLINE", "AIRLINES", "AIRWAYS", "AIRWAY", "AVIATION", "GROUP",
    "THE", "INTERNATIONAL", "INTL", "CO", "LTD", "COMPANY", "LINES", "CJSC",
    "INC", "S", "ROYAL", "DUTCH",
}) | _MODIFIERS


def airline_match_key(name: str | None) -> str:
    """Normalise a name down to what actually identifies the carrier."""
    s = _ALL_PARENS.sub(" ", (name or "").replace("\n", " "))
    s = _OPEN_PAREN.sub(" ", s)
    s = _BARE_CHANNEL.sub(" ", s)
    s = _WS.sub(" ", _NON_KEY.sub(" ", s.upper())).strip()
    if not s:
        return ""
    # Keep the bare key if stripping modifiers would empty it entirely.
    return " ".join(t for t in s.split() if t not in _MODIFIERS) or s


# ══════════════════════════════════════════════════════════════════════════════
# CODE CELL
# ══════════════════════════════════════════════════════════════════════════════

# 211 of the master's 212 rows are exactly 2 characters; the sole 3-char value is
# the literal string 'NAN'. Rejecting 3-char candidates outright is what stops
# "AIR CANADA (Pure AC flts)" — a NAME that landed in the code column on two
# Lords rows — from yielding the bogus code "AIR".
_CODE_RE = re.compile(r"^[A-Z0-9]{2}$")
_CHANNEL_TAIL = re.compile(r"\b(?:" + _CHANNEL + r")\b.*$", re.I | re.X)


def clean_airline_code(cell: str | None) -> tuple[str | None, bool]:
    """-> (2-char IATA code or None, multi_carrier flag)

    The code is always the FIRST token of the cell; everything after the first
    "(" or the first channel word is annotation:

        "AI (LORDS ISSUANCE)"                 -> ("AI", False)
        "AI (1st Apr 2026) (XO SALE)"         -> ("AI", False)
        "AF/KL/DL (XO SALE)"                  -> ("AF", True)     multi-carrier
        "EY (T/E/G & GCC SECTOR) LORDS ISSU." -> ("EY", False)
        "YY+ ONWARDS AIR CANADA PURE FLT ..." -> (None, False)    junk cell
        ""                                    -> (None, False)
    """
    if not cell:
        return None, False
    head = str(cell).replace("\n", " ").split("(")[0]
    head = _CHANNEL_TAIL.sub("", head).strip(" .,-–&")
    if not head:
        return None, False
    multi = "/" in head
    first = re.split(r"[\s/,]+", head)[0].strip(" .,-–").upper()
    # Needs at least one letter: a bare "26" from a stray date is not a carrier.
    if not _CODE_RE.match(first) or not re.search(r"[A-Z]", first):
        return None, multi
    return first, multi


# An agency IATA number is 7-8 digits — never a carrier designator. The non-AI
# column-mapping path routes the sheet's CODE column into ExtractedRow.iata_code,
# which `confirm_upload` also uses for the agency number, so this guard keeps the
# two apart.
def carrier_code_from_row_field(raw: str | None) -> str | None:
    if not raw or str(raw).strip().isdigit():
        return None
    return clean_airline_code(raw)[0]


# "AF/KL/DL", "AirFrance / KLM / Delta", "LUFTHANSA /SWISS ROW" — one row quoting
# one rate for several carriers.
_MULTI_SEP = re.compile(r"[A-Za-z]\s*/\s*[A-Za-z]")


def _lists_multiple_carriers(name: str | None) -> bool:
    """Multi-carrier detected from the NAME as well as the code cell.

    The code reaches `confirm_upload` already cleaned to a single designator —
    "AF/KL/DL" arrives as "AF" — so the code cell alone cannot tell the two
    stages the same story, and the review table would say "multi-carrier" while
    the save silently renamed the row to Air France. The name survives transport
    intact, so it is the reliable signal.

    Parentheticals are removed first: Akbar's "AIR NEWZELAND( SIN/CHC or AKL"
    names a route, not a second carrier.
    """
    s = _ALL_PARENS.sub(" ", (name or "").replace("\n", " "))
    s = _OPEN_PAREN.sub(" ", s)
    return bool(_MULTI_SEP.search(s))


# ══════════════════════════════════════════════════════════════════════════════
# JUNK GATE
# ══════════════════════════════════════════════════════════════════════════════

_DIGITS = re.compile(r"\d")
_ALPHA_TOKEN = re.compile(r"[A-Za-z]{3,}")


def looks_like_airline_name(name: str | None) -> bool:
    """Never propose a master row for a footer, a phone number or a T&C line.

    Deliberately strict — this gates a write into GLOBAL master data, where a
    false positive is permanent and visible to every tenant. A real airline that
    fails this is merely not auto-created; the reviewer can still add it.
    """
    text = (name or "").strip()
    if not 2 <= len(text) <= 60:
        return False
    if NOISE_RE.search(text):
        return False
    if not _ALPHA_TOKEN.search(text):
        return False
    digits = len(_DIGITS.findall(text))
    return digits / len(text) <= 0.4


# ══════════════════════════════════════════════════════════════════════════════
# COMPATIBILITY GATE — the anti-silent-rename guard
# ══════════════════════════════════════════════════════════════════════════════

# Measured on the real three-PDF corpus against the live master. Accepted pairs
# score 0.80-0.96 (AIR NEWZELAND/AIR NEW ZEALAND 0.96, TAP AIR PORTUAL/TAP
# Portugal 0.95, SPICEJT INTL/SPICEJET 0.93, SCANDAVIAN AIR/SAS SCANDINAVIAN
# AIRLINES 0.80); rejected pairs score 0.23-0.55 (ITA AIRWAYS/ALITALIA 0.55,
# AMERICAN AIRLINE/AIR INDIA 0.43, AVIANCE AIR/AIR EUROPA 0.32). The threshold
# sits in the middle of that empty band, so it is not fragile.
_SIM_THRESHOLD = 0.72


def _core(key: str) -> str:
    """The key with generic carrier words removed, so "FIJI AIR" vs "AIR PACIFIC"
    is not scored on the shared word "AIR"."""
    return " ".join(t for t in key.split() if t not in _GENERIC)


def names_compatible(sheet_key: str, master_key: str) -> bool:
    """Is renaming `sheet_key` to the master's name defensible?"""
    if not sheet_key or not master_key:
        return False
    if sheet_key == master_key:
        return True

    sheet_core, master_core = _core(sheet_key), _core(master_key)
    # Significant-token subset either way: UGANDA ⊆ UGANDA AIRLINES,
    # SCOOT ⊆ SCOOT TIGER AIR.
    s_tokens, m_tokens = set(sheet_core.split()), set(master_core.split())
    if s_tokens and m_tokens and (s_tokens <= m_tokens or m_tokens <= s_tokens):
        return True

    full = SequenceMatcher(None, sheet_key, master_key).ratio()
    core = SequenceMatcher(None, sheet_core, master_core).ratio() if sheet_core and master_core else 0.0
    return max(full, core) >= _SIM_THRESHOLD


# ══════════════════════════════════════════════════════════════════════════════
# RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════

RESOLVED = "resolved"
NEW = "new"
CONFLICT = "conflict"
MULTI_CARRIER = "multi_carrier"
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class AirlineMatch:
    status: str
    airline_id: int | None = None
    canonical_name: str | None = None    # the master's name; only when RESOLVED
    display_name: str = ""               # what to show/save when not resolved
    code: str | None = None              # cleaned 2-char code — transport only
    note: str | None = None              # reviewer-facing sentence

    @property
    def saved_name(self) -> str:
        """What `deals.airline_name` should hold."""
        return self.canonical_name if self.status == RESOLVED and self.canonical_name else self.display_name


@dataclass(frozen=True)
class _MasterRow:
    id: int
    name: str
    iata_code: str
    contract_year: str | None = None


class AirlineIndex:
    """The whole airline master, in memory.

    One `select(Airline)` per request beats `tickets.py`'s IN-list: the master is
    ~212 rows, and holding it all is what makes key-normalised lookup and
    similarity scoring possible at all — neither can be expressed as a WHERE.
    """

    def __init__(self, rows: list[_MasterRow]) -> None:
        self._by_key: dict[str, list[_MasterRow]] = {}
        self._by_code: dict[str, _MasterRow] = {}
        self._cy_by_name: dict[str, str] = {}
        for row in rows:
            self._add(row)

    def _add(self, row: _MasterRow) -> None:
        key = airline_match_key(row.name)
        if key:
            self._by_key.setdefault(key, []).append(row)
        code = (row.iata_code or "").strip().upper()
        if code:
            # First wins — `iata_code` is UNIQUE, so a second one cannot happen
            # against the DB, only against an in-memory adopt().
            self._by_code.setdefault(code, row)
        if row.contract_year:
            self._cy_by_name[(row.name or "").strip().lower()] = row.contract_year

    @classmethod
    def from_rows(cls, rows) -> "AirlineIndex":
        """Build from plain `(id, name, iata_code[, contract_year])` tuples.

        The seam that makes the whole decision matrix testable without a
        database — `load` below is only the DB adapter.
        """
        return cls([_MasterRow(*row) for row in rows])

    @classmethod
    async def load(cls, db: AsyncSession) -> "AirlineIndex":
        result = await db.execute(
            select(Airline.id, Airline.name, Airline.iata_code, Airline.contract_year)
        )
        return cls([
            _MasterRow(id=r.id, name=r.name or "", iata_code=r.iata_code or "",
                       contract_year=r.contract_year)
            for r in result.all()
        ])

    def adopt(self, airline: Airline) -> None:
        """Fold a just-created (or just-discovered) master row in, so the rest of
        the batch resolves against it instead of trying to create it again."""
        self._add(_MasterRow(
            id=airline.id, name=airline.name or "",
            iata_code=airline.iata_code or "", contract_year=airline.contract_year,
        ))

    def contract_year_for(self, name: str | None) -> str | None:
        return self._cy_by_name.get((name or "").strip().lower())

    def _one_carrier(self, part: str) -> _MasterRow | None:
        """Identify a single carrier from one fragment, whichever cell it came
        from — the two columns are transposed on some sheets, so a fragment is
        tried as a code AND as a name."""
        code, _ = clean_airline_code(part)
        if code and code in self._by_code:
            return self._by_code[code]
        key = airline_match_key(part)
        if not key:
            return None
        exact = self._by_key.get(key, [])
        if len(exact) == 1:
            return exact[0]
        if exact:
            return None                                   # ambiguous, don't guess
        # "SWISS AIR" for master "SWISS". Only when exactly one row is
        # compatible — several candidates means we cannot tell them apart.
        near = [rows[0] for k, rows in self._by_key.items()
                if len(rows) == 1 and names_compatible(key, k)]
        return near[0] if len(near) == 1 else None

    def split_carriers(self, raw_name: str | None, raw_code: str | None) -> list[AirlineMatch]:
        """Split one multi-carrier row into one resolved entry per carrier.

        "AirFrance / KLM / Delta" + "AF/KL/DL" is three separate deals at the
        same rate, and storing it as one row named "AirFrance / KLM / Delta"
        makes all three unmatchable against a ticket.

        Fragments are gathered from BOTH cells and de-duplicated by airline id
        rather than zipped positionally, because the two cells do not agree on
        order — Akbar prints the name "AIRFRANCE/KLM/DL" against the code
        "KL/AF/DL", so zipping would file Air France's rate under KLM.

        Returns [] unless EVERY fragment was identified. A partial split would
        silently drop a carrier, which is worse than leaving the row flagged for
        a human: the reviewer can still see all three names in the untouched cell.
        """
        name_parts = _carrier_parts(raw_name)
        code_parts = _carrier_parts(raw_code)
        expected = max(len(name_parts), len(code_parts))
        if expected < 2:
            return []

        # Code fragments first: a designator identifies a carrier unambiguously,
        # so it also gives the most sensible output order.
        found: dict[int, _MasterRow] = {}
        for part in code_parts + name_parts:
            row = self._one_carrier(part)
            if row is not None:
                found.setdefault(row.id, row)

        if len(found) != expected:
            return []
        return [
            AirlineMatch(
                status=RESOLVED, airline_id=row.id, canonical_name=row.name,
                display_name=row.name, code=row.iata_code,
                note=f"Split from a multi-carrier row listing {expected} airlines.",
            )
            for row in found.values()
        ]

    def resolve(self, raw_name: str | None, raw_code: str | None) -> AirlineMatch:
        display = strip_channel_qualifier(raw_name) or (raw_name or "").strip()
        key = airline_match_key(raw_name)
        code, code_multi = clean_airline_code(raw_code)
        # From the name too, so extract-time and confirm-time agree even though
        # the code arrives at confirm already reduced to one designator.
        multi = code_multi or _lists_multiple_carriers(raw_name)

        by_name = self._by_key.get(key, []) if key else []
        by_code = self._by_code.get(code) if code else None

        if len(by_name) > 1:
            # `airlines.name` carries no unique constraint. No collisions exist
            # in the master today, but silently picking one would be a guess.
            return AirlineMatch(
                status=AMBIGUOUS, display_name=display, code=code,
                note=f"{len(by_name)} master airlines are named '{by_name[0].name}' — pick one by hand.",
            )

        if len(by_name) == 1:
            hit = by_name[0]
            if by_code is not None and by_code.id != hit.id:
                return AirlineMatch(
                    status=CONFLICT, airline_id=hit.id, canonical_name=hit.name,
                    display_name=display, code=code,
                    note=(f"The name matches {hit.name} ({hit.iata_code}) but the code cell says "
                          f"{code}, which belongs to {by_code.name} — check the sheet."),
                )
            return AirlineMatch(
                status=RESOLVED, airline_id=hit.id, canonical_name=hit.name,
                display_name=display, code=code or hit.iata_code,
            )

        if by_code is not None:
            if multi:
                return AirlineMatch(
                    status=MULTI_CARRIER, display_name=display, code=code,
                    note=(f"The code cell lists several carriers; '{code}' is {by_code.name}. "
                          "Left as printed — split the row if this is one deal per carrier."),
                )
            if names_compatible(key, airline_match_key(by_code.name)):
                return AirlineMatch(
                    status=RESOLVED, airline_id=by_code.id, canonical_name=by_code.name,
                    display_name=display, code=code,
                )
            return AirlineMatch(
                status=CONFLICT, airline_id=by_code.id, canonical_name=by_code.name,
                display_name=display, code=code,
                note=(f"Code {code} belongs to {by_code.name} in the master, but this row says "
                      f"'{display}' — check the sheet."),
            )

        if code and looks_like_airline_name(display):
            return AirlineMatch(
                status=NEW, display_name=display, code=code,
                note=f"Not in the airline master — will be added as {display} ({code}) when you save.",
            )

        note = ("No airline code on this row, so it cannot be added to the master — "
                "add the code, or pick an existing airline.") if looks_like_airline_name(display) else None
        return AirlineMatch(status=UNRESOLVED, display_name=display, code=code, note=note)


def _carrier_parts(cell: str | None) -> list[str]:
    """The "/"-separated carrier fragments of a cell, with the channel qualifier
    and every parenthetical removed: "(NDC )", "(REST OF WORLD)", "(A++)" qualify
    the deal, they do not name a carrier."""
    s = strip_channel_qualifier(cell)
    s = _OPEN_PAREN.sub(" ", _ALL_PARENS.sub(" ", s))
    return [p for p in (frag.strip(" .,-–&") for frag in s.split("/")) if p]


async def resolve_many(
    db: AsyncSession,
    pairs: list[tuple[str | None, str | None]],
    index: AirlineIndex | None = None,
) -> dict[tuple[str | None, str | None], AirlineMatch]:
    """Read-only bulk resolve. Nothing is written."""
    idx = index or await AirlineIndex.load(db)
    return {pair: idx.resolve(*pair) for pair in set(pairs)}


# ══════════════════════════════════════════════════════════════════════════════
# CREATION — confirm-time only
# ══════════════════════════════════════════════════════════════════════════════

async def resolve_and_create_airlines(
    db: AsyncSession,
    pairs: set[tuple[str | None, str | None]] | list[tuple[str | None, str | None]],
    current_user,
    index: AirlineIndex | None = None,
) -> tuple[dict[tuple[str | None, str | None], AirlineMatch], dict[str, int]]:
    """Resolve every (name, code) pair in a batch and create what is missing.

    Returns (resolutions, summary). Governance is exactly what `POST /airlines/`
    applies: a platform admin writes `airlines` directly, anyone else files an
    `airline_approvals` row for review.

    Transaction discipline is NOT `airlines.py`'s. `bulk_upload_airlines` commits
    per row and rolls back on failure; inside `confirm_upload` that would commit —
    and then discard — a half-built statement -> deals -> incentives graph. So:
    never `crud.airline.create` (it commits, crud/base.py:25), always
    `db.add` + `flush` inside a SAVEPOINT, and let the caller own the one commit.
    """
    from app.dependencies import is_platform_admin

    idx = index or await AirlineIndex.load(db)
    pairs = set(pairs)

    resolutions = {pair: idx.resolve(*pair) for pair in pairs}

    # Creation is keyed on the CLEANED CODE, not on the pair: the Lords sheet's
    # six "AIR INDIA (...)" name variants are one airline, AI.
    to_create: dict[str, str] = {}
    for match in resolutions.values():
        if match.status == NEW and match.code and looks_like_airline_name(match.display_name):
            to_create.setdefault(match.code, match.display_name)

    created = submitted = 0

    if not to_create:
        return resolutions, _summarise(resolutions, created, submitted)

    is_admin = is_platform_admin(current_user)

    # One bulk query rather than airlines.py's per-row SELECT.
    pending: set[str] = set()
    if not is_admin:
        rows = await db.execute(
            select(AirlineApproval.iata_code).where(
                AirlineApproval.iata_code.in_(list(to_create)),
                func.lower(AirlineApproval.status) == "pending",
            )
        )
        pending = {(c or "").upper() for (c,) in rows.all()}

    for code, name in to_create.items():
        if not is_admin and code in pending:
            continue                                  # already asked; don't ask twice
        try:
            # SAVEPOINT: a UNIQUE violation on airlines.iata_code must not poison
            # the outer transaction, which is holding the whole deal batch.
            async with db.begin_nested():
                if is_admin:
                    obj = Airline(name=name, iata_code=code)
                    db.add(obj)
                    await db.flush()
                    idx.adopt(obj)
                    created += 1
                else:
                    db.add(AirlineApproval(
                        name=name, iata_code=code, status="pending",
                        request_type="new", target_airline_id=None,
                        submitted_by_id=current_user.id,
                        tenant_id=current_user.tenant_id,
                    ))
                    await db.flush()
                    submitted += 1
        except IntegrityError:
            # A concurrent upload won the race on the UNIQUE code. The savepoint
            # rolled back; the outer transaction and every deal built so far are
            # intact. Adopt the winner so the rest of the batch resolves to it.
            existing = (await db.execute(
                select(Airline).where(func.upper(Airline.iata_code) == code)
            )).scalar_one_or_none()
            if existing is not None:
                idx.adopt(existing)
            else:
                logger.exception("airline %s (%s) could not be created", code, name)

    # Re-resolve so rows whose airline was just created come back RESOLVED and
    # save under the master's name rather than the sheet's. Rows that only filed
    # an approval stay NEW and save under the sheet's cleaned name — correct,
    # since the master row does not exist until an admin approves it.
    final = {pair: idx.resolve(*pair) for pair in pairs}
    return final, _summarise(final, created, submitted)


def _summarise(resolutions: dict, created: int, submitted: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for match in resolutions.values():
        out[match.status] = out.get(match.status, 0) + 1
    out["created"] = created
    out["submitted"] = submitted
    return out
