"""How a spec-driven statement row is DISPLAYED: its ordered columns and its flattened record.

Lifted out of ``api/v1/statements.py`` so the ``/columns`` + ``/records`` endpoints and the
Workspace report download (``services/report_download``) render a TGQ HMPR / NDC / LCC ledger
/ Third Party row from ONE definition. Before the move the column list and the per-row
flattening lived inside the router, where a second consumer could only copy them — and a
copy is exactly how the Format column once drifted (declared for a spec-driven type while the
serializer still branched on ``parser`` alone, so it rendered blank on every line).

Both functions are pure: no DB, no FastAPI. ``flatten_record`` reads plain attributes, so it
accepts an ORM instance, a SQLAlchemy ``Row`` or a ``SimpleNamespace`` alike.
"""
from __future__ import annotations

from typing import Any

from app.services import statement_spec as spec


def _seg_str(s: dict) -> str:
    return f"{s.get('route') or ''} {s.get('flight_no') or ''}".strip()


def display_columns(slug: str) -> list[dict]:
    """Ordered display columns: the spec's own, plus folded/derived/leg extras.

    Single source of truth so `/records` and `/columns` can never drift apart.
    """
    parser_name = spec.parser(slug)
    cols = spec.columns(slug)
    if parser_name == "lcc":
        cols = cols + [
            {"header": "Taxes", "field": "__taxes__"},
            {"header": "Segments", "field": "__segments__"},
            {"header": "SSR", "field": "__ssr__"},
            {"header": "Format", "field": "__format__"},
        ]
    elif parser_name:  # any other custom parser (DI / Divided PNR / Flown / Third Party …) is a flat ledger
        cols = cols + [{"header": "Format", "field": "__format__"}]
    elif spec.detect_format(slug):
        # A spec-driven type whose one table holds several vendor shapes (Third Party API:
        # MakeMyTrip and TBO). It has no `parser`, but it does write `source_format`, so it
        # earns the same Format column the flat ledgers get.
        cols = cols + [{"header": "Format", "field": "__format__"}]
    elif spec.fold_taxes(slug):
        cols = cols + [{"header": "Taxes", "field": "__taxes__"}]

    # Airline accounting code, lifted out of the ticket-number cell at ingest.
    tn = spec.ticket_no_config(slug)
    if tn:
        col = {"header": tn.get("header", "Airline_Code"), "field": tn.get("code_field", "airline_code")}
        i = next((k for k, c in enumerate(cols) if c["header"] == tn.get("before")), len(cols))
        cols = cols[:i] + [col] + cols[i:]

    if spec.split_config(slug):
        # First, not next to `Sectors`: that sits at column ~48 of 66, where a Leg column
        # would be invisible without scrolling — and which leg a row is is row identity.
        cols = [{"header": "Leg", "field": "__leg__"}] + cols

    money = spec.money_fields(slug)
    if money:
        cols = [{**c, "kind": "money"} if c["field"] in money else c for c in cols]
    return cols


def flatten_record(slug: str, row: Any) -> dict:
    """One stored row → the flat ``{field: value}`` record `/records` serves.

    ``data`` is copied (never mutated) and the derived ``__leg__`` / ``__taxes__`` /
    ``__segments__`` / ``__ssr__`` / ``__format__`` keys are added on exactly the conditions
    under which ``display_columns`` declares them.
    """
    parser_name = spec.parser(slug)
    # A spec-driven type can carry `source_format` too (Third Party API's two vendors), and
    # `display_columns` gives it a Format column on exactly this condition. The two have to
    # agree: a declared column that nothing fills is an empty column on every row.
    has_format = bool(parser_name) or spec.detect_format(slug) is not None

    d = dict(row.data or {})
    d["id"] = row.id
    if spec.split_config(slug):
        count = getattr(row, "sector_count", None)
        d["__leg__"] = f"{row.sector_index}/{count}" if count else ""
        d["__split__"] = getattr(row, "split_status", None)
        d["__legs__"] = count
    if parser_name == "lcc":
        d["__taxes__"] = " · ".join(
            f"{t.get('code')} {t.get('amount') or ''}".strip()
            for t in (row.taxes or []) if t.get("code")
        )
        d["__segments__"] = " · ".join(_seg_str(s) for s in (row.segments or []))
        d["__ssr__"] = " · ".join(
            f"{s.get('code')} {s.get('amount') or ''}".strip()
            for s in (row.ssr or []) if s.get("code")
        )
        d["__format__"] = row.source_format or ""
    elif has_format:
        # getattr, not attribute access: `has_format` is also true for a spec-driven
        # type, and nothing stops one being put on a plain `_StatementBase` table that
        # has no such column — the same guard `api/v1/statements._fmt_extra` makes on the
        # way in.
        d["__format__"] = getattr(row, "source_format", None) or ""
    elif spec.fold_taxes(slug):
        d["__taxes__"] = " · ".join(
            f"{t.get('type')} {t.get('amount') or ''}".strip()
            for t in (row.taxes or []) if t.get("type")
        )
    return d
