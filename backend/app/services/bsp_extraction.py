"""
BspExtractionService
────────────────────
Parses a BSP settlement file (Excel/CSV) and returns structured rows for a
2-step extract → preview → confirm flow, mirroring TicketExtractionService /
DealExtractionService. Auto-maps common BSP headers to canonical fields; the
preview carries `xls_columns` + `suggested_mapping` so the UI can show/adjust
the mapping.
"""
from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# canonical field -> accepted header aliases (normalized: lowercase, alphanumerics only)
_ALIASES: dict[str, list[str]] = {
    "ticket_number":    ["ticketnumber", "ticketno", "ticket", "tktno", "documentno", "documentnumber", "docno"],
    "airline_code":     ["airlinecode", "airline", "aircode", "carrier", "carriercode", "aicode"],
    "gross":            ["gross", "grossamount", "grossfare", "fare", "totalfare", "faretotal"],
    "commission":       ["commission", "comm", "commamount", "commissionamount", "commamt"],
    "adm":              ["adm", "admamount", "admdebit", "debit"],
    "acm":              ["acm", "acmamount", "acmcredit", "credit"],
    "refund":           ["refund", "refundamount", "rfnd", "refundamt"],
    "net_due":          ["netdue", "net", "netremit", "netamount", "netpayable", "amountdue", "netremittance"],
    "transaction_type": ["transactiontype", "txntype", "transaction", "type", "documenttype", "doctype"],
}


def _norm(h: Any) -> str:
    return "".join(ch for ch in str(h).strip().lower() if ch.isalnum())


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s == "" or s.lower() in ("nan", "none", "-"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _clean_str(v: Any) -> str | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s or None


class BspExtractionService:
    @staticmethod
    async def extract(file_bytes: bytes, file_name: str) -> dict:
        name = (file_name or "").lower()
        try:
            if name.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
            else:
                df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        except Exception as exc:  # noqa: BLE001 — surface as a 422 upstream
            raise ValueError(f"Could not read file: {exc}")

        df = df.where(pd.notna(df), None)
        xls_columns = [str(c) for c in df.columns]

        # canonical -> actual header
        norm_to_actual = {_norm(c): c for c in xls_columns}
        col_map: dict[str, str] = {}
        for canon, aliases in _ALIASES.items():
            for a in aliases:
                if a in norm_to_actual:
                    col_map[canon] = norm_to_actual[a]
                    break

        warnings: list[str] = []
        if "ticket_number" not in col_map:
            warnings.append("No ticket-number column detected — rows won't be matchable to tickets.")
        if not col_map:
            warnings.append("No known BSP columns detected; check the file headers.")

        rows: list[dict] = []
        for _, r in df.iterrows():
            raw = {c: _clean_str(r.get(c)) for c in xls_columns}

            def g(canon: str):
                col = col_map.get(canon)
                return raw.get(col) if col else None

            tt = (g("transaction_type") or "").strip().lower() or None
            rows.append({
                "ticket_number":    g("ticket_number"),
                "airline_code":     g("airline_code"),
                "gross":            _to_float(g("gross")),
                "commission":       _to_float(g("commission")),
                "adm":              _to_float(g("adm")),
                "acm":              _to_float(g("acm")),
                "refund":           _to_float(g("refund")),
                "net_due":          _to_float(g("net_due")),
                "transaction_type": tt[:10] if tt else None,
                "raw_data":         raw,
            })

        return {
            "file_name":         file_name,
            "total_rows":        len(rows),
            "rows":              rows,
            "warnings":          warnings,
            "xls_columns":       xls_columns,
            "suggested_mapping": dict(col_map),
        }
