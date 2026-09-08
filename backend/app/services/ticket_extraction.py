"""
TicketExtractionService
────────────────────────
Parses supplier statement XLS/XLSX files and returns structured rows.

Supports two statement types:
  B2B  — BookingRef, SegmentType, InvoiceType, … (existing format)
  AIRLINE — BSP/NDC format with Tax_Type1…Tax20, Sectors, FlightNo, TravelDt, etc.

Airline columns are mapped onto the same flat column names used by B2B where
the concept is equivalent, so deal_matching.py and exclusion_evaluator.py
require zero changes.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

from app.services import sector_split, spreadsheet
from app.services.statement_spec import norm as _norm

logger = logging.getLogger(__name__)

# ── B2B template headers ──────────────────────────────────────────────────────
TEMPLATE_HEADERS: list[str] = [
    "BookingRef", "SegmentType", "InvoiceType", "InvoiceNo", "TicketDate",
    "LastName", "FirstName", "Sector", "Class", "DepartureDateTime",
    "GDS_PNR", "AirlinesCode", "TicketNumber", "SellFare", "SellTax",
    "SellTax_YQ", "Sale_YR", "Sale_K3", "REI_Sell", "Seat_Selection",
    "Excessbagage", "Meals", "RFD_SELL", "CAN_Charge", "Booking_Fee_Sell",
    "CGST_Sell", "SGST_Sell", "IGST_Sell", "Comm_Sell", "ADM",
    "Incentive_Sell", "DIS_Sell", "TDS_Sell", "TotalAmt", "PaidByCreditCard",
    "Net_AMT", "CC", "AccCode", "SoldTo", "CustomerName", "AirlineName", "TourCode",
]

# ── Airline (BSP/NDC) template headers ───────────────────────────────────────
AIRLINE_TEMPLATE_HEADERS: list[str] = [
    "SNO", "PCC", "Date", "Airline", "Ticket_Date", "Ticket_No", "Air_Name",
    "Air_PNR", "Gal_PNR", "Pax_Name", "Booking_Signon", "Booking_PCC",
    "BookingAgencyName", "Ticketing_Signon", "Ticket_Type", "Document_Type",
    "Fare_Basis", "Fare_Const_Type", "Base_Fare", "BaseFareCurrency",
    "Tax_Type1", "Tax1", "Tax_Type2", "Tax2", "Tax_Type3", "Tax3",
    "Tax_Type4", "Tax4", "Tax_Type5", "Tax5", "Tax_Type6", "Tax6",
    "Tax_Type7", "Tax7", "Tax_Type8", "Tax8", "Tax_Type9", "Tax9",
    "Tax_Type10", "Tax10", "Tax_Type11", "Tax11", "Tax_Type12", "Tax12",
    "Tax_Type13", "Tax13", "Tax_Type14", "Tax14", "Tax_Type15", "Tax15",
    "Tax_Type16", "Tax16", "Tax_Type17", "Tax17", "Tax_Type18", "Tax18",
    "Tax_Type19", "Tax19", "Tax_Type20", "Tax20",
    "WOTax", "YQTax", "Other_Tax", "Total_Tax", "AirlineFee", "Total_Fare",
    "Comm(%)", "Comm_Amount", "FOP", "FOP_Details", "CC_Auth", "CC_DOExpiry",
    "AI_Code", "Tour_Code", "Value_Code", "Net_Remit", "Net_Fare",
    "Actual_Selling_Fare", "Invoice_Fare", "Transaction_Type", "EXCHANGED_FOR",
    "Multiple_Receivables", "Invoice_No", "Stock_Control_No", "STP_No",
    "Void__Exchange__Refund_Date", "Sectors", "FlightNo", "TravelDt", "Class",
    "Coupon_Status", "Refund_Type", "Total_Refund_Amount", "AC_ACCT", "TripID",
    "ROE", "NUC", "Fare Ladder", "ClientEntityName", "BusinessPhoneNumber",
    "BusinessEmailAddress", "EntityAddressLine1", "GSTN",
]

_TEMPLATE_MATCH_THRESHOLD = 10

# ── Canonical field → accepted header variants (lowercase, stripped) ──────────
_COL_ALIASES: dict[str, list[str]] = {
    # ── shared / B2B ─────────────────────────────────────────────────────────
    "booking_ref":         ["bookingref", "booking_ref", "booking ref"],
    "segment_type":        ["segmenttype", "segment_type", "segment type"],
    "invoice_type":        ["invoicetype", "invoice_type", "invoice type",
                            "ticket_type", "tickettype"],
    "invoice_no":          ["invoiceno", "invoice_no", "invoice no", "invoicenumber",
                            "invoice_no"],
    "ticket_date":         ["ticketdate", "ticket_date", "ticket date", "ticket_date",
                            "issue_date", "date_of_issue", "invoice_date", "booked_date"],
    "last_name":           ["lastname", "last_name", "last name", "surname"],
    "first_name":          ["firstname", "first_name", "first name"],
    "sector":              ["sector", "sectors", "sector_description", "sector_desc",
                            "routing", "route"],
    "booking_class":       ["class", "bookingclass", "booking_class"],
    "departure_datetime":  ["departuredatetime", "departure_datetime", "departuretime",
                            "departure", "travel_date", "date_of_travel", "journey_date",
                            "dep_date", "flight_date"],
    "gds_pnr":             ["gds_pnr", "gdspnr", "pnr", "gal_pnr", "galpnr",
                            "pnr_no", "pnr_number", "pnr_ref", "crs_pnr"],
    # "al" is the two-letter carrier column an Indian consolidator statement prints.
    "airlines_code":       ["airlinescode", "airlines_code", "airlinecode",
                            "airline_code", "airlineid", "airline", "al", "al_code",
                            "carrier", "carrier_code"],
    "airline_name":        ["airlinename", "airline_name", "airline name",
                            "air_name", "airname"],
    "ticket_number":       ["ticketnumber", "ticket_number", "ticketno", "ticket_no",
                            "tkt_no", "tktno"],
    "sell_fare":           ["sellfare", "sell_fare", "base_fare", "basefare",
                            "basic_fare", "basic", "fare"],
    "sell_tax":            ["selltax", "sell_tax", "total_tax", "totaltax"],
    "sell_tax_yq":         ["selltax_yq", "sell_tax_yq", "selltaxyq",
                            "yqtax", "yq_tax", "yq", "yq_amount"],
    "sale_yr":             ["sale_yr", "saleyr", "yr_tax", "yr", "yr_amount"],
    "sale_k3":             ["sale_k3", "salek3", "k3_tax", "k3", "k3_amount"],
    "rei_sell":            ["rei_sell", "reisell"],
    "seat_selection":      ["seat_selection", "seatselection"],
    "excess_baggage":      ["excessbagage", "excessbaggage", "excess_baggage"],
    "meals":               ["meals"],
    "rfd_sell":            ["rfd_sell", "rfdsell"],
    "can_charge":          ["can_charge", "cancharge"],
    "booking_fee_sell":    ["booking_fee_sell", "bookingfeesell",
                            "airlinefee", "airline_fee"],
    "cgst_sell":           ["cgst_sell", "cgstsell", "cgst"],
    "sgst_sell":           ["sgst_sell", "sgstsell", "sgst"],
    "igst_sell":           ["igst_sell", "igstsell", "igst"],
    "comm_sell":           ["comm_sell", "commsell", "commission", "comm_amount",
                            "commamount"],
    "adm":                 ["adm"],
    "incentive_sell":      ["incentive_sell", "incentivesell", "incentive"],
    "dis_sell":            ["dis_sell", "dissell", "discount", "disc", "discount_amount"],
    "tds_sell":            ["tds_sell", "tdssell", "tds", "tds_amount", "tds_amt"],
    "total_amt":           ["totalamt", "total_amt", "total", "total_fare",
                            "totalfare", "actual_selling_fare", "actualselling",
                            "billamount", "bill_amount", "bill_amt", "grand_total",
                            "invoice_amount"],
    "paid_by_credit_card": ["paidbycreditcard", "paid_by_credit_card", "creditcard"],
    # "net_remit"/"netremit" deliberately NOT here — they belong to the net_remit
    # field below. The index is first-wins, and net_amt is declared earlier, so
    # leaving them would quietly steal a column named "Net_Remit" from the field
    # actually called that.
    "net_amt":             ["net_amt", "netamt", "net", "net_amount"],
    # "fop_details"/"fopdetails" likewise belong to fop_details, not to cc.
    "cc":                  ["cc"],
    "acc_code":            ["acccode", "acc_code", "ac_acct", "acacct"],
    "sold_to":             ["soldto", "sold_to", "sold to", "soldtoparty"],
    "customer_name":       ["customername", "customer_name", "customer name",
                            "cliententityname", "clientname", "client name"],
    "tour_code":           ["tourcode", "tour_code", "tour code", "tourcd", "tour_cd",
                            "tour_code"],
    # ── airline-specific new fields ───────────────────────────────────────────
    "pax_name":             ["pax_name", "paxname", "passenger_name", "passenger", "pax"],
    "air_pnr":              ["air_pnr", "airpnr"],
    "pcc":                  ["pcc"],
    "booking_signon":       ["booking_signon", "bookingsignon"],
    "booking_pcc":          ["booking_pcc", "bookingpcc"],
    "booking_agency_name":  ["bookingagencyname", "booking_agency_name"],
    "ticketing_signon":     ["ticketing_signon", "ticketingsignon"],
    "document_type":        ["document_type", "documenttype"],
    "fare_basis":           ["fare_basis", "farebasis"],
    "fare_const_type":      ["fare_const_type", "fareconsttype"],
    "base_fare_currency":   ["basefarecurrency", "base_fare_currency"],
    "transaction_type":     ["transaction_type", "transactiontype"],
    "exchanged_for":        ["exchanged_for", "exchangedfor"],
    "stock_control_no":     ["stock_control_no", "stockcontrolno"],
    "stp_no":               ["stp_no", "stpno"],
    "void_date":            ["void__exchange__refund_date", "voiddate", "void_date"],
    "coupon_status":        ["coupon_status", "couponstatus"],
    "refund_type":          ["refund_type", "refundtype"],
    "trip_id":              ["tripid", "trip_id"],
    "ai_code":              ["ai_code", "aicode"],
    "value_code":           ["value_code", "valuecode"],
    "multiple_receivables": ["multiple_receivables", "multiplereceivables"],
    "wo_tax":               ["wotax", "wo_tax"],
    "other_tax":            ["other_tax", "othertax", "other_taxes", "oth_tax"],
    # "%%%%" is a real commission-percent header on Globe's statement. It survives
    # only through the raw-lowercase half of the alias index — norm() erases it.
    "comm_percent":         ["comm(%)", "commpercent", "comm_percent", "%%%%",
                             "comm_%", "commission_percent", "plb_percent"],
    "net_remit":            ["net_remit", "netremit"],
    "net_fare":             ["net_fare", "netfare"],
    "invoice_fare":         ["invoice_fare", "invoicefare"],
    "total_refund_amount":  ["total_refund_amount", "totalrefundamount"],
    "roe":                  ["roe"],
    "nuc":                  ["nuc"],
    "fop":                  ["fop"],
    "fop_details":          ["fop_details", "fopdetails"],
    "cc_auth":              ["cc_auth", "ccauth"],
    "cc_do_expiry":         ["cc_doexpiry", "ccdoexpiry"],
    "flight_no":            ["flightno", "flight_no"],
    "travel_dt":            ["traveldt", "travel_dt"],
    "fare_ladder":          ["fare ladder", "fareladder", "fare_ladder"],
    "gstn":                 ["gstn"],
    "business_phone":       ["businessphonenumber", "business_phone"],
    "business_email":       ["businessemailaddress", "business_email"],
    "entity_address":       ["entityaddressline1", "entity_address"],
    # ── consolidator statements ───────────────────────────────────────────────
    # An Indian consolidator's own statement (Globe, Akbar, Riya, TSI…) prints a
    # different vocabulary from both our template and a BSP export: a document
    # number of its own, taxes broken out by IATA code, and its service charge and
    # refund fee as named columns. None of these had a home before, so a file like
    # `GLOBE OUR 08 15 AUG 26.xls` auto-mapped 5 of its 23 columns.
    #
    # These four money columns are RECORDED, not calculated on. The incentive bases
    # are sell_fare / sell_tax_yq / sale_yr and the named ancillaries; deal_matching
    # and exclusion_evaluator read none of the fields below.
    "oc_tax":               ["oc_tax", "oc", "octax", "carrier_misc_fee"],
    "raf":                  ["raf", "refund_admin_fee", "refund_administration_fee"],
    "serv_charge":          ["serv_chrgs", "serv_charges", "serv_chgs", "service_charge",
                             "servicecharge", "management_fee", "mgmt_fee", "handling_charge"],
    # A single GST figure, as opposed to the CGST/SGST/IGST triple. NOT an alias of
    # sale_k3: K3 is GST on the air fare, this is GST on the agency's own service
    # charge, and they land on different lines of a return.
    "gst_sell":             ["gst", "gst_amount", "gst_amt", "gst_value"],
    # The consolidator's own voucher number and its date — deliberately NOT aliases
    # of invoice_no / ticket_date. "IS26/ 1067" is the consolidator's document, not
    # the airline's invoice, and on a credit note the document date is the credit
    # date rather than the issue date. `_suggest_fallbacks` proposes doc_date for
    # ticket_date where nothing better exists, so the user confirms that reading
    # instead of it being assumed.
    "doc_no":               ["doc_no", "docno", "document_no", "voucher_no"],
    "doc_date":             ["doc_date", "docdate", "document_date"],
    "reference":            ["reference", "ref_no", "refno"],
    "narration":            ["narration", "particulars", "remarks", "description"],
}

# ── Alias index ───────────────────────────────────────────────────────────────
# Every alias is indexed twice: under statement_spec.norm (the repo-wide rule,
# "Serv. Chrgs" -> "serv_chrgs") and under its raw lowercased form. The raw index is
# not redundant — norm() strips every non-alphanumeric character, so a header like
# "%%%%" (a real commission-percent column) normalises to the empty string and would
# be unreachable without it.
#
# setdefault, not assignment: the first canonical field to claim an alias keeps it,
# so a loose synonym added later can never steal a header from the field that owns it.
_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in _COL_ALIASES.items():
    for _alias in _aliases:
        for _key in (_norm(_alias), _alias.strip().lower()):
            # An alias that normalises away to nothing ("%%%%", "---") must not be
            # indexed under the empty key: every other blank-normalising header in
            # every future file would then match it.
            if _key:
                _ALIAS_TO_CANON.setdefault(_key, _canon)


def canonical_for(header: str) -> str | None:
    """The canonical field a source header names, or None."""
    for key in (_norm(header), (header or "").strip().lower()):
        if key and key in _ALIAS_TO_CANON:
            return _ALIAS_TO_CANON[key]
    return None


def recognised_count(headers: list[str]) -> int:
    """How many of these headers name a canonical field — the header-row score.

    Passed to spreadsheet.detect_header so the reader can find the header row of a
    file whose real headers sit under a title block, without the reader knowing
    anything about tickets.
    """
    seen: set[str] = set()
    for h in headers:
        canon = canonical_for(h)
        if canon:
            seen.add(canon)
    return len(seen)

NUMERIC_COLS = {
    "sell_fare", "sell_tax", "sell_tax_yq", "sale_yr", "sale_k3",
    "rei_sell", "seat_selection", "excess_baggage", "meals",
    "rfd_sell", "can_charge", "booking_fee_sell",
    "cgst_sell", "sgst_sell", "igst_sell", "comm_sell",
    "adm", "incentive_sell", "dis_sell", "tds_sell",
    "total_amt", "paid_by_credit_card", "net_amt",
    # airline-specific
    "wo_tax", "other_tax", "comm_percent", "net_remit", "net_fare",
    "invoice_fare", "total_refund_amount", "roe", "nuc",
    # consolidator statements. NOTE: membership here governs _to_float coercion
    # ONLY. It says nothing about the incentive base — deal_matching reads
    # sell_fare / sell_tax_yq / sale_yr and the named ancillaries, and none of
    # these four is one of them.
    "oc_tax", "raf", "serv_charge", "gst_sell",
}

# ── Columns split across multi-sector legs ───────────────────────────────────
# A per-ticket amount must be divided when the ticket becomes one row per leg, or
# the leg rows no longer add up to the document they came from. A leg carrying the
# whole ticket's K3 next to its own share of YQ/YR is simply wrong.
#
# Amounts that are a RATE, not money: dividing 18% across three legs would give
# three legs at 6%.
_PER_TICKET_RATES = {"comm_percent", "roe", "nuc"}

# Derived rather than listed, and that is the point. This set used to name five
# columns by hand, so the ticket's total, discount, TDS and other taxes were copied
# whole onto every leg — a two-leg ticket reported twice its own BillAmount, and
# nobody noticed because the fare columns beside them were right. A column added to
# NUMERIC_COLS is now split automatically; the only way to opt out is to declare it
# a rate above, which is a decision someone has to make deliberately.
_SPLIT_FIN_COLS = NUMERIC_COLS - _PER_TICKET_RATES


def _leg_share(value: float, n: int, i: int) -> float:
    """This leg's share of a per-ticket amount, allocated so the legs re-sum EXACTLY.

    `round(value / n, 2)` invents or loses a paisa whenever the amount does not
    divide cleanly — 6395 over three legs re-sums to 6395.01. sector_split.allocate
    is the largest-remainder allocator the vendor-statement splitter already uses,
    and it is sign-aware, which matters here because a refund row is negative.
    """
    shares = sector_split.allocate(f"{value:.2f}", n)
    try:
        return float(shares[i])
    except (IndexError, TypeError, ValueError):   # allocate refused to divide
        return round(value / n, 2)

# BSP transaction_type → invoice_type + adm_acm_ra
_TRANSACTION_TYPE_MAP: dict[str, tuple[str, str | None]] = {
    "tktt":  ("Invoice",     None),
    "rfnd":  ("Credit Note", None),
    "admd":  ("Credit Note", "ADM"),
    "acmd":  ("Credit Note", "ACM"),
    "canx":  ("Credit Note", None),
    "void":  ("Credit Note", None),
}

# Airports assumed to be in India for segment_type detection
_INDIA_AIRPORTS: frozenset[str] = frozenset({
    "DEL", "BOM", "MAA", "CCU", "HYD", "BLR", "AMD", "COK", "GOI", "JAI",
    "PNQ", "ATQ", "IXC", "LKO", "IXB", "GAU", "BBI", "IXR", "SXR", "VNS",
    "IXZ", "TRV", "IXM", "IDR", "RPR", "NAG", "VTZ", "BHO", "UDR", "JDH",
    "PAT", "GWL", "IXA", "IXE", "MYQ", "STV", "DIU", "RAJ", "IXU",
})


def _leg_classes(raw: str | None, n: int) -> list[str]:
    """Per-leg booking classes from one class string.

    Slash-delimited is the B2B form ("Y/J"); HMPR airline exports use spaces
    ("L L U U"). Slash is tried first and wins whenever it yields structure,
    because that is what the B2B split has always done — and a list longer than
    `n` is truncated by indexing, not rejected. A single value broadcasts: "Y"
    across three legs genuinely means Y on every leg.
    """
    s = (raw or "").strip()
    parts = [c.strip() for c in s.split("/") if c.strip()]
    if len(parts) < 2:
        whitespace = s.split()
        if len(whitespace) > 1:
            parts = whitespace
    while len(parts) < n:
        parts.append(parts[-1] if parts else "")
    return parts


def _split_multi_sector_rows(rows: list[dict]) -> list[dict]:
    """Expand a multi-sector row into one row per flown leg.

    Both sector grammars are understood, via `sector_split.leg_sectors`:
    the B2B slash chain ("DEL/BOM/HYD") and the airline space-separated pairs
    ("DEL/BOM BOM/HYD"). A sector that does not parse leaves the row untouched
    rather than being guessed at — dividing money by a leg count we are not sure
    of would silently corrupt it.

    Per-leg values come from `segments` when the caller supplied one entry per
    leg. That is how the manual entry form carries a distinct travel date and
    segment type per leg, neither of which the parallel strings can express.
    Without `segments` the historical positional-token behaviour applies, so XLS
    rows and legacy single-string payloads split exactly as they always have.
    """
    result: list[dict] = []
    for row in rows:
        legs, status = sector_split.leg_sectors(row.get("sector"))
        n = len(legs)

        # One segment per leg means the caller punched the legs individually.
        raw_segments = row.get("segments")
        segments = raw_segments if isinstance(raw_segments, list) and len(raw_segments) == n else None

        if n <= 1 or status == sector_split.UNPARSED:
            row.setdefault("split_type", "normal")
            # A one-leg ticket still carries a punched segment, and its date and
            # segment type are just as real as a split ticket's. Reading them
            # here is what keeps one leg from being a special case the form has
            # to work around.
            if segments:
                seg = segments[0]
                if seg.get("travel_date") and not row.get("departure_datetime"):
                    row["departure_datetime"] = _normalize_date(seg["travel_date"])
                if seg.get("segment_type"):
                    row["segment_type"] = seg["segment_type"]
                row["segments"] = [{**seg, "segment_type": row.get("segment_type")}]
            result.append(row)
            continue

        classes  = _leg_classes(row.get("booking_class"), n)
        flights  = sector_split.tokens(row.get("flight_no"), n)
        journeys = sector_split.tokens(row.get("travel_dt"), n)

        for i in range(n):
            r = dict(row)
            seg = segments[i] if segments else {}

            r["sector"] = legs[i]
            r["split_type"] = "split"
            r["booking_class"] = seg.get("class") or classes[i]

            if flight := (seg.get("flight_no") or (flights[i] if i < len(flights) else None)):
                r["flight_no"] = flight
            if journey := (seg.get("travel_date") or (journeys[i] if i < len(journeys) else None)):
                r["travel_dt"] = journey

            # This leg's own date, falling back to the whole-ticket one.
            departure = seg.get("travel_date") or (journeys[i] if i < len(journeys) else None)
            if departure:
                r["departure_datetime"] = _normalize_date(departure)

            # The leg's own airports are better evidence than a whole-ticket
            # value, so they outrank it — but only when the caller punched legs
            # individually. A mapped SegmentType column on an XLS row still wins.
            if segments:
                r["segment_type"] = (
                    seg.get("segment_type")
                    or _detect_segment_type_from_sector(legs[i])
                    or row.get("segment_type")
                )
            else:
                r["segment_type"] = (
                    row.get("segment_type") or _detect_segment_type_from_sector(legs[i])
                )

            # Keep the stored segment agreeing with the columns it produced —
            # a leg whose JSONB says one thing and whose column says another is
            # a bug waiting to be read by whichever of the two a caller trusts.
            if segments:
                origin, _, destination = legs[i].partition("/")
                r["segments"] = [{
                    **seg,
                    "origin":       seg.get("origin") or origin,
                    "destination":  seg.get("destination") or destination,
                    "flight_no":    r.get("flight_no"),
                    "class":        r["booking_class"] or None,
                    "travel_date":  seg.get("travel_date") or r.get("departure_datetime"),
                    "segment_type": r["segment_type"],
                }]

            for col in _SPLIT_FIN_COLS:
                if row.get(col) is not None:
                    r[col] = _leg_share(row[col], n, i)

            # The breakup has to follow the columns it fed, or a leg's YR would
            # no longer agree with the YR printed in its own breakup.
            if isinstance(row.get("tax_breakup"), dict):
                r["tax_breakup"] = {
                    code: round(amount / n, 2) if isinstance(amount, (int, float)) else amount
                    for code, amount in row["tax_breakup"].items()
                }

            r["row_order"] = row.get("row_order", 0) * 1000 + i
            result.append(r)
    return result


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "-", "--", "N/A", "NA", "nan"):
        return None
    try:
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _to_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s not in ("-", "--", "nan") else None


def _normalize_date(val: Any) -> str | None:
    """Normalize any common date string to YYYY-MM-DD for <input type='date'>.

    Delegates to flat_statement.to_iso_date, which tries explicit formats before
    dateutil. That order is load-bearing, not tidiness: a spreadsheet engine hands
    back a date-formatted cell as "2026-08-11 00:00:00", and dateutil with
    dayfirst=True reads the day and month of even an ISO string back to front —
    11 August became 8 November, moving the ticket a quarter down the calendar and
    into a different contract window.

    An unparseable value is returned unchanged rather than dropped, so the reviewer
    can see and correct it in the preview grid.
    """
    s = _to_str(val)
    if not s:
        return None
    from app.services.flat_statement import to_iso_date
    return to_iso_date(s) or s


# What makes a row a document. A ticket always has at least one of these; a
# statement's summary line has none of them.
_IDENTIFIERS = ("ticket_number", "doc_no", "invoice_no", "gds_pnr", "air_pnr",
                "pax_name", "last_name", "booking_ref")

# The literals a labelled total row uses, for the statements that do label them.
_TOTAL_WORDS = {"total", "totals", "grand total", "sub total", "subtotal",
                "net total", "g.total", "gross total"}


def _is_total_line(row: dict[str, Any]) -> bool:
    """True when this row sums the rows above it rather than describing a ticket.

    Two shapes, both requiring that NO identifier is present — that condition is
    what makes this safe, because a row without a ticket number, voucher, PNR or
    passenger cannot be matched to a deal or billed to anyone in the first place:

      * an unlabelled row of sums (what a consolidator actually prints), or
      * one labelled "Total" in a text column.

    A row with no identifiers AND no money is just a spacer and is dropped by the
    same rule.
    """
    if any(row.get(f) for f in _IDENTIFIERS):
        return False
    if any((row.get(c) or 0) != 0 for c in NUMERIC_COLS):
        return True
    return any(
        isinstance(v, str) and v.strip().lower() in _TOTAL_WORDS
        for k, v in row.items() if k != "row_order"
    )


def _build_col_map(df_columns: list[str]) -> dict[str, str]:
    """{source column: canonical field} for the columns this vocabulary recognises.

    A canonical field is claimed once. If a file carries both "Ticket No" and
    "Document Number", taking the second would silently overwrite the first; the
    user resolves that on the mapping screen instead.
    """
    mapping: dict[str, str] = {}
    seen_canon: set[str] = set()
    for col in df_columns:
        canon = canonical_for(col)
        if canon and canon not in seen_canon:
            mapping[col] = canon
            seen_canon.add(canon)
    return mapping


# A ratio this side of certainty. airline_resolver uses 0.72 for airline NAMES, but
# customer_resolver records that 0.72 produced eight false pairs on one 203-row
# statement — and a column mis-match puts a number in the wrong money field rather
# than merely naming the wrong airline. Suggestions are never applied automatically,
# so the cost of being strict here is only that the user picks from the dropdown.
_FUZZY_THRESHOLD = 0.82


def _fuzzy_suggestions(
    columns: list[str], col_map: dict[str, str], wanted: list[str],
) -> dict[str, list[dict]]:
    """{canonical: [{column, score}]} for fields nothing claimed outright.

    Only unclaimed source columns are offered, and only for unmapped fields, so a
    suggestion can never contradict a confident match.
    """
    free_cols = [c for c in columns if c not in col_map]
    unmapped = [f for f in wanted if f not in set(col_map.values())]
    if not free_cols or not unmapped:
        return {}

    out: dict[str, list[dict]] = {}
    for field in unmapped:
        target = _norm(field)
        scored = []
        for col in free_cols:
            key = _norm(col)
            if not key:
                continue
            ratio = SequenceMatcher(None, key, target).ratio()
            if ratio >= _FUZZY_THRESHOLD:
                scored.append({"column": col, "score": round(ratio, 3)})
        if scored:
            scored.sort(key=lambda s: -s["score"])
            out[field] = scored[:2]
    return out


def _suggest_fallbacks(col_map: dict[str, str], suggestions: dict[str, list[dict]]) -> None:
    """Industry readings that are right often enough to offer, never to assume.

    A consolidator's document date IS the issue date for a sale, so proposing it for
    ticket_date saves the user a lookup — but on a credit note it is the credit date,
    which is why it is a suggestion and not an alias.
    """
    claimed = set(col_map.values())
    by_canon = {canon: col for col, canon in col_map.items()}
    for source, target in (("doc_date", "ticket_date"), ("doc_no", "invoice_no")):
        if source in claimed and target not in claimed and target not in suggestions:
            suggestions[target] = [{"column": by_canon[source], "score": 1.0}]


def _detect_airline_format(df_columns: list[str]) -> bool:
    """Return True if the file looks like a BSP/airline format."""
    lower_cols = {c.strip().lower() for c in df_columns}
    airline_markers = {"tax_type1", "yqtax", "gal_pnr", "air_pnr", "pax_name",
                       "traveldt", "flightno", "sectors", "fare_basis"}
    return bool(lower_cols & airline_markers)


def _build_tax_breakup(raw: Any, all_cols: list[str], df_row: Any) -> dict[str, float]:
    """Build tax_breakup dict from Tax_Type1/Tax1 … Tax_Type20/Tax20 pairs."""
    breakup: dict[str, float] = {}
    for i in range(1, 21):
        type_col = next((c for c in all_cols if c.strip().lower() == f"tax_type{i}"), None)
        val_col  = next((c for c in all_cols if c.strip().lower() == f"tax{i}"), None)
        if not type_col or not val_col:
            continue
        tax_type = _to_str(df_row.get(type_col))
        tax_val  = _to_float(df_row.get(val_col))
        if tax_type and tax_val is not None:
            breakup[tax_type.upper()] = tax_val
    return breakup


# Courtesy titles and passenger-type markers that a consolidator prints inside the
# name cell — "MR. SAHOTA/VIKAS", "INF DIYA MISS". Stripped so the surname column
# holds a surname; a customer search for "SAHOTA" must not miss "MR. SAHOTA".
_TITLE_RE = re.compile(
    r"^(?:MR|MRS|MS|MISS|MSTR|MASTER|DR|PROF|INF|INFANT|CHD|CHILD)\.?\s+", re.I)
_TRAILING_TITLE_RE = re.compile(
    r"\s+(?:MR|MRS|MS|MISS|MSTR|MASTER|DR|PROF|INF|INFANT|CHD|CHILD)\.?$", re.I)


def _strip_title(name: str | None) -> str | None:
    if not name:
        return None
    s = _TITLE_RE.sub("", name.strip())
    s = _TRAILING_TITLE_RE.sub("", s).strip()
    # A cell holding nothing but a title ("MR") is not a name — keep the original
    # rather than replacing it with an empty string the reviewer cannot see.
    return s or name.strip() or None


def _parse_pax_name(pax_name: str | None) -> tuple[str | None, str | None]:
    """Parse 'LASTNAME/FIRSTNAME M' → (last_name, first_name), titles removed."""
    if not pax_name:
        return None, None
    parts = pax_name.strip().split("/", 1)
    last = _strip_title(parts[0])
    first = _strip_title(parts[1]) if len(parts) > 1 else None
    return last, first


def _parse_first_date(travel_dt: str | None) -> str | None:
    """Extract first space-separated date token from TravelDt ('16MAY 24MAY')."""
    if not travel_dt:
        return None
    token = travel_dt.strip().split()[0]
    return token if token else None


def _build_segments(sectors: str | None, flight_no: str | None,
                    travel_dt: str | None, booking_class: str | None) -> list[dict]:
    """Build segments list from raw airline fields."""
    if not sectors:
        return []
    airport_pairs = sectors.strip().split()
    flights = (flight_no or "").strip().split() if flight_no else []
    dates   = (travel_dt or "").strip().split()  if travel_dt else []
    classes = (booking_class or "").strip().split("/") if booking_class else []

    segments = []
    for i, pair in enumerate(airport_pairs):
        parts = pair.split("/")
        if len(parts) != 2:
            continue
        origin, dest = parts[0].strip(), parts[1].strip()
        seg = {
            "origin":      origin,
            "destination": dest,
            "flight_no":   flights[i].replace("-", "") if i < len(flights) else None,
            "class":       classes[i].strip() if i < len(classes) else None,
            "travel_date": dates[i] if i < len(dates) else None,
        }
        segments.append(seg)
    return segments


def _detect_segment_type_from_sector(sector: str | None) -> str | None:
    """Return 'Domestic' or 'International' based on origin/dest airports."""
    if not sector:
        return None
    parts = [p.strip().upper() for p in sector.split("/") if p.strip()]
    if len(parts) < 2:
        return None
    origin = parts[0]
    dest   = parts[-1]
    if origin in _INDIA_AIRPORTS and dest in _INDIA_AIRPORTS:
        return "Domestic"
    if origin in _INDIA_AIRPORTS or dest in _INDIA_AIRPORTS:
        return "International"
    return "International"


def _derive_from_transaction_type(
    transaction_type: str | None,
    ticket_number: str | None,
    existing_invoice_type: str | None,
) -> tuple[str | None, str | None]:
    """Return (invoice_type, adm_acm_ra) from BSP transaction_type."""
    if transaction_type:
        key = transaction_type.strip().lower()
        if key in _TRANSACTION_TYPE_MAP:
            inv_type, adm_cat = _TRANSACTION_TYPE_MAP[key]
            return inv_type, adm_cat
    # Fallback: use ticket-number prefix if present (existing B2B logic)
    if ticket_number:
        tn_norm = ticket_number.lstrip("0") or "0"
        if ticket_number.startswith("400"):
            return existing_invoice_type, "RA"
        if tn_norm.startswith("6"):
            return "Credit Note", "ADM"
        if tn_norm.startswith("8"):
            return "Credit Note", "ACM"
    return existing_invoice_type, None


# ── Shared row derivation (XLS upload + manual entry) ────────────────────────
# Everything below the column mapping is pure dict work, so the manual-entry
# endpoint can run the exact same pipeline the parser does. Keeping one
# implementation is the whole point: a ticket punched by hand must be
# indistinguishable from an uploaded one, and a second copy of these rules would
# drift silently — producing wrong money rather than an error.

def derive_ticket_row(row: dict[str, Any], is_airline: bool) -> dict[str, Any]:
    """Row-level derivations applied after canonical column mapping.

    `row` must already use canonical field names, with `tax_breakup`, `pax_name`
    and `travel_dt` pre-filled by the caller (the XLS path reads those from
    source columns the alias map does not cover).

    A field whose value is unknown must be ABSENT, not None — `setdefault` and
    `if not row.get(...)` both treat a present None differently from a missing
    key. Callers building rows from Pydantic models must use
    `model_dump(exclude_none=True)`.

    Mutates and returns `row`.
    """
    # Normalize ticket_date to YYYY-MM-DD so <input type="date"> can display it
    if row.get("ticket_date"):
        row["ticket_date"] = _normalize_date(row["ticket_date"])
    if row.get("doc_date"):
        row["doc_date"] = _normalize_date(row["doc_date"])

    # ── Ticket number: accounting code + document serial ──────────
    # A consolidator prints "607 5808583279" — the airline's 3-digit IATA
    # accounting code, then the document serial. Joining them gives the 13-digit
    # canonical form, and the prefix is kept because it identifies the carrier on
    # a statement whose airline column is blank.
    code, serial = sector_split.split_ticket_no(row.get("ticket_number"))
    if code:
        row["ticket_number"] = f"{code}{serial}"
        row.setdefault("ticket_prefix", code)
        if not row.get("airlines_code"):
            row["airlines_code"] = code      # resolved to the 2-letter code at confirm

    # ── Sector: normalise the consolidator hyphen chain ───────────
    # "IST-AUH-DEL-   -   " -> "IST/AUH AUH/DEL", the grammar every other reader
    # here already speaks. Fails closed: an unrecognised string is left verbatim.
    if row.get("sector"):
        legs, status = sector_split.leg_sectors(row["sector"])
        if legs and status != sector_split.UNPARSED:
            row["sector"] = " ".join(legs)

    # ── Tax breakup → the tax columns deal matching reads ─────────
    # Not airline-only: a B2B ticket can be punched with a tax breakup too, and
    # the same codes mean the same things. Non-destructive by design — an
    # explicitly supplied column always wins, the breakup only fills a blank.
    tax_breakup = row.get("tax_breakup") or {}
    if tax_breakup:
        row["tax_breakup"] = tax_breakup
        if "YR" in tax_breakup and row.get("sale_yr") is None:
            row["sale_yr"] = tax_breakup["YR"]
        if "K3" in tax_breakup and row.get("sale_k3") is None:
            row["sale_k3"] = tax_breakup["K3"]
        # sell_tax_yq: prefer YQTax column already mapped; fallback to YQ in breakup
        if row.get("sell_tax_yq") is None and "YQ" in tax_breakup:
            row["sell_tax_yq"] = tax_breakup["YQ"]

    # ── Segment type auto-detection ───────────────────────────────
    # Also not airline-only. A blank segment type does not block deal matching
    # but defeats the Domestic/International filter, so deriving it from the
    # airports is strictly better than leaving it null. Only fills a blank.
    # Per-leg detection happens in _split_multi_sector_rows, once the sector has
    # been narrowed to a single pair.
    if not row.get("segment_type"):
        detected = _detect_segment_type_from_sector(row.get("sector"))
        if detected:
            row["segment_type"] = detected

    # ── Pax_Name → last_name / first_name ─────────────────────────
    # Not airline-only any more: a consolidator's B2B statement carries one
    # "Pax Name" column in the same LAST/FIRST grammar, and leaving it unsplit
    # meant the passenger columns the review grid shows stayed empty.
    raw_pax = row.get("pax_name")
    if raw_pax:
        row["pax_name"] = raw_pax
        last, first = _parse_pax_name(raw_pax)
        if not row.get("last_name"):
            row["last_name"] = last
        if not row.get("first_name"):
            row["first_name"] = first

    # ── A negative sale is a credit note ──────────────────────────
    # Refund-vs-sale is normally decided by a status vocabulary, never by sign
    # (see services/commission/calc_row.py). This only fills a blank: a
    # consolidator statement carries no transaction-type column at all, and a row
    # whose fare, total and net are all negative is not a sale by any reading.
    if not row.get("invoice_type"):
        amounts = [row.get(c) for c in ("sell_fare", "total_amt", "net_amt")]
        present = [a for a in amounts if a is not None]
        if present and all(a < 0 for a in present):
            row["invoice_type"] = "Credit Note"   # NOT adm_acm_ra — a refund is not an ADM

    if is_airline:
        # ── TravelDt → departure_datetime (first leg date) ────────
        raw_travel_dt = row.get("travel_dt")
        if raw_travel_dt:
            row["travel_dt"] = raw_travel_dt
            if not row.get("departure_datetime"):
                row["departure_datetime"] = _parse_first_date(raw_travel_dt)

        # ── invoice_type + adm_acm_ra from transaction_type ────────
        inv_type, adm_cat = _derive_from_transaction_type(
            row.get("transaction_type"),
            row.get("ticket_number"),
            row.get("invoice_type"),
        )
        if inv_type:
            row["invoice_type"] = inv_type
        if adm_cat:
            row["adm_acm_ra"] = adm_cat

        # ── Segments JSONB ─────────────────────────────────────────
        # Only built when the caller did not supply them. The manual entry form
        # posts one segment per punched leg, carrying a per-leg travel date and
        # segment type that the parallel sector/flight/date strings cannot
        # express — rebuilding here would throw that away.
        if not row.get("segments"):
            segs = _build_segments(
                row.get("sector"),
                row.get("flight_no"),
                row.get("travel_dt"),
                row.get("booking_class"),
            )
            if segs:
                row["segments"] = segs

        # ── store statement_type on each row ──────────────────────
        row["statement_type"] = "AIRLINE"

    else:
        row.setdefault("statement_type", "B2B")

    # Normalize departure_datetime to YYYY-MM-DD (drop time)
    if row.get("departure_datetime"):
        row["departure_datetime"] = _normalize_date(row["departure_datetime"])

    return row


def derive_ticket_rows(rows: list[dict[str, Any]], is_airline: bool) -> list[dict[str, Any]]:
    """derive_ticket_row over a list, plus the multi-sector split.

    The manual entry path only. It splits BOTH statement types, because a ticket
    punched leg by leg is meant to land as one row per leg whichever type it is.

    TicketExtractionService.extract deliberately does NOT call this — it runs
    derive_ticket_row itself and splits only B2B, so an uploaded BSP file still
    lands as one row per ticket document.
    """
    out = [derive_ticket_row(dict(r), is_airline) for r in rows]
    return _split_multi_sector_rows(out)


class TicketExtractionService:

    @staticmethod
    async def extract(
        file_bytes: bytes,
        file_name: str,
        column_mapping: dict[str, str] | None = None,
        statement_type: str = "B2B",
        sheet_name: str | None = None,
        header_row: int | None = None,
    ) -> dict:
        """
        Parse spreadsheet bytes and return a preview dict.

        statement_type: 'B2B' or 'AIRLINE' — used to choose template and
        trigger airline-specific post-processing.

        `sheet_name` and `header_row` are DETECTED when None and OBEYED when given.
        The caller must send back what the first call detected: a column map is a
        list of column NAMES, so re-detecting a header one row out on the second
        read would rename every column and drop the whole mapping on the floor.
        """
        warnings: list[str] = []
        try:
            read = spreadsheet.read_table(
                file_bytes, file_name,
                sheet=sheet_name, header_row=header_row, recognise=recognised_count,
            )
        except spreadsheet.SpreadsheetError as exc:
            raise ValueError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — anything else is still unreadable
            raise ValueError(f"Could not read the file: {exc}") from exc

        df = read.df
        xls_columns: list[str] = list(read.columns)
        period = spreadsheet.parse_period(read.preamble)

        # What the file said about itself above its header, and what we made of it.
        base: dict[str, Any] = {
            "file_name":         file_name,
            "sheet_name":        read.sheet,
            "sheet_names":       read.sheets,
            "header_row":        read.header_row,
            "preamble":          read.preamble,
            "detected_from":     period[0] if period else None,
            "detected_to":       period[1] if period else None,
        }

        if df.empty:
            return {
                **base, "total_rows": 0, "rows": [],
                "warnings": ["File has no data rows."],
                "xls_columns": xls_columns, "suggested_mapping": {},
                "is_template_match": False, "sample_row": {}, "sample_rows": {},
                "unmapped_columns": xls_columns, "fuzzy_suggestions": {},
            }

        # Auto-detect airline format even if statement_type not explicitly set
        is_airline = statement_type == "AIRLINE" or _detect_airline_format(xls_columns)

        if column_mapping:
            # Kept in the wire direction {canonical: column} rather than inverted.
            # Inverting loses a column feeding two fields — which is exactly what
            # happens when the user accepts the "Doc Date is also the ticket date"
            # suggestion.
            user_map: dict[str, str] = {
                canon: xls_col
                for canon, xls_col in column_mapping.items()
                if xls_col and xls_col in xls_columns
            }
        else:
            user_map = {canon: col for col, canon in _build_col_map(xls_columns).items()}

        if not user_map:
            warnings.append(
                "No recognised columns found — check that the header row is the one "
                "highlighted below, and map the columns by hand."
            )

        suggested_mapping = user_map
        claimed = {col for col in user_map.values()}
        unmapped_columns = [c for c in xls_columns if c not in claimed]
        col_map = {col: canon for canon, col in user_map.items()}

        fuzzy = _fuzzy_suggestions(
            xls_columns, col_map,
            [f for f in _COL_ALIASES if f not in user_map],
        )
        _suggest_fallbacks(col_map, fuzzy)

        is_template_match: bool = len(user_map) >= _TEMPLATE_MATCH_THRESHOLD

        # Up to three sample values per source column. One was not enough to tell a
        # date column from a reference number when the first row happens to be blank.
        sample_rows: dict[str, list[str]] = {}
        for col in xls_columns:
            vals = [v for v in (_to_str(x) for x in df[col].head(6).tolist()) if v]
            sample_rows[col] = vals[:3]
        sample_row: dict[str, str] = {c: (v[0] if v else "") for c, v in sample_rows.items()}

        rows: list[dict] = []
        skipped_totals: list[int] = []
        for i, (_, raw) in enumerate(df.iterrows()):
            row: dict[str, Any] = {"row_order": i + 1}

            # ── Map standard columns ──────────────────────────────────────
            for canon, df_col in user_map.items():
                val = raw.get(df_col)
                if canon in NUMERIC_COLS:
                    row[canon] = _to_float(val)
                else:
                    s = _to_str(val)
                    if canon == "sold_to" and s:
                        s = s.strip().lower()
                    row[canon] = s

            # ── The statement's own total line is not a ticket ─────────────
            # A statement ends with a row that sums the columns above it. It has
            # money in every amount column and NOTHING identifying a document —
            # no ticket number, no voucher, no PNR, no passenger. Importing it
            # doubles every figure in the batch, and it is the one row nobody
            # checks because it looks right on the statement.
            #
            # Matched structurally, not by the word "Total": the real file that
            # prompted this carries no literal at all, just an unlabelled row of
            # sums. sector_split.is_total_row handles the labelled kind for the
            # vendor-statement importers; this catches the unlabelled kind.
            if _is_total_line(row):
                skipped_totals.append(i + 1)
                continue

            # ── Every source cell, verbatim ───────────────────────────────
            # Keyed by its original header, mapped or not. This is what makes
            # "upload any statement" true: a column with no canonical home is
            # preserved rather than dropped, and a batch can be re-mapped later
            # without the file — the same thing statements.py's /reprocess does.
            row["raw_data"] = {c: (_to_str(raw.get(c)) or "") for c in xls_columns}

            if is_airline:
                # DataFrame-only pre-fills: source columns the canonical alias
                # map does not cover. Everything past this point is dict work
                # and lives in derive_ticket_row, shared with manual entry.
                # Each guard preserves key-absence, which derive_ticket_row and
                # _split_multi_sector_rows rely on (see their docstrings).
                tax_breakup = _build_tax_breakup(raw, xls_columns, raw)
                if tax_breakup:
                    row["tax_breakup"] = tax_breakup

                if not row.get("pax_name"):
                    v = _to_str(next((raw.get(c) for c in xls_columns
                                      if c.strip().lower() in ("pax_name", "paxname")), None))
                    if v:
                        row["pax_name"] = v

                if not row.get("travel_dt"):
                    v = _to_str(next((raw.get(c) for c in xls_columns
                                      if c.strip().lower() in ("traveldt", "travel_dt")), None))
                    if v:
                        row["travel_dt"] = v

            rows.append(derive_ticket_row(row, is_airline))

        if skipped_totals:
            where = ", ".join(str(n) for n in skipped_totals[:5])
            warnings.append(
                f"Skipped {len(skipped_totals)} row(s) that carry amounts but no ticket, "
                f"document or passenger — these are the statement's own total lines "
                f"(row {where}). Importing them would double every figure in the batch."
            )

        # Multi-sector splitting (B2B style — only when not airline BSP format)
        if not is_airline:
            rows = _split_multi_sector_rows(rows)

        return {
            **base,
            "total_rows":        len(rows),
            "rows":              rows,
            "warnings":          warnings,
            "xls_columns":       xls_columns,
            "suggested_mapping": suggested_mapping,
            "is_template_match": is_template_match,
            "sample_row":        sample_row,
            "sample_rows":       sample_rows,
            "unmapped_columns":  unmapped_columns,
            "fuzzy_suggestions": fuzzy,
        }
