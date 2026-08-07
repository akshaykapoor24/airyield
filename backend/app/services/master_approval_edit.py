"""Platform-admin edits to a pending System Master approval request.

The four master queues (suppliers, airlines, airports, classes/RBD) all mirror
their business columns directly onto the approval row, and the approve endpoints
copy that row onto the master afterwards. An admin edit is therefore just an
in-place update of the approval row — approve needs no change at all.

What the submitter is owed is visibility. `original_payload` is a JSONB snapshot
of the business columns as the submitter left them, written lazily on the *first*
edit: NULL means "no admin changed anything", which is exactly the case where
there is nothing extra to show, and it needs no backfill for rows already queued.
A later edit never overwrites the snapshot, so the submitter always diffs against
their own values rather than against an intermediate admin draft.
"""
from datetime import datetime
from typing import Any, Mapping, Sequence


# ── Editable business fields per master ────────────────────────────────────
# These define both what an admin may write and what the snapshot covers.
# `request_type` and `target_*_id` are deliberately absent: an admin must not be
# able to turn a "new" request into an "update" — that is a different request.

AIRPORT_FIELDS = ("iata_code", "country", "categorization", "continent", "city_airport_name")

AIRLINE_FIELDS = ("name", "iata_code", "icao_code", "contract_year")

CLASS_FIELDS = ("airline_name", "class_type", "class_code", "airline_type", "class_note")

SUPPLIER_CORE_FIELDS = (
    "name", "vendor_type", "vendor_name", "branch", "branches",
    "contact_phone", "alternate_phone", "contact_email", "alternate_email",
    "gst_number", "pan_number", "notes",
)
# The 15 directory fields are appended by app/api/v1/suppliers.py from its
# existing DIRECTORY_FIELDS constant, so that list stays the single source.


def _is_blank(value: Any) -> bool:
    """NULL, "" and [] all mean "no value" in these tables.

    The masters store optional text as NULL or "" depending on which path wrote
    it (form post vs bulk upload), and an HTML form always posts "". Without
    this, opening the edit modal and pressing Save would register a change on
    every blank field and stamp a spurious "edited by admin" on the request.
    """
    return value is None or value == "" or value == [] or value == {}


def _jsonable(value: Any) -> Any:
    # Business columns are str / None / list-of-dict today; the datetime arm is
    # cheap insurance if one of the masters ever grows a date column.
    return value.isoformat() if isinstance(value, datetime) else value


def snapshot(approval: Any, fields: Sequence[str]) -> dict[str, Any]:
    """The approval row's business values as a plain JSON-safe dict."""
    return {f: _jsonable(getattr(approval, f, None)) for f in fields}


def apply_admin_edit(
    approval: Any,
    *,
    fields: Sequence[str],
    changes: Mapping[str, Any],
    editor_id: int,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Apply a platform admin's edit to a pending approval row, in place.

    `fields` is the master's full set of editable business columns; it defines
    both what may be written and what the snapshot covers. `changes` has already
    been normalised by the caller (categorization slash-joined, codes upper-cased)
    and reduced with model_dump(exclude_unset=True), so an absent key means
    "leave alone" while an explicit None means "clear".

    Returns {field: {"from": old, "to": new}} for the fields this call actually
    changed. An empty result means the admin saved without changing anything —
    nothing is written and no edit stamp is left behind, so the submitter sees
    the request exactly as they submitted it.

    Does not commit; the caller owns the transaction.
    """
    unknown = set(changes) - set(fields)
    if unknown:
        raise ValueError(f"Not editable on this request: {', '.join(sorted(unknown))}")

    before = snapshot(approval, fields)

    diff: dict[str, dict[str, Any]] = {}
    for field, new_value in changes.items():
        old_value = getattr(approval, field)
        if (_is_blank(old_value) and _is_blank(new_value)) or old_value == new_value:
            continue
        setattr(approval, field, new_value)
        diff[field] = {"from": _jsonable(old_value), "to": _jsonable(new_value)}

    if not diff:
        return {}

    if approval.original_payload is None:
        # First edit only. `before` is a freshly built dict, never the one loaded
        # from the DB — these JSON columns have no mutation tracking anywhere in
        # this codebase, so they must be assigned wholesale, never mutated.
        approval.original_payload = before

    if approval.original_payload == snapshot(approval, fields):
        # The admin put every value back the way the submitter sent it. There is
        # nothing for the submitter to see, so drop the edit stamp entirely
        # rather than badge the request and open an empty diff.
        approval.original_payload = None
        approval.edited_by_id = None
        approval.edited_at = None
        return diff

    approval.edited_by_id = editor_id
    approval.edited_at = now or datetime.utcnow()
    return diff
