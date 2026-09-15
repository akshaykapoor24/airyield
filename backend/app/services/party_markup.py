"""Which markup a party charges on one line of their bill.

A party has a DEFAULT markup (`markup_type` + `markup_value`, the two columns that have
always been there) and, optionally, an OVERRIDE per category in `category_markups`. This
module is the whole seam between the two: `markup_for` picks the pair, `category_of` says
which category a billable line is, and `norm_category_markups` decides what is allowed to be
stored in the first place.

`compute_markup` itself is untouched — it is pure arithmetic with fifty tests on it, and the
four call sites in api/v1/{customers,corporates}.py now pass it a resolved pair instead of
reading two columns directly.

WHY THIS IS NOT IN billing_calc.py, where the four callers already import from: that module
is shared with the AGENCY billing router, and an agency deliberately has no stored markup at
all (api/v1/agency_billing.py hardcodes 0.0, with its reason). Putting party-markup
vocabulary in it would be an invitation to wire it in there.
"""
from __future__ import annotations

from app.services.markup_categories import (
    CATEGORY_AIR,
    CATEGORY_SLUGS,
    MARKUP_TYPES,
    category_slug,
)

__all__ = [
    "norm_category_markups", "markup_for", "category_of", "category_summary",
    "CATEGORY_COLUMNS", "category_columns", "category_markups_from_cells",
    "pax_of", "line_markup",
]


def _num(value):
    """A markup value as a number, or None. Accepts the str a JSONB round-trip can produce."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def norm_category_markups(raw) -> dict | None:
    """Whatever the client sent → what may be stored, or None for "no overrides".

    SHAPE 422s, VOCABULARY COERCES — the line this codebase already draws. Pydantic rejects a
    malformed body; an unrecognised *value* is silently blanked by `_norm_choice`
    (api/v1/customers.py), and `lib/partyImport.ts` says why: "a miss here is a blank the user
    fills in at review, never a wrong value that gets saved."

    So, per entry:

    * an unknown key is DROPPED, not rejected — a seventh category arriving from a newer or
      older frontend must not fail the whole save;
    * a known key spelt differently ("Flight", "HOTEL") is aliased onto its slug;
    * an unknown `type` drops the entry, the same coercion `_norm_choice` performs;
    * a HALF-SET entry — a type with no value, or a value with no type — is DROPPED, because
      `compute_markup` is inert on both (a type with no value bills 0.0; a value with no type
      falls through to `return 0.0`). Storing one would be a category silently priced at
      nothing, which is a revenue leak nothing on screen would report;
    * `value: 0` is KEPT. A deliberate 0% is a real override — the same call
      `services/party_inherit.is_blank` already makes for `markup_value`.

    Returns None rather than `{}` so the column stays NULL. NULL and `{}` must not be two
    spellings of one state, or `is_blank`, `markup_for` and the browser all have to handle
    two empties.
    """
    if not isinstance(raw, dict):
        return None

    out: dict[str, dict] = {}
    for key, entry in raw.items():
        slug = category_slug(key)
        if slug is None or not isinstance(entry, dict):
            continue
        mtype = entry.get("type")
        mtype = str(mtype).strip().lower() if mtype is not None else None
        if mtype not in MARKUP_TYPES:
            continue
        mval = _num(entry.get("value"))
        if mval is None:
            continue                     # half-set: inert in compute_markup, so not an override
        out[slug] = {"type": mtype, "value": mval}

    # Stable, and the order the form renders them in — so a GET after a PATCH reads the way
    # the screen looks rather than in whatever order the client happened to send.
    return {s: out[s] for s in CATEGORY_SLUGS if s in out} or None


def category_columns(slug: str) -> tuple[str, str]:
    """The two spreadsheet columns one category's markup is imported from.

    A PAIR, like the default MARKUP_TYPE / MARKUP_VALUE beside them, rather than one
    "AIR_MARKUP" cell holding "5%": Excel stores a typed "5%" as the number 0.05, and a
    bare "5" cannot say whether it is 5% or ₹5. Two columns cannot be misread.
    """
    prefix = slug.upper()
    return f"{prefix}_MARKUP_TYPE", f"{prefix}_MARKUP_VALUE"


#: Every category column, in template order. Appended AFTER the columns the templates have
#: always had, so an older file is a strict subset of a new one.
CATEGORY_COLUMNS: tuple[str, ...] = tuple(
    col for slug in CATEGORY_SLUGS for col in category_columns(slug)
)


def category_markups_from_cells(cell) -> tuple[dict | None, str | None]:
    """One spreadsheet row's category columns → (category_markups, problem).

    `cell(column)` returns a cell's trimmed text, or None when blank or absent. A sheet
    with none of these columns — every template made before they existed — gives
    (None, None), so an old file imports exactly as it always did.

    UNLIKE `norm_category_markups`, a half-filled pair here is a PROBLEM, not a silent
    drop. The form cannot produce one; a spreadsheet easily can, and someone who typed
    300 under HOTEL_MARKUP_VALUE and forgot the type must hear about it rather than find
    hotels billed at the default.
    """
    out: dict[str, dict] = {}
    for slug in CATEGORY_SLUGS:
        type_col, value_col = category_columns(slug)
        raw_type, raw_value = cell(type_col), cell(value_col)
        if not raw_type and not raw_value:
            continue
        mtype = str(raw_type).strip().lower() if raw_type else None
        if raw_type and mtype not in MARKUP_TYPES:
            return None, f"{type_col} '{raw_type}' must be percentage or fixed."
        if not raw_value:
            return None, f"{value_col} is required when {type_col} is filled in."
        mval = _num(raw_value)
        if mval is None or mval != mval:        # NaN != NaN: float("nan") parses
            return None, f"{value_col} '{raw_value}' is not a number."
        if not mtype:
            return None, f"{type_col} (percentage or fixed) is required when {value_col} is filled in."
        out[slug] = {"type": mtype, "value": mval}
    return (out or None), None


def markup_for(party, category: str | None) -> tuple[str | None, object]:
    """(markup_type, markup_value) for one line of this party's bill.

    THE OVERRIDE IS AN OVERRIDE, AND ITS ABSENCE MEANS "AS USUAL". A category with no entry —
    and a line whose category is unknown — takes the party's default. It does NOT take zero:
    a category quietly priced at nothing the day its bills come online is a revenue leak
    nobody would see, and the default is the terms actually agreed with this party. The same
    reasoning PartyModal already applies to a blank billing_type ("Blank is not a neutral
    starting point here").

    ZERO IS AN OVERRIDE, THOUGH. {"hotel": {"type": "percentage", "value": 0}} means "no
    margin on hotels" and is honoured — hence `mval is None` below, never `not mval`.

    Guards again on read even though `norm_category_markups` prunes on write: JSONB will hold
    whatever a psql session puts there, and this runs on every line of every bill.
    """
    default = (getattr(party, "markup_type", None), getattr(party, "markup_value", None))
    if not category:
        return default

    overrides = getattr(party, "category_markups", None)
    if not isinstance(overrides, dict):
        return default
    entry = overrides.get(category)
    if not isinstance(entry, dict):
        return default

    mtype, mval = entry.get("type"), entry.get("value")
    if mtype not in MARKUP_TYPES or mval is None:
        return default          # half-set would bill zero — fall back rather than leak
    return (mtype, mval)


def category_of(ticket) -> str | None:
    """Which of the six markup categories this billable line is.

    READ FROM `uploaded_tickets.product_category`. The Third Party API projection writes
    `category_slug(product_type)` there for hotels, trains, buses and cars; every other writer
    (LCC, NDC, B2B, manual tickets) writes flights and leaves the column at its 'air' default.

    An object with no such attribute is a flight — the same assumption the column's default
    makes. A value that is not a category slug returns None, which `markup_for` answers with
    the party's DEFAULT markup rather than a guess at a category.

    NOT `statement_type` OR `document_type`. Those are PROVENANCE — which file the row came
    from ('lcc' | 'ndc' | 'tp-api') and the airline's own document class ('E-Ticket') —
    and neither says "Hotel".
    """
    return category_slug(getattr(ticket, "product_category", None) or CATEGORY_AIR)


def pax_of(ticket) -> int:
    """How many passengers a billing line covers — at least 1.

    `uploaded_tickets.pax_count` is NOT NULL with a default of 1, but this runs on every line
    of every bill, and an object with no such attribute (or a 0 a psql session put there) must
    not zero a fixed markup. So anything that is not a positive whole number is one passenger.
    """
    raw = getattr(ticket, "pax_count", None)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 1
    return n if n >= 1 else 1


def line_markup(base: float, party, ticket) -> tuple[float, str | None]:
    """`(markup amount, note)` for one line of this party's bill — the ONE place the four
    billing call sites in api/v1/{customers,corporates}.py get their markup from.

    A FIXED MARKUP IS PER PASSENGER. ₹300 agreed with a corporate is ₹300 for each traveller,
    so a six-passenger train booking carries ₹1,800. A PERCENTAGE IS NOT MULTIPLIED: the base
    it is a percentage of is the booking's own amount, which already covers all six — 2% × 6
    would charge six times the agreed rate.

    `compute_markup` stays the arithmetic (and keeps its sign rule: a credit's fixed markup
    comes back negative, so a six-pax refund reverses ₹300 × 6). With pax 1 — every line
    except a Third Party API booking — this is exactly `compute_markup(base, *markup_for(…))`,
    the figure these call sites have always produced.

    `note` says how the amount was reached, for the screens: "₹300 × 6 pax", "2% of fare".
    """
    from app.services.billing_calc import compute_markup   # billing_calc imports the models

    mtype, mval = markup_for(party, category_of(ticket))
    amount = compute_markup(base, mtype, mval)
    kind = (mtype or "").lower()
    pax = pax_of(ticket)
    if kind == "fixed":
        amount *= pax
        shown = _num(mval)
        value = f"₹{shown:g}" if shown is not None else "₹0"
        return amount, (f"{value} × {pax} pax" if pax > 1 else f"{value} per pax")
    if kind == "percentage":
        shown = _num(mval)
        return amount, (f"{shown:g}% of fare" if shown is not None else None)
    return amount, None


def category_summary(party) -> str:
    """"Hotel 5% · Train ₹100" — the overrides in one line, for a list cell or a detail row."""
    overrides = getattr(party, "category_markups", None)
    if not isinstance(overrides, dict) or not overrides:
        return ""
    from app.services.markup_categories import CATEGORY_LABELS

    parts = []
    for slug in CATEGORY_SLUGS:
        entry = overrides.get(slug)
        if not isinstance(entry, dict):
            continue
        mtype, mval = entry.get("type"), entry.get("value")
        if mtype not in MARKUP_TYPES or mval is None:
            continue
        shown = f"{mval:g}" if isinstance(mval, (int, float)) else str(mval)
        parts.append(f"{CATEGORY_LABELS[slug]} "
                     + (f"{shown}%" if mtype == "percentage" else f"₹{shown}"))
    return " · ".join(parts)
