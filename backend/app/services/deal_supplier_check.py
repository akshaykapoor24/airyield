"""Is this deal file really from the supplier picked on the upload form?

An incoming B2B upload is signed with one supplier (an Agency Master row), and every
deal in the file is saved under it. Attaching Lords' deal sheet while Akbar is picked
files Lords' commissions as Akbar's, and nothing downstream would notice — the rows
look perfectly valid. So before extraction the file is read for who it is from.

TWO KINDS OF EVIDENCE, IN ORDER OF TRUST
  1. A "Supplier Code" column (the tabbed template carries one, filled with the
     agency code from Agency Master). Exact: a code either is the picked agency's or
     it is not.
  2. Names in the file — its file name, a PDF's title, and the text itself. A deal
     sheet names its supplier ("LORDS ISSUANCE", "Akbar Travels deal circular") far
     more often than not.

NAME MATCHING HAS ONE BIG TRAP: AIRLINES. A deal sheet is mostly airline names, and
plenty of suppliers share a word with an airline ("Royal Travels" / Royal Jordanian,
"Air India Limited" is in the supplier master). So every airline name from the Airline
master is blanked out of the text BEFORE suppliers are looked for, and a supplier
whose whole name is an airline's is never a candidate.

THE VERDICT
  match     the picked supplier is named (or its code is in the file)
  mismatch  the picked supplier is NOT named, and another supplier clearly IS — named
            in the file name or title, or several times in the text
  unknown   neither — a file that names nobody. Not an error: it is let through, with
            a note, because many sheets simply do not say.
A mismatch is never declared on weak evidence: a single passing mention of another
name, with no trace of the picked one, is "unknown", not "mismatch".
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

# Words that describe the trade or the legal form rather than name the company. Mirrors
# GENERIC_NAME_WORDS in the Add Agency form's near-match search.
GENERIC = {
    "travel", "travels", "travelling", "tour", "tours", "tourism", "trip", "trips",
    "holiday", "holidays", "vacation", "vacations", "air", "airways", "aviation", "airline",
    "airlines", "world", "global", "international", "india", "indian", "services", "service",
    "solutions", "enterprises", "agency", "agencies", "company", "consultants", "consultancy",
    "pvt", "private", "ltd", "limited", "llp", "inc", "corp", "corporation", "and", "the",
    "for", "of", "co", "group", "online", "net", "express", "network", "ventures", "deal",
    "deals", "booking", "bookings", "ticket", "tickets", "ticketing", "branch", "office",
    # The vocabulary of a deal sheet itself. "Global Business Services" must not be
    # found in every sheet that has a Business column.
    "business", "economy", "premium", "first", "class", "classes", "cabin", "fare", "fares",
    "base", "basic", "sector", "sectors", "flight", "flights", "commission", "incentive",
    "validity", "valid", "remarks", "sale", "sales", "issuance", "domestic", "route", "routes",
    "special", "offline", "online", "consolidator", "updated", "effective", "sheet",
    "prem", "bizz", "pey", "eco", "nil", "open", "till", "notice", "further",
}
MIN_TOKEN = 4


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def distinctive(name: str) -> list[str]:
    """The words that identify a company: 'Lords Travel Pvt. Ltd.' -> ['lords']."""
    return [w for w in _words(name) if len(w) >= MIN_TOKEN and w not in GENERIC and not w.isdigit()]


def _compact(s: str) -> str:
    return "".join(_words(s))


@dataclass
class Candidate:
    label: str                       # what the message calls it
    name: str
    agency_ids: list[int] = field(default_factory=list)   # the user's own rows, if any
    code: str | None = None          # agency code, when it is one of the user's


@dataclass
class Evidence:
    """Where a candidate turned up. `strong` = file name or title; `hits` = text mentions."""
    strong: bool = False
    hits: int = 0
    whole: int = 0       # text mentions of the full multi-word name ("vickytourism")

    @property
    def score(self) -> int:
        return (3 if self.strong else 0) + min(self.hits, 5)


@dataclass
class FileText:
    head: str                         # file name + document title — the strongest place
    body: str                         # everything else
    supplier_codes: list[str] = field(default_factory=list)


# ── reading the file ─────────────────────────────────────────────────────────

def read_file_text(content: bytes, filename: str) -> FileText:
    """Pull the readable text out of an uploaded deal file. Never raises: an
    unreadable file just yields less evidence."""
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    head = re.sub(r"\.[a-z0-9]+$", "", filename, flags=re.I)
    body_parts: list[str] = []
    codes: list[str] = []
    try:
        if ext == "pdf":
            import fitz  # PyMuPDF — already used by deal_extraction
            doc = fitz.open(stream=content, filetype="pdf")
            title = (doc.metadata or {}).get("title") or ""
            head += " " + re.sub(r"\.[a-z0-9]+$", "", title, flags=re.I)
            for page in doc:
                body_parts.append(page.get_text() or "")
        elif ext in ("xlsx", "xlsm", "xls", "csv"):
            body_parts, codes = _sheet_text(content, filename)
        elif ext in ("docx", "doc"):
            import docx
            d = docx.Document(io.BytesIO(content))
            body_parts.extend(p.text for p in d.paragraphs)
            for t in d.tables:
                for r in t.rows:
                    body_parts.append(" ".join(c.text for c in r.cells))
    except Exception:
        pass
    return FileText(head=head, body="\n".join(body_parts), supplier_codes=codes)


def _norm_header(h) -> str:
    return re.sub(r"[^a-z]", "", str(h or "").lower())


def _sheet_text(content: bytes, filename: str) -> tuple[list[str], list[str]]:
    """Every cell of every sheet as text, plus the values of any Supplier Code column."""
    import pandas as pd
    from app.services import spreadsheet

    parts: list[str] = []
    codes: list[str] = []
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=str)
    except Exception:
        try:
            sheets = {"Sheet1": spreadsheet.read_df(content, filename, None)}
        except Exception:
            return parts, codes
    for name, df in sheets.items():
        parts.append(str(name))
        df = df.fillna("")
        rows = df.values.tolist()
        code_col = None
        for r in rows:
            cells = [str(c).strip() for c in r]
            if code_col is None:
                for i, c in enumerate(cells):
                    if _norm_header(c) in ("suppliercode", "agencycode", "vendorcode", "corporatecode"):
                        code_col = i
                        break
                else:
                    parts.append(" ".join(cells))
                continue
            if code_col < len(cells) and cells[code_col]:
                codes.append(cells[code_col].upper())
            parts.append(" ".join(cells))
    return parts, codes


# ── finding suppliers in it ──────────────────────────────────────────────────

def strip_airlines(text: str, airline_names: list[str]) -> str:
    """Blank every airline name out of the text, longest first so 'Air India Express'
    goes before 'Air India'."""
    out = text.lower()
    for n in sorted({a.strip().lower() for a in airline_names if a and len(a.strip()) >= 3}, key=len, reverse=True):
        out = re.sub(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", " ", out)
    return out


class Indexed:
    """A text prepared once for thousands of lookups: word counts + the compacted string."""

    def __init__(self, text: str):
        from collections import Counter
        self.words = Counter(_words(text))
        self.compact = _compact(text)

    def count(self, toks: list[str], core: str) -> int:
        n = 0
        if toks:
            per = [self.words.get(t, 0) for t in toks]
            n = min(per) if all(per) else 0
        return max(n, self.whole(core))

    def whole(self, core: str) -> int:
        """Mentions of the full name with its spaces squeezed out."""
        return self.compact.count(core) if len(core) >= 6 else 0


_LEGAL = {"pvt", "private", "ltd", "limited", "llp", "inc", "the", "india"}


def find(candidate: Candidate, head: "Indexed", body: "Indexed") -> Evidence:
    """How strongly a candidate is named. A name counts when ALL its distinctive words
    appear (as whole words); the compacted full name ('makemytrip') counts too, which
    catches names written without spaces and names whose words are all generic."""
    toks = distinctive(candidate.name)
    core_words = [w for w in _words(candidate.name) if w not in _LEGAL]
    core = _compact(" ".join(core_words))
    return Evidence(
        strong=head.count(toks, core) > 0,
        hits=body.count(toks, core),
        # Only a name of two or more words: "lords" alone is not a "whole name".
        whole=body.whole(core) if len(core_words) >= 2 else 0,
    )


@dataclass
class Verdict:
    status: str                        # match | mismatch | unknown
    message: str
    found: str | None = None           # the other supplier the file names
    found_agency_ids: list[int] = field(default_factory=list)
    basis: str = "name"                # name | code


def check(
    text: FileText,
    selected: Candidate,
    others: list[Candidate],
    airline_names: list[str],
    code_owners: list[Candidate] | None = None,
) -> Verdict:
    """`code_owners`: extra rows consulted ONLY to name a Supplier Code's owner — the
    picked vendor's other branches/channels, which are not "another supplier" for the
    name check but do hold codes of their own."""
    picked = selected.label

    # 1. The Supplier Code column, when the sheet has one — exact, and it wins.
    codes = sorted({c for c in text.supplier_codes if c})
    if codes:
        mine = (selected.code or "").upper()
        wrong = [c for c in codes if c != mine]
        if not wrong:
            return Verdict("match", f"Supplier Code {mine} matches {picked}.", basis="code")
        owner = next((o for o in [*(code_owners or []), *others]
                      if o.code and o.code.upper() == wrong[0]), None)
        who = owner.label if owner else None
        return Verdict(
            "mismatch",
            (f"This sheet's Supplier Code is {wrong[0]}"
             + (f" — that is {who}" if who else ", which is not one of your agencies")
             + f", but you selected {picked}"
             + (f" ({mine})" if mine else "") + "."),
            found=who or wrong[0],
            found_agency_ids=owner.agency_ids if owner else [],
            basis="code",
        )

    # 2. Names. The file name / title outranks the text: a deal sheet called "LORDS
    #    Deal Sheet" is Lords' even if the word "make" happens to occur in a remark.
    head = Indexed(strip_airlines(text.head, airline_names))
    body = Indexed(strip_airlines(text.body, airline_names))
    mine = find(selected, head, body)
    if mine.strong:
        return Verdict("match", f"{picked} is named in this file.")

    airline_cores = {_compact(a) for a in airline_names if a}
    # Ranked by: the user's own agency over a supplier-master row (so Akbar's sheet
    # names "Akbar Travels of India", the agency they onboarded, not "Akbar Online
    # Booking Co." from the master), then by strength of evidence, then by how much
    # of the name matched (a longer distinctive name is the more specific hit).
    def rank(ev: Evidence, o: Candidate) -> tuple:
        return (bool(o.agency_ids), ev.score, len(distinctive(o.name)))

    best_head: tuple[tuple, Candidate] | None = None
    best_body: tuple[tuple, Candidate] | None = None
    for o in others:
        if not distinctive(o.name) and _compact(o.name) in airline_cores:
            continue
        ev = find(o, head, body)
        if ev.strong and (best_head is None or rank(ev, o) > best_head[0]):
            best_head = (rank(ev, o), o)
            continue
        # The text alone is weaker ground. A supplier-master row whose name boils
        # down to ONE word ("Prem Travels", "Royal Tours", "Star Air Services") is
        # found in some deal sheet by sheer vocabulary, so from the master only a
        # name of two or more distinctive words counts in the text. The user's own
        # agencies are a short, known list and keep the single-word match ("Lords").
        # The exception is the full name written out: "Vicky Tourism Limited" in
        # Vicky's footer is the whole name, which no deal-sheet vocabulary produces.
        if not o.agency_ids and len(distinctive(o.name)) < 2 and not ev.whole:
            continue
        if ev.hits >= 2 and (best_body is None or rank(ev, o) > best_body[0]):
            best_body = (rank(ev, o), o)

    def mismatch(o: Candidate) -> Verdict:
        return Verdict(
            "mismatch",
            f"This file looks like {o.label}'s deal, but you selected {picked}.",
            found=o.label, found_agency_ids=o.agency_ids,
        )

    if best_head:
        return mismatch(best_head[1])
    if mine.hits > 0:
        return Verdict("match", f"{picked} is named in this file.")
    if best_body:
        return mismatch(best_body[1])
    return Verdict(
        "unknown",
        f"{picked} isn't named anywhere in this file, so it could not be confirmed as theirs. "
        "Check it is the right sheet before saving.",
    )


def supplier_cell_matches(cell: str | None, supplier_name: str) -> bool:
    """Does a sheet's Source / Supplier cell name this supplier?

    Vendor-comparison sheets abbreviate: "AKBAR" for Akbar Travels of India Private
    Limited, "YATRA(YFB)" for Yatra. A cell matches when its distinctive words all
    occur in the supplier's name, or the supplier's distinctive words all occur in
    the cell. Generic-only cells ("TRAVELS") match nothing.
    """
    cell_words = set(_words(cell or ""))
    if not cell_words:
        return False
    name_words = set(_words(supplier_name))
    cell_key = set(distinctive(cell or "")) or {w for w in cell_words if len(w) >= 3 and w not in GENERIC}
    name_key = set(distinctive(supplier_name))
    if cell_key and cell_key <= name_words:
        return True
    return bool(name_key) and name_key <= cell_words
