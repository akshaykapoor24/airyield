"""What the email TEXT carries (architecture/06 §6.6): tables, deals written as text, and facts.

Travel desks often paste the content instead of attaching it:
  * a consolidator's deal grid pasted into the mail as an HTML table;
  * "Dear partner, w.e.f. 01 Oct: 6E 3% on basic, AI intl 5% PLB, valid till 31 Oct";
  * a covering note — "PFA statement for 08-15th Aug, 245 tickets, net payable ₹12,34,567".

So the body is read for three things, all pure (no database, no network):
  tables()       HTML tables with at least 2 rows × 2 columns, as lists of cell texts. Each can
                 be turned into a real .xlsx (to_xlsx) and imported by the module's own wizard.
  deal_text()    the body's NEW content (quoted replies and signatures removed) when it reads
                 like a deal circular — deal vocabulary AND percentages.
  facts()        period, effective date and control totals, to pre-fill what the wizards ask.

Quoted history is cut before anything is read, so last week's quoted totals are never taken
for this week's.
"""
from __future__ import annotations

import io
import re
from datetime import date
from html.parser import HTMLParser

from app.services.mail import classify
# The statement period is read by the same code the upload wizard reads a file name with, so a
# period the wizard understands is one the inbox understands too.
from app.services.statement_period import MON as _MON, MONTHS as _MONTHS, find_period

# ── quoted history and signatures ───────────────────────────────────────────

_QUOTE_STARTS = [
    re.compile(r"^\s*On .{5,200}wrote:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*From:\s.+\n\s*(Sent|Date):\s", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*_{10,}\s*$", re.MULTILINE),
]
_FORWARD_START = re.compile(r"^\s*-{5,}\s*Forwarded message\s*-{5,}", re.IGNORECASE | re.MULTILINE)
_SIGNOFF = re.compile(r"^\s*(thanks|thank you|regards|warm regards|best regards|thanks\s*&\s*regards)\b.*$",
                      re.IGNORECASE | re.MULTILINE)


def new_content(text: str) -> str:
    """The part of a plain-text body written in THIS mail.

    A forward is different from a reply: in "Fwd: Vendor deal sheet" the useful content IS the
    forwarded part, so a forwarded block is kept; reply history ("On … wrote:", "-----Original
    Message-----", ">" lines) is dropped, and so is everything after the sign-off."""
    if not text:
        return ""
    if _FORWARD_START.search(text):
        return text
    cut = len(text)
    for pat in _QUOTE_STARTS:
        m = pat.search(text)
        if m:
            cut = min(cut, m.start())
    body = "\n".join(line for line in text[:cut].splitlines() if not line.lstrip().startswith(">"))
    sign = _SIGNOFF.search(body)
    if sign and sign.start() > 40:          # keep "Thanks for the deal…" opening lines
        body = body[:sign.start()]
    return body.strip()


# ── HTML tables ─────────────────────────────────────────────────────────────

class _Tables(HTMLParser):
    """Collects every <table> as rows of cell texts. Nested tables (layout tables wrapping a
    data table, common in Outlook mail) are kept separately; the outer layout table usually
    fails the shape test and is dropped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._stack: list[list[list[str]]] = []
        self._cell: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip += 1
        elif tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._stack[-1].append([])
        elif tag in ("td", "th") and self._stack:
            if not self._stack[-1]:
                self._stack[-1].append([])
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None and self._stack:
            self._stack[-1][-1].append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def tables(html: str | None) -> list[list[list[str]]]:
    """Data tables in the HTML body: ≥ 2 non-empty rows, ≥ 2 columns, padded to a rectangle."""
    if not html:
        return []
    parser = _Tables()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — malformed HTML: no tables rather than a failed message
        return []
    out = []
    for t in parser.tables:
        rows = [r for r in t if any(c.strip() for c in r)]
        if len(rows) < 2:
            continue
        width = max(len(r) for r in rows)
        if width < 2:
            continue
        out.append([r + [""] * (width - len(r)) for r in rows])
    return out


def to_csv(table: list[list[str]]) -> bytes:
    import csv
    buf = io.StringIO()
    csv.writer(buf).writerows(table)
    return buf.getvalue().encode("utf-8")


def to_xlsx(rows: list[list[str]], sheet: str = "Sheet1") -> bytes:
    """A real workbook for the module's own upload wizard. Numbers stay text: a 13-digit ticket
    number must not become 9.81E+12 on the way in."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = sheet[:31]
    for r in rows:
        ws.append([str(c) if c is not None else "" for c in r])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def classify_table(table: list[list[str]], *, sender_hint: str | None, context: str) -> classify.DocClass:
    return classify.classify(to_csv(table), "email-table.csv", "text/csv", sender_hint=sender_hint, context=context)


# ── deals written as text ───────────────────────────────────────────────────

# A rate line names a carrier: a 2-character IATA designator (6E, AI, UK, EK …) or a name.
_CARRIER_CODE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9]|[0-9][A-Z])(?![A-Za-z0-9])")
_CARRIER_NAME = re.compile(
    r"\b(indigo|air\s?india|vistara|spice\s?jet|akasa|alliance\s+air|star\s+air|fly\s?big|emirates|qatar|etihad|"
    r"lufthansa|singapore|british|klm|air\s+france|thai|malaysia|cathay|fly\s?dubai|air\s+arabia|gulf\s+air|"
    r"oman\s+air|saudia|turkish|virgin|united|american|delta|air\s+canada|qantas|srilankan|bangladesh|"
    r"biman|nepal|druk|jazeera|kuwait|swiss|austrian|finnair|air\s+asia|vietnam|garuda|korean|japan)\b",
    re.IGNORECASE)
_RATE = re.compile(r"\d+(?:\.\d+)?\s*%")


def deal_lines(text: str | None) -> list[str]:
    """Lines that pair a carrier with a rate — "6E 3% on basic", "Air India intl 5% PLB"."""
    out = []
    for line in (text or "").splitlines():
        if _RATE.search(line) and (_CARRIER_CODE.search(line) or _CARRIER_NAME.search(line)):
            out.append(line.strip())
    return out


def deal_text(text: str | None, *, min_lines: int = 1) -> str | None:
    """The new content when it reads like a deal circular — deal vocabulary AND at least
    `min_lines` lines pairing a carrier with a rate. "Kindly find attached the deal sheet" is a
    covering note, not a deal, and no longer counts."""
    body = new_content(text or "")
    if not body or not classify.looks_like_deal_text(body):
        return None
    return body if len(deal_lines(body)) >= min_lines else None


# ── facts ───────────────────────────────────────────────────────────────────

_EFFECTIVE = re.compile(
    rf"\b(?:effective|w\.?\s?e\.?\s?f\.?|with effect from|valid from|from)\s*:?\s*"
    rf"(?:(\d{{1,2}})(?:st|nd|rd|th)?\s*{_MON}\W{{0,2}}\s*'?(\d{{2,4}})|(\d{{1,2}})[./-](\d{{1,2}})[./-](\d{{2,4}}))",
    re.IGNORECASE)
# Month first, as US-style circulars write it: "Effective March 24th", "w.e.f. Oct 1, 2026".
_EFFECTIVE_MDY = re.compile(
    rf"\b(?:effective|w\.?\s?e\.?\s?f\.?|with effect from|valid from)\s*:?\s*{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*'?(\d{{4}}|\d{{2}}(?!\d))?",
    re.IGNORECASE)
_VALID_TILL = re.compile(
    rf"\b(?:valid\s+(?:till|until|upto|up to)|till|until|upto)\s*:?\s*"
    rf"(?:(\d{{1,2}})(?:st|nd|rd|th)?\s*{_MON}\W{{0,2}}\s*'?(\d{{2,4}})|(\d{{1,2}})[./-](\d{{1,2}})[./-](\d{{2,4}}))",
    re.IGNORECASE)
_COUNT = re.compile(r"\b(\d{1,6})\s*(?:tickets?|tkts?|records?|rows?|transactions?|entries)\b", re.IGNORECASE)
_AMOUNT = re.compile(
    r"\b(?:net\s+payable|total\s+payable|amount\s+payable|net\s+amount|total\s+amount|net\s+remit|net)\s*"
    r"(?:of|is|:)?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)\s*(lakh|lac|crore|cr)?", re.IGNORECASE)


def _year(y: str | None, fallback: int) -> int:
    if not y:
        return fallback
    n = int(y)
    return n + 2000 if n < 100 else n


def _mk(d: str, mon: str, y: str | None, fallback_year: int) -> date | None:
    try:
        return date(_year(y, fallback_year), _MONTHS[mon[:3].lower()], int(d))
    except (ValueError, KeyError):
        return None


def _numeric(d: str, m: str, y: str) -> date | None:
    try:
        return date(_year(y, 0), int(m), int(d))      # DD/MM/YYYY — the Indian convention
    except ValueError:
        return None


def facts(*texts: str | None, today: date | None = None) -> dict:
    """Period, effective / valid-till dates and control totals found in subject, body or file
    names. Every value is a SUGGESTION the reviewer sees and can change."""
    today = today or date.today()
    blob = " \n ".join(t for t in texts if t)
    out: dict = {}

    period = find_period(blob, today)
    if period:
        out["period_from"], out["period_to"] = period[0].isoformat(), period[1].isoformat()

    m = _EFFECTIVE.search(blob)
    if m:
        d, mon, y, nd, nm, ny = m.groups()
        when = _mk(d, mon, y, today.year) if d else _numeric(nd, nm, ny)
        if when:
            out["effective_from"] = when.isoformat()
    if "effective_from" not in out:
        m = _EFFECTIVE_MDY.search(blob)
        if m:
            mon, d, y = m.groups()
            when = _mk(d, mon, y, today.year)
            if when:
                out["effective_from"] = when.isoformat()
    m = _VALID_TILL.search(blob)
    if m:
        d, mon, y, nd, nm, ny = m.groups()
        when = _mk(d, mon, y, today.year) if d else _numeric(nd, nm, ny)
        if when:
            out["valid_to"] = when.isoformat()

    m = _COUNT.search(blob)
    if m:
        out["expected_count"] = int(m.group(1))
    m = _AMOUNT.search(blob)
    if m:
        try:
            value = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower()
            value *= 100_000 if unit in ("lakh", "lac") else 10_000_000 if unit in ("crore", "cr") else 1
            if value > 0:
                out["expected_amount"] = f"{value:.2f}"
        except ValueError:
            pass
    return out
