"""What an employee picks up from the corporate they work for.

These are terms of the relationship with the EMPLOYER, not facts about the person: the
markup and billing type were agreed with the corporate, and when the corporate is the
party being invoiced, the GSTIN, PAN and billing contact on that invoice are the
corporate's too. Retyping them per employee is how fifty people under one company end up
on three different markups — or, until now, on none at all.

THIS IS THE SERVER TWIN OF `frontend/src/lib/party.ts`. That file's `INHERITED_FIELDS`,
`isBlankInherited` and `seedFromCorporate` do exactly this for the single-record form, in
the browser, as the user types. This module does it for the paths the browser never sees:
the Excel import and the re-link action. **The two field lists must stay identical** — if
you add a field to one, add it to the other, or the same employee gets different terms
depending on whether they were typed in or imported.

INHERITED IS A DEFAULT, NOT A BINDING. Each value is copied into the employee's own
columns and can be edited straight after; nothing re-reads the corporate later, so
changing a corporate's markup does NOT move the employees already on file. That is
deliberate — a per-employee override has to survive an edit to the parent, or it is not
an override.

`company` is deliberately NOT in this set. It is a mirror rather than a default: the
routers rewrite it on link, unlink and corporate rename (api/v1/customers.py,
api/v1/corporates.py), and it must keep being handled there.
"""
from __future__ import annotations

__all__ = ["INHERITED_FIELDS", "is_blank", "inherit_from_corporate"]

# The same eight as lib/party.ts INHERITED_FIELDS, in the same order. Note this is more
# than the "Billing & Tax" box on the form suggests: phone and email are inherited too,
# because an invoice raised against the corporate carries the corporate's contact.
INHERITED_FIELDS = (
    "phone",
    "email",
    "markup_type",
    "markup_value",
    "billing_type",
    "gst_registered",
    "gst_no",
    "pan_no",
)

# Two of the eight are PAIRS and must be decided together rather than field by field.
#
#   gst_registered + gst_no — a number is meaningless without the flag, and the routers
#   null the number whenever the flag is false.
#
#   markup_type + markup_value — a value only means anything under the type it was
#   quoted as. An employee saved with markup_type "fixed" and no value, inheriting the
#   10 from a "percentage 10" corporate, would bill ₹10 a ticket instead of 10%. The
#   value never travels without its type agreeing.
_GST_FIELDS = ("gst_registered", "gst_no")
_MARKUP_FIELDS = ("markup_type", "markup_value")
_PAIRED_FIELDS = _GST_FIELDS + _MARKUP_FIELDS


def is_blank(field: str, value) -> bool:
    """Is this employee value empty enough to take the corporate's?

    Mirrors `isBlankInherited` in lib/party.ts, with the column types this side of the
    wire rather than the form's all-strings:

      * `gst_registered` is a NOT NULL boolean, so its blank is False — there is no
        "unset" to distinguish from "unregistered".
      * `markup_value` is Numeric(14,2), so its blank is None. Zero is NOT blank: a
        deliberate 0% markup has to survive, or the inheritance would silently overwrite
        the one value a user set to mean "no margin on this person".
    """
    if field == "gst_registered":
        return not value
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def inherit_from_corporate(values: dict, corporate) -> dict:
    """Fill the blanks in `values` from `corporate`. Returns ONLY what it filled.

    `values` is the employee's own values, already normalised — run this AFTER
    `_norm_choice` and friends, never before. An unrecognised markup type normalises to
    None, which this then reads as blank and replaces with the corporate's real setting;
    inheriting first would leave the junk in place for the normaliser to discard, and the
    employee would end up on no markup at all.

    Nothing is mutated. The caller applies the returned dict, so it can also report how
    many fields it actually filled.
    """
    if corporate is None:
        return {}

    filled: dict = {}

    for field in INHERITED_FIELDS:
        if field in _PAIRED_FIELDS:
            continue                      # decided together, below
        if not is_blank(field, values.get(field)):
            continue                      # theirs, not ours
        source = getattr(corporate, field, None)
        if is_blank(field, source):
            continue                      # the corporate has nothing to give either
        filled[field] = source

    # The GST pair. Only inherit when the employee carries no registration of their own;
    # an employee already marked registered keeps their own number, and one deliberately
    # left unregistered is not silently registered by their employer's status.
    if is_blank("gst_registered", values.get("gst_registered")) \
            and is_blank("gst_no", values.get("gst_no")) \
            and getattr(corporate, "gst_registered", False):
        gst_no = getattr(corporate, "gst_no", None)
        if not is_blank("gst_no", gst_no):
            filled["gst_registered"] = True
            filled["gst_no"] = gst_no

    # The markup pair. The type is inherited like any other blank field, but the VALUE
    # only travels when the type the employee ends up on is the corporate's own — see
    # _MARKUP_FIELDS. This is the one place a naive per-field fill would change money in
    # the wrong direction rather than merely fail to change it.
    corp_type = getattr(corporate, "markup_type", None)
    if is_blank("markup_type", values.get("markup_type")) and not is_blank("markup_type", corp_type):
        filled["markup_type"] = corp_type

    resulting_type = filled.get("markup_type", values.get("markup_type"))
    if (is_blank("markup_value", values.get("markup_value"))
            # Not merely equal: both must be a real type. Two Nones comparing equal
            # would otherwise hand over a bare number with nothing to quote it under.
            and not is_blank("markup_type", resulting_type)
            and resulting_type == corp_type):
        corp_value = getattr(corporate, "markup_value", None)
        if not is_blank("markup_value", corp_value):
            filled["markup_value"] = corp_value

    return filled
