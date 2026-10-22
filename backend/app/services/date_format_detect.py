"""Which order a statement's date columns are written in, read off the file itself — to fill
in the upload step's Date format (statement_spec.date_format_fields) before anyone is asked.

A dated cell is evidence only where the orders disagree about it:

  * WRITTEN AS TEXT. "13/08/2026" can only be day-first. "05/08/2026" is 5 Aug or 8 May, and
    the statement period decides: a statement's Booked Dates sit in its period, give or take
    a day or two, so the reading inside it — or nearer it, for the odd early or late ticket
    and for travel dates — is the one meant. Each such cell is one vote for the order that
    reads it best. A cell every order reads alike ("2026-08-05", "08/08/2026"), or none can
    read, is no vote. Without a period only the first kind counts.
  * STORED BY EXCEL and put right by services/excel_dates.py. Stored dates that fall in the
    period only with day and month swapped were typed day-first on a month-first Excel —
    every one it put right is a vote for DD-MM-YYYY (the assumption excel_dates.py makes:
    an Indian consolidator types day-first). A stored date read right as stored says nothing
    about how the vendor writes dates: Excel decided it.

The order with the most votes is the answer when it has at least twice the votes of any
other; short of that the file does not settle it, and the uploader is asked.

Pure: a DataFrame of strings, the period and excel_dates' DateFix; no database.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.services import flat_statement as flat
from app.services.excel_dates import DateFix

# A stored Excel date as the reader hands it over, or ISO text: the same in every order.
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")
# The winning order needs this many times the votes of the runner-up.
_LEAD = 2


@dataclass
class Detection:
    field: str
    column: str | None                  # the file column read — the suggested mapping's
    order: str | None = None            # None: the file does not settle it
    votes: dict[str, int] = field(default_factory=lambda: dict.fromkeys(flat.DATE_ORDERS, 0))
    swapped: int = 0                    # stored dates excel_dates read day-first
    text_dates: int = 0                 # cells written as a date in text (readable some way)
    example: dict | None = None         # {"value", "read"} — a text cell that voted for `order`

    def as_dict(self) -> dict:
        return {"field": self.field, "column": self.column, "order": self.order,
                "votes": self.votes, "swapped": self.swapped, "text_dates": self.text_dates,
                "example": self.example}


def _distance(iso: str, period: tuple[date, date] | None) -> int:
    """Days from the date to the nearest day of the period; 0 inside it, or with no period."""
    if period is None:
        return 0
    d = date.fromisoformat(iso)
    if d < period[0]:
        return (period[0] - d).days
    if d > period[1]:
        return (d - period[1]).days
    return 0


def detect_column(field_name: str, column: str, values: list, period: tuple[date, date] | None,
                  swapped: int = 0) -> Detection:
    """The order one column's cells are written in — see the module docstring."""
    det = Detection(field_name, column, swapped=swapped)
    # Per order, the best example seen: one no other order could read beats one it read worse.
    examples: dict[str, tuple[bool, dict]] = {}
    for raw in values:
        s = "" if raw is None else str(raw).strip()
        if not s or s.lower() == "nan" or _ISO.match(s):
            continue
        readings = {o: flat.to_iso_date(s, o) for o in flat.DATE_ORDERS}
        distance = {o: _distance(r, period) for o, r in readings.items() if r is not None}
        if not distance:
            continue
        det.text_dates += 1
        best = min(distance.values())
        winners = [o for o, d in distance.items() if d == best]
        if len(winners) != 1:
            continue
        o = winners[0]
        det.votes[o] += 1
        only = len(distance) == 1
        if o not in examples or (only and not examples[o][0]):
            examples[o] = (only, {"value": s, "read": readings[o]})

    totals = Counter(det.votes)
    totals["DMY"] += swapped
    (top, n1), (_, n2) = totals.most_common(2)
    if n1 > 0 and n1 >= _LEAD * n2:
        det.order = top
        det.example = examples[top][1] if top in examples else None
    return det


def detect(df: pd.DataFrame, columns: dict[str, str | None], period: tuple[date, date] | None,
           fix: DateFix | None) -> list[Detection]:
    """{date field: the file column it maps to} → a Detection per field, in that order. `df` is
    the file as read for mapping, after excel_dates put right what it did (`fix`)."""
    swapped_in = Counter(c for _, c, _, _ in fix.cells) if fix else Counter()
    names = [str(c) for c in df.columns]
    out = []
    for field_name, col in columns.items():
        if not col or col not in names:
            out.append(Detection(field_name, None))
            continue
        values = df.iloc[:, names.index(col)].tolist()
        out.append(detect_column(field_name, col, values, period, swapped_in.get(col, 0)))
    return out
