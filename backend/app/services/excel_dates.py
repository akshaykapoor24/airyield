"""Excel-stored dates in a statement's date columns, put in the order the sheet is written in.

The uploader declares the order each date column is written in (statement_spec
.date_format_fields: DD-MM-YYYY, MM-DD-YYYY or YYYY-MM-DD), and a date written as TEXT is read
in that order and no other (flat_statement.to_iso_date). A date Excel STORED is different: it
is a day number, with no written order left in the cell to follow. Excel turned what was
typed into a date the moment it was typed, reading it the way ITS settings say. Where those
match the sheet the stored date is right. Where they don't — "01-08-2026" typed day-first
into an Excel set to month-first — Excel stored 8 January, and shows it back as 01-08-26, so
the sheet still looks right. A day past 12 cannot be a month, so Excel kept "13/08/2026" as
text, which the declared order reads correctly.

Typed rows and rows pasted in from a system export (stored right) sit side by side — the
TRIUMPHH 01–07 Aug statement has 64 typed Booked Dates stored as 8 Jan … 8 Jul and a run of
pasted cancellations stored right on 7, 15 and 22 Aug — and nothing in a cell says which. The
statement period does, through each row's Booked Date: the one date that belongs in it (a
sales statement's Ticket Date plays that part on Internal Statement — `anchor`).

  * THE FILE. Was it entered the other way round at all? Each stored Booked Date votes:
    "swapped" when only the swapped reading falls in the period (or nearer it), "as stored"
    when the stored one does, or when it is past the 12th (Excel could never have swapped
    it). No more swapped votes than as-stored ones → every stored date is left as Excel holds
    it (every correctly dated statement seen so far).
  * EACH ROW, in a file that was. A row whose Booked Date was swapped was typed: every stored
    date on it — Booked Date and Date of Travel alike — is put back. A row whose Booked Date is
    stored right was pasted: its dates stay as they are. A row whose Booked Date is text was
    typed (Excel could not read it its way), and is put back. Only a row whose Booked Date
    says neither — empty, or a day equal to its month — is decided date by date: the reading
    in the period, else the nearer one.
  * ONLY the declared date columns, and only those declared day-and-month (DD-MM or MM-DD).
    A YYYY-MM-DD column is read the same by every Excel, so nothing in it is moved.

Only stored dates move — the reader hands them over as "2026-01-08 00:00:00"; text is read in
the declared order. Only Excel workbooks: a CSV holds text. Every change is reported cell by
cell, so the review step can show what was read differently.

Pure: a DataFrame of strings, the columns, the period and the declared orders; no database.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.services import flat_statement as flat
from app.services import statement_period

# A real Excel date as services/spreadsheet.py hands it over: str(datetime).
_STORED = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2}:\d{2})$")
# The declared orders whose day and month an Excel set the other way round can swap.
_SWAPPABLE = ("DMY", "MDY")
# The date that belongs in the statement period, and so says how its row was entered.
ANCHOR = "booking_date"


@dataclass
class DateFix:
    """The stored dates read with their day and month put back."""
    period: tuple[date, date]
    # (file row, column, as stored, as read) — ISO dates, in file order.
    cells: list[tuple[int, str, str, str]] = field(default_factory=list)

    def as_dict(self, rows_shown: int | None = None) -> dict:
        """For the wizard. `cells` only for the rows it shows, which are the ones it can mark."""
        by_column = Counter(c for _, c, _, _ in self.cells)
        shown = [c for c in self.cells if rows_shown is None or c[0] < rows_shown]
        return {
            "period_label": statement_period.label(*self.period),
            "count": len(self.cells),
            "columns": [{"column": c, "cells": n} for c, n in by_column.items()],
            "cells": [{"index": i, "column": c, "stored": s, "read": r} for i, c, s, r in shown],
        }


def _stored(value) -> tuple[date, str] | None:
    """(date, time) of a stored Excel date; None for text, blanks and anything else."""
    m = _STORED.match(value) if isinstance(value, str) else None
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])), m[4]
    except ValueError:
        return None


def _swapped(d: date) -> date | None:
    """`d` with its day and month exchanged, or None when that is no other date."""
    if d.day > 12 or d.day == d.month:
        return None
    return date(d.year, d.day, d.month)


def _distance(d: date, period: tuple[date, date]) -> int:
    """Days from `d` to the nearest day of `period`; 0 inside it."""
    if d < period[0]:
        return (period[0] - d).days
    if d > period[1]:
        return (d - period[1]).days
    return 0


def _says(d: date, period: tuple[date, date]) -> str | None:
    """What a stored Booked Date says about its row: "swap" (entered the other way round),
    "keep" (stored right) or None (it reads the same, or as near, both ways)."""
    s = _swapped(d)
    if s is None:
        # Past the 12th Excel could never have swapped it; a day equal to its month reads
        # the same both ways.
        return "keep" if d.day > 12 else None
    swapped, kept = _distance(s, period), _distance(d, period)
    return "swap" if swapped < kept else "keep" if kept < swapped else None


def _typed_text(value) -> bool:
    """A date left as text — Excel could not read it its own way, so it was typed."""
    if not isinstance(value, str) or _stored(value):
        return False
    return any(flat.to_iso_date(value, o) for o in _SWAPPABLE)


def read_stored_dates(df: pd.DataFrame, period: tuple[date, date] | None, columns: dict[str, str],
                      orders: dict[str, str] | None, anchor: str = ANCHOR) -> DateFix | None:
    """Put back, IN PLACE, the stored dates of the declared date columns that Excel stored with
    day and month swapped — see the module docstring.

    `columns` is {date field: the file column mapped to it}; `orders` the declared order of
    each field (flat_statement.date_orders), or None while the file is still being read for
    its format, when every date column given may be swapped. `anchor` is the field whose date
    belongs in the period — Booked Date on a vendor statement, Ticket Date on a sales one.
    None, and `df` untouched, when the sheet reads right as it is."""
    if not period or df.empty:
        return None
    names = [str(c) for c in df.columns]
    at = {f: names.index(c) for f, c in columns.items() if c and c in names}
    # By column, not by field: one column mapped to two fields (a Doc Date that is also the
    # Ticket Date) must be put back once, not swapped and swapped back.
    movable = sorted({j for f, j in at.items() if orders is None or orders.get(f) in _SWAPPABLE})
    if not movable:
        return None
    anchor_at = at.get(anchor)

    # The file: entered the other way round at all? Asked of the anchor dates when mapped.
    votes: Counter = Counter()
    for j in ([anchor_at] if anchor_at is not None else movable):
        for value in df.iloc[:, j].tolist():
            st = _stored(value)
            if st:
                votes[_says(st[0], period)] += 1
    if votes["swap"] <= votes["keep"]:
        return None

    fix = DateFix(period=period)
    for pos in range(len(df)):
        row = None
        if anchor_at is not None:
            a = df.iat[pos, anchor_at]
            st = _stored(a)
            row = _says(st[0], period) if st else "swap" if _typed_text(a) else None
        for j in movable:
            st = _stored(df.iat[pos, j])
            if not st:
                continue
            stored, time = st
            swapped = _swapped(stored)
            if swapped is None:
                continue
            put_back = (row == "swap" if row is not None
                        else _distance(swapped, period) < _distance(stored, period))
            if put_back:
                df.iat[pos, j] = f"{swapped.isoformat()} {time}"
                fix.cells.append((pos, names[j], stored.isoformat(), swapped.isoformat()))
    fix.cells.sort()
    return fix if fix.cells else None
