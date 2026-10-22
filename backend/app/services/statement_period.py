"""The period a statement covers, read from what a person wrote: a file name, an email subject.

Consolidators name a statement after the days it covers, each in their own way:

  TRIUMPHH BSP STATMENT 01-07TH AUG 26 (5).xlsx        same month, ordinal, 2-digit year
  GLOBE OUR 08 15 AUG 26.xls                           same month, the range written with a space
  Vendor 23-30SEP'26.xlsx                              glued month, apostrophe year
  GLOBE 01 AUG TO 31 AUG.xls                           a month on both ends, no year at all
  …PVT LTD(62257)01-Jul-26 To 06-Oct-26.xlsx           across months, glued to the account number
  DividePNR_All_08Sep2026_20Sep2026_20260921143112.csv underscores for spaces
  …_bookingDate_2026-08-01_2026-08-31_….xlsx           ISO dates

The Third Party GDS upload pre-fills its Statement period from the file name, and the email
intake reads the same thing out of a subject, a covering note or an attachment's name
(services/mail/body.py). One reader serves both, so a name the wizard understands is one the
inbox understands too.

EVERY ANSWER IS A SUGGESTION the user sees and can change. Nothing is decided from it
unseen, which is why a name that says nothing ("test1.xlsx", a single as-of date like
"YATRA STATEMENT 30 SEP 26") gets None rather than a guess: an empty box asks the question,
a wrong date pre-filled in it hides one.

A YEAR IS TWO OR FOUR DIGITS, nothing else — "08-15th Aug, 245 tickets" is a period in August,
not one in the year 245. With no year the period is the latest one that has (nearly) ended:
this year, unless that puts its end more than a month ahead of `today`, when it is last year's
— "20-31 DEC" read on 5 January is the December just gone.

Pure: no database, no clock (callers pass `today`). Also home to the check every period's
upload runs on its lines — which are dated outside the period (`side`, `OutsidePeriod`).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
# A month's name, short or long — ONE capturing group, so it slots into a larger pattern the
# way services/mail/body.py uses it. Not followed by a letter: "MARKUP" and "DECLARATION" are
# not March and December.
MON = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
       r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?![a-z])")

# Between the two ends of a range. Digit lookarounds rather than \b everywhere below: "_" is
# a word character, so \b finds no edge in "_08Sep2026_", and none between ")" and "01" either.
_SEP = r"\s*(?:-|–|—|~|_|\bto\b|\btill\b|\buntil\b|\bupto\b|\bup\s+to\b)\s*"
_ORD = r"(?:st|nd|rd|th)?"
_DAY = r"(?<!\d)(\d{1,2})" + _ORD
_YEAR = r"(?:[\s\-./,'’]*(\d{4}|\d{2})(?!\d))?"
_GLUE = r"[\s\-./]*"

# Tried in this order; within one pattern the first match that makes a real period wins.
_ISO = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)" + _SEP + r"(\d{4})-(\d{2})-(\d{2})(?!\d)", re.I)
_DMY_NUMERIC = re.compile(
    r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)" + _SEP
    + r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)", re.I)
_BOTH_MONTHS = re.compile(_DAY + _GLUE + MON + _YEAR + _SEP + _DAY + _GLUE + MON + _YEAR, re.I)
_SAME_MONTH = re.compile(_DAY + rf"(?:{_SEP}|\s+)" + r"(\d{1,2})" + _ORD + _GLUE + MON + _YEAR, re.I)
_MONTH_FIRST = re.compile(r"(?<![a-z])" + MON + _GLUE + _DAY + _SEP + r"(\d{1,2})" + _ORD + _YEAR, re.I)

# Only a real file extension is cut — "01.08.2026 TO 07.08.2026" has dots that are dates.
_EXTENSION = re.compile(r"\.(xlsx|xlsm|xlsb|xls|csv|tsv|txt|pdf|zip)$", re.I)
# A copy's suffix the OS or the mail client added: "… AUG 26 (5).xlsx", "… - Copy.xlsx".
_COPY_SUFFIX = re.compile(r"(\s*\(\d+\)|\s*-\s*copy(\s*\(\d+\))?)+$", re.I)

# A period longer than a year is a misreading, not a statement.
_MAX_DAYS = 366
# How far past `today` an inferred period may end before it is taken to be last year's.
_AHEAD = timedelta(days=31)


def _year(y: str | None) -> int | None:
    if not y:
        return None
    n = int(y)
    return 2000 + n if len(y) == 2 else n


def _month(name: str) -> int:
    return MONTHS[name[:3].lower()]


def _period(d1, m1, y1, d2, m2, y2, today: date) -> tuple[date, date] | None:
    """Two (day, month, year-or-None) ends → a real period, the missing years inferred."""
    try:
        d1, m1, d2, m2 = int(d1), int(m1), int(d2), int(m2)
        wraps = (m1, d1) > (m2, d2)               # 28 DEC – 03 JAN crosses the year end
        if y2 is None and y1 is not None:
            y2 = y1 + 1 if wraps else y1
        if y2 is None:
            y2 = today.year
            if date(y2, m2, d2) > today + _AHEAD:
                y2 -= 1
        if y1 is None:
            y1 = y2 - 1 if wraps else y2
        start, end = date(y1, m1, d1), date(y2, m2, d2)
    except (ValueError, TypeError):
        return None                               # 31 SEP, 29 FEB of a common year, …
    if start > end or (end - start).days > _MAX_DAYS:
        return None
    return start, end


def find_period(text: str | None, today: date) -> tuple[date, date] | None:
    """The first statement period written in `text`, or None."""
    if not text:
        return None
    for m in _ISO.finditer(text):
        y1, m1, d1, y2, m2, d2 = m.groups()
        if (p := _period(d1, m1, int(y1), d2, m2, int(y2), today)):
            return p
    for m in _DMY_NUMERIC.finditer(text):
        d1, m1, y1, d2, m2, y2 = m.groups()
        if (p := _period(d1, m1, _year(y1), d2, m2, _year(y2), today)):
            return p
    for m in _BOTH_MONTHS.finditer(text):
        d1, mon1, y1, d2, mon2, y2 = m.groups()
        if (p := _period(d1, _month(mon1), _year(y1), d2, _month(mon2), _year(y2), today)):
            return p
    for m in _SAME_MONTH.finditer(text):
        d1, d2, mon, y = m.groups()
        if (p := _period(d1, _month(mon), _year(y), d2, _month(mon), _year(y), today)):
            return p
    for m in _MONTH_FIRST.finditer(text):
        mon, d1, d2, y = m.groups()
        if (p := _period(d1, _month(mon), _year(y), d2, _month(mon), _year(y), today)):
            return p
    return None


def file_stem(name: str | None) -> str:
    """A file's name as a person wrote it — folders, a real extension and a copy's "(5)" /
    "- Copy" left out. "C:\\…\\GLOBE 01 AUG TO 31 AUG (2).xls" → "GLOBE 01 AUG TO 31 AUG"."""
    if not name:
        return ""
    stem = _EXTENSION.sub("", os.path.basename(name.replace("\\", "/")).strip())
    return _COPY_SUFFIX.sub("", stem)


def from_file_name(name: str | None, today: date) -> tuple[date, date] | None:
    """The period a statement's file name gives, or None — extension, folders and a copy's
    "(5)" left out, so they cannot be taken for a day."""
    stem = file_stem(name)
    return find_period(stem, today) if stem else None


def overlaps(a_from: date, a_to: date, b_from: date, b_to: date) -> bool:
    """Do two periods share at least one day? Both ends are inclusive."""
    return a_from <= b_to and b_from <= a_to


# ── a line's date against the period it was uploaded under ───────────────────
# The review step of a period's upload flags the lines dated outside it — a refund of an
# older ticket, a late posting, or the wrong period typed — for the user to look at before
# saving. Flagged, never dropped. Third Party GDS checks Booked Date and Issue Date
# (services/tp_gds_reupload.py), and answers in the shape below.

# Lines listed back to the user. The count always covers every line.
OUTSIDE_LISTED = 200


def side(value, period: tuple[date, date]) -> str | None:
    """Where a YYYY-MM-DD value sits against `period`: "before", "after", "unreadable" (not a
    date at all), or None when inside it."""
    try:
        d = date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return "unreadable"
    if d < period[0]:
        return "before"
    if d > period[1]:
        return "after"
    return None


@dataclass
class OutsidePeriod:
    """A file's lines dated outside its declared period."""
    period: tuple[date, date] | None = None
    # One per line: the line as shown, its row (`index`), and {field: "before"|"after"|"unreadable"}.
    lines: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "period_label": label(*self.period) if self.period else "this period",
            "count": len(self.lines),
            "lines": self.lines[:OUTSIDE_LISTED],
            # Every flagged row, uncapped and small, so the review grid can mark each one.
            "rows": [{"index": r["index"], "outside": r["outside"]}
                     for r in self.lines if r.get("index") is not None],
        }


def label(start: date | None, end: date | None) -> str:
    """"01–07 Aug 2026", "28 Jul – 03 Aug 2026", "28 Dec 2025 – 03 Jan 2026"."""
    if start is None or end is None:
        return "—"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start:%d}–{end:%d %b %Y}"
    if start.year == end.year:
        return f"{start:%d %b} – {end:%d %b %Y}"
    return f"{start:%d %b %Y} – {end:%d %b %Y}"
