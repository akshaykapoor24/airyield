"""Agency Code — the system's own identifier for an onboarded agency.

NOT `customer_code` and NOT `account_code`. Those two are the user's references to
some OTHER system (their customer list, their ledger) and are free text, optional
and non-unique. The agency code is ours: every agency has one, it is unique within
the user's book, and by default the system issues it.

HOW A CODE IS ISSUED
  Auto (the default)  → the next number in the user's CURRENT PATTERN.
  Manual              → whatever the user typed, normalised and checked for clashes.
                        A manual code that carries a number becomes the current
                        pattern, so the auto codes after it continue from it.

A PATTERN is "prefix + number + suffix", read off a code by `parse`:
  AG-0007     → ("AG-",  7, "",     width 4)
  LT/DEL/105  → ("LT/DEL/", 105, "", width 3)
  B2B-12-M    → ("B2B-", 12, "-M",  width 2)   — the LAST run of digits is the counter
  LORDS       → no pattern (no digits), accepted as a one-off and never continued

The current pattern is the one on the user's most recently created agency whose code
has a counter; with none, it is DEFAULT_PREFIX + 4 digits (AG-0001). The next code is
the highest counter already used in that pattern + 1, padded to the widest width seen
— so a book at AG-9999 rolls to AG-10000 instead of colliding.

A manual code typed in the current pattern but short of its padding ("ag-7" while
the book is on AG-0042) is padded to match ("AG-0007"), so one pattern does not end
up with two spellings of the same number.

ONE CODE PER BRANCH, NOT PER ROW. A vendor branch working both channels is two rows
(see models/agency.py), and they are one agency to the person reading a statement.
So the second channel's row reuses the first row's code, and the only rows allowed
to share a code are siblings — same name, same branch, different channel.
`uq_agencies_user_code_channel` backs that up in the database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agency import Agency

DEFAULT_PREFIX = "AG-"
DEFAULT_WIDTH = 4
MAX_LEN = 30

# Letters, digits and the separators people actually use in codes. Must start with a
# letter or digit, so a stray "-" or "/" typed first is refused rather than kept.
_ALLOWED = re.compile(r"^[A-Z0-9][A-Z0-9\-/_.]*$")
# Last run of digits = the counter. Everything before is prefix, everything after suffix.
_PATTERN = re.compile(r"^(.*?)(\d+)(\D*)$")


@dataclass(frozen=True)
class Pattern:
    prefix: str
    suffix: str
    width: int

    def format(self, n: int) -> str:
        return f"{self.prefix}{n:0{self.width}d}{self.suffix}"

    @property
    def example(self) -> str:
        """How the pattern reads on screen: AG-#### ."""
        return f"{self.prefix}{'#' * self.width}{self.suffix}"


DEFAULT_PATTERN = Pattern(DEFAULT_PREFIX, "", DEFAULT_WIDTH)


def normalise(raw) -> str:
    """Trimmed, upper-cased, inner whitespace removed. '' when blank."""
    if raw is None:
        return ""
    return re.sub(r"\s+", "", str(raw)).upper()


def format_error(code: str, label: str = "Agency", max_len: int = MAX_LEN) -> str | None:
    """Why a (normalised) code cannot be stored, or None."""
    if not code:
        return f"{label} code is empty."
    if len(code) > max_len:
        return f"{label} code can be at most {max_len} characters."
    if not _ALLOWED.match(code):
        return f"{label} code may use letters, digits and - / _ . only, and must start with a letter or digit."
    return None


def parse(code: str) -> tuple[Pattern, int] | None:
    """Split a code into its pattern and counter, or None if it has no digits."""
    m = _PATTERN.match(code or "")
    if not m:
        return None
    prefix, digits, suffix = m.groups()
    return Pattern(prefix, suffix, len(digits)), int(digits)


async def _codes(db: AsyncSession, user_id: int) -> list[tuple[int, str]]:
    """(id, code) for every coded agency of this user, oldest first."""
    rows = await db.execute(
        select(Agency.id, Agency.agency_code)
        .where(Agency.user_id == user_id, Agency.agency_code.is_not(None))
        .order_by(Agency.id)
    )
    return [(i, c) for i, c in rows.all() if c]


def _current_pattern(codes: list[tuple[int, str]], default: Pattern = DEFAULT_PATTERN) -> Pattern:
    """The pattern on the newest code that has a counter, else the default."""
    for _id, code in reversed(codes):
        parsed = parse(code)
        if parsed:
            return parsed[0]
    return default


def _next_in(pattern: Pattern, codes: list[tuple[int, str]]) -> str:
    """Highest counter used in this pattern + 1, at the widest width seen."""
    top, width = 0, pattern.width
    for _id, code in codes:
        parsed = parse(code)
        if not parsed:
            continue
        p, n = parsed
        if p.prefix == pattern.prefix and p.suffix == pattern.suffix:
            top = max(top, n)
            width = max(width, p.width)
    return Pattern(pattern.prefix, pattern.suffix, width).format(top + 1)


async def sibling_code(
    db: AsyncSession, user_id: int, name: str, branch_code: str, exclude_id: int | None = None,
) -> str | None:
    """The code already held by this vendor branch on its other channel, if any."""
    q = select(Agency.agency_code).where(
        Agency.user_id == user_id,
        func.lower(Agency.name) == name.strip().lower(),
        func.lower(Agency.branch_code) == branch_code.strip().lower(),
        Agency.agency_code.is_not(None),
    )
    if exclude_id is not None:
        q = q.where(Agency.id != exclude_id)
    return (await db.execute(q.order_by(Agency.id).limit(1))).scalar()


async def suggest(
    db: AsyncSession, user_id: int, name: str | None = None, branch_code: str | None = None,
) -> tuple[str, Pattern]:
    """What auto mode would issue right now, and the pattern it comes from.

    A branch already onboarded on its other channel gets that row's code back.
    """
    codes = await _codes(db, user_id)
    pattern = _current_pattern(codes)
    if name and branch_code:
        existing = await sibling_code(db, user_id, name, branch_code)
        if existing:
            parsed = parse(existing)
            return existing, parsed[0] if parsed else pattern
    return _next_in(pattern, codes), pattern


class Allocator:
    """Issues codes for a batch without re-reading the table per row.

    Bulk add and XLS upload create many agencies before committing, so asking the
    database for "the next number" each time would hand out the same one twice. The
    allocator reads once and tracks what it has issued.

    Not agency-specific apart from `load`: any book of codes can build one from its
    (id, code) list and a code -> holder-key map, with its own default pattern — see
    services/corporate_code.py.
    """

    def __init__(self, user_id: int, codes: list[tuple[int, str]],
                 holders: dict[str, tuple[str, str]], default: Pattern = DEFAULT_PATTERN,
                 label: str = "agency", max_len: int = MAX_LEN):
        self.user_id = user_id
        self.codes = list(codes)
        # code -> (lower name, lower branch) that holds it
        self.holders = holders
        self.default = default
        self.label = label
        self.max_len = max_len

    @classmethod
    async def load(cls, db: AsyncSession, user_id: int) -> "Allocator":
        rows = await db.execute(
            select(Agency.agency_code, Agency.name, Agency.branch_code)
            .where(Agency.user_id == user_id, Agency.agency_code.is_not(None))
        )
        holders = {c: (n.lower(), (b or "").lower()) for c, n, b in rows.all() if c}
        return cls(user_id, await _codes(db, user_id), holders)

    def _record(self, code: str, key: tuple[str, str]) -> str:
        self.codes.append((10**12 + len(self.codes), code))   # newest
        self.holders.setdefault(code, key)
        return code

    def resolve(self, raw, name: str, branch_code: str) -> str:
        """The code for this agency: `raw` if given (validated), else the next one.

        Raises ValueError with a user-facing message on a bad or clashing code.
        """
        key = (name.strip().lower(), branch_code.strip().lower())
        manual = normalise(raw)

        if not manual:
            for code, holder in self.holders.items():
                if holder == key:
                    return code           # other channel of a branch already coded
            return self._record(_next_in(_current_pattern(self.codes, self.default), self.codes), key)

        problem = format_error(manual, self.label.capitalize(), self.max_len)
        if problem:
            raise ValueError(problem)
        manual = self._pad_to_current(manual)
        holder = self.holders.get(manual)
        if holder is not None and holder != key:
            raise ValueError(f"{self.label.capitalize()} code {manual} is already used by another {self.label}.")
        return self._record(manual, key)

    def _pad_to_current(self, code: str) -> str:
        parsed = parse(code)
        if not parsed:
            return code
        p, n = parsed
        cur = _current_pattern(self.codes, self.default)
        if p.prefix == cur.prefix and p.suffix == cur.suffix and p.width < cur.width:
            return cur.format(n)
        return code


def code_resolver(agencies: list[Agency]):
    """Resolve an XLS AGENCY_CODE cell (+ optional channel) to one of these agencies.

    The code names a BRANCH, and a branch on both channels is two rows sharing it,
    so the channel settles which row; without one, a shared code is reported rather
    than guessed. Returns (agency, "") or (None, why).
    """
    by_code: dict[str, list[Agency]] = {}
    for a in agencies:
        if a.agency_code:
            by_code.setdefault(a.agency_code.upper(), []).append(a)

    def resolve(code_raw: str, channel: str | None) -> tuple[Agency | None, str]:
        code = normalise(code_raw)
        matches = by_code.get(code, [])
        if not matches:
            return None, f"agency code '{code}' not found in your agencies — skipped."
        if len(matches) > 1 and channel:
            matches = [m for m in matches if m.channels in (channel, "BOTH")] or matches
        if len(matches) == 1:
            return matches[0], ""
        return None, (
            f"agency code '{code}' is onboarded on both channels — "
            f"set the channel on this row to say which."
        )

    return resolve
