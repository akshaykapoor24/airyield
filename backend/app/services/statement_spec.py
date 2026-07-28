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

STATEMENT_SPECS: dict[str, dict] = {
    "tgq-hmpr": {
        "label": "TGQ HMPR",
        "headers": _TGQ_HMPR_HEADERS,
        "fold_taxes": True,
        "tax_after": _TGQ_HMPR_TAX_AFTER,
        "template_tax_pairs": 20,   # how many Tax_TypeN/TaxN pairs to seed in the blank template
    },
    "ndc": {
        "label": "NDC",
        "headers": _TGQ_HMPR_HEADERS,   # same airline-ticket shape as TGQ HMPR for now
        "fold_taxes": True,
        "tax_after": _TGQ_HMPR_TAX_AFTER,
        "template_tax_pairs": 20,
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
    },
    # LCC Divided PNR Statement — parent→child PNR split ledger (see services/divided_pnr.py).
    "lcc-divided-pnr": {
        "label": "Divided PNR",
        "parser": "divided-pnr",
        "columns": _dp.DISPLAY_COLUMNS,
        "fold_taxes": False,
    },
    # LCC Flown Report — flown/uplifted segment ledger (see services/flown_report.py).
    "lcc-flown-report": {
        "label": "Flown Report",
        "parser": "flown-report",
        "columns": _fr.DISPLAY_COLUMNS,
        "fold_taxes": False,
    },
    # LCC CTA/BTA Report — lodged-account (Central/Business Travel Account) settlement
    # ledger (see services/cta_bta_report.py).
    "lcc-cta-bta": {
        "label": "CTA/BTA Report",
        "parser": "cta-bta",
        "columns": _cb.DISPLAY_COLUMNS,
        "fold_taxes": False,
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
