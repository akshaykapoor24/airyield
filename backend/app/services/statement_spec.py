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
from app.services import ndc_spec as _ndc

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

# ── Third Party ──────────────────────────────────────────────────────────────
# `summary` does double duty: it is the totals slab AND the only way these columns get
# money formatting, because `money_fields()` is (split divide_fields ∪ summary fields) and
# the third-party tables do not split. The declared-total block stays empty for them —
# `_summary` gates it on `_splits(model)` — which is right: the export has no total line.
_TP_SUMMARY = [
    {"field": "base_fare",         "label": "Basic Fare"},
    {"field": "yq",                "label": "YQ"},
    {"field": "other_taxes",       "label": "Other Taxes"},
    {"field": "commission_amount", "label": "Agent Commission"},
    {"field": "incentive_amount",  "label": "Incentive"},
    {"field": "net_amount",        "label": "Net Amount"},
]

# Filtering on `airline_master_name`, not the file's `airline_name`: the master spelling is
# what the deal was written against, so it is also the grouping a user reasons about.
_TP_GDS_FILTERS = [
    {"field": "airline_master_name", "label": "Airline",   "type": "select"},
    {"field": "segment_type",        "label": "Category",  "type": "select"},
    {"field": "ticket_status",       "label": "Status",    "type": "select"},
    {"field": "customer_name",       "label": "Customer",  "type": "select"},
    {"field": "ticket_number",       "label": "Ticket No", "type": "text"},
    {"field": "pnr",                 "label": "PNR",       "type": "text"},
    {"field": "passenger_name",      "label": "Passenger", "type": "text"},
]
_TP_LCC_FILTERS = [
    {"field": "airline_master_name", "label": "Airline",   "type": "select"},
    {"field": "ticket_status",       "label": "Status",    "type": "select"},
    {"field": "customer_name",       "label": "Customer",  "type": "select"},
    {"field": "pnr",                 "label": "PNR",       "type": "text"},
    {"field": "passenger_name",      "label": "Passenger", "type": "text"},
]


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
    # NDC — the airline's own (New Distribution Capability) sales export. See
    # services/ndc_spec.py for the columns and for why this one is mapped rather than read
    # verbatim like TGQ HMPR: every airline runs its own NDC portal and names the same
    # field differently, so `supports_mapping` puts the mapping in front of the uploader
    # instead of guessing. `fold_taxes` is off — an NDC export names its taxes as columns
    # (`YQ Tax`, `K3 Tax`, …) rather than as generic Tax_TypeN/TaxN pairs.
    #
    # The `ndc` table carries the per-sector leg columns (they were added alongside TGQ
    # HMPR's) but splitting stays off: `Sectors` on an NDC line is a single leg.
    "ndc": {
        "label": "NDC",
        "columns": _ndc.COLUMNS,
        "aliases": _ndc.ALIASES,
        "group_order": _ndc.GROUP_ORDER,
        "fold_taxes": False,
        "supports_mapping": True,
        "required_groups": _ndc.REQUIRED_GROUPS,
        "advisory_groups": _ndc.ADVISORY_GROUPS,
        "filters": _ndc.FILTERS,
        "summary": _ndc.SUMMARY,
        "money": _ndc.MONEY_FIELDS,
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
    #
    # `resolve_airline` — unlike the LCC types, these files DO name their carrier, but they
    # name it as free text ("TURKISH AIRLINES") and as a ticket prefix ("235"), neither of
    # which any downstream join can use. So the airline master is consulted at ingest and
    # the row is stamped with the canonical name and the 2-letter code. Opt-in per type
    # because TGQ HMPR and NDC share this router and already carry a usable code.
    #
    # `requires_supplier` — the uploader must name the consolidator from the
    # platform-admin Supplier master. A third-party statement is issued BY one and nothing
    # in the file names them, so the uploader is the only source of that fact, and without
    # it the B2B deal has nothing to match against. The Supplier master, not Agency Master:
    # it is the same list `deals.supplier_name` is picked from, so both sides of the match
    # name the same thing. Same opt-in discipline as `requires_airline_id`.
    "tp-gds": {
        "label": "GDS",
        "parser": "tp-gds",
        "columns": _flat.TP_GDS_DISPLAY,
        "fold_taxes": False,
        "resolve_airline": True,
        "requires_supplier": True,
        "supports_mapping": True,
        "filters": _TP_GDS_FILTERS,
        "summary": _TP_SUMMARY,
    },
    "tp-lcc": {
        "label": "LCC",
        "parser": "tp-lcc",
        "columns": _flat.TP_LCC_DISPLAY,
        "fold_taxes": False,
        "resolve_airline": True,
        "requires_supplier": True,
        "supports_mapping": True,
        "filters": _TP_LCC_FILTERS,
        "summary": _TP_SUMMARY,
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


def requires_supplier(slug: str) -> bool:
    """Must the uploader name the consolidator from the Supplier master?

    True for the third-party types. Their statements are issued BY a vendor the file never
    names, so the uploader is the only source of it — and it is what the B2B deal is
    matched against (services/deal_matching.py's supplier guard).

    A plain bool, unlike the channel this used to return: `suppliers` has one row per
    branch with a unique code and no channel, so the id alone identifies the counterparty
    and there is nothing left to validate it against.

    Opt-in per type, exactly like `requires_airline_id`: BSP, TGQ HMPR, NDC and the LCC
    ledger types share this router and must not grow the requirement.
    """
    s = spec_for(slug)
    return bool(s and s.get("requires_supplier"))


def supports_mapping(slug: str) -> bool:
    """Can this type be uploaded through the map-review-confirm wizard?

    True for the third-party types and for NDC. A consolidator writes whatever spreadsheet
    it likes, and every airline's NDC portal names the same field differently — the alias
    map covers the shapes we have seen, and the wizard covers the ones we have not, by
    letting the uploader say which of their columns is which. The remaining types on this
    router come out of one system with one fixed export (BSPlink, a GDS), so a mapping step
    there would be a question with one possible answer.
    """
    s = spec_for(slug)
    return bool(s and s.get("supports_mapping"))


def aliases(slug: str) -> dict[str, list[str]]:
    """{field: [source header, …]} used to auto-map an arbitrary file onto this spec.

    Only the spec-driven mapped types declare this; the `parser` types keep their alias map
    inside their own builder (services/flat_statement.py), which is also where their
    mapping comes from. Empty here means "match on the canonical header only".
    """
    s = spec_for(slug)
    return dict(s.get("aliases") or {}) if s else {}


def group_order(slug: str) -> list[str]:
    """Section order for the mapping screen; unlisted groups fall to the end in spec order."""
    s = spec_for(slug)
    return list(s.get("group_order") or []) if s else []


def required_groups(slug: str) -> list[dict]:
    """Field groups the confirm step REFUSES a mapping without ("at least one of these").

    Falls back to the flat-statement rule, which is what the `parser` types are checked
    against — so a type that declares neither keeps exactly the behaviour it had.
    """
    s = spec_for(slug)
    return list((s or {}).get("required_groups") or _flat.REQUIRED_GROUPS)


def advisory_groups(slug: str) -> list[dict]:
    """Field groups the confirm step ACCEPTS but warns about. See `required_groups`."""
    s = spec_for(slug)
    return list((s or {}).get("advisory_groups") or _flat.ADVISORY_GROUPS)


def resolves_airline(slug: str) -> bool:
    """Should ingest look this type's carrier up in the airline master?

    True for the third-party types, whose files name the carrier only as free text and a
    ticket prefix — neither of which the deal matcher or PLB accrual can join on. See
    services/tp_airline_resolution.py.
    """
    s = spec_for(slug)
    return bool(s and s.get("resolve_airline"))


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
    """Fields the UI should right-align and thousands-format.

    Divided ∪ summarised ∪ an explicit `money` list. The first two are inferred because a
    field that is allocated across legs or totalled in the slab is necessarily an amount;
    the explicit list is for the amounts that are neither — NDC has 25 money columns and
    only six of them are worth a total.
    """
    s = spec_for(slug)
    if not s:
        return set()
    out = set((s.get("split_sectors") or {}).get("divide_fields") or [])
    out |= {f["field"] for f in (s.get("summary") or [])}
    out |= set(s.get("money") or ())
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
