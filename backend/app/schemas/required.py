"""Annotated types for fields that are genuinely mandatory.

A bare `str` in a Pydantic model looks required but accepts `""`, and most
endpoints here then write `payload.field or None` into the column. The net effect
was that a form which sent an empty string for a field it had forgotten to
validate got a 201 back and a row with NULL in it — a save that reported success
and lost data. These types make "required" mean non-blank.

    airline_name: RequiredStr     # rejects "", "   ", missing
    valid_from:   ISODate         # rejects the above, plus "31/03/2026"
"""
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, StringConstraints


def _not_blank(v: str) -> str:
    # strip_whitespace has already run, so a whitespace-only value is "" here.
    if not v:
        raise ValueError("This field is required.")
    return v


def _iso_date(v: str) -> str:
    try:
        date.fromisoformat(v[:10])
    except ValueError:
        raise ValueError("Expected a date in YYYY-MM-DD format.")
    return v


#: Required text: trimmed, and blank is rejected rather than silently stored.
RequiredStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    AfterValidator(_not_blank),
]

#: Required date-as-string. The endpoints call date.fromisoformat() on these, so
#: catching the format here turns a 500 into a field-level 422.
ISODate = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    AfterValidator(_not_blank),
    AfterValidator(_iso_date),
]
