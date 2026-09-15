"""The six things a party can be quoted a different markup on.

A party used to have ONE markup, applied to every ticket. An agency that also sells hotel
nights, train berths and MICE packages needs a different rate per line of business, so
`customers.category_markups` and `corporates.category_markups` hold an override per slug
below and `services/party_markup.markup_for` picks the one a line belongs to.

PLAIN LOWERCASE SLUGS, NOT A DB ENUM. models/gst_configuration.py states the house rule for
this schema: "Kept as plain strings (not a DB Enum) to match every other choice column …
so adding a fourth basis is a code change, never a migration." A seventh category is one
line here and one line in the browser twin.

"AIR", NOT "FLIGHT". services/tp_api_spec.py::PRODUCT_VALUES says "Flight" — that is
Title-Case DISPLAY text for the statement parser's Category facet and its AI prompt. These
are config slugs, and every config slug in this schema is lowercase: `percentage`, `fixed`,
`reseller`, `agency`, `private_limited`, `basic_fare`, `abatement`, `domestic`. CATEGORY_ALIASES
maps every PRODUCT_VALUES spelling onto one of these, so the day a hotel row becomes billable
the projection can hand over its `product_type` unchanged. (The two vocabularies already meet
in one direction: tp_api_spec._PRODUCT_TYPES already accepts "air" as a spelling of "Flight".)

THIS IS THE ONLY DEFINITION ON THE SERVER. The browser twin is
frontend/src/lib/party.ts::MARKUP_CATEGORIES, kept in step the way CORPORATE_TYPES already is
with api/v1/corporates.py::_CORPORATE_TYPES.
"""
from __future__ import annotations

CATEGORY_AIR = "air"
CATEGORY_HOTEL = "hotel"
CATEGORY_TRAIN = "train"
CATEGORY_BUS = "bus"
CATEGORY_CAR = "car"
CATEGORY_MICE = "mice"

#: (slug, display label), in the order the form renders them. Air first because it is the
#: one every existing party already bills under.
MARKUP_CATEGORIES: tuple[tuple[str, str], ...] = (
    (CATEGORY_AIR, "Air"),
    (CATEGORY_HOTEL, "Hotel"),
    (CATEGORY_TRAIN, "Train"),
    (CATEGORY_BUS, "Bus"),
    (CATEGORY_CAR, "Car"),
    (CATEGORY_MICE, "MICE"),
)

CATEGORY_SLUGS: tuple[str, ...] = tuple(slug for slug, _label in MARKUP_CATEGORIES)
CATEGORY_LABELS: dict[str, str] = dict(MARKUP_CATEGORIES)

#: How a markup is quoted. The same two values `compute_markup` branches on, and the same
#: two `_MARKUP_TYPES` has meant in customers.py and corporates.py all along — this is now
#: the one definition those two import, rather than a third copy.
MARKUP_TYPES: tuple[str, ...] = ("percentage", "fixed")

#: Every spelling that resolves to a slug, including the canonical one. Deliberately NOT
#: aliasing `series` or `sit` onto MICE: series_contracts.contract_type holds three distinct
#: contract types and only one of them is MICE.
CATEGORY_ALIASES: dict[str, str] = {
    "air": CATEGORY_AIR,
    "flight": CATEGORY_AIR,
    "flights": CATEGORY_AIR,
    "airline": CATEGORY_AIR,
    "domestic flight": CATEGORY_AIR,
    "international flight": CATEGORY_AIR,
    "hotel": CATEGORY_HOTEL,
    "hotels": CATEGORY_HOTEL,
    "accommodation": CATEGORY_HOTEL,
    "stay": CATEGORY_HOTEL,
    "train": CATEGORY_TRAIN,
    "trains": CATEGORY_TRAIN,
    "rail": CATEGORY_TRAIN,
    "railways": CATEGORY_TRAIN,
    "irctc": CATEGORY_TRAIN,
    "bus": CATEGORY_BUS,
    "buses": CATEGORY_BUS,
    "coach": CATEGORY_BUS,
    "car": CATEGORY_CAR,
    "cab": CATEGORY_CAR,
    "cabs": CATEGORY_CAR,
    "car rental": CATEGORY_CAR,
    "self drive": CATEGORY_CAR,
    "mice": CATEGORY_MICE,
}


def category_slug(raw) -> str | None:
    """Any spelling of a category → its slug, or None.

    None rather than a guess, and the callers differ on what to do with it: the normaliser
    DROPS an entry whose key it cannot place (matching `_norm_choice`'s silent coercion, so
    a category arriving from a newer frontend cannot fail the whole save), while
    `markup_for` falls back to the party's default.
    """
    if raw is None:
        return None
    key = " ".join(str(raw).split()).lower()
    return CATEGORY_ALIASES.get(key)
