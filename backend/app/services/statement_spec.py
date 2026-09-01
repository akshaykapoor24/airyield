"""Spec registry for generic, spec-driven vendor statements (TGQ HMPR, and later
NDC / LCC / GDS). Each type declares its ordered fixed-column headers; the repeating
``Tax_TypeN`` / ``TaxN`` pairs are NOT columns — the parser folds them into a JSONB
``taxes`` array (so any number of taxes is supported with no schema change).

Adding a new statement type = add an entry here + flip its registry entry on the
frontend. No new table, model, router, or UI.
"""
from __future__ import annotations

import re

from app.services import lcc_statement as _lcc
from app.services import di_statement as _di
from app.services import divided_pnr as _dp
from app.services import flown_report as _fr
from app.services import cta_bta_report as _cb
from app.services import flat_statement as _flat

# ── TGQ HMPR ─────────────────────────────────────────────────────────────────
# The user's column list MINUS the Tax_TypeN/TaxN pairs (those fold into `taxes`).
_TGQ_HMPR_HEADERS = [
    "SNO", "PCC", "Date", "Airline", "Ticket_Date", "Ticket_No", "Air_Name", "Air_PNR",
    "Gal_PNR", "Pax_Name", "Booking_Signon", "Booking_PCC", "BookingAgencyName",
    "Ticketing_Signon", "Ticket_Type", "Document_Type", "Fare_Basis", "Fare_Const_Type",
    "Base_Fare", "BaseFareCurrency",
    # ── Tax_Type1/Tax1 … Tax_TypeN/TaxN fold into the JSONB `taxes` array here ──
    "WOTax", "YQTax", "Other_Tax", "Total_Tax", "AirlineFee", "Total_Fare", "Comm(%)",
    "Comm_Amount", "FOP", "FOP_Details", "CC_Auth", "CC_DOExpiry", "AI_Code", "Tour_Code",
    "Value_Code", "Net_Remit", "Net_Fare", "Actual_Selling_Fare", "Invoice_Fare",
    "Transaction_Type", "EXCHANGED_FOR", "Multiple_Receivables", "Invoice_No",
    "Stock_Control_No", "STP_No", "Void__Exchange__Refund_Date", "Sectors", "FlightNo",
    "TravelDt", "Class", "Coupon_Status", "Refund_Type", "Total_Refund_Amount", "AC_ACCT",
    "TripID", "ROE", "NUC", "Fare Ladder", "ClientEntityName", "BusinessPhoneNumber",
    "BusinessEmailAddress", "EntityAddressLine1", "GSTN",
]

# The index (into the fixed header list) after which the Tax_TypeN/TaxN pairs sit in
# the source file — used only to build a friendly blank template.
_TGQ_HMPR_TAX_AFTER = "BaseFareCurrency"

# ── TGQ HMPR: per-sector expansion ───────────────────────────────────────────
# An airline statement carries one line per TICKET, but `Sectors` holds every flown
# sector ("BOM/DEL DEL/MNL MNL/DEL DEL/BOM") and FlightNo / TravelDt / Class /
# Coupon_Status run parallel to it, space-separated. On ingest we expand that into one
# row per sector and allocate every money column across the legs (see
# services/sector_split.py). Field keys below are `norm()` outputs, not raw headers.
_TGQ_SPLIT = {
    "sector_field": "sectors",
    "parallel_fields": [
        # "pad" leaves a leg blank when the source has too few tokens — inventing a
        # flight number or a travel date would be worse than showing nothing.
        {"field": "flightno", "on_short": "pad"},
        {"field": "traveldt", "on_short": "pad"},
        # A single "V" against 4 sectors genuinely means V on every leg.
        {"field": "class", "on_short": "broadcast"},
        {"field": "coupon_status", "on_short": "broadcast"},
    ],
    # Ticket-level amounts. NOT divided: `comm` (a percentage — and comm_amount/base_fare
    # stays correct when both are divided), `roe` (dividing it would break the
    # NUC x ROE ~= Base_Fare identity that dividing nuc and base_fare together preserves),
    # `fare_ladder` (describes the whole ticket), `multiple_receivables` (not a currency),
    # and `fop_details` (an amount can be embedded in free text — not safely parseable).
    "divide_fields": [
        "base_fare", "wotax", "yqtax", "other_tax", "total_tax", "airlinefee",
        "total_fare", "comm_amount", "net_remit", "net_fare",
        "actual_selling_fare", "invoice_fare", "total_refund_amount", "nuc",
    ],
    "divide_taxes": True,   # mandatory, or a leg's taxes stop summing to its Total_Tax
    "precision": 2,         # set 0 to allocate in whole rupees (also sum-preserving)
    "mode": "equal",        # "fare_ladder" (NUC-weighted) reserved — see sector_split docs
}

# Ticket_No arrives as "<airline accounting code> <document serial>" — "098 5805708071"
# (098 = Air India), "618 5800920932-933". Lift the code into its own column so Ticket_No
# holds only the document number. `before` positions the new column in the display order.
_TGQ_TICKET_NO = {
    "source": "ticket_no",
    "code_field": "airline_code",
    "header": "Airline_Code",
    "before": "Ticket_No",
}

# Drives the drill-in filter toolbar. "select" is an exact match fed by /records/facets;
# "text" is a case-insensitive contains.
_TGQ_FILTERS = [
    {"field": "airline",     "label": "Airline",      "type": "select"},
    {"field": "air_name",    "label": "Airline Name", "type": "select"},
    {"field": "ticket_date", "label": "Ticket Date",  "type": "select"},
    {"field": "traveldt",    "label": "Travel Date",  "type": "select"},
    {"field": "ticket_no",   "label": "Ticket No",    "type": "text"},
    {"field": "air_pnr",     "label": "Air PNR",      "type": "text"},
    {"field": "gal_pnr",     "label": "Gal PNR",      "type": "text"},
    {"field": "pax_name",    "label": "Pax Name",     "type": "text"},
]

# Totalled over the whole filtered set and shown in the slab above the table.
_TGQ_SUMMARY = [
    {"field": "base_fare",   "label": "Base Fare"},
    {"field": "total_tax",   "label": "Total Tax"},
    {"field": "total_fare",  "label": "Total Fare"},
    {"field": "airlinefee",  "label": "Airline Fee"},
    {"field": "comm_amount", "label": "Commission"},
    {"field": "net_remit",   "label": "Net Remit"},
]

# TGQ exports end with a grand-total line. Both conditions are ANDed so a real PCC or
# agency literally named "TOTAL" is never mistaken for it.
_TGQ_TOTAL_ROW = {
    "value_in": ["total", "totals", "grand total", "grand totals"],
    "require_blank": ["ticket_no", "pax_name", "sectors"],
}

STATEMENT_SPECS: dict[str, dict] = {
    "tgq-hmpr": {
        "label": "TGQ HMPR",
        "headers": _TGQ_HMPR_HEADERS,
        "fold_taxes": True,
        "tax_after": _TGQ_HMPR_TAX_AFTER,
        "template_tax_pairs": 20,   # how many Tax_TypeN/TaxN pairs to seed in the blank template
        "split_sectors": _TGQ_SPLIT,
        "split_ticket_no": _TGQ_TICKET_NO,
        "filters": _TGQ_FILTERS,
        "summary": _TGQ_SUMMARY,
        "total_row": _TGQ_TOTAL_ROW,
    },
    "ndc": {
        "label": "NDC",
        "headers": _TGQ_HMPR_HEADERS,   # same airline-ticket shape as TGQ HMPR for now
        "fold_taxes": True,
        "tax_after": _TGQ_HMPR_TAX_AFTER,
        "template_tax_pairs": 20,
        # NDC shares the TGQ HMPR column shape, so per-sector splitting, filters and the
        # summary slab work here too — the `ndc` table already carries the leg columns.
        # Add "split_sectors": _TGQ_SPLIT, "filters": _TGQ_FILTERS, "summary": _TGQ_SUMMARY,
        # "total_row": _TGQ_TOTAL_ROW to switch it on (then re-upload or re-process batches).
    },
    # LCC Detailed Statement now has its OWN dedicated batch+rows schema, wizard router
    # (api/v1/lcc_detailed.py) and spec (services/lcc_detailed_spec.py) — it is no longer
    # routed through this generic registry.
    # LCC DI (Deposit) Statement — flat deposit ledger, two formats (see services/di_statement.py).
    "lcc-di": {
        "label": "DI Statement",
        "parser": "di",
        "columns": _di.DISPLAY_COLUMNS,
        "fold_taxes": False,
        # Like LCC Detailed, an LCC export names no carrier — so the uploader declares
        # it from their Airline Master. Opt-in per type: the BSP, TGQ HMPR, NDC and
        # third-party types below share this router and must NOT grow the requirement.
        "requires_airline_id": True,
    },
    # LCC Divided PNR Statement — parent→child PNR split ledger (see services/divided_pnr.py).
    "lcc-divided-pnr": {
        "label": "Divided PNR",
        "parser": "divided-pnr",
        "columns": _dp.DISPLAY_COLUMNS,
        "fold_taxes": False,
        "requires_airline_id": True,
    },
    # LCC Flown Report — flown/uplifted segment ledger (see services/flown_report.py).
    "lcc-flown-report": {
        "label": "Flown Report",
        "parser": "flown-report",
        "columns": _fr.DISPLAY_COLUMNS,
        "fold_taxes": False,
        "requires_airline_id": True,
    },
    # LCC CTA/BTA Report — lodged-account (Central/Business Travel Account) settlement
    # ledger (see services/cta_bta_report.py).
    "lcc-cta-bta": {
        "label": "CTA/BTA Report",
        "parser": "cta-bta",
        "columns": _cb.DISPLAY_COLUMNS,
        "fold_taxes": False,
        "requires_airline_id": True,
    },
    # Third Party — a consolidator/big agency sends the sub-agency a GDS/LCC statement of
    # the bookings it made through them (see services/flat_statement.py).
    "tp-gds": {
        "label": "GDS",
        "parser": "tp-gds",
        "columns": _flat.TP_GDS_DISPLAY,
        "fold_taxes": False,
    },
    "tp-lcc": {
        "label": "LCC",
        "parser": "tp-lcc",
        "columns": _flat.TP_LCC_DISPLAY,
        "fold_taxes": False,
    },
}

ADJ_LIKE_SLUGS = tuple(STATEMENT_SPECS)


def norm(header: str) -> str:
    """'Comm(%)' -> 'comm'; 'Fare Ladder' -> 'fare_ladder'; 'BaseFareCurrency' -> 'basefarecurrency'."""
    h = str(header).lower().replace("'", "").replace("’", "")
    h = re.sub(r"[^a-z0-9]+", "_", h)
    return h.strip("_")


def spec_for(slug: str) -> dict | None:
    return STATEMENT_SPECS.get((slug or "").lower())


def headers(slug: str) -> list[str]:
    s = spec_for(slug)
    return list(s.get("headers") or []) if s else []


def columns(slug: str) -> list[dict]:
    """Ordered [{header, field}] — drives the repository table. Explicit `columns` (e.g. LCC)
    take precedence over a verbatim `headers` list."""
    s = spec_for(slug)
    if not s:
        return []
    if s.get("columns"):
        return list(s["columns"])
    return [{"header": h, "field": norm(h)} for h in s["headers"]]


def fields(slug: str) -> list[str]:
    return [c["field"] for c in columns(slug)]


def parser(slug: str) -> str | None:
    s = spec_for(slug)
    return s.get("parser") if s else None


def fold_taxes(slug: str) -> bool:
    s = spec_for(slug)
    return bool(s and s.get("fold_taxes"))


def requires_airline_id(slug: str) -> bool:
    """Must the uploader declare which of their Airline Master ids this file covers?

    True for the LCC types, whose exports name no carrier — the id is the only thing
    that identifies it, exactly as for LCC Detailed. False everywhere else: a BSP,
    TGQ HMPR, NDC or third-party statement carries its own airline, and these types
    share one upload endpoint and one frontend view, so the flag is what stops the
    requirement leaking onto them.
    """
    s = spec_for(slug)
    return bool(s and s.get("requires_airline_id"))


# ── Optional, opt-in behaviours ──────────────────────────────────────────────
# Every accessor below returns None/[] for a slug that doesn't declare the key, so the
# router and the shared frontend view short-circuit and behave exactly as before.

def split_config(slug: str) -> dict | None:
    """Per-sector expansion config, or None when this type is one row per ticket."""
    s = spec_for(slug)
    return s.get("split_sectors") if s else None


def ticket_no_config(slug: str) -> dict | None:
    """How to split the ticket-number cell into airline code + serial, or None."""
    s = spec_for(slug)
    return s.get("split_ticket_no") if s else None


def filter_specs(slug: str) -> list[dict]:
    """Ordered [{field, label, type}] driving the drill-in filter toolbar."""
    s = spec_for(slug)
    return list(s.get("filters") or []) if s else []


def summary_fields(slug: str) -> list[dict]:
    """Ordered [{field, label}] totalled over the filtered set for the summary slab."""
    s = spec_for(slug)
    return list(s.get("summary") or []) if s else []


def total_row_config(slug: str) -> dict | None:
    """How to recognise the file's own declared grand-total line, or None."""
    s = spec_for(slug)
    return s.get("total_row") if s else None


def money_fields(slug: str) -> set[str]:
    """Fields the UI should right-align and thousands-format (divided ∪ summarised)."""
    s = spec_for(slug)
    if not s:
        return set()
    out = set((s.get("split_sectors") or {}).get("divide_fields") or [])
    out |= {f["field"] for f in (s.get("summary") or [])}
    return out


def template_headers(slug: str) -> list[str]:
    """Fixed headers with the Tax_Type/Tax pairs re-inserted, for a blank upload template."""
    s = spec_for(slug)
    if not s:
        return []
    if not s.get("headers"):
        return [c["header"] for c in columns(slug)]   # explicit-column specs (e.g. LCC)
    hs = list(s["headers"])
    if s.get("fold_taxes"):
        pairs: list[str] = []
        for i in range(1, int(s.get("template_tax_pairs", 20)) + 1):
            pairs += [f"Tax_Type{i}", f"Tax{i}"]
        after = s.get("tax_after")
        idx = (hs.index(after) + 1) if after in hs else len(hs)
        hs = hs[:idx] + pairs + hs[idx:]
    return hs
