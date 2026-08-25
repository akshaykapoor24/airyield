"""AI extraction of supplier deal sheets (PDF).

The whole document is extracted. Rows are enumerated deterministically by
:mod:`app.services.pdf_table_rows`; the model's only job is to copy what each
cell says into a compact fixed-slot shape, and Python expands that back into the
full deal objects the review table expects.

That split is deliberate. The model used to emit the entire nested PLB object —
~257 output tokens per deal, so a 4-page sheet needed ~87,000 tokens against
gpt-4o's hard 16,384 ceiling. It could not physically return a full sheet, and
when it hit the ceiling the truncated JSON was salvaged and reported as a
high-confidence success. Now the model emits ~165 tokens per *source row*
covering all three classes at once, Python writes every constant field, and the
document is split into chunks that each fit comfortably inside the ceiling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re

from fastapi import UploadFile

from app.services.pdf_table_rows import (
    Chunk,
    DocLayout,
    DocRow,
    build_layout,
    chunk_rows,
    render_chunk,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are a data-extraction component in an airline Deals Management System.

You are given ONE EXCERPT of a supplier deal sheet that has already been parsed
into table rows by software. Your only job is to COPY what each cell says into a
fixed JSON shape. You never normalize, never convert dates, never infer values
that are not printed on the row.

## Input format

Rows arrive one per line, already split into labelled fields:

  [ 97][DOM] AL=«AIR INDIA (INTL)» CD=«AI» ECO=«2.00% (B+YQ)» PEY=«2.75%» BUS=«3.75%»
             VALIDON=«B+YQ» VALIDITY=«OB/IB till 31 Mar 2026» RMK=«NO PLB ON CODE SHARE»

- Every value is wrapped in «». A field shown as «» is empty. A field that is
  absent from a line does not exist in this document at all.
- The labels are authoritative — they were assigned from the document's own
  header by software. Use them exactly as given; never re-derive which value
  belongs to which column, and never shift a value from one label to another.
    AL=airline   CD=airline code   IATA=IATA-commission column
    ECO=Economy  PEY=Premium       BUS=Business/First
    CABIN=cabin-type column        COMM=the single commission column
    VALIDON=calculation-basis column   VALIDITY=travel-validity column
    RMK=remarks    Cn=an unlabelled extra column
- The number in the first bracket is the row's id. You MUST return it unchanged
  as "n". Never renumber, never offset, never invent an id.
- The tag in the second bracket is the row's section, computed from the document
  structure. It is AUTHORITATIVE.
    [DOM]  -> a Domestic section header governs this row. Set ft="DOM".
    [INTL] -> an International section header governs this row. Set ft="INTL".
    [--]   -> no section header governs this row. Infer ft from THIS ROW's own
              validity/remarks text; if nothing indicates otherwise use "BOTH".
  Never infer a row's section from a neighbouring row or from the excerpt as a
  whole.
- Rows under "# CONTEXT ONLY - DO NOT EXTRACT" are shown so that back-references
  like "-do-" or "same as above" can be resolved. Do NOT return an object for them.
- Return EXACTLY ONE object for EVERY row under "# EXTRACT EVERY ROW BELOW",
  in the order given, including rows you believe are not deals. Never skip a row.
  Never stop early. There is no maximum.

## Output

Return ONLY a JSON object: {"rows": [ ... ]}. One object per source row:

  "n"      the row id, copied exactly
  "al"     the airline cell, copied VERBATIM including any parenthetical
           qualifier. "AIR INDIA (INTL)" and "AIR INDIA (SAARC/ME)" are
           DIFFERENT airlines. Never shorten, never merge, never title-case.
  "cd"     the airline code cell, or null
  "iata"   the IATA-commission column as a plain number (5 for "5%"), or null.
           This is the agent's standard IATA commission and is NOT the PLB %.
  "vt"     the VALIDITY= cell copied VERBATIM (e.g. "OB/IB till 31 Mar 2026",
           "Open", "31 Dec'2026"), or null. Do not reformat it.
           If the row has NO VALIDITY= field, many sheets state the validity
           inside RMK= instead ("Travel Till 31 DEC 2026", "Ticketing & Travel
           Till 31Dec26"). Copy that phrase into "vt". Only use null when the
           row genuinely states no validity anywhere.
  "vt_iso" your best reading of "vt" as "YYYY-MM-DD", or null if it has no date
           ("Open", "Till Further Notice"). When a cell gives two dates, use the
           LATER one.
  "ft"     "DOM" | "INTL" | "BOTH" | null  (see the section tag rule above).
           For a [--] row, look at THIS row's own text: a remark opening
           "INTERNATIONAL:" or naming only overseas sectors means "INTL"; one
           opening "DOMESTIC:" means "DOM". A mere mention of a country or a
           carve-out like "not applicable on Domestic USA" is NOT a scope —
           that stays "BOTH".
  "rmk"    the REMARKS cell copied verbatim, truncated to 150 characters.
           Never paraphrase, never exceed 150 characters.
  "cl"     an object with EXACTLY three keys: "ECO", "PEY", "BUS".
           Each is either null or {"p": <number>, "cc": <calc code|null>}.

             "p"  the commission percent as a plain number: "2.00%" -> 2.0
             "cc" the calculation basis printed for that cell, copied as one of
                  "B", "B+YQ", "B+YR", "B+YQ+YR", or null if not printed.
                  A dedicated VALID ON / Applicable-on column, when present,
                  OVERRIDES any code printed inside the commission cell.

## Filling "cl"

- ECO= fills the "ECO" slot, PEY= fills "PEY", BUS= fills "BUS". One label, one
  slot. If a row has a rate under ECO=, the "ECO" slot MUST NOT be null.
- If the row has CABIN= and COMM= instead of ECO/PEY/BUS, put COMM='s rate in
  the slot CABIN= names ("Eco"->ECO, "Prem Eco"/"Premium"->PEY,
  "Bizz/First"/"Business"->BUS) and leave the other two null. A CABIN= of "All"
  fills all three slots with the same value.
- A BARE NUMBER IS A PERCENTAGE. Many sheets omit the sign entirely: «5.50»
  means p=5.5, «6» means p=6, «1.25» means p=1.25. Never null a slot just
  because the % sign is missing.
- A composite or annotated rate still yields a number: «3+5%», «3+5.00» and
  «3% IATA» all mean p=3 (the FIRST number). Copy the cell's full text into
  "rmk" so the reviewer can see what it originally said.
- "-", "NIL", "N/A", "NET", "SC 50", "SC 118", empty, or text with no number in
  it at all -> that slot is null. Never emit 0 for a NIL or a dash.
- A printed zero IS a real rate. «0.00%», «0.0%» and «0%» mean p=0, not null.
  Some sheets list a suspended deal that way and the row must still come back.
- If one cell holds SEVERAL rates - e.g. «1.25%-STD-(B+YQ), 1.5%(B+YQ)-FLEX+» or
  «4% on Base Fare (E,H,K,Q), 5% on (C,D,Z)» - use the FIRST percentage in the
  cell and put the rest in "rmk". Never leave the slot null just because the
  cell is complicated.
- If a cell's own text names classes explicitly - e.g. «1.25% (P Eco) 1.75% (Bus)»
  - fill one slot per class named IN THE CELL and ignore that field's default
  slot for that cell.
- A row with no extractable percentage anywhere: return the object with
  "cl" = {"ECO":null,"PEY":null,"BUS":null}. Do not omit the row.

## Not deals

Phone numbers, email addresses, postal addresses, GDS/PCC codes, payment terms,
ADM clauses, disclaimers, page headers and footers are NOT deals. If such a row
appears, still return an object for its id with all three "cl" slots null.

## Rules

- Copy, do not interpret. If a value is not printed on the row, use null.
- Never guess a percentage, a date, or an airline name.
- Return ONLY the JSON object. No markdown fences, no commentary.
"""


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT CONTRACT
# ══════════════════════════════════════════════════════════════════════════════

# The `strict` subset is unforgiving: every property must appear in `required`,
# `additionalProperties` must be false everywhere, nullability is expressed as a
# type union, and `minimum`/`maximum`/`maxItems` are simply unsupported — range
# checks live in Python.
_CELL_SCHEMA = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "required": ["p", "cc"],
    "properties": {
        "p": {"type": ["number", "null"]},
        "cc": {"type": ["string", "null"], "enum": ["B", "B+YQ", "B+YR", "B+YQ+YR", None]},
    },
}

_ROW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["n", "al", "cd", "iata", "vt", "vt_iso", "ft", "rmk", "cl"],
    "properties": {
        "n": {"type": "integer"},
        "al": {"type": "string"},
        "cd": {"type": ["string", "null"]},
        "iata": {"type": ["number", "null"]},
        "vt": {"type": ["string", "null"]},
        "vt_iso": {"type": ["string", "null"]},
        "ft": {"type": ["string", "null"], "enum": ["BOTH", "INTL", "DOM", None]},
        "rmk": {"type": ["string", "null"]},
        # Three fixed slots rather than an array. `maxItems` is not in the strict
        # subset, so an array is grammatically unbounded and a degenerate
        # repetition loop could burn the whole token budget without ever closing
        # an object. Fixed keys make that impossible by grammar, cost fewer
        # tokens than repeating a class label, and make null the explicit
        # NIL/dash sentinel.
        "cl": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ECO", "PEY", "BUS"],
            "properties": {"ECO": _CELL_SCHEMA, "PEY": _CELL_SCHEMA, "BUS": _CELL_SCHEMA},
        },
    },
}

EXTRACT_SCHEMA = {
    "name": "deal_rows",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["rows"],
        "properties": {"rows": {"type": "array", "items": _ROW_SCHEMA}},
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# NORMALISATION — Python owns every translation the model used to guess at
# ══════════════════════════════════════════════════════════════════════════════

# NOTE the missing space before YR. That is the canonical spelling the deal form
# offers (frontend/src/components/deals/IncentiveInclExclShared.tsx); emit
# anything else and the review <select> renders with no matching option.
CALC = {
    "B": "Basic", "BF": "Basic", "BASE FARE": "Basic", "BASIC": "Basic",
    "B+YQ": "Basic + YQ", "BF+YQ": "Basic + YQ", "BASE FARE + YQ": "Basic + YQ",
    "B+YR": "Basic + YR", "BF+YR": "Basic + YR", "BASE FARE + YR": "Basic + YR",
    "B+YQ+YR": "Basic + YQ +YR", "BF+YQ+YR": "Basic + YQ +YR",
    "BASE FARE + YQ + YR": "Basic + YQ +YR",
}
SLOT_CLASS = {"ECO": "Economy", "PEY": "Premium", "BUS": "Business"}
FT = {"BOTH": "Both", "INTL": "International", "DOM": "Domestic"}
SECTION_FT = {"Domestic": "Domestic", "International": "International"}

LCC_NAMES = {
    "INDIGO", "AKASA", "AKASA AIR", "SPICEJET", "SPICE JET", "SPICEJT INTL",
    "AIR INDIA EXPRESS", "STAR AIR", "ALLIANCE AIR", "AIR IQ", "AIR ASIA",
    "AIR ASIA INTL", "SCOOT", "NOK AIR", "THAI LION AIR", "BATIK AIR",
}

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DAY_MONTH_YEAR_RE = re.compile(
    r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*[-/. ]?\s*"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*'?\s*(\d{2,4})",
    re.I,
)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b")
_MONTH_END = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
              7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _norm_year(raw: str) -> int:
    year = int(raw)
    return year if year >= 1000 else 2000 + year


def _clamp_day(day: int, month: int, year: int) -> int:
    last = _MONTH_END[month]
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        last = 29
    return min(max(day, 1), last)


def parse_validity_iso(text: str | None) -> str | None:
    """Pull the LATEST date out of a validity cell.

    Cells routinely carry two ("OB 1Apr 26 / IB till 31 Mar 2027"); the contract
    ends on the later one. "Open" / "Till Further Notice" have no date at all and
    correctly yield None.
    """
    if not text:
        return None
    found: list[tuple[int, int, int]] = []

    for day, mon, year in _DAY_MONTH_YEAR_RE.findall(text):
        m = _MONTHS[mon[:3].lower()]
        y = _norm_year(year)
        found.append((y, m, _clamp_day(int(day), m, y)))

    for a, b, year in _NUMERIC_DATE_RE.findall(text):
        day, month = int(a), int(b)
        if not 1 <= month <= 12:
            continue
        y = _norm_year(year)
        found.append((y, month, _clamp_day(day, month, y)))

    if not found:
        return None
    y, m, d = max(found)
    return f"{y:04d}-{m:02d}-{d:02d}"


_DOM_RE = re.compile(r"\bdomestic\b", re.I)
_INTL_RE = re.compile(r"\b(international|intl)\b", re.I)

# Anchored at the very start and followed by a separator, because sheets are
# full of scope CARVE-OUTS that a loose keyword search reads backwards:
# "PLB is not applicable on … Domestic USA" would otherwise mark an
# international deal Domestic. Only a leading "INTERNATIONAL:" style label is a
# statement of scope.
_SCOPE_PREFIX_RE = re.compile(r"^\s*(?P<kw>international|intl|domestic)\b\s*[:\-–]", re.I)


def ft_from_validity(text: str | None) -> str | None:
    """Only fires when the validity cell itself names a scope; most do not."""
    if not text:
        return None
    if _DOM_RE.search(text) and not _INTL_RE.search(text):
        return "Domestic"
    if _INTL_RE.search(text) and not _DOM_RE.search(text):
        return "International"
    return None


def ft_from_remark_prefix(text: str | None) -> str | None:
    if not text:
        return None
    m = _SCOPE_PREFIX_RE.match(text)
    if not m:
        return None
    return "Domestic" if m.group("kw").lower() == "domestic" else "International"


# Several sheets carry the scope in the airline name itself — "AIR INDIA(DOM)",
# "AIR INDIA (INTL)", "INDIGO ( INTL )", "SPICEJT INTL". Word-bounded so it
# cannot fire on an ordinary name.
_NAME_SCOPE_RE = re.compile(r"\b(?P<kw>dom|domestic|intl|international)\b", re.I)


def ft_from_airline_name(name: str | None) -> str | None:
    if not name:
        return None
    m = _NAME_SCOPE_RE.search(name)
    if not m:
        return None
    return "Domestic" if m.group("kw").lower().startswith("dom") else "International"


# Take the FIRST numeric token rather than stripping non-digits: a cell like
# "3+5.00" (Lords' Uganda row) would otherwise collapse to a plausible-looking
# but entirely invented 35%.
_FIRST_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def canon_pct(value) -> float | None:
    """Accepts 2.25, "2.25", "2.25%", " 2.25 % " -> 2.25. Anything unparseable
    yields None; the caller decides what that means."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _FIRST_NUM_RE.search(str(value))
    return float(match.group()) if match else None


# Keys with whitespace squeezed out, so "Base Fare + YQ", "BASE FARE+YQ" and
# "B+YQ" all land on the same entry.
_CALC_LOOKUP = {re.sub(r"\s+", "", k): v for k, v in CALC.items()}


def norm_calc(code: str | None) -> str:
    return _CALC_LOOKUP.get(re.sub(r"\s+", "", (code or "").upper()), "Basic")


def _canon_airline(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(.*?\)", "", name or "")).strip().upper()


def _row_code(row: DocRow, cm) -> str | None:
    """The airline code as printed in this row's code column.

    Prefers the physical cell over the model's echo of it: Python already holds
    the cell (post forward-fill — byte-for-byte what `render_row` sent), so
    trusting a transcription round-trip buys nothing. Falls back to the model's
    "cd" only when the document has no code column at all.

    Transport only. The code is never written to `deals`; it exists so the master
    can be resolved, and created, from the row.
    """
    from app.services.airline_resolver import clean_airline_code

    if cm is None or cm.code is None or cm.code >= len(row.cells):
        return None
    return clean_airline_code(row.cells[cm.code])[0]


# ══════════════════════════════════════════════════════════════════════════════
# EXPANSION — one compact row becomes up to three deal objects
# ══════════════════════════════════════════════════════════════════════════════

class Stats:
    def __init__(self) -> None:
        self.ft_overrides = 0
        self.date_disputes = 0
        self.dropped_no_name = 0
        self.dropped_bad_pct = 0
        self.misnumbered = 0
        self.needs_manual = 0
        self.unresolved = 0
        self.failed_chunks = 0
        self.total_chunks = 0

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _has_validity_cell(row: DocRow, cm) -> bool:
    if cm is None or cm.validity is None or cm.validity >= len(row.cells):
        return False
    return bool((row.cells[cm.validity] or "").strip())


def expand_row(compact: dict, row: DocRow, stats: Stats, cm=None) -> list[dict]:
    """Turn one compact model row into the nested deal objects the UI expects.

    Every constant field is written here rather than asked of the model, which is
    both cheaper and strictly more reliable — the old prompt had to repeat
    "ALWAYS set targetBased=Amount Based" and still got it wrong sometimes.
    """
    name = (compact.get("al") or "").strip()
    if not name:
        stats.dropped_no_name += 1
        return []

    remark_cell = ""
    if cm is not None and cm.remarks is not None and cm.remarks < len(row.cells):
        remark_cell = row.cells[cm.remarks] or ""

    # flightType priority: the section Python computed from document structure
    # wins over anything the model inferred. On sheets whose only scope signal is
    # a section banner, the model has nothing else to go on.
    if row.section:
        flight_type = SECTION_FT[row.section]
        if compact.get("ft") and FT.get(compact["ft"]) != flight_type:
            stats.ft_overrides += 1
    else:
        flight_type = (ft_from_airline_name(name)
                       or ft_from_remark_prefix(remark_cell)
                       or ft_from_validity(compact.get("vt"))
                       or FT.get(compact.get("ft") or "")
                       or "Both")

    py_iso = parse_validity_iso(compact.get("vt"))
    model_iso = compact.get("vt_iso") or None
    if model_iso and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(model_iso)):
        model_iso = None
    if py_iso and model_iso and py_iso != model_iso:
        stats.date_disputes += 1
    valid_to = py_iso or model_iso
    # Last resort, and only when the sheet has no validity column at all (or left
    # it blank): those sheets state validity mid-remark instead. Scoped tightly
    # on purpose — a row whose Travel Validity says "Open" means open, and must
    # not pick up an unrelated "booking till 31st March" from its remark.
    if valid_to is None and not _has_validity_cell(row, cm):
        valid_to = parse_validity_iso(remark_cell)

    airline_type = "LCC" if _canon_airline(name) in LCC_NAMES else "GDS"

    # Deliberately AFTER every consumer of the raw name. `ft_from_airline_name`
    # above needs to see "(INTL)" and `_canon_airline` needs the sheet's own
    # spelling for LCC_NAMES — this module never renames anything, it only
    # carries the code out so the API layer can resolve the master with it.
    from app.services.airline_resolver import clean_airline_code
    airline_code = _row_code(row, cm) or clean_airline_code(compact.get("cd"))[0]

    remark = (compact.get("rmk") or "").strip()[:150] or None
    iata = canon_pct(compact.get("iata"))
    if iata is not None and not 0 < iata <= 100:
        iata = None

    out: list[dict] = []
    for slot in ("ECO", "PEY", "BUS"):
        cell = (compact.get("cl") or {}).get(slot)
        if not isinstance(cell, dict):
            continue
        pct = canon_pct(cell.get("p"))
        # 0 is kept: several sheets print a literal "0.00%" for a suspended deal,
        # and dropping those loses real rows. A NIL or a dash arrives as null
        # instead (the prompt forbids emitting 0 for one), and a stray 118 — a
        # flat service charge, not a rate — is out of range.
        if pct is None or not 0 <= pct <= 100:
            if cell.get("p") is not None:
                stats.dropped_bad_pct += 1
            continue
        calc = norm_calc(cell.get("cc"))
        out.append({
            "airline_type": airline_type,
            "airline_name": name,          # still the RAW cell — the API layer renames
            "airline_code": airline_code,  # transport only, never persisted on the deal
            "iata_commission": iata,
            "contract_valid_from": None,
            "contract_valid_to": valid_to,
            "incentive_types": ["PLB"],
            "incentive_data": {"PLB": {
                "validFrom": None,
                "validTo": valid_to,
                "frequency": "Yearly",
                "flightType": flight_type,
                "class": SLOT_CLASS[slot],
                "targetCalcCols": calc,
                "payoutCalcCols": calc,
                "targetBased": "Amount Based",
                "amountBasedType": "Fixed",
                "baseTargetAmount": None,
                "segmentBasedType": None,
                "baseTargetSegments": None,
                "incentiveNumPct": "Percentage",
                "incentiveAmtPct": pct,
                "cappedIncentive": None,
            }},
            "remark": remark,
            "src_n": row.n,
            "src_page": row.page + 1,
            "src_text": row.raw[:120],
            "needs_manual": False,
        })
    return out


def _manual_placeholder(row: DocRow, cm) -> dict:
    """A row we could not read still occupies a review row, so the user can fill
    it in by hand. A source row must never vanish silently — that is the whole
    complaint this change exists to fix."""
    name = ""
    cm_airline = cm.airline if cm is not None else None
    if cm_airline is not None and cm_airline < len(row.cells):
        # Cells keep their internal newlines; a name going straight to the UI
        # must not.
        name = re.sub(r"\s+", " ", row.cells[cm_airline] or "").strip()
    return {
        "airline_type": "GDS",
        "airline_name": name,
        "airline_code": _row_code(row, cm),
        "iata_commission": None,
        "contract_valid_from": None,
        "contract_valid_to": None,
        "incentive_types": ["PLB"],
        "incentive_data": {"PLB": {}},
        "remark": None,
        "src_n": row.n,
        "src_page": row.page + 1,
        "src_text": row.raw[:120],
        "needs_manual": True,
    }


# ══════════════════════════════════════════════════════════════════════════════
# JSON SALVAGE
# ══════════════════════════════════════════════════════════════════════════════

def _repair_truncated_json(content: str, key: str = "rows") -> list[dict]:
    """Extract all complete objects from potentially truncated JSON."""
    match = re.search(r'"' + re.escape(key) + r'"\s*:\s*\[', content)
    if match:
        array_content = content[match.end():]
    else:
        bare = re.search(r"\[", content)
        if not bare:
            return []
        array_content = content[bare.end():]

    # Walk through characters to find the boundary of each complete object
    depth = 0
    in_string = False
    escape_next = False
    last_complete_end = -1

    for i, ch in enumerate(array_content):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_complete_end = i

    if last_complete_end == -1:
        return []

    try:
        return json.loads("[" + array_content[: last_complete_end + 1] + "]")
    except json.JSONDecodeError:
        return []


def _salvage_or_parse(raw: str) -> list[dict]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _repair_truncated_json(raw)
    if isinstance(parsed, list):
        return parsed
    rows = parsed.get("rows")
    if isinstance(rows, list):
        return rows
    return []


def _row_shape_ok(obj) -> bool:
    """Salvaged and json_object-mode objects bypass `strict`, so they have to be
    checked before they reach the expander."""
    return (isinstance(obj, dict)
            and isinstance(obj.get("n"), int)
            and isinstance(obj.get("al", ""), str))


# ══════════════════════════════════════════════════════════════════════════════
# MODEL CALLS
# ══════════════════════════════════════════════════════════════════════════════

class _FatalExtractionError(Exception):
    """Auth/permission problems — retrying every chunk reaches the same answer
    three minutes later, so fail the whole request at once."""


def _max_tokens_for(row_count: int) -> int:
    from app.config import settings
    return min(16000, 400 + settings.AI_EXTRACT_OUT_TOK_PER_ROW * max(row_count, 1))


def _build_client():
    import httpx
    from openai import AsyncOpenAI
    from app.config import settings

    # The old client had neither a timeout nor a retry override, so one hung TCP
    # connection could wedge a worker indefinitely. max_retries=0 because the
    # ladder below is ours; the SDK's silent retries would corrupt attempt
    # accounting and re-spend tokens invisibly.
    return AsyncOpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=httpx.Timeout(settings.OPENAI_TIMEOUT_SECONDS, connect=10.0),
        max_retries=0,
    )


async def _one_call(client, user_content: str, row_count: int, strict: bool = True) -> str:
    from openai import (
        APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError,
        InternalServerError, PermissionDeniedError, RateLimitError,
    )
    from app.config import settings

    if strict:
        response_format = {"type": "json_schema", "json_schema": EXTRACT_SCHEMA}
    else:
        response_format = {"type": "json_object"}

    max_tokens = _max_tokens_for(row_count)
    attempt = 0
    while True:
        try:
            # Deliberately chat.completions.create() and not .parse(): .parse()
            # raises LengthFinishReasonError on a truncated response, which would
            # make the salvage path below unreachable.
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format=response_format,
                temperature=0,
                seed=settings.AI_EXTRACT_SEED,
                max_tokens=max_tokens,
            )
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise _FatalExtractionError(str(exc)) from exc
        except (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError) as exc:
            attempt += 1
            if attempt >= settings.AI_EXTRACT_MAX_ATTEMPTS:
                logger.warning("chunk call giving up after %s attempts: %s", attempt, exc)
                raise
            delay = min(2 ** attempt * 2, 60) * random.uniform(0.5, 1.0)
            retry_after = getattr(getattr(exc, "response", None), "headers", {}) or {}
            try:
                delay = max(delay, float(retry_after.get("retry-after", 0)))
            except (TypeError, ValueError):
                pass
            logger.info("retrying chunk in %.1fs (attempt %s): %s", delay, attempt, exc)
            await asyncio.sleep(delay)
            continue
        except BadRequestError:
            if strict:
                logger.warning("strict schema rejected; retrying chunk in json_object mode")
                return await _one_call(client, user_content, row_count, strict=False)
            raise

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        logger.info(
            "ai-extract chunk rows=%s finish=%s completion_tokens=%s max_tokens=%s fingerprint=%s",
            row_count, choice.finish_reason, completion_tokens, max_tokens,
            getattr(response, "system_fingerprint", None),
        )
        if completion_tokens and completion_tokens > 0.8 * max_tokens:
            logger.warning(
                "chunk used %s of %s output tokens — AI_EXTRACT_OUT_TOK_PER_ROW may be "
                "mis-calibrated for this layout", completion_tokens, max_tokens,
            )
        return choice.message.content or "{}"


async def _extract_rows(client, header, cm, rows: list[DocRow], stats: Stats,
                        depth: int = 0) -> list[dict]:
    """Ask for these rows, then chase whatever came back missing.

    A truncated or refused response is never retried as-is: at temperature 0 an
    identical request produces an identical reply, so only a change of INPUT can
    change the outcome. Zero progress therefore halves the row list instead of
    re-asking. Every recursive call gets a strictly smaller list and the base
    case is a single row, so this terminates structurally rather than on a
    counter.
    """
    from app.config import settings

    if not rows:
        return []

    chunk = Chunk(index=0, body=rows, context=[], n_lo=rows[0].n, n_hi=rows[-1].n)
    try:
        raw = await _one_call(client, render_chunk(chunk, header, cm), len(rows))
    except _FatalExtractionError:
        raise
    except Exception:
        logger.exception("chunk failed permanently (rows %s-%s)", rows[0].n, rows[-1].n)
        stats.failed_chunks += 1
        return [{"__row__": r} for r in rows]        # marked for the manual placeholder

    valid_ns = {r.n for r in rows}
    got = [o for o in _salvage_or_parse(raw) if _row_shape_ok(o)]

    # Objects outside the requested range are the context row being echoed back,
    # or a misnumbering. Either way they are not silently dropped — they are
    # counted so confidence reflects them.
    in_range = [o for o in got if o["n"] in valid_ns]
    stats.misnumbered += len(got) - len(in_range)

    seen: dict[int, dict] = {}
    for obj in in_range:
        seen.setdefault(obj["n"], obj)          # first wins on a stutter

    missing = [r for r in rows if r.n not in seen]
    result = list(seen.values())

    if not missing:
        return result

    if len(missing) == len(rows):
        if len(rows) == 1:
            return result + await _single_row_fallback(client, header, cm, rows[0], stats)
        mid = len(rows) // 2
        return (result
                + await _extract_rows(client, header, cm, rows[:mid], stats, depth + 1)
                + await _extract_rows(client, header, cm, rows[mid:], stats, depth + 1))

    if depth >= settings.AI_EXTRACT_MAX_SPLIT_DEPTH:
        logger.warning("split depth exhausted; %s rows unresolved", len(missing))
        return result + [{"__row__": r} for r in missing]

    return result + await _extract_rows(client, header, cm, missing, stats, depth + 1)


async def _single_row_fallback(client, header, cm, row: DocRow, stats: Stats) -> list[dict]:
    """One row cannot be split, so it needs different INPUT. The remarks cell is
    the only unbounded field and therefore the overwhelmingly likely trigger."""
    trimmed = row
    for idx, cell in enumerate(row.cells):
        if len(cell) > 150:
            trimmed = trimmed.with_cell(idx, cell[:150])

    if trimmed is not row:
        chunk = Chunk(index=0, body=[trimmed], context=[], n_lo=row.n, n_hi=row.n)
        try:
            raw = await _one_call(client, render_chunk(chunk, header, cm), 1)
            got = [o for o in _salvage_or_parse(raw) if _row_shape_ok(o) and o["n"] == row.n]
            if got:
                return got[:1]
        except _FatalExtractionError:
            raise
        except Exception:
            logger.exception("single-row fallback failed for n=%s", row.n)

    stats.needs_manual += 1
    return [{"__row__": row}]


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

async def _run_chunks(layout: DocLayout, stats: Stats) -> list[dict]:
    from app.config import settings

    chunks = chunk_rows(
        layout.rows,
        layout.colmap,
        rows_per_chunk=settings.AI_EXTRACT_ROWS_PER_CHUNK,
        max_chars=settings.AI_EXTRACT_CHUNK_MAX_CHARS,
    )
    stats.total_chunks = len(chunks)
    client = _build_client()
    semaphore = asyncio.Semaphore(settings.AI_EXTRACT_MAX_CONCURRENCY)

    async def run(chunk: Chunk) -> list[dict]:
        async with semaphore:
            # The full chunk (with its context row) goes out first; only the
            # retry path drops the context and re-splits.
            try:
                raw = await _one_call(
                    client, render_chunk(chunk, layout.header, layout.colmap), len(chunk.body))
            except _FatalExtractionError:
                raise
            except Exception:
                logger.exception("chunk %s failed; falling back to re-split", chunk.index)
                return await _extract_rows(
                    client, layout.header, layout.colmap, chunk.body, stats)

            valid_ns = {r.n for r in chunk.body}
            got = [o for o in _salvage_or_parse(raw) if _row_shape_ok(o)]
            in_range = [o for o in got if o["n"] in valid_ns]
            stats.misnumbered += len(got) - len(in_range)

            seen: dict[int, dict] = {}
            for obj in in_range:
                seen.setdefault(obj["n"], obj)

            missing = [r for r in chunk.body if r.n not in seen]
            if missing:
                logger.info("chunk %s missing %s rows; re-asking", chunk.index, len(missing))
                return list(seen.values()) + await _extract_rows(
                    client, layout.header, layout.colmap, missing, stats, depth=1)
            return list(seen.values())

    try:
        results = await asyncio.gather(*(run(c) for c in chunks))
    finally:
        await client.close()
    return [obj for batch in results for obj in batch]


def _build_warning(layout: DocLayout, stats: Stats, capped_from: int | None,
                   page_capped_from: int | None) -> str | None:
    parts: list[str] = []
    if page_capped_from:
        parts.append(
            f"This PDF has {page_capped_from} pages; only the first "
            f"{_settings().AI_EXTRACT_MAX_PDF_PAGES} were read."
        )
    if capped_from:
        parts.append(
            f"This sheet has {capped_from} rows; the first {len(layout.rows)} were extracted "
            f"(the per-upload limit). Split the file to import the rest."
        )
    if stats.failed_chunks:
        parts.append(f"{stats.failed_chunks} section(s) could not be read.")
    unread = stats.needs_manual + stats.unresolved
    if unread:
        parts.append(f"{unread} row(s) could not be read and need filling in by hand — "
                     "look for the blank rows in the table.")
    if stats.date_disputes:
        parts.append(f"{stats.date_disputes} validity date(s) were ambiguous — check Contract Valid To.")
    return " ".join(parts) or None


def _settings():
    from app.config import settings
    return settings


def _confidence(stats: Stats, deal_count: int) -> float:
    if not deal_count:
        return 0.2
    total_chunks = max(stats.total_chunks, 1)
    score = (1.0
             - 0.30 * (stats.failed_chunks / total_chunks)
             - 0.10 * (stats.date_disputes / deal_count)
             - 0.10 * (stats.needs_manual / deal_count)
             - 0.05 * (stats.misnumbered / deal_count))
    return round(max(0.2, min(0.99, score)), 2)


class AIDealExtractionService:
    @staticmethod
    async def extract(file: UploadFile) -> dict:
        content = await file.read()
        await file.seek(0)
        filename = file.filename or ""

        layout = build_layout(content)
        if not layout.ok:
            # Never fall through to raw text: a wrong-but-plausible layout is
            # worse than an honest refusal, and the column-mapping path exists
            # for exactly this case.
            return {
                "deals": [],
                "file_name": filename,
                "confidence": 0.0,
                "warning": None,
                "unreadable": True,
            }

        settings = _settings()
        page_capped_from = layout.page_count if layout.page_count > settings.AI_EXTRACT_MAX_PDF_PAGES else None
        capped_from = None
        if len(layout.rows) > settings.AI_EXTRACT_MAX_SOURCE_ROWS:
            capped_from = len(layout.rows)
            layout.rows = layout.rows[: settings.AI_EXTRACT_MAX_SOURCE_ROWS]

        stats = Stats()
        compact_rows = await _run_chunks(layout, stats)

        by_n = {r.n: r for r in layout.rows}
        deals: list[dict] = []
        for obj in compact_rows:
            unread: DocRow | None = obj.get("__row__") if isinstance(obj, dict) else None
            if unread is not None:
                deals.append(_manual_placeholder(unread, layout.colmap))
                continue
            row = by_n.get(obj.get("n"))
            if row is None:
                continue
            deals.extend(expand_row(obj, row, stats, layout.colmap))

        # Completeness backstop. Python independently decided these rows hold a
        # rate; if nothing came back for one, it is a miss, not a non-deal. Give
        # it a review row and say so, rather than letting it disappear the way
        # the old truncation did.
        covered = {d["src_n"] for d in deals}
        for row in layout.rows:
            if row.expects_deals and row.n not in covered:
                stats.unresolved += 1
                deals.append(_manual_placeholder(row, layout.colmap))

        # Document reading order — the reviewer checks these against the printed
        # sheet, and any other order makes that impossible.
        slot_rank = {"Economy": 0, "Premium": 1, "Business": 2}
        deals.sort(key=lambda d: (
            d.get("src_n") or 0,
            slot_rank.get((d.get("incentive_data", {}).get("PLB") or {}).get("class"), 9),
        ))

        warning = _build_warning(layout, stats, capped_from, page_capped_from)
        logger.info(
            "ai-extract done file=%s engine=%s rows=%s deals=%s stats=%s",
            filename, layout.used_table_engine, len(layout.rows), len(deals), stats.as_dict(),
        )

        # Invariant: a short result must never come back with warning=None. That
        # exact combination — 15 rows reported at 0.9 confidence with nothing
        # flagged — is the bug this rewrite exists to kill.
        if not deals and warning is None:
            warning = "No deals could be extracted from this PDF."

        return {
            "deals": deals,
            "file_name": filename,
            "confidence": _confidence(stats, len(deals)),
            "warning": warning,
            "unreadable": False,
        }
