"""Money, date and ticket-number normalisation for the report pipeline.

Every source in Vendors → Statements stores its values its own way: BSP has typed Decimal
columns, TGQ / NDC / Third Party keep verbatim strings in JSONB, and each vendor prints
dates, negatives and ticket numbers differently. The Combined sheet can only total, filter
and link rows if all of them go through ONE set of rules, so those rules live here and
nowhere else. Everything is pure; ``date_key_sql`` builds (but never runs) a SQL expression.

Three decisions a reader should know before editing:

1. **Blank is not zero, junk is not blank.** ``parse_money`` returns None for both a blank
   cell and an unreadable one; ``parse_money_checked`` tells them apart so a mapper can flag
   ``AMOUNT_UNPARSEABLE`` for "abc" without flagging every "N/A" or "-" placeholder.
2. **The period filter runs in SQL and in Python and they must agree.** The upload listing
   counts rows per period inside Postgres (``date_key_sql``) while the builder reads each row
   in Python (``parse_report_date``). Both are generated from the one ``DATE_PATTERNS`` table,
   use only regex syntax that means the same in Python ``re`` and Postgres AREs (``[0-9]``,
   ``[A-Za-z]``, no backslashes), trim the same characters and validate the calendar exactly.
   A row can therefore never be counted in the listing and then dropped by the build, or the
   reverse. ``test_report_download_normalize`` runs the SQL on a real database to prove it
   (``REPORT_DB_TESTS=1``).
3. **Ticket keys keep leading zeros.** ``bsp_reconciliation.norm_tn`` strips them (it joins
   BSP to internal tickets, where that is harmless), but ``098 0123456789`` and
   ``098 123456789`` are different documents for linking. ``doc_key`` normalises every printed
   form onto (3-digit accounting code, 10-digit serial) without dropping a significant digit.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional, Union

from sqlalchemy import ARRAY, Date, Integer, Text, case, cast, func, literal, type_coerce
from sqlalchemy.sql.elements import ColumnElement, UnaryExpression
from sqlalchemy.sql.operators import custom_op

from app.services.report_download import columns as C
from app.services.report_download.types import DocKey

__all__ = [
    "DATE_PATTERNS", "DatePattern",
    "clean_text", "join_unique", "zfill3",
    "parse_money", "parse_money_checked", "signed", "magnitude", "D", "dsum",
    "parse_report_date", "date_key_py", "date_key_sql",
    "doc_key", "doc_keys", "pack", "ticket13",
    "canon_bsp_txn", "stat_segment",
]


# ── text ─────────────────────────────────────────────────────────────────────

# What pandas / str() make of an empty cell. Exact spellings on purpose: an upper-case NONE
# or NAN can be a real code or a passenger's name.
_NULL_TEXTS = frozenset({"nan", "NaN", "None", "NaT"})


def clean_text(v: Any) -> Optional[str]:
    """``str(v).strip()``, or None for None / blank / a stringified NaN or None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in _NULL_TEXTS:
        return None
    return s


def join_unique(values: Optional[Iterable[Any]], sep: str = "/") -> Optional[str]:
    """Ordered-unique join of the non-blank values: ``['L', 'L', 'U']`` → ``'L/U'``."""
    if values is None:
        return None
    out: list[str] = []
    for v in values:
        s = clean_text(v)
        if s is not None and s not in out:
            out.append(s)
    return sep.join(out) if out else None


_ASCII_INT_RE = re.compile(r"[0-9]+")
# A numeric Excel cell read through pandas arrives as "98.0".
_WHOLE_FLOAT_RE = re.compile(r"([0-9]+)\.0+")


def zfill3(code: Any) -> Optional[str]:
    """Airline accounting code → 3 digits (``"98"`` → ``"098"``); letters upper-cased."""
    s = clean_text(code)
    if s is None:
        return None
    m = _WHOLE_FLOAT_RE.fullmatch(s)
    if m:
        s = m.group(1)
    if _ASCII_INT_RE.fullmatch(s):
        return s.zfill(3)
    return s.upper()


# ── money ────────────────────────────────────────────────────────────────────

# Cells that mean "no amount" rather than "an amount we could not read".
_MONEY_PLACEHOLDERS = frozenset({
    "", "-", "--", "\N{EM DASH}", "\N{EN DASH}", "N/A", "NA", "NIL", "NULL", "NONE", "NAN",
})
# Currency symbols and every kind of space carry no sign or magnitude.
_MONEY_NOISE_RE = re.compile("[\\s\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}₹$€£]")
_MONEY_PREFIX_RE = re.compile(r"^(?:RS\.?|INR)")
_PLAIN_NUMBER_RE = re.compile(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+")
# Thousands separators must sit where a real grouping puts them — Western 1,234,567 or
# Indian 12,34,567. Anything else ("12,34" or "1.234,56") is a European decimal comma or a
# typo, and stripping the commas would silently multiply the amount by 100.
_GROUPED_INT_RE = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}")


def parse_money_checked(v: Any) -> tuple[Optional[Decimal], bool]:
    """``(amount, unparseable)``.

    ``unparseable`` is True only when the value is neither a number nor a blank placeholder —
    the case a mapper flags ``AMOUNT_UNPARSEABLE`` for.
    """
    if v is None or isinstance(v, bool):
        return None, False
    if isinstance(v, int):
        return Decimal(v), False
    if isinstance(v, float):
        if v != v:                     # NaN is how pandas spells an empty cell
            return None, False
        v = Decimal(str(v))
    if isinstance(v, Decimal):
        return (_no_negative_zero(v), False) if v.is_finite() else (None, True)

    s = _MONEY_NOISE_RE.sub("", str(v)).replace("\N{MINUS SIGN}", "-").upper()
    if s in _MONEY_PLACEHOLDERS:
        return None, False
    s = _MONEY_PREFIX_RE.sub("", s)

    # Exactly one sign convention per cell. "(500) CR" or "-100-" is not a stronger
    # negative, it is a cell nobody can read with confidence.
    markers, negative = 0, False
    if s.startswith("(") and s.endswith(")"):
        s, markers, negative = s[1:-1], markers + 1, True
    if s.endswith("CR"):
        # Report convention: + the agency owes / is charged, − the agency is credited.
        s, markers, negative = s[:-2], markers + 1, True
    elif s.endswith("DR"):
        s, markers = s[:-2], markers + 1
    if s.endswith("-"):
        s, markers, negative = s[:-1], markers + 1, True
    if s.startswith("-"):
        s, markers, negative = s[1:], markers + 1, True
    elif s.startswith("+"):
        s, markers = s[1:], markers + 1
    if markers > 1 or not s:
        return None, True

    int_part, dot, frac = s.partition(".")
    if "," in int_part:
        if not _GROUPED_INT_RE.fullmatch(int_part):
            return None, True
        int_part = int_part.replace(",", "")
    s = f"{int_part}{dot}{frac}"
    if not _PLAIN_NUMBER_RE.fullmatch(s):
        return None, True
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None, True
    return _no_negative_zero(-d if negative else d), False


def parse_money(v: Any) -> Optional[Decimal]:
    """Any stored amount → Decimal, or None when blank or unreadable.

    Decimal / int pass through, a float goes via ``str`` (so 0.1 stays 0.1), and text may
    carry thousands separators (Western or Indian grouping), ₹ / $ / € / £ / Rs / INR,
    ``(285.72)``, ``100-``, a leading sign, or a ``CR`` (credit → negative) / ``DR`` suffix.
    """
    return parse_money_checked(v)[0]


def _no_negative_zero(d: Decimal) -> Decimal:
    return d.copy_abs() if d.is_zero() else d


def D(v: Any) -> Optional[Decimal]:
    """An already-numeric DB value (Decimal / float / int / None) → Decimal. The short name
    keeps mapper arithmetic on typed columns readable; text follows ``parse_money``."""
    return parse_money(v)


def dsum(*vals: Any) -> Optional[Decimal]:
    """Sum of the non-None values, or None when every value is None — a missing component
    must not turn into a printed 0.00. Text is read with ``parse_money``, so a caller that
    has to flag unreadable text parses it first."""
    total: Optional[Decimal] = None
    for v in vals:
        d = D(v)
        if d is not None:
            total = d if total is None else total + d
    return total


def signed(v: Optional[Decimal], canon: str) -> Optional[Decimal]:
    """Apply ``columns.TYPE_SIGN`` for TYPE_SIGNED sources: +1 → |v|, −1 → −|v|; a type
    whose sign is "as stored" (or that the table does not know) keeps v unchanged."""
    d = D(v)
    if d is None:
        return None
    sign = C.TYPE_SIGN.get(canon)
    if sign is None:
        return d
    return _no_negative_zero(abs(d) if sign > 0 else -abs(d))


def magnitude(v: Optional[Decimal]) -> Optional[Decimal]:
    d = D(v)
    return None if d is None else abs(d)


# ── dates ────────────────────────────────────────────────────────────────────

# A pattern part is literal regex text or a (component, regex) capture. Components:
# Y4 / Y2 year (Y2 means 2000 + yy), M numeric month, MON month name (its first three
# letters), D day, N Excel serial.
_Part = Union[str, tuple[str, str]]
_MONTH_NAMES = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_MONTH_NUMBER = {m: i for i, m in enumerate(_MONTH_NAMES, start=1)}
_EXCEL_EPOCH = date(1899, 12, 30)     # Excel's day 0 once its phantom 29-Feb-1900 is absorbed
# Trimmed from both ends by BOTH implementations (Python str.strip(chars) / Postgres btrim).
_DATE_TRIM = " \t\n\r\N{NO-BREAK SPACE}"


@dataclass(frozen=True)
class DatePattern:
    """One accepted date layout, written once and rendered for both engines."""
    name: str
    example: str
    parts: tuple[_Part, ...]

    @property
    def components(self) -> tuple[str, ...]:
        return tuple(p[0] for p in self.parts if isinstance(p, tuple))

    @property
    def regex(self) -> str:
        """Anchor-free body with every component captured, identical in Python and SQL."""
        return "".join(p if isinstance(p, str) else f"({p[1]})" for p in self.parts)


_D = ("D", "[0-9]{1,2}")
_M = ("M", "[0-9]{1,2}")
_MON = ("MON", "[A-Za-z]{3}")
_Y4 = ("Y4", "[0-9]{4}")
_Y2 = ("Y2", "[0-9]{2}")
_TIME = "(?: .*)?"      # a time (or anything) after a space is ignored

#: The only date layouts the report reads. Day-first throughout: every supplier in scope is
#: Indian, and ``flat_statement`` / ``lcc_detailed_spec`` read dates day-first for the same
#: reason. The layouts are mutually exclusive (a test proves it), so their order is chosen
#: for speed — the most common shapes first — and never changes a result. A string that
#: matches a layout but is not a real calendar date is None.
DATE_PATTERNS: tuple[DatePattern, ...] = (
    # ISO, also what a typed Date / Timestamp column casts to.
    DatePattern("iso", "2026-07-01 00:00:00",
                (_Y4, "[-/]", ("M", "[0-9]{2}"), "[-/]", ("D", "[0-9]{2}"), "(?:[ T].*)?")),
    # TGQ HMPR's Ticket_Date.
    DatePattern("ddmonyy", "23APR26", (_D, _MON, _Y2)),
    DatePattern("ddmonyyyy", "23APR2026", (_D, _MON, _Y4)),
    DatePattern("d_mon_y", "01-Jul-2026 10:30", (_D, "[ /-]", _MON, "[A-Za-z]*[ /,-]*", _Y4, _TIME)),
    # The optional time is Air India Express's "01 Sep 26 13:41:15" (lcc_detailed_spec).
    DatePattern("d_mon_yy", "15-Aug-26", (_D, "[ /-]", _MON, "[A-Za-z]*[ /-]+", _Y2, _TIME)),
    DatePattern("dmy_num", "01/07/2026", (_D, "[/.-]", _M, "[/.-]", _Y4, _TIME)),
    DatePattern("dmy_num2", "01/07/26", (_D, "[/.-]", _M, "[/.-]", _Y2)),
    DatePattern("mon_d_y", "Jul 01, 2026", (_MON, "[A-Za-z]* +", _D, ",? +", _Y4, _TIME)),
    # A date cell read as a number. The range 20000-80000 (1954-10-03 … 2119-01-12) lives in
    # the regex itself so SQL needs no second look at the value; anything else is not a date.
    DatePattern("excel_serial", "46204", (("N", "[2-7][0-9]{4}|80000"), "(?:[.]0+)?")),
)

# A quote or backslash would change meaning between drivers and standard_conforming_strings
# settings when a statement is rendered with literal binds.
assert not any("'" in p.regex or "\\" in p.regex for p in DATE_PATTERNS)

# DOTALL because a Postgres ARE "." also matches a newline.
_PY_DATE_RX = tuple((p, re.compile(p.regex, re.DOTALL)) for p in DATE_PATTERNS)

# Exact Gregorian validity of an assembled "YYYY-M-D" (month and day with or without a
# leading zero), years 0001-9999 — the same dates Python's ``date`` accepts. Written as a
# regex so Postgres can reject 31-04 or 29-02-2026 without calling a date function that would
# raise and abort the whole listing query. A unit test checks it against ``date`` exhaustively.
_DAY_31 = "0?[1-9]|[12][0-9]|3[01]"
_DAY_30 = "0?[1-9]|[12][0-9]|30"
_DAY_28 = "0?[1-9]|1[0-9]|2[0-8]"
_LEAP_YEAR = "[0-9]{2}(?:0[48]|[2468][048]|[13579][26])|(?:[02468][048]|[13579][26])00"


def _calendar_regex(months_31: str, months_30: str, february: str) -> str:
    return (
        "^((?!0000)(?:[0-9]{4}-(?:"
        f"(?:{months_31})-(?:{_DAY_31})|(?:{months_30})-(?:{_DAY_30})|(?:{february})-(?:{_DAY_28}))"
        f"|(?:{_LEAP_YEAR})-(?:{february})-29))$"
    )


_VALID_YMD_NUMERIC = _calendar_regex("0?[13578]|1[02]", "0?[469]|11", "0?2")
_VALID_YMD_NAMED = _calendar_regex("JAN|MAR|MAY|JUL|AUG|OCT|DEC", "APR|JUN|SEP|NOV", "FEB")


def _date_from_match(pat: DatePattern, m: re.Match) -> Optional[date]:
    got = dict(zip(pat.components, m.groups()))
    if "N" in got:
        return _EXCEL_EPOCH + timedelta(days=int(got["N"]))
    year = int(got["Y4"]) if "Y4" in got else 2000 + int(got["Y2"])
    month = int(got["M"]) if "M" in got else _MONTH_NUMBER.get(got["MON"].upper())
    if month is None:
        return None
    try:
        return date(year, month, int(got["D"]))
    except ValueError:       # 31-04, 29-02 in a common year, year 0 …
        return None


def parse_report_date(v: Any) -> Optional[date]:
    """A stored date value → ``date``, or None when it is not one of ``DATE_PATTERNS``.

    ``date`` / ``datetime`` objects pass through (a datetime keeps its calendar date, no
    time-zone conversion). Everything else — numbers included — is read as text.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip(_DATE_TRIM)
    if not s:
        return None
    for pat, rx in _PY_DATE_RX:
        m = rx.fullmatch(s)
        if m:
            return _date_from_match(pat, m)
    return None


def date_key_py(v: Any) -> Optional[str]:
    """``'YYYY-MM-DD'`` for a readable date, else None — the Python twin of ``date_key_sql``."""
    d = parse_report_date(v)
    return d.isoformat() if d is not None else None


def _txt(value: str) -> ColumnElement:
    return literal(value, Text)


def _sql_arm(pat: DatePattern, s: ColumnElement, anchored: ColumnElement) -> ColumnElement:
    """'YYYY-MM-DD' or NULL for a trimmed string ALREADY KNOWN to match ``pat``.

    Postgres has no common-subexpression elimination, so every reference to an extracted
    component would re-run the regex. The arm therefore runs ``regexp_match`` exactly once
    and threads its result through single-use calls: ``format(…, VARIADIC captures)``
    reorders the captures into year-month-day, a ``substring`` against the calendar regex
    turns an impossible date into NULL, and only that validated text reaches ``to_date``.
    """
    captures = UnaryExpression(
        func.regexp_match(s, anchored, type_=ARRAY(Text)),
        operator=custom_op("VARIADIC"), type_=ARRAY(Text),
    )
    position = {c: i for i, c in enumerate(pat.components, start=1)}
    if "N" in position:
        serial = cast(func.array_to_string(captures.element, _txt("")), Integer)
        epoch = func.make_date(_EXCEL_EPOCH.year, _EXCEL_EPOCH.month, _EXCEL_EPOCH.day, type_=Date)
        return func.to_char(epoch + serial, _txt("YYYY-MM-DD"))

    year = f"%{position['Y4']}$s" if "Y4" in position else f"20%{position['Y2']}$s"
    named = "MON" in position
    month = f"%{position['MON' if named else 'M']}$s"
    assembled = func.format(_txt(f"{year}-{month}-%{position['D']}$s"), captures)
    if named:
        assembled, valid, layout = func.upper(assembled), _VALID_YMD_NAMED, "YYYY-MON-DD"
    else:
        valid, layout = _VALID_YMD_NUMERIC, "YYYY-MM-DD"
    checked = func.substring(assembled, _txt(valid))
    return func.to_char(func.to_date(checked, _txt(layout)), _txt("YYYY-MM-DD"))


def date_key_sql(expr: Any) -> ColumnElement:
    """Postgres expression: ``'YYYY-MM-DD'`` text or NULL, for the same inputs and with the
    same result as ``date_key_py``.

    ``expr`` may be any column or expression; it is cast to text first, so a JSONB ``->>``
    value, a Text column and a typed Date / Timestamp column (which casts to ISO text) all
    work. The result compares correctly with ISO strings (``BETWEEN '2026-07-01' AND …``).
    It never raises on bad text and validates the calendar exactly, so no Python re-filter
    is needed. Cost is one regex test per layout tried plus two regex runs on the layout that
    matches (a few microseconds a row).
    """
    s = func.btrim(cast(expr, Text), _txt(_DATE_TRIM))
    whens = []
    for pat in DATE_PATTERNS:
        anchored = _txt(f"^{pat.regex}$")
        whens.append((s.op("~")(anchored), _sql_arm(pat, s, anchored)))
    return type_coerce(case(*whens), Text)


# ── ticket / document numbers ────────────────────────────────────────────────

# 13 digits with an optional separator after the code and an optional printed check digit:
# "0985805708071", "098 5805708071", "098-5805708071-3".
_TICKET_3_10_RE = re.compile(r"([0-9]{3})[\s-]?([0-9]{10})(?:[\s-][0-9])?", re.ASCII)
# A code-prefixed conjunction: "0985800920932-933". A one-digit tail after a single
# separator is the check-digit form above, which is tried first.
_PREFIXED_CONJ_RE = re.compile(r"([0-9]{3})[\s-]?([0-9]{10})\s*-\s*([0-9]{1,3})", re.ASCII)
# "5800920932-933": one line, several consecutive documents.
_CONJ_RE = re.compile(r"([0-9]{9,11})\s*-\s*([0-9]{1,3})", re.ASCII)
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")


def _expand(head: str, tail: str) -> list[str]:
    # Imported lazily: bsp_tgq_enrichment pulls in the ORM models, and its report-mode code
    # may itself come to use this module — a top-level import would make that circular.
    from app.services.bsp_tgq_enrichment import expand_conjunction
    return expand_conjunction(f"{head}-{tail}")


def _digits_key(code: Any, d: str) -> Optional[DocKey]:
    """An all-digit document number, by length."""
    n = len(d)
    if n == 10:
        return DocKey(zfill3(code), d)
    if n == 9:
        return DocKey(zfill3(code), d.zfill(10))
    if n in (11, 12):
        # A 13-digit ticket whose leading zero(s) Excel dropped ("985805708071" for 098…).
        # A declared code that disagrees with the surviving prefix wins: one or two digits
        # are too little to trust over the column the file names.
        inferred, given = zfill3(d[:-10]), zfill3(code)
        if given is not None and given != inferred:
            return DocKey(given, d[-10:])
        return DocKey(inferred, d[-10:])
    if n == 13:
        return DocKey(d[:3], d[3:])
    if n == 14:
        return DocKey(d[:3], d[3:13])   # 13 digits + check digit
    return None


def _clean_doc(raw: Any) -> Optional[str]:
    s = clean_text(raw)
    if s is None:
        return None
    m = _WHOLE_FLOAT_RE.fullmatch(s)       # a ticket number read from a numeric Excel cell
    return (m.group(1) if m else s).upper()


def _conjunction_keys(code: Any, s: str) -> Optional[list[DocKey]]:
    """Every document of a conjunction, or None when ``s`` is not one.

    ``expand_conjunction`` fails closed on an implausible range (tail below head, span over
    15); the head is still a real printed document, so it alone is returned then.
    """
    m = _PREFIXED_CONJ_RE.fullmatch(s)
    if m:
        prefix, head, tail = m.groups()
        return [DocKey(prefix, serial) for serial in (_expand(head, tail) or [head])]
    m = _CONJ_RE.fullmatch(s)
    if m:
        head, tail = m.groups()
        keys = (_digits_key(code, serial) for serial in (_expand(head, tail) or [head]))
        return [k for k in keys if k is not None]
    return None


def doc_key(code: Any, raw: Any) -> Optional[DocKey]:
    """Any printed ticket / document number → ``DocKey``, or None when there is none.

    Structured forms come before the digits-only rule, because a check digit or conjunction
    tail would otherwise be read as part of the serial. A conjunction yields its FIRST
    document, so ``doc_key(c, x) == doc_keys(c, x)[0]`` whenever either is non-empty.
    """
    s = _clean_doc(raw)
    if s is None:
        return None
    m = _TICKET_3_10_RE.fullmatch(s)
    if m:
        return DocKey(m.group(1), m.group(2))
    keys = _conjunction_keys(code, s)
    if keys is not None:
        return keys[0] if keys else None
    if _ASCII_INT_RE.fullmatch(s):
        return _digits_key(code, s)
    if any("A" <= ch <= "Z" for ch in s):
        return DocKey(zfill3(code), _NON_ALNUM_RE.sub("", s))
    return None


def doc_keys(code: Any, raw: Any) -> list[DocKey]:
    """Like ``doc_key``, but a conjunction expands to every document it covers."""
    s = _clean_doc(raw)
    if s is None:
        return []
    if _TICKET_3_10_RE.fullmatch(s) is None:
        keys = _conjunction_keys(code, s)
        if keys is not None:
            return list(dict.fromkeys(keys))
    key = doc_key(code, raw)
    return [key] if key is not None else []


def pack(key: DocKey) -> Union[int, str]:
    """Compact, collision-free hashable form of a key for the in-memory indexes.

    A numeric key (code below 1000, serial of at most 10 digits) becomes one int — far
    smaller than a tuple of strings at 750k rows. Everything else is ``"code|serial"``, and a
    codeless key is ``"|serial"`` so it can never collide with a coded one.
    """
    code, serial = key.code, key.serial
    if code is None:
        return f"|{serial}"
    if (_ASCII_INT_RE.fullmatch(code) and _ASCII_INT_RE.fullmatch(serial)
            and int(code) < 1000 and len(serial) <= 10):
        return int(code) * 10**10 + int(serial)
    return f"{code}|{serial}"


def ticket13(code: Any, raw: Any) -> tuple[Optional[str], bool]:
    """``(13-digit ticket, nonstandard)`` for the Combined ``Ticket Number`` column.

    A clean 3+10 form — 13 digits, ``098 5805708071``, ``098-5805708071-3``, or a 10-digit
    serial with a 3-digit code — gives ``(code+serial, False)``. A 9-digit serial is
    zero-filled and flagged. Anything else (conjunctions, lost leading zeros, alphanumeric
    memo numbers) is shown as printed and flagged: a reconstructed number the source never
    printed must not look authoritative.
    """
    s = _clean_doc(raw)
    if s is None:
        return None, False
    m = _TICKET_3_10_RE.fullmatch(s)
    if m:
        return m.group(1) + m.group(2), False
    if _ASCII_INT_RE.fullmatch(s) and len(s) in (9, 10):
        c = zfill3(code)
        if c is not None and len(c) == 3 and _ASCII_INT_RE.fullmatch(c):
            return c + s.zfill(10), len(s) == 9
    return clean_text(raw), True


# ── transaction types / segments ─────────────────────────────────────────────

# BSP TRNC codes from the tuned parser (bsp_pdf_parser._TRNC_CODES) and the fallback
# parser's mapped forms (bsp_pdf_parser._TRNC_MAP: ADM / ACM / EMD / EXCH).
_BSP_CODES: dict[str, str] = {
    "TKTT": C.SALE, "EXCH": C.EXCHANGE,
    "RFND": C.REFUND, "RFDA": C.REFUND,
    "EMDS": C.EMD, "EMDA": C.EMD, "EMDT": C.EMD, "EMD": C.EMD,
    "ADMA": C.ADM, "ADMD": C.ADM, "ADM": C.ADM, "SPDR": C.ADM,
    "ACMA": C.ACM, "ACMD": C.ACM, "ACM": C.ACM, "SPCR": C.ACM,
    "CANX": C.CANCELLATION, "CANN": C.CANCELLATION,
    "VOID": C.VOID, "TASF": C.AGENT_FEE,
}

# Legacy Excel/CSV free text (bsp_extraction.py lower-cases it and cuts it at 10 chars), in
# precedence order. A legacy statement carries only gross / commission / adm / acm / refund /
# net_due, so a line naming nothing recognisable is a sale.
_LEGACY_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("REFUND", "RFND", "RFD"), C.REFUND),
    (("ADM", "DEBIT M"), C.ADM),
    (("ACM", "CREDIT M"), C.ACM),
    (("VOID",), C.VOID),
    (("CANX", "CANN", "CANCEL"), C.CANCELLATION),
    (("EXCH", "REISS"), C.EXCHANGE),
    (("EMD",), C.EMD),
)


def _has_exchange(associated_docs: Any) -> bool:
    docs = associated_docs
    if isinstance(docs, str):       # JSONB read through a raw text() query arrives as text
        try:
            docs = json.loads(docs)
        except ValueError:
            return False
    if not isinstance(docs, dict):
        return False
    exchanges = docs.get("exchanges")
    if not isinstance(exchanges, list):
        return False
    return any((e.get("doc") if isinstance(e, dict) else e) for e in exchanges)


def canon_bsp_txn(transaction_type: Any, associated_docs: Any) -> tuple[str, bool]:
    """``(canonical type, legacy)`` for a BSP detailed row.

    A TKTT that printed an ``+RTDN`` exchange line is a reissue, so it is EXCHANGE (the
    parser records every ``+RTDN`` under ``associated_docs.exchanges``). ``legacy`` is True
    for the Excel/CSV import's lower-cased free text, which the PDF parsers never produce;
    the mapper flags those rows ``LEGACY_BSP_EXCEL``. A blank type is UNKNOWN and not legacy —
    a legacy statement is recognisable from its missing fare / tax columns instead.
    """
    raw = clean_text(transaction_type)
    if raw is None:
        return C.UNKNOWN, False
    upper = raw.upper()
    legacy = raw != upper
    canon = _BSP_CODES.get(upper)
    if canon is None:
        if not legacy:
            return C.UNKNOWN, False
        canon = next((c for words, c in _LEGACY_KEYWORDS if any(w in upper for w in words)), C.SALE)
    if canon == C.SALE and _has_exchange(associated_docs):
        canon = C.EXCHANGE
    return canon, legacy


_STAT_RE = re.compile(r"([ID])[0-9]*")
_SEGMENT_WORDS = {
    "INTERNATIONAL": "International", "INTL": "International", "INT": "International",
    "DOMESTIC": "Domestic", "DOM": "Domestic",
}


def stat_segment(stat: Any) -> Optional[str]:
    """BSP STAT → ``International`` / ``Domestic``; other text upper-cased; blank → None.

    Amended rows print a suffix (``I71``), so the leading letter decides — the reading of
    ``bsp_commission.stat_to_segment``, except that the report keeps an unrecognised value
    instead of dropping it, so nothing silently disappears from the column.
    """
    s = clean_text(stat)
    if s is None:
        return None
    upper = s.upper()
    m = _STAT_RE.fullmatch(upper)
    if m:
        return "International" if m.group(1) == "I" else "Domestic"
    return _SEGMENT_WORDS.get(upper, upper)
