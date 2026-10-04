"""A statement's own balance and total lines — never bookings.

A consolidator's GDS statement is a running account: an `OLD <opening>` line above the
header and a `BALANCE <closing>` line after the last ticket, with opening + Σ net = closing.
The real export writes both into its last two columns, so once mapped the closing line is
`{"cancellation_markup": "BALANCE", "net_amount": "960428.43"}` — a row with money and no
booking behind it. Counted as an entry it inflates every count and total on the statement
(the 16-22 Aug file read 38 entries and a Net Amount of 12.9 lakh for 37 tickets and 3.33
lakh), and priced as a ticket it comes back "unmatched".

This module is the one definition of such a line. The ingest derive step stamps it on the
row (`data["row_kind"]`), the statements router keeps stamped rows out of entries and
totals, commission income skips them, and the Payment Module reads the balances from them.
It imports nothing from the app, because the parser path (`services/flat_statement.py`)
calls it at import-free speed for every row.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

ROW_KIND_KEY = "row_kind"
ROW_LABEL_KEY = "row_label"
ROW_KINDS = ("opening", "closing", "payment", "total")

# Matched exactly or as a leading word ("BALANCE AS ON 22-AUG"), and only on a row with no
# ticket, PNR or passenger — a real booking can never be mistaken for one.
OPENING_MARKERS = ("OLD", "OPENING", "OPENING BALANCE", "OLD BALANCE", "B/F",
                   "BROUGHT FORWARD")
CLOSING_MARKERS = ("BALANCE", "CLOSING", "CLOSING BALANCE", "C/F", "CARRIED FORWARD")
# What the agency paid against the account during the period. The real 08-15 Aug export
# prints `LESS PAYMENT 1397642.4` between its subtotal and its BALANCE, so the account
# reads: opening + Σ ticket net − payments = closing.
PAYMENT_MARKERS = ("LESS PAYMENT", "LESS PAYMENTS", "PAYMENT", "PAYMENTS",
                   "PAYMENT RECEIVED", "PAYMENTS RECEIVED", "LESS RECEIPT", "RECEIPT",
                   "RECEIPTS", "AMOUNT RECEIVED", "AMOUNT PAID")
TOTAL_MARKERS = ("TOTAL", "TOTALS", "GRAND TOTAL", "SUB TOTAL", "SUBTOTAL")

IDENTITY_KEYS = ("ticket_number", "pnr", "airline_pnr", "gds_pnr",
                 "passenger_name", "first_name", "last_name")

MONEY_KEYS = (
    "base_fare", "yq", "other_taxes", "taxes", "ssr_amount", "reschedule_charges",
    "total_fare", "commission_amount", "incentive_amount", "tds", "service_charge",
    "service_fee", "gst_on_sf", "agent_penalty", "cancellation_markup", "net_amount",
)


def to_decimal(v) -> Decimal | None:
    """A cell to Decimal, or None when it is not a number. Never through float."""
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _text(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def balance_kind(data: dict | None) -> tuple[str, str] | None:
    """('opening' | 'closing' | 'payment' | 'total', label) for a statement's own lines.

    None for anything that could be a booking. A row with no identity AND no label but a
    lone Net Amount is a footer nobody labelled (the real export's subtotal, opening + Σ
    net) — kept out as a 'total', never used as a balance.
    """
    data = data or {}
    if any(_text(data.get(k)) for k in IDENTITY_KEYS):
        return None
    for k, v in data.items():
        if k == ROW_KIND_KEY or not isinstance(v, str):
            continue
        t = " ".join(v.upper().split())
        for kind, markers in (("opening", OPENING_MARKERS), ("closing", CLOSING_MARKERS),
                              ("payment", PAYMENT_MARKERS), ("total", TOTAL_MARKERS)):
            if any(t == m or t.startswith(m + " ") for m in markers):
                return kind, t
    money = [k for k in MONEY_KEYS if to_decimal(data.get(k)) is not None]
    if money == ["net_amount"]:
        return "total", "UNLABELLED TOTAL"
    return None


def tag(data: dict) -> None:
    """Stamp `row_kind` / `row_label` on a balance or total line, in place. Idempotent.

    Called from the ingest derive step, so a reprocess — which rebuilds `data` through the
    same builder — re-stamps it, and a line that stops looking like one is un-stamped.
    """
    kind = balance_kind(data)
    if kind is None:
        data.pop(ROW_KIND_KEY, None)
        data.pop(ROW_LABEL_KEY, None)
        return
    data[ROW_KIND_KEY], data[ROW_LABEL_KEY] = kind


def is_balance_row(data: dict | None) -> bool:
    return bool(data) and (data.get(ROW_KIND_KEY) in ROW_KINDS or balance_kind(data) is not None)


def account_figures(lines) -> dict:
    """{opening, closing, payments} from a statement's own lines, as Decimals or None.

    `lines` is any iterable of (kind, amount). Payments are summed and taken as positive —
    a vendor may print the deduction either way round. The last closing line wins.
    """
    opening = closing = None
    payments = None
    for kind, amount in lines:
        amount = to_decimal(amount)
        if amount is None:
            continue
        if kind == "opening":
            opening = amount
        elif kind == "closing":
            closing = amount
        elif kind == "payment":
            payments = abs(amount) if payments is None else payments + abs(amount)
    return {"opening": opening, "closing": closing, "payments": payments}


def derived_ticket_net(opening, closing, payments) -> Decimal | None:
    """What the tickets must add up to for the account to close: closing − opening + paid."""
    if opening is None or closing is None:
        return None
    return closing - opening + (payments or Decimal("0"))
