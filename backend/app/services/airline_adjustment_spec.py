"""Column specifications for airline adjustment uploads (ADM / ACM / RA).

Single source of truth shared by the model, the Alembic migration, the upload
parser and the ``/columns`` API. Each type is an ordered list of the exact IATA
BSPlink export headers. The DB column / attribute name for a header is derived
deterministically by :func:`norm` (lower-case, drop apostrophes, non-alphanumeric
runs -> ``_``) so the parser can map an uploaded file's headers back to fields
without a hand-maintained alias table.
"""
from __future__ import annotations

import re

# ── ordered export headers, verbatim from the IATA ADM/ACM/RA files ──────────
ADM_HEADERS: list[str] = [
    "ISO Country Code", "Type", "Country / Territory", "Issue Date",
    "Reason for Issue", "Document Number", "Status", "Date of Ticket Issue",
    "Airline Code", "Agent Code", "Airline's Fare", "Agent's Fare",
    "Airline's Tax", "Agent's Tax", "Airline's Commission", "Agent's Commission",
    "Airline's Supplementary Commission", "Agent's Supplementary Commission",
    "Airline's Tax on Commission", "Agent's Tax on Commission",
    "Airline's Cancellation Penalty", "Agent's Cancellation Penalty",
    "Airline's Miscellaneous Fee", "Agent's Miscellaneous Fee", "Amount",
    "Currency", "Statistical Code", "RTDN Type", "Issue Reason", "Primary Reason",
    "Reporting Date", "Period", "Dispute Date", "Forward to GDS",
    "Forward to GDS Date", "Contact Name", "Contact Email", "Contact Phone",
    "Dispute Reason", "Forward to GDS Reason", "Related Document",
    "Dispute Rejection Reason", "Dispute Approval Remark", "Sent to DPC",
]

ACM_HEADERS: list[str] = [
    "ISO Country Code", "Type", "Country / Territory", "Issue Date",
    "Reason for Issue", "Document Number", "Status", "Date of Ticket Issue",
    "Airline Code", "Agent Code", "Airline's Fare", "Agent's Fare",
    "Airline's Tax", "Agent's Tax", "Airline's Commission", "Agent's Commission",
    "Airline's Supplementary Commission", "Agent's Supplementary Commission",
    "Airline's Tax on Commission", "Agent's Tax on Commission",
    "Airline's Cancellation Penalty", "Agent's Cancellation Penalty",
    "Airline's Miscellaneous Fee", "Agent's Miscellaneous Fee", "Amount",
    "Currency", "Statistical Code", "RTDN Type", "Issue Reason", "Reporting Date",
    "Period", "Dispute Date", "Contact Name", "Contact Email", "Contact Phone",
    "Dispute Reason", "Related Document", "Dispute Rejection Reason",
    "Dispute Approval Remark", "Sent to DPC",
]

RA_HEADERS: list[str] = [
    "ISO Country Code", "Country / Territory", "Document Number", "RTDN Number",
    "Status", "Airline Code", "Agent Code", "Application Date",
    "Authorization Date", "Rejection Date", "Reporting Date", "Period",
    "Currency", "Forms of Payment", "Amount", "Passenger", "ET", "Sent to DPC",
    "Airline Remark", "Reason for Refund", "Rejection Reason", "Deletion Reason",
    "Final", "Days Left", "Process Stopped",
]

HEADERS: dict[str, list[str]] = {
    "adm": ADM_HEADERS,
    "acm": ACM_HEADERS,
    "ra": RA_HEADERS,
}

ADJUSTMENT_TYPES = tuple(HEADERS.keys())  # ("adm", "acm", "ra")


def norm(header: str) -> str:
    """Normalize a column header to its DB field name.

    "Airline's Fare" -> "airlines_fare"; "Country / Territory" -> "country_territory".
    """
    h = str(header).lower().replace("'", "").replace("’", "")
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


def fields(adj_type: str) -> list[str]:
    """Ordered DB field names for a type."""
    return [norm(h) for h in HEADERS[adj_type.lower()]]


def columns(adj_type: str) -> list[dict[str, str]]:
    """Ordered [{header, field}] pairs — served to the frontend to render tables."""
    return [{"header": h, "field": norm(h)} for h in HEADERS[adj_type.lower()]]


def header_to_field_map(adj_type: str) -> dict[str, str]:
    """{normalized-header -> field}, used to match an uploaded file's columns."""
    return {norm(h): norm(h) for h in HEADERS[adj_type.lower()]}
