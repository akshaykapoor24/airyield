"""Grouping for User Master → Airline Master.

The user's Airline Master is a **live view of the platform airline master**, not a
per-tenant copy of it. The airline columns (name / code / IATA numeric code /
contract year) are owned by the platform admin; the only thing a tenant owns is its
own id(s) for each airline. So the screen is built by listing `airlines` and hanging
the tenant's `tenant_airlines` rows underneath each one — no seeding, no re-sync job,
and an airline the platform admin adds shows up immediately.

A tenant normally holds SEVERAL ids for one carrier (five Indigo agent logins across
offices is ordinary), which is why `ids` is a list. Nothing in the schema had to
change for that: `tenant_airlines` only constrains `(tenant_id, ref_id)`, so many
rows may share an `airline_id` already.

This module is deliberately pure — no session, no I/O — so the grouping can be tested
without a database, like the rest of `backend/tests/`.
"""
from typing import Iterable, Mapping


def _id_entry(row, master_name: str | None, usage_counts: Mapping[int, int]) -> dict:
    return {
        "id": row.id,
        "ref_id": row.ref_id,
        "is_active": bool(row.is_active),
        # How many LCC batches were uploaded against this id. DELETE refuses when
        # this is non-zero (api/v1/tenant_airlines.py), so the UI can say so up
        # front instead of letting the user discover it as a 409.
        "in_use_count": int(usage_counts.get(row.id, 0)),
        # The snapshot is what statements were stamped with at upload time and is
        # never rewritten. When the admin has since renamed the airline, say so
        # rather than silently showing one name or the other.
        "snapshot_name_drifted": bool(
            row.airline_name and master_name and row.airline_name != master_name
        ),
    }


def build_catalog(
    airlines: Iterable,
    tenant_rows: Iterable,
    usage_counts: Mapping[int, int] | None = None,
) -> list[dict]:
    """One entry per platform airline, with the tenant's ids nested under it.

    `airlines` is returned in the order given (the query orders by name); an airline
    the tenant has no id for still gets an entry, with an empty `ids` — that is the
    blank-ID row the user fills in.
    """
    counts = usage_counts or {}

    by_airline: dict[int, list] = {}
    for row in tenant_rows:
        by_airline.setdefault(row.airline_id, []).append(row)

    entries: list[dict] = []
    for airline in airlines:
        rows = by_airline.get(airline.id, [])
        # Stable, human order — the ids are free-text handles, so sort them the way
        # the user reads them rather than by insertion id.
        rows = sorted(rows, key=lambda r: (r.ref_id or "").lower())
        ids = [_id_entry(r, airline.name, counts) for r in rows]
        entries.append({
            "airline_id": airline.id,
            "name": airline.name,
            "iata_code": airline.iata_code,
            # The importer writes the numeric code to both columns; older rows only
            # ever got icao_code, so fall back to it — same as /airlines/export.
            "iata_numeric_code": airline.iata_numeric_code or airline.icao_code,
            "contract_year": airline.contract_year,
            # `is_active` has a Python-side default but no server default, so a row
            # written outside the ORM can be NULL. NULL is not "inactive".
            "master_is_active": airline.is_active is not False,
            "ids": ids,
            "id_count": len(ids),
            "active_id_count": sum(1 for i in ids if i["is_active"]),
        })
    return entries
