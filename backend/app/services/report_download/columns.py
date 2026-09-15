"""The Combined sheet's 62 common columns, the transaction-type vocabulary, the sign rules,
the Counts-In-Net reason strings and the Data Flags legend.

This module is the CONTRACT between mappers, linking, summary and the workbook writer:
mappers produce dicts keyed by ``Col.key``; the writer orders them by ``COMBINED_COLUMNS``.
Nothing here touches the DB or openpyxl.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.services.report_download.types import LinkResult, MapCtx

ColKind = Literal["text", "int", "date", "datetime", "money", "flag"]
# S = signed money, U = unsigned (magnitude) money, "" = not money
SignRule = Literal["S", "U", ""]


@dataclass(frozen=True)
class Col:
    key: str
    header: str
    kind: ColKind = "text"
    width: int = 14
    sign: SignRule = ""
    meaning: str = ""


COMBINED_COLUMNS: tuple[Col, ...] = (
    # ── provenance ──────────────────────────────────────────────────────────
    Col("category", "Category", width=11, meaning="Vendors → Statements category: BSP | LCC | Third Party"),
    Col("source_type", "Source Type", width=16, meaning="Exact statement type the row came from"),
    Col("source_file", "Source File", width=28, meaning="Original uploaded file name"),
    Col("upload_id", "Upload ID", width=20, meaning="Upload (batch) identifier"),
    Col("uploaded_at", "Uploaded At (UTC)", "datetime", 18, meaning="When the file was uploaded"),
    Col("row_ref", "Row Ref", width=22, meaning="table:id reference; joins to the detail sheet"),
    Col("counts_in_net", "Counts In Net", width=26, meaning="Yes, or No – reason. Only Yes rows are totalled on Summary"),
    # ── parties ─────────────────────────────────────────────────────────────
    Col("settled_with", "Settled With", width=26, meaning="BSP, airline direct, consolidator or aggregator"),
    Col("agent_signon", "Agent / Sign-on", width=14, meaning="IATA agent code, portal login or GDS sign-on"),
    Col("airline_numeric", "Airline Numeric Code", width=8, meaning="3-digit IATA accounting (ticket stock) code"),
    Col("airline_code", "Airline Code", width=8, meaning="2-letter IATA airline designator"),
    Col("airline_name", "Airline Name", width=22, meaning="Validating / operating airline"),
    Col("booking_party_gstin", "Booking Party GSTIN", width=17, meaning="GSTIN of the booking party where the source carries it"),
    # ── document ────────────────────────────────────────────────────────────
    Col("product", "Product", width=8, meaning="Air | Hotel | Train | Bus | Car | other (Third Party API)"),
    Col("transaction_type", "Transaction Type", width=14, meaning="Canonical type, see Read Me"),
    Col("source_txn_type", "Source Txn Type", width=16, meaning="The source's own type/status text"),
    Col("document_number", "Document Number", width=16, meaning="The settlement document itself"),
    Col("ticket_number", "Ticket Number", width=15, meaning="13-digit ticket (code + serial) the row concerns"),
    Col("related_document", "Related Document", width=15, meaning="Original / related document (RTDN, exchange, memo target)"),
    Col("status", "Status", width=14, meaning="Source status text (coupon, memo, booking)"),
    # ── booking ─────────────────────────────────────────────────────────────
    Col("airline_pnr", "Airline PNR", width=10),
    Col("gds_ref", "GDS / Supplier Ref", width=14),
    Col("invoice_ref", "Invoice / Booking Ref", width=16),
    Col("passenger_name", "Passenger Name", width=24),
    Col("pax_count", "Pax Count", "int", 7),
    # ── dates ───────────────────────────────────────────────────────────────
    Col("issue_date", "Issue / Txn Date", "date", 12, meaning="Issue / transaction date (period basis)"),
    Col("booking_date", "Booking Date", "date", 12),
    Col("travel_date", "Travel Date", "date", 12, meaning="First-segment departure date"),
    Col("settlement_period", "Settlement Period", width=16),
    # ── itinerary ───────────────────────────────────────────────────────────
    Col("sector", "Sector", width=18),
    Col("dom_intl", "Dom / Intl", width=12),
    Col("flight_no", "Flight No", width=12),
    Col("booking_class", "Class (RBD)", width=8),
    Col("fare_basis", "Fare Basis / Family", width=12),
    Col("tour_code", "Tour / Deal Code", width=14),
    # ── money ───────────────────────────────────────────────────────────────
    Col("currency", "Currency", width=8),
    Col("base_fare", "Base Fare", "money", 12, "S"),
    Col("yq", "YQ", "money", 10, "S"),
    Col("yr", "YR", "money", 10, "S"),
    Col("k3", "K3 (GST on Fare)", "money", 11, "S", meaning="GST on air fare (code K3 / LCC GST). Never IN (UDF)"),
    Col("other_taxes", "Other Taxes & Fees", "money", 12, "S"),
    Col("total_taxes", "Total Taxes", "money", 12, "S"),
    Col("gross_amount", "Gross Amount", "money", 13, "S"),
    Col("penalty", "Penalty / Change Fee", "money", 11, "U", meaning="Unsigned, except BSP (as printed)"),
    Col("ancillary", "Ancillary (SSR/EMD)", "money", 11, "S"),
    Col("service_fee", "Service Fee", "money", 11, "U"),
    Col("discount", "Discount", "money", 10, "U"),
    Col("gst_on_service", "GST on Service", "money", 11, "U", meaning="GST on fees/services, not K3"),
    Col("commission", "Commission", "money", 11, "S"),
    Col("supp_commission", "Supp. Commission", "money", 11, "S"),
    Col("tax_on_commission", "Tax on Commission", "money", 11, "S"),
    Col("incentive_declared", "Incentive (Declared)", "money", 11, "S"),
    Col("tds", "TDS", "money", 9, "U"),
    Col("tcs", "TCS", "money", 9, "U"),
    Col("net_payable", "Net Payable", "money", 13, "S", meaning="Net owed to/by the Settled With party"),
    Col("form_of_payment", "Form of Payment", width=10),
    # ── links ───────────────────────────────────────────────────────────────
    Col("linked_document", "Linked Document", width=15),
    Col("linked_via", "Linked Via", width=24),
    Col("also_in_bsp", "Also In BSP Billing", "flag", 22),
    Col("not_in_bsp", "Not In BSP", "flag", 22),
    Col("tgq_enriched", "TGQ Enriched", "flag", 14),
    Col("data_flags", "Data Flags", "flag", 30, meaning="; -separated codes, see Read Me"),
)

COMBINED_KEYS: tuple[str, ...] = tuple(c.key for c in COMBINED_COLUMNS)
COMBINED_HEADERS: tuple[str, ...] = tuple(c.header for c in COMBINED_COLUMNS)
COL_BY_KEY: dict[str, Col] = {c.key: c for c in COMBINED_COLUMNS}
MONEY_KEYS: tuple[str, ...] = tuple(c.key for c in COMBINED_COLUMNS if c.kind == "money")

# ── categories / products ────────────────────────────────────────────────────
CAT_BSP, CAT_LCC, CAT_TP = "BSP", "LCC", "Third Party"
PRODUCT_AIR = "Air"

# ── transaction types ────────────────────────────────────────────────────────
SALE, EXCHANGE, EMD, REFUND = "SALE", "EXCHANGE", "EMD", "REFUND"
ADM, ACM, CANCELLATION, AGENT_FEE, VOID = "ADM", "ACM", "CANCELLATION", "AGENT_FEE", "VOID"
FLOWN, DEPOSIT, PAYMENT, CREDIT_TRANSFER, PNR_DIVIDE = "FLOWN", "DEPOSIT", "PAYMENT", "CREDIT_TRANSFER", "PNR_DIVIDE"
NON_BILLABLE, UNKNOWN = "NON_BILLABLE", "UNKNOWN"

TXN_TYPES: dict[str, str] = {
    SALE: "Ticket issue / booking",
    EXCHANGE: "Reissue / exchange",
    EMD: "Ancillary document or line (EMD, paid seat, baggage)",
    REFUND: "Refund, refund application or supplier credit",
    ADM: "Agency debit memo (incl. BSP SPDR)",
    ACM: "Agency credit memo (incl. BSP SPCR)",
    CANCELLATION: "Cancellation charge (BSP CANX/CANN, aggregator retained amount)",
    AGENT_FEE: "Agent service fee collected through BSP (TASF)",
    VOID: "Void / cancelled booking",
    FLOWN: "LCC flown (uplifted) record",
    DEPOSIT: "LCC deposit / agency ledger entry",
    PAYMENT: "Money movement with no fare (LCC payment, CTA/BTA settlement)",
    CREDIT_TRANSFER: "LCC account credit from a cancelled booking (Funds Added)",
    PNR_DIVIDE: "LCC divided PNR link",
    NON_BILLABLE: "Not a sale: pending, hold, failed, expired, rejected, no amount",
    UNKNOWN: "Type not recognised (flag TXN_UNMAPPED)",
}

# Sign applied by normalize.signed(v, type) for TYPE_SIGNED sources.
# +1 / -1 force the sign of |v|; None keeps the stored value unchanged.
TYPE_SIGN: dict[str, Optional[int]] = {
    SALE: 1, EXCHANGE: 1, EMD: 1, ADM: 1, CANCELLATION: 1, FLOWN: 1,
    REFUND: -1, ACM: -1,
    AGENT_FEE: None, VOID: None, DEPOSIT: None, PAYMENT: None,
    CREDIT_TRANSFER: None, PNR_DIVIDE: None, NON_BILLABLE: None, UNKNOWN: None,
}

SIGN_RULES_TEXT: tuple[tuple[str, str], ...] = (
    ("Convention", "Money is from the agency's side: + the agency owes / is charged; − the agency is owed / credited."),
    ("As stored", "BSP Detailed (printed signs, incl. card-paid balances, refunds with penalty, negative CANX), LCC Detailed, LCC ledgers."),
    ("Type-signed", "NDC, TGQ HMPR, ADM/ACM/RA, Third Party GDS/LCC/API: + on SALE/EXCHANGE/EMD/ADM/CANCELLATION, − on REFUND/ACM; other types as stored."),
    ("Unsigned columns", "Penalty (except BSP), Service Fee, Discount, GST on Service, TDS, TCS are magnitudes."),
    ("Detail sheets", "Every detail sheet shows values exactly as stored in the upload."),
)

# ── Counts In Net ────────────────────────────────────────────────────────────
NET_YES = "Yes"
NET_SUPERSEDED = "No – superseded by newer upload"
NET_MEMO_IN_BILLING = "No – in BSP billing (this report)"
NET_MEMO_OTHER_UPLOAD = "No – in another BSP upload"
NET_MEMO_OTHER_PERIOD = "No – in BSP billing (other period)"
NET_MEMO_NOT_BILLED = "No – not yet billed in BSP"          # + " (status: …[, sent to DPC])"
NET_TGQ_NOT_IN_BSP = "No – GDS record, not in BSP"
NET_TGQ_OTHER_UPLOAD = "No – in another BSP upload"
NET_TGQ_OUTSIDE_PERIOD = "No – BSP row outside period"
NET_TGQ_UNMATCHABLE = "No – cannot match (no ticket no.)"
NET_NDC_IN_BSP = "No – settled in BSP"
NET_LCC_PAYMENT = "No – payment movement"
NET_LEDGER = "No – ledger (see LCC Detailed)"
NET_NOT_A_SALE = "No – not a sale"
NET_CANCELLED = "No – cancelled"
NET_CANCELLED_VERIFY = "No – cancelled (verify)"
NET_NEEDS_REVIEW = "No – needs review"
NET_SUMMARY_ONLY = "No – summary line"

COUNTS_IN_NET_RULES: tuple[tuple[str, str], ...] = (
    ("Superseded rows", NET_SUPERSEDED),
    ("BSP Detailed", "Yes (the settlement file)"),
    ("ADM / ACM / RA", "No – they count through the BSP ADMA/ACMA/RFND row; the reason says where"),
    ("TGQ HMPR", "Tickets found in BSP are not repeated; tickets listed are GDS records and never count"),
    ("NDC", "Yes, unless the ticket is settled through BSP in this or another upload"),
    ("LCC Detailed", "Yes, except payment movements"),
    ("LCC DI / Divided PNR / Flown / CTA-BTA", NET_LEDGER),
    ("Third Party GDS / LCC", "Yes, except not-a-sale statuses, the statement's own footer lines (total / balance) and cancellations (verify)"),
    ("Third Party API", "Yes, except pending / no amount / cancelled / needs review"),
)

# ── Data flags ───────────────────────────────────────────────────────────────
FLAG_LEGEND: dict[str, str] = {
    # BSP
    "SPDR_DISTRIBUTED": "A bulk SPDR cancellation charge was spread onto this CANX row",
    "SPDR_ZEROED": "SPDR row whose amount was distributed onto CANX rows",
    "STAT_AMENDED": "BSP printed this amount as amended (*)",
    "LEGACY_BSP_EXCEL": "BSP row from the legacy Excel/CSV import (no fare/tax detail)",
    "MEMO_UPLOADED": "The matching ADM/ACM/RA is also in an uploaded BSPlink file",
    "ALSO_IN_NDC": "The same ticket is also in an NDC upload",
    "ISSUE_DATE_FALLBACK": "No row issue date; statement period start used",
    "TGQ_ENRICH_STORED": "Sector/class/travel date taken from the last commission run, not a live TGQ match",
    "TRAVEL_YEAR_INFERRED": "TGQ prints travel dates without a year; the year was inferred",
    "GROSS_COMPONENTS_MISMATCH": "Fare + taxes + fees + penalty does not equal the transaction amount",
    # ADM / ACM / RA
    "MEMO_COMPONENTS_MISMATCH": "Memo components do not add up to the memo amount",
    # TGQ
    "TGQ_PRE_SPLIT": "TGQ batch uploaded before sector splitting; sectors derived on the fly",
    "TGQ_UNMATCHABLE": "TGQ line has no valid ticket number and cannot be matched to BSP",
    "TGQ_MONEY_UNSPLIT": "TGQ money could not be re-assembled from the split legs; first leg shown",
    "BSP_HAS_OTHER_TXN": "BSP holds this ticket but with a different transaction type",
    "ALSO_IN_TP_GDS": "The same ticket is also in a Third Party GDS upload",
    "FARE_CURRENCY_DIFFERS": "Base fare currency differs from the row currency",
    # NDC
    "NDC_ANCILLARY": "NDC ancillary line (seat, baggage, meal); fare components on the ticket row",
    "NDC_LATCHED": "NDC line rolled up under its ticket; fare components on the ticket row",
    "NDC_GROUPING_STORED": "Very large NDC batch: stored billing grouping used",
    # LCC
    "LCC_PAYMENT_MOVEMENT": "LCC money movement with no fare",
    "LCC_MERGED_ACCOUNT_ROW": "Air India Express account row merged with the passenger file",
    "LCC_NOTE_SIGN_CONFLICT": "LCC account amount sign disagrees with its note",
    "LCC_CODE_UNCLASSIFIED": "LCC charge code not yet classified as tax / ancillary / fee",
    "PAYMENT_CURRENCY_DIFFERS": "Payment currency differs from the booking currency",
    "TAXES_DERIVED": "Taxes derived as gross − base fare",
    "FARE_FAMILY_NOT_RBD": "LCC product class is a fare family, not a booking class",
    "ALSO_IN_LCC_DETAILED": "The PNR is also in an LCC Detailed upload",
    "SCHEMA_UNVERIFIED": "Statement layout built without a real sample; check the mapping",
    # Third party
    "TP_DATE_PARSE_FAILED": "The consolidator's date could not be read",
    "TP_AIRLINE_CONFLICT": "Ticket prefix and airline name point to different airlines",
    "TP_STALE_FORMAT": "Parsed with an older column map; reprocess the upload",
    "TP_UNRECOGNISED_STATUS": "Ticket status not recognised; treated as a sale",
    "TP_REFUND_WITHOUT_SALE": "Refund with no matching sale from the same supplier",
    "TP_TOTAL_FARE_DERIVED": "Total fare derived by the importer",
    "TP_NET_IDENTITY_MISMATCH": "Consolidator net does not equal its own components",
    "ALSO_IN_BSP": "The same ticket is also settled in BSP",
    "API_TBO_CREDIT": "TBO credit line (MZ/RM invoice series)",
    "API_RETAINED_ON_CANCEL": "Cancelled booking with an amount retained by the aggregator",
    "API_NEEDS_REVIEW": "Aggregator row needs review before billing",
    "API_NO_CATEGORY": "Aggregator product not recognised",
    "API_GROSS_DERIVED": "Gross derived as base fare + taxes",
    # any source
    "AMOUNT_UNPARSEABLE": "An amount could not be read and was left blank",
    "DATE_UNREADABLE": "No readable date for the period filter",
    "TICKET_NO_NONSTANDARD": "Ticket number is not a standard 3+10 digit form",
    "LINK_AMBIGUOUS": "More than one candidate matched; newest used",
    "DUPLICATE_SUPERSEDED": "Same record in a newer upload of this type",
    "CURRENCY_ASSUMED": "Source carries no currency; INR assumed",
    "TXN_UNMAPPED": "Transaction type not recognised",
    "NEG_TAX_RESIDUAL": "Other taxes came out with the opposite sign to total taxes",
}


# ── row helpers ──────────────────────────────────────────────────────────────

def new_common_row(ctx: MapCtx, *, category: str, source_type: str, row_ref: str) -> dict[str, Any]:
    """A Combined row with provenance filled and every other column None.

    ``data_flags`` is a list while mapping; the writer joins it with "; ".
    """
    row: dict[str, Any] = {k: None for k in COMBINED_KEYS}
    up = ctx.upload
    row.update(
        category=category,
        source_type=source_type,
        source_file=up.file_name,
        upload_id=up.upload_id,
        uploaded_at=up.uploaded_at,
        row_ref=row_ref,
        data_flags=[],
    )
    return row


def add_flag(row: dict[str, Any], *codes: str) -> None:
    """Append flag codes once each. Unknown codes raise, so the legend can never drift."""
    flags = row.setdefault("data_flags", [])
    for code in codes:
        if code not in FLAG_LEGEND:
            raise KeyError(f"Unknown data flag {code!r}; add it to columns.FLAG_LEGEND")
        if code not in flags:
            flags.append(code)


def apply_link(row: dict[str, Any], link: Optional[LinkResult]) -> dict[str, Any]:
    """Copy a LinkResult's non-None fields onto the row and merge its flags."""
    if link is None:
        return row
    for attr, key in (
        ("linked_document", "linked_document"), ("linked_via", "linked_via"),
        ("also_in_bsp", "also_in_bsp"), ("not_in_bsp", "not_in_bsp"),
        ("tgq_enriched", "tgq_enriched"), ("counts_in_net", "counts_in_net"),
    ):
        val = getattr(link, attr)
        if val is not None:
            row[key] = val
    if link.flags:
        add_flag(row, *link.flags)
    return row


def flags_text(row: dict[str, Any]) -> Optional[str]:
    flags = row.get("data_flags") or []
    return "; ".join(flags) if flags else None
