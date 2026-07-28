"""
BSP PDF parser (streaming, pluggable)
─────────────────────────────────────
Parses a large BSP settlement PDF page-by-page with PyMuPDF so memory stays flat
regardless of page count. The Celery worker owns transaction / progress concerns;
this module owns *layout* concerns behind a stable seam:

    for outcome in iter_page_results(pdf_bytes):
        outcome.page_number, outcome.total_pages, outcome.result.transactions, .errors

Tuned parser: **FCAGBILLDETALT — IATA "Agent Billing Details ALT"** (the per-ticket
settlement register). Its columns sit at fixed x-positions on a landscape page, so
we cluster words into visual rows (y) and assign each token to a column by its x
range. Taxes/fees/penalties are stacked vertically in the TAX / F&C / PEN
sub-columns — component_type is decided purely by which x-column a code sits in.

Unknown layouts fall back to ``DEFAULT_PARSER`` (identity fields + raw dump), so the
pipeline still runs end-to-end on a format we haven't tuned yet.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterator, Optional

logger = logging.getLogger(__name__)


# ── Parsed value types (the seam contract) ──────────────────────────────────
@dataclass
class ParsedTaxComponent:
    component_type: str            # BASE_FARE | TAX | FEE | PENALTY | COMMISSION
    component_code: str            # YQ / YR / IN / K3 ...
    amount: Optional[Decimal] = None


@dataclass
class ParsedTransaction:
    transaction_type: Optional[str] = None          # TKTT / RFND / EMDS / EMDA / CANX / SPDR ...
    document_number: Optional[str] = None
    airline_accounting_code: Optional[str] = None
    airline_code: Optional[str] = None
    issue_date: Optional[str] = None                # ISO string; normalised downstream
    cpui: Optional[str] = None
    nr_code: Optional[str] = None
    stat: Optional[str] = None                       # I / D
    form_of_payment: Optional[str] = None            # CA / CC
    transaction_amount: Optional[Decimal] = None
    fare_amount: Optional[Decimal] = None
    penalty_amount: Optional[Decimal] = None
    net_sales: Optional[Decimal] = None
    standard_commission_rate: Optional[Decimal] = None
    standard_commission_amount: Optional[Decimal] = None
    supplier_discount_rate: Optional[Decimal] = None
    supplier_discount_amount: Optional[Decimal] = None
    tax_on_commission: Optional[Decimal] = None
    balance_payable: Optional[Decimal] = None
    tax_components: list[ParsedTaxComponent] = field(default_factory=list)
    # Detailed-PDF enrichment (cleaned continuation-line values).
    tour: list[str] = field(default_factory=list)                 # ["INGBAFF500", ...] — can be multiple
    alt_document_numbers: list[str] = field(default_factory=list)  # +TKTT conjunction doc numbers
    rtdn: Optional[str] = None                                     # +RTDN related/refund doc number
    esac: Optional[str] = None                                     # ESAC authority code
    wavr: Optional[str] = None                                     # WAVR waiver code
    # Full structured continuation-line detail (surfaced to the UI). Shape:
    #   {"rtdn": {"doc","ref","indicator"}, "conjunctions": [{"doc","issue_date","cpui"}]}
    associated_docs: dict = field(default_factory=dict)
    raw_data: dict = field(default_factory=dict)


@dataclass
class PageParseResult:
    transactions: list[ParsedTransaction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class PageOutcome:
    page_number: int          # 1-based
    total_pages: int
    result: PageParseResult


class ParserState:
    """Carries an open transaction across page boundaries (a transaction whose tax
    lines spill onto the next page), plus the current section/category tags."""
    def __init__(self) -> None:
        self.open_txn: Optional[ParsedTransaction] = None
        self.section: Optional[str] = None       # ISSUES | REFUNDS | DEBIT MEMOS
        self.category: Optional[str] = None       # BSP | WEBSALES-EDIS

    def flush(self) -> list[ParsedTransaction]:
        if self.open_txn is not None:
            txn, self.open_txn = self.open_txn, None
            return [txn]
        return []


# ── Money / number parsing (Decimal — never float for money) ────────────────
_NUM_RE = re.compile(r"^[+-]?[\d,]*\.?\d+$")


def to_decimal(value) -> Optional[Decimal]:
    """Parse a BSP money/rate token to Decimal. Handles thousands separators,
    parenthesised negatives ``(123.00)``, trailing CR/DR markers, and a trailing
    ``*`` (BSP's "amended transaction" marker, e.g. ``1,219*`` / ``5.00*`` /
    ``-927*`` — the asterisk flags the value as amended but the number is genuine).
    None for blanks / non-numerics."""
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith("*"):                    # amended-transaction marker → keep the number
        s = s.rstrip("*").strip()
    if not s or s.lower() in ("nan", "none", "-", "--"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    up = s.upper()
    if up.endswith("CR"):
        s = s[:-2].strip()
    elif up.endswith("DR"):
        neg, s = True, s[:-2].strip()
    if s.endswith("-"):
        neg, s = True, s[:-1].strip()
    s = s.replace(",", "").replace(" ", "")
    if not _NUM_RE.match(s):
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return -d if neg else d


def _money(value) -> Optional[Decimal]:
    d = to_decimal(value)
    return d.quantize(Decimal("0.01")) if d is not None else None


# ── Word / row clustering ───────────────────────────────────────────────────
# fitz "words" tuple: (x0, y0, x1, y1, word, block_no, line_no, word_no)
def _x0(w): return w[0]
def _x1(w): return w[2]
def _y0(w): return w[1]
def _txt(w): return str(w[4])


def cluster_rows(words: list, tol: float = 4.0) -> list[list]:
    """Cluster words into visual rows by y (tolerance ~4px merges a two-line main
    row but keeps the ~7px-spaced tax continuation lines separate). Each row's words
    are returned left-to-right; rows top-to-bottom."""
    ws = sorted((w for w in words if len(w) >= 5), key=lambda w: (w[1], w[0]))
    rows: list[list] = []
    cur: list = []
    anchor = None
    for w in ws:
        if anchor is None or (w[1] - anchor) <= tol:
            cur.append(w)
            anchor = cur[0][1] if anchor is None else anchor
        else:
            rows.append(sorted(cur, key=lambda t: t[0]))
            cur = [w]
            anchor = w[1]
    if cur:
        rows.append(sorted(cur, key=lambda t: t[0]))
    return rows


# ── FCAGBILLDETALT column map (x-ranges measured from the real statement) ────
# right-aligned amount columns → match by right edge x1: (lo, hi)
COL_TXN  = (282, 300)    # Transaction Amount
COL_FARE = (334, 353)    # FARE Amount
COL_TAXA = (366, 389)    # TAX amount
COL_FCA  = (418, 442)    # F&C amount
COL_PENA = (466, 508)    # PEN amount
COL_NET  = (538, 562)    # Net Sales
COL_STDA = (622, 640)    # STD Comm amount
COL_SUPA = (696, 712)    # SUPP Discount amount
COL_TOC  = (750, 782)    # Tax on Comm
COL_BAL  = (795, 822)    # Balance Payable
# left-aligned text / code / rate columns → match by left edge x0: (lo, hi)
COL_AIR  = (18, 40)      # airline accounting code (3 digits)
COL_TRNC = (40, 64)      # transaction code
COL_DOC  = (64, 112)     # document number
COL_DATE = (112, 148)    # issue date DDMMMYY
COL_CPUI = (148, 172)    # CPUI
COL_NR   = (172, 196)    # NR code
COL_STAT = (196, 214)    # STAT (I/D)
COL_FOP  = (214, 250)    # form of payment
COL_TAXC = (388, 415)    # TAX code
COL_FCC  = (442, 468)    # F&C code
COL_PENC = (494, 524)    # PEN code
COL_STDR = (565, 600)    # STD Comm rate
COL_SUPR = (640, 668)    # SUPP Discount rate

_TRNC_CODES = {
    "TKTT", "RFND", "EMDS", "EMDA", "EMDT", "ACMA", "ACMD", "ADMA", "ADMD",
    "CANX", "CANN", "SPDR", "SPCR", "RFDA", "VOID", "TASF", "EMD",
}

# Ticket-number derivation by transaction type. document_number is always the raw
# printed value; the *ticket* number depends on the transaction:
#   • EMD family + ACM/ADM memos carry NO ticket number (they are documents, not tickets).
#     ACM/ADM are the fallback parser's mapped forms of ACMA/ACMD / ADMA/ADMD.
#   • RFND/RFDA: a refund whose document number starts 00/40 is not a real ticket number.
#   • Everything else (TKTT, SPDR, SPCR, CANN, CANX, VOID, TASF, …) copies the document number.
# CANX gets its document_number rewritten to the parent SPDR doc in the worker's post-parse
# pass, but ONLY when that SPDR's charge is fully distributed (see _distribute_spdr_canx);
# the ticket number set here (the printed value) is always preserved.
_BLANK_TICKET_TYPES = {"EMDS", "EMDA", "EMDT", "EMD", "ACMA", "ACMD", "ADMA", "ADMD", "ACM", "ADM"}
_RFND_PREFIX_TYPES = {"RFND", "RFDA"}


def derive_ticket_number(transaction_type: Optional[str], document_number: Optional[str]) -> Optional[str]:
    """Ticket number for a BSP row, from its transaction type + printed document number."""
    if not document_number:
        return None
    tt = (transaction_type or "").upper()
    if tt in _BLANK_TICKET_TYPES:
        return None
    if tt in _RFND_PREFIX_TYPES:
        return None if document_number.startswith(("00", "40")) else document_number
    return document_number
_DATE_RE = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")
# tax/fee/pen codes: 2-5 chars, alphanumeric, at least one letter (YQ, K3, OBFCA…).
# The letter guard stops a stray amount token from being read as a code.
_CODE_RE = re.compile(r"^(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,5}$")
# Metadata continuation-line field labels. A single line can carry more than one,
# e.g. "TOUR: <code> ESAC: <code>", so each value must be routed to its own field.
_META_KEYS = ("TOUR", "ESAC", "WAVR", "RMIC")


def _split_meta_segments(texts: list) -> list:
    """Split a metadata line's tokens into ordered (KEY, value) pairs. Handles
    several fields on one line ("TOUR: H3C ESAC: 618XE2J9SYMM4") and colon-joined
    tokens ("ESAC:618XE…"). Value tokens accrue to the most recent key until the
    next key appears; tokens before any key are ignored."""
    out: list = []
    for tok in texts:
        parts = tok.split(":", 1)
        head = parts[0].upper()
        if head in _META_KEYS:
            tail = parts[1] if len(parts) == 2 else ""
            out.append([head, [tail] if tail else []])
        elif out:
            out[-1][1].append(tok)
    return [(k, " ".join(v).strip()) for k, v in out]


def _grab0(cells, lo, hi):
    for w in cells:
        if lo <= _x0(w) < hi:
            return w
    return None


def _grab1(cells, lo, hi):
    for w in cells:
        if lo <= _x1(w) < hi:
            return w
    return None


def _txt_or_none(w):
    return _txt(w) if w is not None else None


def _parse_issue_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip().upper(), "%d%b%y").date().isoformat()
    except ValueError:
        return s


def _is_txn_row(cells) -> bool:
    air = _grab0(cells, *COL_AIR)
    trnc = _grab0(cells, *COL_TRNC)
    doc = _grab0(cells, *COL_DOC)
    if not (air and trnc and doc):
        return False
    return (
        _txt(air).isdigit() and len(_txt(air)) in (2, 3)   # 2-digit codes are zero-padded in _new_txn
        and _txt(trnc).upper() in _TRNC_CODES
        and _txt(doc).isdigit() and len(_txt(doc)) >= 8
    )


def _absorb_components(cells, txn: ParsedTransaction) -> None:
    """Pull any TAX / F&C / PEN (amount, code) pair on this visual row into the
    transaction. component_type is decided by which x-column the code sits in."""
    for amt_col, code_col, ctype in (
        (COL_TAXA, COL_TAXC, "TAX"),
        (COL_FCA,  COL_FCC,  "FEE"),
        (COL_PENA, COL_PENC, "PENALTY"),
    ):
        amt_w = _grab1(cells, *amt_col)
        code_w = _grab0(cells, *code_col)
        if amt_w is None or code_w is None:
            continue
        code = _txt(code_w).upper()
        if not _CODE_RE.match(code):
            continue
        amt = _money(_txt(amt_w))
        txn.tax_components.append(ParsedTaxComponent(ctype, code, amt))
        if ctype == "PENALTY" and amt is not None:
            txn.penalty_amount = (txn.penalty_amount or Decimal("0")) + amt


def _new_txn(cells, state: ParserState) -> ParsedTransaction:
    nr_raw = _txt_or_none(_grab0(cells, *COL_NR))
    stat_raw = _txt_or_none(_grab0(cells, *COL_STAT))
    air_raw = _txt_or_none(_grab0(cells, *COL_AIR))
    t = ParsedTransaction(
        airline_accounting_code=(air_raw.zfill(3) if air_raw and air_raw.isdigit() else air_raw),
        transaction_type=(_txt_or_none(_grab0(cells, *COL_TRNC)) or "").upper() or None,
        document_number=_txt_or_none(_grab0(cells, *COL_DOC)),
        issue_date=_parse_issue_date(_txt_or_none(_grab0(cells, *COL_DATE))),
        cpui=_txt_or_none(_grab0(cells, *COL_CPUI)),
        nr_code=(nr_raw.replace("NR:", "").strip() if nr_raw else None),
        stat=(stat_raw.replace("*", "").strip() if stat_raw else None),
        form_of_payment=_txt_or_none(_grab0(cells, *COL_FOP)),
        transaction_amount=_money(_txt_or_none(_grab1(cells, *COL_TXN))),
        fare_amount=_money(_txt_or_none(_grab1(cells, *COL_FARE))),
        net_sales=_money(_txt_or_none(_grab1(cells, *COL_NET))),
        standard_commission_rate=to_decimal(_txt_or_none(_grab0(cells, *COL_STDR))),
        standard_commission_amount=_money(_txt_or_none(_grab1(cells, *COL_STDA))),
        supplier_discount_rate=to_decimal(_txt_or_none(_grab0(cells, *COL_SUPR))),
        supplier_discount_amount=_money(_txt_or_none(_grab1(cells, *COL_SUPA))),
        tax_on_commission=_money(_txt_or_none(_grab1(cells, *COL_TOC))),
        balance_payable=_money(_txt_or_none(_grab1(cells, *COL_BAL))),
    )
    t.airline_code = t.airline_accounting_code
    if stat_raw and "*" in stat_raw:
        t.raw_data["stat_amended"] = True
    if state.section:
        t.raw_data["section"] = state.section
    if state.category:
        t.raw_data["category"] = state.category
    return t


def _close(state: ParserState, result: PageParseResult) -> None:
    if state.open_txn is not None:
        result.transactions.append(state.open_txn)
        state.open_txn = None


def parse_billdetalt_page(words: list, state: ParserState) -> PageParseResult:
    result = PageParseResult()
    for cells in cluster_rows(words):
        texts = [_txt(w) for w in cells]
        upper = {t.upper() for t in texts}
        first = texts[0] if texts else ""

        # Section / total / category banners → close any open txn, update tags.
        if "***" in texts or "TOTAL" in upper or "TOTALS" in upper \
                or {"CATEGORY", "SCOPE", "SUMMARY"} & upper:
            _close(state, result)
            if "***" in texts:
                name = " ".join(t for t in texts if t != "***").upper().strip()
                if name:
                    state.section = name
            if "CATEGORY" in upper:
                # category value sits at the far right of the banner row
                val = next((t for t in reversed(texts) if t.upper() != "CATEGORY"), None)
                if val:
                    state.category = val.upper()
            continue

        # Conjunction (+TKTT...) / related document (+RTDN:) sub-lines. These carry
        # more than a doc number, so capture the full structure into associated_docs.
        if first.startswith("+"):
            if state.open_txn is not None:
                doc = _txt_or_none(_grab0(cells, *COL_DOC))
                if first.upper().startswith("+RTDN"):
                    # ANY +RTDN line is an exchange (with or without the "EX" marker); a
                    # single document can carry several, so accumulate a list. The scalar
                    # `rtdn` + associated_docs["rtdn"] retain the FIRST for back-compat.
                    if doc:
                        # ref sits in the CPUI column (e.g. 1230); "EX" (exchange) marker
                        # appears further right — match it by value, not x-position.
                        ref = _txt_or_none(_grab0(cells, *COL_CPUI))
                        exch = {"doc": doc}
                        if ref:
                            exch["ref"] = ref
                        if any(_txt(w).upper() == "EX" for w in cells):
                            exch["indicator"] = "EX"
                        state.open_txn.associated_docs.setdefault("exchanges", []).append(exch)
                        if state.open_txn.rtdn is None:   # first exchange seeds back-compat scalars
                            state.open_txn.rtdn = doc
                            state.open_txn.raw_data["rtdn"] = doc
                            state.open_txn.associated_docs["rtdn"] = exch
                elif doc:  # +TKTT conjunction — an associated ticket with its own doc number
                    state.open_txn.alt_document_numbers.append(doc)
                    state.open_txn.raw_data.setdefault("conjunction", []).append(doc)
                    # The conjunction ticket carries its OWN issue date + CPUI
                    # (e.g. +TKTT 4846715097 01JUL26 FVVV) — retain both.
                    conj = {"doc": doc}
                    conj_date = _parse_issue_date(_txt_or_none(_grab0(cells, *COL_DATE)))
                    conj_cpui = _txt_or_none(_grab0(cells, *COL_CPUI))
                    if conj_date:
                        conj["issue_date"] = conj_date
                    if conj_cpui:
                        conj["cpui"] = conj_cpui
                    state.open_txn.associated_docs.setdefault("conjunctions", []).append(conj)
            continue

        # Metadata sub-lines. A single line can carry SEVERAL fields, e.g.
        # "TOUR: H3C ESAC: 618XE2J9SYMM4", so split out every TOUR/ESAC/WAVR/RMIC
        # segment and route each value to its own field (previously only the leading
        # field was read and the rest leaked into TOUR).
        if first.split(":", 1)[0].upper() in _META_KEYS:
            if state.open_txn is not None:
                for mkey, mval in _split_meta_segments(texts):
                    if not mval:
                        continue
                    if mkey == "TOUR":
                        state.open_txn.tour.append(mval)
                    elif mkey == "ESAC":
                        state.open_txn.esac = mval
                    elif mkey == "WAVR":
                        state.open_txn.wavr = mval
                    state.open_txn.raw_data[mkey.lower()] = mval   # keep back-compat (incl. rmic)
            continue

        # A real transaction main row.
        if _is_txn_row(cells):
            _close(state, result)
            state.open_txn = _new_txn(cells, state)
            _absorb_components(cells, state.open_txn)  # first tax/fee/pen on main line
            continue

        # Otherwise: a tax/fee/pen continuation line for the open transaction.
        if state.open_txn is not None:
            _absorb_components(cells, state.open_txn)
        # (page headers etc. absorb nothing and are harmlessly ignored)

    return result


def is_billdetalt(words: list) -> bool:
    for w in words[:60]:
        t = _txt(w).upper()
        if t == "FCAGBILLDETALT" or t == "FCAGBILLDETALT":
            return True
    joined = " ".join(_txt(w).upper() for w in words[:80])
    return "BILLING DETAILS" in joined or "FCAGBILLDETALT" in joined


# ── Fallback parser for un-tuned layouts (identity + raw dump) ──────────────
_TRNC_MAP = {
    "TKTT": "TKTT", "RFND": "RFND", "ADMA": "ADM", "ADMD": "ADM",
    "ACMA": "ACM", "ACMD": "ACM", "EMDA": "EMD", "EMDS": "EMD",
    "CANX": "CANX", "VOID": "VOID", "EXCH": "EXCH",
}
_TRNC_RE = re.compile(r"\b(" + "|".join(sorted(_TRNC_MAP, key=len, reverse=True)) + r")\b")
_DOCNO_RE = re.compile(r"\b(\d{9,14})\b")


def default_parser(words: list, state: ParserState) -> PageParseResult:
    result = PageParseResult()
    for cells in cluster_rows(words):
        text = " ".join(_txt(w) for w in cells)
        m_trnc = _TRNC_RE.search(text.upper())
        m_doc = _DOCNO_RE.search(text)
        if not (m_trnc and m_doc):
            continue
        try:
            result.transactions.append(ParsedTransaction(
                transaction_type=_TRNC_MAP.get(m_trnc.group(1), m_trnc.group(1)),
                document_number=m_doc.group(1),
                raw_data={"line": text},
            ))
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"line parse failed: {exc!r} :: {text[:120]}")
    return result


# ── Streaming entry point (the worker consumes this) ────────────────────────
def iter_page_results(pdf_bytes: bytes) -> Iterator[PageOutcome]:
    """Yield a PageOutcome per PDF page, in order, with constant memory. Per-page
    exceptions are captured as errors (never raised) so one bad page can't abort
    the job. Raises only if the PDF itself can't be opened."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        total = doc.page_count
        state = ParserState()
        detalt: Optional[bool] = None
        for pno in range(total):
            page = doc.load_page(pno)
            try:
                words = page.get_text("words")
                if detalt is None:
                    detalt = is_billdetalt(words)
                parser = parse_billdetalt_page if detalt else default_parser
                result = parser(words, state)
            except Exception as exc:  # noqa: BLE001
                logger.warning("BSP parse: page %d failed: %s", pno + 1, exc)
                result = PageParseResult(errors=[str(exc)])
            finally:
                page = None   # drop the C-level page reference before the next iter
            yield PageOutcome(page_number=pno + 1, total_pages=total, result=result)

        tail = state.flush()
        if tail:
            yield PageOutcome(page_number=total, total_pages=total,
                              result=PageParseResult(transactions=tail))
    finally:
        doc.close()


def has_text_layer(pdf_bytes: bytes, sample_pages: int = 3) -> bool:
    """True if the first few pages contain extractable text (i.e. not a scanned
    image PDF). Lets the worker fail fast with a clear message instead of silently
    completing a scanned statement with zero rows."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for pno in range(min(sample_pages, doc.page_count)):
            if doc.load_page(pno).get_text("text").strip():
                return True
        return False
    finally:
        doc.close()


# ══════════════════════════════════════════════════════════════════════════════
# Header extraction (page 1) — shared by summary + detailed
# ══════════════════════════════════════════════════════════════════════════════
# "14-3 0950 3" agent code, "Billing Period: 260701 ( 01-JUL-2026 to 07-JUL-2026 )"
_AGENT_CODE_RE = re.compile(r"(\d{2}-\d\s+\d{4}\s+\d)")
_PERIOD_RE = re.compile(
    r"Billing Period[:\s]*?(\d{6})\s*\(\s*(\d{2}-[A-Z]{3}-\d{4})\s*to\s*(\d{2}-[A-Z]{3}-\d{4})",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(r"REFERENCE[:\s]*([0-9]+)\s*-\s*([0-9]+)", re.IGNORECASE)


def _period_date(s: Optional[str]) -> Optional[str]:
    """"01-JUL-2026" -> ISO date string, else None."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip().upper(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def parse_statement_header(page1_text: str) -> dict:
    """Pull agent code, billing period from/to, reference and currency out of a BSP
    statement's page-1 text (works for both FCAGBILLSUMNG and FCAGBILLDETALT so the
    upload flow never has to ask the user for airline/period)."""
    out: dict = {}
    m = _PERIOD_RE.search(page1_text)
    if m:
        out["billing_period_code"] = m.group(1)
        out["period_from"] = _period_date(m.group(2))
        out["period_to"] = _period_date(m.group(3))
    m = _AGENT_CODE_RE.search(page1_text)
    if m:
        out["agent_code"] = m.group(1)
    m = _REFERENCE_RE.search(page1_text)
    if m:
        out["reference"] = f"{m.group(1)} - {m.group(2)}"
    if re.search(r"\bINR\b", page1_text):
        out["currency"] = "INR"
    # Agent name: first ALL-CAPS company line after the agent-code title line.
    lines = [ln.strip() for ln in page1_text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if _AGENT_CODE_RE.search(ln) and " - " in ln:  # e.g. "14-3 0950 3 - YATRA.COM"
            for cand in lines[i + 1 : i + 6]:
                up = cand.upper()
                if cand == up and "IATA" not in up and "REFERENCE" not in up and len(cand) > 3:
                    out["agent_name"] = cand
                    break
            break
    return out


# ══════════════════════════════════════════════════════════════════════════════
# FCAGBILLSUMNG — "Agent Billing Summary" parser
# ─────────────────────────────────────────────────────────────────────────────
# Small doc (a handful of pages): parsed whole, not streamed. Columns sit at fixed
# x-positions; we read the per-airline TOTAL line (or the single FOP line) and the
# AGENT/GRAND TOTAL line. Validated against a real statement: the per-airline
# balances sum to the grand total to the rupee.
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class ParsedSummaryLine:
    kind: str = "airline"                 # airline | grand_total
    category: Optional[str] = None        # BSP | WEBSALES-EDIS | WEBSALES-WEBL
    airline_code: Optional[str] = None    # 001
    airline_iata: Optional[str] = None    # AA
    airline_name: Optional[str] = None
    fop: Optional[str] = None             # TOTAL | CASH
    issues: Optional[Decimal] = None
    refunds: Optional[Decimal] = None
    debit_memos: Optional[Decimal] = None
    credit_memos: Optional[Decimal] = None
    std_comm: Optional[Decimal] = None
    sup_comm: Optional[Decimal] = None
    tax_on_comm: Optional[Decimal] = None
    balance_payable: Optional[Decimal] = None
    doc_count: Optional[int] = None


@dataclass
class ParsedSummary:
    agent_code: Optional[str] = None
    agent_name: Optional[str] = None
    reference: Optional[str] = None
    billing_period_code: Optional[str] = None
    period_from: Optional[str] = None
    period_to: Optional[str] = None
    currency: Optional[str] = None
    total_pages: int = 0
    grand_total: Optional[ParsedSummaryLine] = None
    lines: list[ParsedSummaryLine] = field(default_factory=list)   # per-airline
    errors: list[str] = field(default_factory=list)


# summary amount columns — match by right edge x1: (lo, hi)
_S_ISSUES  = (235, 262)
_S_REFUNDS = (350, 378)
_S_DEBITS  = (430, 458)
_S_CREDITS = (496, 520)
_S_STD     = (568, 595)
_S_SUP     = (628, 658)
_S_TOC     = (696, 718)
_S_BAL     = (722, 782)
_S_DOC     = (795, 822)
# identity columns — match by left edge x0
_S_CODE = (14, 33)      # 3-digit airline numeric code
_S_IATA = (33, 50)      # 2-char IATA code
_S_FOP  = (135, 168)    # CASH / CARD / TOTAL
# Known form-of-payment sub-line labels (kept tight so a stray FOP-column token is
# never mistaken for a payment line). TOTAL is handled separately, not here.
_FOP_LABEL_RE = re.compile(r"^(CASH|CARD|CHEQUE|CHQ|MISC|MSAN|MPO|EP|OTHER)$")


def _summary_amounts(cells) -> dict:
    return dict(
        issues=_money(_txt_or_none(_grab1(cells, *_S_ISSUES))),
        refunds=_money(_txt_or_none(_grab1(cells, *_S_REFUNDS))),
        debit_memos=_money(_txt_or_none(_grab1(cells, *_S_DEBITS))),
        credit_memos=_money(_txt_or_none(_grab1(cells, *_S_CREDITS))),
        std_comm=_money(_txt_or_none(_grab1(cells, *_S_STD))),
        sup_comm=_money(_txt_or_none(_grab1(cells, *_S_SUP))),
        tax_on_comm=_money(_txt_or_none(_grab1(cells, *_S_TOC))),
        balance_payable=_money(_txt_or_none(_grab1(cells, *_S_BAL))),
    )


def _summary_doc(cells) -> Optional[int]:
    w = _grab1(cells, *_S_DOC)
    if w is None:
        return None
    t = _txt(w).replace(",", "")
    return int(t) if t.isdigit() else None


def is_billsummary(words: list) -> bool:
    joined = " ".join(_txt(w).upper() for w in words[:80])
    return "FCAGBILLSUMNG" in joined or "AGENT BILLING SUMMARY" in joined


def parse_bsp_summary_pdf(pdf_bytes: bytes) -> ParsedSummary:
    """Parse an FCAGBILLSUMNG summary into header + grand total + per-airline lines.

    Robust against layout drift: the match figures come from the single, clearly
    labelled AGENT/GRAND TOTAL row; per-airline lines are enrichment. Subtotal/total
    banner rows end an airline block so a category subtotal is never mis-attributed
    to the last airline.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = ParsedSummary()
    try:
        out.total_pages = doc.page_count
        for k, v in parse_statement_header(doc.load_page(0).get_text("text")).items():
            setattr(out, k, v)

        category = "BSP"
        cur: Optional[dict] = None       # current airline identity
        lines: list[ParsedSummaryLine] = []   # ordered: each airline's FOP sub-lines then its TOTAL
        expect_grand = False

        for pno in range(doc.page_count):
            words = doc.load_page(pno).get_text("words")
            try:
                for cells in cluster_rows(words, tol=4.0):
                    texts = [_txt(w) for w in cells]
                    up = " ".join(texts).upper()
                    code_w = _grab0(cells, *_S_CODE)
                    fop_w = _grab0(cells, *_S_FOP)
                    code = _txt(code_w) if code_w else ""
                    fop = (_txt(fop_w).upper() if fop_w else "")

                    if "CATEGORY" in {t.upper() for t in texts}:
                        val = next((t for t in reversed(texts) if t.upper() != "CATEGORY"), None)
                        if val:
                            category = val.upper()
                        cur = None
                        continue

                    # subtotal / grand-total banner rows close the current airline block
                    is_banner = (
                        any(k in up for k in ("COMBINED", "TOTALS", "(INR)", "GRAND TOTAL"))
                        or ("AGENT" in up and "TOTAL" in up)
                    )
                    if is_banner:
                        cur = None
                        if ("AGENT" in up and "TOTAL" in up) or "GRAND TOTAL" in up:
                            expect_grand = True
                        continue

                    # Airline start: 3-digit numeric code + IATA + name. This same row is
                    # the airline's first FOP sub-line (usually CASH), so keep it as a line.
                    if code.isdigit() and len(code) == 3:
                        iata_w = _grab0(cells, *_S_IATA)
                        name = " ".join(_txt(w) for w in cells if 50 <= _x0(w) < 135).strip()
                        cur = {"code": code, "iata": (_txt(iata_w) if iata_w else None),
                               "name": name or None}
                        lines.append(ParsedSummaryLine(
                            category=category, airline_code=code, airline_iata=cur["iata"],
                            airline_name=cur["name"], fop=fop or "CASH",
                            doc_count=_summary_doc(cells), **_summary_amounts(cells)))
                        continue

                    if fop == "TOTAL":
                        amt = _summary_amounts(cells)
                        if expect_grand:
                            if amt["balance_payable"] is not None:
                                out.grand_total = ParsedSummaryLine(
                                    kind="grand_total", fop="TOTAL",
                                    doc_count=_summary_doc(cells), **amt)
                            expect_grand = False
                        elif cur is not None:
                            # Keep the airline's TOTAL line ALONGSIDE its FOP sub-lines
                            # (previously it overwrote them) so the UI can show the
                            # CASH / CARD / TOTAL breakdown.
                            lines.append(ParsedSummaryLine(
                                category=category, airline_code=cur["code"],
                                airline_iata=cur["iata"], airline_name=cur["name"],
                                fop="TOTAL", doc_count=_summary_doc(cells), **amt))
                        continue

                    # A further per-FOP sub-line (CARD, cheque, …) for the current airline:
                    # no 3-digit code of its own, but a form-of-payment label in the FOP col.
                    if cur is not None and fop and _FOP_LABEL_RE.match(fop):
                        lines.append(ParsedSummaryLine(
                            category=category, airline_code=cur["code"],
                            airline_iata=cur["iata"], airline_name=cur["name"],
                            fop=fop, doc_count=_summary_doc(cells), **_summary_amounts(cells)))
                        continue
            except Exception as exc:  # noqa: BLE001
                out.errors.append(f"summary page {pno + 1}: {exc!r}")

        out.lines = lines
        return out
    finally:
        doc.close()
