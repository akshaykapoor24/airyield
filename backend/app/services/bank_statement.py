"""Reading a bank statement export, and guessing who each line is from.

Pure functions — no DB, no FastAPI. The router (api/v1/bank_statements.py) stores what
this returns and owns every decision that needs the database: duplicates, links, ledger
postings.

THE FILE IS THE TENANT'S OWN BANK ACCOUNT, not a customer's. Every line is money moving
in or out of the travel agency's business: a deposit is (usually) a customer paying an
invoice, a withdrawal is a supplier being paid, a credit card being cleared, a transfer.
Only deposits are linked to a party today — that is what "billed vs received" needs.

WRITTEN AGAINST ICICI'S "Detailed Statement" EXPORT, kept loose enough for the others:

  * ~16 rows of account details ("Name:", "A/C No:", "IFSC Code:", "Transaction Period")
    ABOVE the table, as label / value pairs in neighbouring cells;
  * the table header is found by its vocabulary, not its position — HDFC calls the
    remarks "Narration", SBI "Description", Axis "Particulars";
  * amounts in the Indian grouping ("2,72,119.00"), blank rather than 0 in the unused
    column; dates as "01/Sep/2026", with the posted time as "01/09/26 11:21:55 AM".

THE COUNTERPARTY IS INSIDE THE REMARKS. There is no payer column: "NEFT-HDFCH0122…-ADITI
DHAR-0001F…" names the payer third, "INF/INFT/045724293821/UNICORN" last, and banks cut
the remark at a fixed width, so a name is routinely truncated ("HILFEN PHARMACE").
`counterparty` digs the name out; `name_score` is built to forgive the truncation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.services import spreadsheet

# ── Categories ───────────────────────────────────────────────────────────────
# A deposit linked to a party is always a `receipt`. The rest are what a line is when it
# is NOT a customer paying — kept so a statement can be fully sorted, and so Purchase
# Accounting and the credit card screens have something to read later.
CATEGORIES = {
    "receipt":        "Customer receipt",
    "refund":         "Refund received",
    "vendor_payment": "Vendor payment",
    "credit_card":    "Credit card payment",
    "bank_charges":   "Bank charges",
    "transfer":       "Transfer / own account",
    "other":          "Other",
}
IN_CATEGORIES = {"receipt", "refund", "transfer", "other"}
OUT_CATEGORIES = {"vendor_payment", "credit_card", "bank_charges", "transfer", "other"}

# ── Column vocabulary ────────────────────────────────────────────────────────
# Normalised (lowercase, letters and digits only). Fields are resolved in THIS order and
# each column is claimed once, so "Transaction Posted Date" is taken as posted_at before
# the looser "date" patterns of txn_date can reach it. Patterns shorter than four
# characters only ever match exactly: "cr" is inside "description".
_COLUMNS: list[tuple[str, list[str]]] = [
    ("posted_at",  ["transactionposteddate", "posteddate", "postingdate"]),
    ("value_date", ["valuedate", "valuedt"]),
    ("txn_date",   ["transactiondate", "txndate", "trandate", "date"]),
    ("tran_id",    ["tranid", "transactionid", "txnid"]),
    ("cheque_ref", ["chequenorefno", "chqrefno", "refnochequeno", "chequeno", "refno", "reference"]),
    ("remarks",    ["transactionremarks", "remarks", "narration", "description", "particulars", "details"]),
    ("withdrawal", ["withdrawalamtinr", "withdrawalamt", "withdrawal", "debitamount", "debit", "dr"]),
    ("deposit",    ["depositamtinr", "depositamt", "deposit", "creditamount", "credit", "cr"]),
    ("balance",    ["balanceinr", "closingbalance", "balance"]),
    ("line_no",    ["sn", "sno", "srno", "slno", "serialno"]),
]

# Label on the left, value in the next filled cell to its right.
_META_LABELS = {
    "name": "account_name",
    "accountname": "account_name",
    "acno": "account_no",
    "accountno": "account_no",
    "accountnumber": "account_no",
    "ifsccode": "ifsc",
    "ifsc": "ifsc",
    "acbranch": "branch",
    "branch": "branch",
    "accountcurrency": "currency",
    "currency": "currency",
    "transactionperiod": "period",
    "statementperiod": "period",
}

# First four letters of an IFSC.
_BANKS = {
    "ICIC": "ICICI Bank", "HDFC": "HDFC Bank", "SBIN": "State Bank of India",
    "UTIB": "Axis Bank", "KKBK": "Kotak Mahindra Bank", "YESB": "Yes Bank",
    "PUNB": "Punjab National Bank", "BARB": "Bank of Baroda", "INDB": "IndusInd Bank",
    "IDFB": "IDFC FIRST Bank", "CNRB": "Canara Bank", "UBIN": "Union Bank of India",
    "FDRL": "Federal Bank", "RATN": "RBL Bank", "AUBL": "AU Small Finance Bank",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ── Values ───────────────────────────────────────────────────────────────────

def parse_amount(value) -> Decimal:
    """'2,72,119.00' → 272119.00. Blank → 0. '(500)' and '500-' are negative.

    A trailing Cr / Dr is dropped: which column the number sits in already says the
    direction, and the balance column is only ever shown, never summed.
    """
    s = spreadsheet.cell(value)
    if not s:
        return Decimal("0")
    s = re.sub(r"\s*(cr|dr)\.?$", "", s, flags=re.I).replace(",", "").replace(" ", "")
    s = s.replace("₹", "").replace("INR", "").replace("Rs.", "")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    elif s.endswith("-"):
        neg, s = True, s[:-1]
    try:
        n = Decimal(s)
    except InvalidOperation:
        return Decimal("0")
    return (-n if neg else n).quantize(Decimal("0.01"))


_DATE_FORMATS = (
    "%d/%b/%Y", "%d-%b-%Y", "%d %b %Y", "%d/%b/%y", "%d-%b-%y", "%d %b %y",
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S",
)
_DATETIME_FORMATS = (
    "%d/%m/%y %I:%M:%S %p", "%d/%m/%Y %I:%M:%S %p", "%d/%m/%y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d/%b/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S",
)


def parse_date(value) -> date | None:
    """Day-first, always — these are Indian statements. None when it does not parse."""
    s = spreadsheet.cell(value)
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    dt = parse_datetime(s)
    return dt.date() if dt else None


def parse_datetime(value) -> datetime | None:
    s = spreadsheet.cell(value)
    if not s:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ── Remarks ──────────────────────────────────────────────────────────────────

# Transaction-type codes and bank shorthand that are never a party's name.
_CODES = {
    "NEFT", "RTGS", "IMPS", "MMT", "UPI", "INF", "INFT", "BIL", "ONL", "BPAY", "TRF", "NA",
    "ATD", "CLG", "CHQ", "ACH", "NACH", "ECS", "IFT", "ICI", "CMS", "POS", "ATM", "CASH",
    "BY", "TO", "FROM", "TRANSFER", "PAYMENT", "INB", "MB", "IB",
}
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_REF_RE = re.compile(r"^(?=.*\d)[A-Z0-9]{6,}$")


def _mode(remarks: str) -> str | None:
    """How the money moved, read off the remark's prefix."""
    head = remarks.upper()
    for token, mode in (
        ("NEFT", "neft"), ("RTGS", "rtgs"), ("IMPS", "imps"), ("UPI", "upi"),
        ("INFT", "transfer"), ("INF/", "transfer"), ("TRF", "transfer"),
        ("BIL/", "bill_pay"), ("ATD", "auto_debit"), ("NACH", "auto_debit"), ("ACH", "auto_debit"),
        ("CLG", "cheque"), ("CHQ", "cheque"), ("CASH", "cash"), ("ATM", "cash"), ("POS", "card"),
    ):
        if head.startswith(token) or f"/{token}" in head[:12] or f"-{token}" in head[:12]:
            return mode
    return None


def _tokens(remarks: str) -> list[str]:
    s = remarks.strip()
    # "NEFT-HDFC…-NAME-…" and "RTGS-KKBK…-NAME" separate with dashes; everything else
    # ICICI writes with slashes. A dash inside a slash remark ("A-ONE TRAVELS") is part
    # of the name and must not be split.
    sep = "-" if re.match(r"^(NEFT|RTGS|IMPS|UPI)-", s, re.I) and "/" not in s[:12] else "/"
    return [t.strip() for t in s.split(sep)]


def reference(remarks: str) -> str | None:
    """The UTR / RRN in the remark, when there is one."""
    for t in _tokens(remarks):
        up = t.upper()
        if _REF_RE.match(up) and not _IFSC_RE.match(up):
            return up
    return None


def counterparty(remarks: str, own_name: str | None = None) -> str | None:
    """The payer's or payee's name out of a remark, or None.

    Skips type codes, UTRs, IFSCs, dates and the account holder's own name (an outgoing
    IMPS names the sender first: "MMT/IMPS/…/ACMETRAVELS/AKASH…"). The first token left
    with three or more letters is the name.
    """
    if not remarks:
        return None
    own = _norm(own_name or "")
    for t in _tokens(remarks):
        up = t.upper().strip()
        if not up or up in _CODES:
            continue
        if _IFSC_RE.match(up) or _REF_RE.match(up.replace(" ", "")):
            continue
        if re.match(r"^[\d./:\s-]+$", up):
            continue                                     # a date or a bare number
        letters = re.sub(r"[^A-Z]", "", up)
        if len(letters) < 3:
            continue
        if own and len(_norm(up)) >= 4 and (own.startswith(_norm(up)) or _norm(up).startswith(own)):
            continue
        return re.sub(r"\s+", " ", t).strip()
    return None


_CREDIT_CARD_RE = re.compile(
    r"CREDIT\s*CARD|BANK\s*CRED|AUTO\s*DEBIT\s*CC|\bCC\s*\d|\bCC\d|CARD\s*PAYMENT|\bCRED\b", re.I,
)
_CHARGES_RE = re.compile(r"CHRG|CHARGES|\bFEE\b|GST\s*ON|SMS\s*ALERT|\bAMC\b|MIN\s*BAL", re.I)


def guess_category(remarks: str, direction: str) -> str:
    """A starting point the user can change. Deposits start as receipts."""
    r = remarks or ""
    if direction == "in":
        return "receipt"
    if _CREDIT_CARD_RE.search(r):
        return "credit_card"
    if _CHARGES_RE.search(r):
        return "bank_charges"
    if r.upper().startswith("BIL/"):
        return "vendor_payment"
    return "other"


# ── Matching a name to a party ───────────────────────────────────────────────

# Words that say what KIND of company it is, not which one. Dropped on both sides, so
# "ORIX CORP" meets "Orix Corporation India Pvt Ltd".
_NOISE = {
    "PVT", "PRIVATE", "LTD", "LIMITED", "LLP", "INC", "CO", "COMPANY", "CORP", "CORPORATION",
    "INDIA", "THE", "AND", "M/S", "MS", "MR", "MRS", "DR", "OPC",
}


def _words(name: str) -> list[str]:
    ws = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split()
    return [w for w in ws if w not in _NOISE]


def name_score(bank_name: str, party_name: str) -> float:
    """0..1 — how well a (possibly truncated) bank name matches a master name.

    Word by word, in order, and the bank's LAST word may be a prefix: the bank cuts the
    remark at a fixed width, so "HILFEN PHARMACE" must still meet "Hilfen Pharmaceuticals".
    A single short word is not trusted on its own — "M" or "AIR" would match half the
    master.
    """
    a, b = _words(bank_name), _words(party_name)
    # A last word that is the START of a noise word was cut mid-"Private" / mid-"Limited"
    # ("AIR IQ PRI"): it is noise too, just truncated, and must not count as a name word.
    if len(a) > 1 and any(n.startswith(a[-1]) and n != a[-1] for n in _NOISE):
        a = a[:-1]
    if not a or not b:
        return 0.0
    if "".join(a) == "".join(b):
        return 1.0

    matched = 0
    for i, w in enumerate(a):
        if i >= len(b):
            break
        last = i == len(a) - 1
        if w == b[i] or (last and len(w) >= 3 and b[i].startswith(w)):
            matched += 1
        else:
            break
    if matched == len(a):
        if len("".join(a)) < 4:
            return 0.0
        # Every bank word found. Full marks when it also covers every master word;
        # less when the master name is longer than what the bank kept.
        return 0.95 if matched == len(b) else 0.85

    # Out of order or partial: shared words, prefix-tolerant.
    hits = sum(1 for w in a if any(x == w or (len(w) >= 4 and x.startswith(w)) for x in b))
    return round(0.7 * hits / max(len(a), len(b)), 3)


@dataclass
class Candidate:
    party_type: str          # corporate | customer | agency
    party_id: int
    name: str


def suggest(bank_name: str | None, candidates: list[Candidate], threshold: float = 0.6) -> tuple[Candidate, float] | None:
    """The best candidate over the threshold, or None. A tie is no suggestion at all:
    two parties matching equally well is exactly when a human has to look."""
    if not bank_name:
        return None
    scored = sorted(
        ((name_score(bank_name, c.name), c) for c in candidates),
        key=lambda x: x[0], reverse=True,
    )
    if not scored or scored[0][0] < threshold:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1], scored[0][0]


# ── The whole file ───────────────────────────────────────────────────────────

@dataclass
class ParsedRow:
    line_no: int | None
    tran_id: str | None
    value_date: date | None
    txn_date: date | None
    posted_at: datetime | None
    cheque_ref: str | None
    remarks: str
    withdrawal: Decimal
    deposit: Decimal
    balance: Decimal | None
    direction: str                 # in | out
    counterparty: str | None
    payment_mode: str | None
    reference: str | None
    category: str


@dataclass
class ParsedStatement:
    account_name: str | None = None
    account_no: str | None = None
    ifsc: str | None = None
    bank_name: str | None = None
    branch: str | None = None
    currency: str | None = None
    period_from: date | None = None
    period_to: date | None = None
    rows: list[ParsedRow] = field(default_factory=list)
    ignored_lines: int = 0


class StatementError(Exception):
    """The file is not a statement this reader understands. Shown to the user."""


def _map_columns(cells: list[str]) -> dict[str, int]:
    names = [_norm(c) for c in cells]
    claimed: dict[str, int] = {}
    taken: set[int] = set()
    for fld, patterns in _COLUMNS:
        hit = None
        for p in patterns:                                    # exact first
            hit = next((i for i, n in enumerate(names) if n == p and i not in taken), None)
            if hit is not None:
                break
        if hit is None:
            for p in patterns:                                # then contains, long patterns only
                if len(p) < 4:
                    continue
                hit = next((i for i, n in enumerate(names) if n and p in n and i not in taken), None)
                if hit is not None:
                    break
        if hit is not None:
            claimed[fld] = hit
            taken.add(hit)
    return claimed


def _find_header(grid, max_scan: int = 60) -> tuple[int, dict[str, int]]:
    for i in range(min(max_scan, len(grid))):
        cols = _map_columns([spreadsheet.cell(v) for v in grid.iloc[i].tolist()])
        has_amount = "withdrawal" in cols or "deposit" in cols
        has_date = "txn_date" in cols or "value_date" in cols
        if "remarks" in cols and has_amount and has_date:
            return i, cols
    raise StatementError(
        "Could not find the transactions table. It needs a remarks / narration column, a "
        "withdrawal or deposit column, and a date column — upload the bank's own Excel "
        "export without editing its headings."
    )


def _read_meta(grid, header_row: int, out: ParsedStatement) -> None:
    for i in range(header_row):
        cells = [spreadsheet.cell(v) for v in grid.iloc[i].tolist()]
        for j, c in enumerate(cells):
            key = _META_LABELS.get(_norm(c.rstrip(":")))
            if not key:
                continue
            if key != "period" and getattr(out, key):
                continue                                      # the first one wins
            value = next((v for v in cells[j + 1:] if v), "")
            if not value:
                continue
            if key == "period":
                m = re.search(r"(\S+)\s+to\s+(\S+)", value, re.I)
                if m:
                    out.period_from, out.period_to = parse_date(m.group(1)), parse_date(m.group(2))
            else:
                setattr(out, key, value)
    if out.ifsc:
        out.ifsc = out.ifsc.strip().upper()
        out.bank_name = _BANKS.get(out.ifsc[:4])
    if out.account_no:
        out.account_no = re.sub(r"\s+", "", out.account_no)


def parse_statement(content: bytes, filename: str = "") -> ParsedStatement:
    try:
        grid, _sheets, _sheet, _kind = spreadsheet.read_grid(content, filename)
    except spreadsheet.SpreadsheetError as exc:
        raise StatementError(str(exc)) from exc
    if grid.empty:
        raise StatementError("The file has no rows.")

    header_row, cols = _find_header(grid)
    out = ParsedStatement()
    _read_meta(grid, header_row, out)

    def get(cells: list[str], fld: str) -> str:
        i = cols.get(fld)
        return cells[i] if i is not None and i < len(cells) else ""

    for r in range(header_row + 1, len(grid)):
        cells = [spreadsheet.cell(v) for v in grid.iloc[r].tolist()]
        if not any(cells):
            continue
        withdrawal = parse_amount(get(cells, "withdrawal"))
        deposit = parse_amount(get(cells, "deposit"))
        posted = parse_datetime(get(cells, "posted_at"))
        txn = parse_date(get(cells, "txn_date")) or (posted.date() if posted else None)
        value = parse_date(get(cells, "value_date"))
        # A transaction has a date and exactly one side. The legend, totals and "end of
        # statement" lines under the table have neither, and are counted, not stored.
        if not (txn or value) or (withdrawal <= 0 and deposit <= 0) or (withdrawal > 0 and deposit > 0):
            out.ignored_lines += 1
            continue
        remarks = get(cells, "remarks")
        direction = "in" if deposit > 0 else "out"
        line_raw = get(cells, "line_no")
        balance_raw = get(cells, "balance")
        out.rows.append(ParsedRow(
            line_no=int(float(line_raw)) if re.match(r"^\d+(\.0+)?$", line_raw) else None,
            tran_id=get(cells, "tran_id") or None,
            value_date=value,
            txn_date=txn or value,
            posted_at=posted,
            cheque_ref=get(cells, "cheque_ref") or None,
            remarks=remarks,
            withdrawal=withdrawal,
            deposit=deposit,
            balance=parse_amount(balance_raw) if balance_raw else None,
            direction=direction,
            counterparty=counterparty(remarks, out.account_name),
            payment_mode=_mode(remarks),
            reference=reference(remarks),
            category=guess_category(remarks, direction),
        ))

    if not out.rows:
        raise StatementError("The transactions table is empty — no line has a date and an amount.")
    if not out.period_from:
        dates = [x.txn_date for x in out.rows if x.txn_date]
        out.period_from, out.period_to = min(dates), max(dates)
    return out


def dedupe_key(account_no: str | None, row: ParsedRow) -> str:
    """What makes a line the same line when a statement is uploaded twice, or two
    overlapping periods are. The bank's transaction id alone repeats across days."""
    return "|".join([
        account_no or "",
        row.tran_id or "",
        row.txn_date.isoformat() if row.txn_date else "",
        row.posted_at.isoformat() if row.posted_at else "",
        str(row.deposit), str(row.withdrawal),
    ])[:250]
