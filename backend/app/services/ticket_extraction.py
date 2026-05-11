"""
TicketExtractionService
────────────────────────
Parses supplier statement XLS/XLSX files and returns structured rows.

Expected XLS columns (case-insensitive, flexible header detection):
  BookingRef, SegmentType, InvoiceType, InvoiceNo, TicketDate, LastName, FirstName,
  Sector, Class, DepartureDateTime, GDS_PNR, AirlinesCode, TicketNumber, SellFare,
  SellTax, SellTax_YQ, Sale_YR, Sale_K3, REI_Sell, Seat_Selection, Excessbagage,
  Meals, RFD_SELL, CAN_Charge, Booking_Fee_Sell, CGST_Sell, SGST_Sell, IGST_Sell,
  Comm_Sell, ADM, Incentive_Sell, DIS_Sell, TDS_Sell, TotalAmt, PaidByCreditCard,
  Net_AMT, CC, AccCode
"""
from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Canonical column name → list of accepted header variants (lowercase, stripped)
_COL_ALIASES: dict[str, list[str]] = {
    "booking_ref":         ["bookingref", "booking_ref", "booking ref"],
    "segment_type":        ["segmenttype", "segment_type", "segment type"],
    "invoice_type":        ["invoicetype", "invoice_type", "invoice type"],
    "invoice_no":          ["invoiceno", "invoice_no", "invoice no", "invoicenumber"],
    "ticket_date":         ["ticketdate", "ticket_date", "ticket date"],
    "last_name":           ["lastname", "last_name", "last name", "surname"],
    "first_name":          ["firstname", "first_name", "first name"],
    "sector":              ["sector"],
    "booking_class":       ["class", "bookingclass", "booking_class"],
    "departure_datetime":  ["departuredatetime", "departure_datetime", "departuretime", "departure"],
    "gds_pnr":             ["gds_pnr", "gdspnr", "pnr"],
    "airlines_code":       ["airlinescode", "airlines_code", "airlinecode", "airline_code", "airlineid"],
    "ticket_number":       ["ticketnumber", "ticket_number", "ticketno"],
    "sell_fare":           ["sellfare", "sell_fare"],
    "sell_tax":            ["selltax", "sell_tax"],
    "sell_tax_yq":         ["selltax_yq", "sell_tax_yq", "selltaxyq"],
    "sale_yr":             ["sale_yr", "saleyr"],
    "sale_k3":             ["sale_k3", "salek3"],
    "rei_sell":            ["rei_sell", "reisell"],
    "seat_selection":      ["seat_selection", "seatselection"],
    "excess_baggage":      ["excessbagage", "excessbaggage", "excess_baggage"],
    "meals":               ["meals"],
    "rfd_sell":            ["rfd_sell", "rfdsell"],
    "can_charge":          ["can_charge", "cancharge"],
    "booking_fee_sell":    ["booking_fee_sell", "bookingfeesell"],
    "cgst_sell":           ["cgst_sell", "cgstsell", "cgst"],
    "sgst_sell":           ["sgst_sell", "sgstsell", "sgst"],
    "igst_sell":           ["igst_sell", "igstsell", "igst"],
    "comm_sell":           ["comm_sell", "commsell", "commission"],
    "adm":                 ["adm"],
    "incentive_sell":      ["incentive_sell", "incentivesell"],
    "dis_sell":            ["dis_sell", "dissell", "discount"],
    "tds_sell":            ["tds_sell", "tdssell", "tds"],
    "total_amt":           ["totalamt", "total_amt", "total"],
    "paid_by_credit_card": ["paidbycreditcard", "paid_by_credit_card", "creditcard"],
    "net_amt":             ["net_amt", "netamt", "net"],
    "cc":                  ["cc"],
    "acc_code":            ["acccode", "acc_code"],
    "airline_name":        ["airlinename", "airline_name", "airline name", "airline"],
}

# Build reverse map: lowercase_alias → canonical
_ALIAS_TO_CANON: dict[str, str] = {}
for canon, aliases in _COL_ALIASES.items():
    for alias in aliases:
        _ALIAS_TO_CANON[alias] = canon

NUMERIC_COLS = {
    "sell_fare", "sell_tax", "sell_tax_yq", "sale_yr", "sale_k3",
    "rei_sell", "seat_selection", "excess_baggage", "meals",
    "rfd_sell", "can_charge", "booking_fee_sell",
    "cgst_sell", "sgst_sell", "igst_sell", "comm_sell",
    "adm", "incentive_sell", "dis_sell", "tds_sell",
    "total_amt", "paid_by_credit_card", "net_amt",
}


def _to_float(val: Any) -> float | None:
    """Convert a cell value to float, treating '-', '', NaN as None."""
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
    for col in df_columns:
        key = col.strip().lower().replace(" ", "_").replace(".", "")
        # try exact
        canon = _ALIAS_TO_CANON.get(key)
        if not canon:
            # try without underscores
            canon = _ALIAS_TO_CANON.get(key.replace("_", ""))
        if canon:
            mapping[col] = canon
    return mapping


class TicketExtractionService:

    @staticmethod
    async def extract(file_bytes: bytes, file_name: str) -> dict:
        """
        Parse XLS/XLSX bytes and return a preview dict:
        {
            "file_name": str,
            "total_rows": int,
            "rows": [TicketRow-compatible dicts],
            "warnings": [str],
        }
        """
        warnings: list[str] = []
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        except Exception as exc:
            raise ValueError(f"Could not read Excel file: {exc}") from exc

        # Drop fully-empty rows
        df = df.dropna(how="all")

        if df.empty:
            return {"file_name": file_name, "total_rows": 0, "rows": [], "warnings": ["File has no data rows."]}

        col_map = _build_col_map(list(df.columns))
        if not col_map:
            warnings.append("No recognised columns found — check the header row matches the expected format.")

        rows = []
        for i, (_, raw) in enumerate(df.iterrows()):
            row: dict[str, Any] = {"row_order": i + 1}
            for df_col, canon in col_map.items():
                val = raw.get(df_col)
                if canon in NUMERIC_COLS:
                    row[canon] = _to_float(val)
                else:
                    row[canon] = _to_str(val)
            rows.append(row)

        return {
            "file_name": file_name,
            "total_rows": len(rows),
            "rows": rows,
            "warnings": warnings,
        }
