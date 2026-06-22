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

import io
import logging
import re
from typing import Any

import pandas as pd

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
    "ticket_date":         ["ticketdate", "ticket_date", "ticket date", "ticket_date"],
    "last_name":           ["lastname", "last_name", "last name", "surname"],
    "first_name":          ["firstname", "first_name", "first name"],
    "sector":              ["sector", "sectors"],
    "booking_class":       ["class", "bookingclass", "booking_class"],
    "departure_datetime":  ["departuredatetime", "departure_datetime", "departuretime",
                            "departure"],
    "gds_pnr":             ["gds_pnr", "gdspnr", "pnr", "gal_pnr", "galpnr"],
    "airlines_code":       ["airlinescode", "airlines_code", "airlinecode",
                            "airline_code", "airlineid", "airline"],
    "airline_name":        ["airlinename", "airline_name", "airline name",
                            "air_name", "airname"],
    "ticket_number":       ["ticketnumber", "ticket_number", "ticketno", "ticket_no"],
    "sell_fare":           ["sellfare", "sell_fare", "base_fare", "basefare"],
    "sell_tax":            ["selltax", "sell_tax", "total_tax", "totaltax"],
    "sell_tax_yq":         ["selltax_yq", "sell_tax_yq", "selltaxyq",
                            "yqtax", "yq_tax"],
    "sale_yr":             ["sale_yr", "saleyr"],
    "sale_k3":             ["sale_k3", "salek3"],
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
    "incentive_sell":      ["incentive_sell", "incentivesell"],
    "dis_sell":            ["dis_sell", "dissell", "discount"],
    "tds_sell":            ["tds_sell", "tdssell", "tds"],
    "total_amt":           ["totalamt", "total_amt", "total", "total_fare",
                            "totalfare", "actual_selling_fare", "actualselling"],
    "paid_by_credit_card": ["paidbycreditcard", "paid_by_credit_card", "creditcard"],
    "net_amt":             ["net_amt", "netamt", "net", "net_remit", "netremit"],
    "cc":                  ["cc", "fop_details", "fopdetails"],
    "acc_code":            ["acccode", "acc_code", "ac_acct", "acacct"],
    "sold_to":             ["soldto", "sold_to", "sold to", "soldtoparty"],
    "customer_name":       ["customername", "customer_name", "customer name",
                            "cliententityname", "clientname", "client name"],
    "tour_code":           ["tourcode", "tour_code", "tour code", "tourcd", "tour_cd",
                            "tour_code"],
    # ── airline-specific new fields ───────────────────────────────────────────
    "pax_name":             ["pax_name", "paxname"],
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
    "other_tax":            ["other_tax", "othertax"],
    "comm_percent":         ["comm(%)", "commpercent", "comm_percent"],
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
}

# Build reverse map: lowercase_alias → canonical
_ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in _COL_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_CANON[_alias] = _canon

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
}

# Columns split equally across multi-sector legs
_SPLIT_FIN_COLS = {"sell_fare", "sell_tax", "sell_tax_yq", "sale_yr"}

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


def _split_multi_sector_rows(rows: list[dict]) -> list[dict]:
    """Expand multi-sector B2B rows (3+ airports) into one row per leg."""
    result: list[dict] = []
    for row in rows:
        sector = (row.get("sector") or "").strip()
        airports = [a.strip() for a in sector.split("/") if a.strip()]
        n = len(airports) - 1

        if n <= 1:
            row.setdefault("split_type", "normal")
            result.append(row)
            continue

        raw_cls_str = (row.get("booking_class") or "").strip()
        classes = [c.strip() for c in raw_cls_str.split("/") if c.strip()]
        while len(classes) < n:
            classes.append(classes[-1] if classes else "")

        for i in range(n):
            r = dict(row)
            r["sector"] = f"{airports[i]}/{airports[i + 1]}"
            r["booking_class"] = classes[i]
            r["split_type"] = "split"
            for col in _SPLIT_FIN_COLS:
                if row.get(col) is not None:
                    r[col] = round(row[col] / n, 2)
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


def _build_col_map(df_columns: list[str]) -> dict[str, str]:
    """Map DataFrame column names → canonical field names."""
    mapping: dict[str, str] = {}
    seen_canon: set[str] = set()
    for col in df_columns:
        key = col.strip().lower().replace(" ", "_").replace(".", "")
        canon = _ALIAS_TO_CANON.get(key)
        if not canon:
            canon = _ALIAS_TO_CANON.get(key.replace("_", ""))
        if canon and canon not in seen_canon:
            mapping[col] = canon
            seen_canon.add(canon)
    return mapping


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


def _parse_pax_name(pax_name: str | None) -> tuple[str | None, str | None]:
    """Parse 'LASTNAME/FIRSTNAME M' → (last_name, first_name)."""
    if not pax_name:
        return None, None
    parts = pax_name.strip().split("/", 1)
    last = parts[0].strip() or None
    first = parts[1].strip() if len(parts) > 1 else None
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


class TicketExtractionService:

    @staticmethod
    async def extract(
        file_bytes: bytes,
        file_name: str,
        column_mapping: dict[str, str] | None = None,
        statement_type: str = "B2B",
    ) -> dict:
        """
        Parse XLS/XLSX bytes and return a preview dict.

        statement_type: 'B2B' or 'AIRLINE' — used to choose template and
        trigger airline-specific post-processing.
        """
        warnings: list[str] = []
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        except Exception as exc:
            raise ValueError(f"Could not read Excel file: {exc}") from exc

        df = df.dropna(how="all")
        xls_columns: list[str] = list(df.columns)

        if df.empty:
            return {
                "file_name": file_name, "total_rows": 0, "rows": [],
                "warnings": ["File has no data rows."],
                "xls_columns": xls_columns, "suggested_mapping": {},
                "is_template_match": False, "sample_row": {},
            }

        # Auto-detect airline format even if statement_type not explicitly set
        is_airline = statement_type == "AIRLINE" or _detect_airline_format(xls_columns)

        if column_mapping:
            col_map: dict[str, str] = {
                xls_col: canon
                for canon, xls_col in column_mapping.items()
                if xls_col and xls_col in xls_columns
            }
        else:
            col_map = _build_col_map(xls_columns)

        if not col_map:
            warnings.append("No recognised columns found — check the header row matches the expected format.")

        suggested_mapping: dict[str, str] = {canon: xls_col for xls_col, canon in col_map.items()}
        is_template_match: bool = len(col_map) >= _TEMPLATE_MATCH_THRESHOLD

        # First-row sample for the mapping UI
        sample_row: dict[str, str] = {}
        if not df.empty:
            first_raw = df.iloc[0]
            for col in xls_columns:
                val = first_raw.get(col)
                s = str(val).strip() if val is not None else ""
                sample_row[col] = "" if s in ("nan", "NaN", "-", "--", "N/A") else s

        rows: list[dict] = []
        for i, (_, raw) in enumerate(df.iterrows()):
            row: dict[str, Any] = {"row_order": i + 1}

            # ── Map standard columns ──────────────────────────────────────
            for df_col, canon in col_map.items():
                val = raw.get(df_col)
                if canon in NUMERIC_COLS:
                    row[canon] = _to_float(val)
                else:
                    s = _to_str(val)
                    if canon == "sold_to" and s:
                        s = s.strip().lower()
                    row[canon] = s

            if is_airline:
                # ── Tax breakup from Tax_Type/Tax pairs ───────────────────
                tax_breakup = _build_tax_breakup(raw, xls_columns, raw)
                if tax_breakup:
                    row["tax_breakup"] = tax_breakup
                    # Derive individual tax columns used by deal matching
                    if "YR" in tax_breakup and row.get("sale_yr") is None:
                        row["sale_yr"] = tax_breakup["YR"]
                    if "K3" in tax_breakup and row.get("sale_k3") is None:
                        row["sale_k3"] = tax_breakup["K3"]
                    # sell_tax_yq: prefer YQTax column already mapped; fallback to YQ in breakup
                    if row.get("sell_tax_yq") is None and "YQ" in tax_breakup:
                        row["sell_tax_yq"] = tax_breakup["YQ"]

                # ── Pax_Name → last_name / first_name ────────────────────
                raw_pax = row.get("pax_name") or _to_str(
                    next((raw.get(c) for c in xls_columns
                          if c.strip().lower() in ("pax_name", "paxname")), None)
                )
                if raw_pax:
                    row["pax_name"] = raw_pax
                    last, first = _parse_pax_name(raw_pax)
                    if not row.get("last_name"):
                        row["last_name"] = last
                    if not row.get("first_name"):
                        row["first_name"] = first

                # ── TravelDt → departure_datetime (first leg date) ────────
                raw_travel_dt = row.get("travel_dt") or _to_str(
                    next((raw.get(c) for c in xls_columns
                          if c.strip().lower() in ("traveldt", "travel_dt")), None)
                )
                if raw_travel_dt:
                    row["travel_dt"] = raw_travel_dt
                    if not row.get("departure_datetime"):
                        row["departure_datetime"] = _parse_first_date(raw_travel_dt)

                # ── Segment type auto-detection ────────────────────────────
                if not row.get("segment_type"):
                    row["segment_type"] = _detect_segment_type_from_sector(row.get("sector"))

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

            rows.append(row)

        # Multi-sector splitting (B2B style — only when not airline BSP format)
        if not is_airline:
            rows = _split_multi_sector_rows(rows)

        return {
            "file_name":         file_name,
            "total_rows":        len(rows),
            "rows":              rows,
            "warnings":          warnings,
            "xls_columns":       xls_columns,
            "suggested_mapping": suggested_mapping,
            "is_template_match": is_template_match,
            "sample_row":        sample_row,
        }
