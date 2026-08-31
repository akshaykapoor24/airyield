"""Resolve a passenger name to a Customer (and, through them, a Corporate).

An LCC Detailed statement names no customer. Per row it gives a passenger (`name1`)
and nothing else — `name`, `email_address` and `source_agent_code` are the agency's
and identical on every row. So the only way an LCC row can reach Customer/Corporate
billing is by matching that passenger against the Customer master.

Mirrors the ARCHITECTURE of ``services/airline_resolver.py`` — normalisation core →
in-memory index → frozen match dataclass with status constants → ``summarise`` — and
deliberately shares NONE of its vocabulary. That module's ``_GENERIC`` strips
"AIR"/"THE"/"ROYAL"/"CO", its ``_MODIFIERS`` strips "PART"/"SPECIAL"/"EXTRA", and its
``names_compatible`` accepts a significant-token SUBSET, which for people would make a
bare "KUMAR" match any "RAJESH KUMAR". None of it is imported.

Simpler than the airline resolver in one respect: this NEVER creates master rows.
There is no approval path, no IntegrityError race, no ``begin_nested()``. It reads
``customers``/``corporates`` and the caller writes the result onto ``lcc_detailed``.
Transaction rule is the airline resolver's (:526-530): never ``crud.*.create``,
``db.add`` + ``flush``, caller owns the one commit.

WHY EXACT-MATCH-ONLY — see ``_SIM_THRESHOLD`` at the bottom of this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "RESOLVED", "AMBIGUOUS", "INITIALS_ONLY", "UNRESOLVED",
    "DEFAULTED", "OVERRIDDEN", "EXCLUDED",
    "REASON",
    "CustomerMatch", "CustomerIndex", "MasterRow",
    "person_match_key", "split_person_name", "summarise",
]


# ══════════════════════════════════════════════════════════════════════════════
# MATCH KEY — lookup only. Never displayed, never saved.
# ══════════════════════════════════════════════════════════════════════════════

_WS = re.compile(r"\s+")
# An apostrophe is INSIDE a word, so it is deleted rather than turned into a
# separator: "O'BRIEN" must key as OBRIEN, not as O + BRIEN — which would then lose
# the "O" to the initials rule and match the wrong family.
_APOSTROPHE = re.compile(r"[’'`ʼ]")
# Everything else non-alphabetic becomes a separator. Narrower than
# airline_resolver._NON_KEY ([^A-Z0-9& ]+) on purpose: a digit is never part of a
# person's name and neither is "&". Dots separate ("R.D." → R, D as initials) and so
# do hyphens ("SMITH-JONES" → two tokens, which the sorted key reunites).
_NON_KEY = re.compile(r"[^A-Z ]+")

# Honorifics and pax-type codes. Dropped from the key so "MR SACHIN DUBEY" and
# "SACHIN DUBEY" are one person. INF/CHD/ADT are the airline pax-type suffixes.
_TITLES = frozenset({
    "MR", "MRS", "MS", "MISS", "MSTR", "MASTER", "DR", "PROF", "MDM",
    "INF", "INFANT", "CHD", "CHILD", "ADT", "ADULT",
    "SHRI", "SMT", "SRI", "SH",
})

# BSP and some GDS exports glue the honorific to the surname: "SMITHJOHNMR".
# Only strip when at least 3 characters precede it, so "MR" alone survives step 1
# and is handled as a title token instead.
_GLUED_TITLE = re.compile(r"(?<=[A-Z]{3})(MR|MRS|MS|MSTR)$")


def person_match_key(name: str | None) -> tuple[str, frozenset[str]]:
    """Normalise a person's name to a lookup key.

    Returns ``(key, dropped_initials)``. The key is a SORTED token multiset, so word
    order does not matter — that is lossless, not fuzzy, and it is what catches
    "S Shreyas" / "Shreyas S", which appear as two spellings of one passenger in a
    single real statement.

    Single-letter tokens are pulled out into ``dropped_initials`` and never take part
    in the key. See ``CustomerIndex.resolve`` for why they can't be expanded.
    """
    s = (name or "").replace("/", " ").upper()    # GDS "SURNAME/FIRSTNAME"
    s = _WS.sub(" ", _NON_KEY.sub(" ", _APOSTROPHE.sub("", s))).strip()
    if not s:
        return "", frozenset()

    toks = [_GLUED_TITLE.sub("", t) for t in s.split()]
    toks = [t for t in toks if t]

    # Keep the bare tokens if stripping titles would empty the list — same guard as
    # airline_match_key:134. A passenger literally recorded as "MR" is unresolvable
    # either way, but it must not become the empty key and collide with every other
    # blank row.
    stripped = [t for t in toks if t not in _TITLES]
    toks = stripped or toks

    initials = frozenset(t for t in toks if len(t) == 1)
    words = sorted(t for t in toks if len(t) >= 2)
    return " ".join(words), initials


def split_person_name(name: str | None) -> tuple[str | None, str | None]:
    """Best (first_name, last_name) split for a single-field passenger name.

    The projected ticket needs both columns populated so that a row which ends up
    with no party link can still be found by the billing screens' passenger-name
    fallback. Last token is the surname; everything before it is the given name.
    """
    s = _WS.sub(" ", (name or "").replace("/", " ")).strip()
    if not s:
        return None, None
    parts = [p for p in s.split() if p.upper() not in _TITLES] or s.split()
    if len(parts) == 1:
        return parts[0], None
    return " ".join(parts[:-1]), parts[-1]


# ══════════════════════════════════════════════════════════════════════════════
# RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════

RESOLVED = "resolved"            # exactly one master row shares the key
AMBIGUOUS = "ambiguous"          # several do — never guessed
INITIALS_ONLY = "initials_only"  # would match if an initial were expanded
UNRESOLVED = "unresolved"        # no candidate
DEFAULTED = "defaulted"          # took the batch-level fallback party
OVERRIDDEN = "overridden"        # a human picked the party
EXCLUDED = "excluded"            # not a billable row (a payment movement)

# Reason strings are DELIBERATELY IDENTICAL per gap type, following
# services/bsp_commission.py:594-598. The gaps endpoint groups on this column; putting
# the passenger's name in here would turn 108 passengers into 108 groups of one.
# Specifics belong in the grouped response's sample list, not in the reason.
REASON = {
    UNRESOLVED: "No customer in your master has this passenger's name.",
    AMBIGUOUS: "Several customers share this passenger's name — pick one.",
    INITIALS_ONLY: "Only initials were given, so this could be more than one person — confirm it.",
    EXCLUDED: "Payment movement — this row carries no fare, so there is nothing to bill.",
}


@dataclass(frozen=True)
class MasterRow:
    id: int
    first_name: str
    last_name: str | None = None
    corporate_id: int | None = None
    corporate_name: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name or ''}".strip()


@dataclass(frozen=True)
class CustomerMatch:
    status: str
    customer_id: int | None = None
    corporate_id: int | None = None
    customer_type: str | None = None       # 'corporate' | 'direct' — CHECK-valid
    canonical_name: str | None = None      # the master's spelling; only when RESOLVED
    display_name: str = ""                 # the row's own name otherwise
    matched_key: str | None = None
    candidate_ids: tuple[int, ...] = ()
    note: str | None = None

    @property
    def is_billable(self) -> bool:
        return self.status in (RESOLVED, DEFAULTED, OVERRIDDEN)


def _match_from_row(row: MasterRow, status: str, key: str, display: str,
                    note: str | None = None) -> CustomerMatch:
    """A matched customer who belongs to a corporate is an EMPLOYEE.

    corporates.py:524-535 already defines a corporate's tickets as its employees'
    tickets, so resolving a passenger to such a customer has to make the row billable
    to the corporate as well — hence customer_type 'corporate' and both ids carried.
    """
    return CustomerMatch(
        status=status,
        customer_id=row.id,
        corporate_id=row.corporate_id,
        customer_type="corporate" if row.corporate_id else "direct",
        canonical_name=row.full_name,
        display_name=display,
        matched_key=key,
        candidate_ids=(row.id,),
        note=note,
    )


class CustomerIndex:
    """The tenant's Customer master, in memory.

    One SELECT per run. Key-normalised lookup cannot be expressed as a WHERE — the
    same justification as AirlineIndex (:308-313) — and the master is small (a few
    thousand rows at most, ~6 on the dev tenant).
    """

    def __init__(self, rows: list[MasterRow]) -> None:
        self._by_key: dict[str, list[MasterRow]] = {}
        self._by_id: dict[int, MasterRow] = {}
        for row in rows:
            key, _ = person_match_key(row.full_name)
            if key:
                # A list, not a dict: `customers` has NO unique constraint on the
                # name, and duplicates genuinely exist.
                self._by_key.setdefault(key, []).append(row)
            self._by_id[row.id] = row

    def __len__(self) -> int:
        return len(self._by_id)

    @classmethod
    def from_rows(cls, rows) -> "CustomerIndex":
        """Build from plain tuples/MasterRows — the seam that makes the whole
        decision matrix testable without a database. `load` is only the DB adapter."""
        return cls([r if isinstance(r, MasterRow) else MasterRow(*r) for r in rows])

    @classmethod
    async def load(cls, db: AsyncSession, *, tenant_id: int | None, created_by_id: int) -> "CustomerIndex":
        """Load under EXACTLY customers._scope (api/v1/customers.py:52-57).

        Note Customer.tenant_id is nullable while that scope compares equality, so a
        NULL-tenant customer is invisible to its own endpoints. Matching the scope
        exactly is what keeps the resolver and the billing query agreeing about who
        exists — diverging here would resolve a row to a customer whose billing page
        can never show it.
        """
        from app.models.corporate import Corporate
        from app.models.customer import Customer

        result = await db.execute(
            select(
                Customer.id, Customer.first_name, Customer.last_name,
                Customer.corporate_id, Corporate.company,
            )
            .outerjoin(Corporate, Corporate.id == Customer.corporate_id)
            .where(Customer.tenant_id == tenant_id, Customer.created_by_id == created_by_id)
        )
        return cls([MasterRow(*row) for row in result.all()])

    def get(self, customer_id: int) -> MasterRow | None:
        return self._by_id.get(customer_id)

    def resolve(self, raw_name: str | None) -> CustomerMatch:
        display = (raw_name or "").strip()
        key, initials = person_match_key(raw_name)

        if not key:
            return CustomerMatch(status=UNRESOLVED, display_name=display,
                                 note="No usable passenger name on this row.")

        rows = self._by_key.get(key, [])

        # Exact key equality always wins, whatever the token count. A customer
        # recorded as "Shreyas S" also keys to "SHREYAS", so both "S Shreyas" and
        # "Shreyas S" land here rather than in INITIALS_ONLY.
        if len(rows) == 1:
            return _match_from_row(rows[0], RESOLVED, key, display)

        if len(rows) > 1:
            # Never a tie-break. billing_id is a single FK that does not come back,
            # so refusing to attribute is the correct failure and billing the wrong
            # party is not. Same stance as AirlineIndex.resolve:438-444.
            return CustomerMatch(
                status=AMBIGUOUS, display_name=display, matched_key=key,
                candidate_ids=tuple(r.id for r in rows), note=REASON[AMBIGUOUS],
            )

        # Initials are dropped from the key and NEVER expanded. "R D AGGARWAL" keys to
        # "AGGARWAL", which is a strict subset of "AGGARWAL RAJESH" — precisely the
        # subset rule that is wrong to obey for people. Surface it for one-click
        # review instead of guessing.
        if initials:
            tokens = set(key.split())
            candidates = [
                r for k, rs in self._by_key.items()
                if tokens < set(k.split()) for r in rs
            ]
            if len(candidates) == 1:
                return _match_from_row(candidates[0], INITIALS_ONLY, key, display,
                                       note=REASON[INITIALS_ONLY])
            if len(candidates) > 1:
                return CustomerMatch(
                    status=AMBIGUOUS, display_name=display, matched_key=key,
                    candidate_ids=tuple(r.id for r in candidates), note=REASON[AMBIGUOUS],
                )

        return CustomerMatch(status=UNRESOLVED, display_name=display, matched_key=key,
                             note=REASON[UNRESOLVED])


def summarise(matches) -> dict[str, int]:
    """`{status: count}` — same shape as airline_resolver._summarise:605-611.
    Feeds the batch counters and the worklist's bucket chips."""
    out: dict[str, int] = {}
    for m in matches:
        status = m.status if isinstance(m, CustomerMatch) else str(m)
        out[status] = out.get(status, 0) + 1
    return out


# ══════════════════════════════════════════════════════════════════════════════
# WHY THERE IS NO SIMILARITY THRESHOLD
# ══════════════════════════════════════════════════════════════════════════════
#
# airline_resolver._SIM_THRESHOLD = 0.72 was calibrated on 60-character airline names,
# where accepted and rejected pairs are separated by an empty band. For short person
# names that band is FULL. Measured over the 101 distinct normalised keys of one real
# 203-row LCC statement, SequenceMatcher(...).ratio() >= 0.72 yields eight pairs of
# DIFFERENT people:
#
#   0.960  AASHISH KUMAR    / ASHISH KUMAR          (plausibly the same person)
#   0.909  BAJAJ SUNIL      / BALAJ SUNIL
#   0.828  ASHISH KUMAR     / ASHOK BISHT KUMAR
#   0.800  AASHISH KUMAR    / ASHOK BISHT KUMAR
#   0.750  AKSHAY KUMAR     / ASHISH KUMAR          <- unmistakably different
#   0.727  AGGARWAL         / AGGARWAL HARSH        <- the bare-surname trap
#   0.722  ANIL KUMAR MEHTA / ASHWINI KUMAR MISHRA  <- different first AND last name
#   0.720  AASHISH KUMAR    / AKSHAY KUMAR
#
# One statement, eight wrong invoices. No threshold separates them, because the most
# plausible true variant (0.960) does not outrank a clearly wrong pair by enough to
# leave a usable gap. Exact normalised-key equality only.
#
# Left as a documented seam so that changing this is a deliberate one-line decision
# with the evidence attached, not a guess.
_SIM_THRESHOLD = None
