"""Deterministic table-row extraction for supplier deal-sheet PDFs.

The AI extractor used to feed the model `page.get_text("text")`, which shatters
one logical table row across up to ~15 physical lines — so any character- or
line-based chunker can bisect a deal, and the model has to re-derive row
boundaries itself. `find_tables()` keeps a row atomic instead: a cell's internal
newlines stay inside the cell.

    cells[0] = 'AIR INDIA (INTL)\\n(OB/IB till 31 Mar 2026)'
    cells[2] = '2.00%\\n(B+YQ)'

Everything here is pure — no API key, no DB, no network — so it can be pinned by
tests against the sample sheets. The model never sees a partial row, and layout
questions (which column is Economy, which section governs this row) are answered
by Python rather than guessed.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field, replace

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# TYPES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DocRow:
    """One physical table row, after cleanup."""
    n: int                          # global index — assigned once, never rebased per chunk
    page: int
    cells: tuple[str, ...]
    section: str | None             # "Domestic" | "International" | None — per ROW, not per chunk
    raw: str                        # tab-joined cells, for the prompt and the Source column
    expects_deals: bool             # Python's own verdict: this row should yield >=1 deal

    def with_cell(self, idx: int, value: str) -> "DocRow":
        cells = list(self.cells)
        cells[idx] = value
        return replace(self, cells=tuple(cells), raw="\t".join(c.replace("\n", " ") for c in cells))


@dataclass
class ColumnMap:
    """Which column index feeds which role, derived from the detected header."""
    format_hint: str = "unknown"    # "A" (class columns) | "B" (cabin column) | "unknown"
    airline: int | None = None
    code: int | None = None
    iata: int | None = None
    eco: int | None = None
    pey: int | None = None
    bus: int | None = None
    cabin: int | None = None
    commission: int | None = None
    valid_on: int | None = None
    validity: int | None = None
    remarks: int | None = None

    @property
    def rate_columns(self) -> tuple[int, ...]:
        """Columns that can legitimately hold a commission percentage."""
        if self.cabin is not None and self.commission is not None:
            return (self.commission,)
        return tuple(c for c in (self.eco, self.pey, self.bus) if c is not None)


@dataclass
class DocLayout:
    rows: list[DocRow] = field(default_factory=list)
    header: tuple[str, ...] = ()
    colmap: ColumnMap = field(default_factory=ColumnMap)
    col_count: int = 0
    page_count: int = 0
    page_col_counts: list[int] = field(default_factory=list)
    used_table_engine: str = "none"        # "lines_strict" | "lines" | "text" | "none"
    dropped_noise: int = 0
    dropped_headers: int = 0
    forward_filled: int = 0
    split_merged: int = 0
    section_spans: list[tuple[int, int, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.used_table_engine != "none" and bool(self.rows)


@dataclass
class Chunk:
    index: int
    body: list[DocRow]
    context: list[DocRow]           # read-only look-back so "-do-" resolves across a seam
    n_lo: int
    n_hi: int


# ══════════════════════════════════════════════════════════════════════════════
# HEADER DETECTION
# ══════════════════════════════════════════════════════════════════════════════

HEADER_TOKENS = {
    "AIRLINE", "AIRLINENAME", "CODE", "AIRLINECODE", "IATA", "ECO", "ECONOMY",
    "PECOM", "PECO", "PEY", "BUS", "BUSFRST", "BUSINESS", "CABINTYPE", "CABIN",
    "COMMISSION", "APPLICABLEON", "VALIDON", "VALIDITY", "TRAVELVALIDITY",
    "REMARKS", "REMARK", "REMARKSCONDITIONSIFANY",
}

# Header rows are scanned for in the first few rows of a page, never assumed to
# be row 0: the Akbar sheet buries its header at index 3 behind a blank row, a
# "CONSOLIDATOR" banner and a "PLB W.E.F …" banner.
HEADER_SCAN_DEPTH = 8
HEADER_MIN_HITS = 3


def _norm(s: str | None) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _find_header(rows: list[tuple[str, ...]]) -> tuple[int | None, tuple[str, ...] | None]:
    for idx, cells in enumerate(rows[:HEADER_SCAN_DEPTH]):
        hits = sum(1 for c in cells if _norm(c) in HEADER_TOKENS)
        non_empty = [c for c in cells if c and c.strip()]
        if hits >= HEADER_MIN_HITS and len(non_empty) == len(cells):
            return idx, cells
    return None, None


def _is_repeat_header(cells: tuple[str, ...], header: tuple[str, ...]) -> bool:
    """Continuation banners on pages 2..N repeat the header verbatim."""
    return tuple(_norm(c) for c in cells) == tuple(_norm(c) for c in header)


def build_colmap(header: tuple[str, ...]) -> ColumnMap:
    """Map column roles from the header. Deterministic and testable — deliberately
    not an LLM pass, because a wrong map would poison every chunk self-consistently."""
    cm = ColumnMap()
    for i, raw in enumerate(header):
        h = _norm(raw)
        if h in ("AIRLINE", "AIRLINENAME") and cm.airline is None:
            cm.airline = i
        elif h in ("CODE", "AIRLINECODE") and cm.code is None:
            cm.code = i
        elif h == "IATA" and cm.iata is None:
            cm.iata = i
        elif h in ("ECO", "ECONOMY") and cm.eco is None:
            cm.eco = i
        elif h in ("PECOM", "PECO", "PEY") and cm.pey is None:
            cm.pey = i
        elif h in ("BUS", "BUSFRST", "BUSINESS") and cm.bus is None:
            cm.bus = i
        elif h in ("CABINTYPE", "CABIN") and cm.cabin is None:
            cm.cabin = i
        elif h == "COMMISSION" and cm.commission is None:
            cm.commission = i
        elif h in ("VALIDON", "APPLICABLEON") and cm.valid_on is None:
            cm.valid_on = i
        elif h in ("VALIDITY", "TRAVELVALIDITY") and cm.validity is None:
            cm.validity = i
        elif h.startswith("REMARK") and cm.remarks is None:
            cm.remarks = i

    # Fall back to position 0 for the airline column — every observed layout
    # leads with it, and without it forward-fill and chunk nudging are blind.
    if cm.airline is None:
        cm.airline = 0

    if cm.cabin is not None and cm.commission is not None:
        cm.format_hint = "B"
    elif cm.eco is not None or cm.bus is not None:
        cm.format_hint = "A"
    return cm


# ══════════════════════════════════════════════════════════════════════════════
# SECTION DETECTION
# ══════════════════════════════════════════════════════════════════════════════

# Anchored on purpose. An unanchored keyword search matches data rows whose
# remarks read "Not valid on Domestic" / "No deal on Domestic" / "Not Valid for
# Domestic Sector" — 19 such rows across the three sample sheets.
SECTION_RE = re.compile(r"^\s*(?:::\s*)?(?P<kw>domestic|international|intl)\b[^%]*$", re.I)
SECTION_MAX_LEN = 40


def detect_section(cells: tuple[str, ...]) -> str | None:
    """A section banner occupies a row on its own.

    The test is EXACTLY one non-empty cell, not "at most two": Akbar's footer
    rows (['Telephone', '', '011-4040-3434/…']) have two and would otherwise be
    misread as banners.
    """
    non_empty = [c.strip() for c in cells if c and c.strip()]
    if len(non_empty) != 1:
        return None
    text = non_empty[0]
    if "%" in text or len(text) > SECTION_MAX_LEN:
        return None
    m = SECTION_RE.match(text)
    if not m:
        return None
    return "Domestic" if m.group("kw").lower().startswith("dom") else "International"


# ══════════════════════════════════════════════════════════════════════════════
# NOISE
# ══════════════════════════════════════════════════════════════════════════════

# Deal sheets end with contact blocks, GDS PCCs and T&C paragraphs. On the Akbar
# sheet these sit INSIDE the detected table bbox, so filtering by geometry does
# not remove them — but they are narrow and never carry a percentage.
NOISE_RE = re.compile(
    r"(@|\bhttps?://|\b\d{3,}[-\s]?\d{4,}|\bPCC\b|\bamadeus\b|\bgalileo\b|\bsabre\b"
    r"|\bterms\b|\bconditions\b|\bdisclaimer\b|\bsubject to change\b)",
    re.I,
)

# A rate cell is either "2.25%" / "CNP +2.25%" (a percent sign somewhere after a
# digit) or a bare number — many sheets drop the sign entirely and print "1.25",
# "8.50", "6" or "3+5.00". Requiring the cell to START with a digit is what keeps
# "SC 118" (a flat service charge) and "NET + SC 50" out.
_PCT_SIGN_RE = re.compile(r"\d\s*%")
_BARE_NUM_RE = re.compile(r"^\(?\s*\d")


def _is_rate_cell(text: str | None) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_PCT_SIGN_RE.search(t) or _BARE_NUM_RE.match(t))


def _row_expects_deals(cells: tuple[str, ...], cm: ColumnMap) -> bool:
    """Does a commission-role column hold something that parses as a rate?"""
    return any(ci < len(cells) and _is_rate_cell(cells[ci]) for ci in cm.rate_columns)


def is_noise_row(cells: tuple[str, ...], cm: ColumnMap) -> bool:
    """Conservative on purpose — a wide row, or any row carrying a rate in a rate
    column, is never noise. Eating a real row is far worse than paying for a
    wasted one.

    The "has a rate" guard is scoped to RATE columns specifically. Scanning every
    cell instead lets footer prose protect itself: Akbar's
    "NOTE :- '18% will be deducted…" contains a percentage but not in a rate
    column, and used to survive on that technicality.

    Note there is deliberately NO "drop everything after the last data row" rule:
    Akbar's only Domestic airline row sits immediately above its footer block.
    """
    non_empty = [c.strip() for c in cells if c and c.strip()]
    if not non_empty:
        return True
    if _row_expects_deals(cells, cm):
        return False
    if len(non_empty) > 2:
        return False
    # A deal needs at least an airline and a rate. One lonely cell with no rate
    # anywhere is a banner, a note or a T&C sentence.
    if len(non_empty) == 1:
        return True
    return any(NOISE_RE.search(c) for c in non_empty)


# ══════════════════════════════════════════════════════════════════════════════
# MERGED-CELL SPLIT
# ══════════════════════════════════════════════════════════════════════════════

CABIN_TOKEN_RE = re.compile(r"^(eco|economy|prem\s*eco|premium|prem/eco|eco/prem|bizz?|business|"
                            r"business/first|bizz/first|first|all)\b", re.I)


def split_merged_rows(rows: list[tuple[int, tuple[str, ...]]], cm: ColumnMap
                      ) -> tuple[list[tuple[int, tuple[str, ...]]], int]:
    """Format B sheets list one airline as N cabin sub-rows; the table engine
    sometimes merges those into a single row whose cabin cell holds N
    newline-separated tokens. Split them back apart BEFORE global n is assigned,
    so one n can never legitimately carry two deals of the same class."""
    if cm.cabin is None or cm.commission is None:
        return rows, 0

    out: list[tuple[int, tuple[str, ...]]] = []
    split_count = 0
    for page, cells in rows:
        cabin_parts = [p.strip() for p in (cells[cm.cabin] or "").split("\n") if p.strip()]
        if len(cabin_parts) < 2 or not all(CABIN_TOKEN_RE.match(p) for p in cabin_parts):
            out.append((page, cells))
            continue

        comm_parts = [p.strip() for p in (cells[cm.commission] or "").split("\n") if p.strip()]
        if len(comm_parts) != len(cabin_parts):
            # Can't distribute the rates positionally with confidence — leave the
            # row intact and let the model read it as printed.
            out.append((page, cells))
            continue

        for cabin, comm in zip(cabin_parts, comm_parts):
            new = list(cells)
            new[cm.cabin] = cabin
            new[cm.commission] = comm
            out.append((page, tuple(new)))
        split_count += len(cabin_parts) - 1
    return out, split_count


# ══════════════════════════════════════════════════════════════════════════════
# IDENTITY FORWARD-FILL
# ══════════════════════════════════════════════════════════════════════════════

# `cabin` is carried for the same reason as the identity columns: a sub-row that
# states a second rate for the same group ("Air Mauritius … 8.26% / 5.90% after
# 1 Apr") leaves the cabin blank, and a blank cabin names no class, so the row
# yields nothing at all.
IDENTITY_ROLES = ("airline", "code", "iata", "cabin")


def forward_fill_identity(rows: list[DocRow], cm: ColumnMap) -> tuple[list[DocRow], int]:
    """Format B lists one airline as several cabin sub-rows where only the first
    carries the name — 18 of Mirror's 80 extractable rows have a blank airline
    cell. A chunk that opens on one of those is unreadable, and a one-row
    look-back cannot rescue it (the parent can be two rows up).

    The carry is SCOPED to rows that hold a rate in a commission column, so
    footer lines like "psr.del@akbartravels.in" never inherit an airline name.
    """
    out: list[DocRow] = []
    carry: dict[str, str] = {}
    filled = 0
    last_section = None

    for row in rows:
        if row.section != last_section:      # structural break — nothing carries across it
            carry = {}
            last_section = row.section
        if not row.expects_deals:
            carry = {}
            out.append(row)
            continue

        for role in IDENTITY_ROLES:
            ci = getattr(cm, role)
            if ci is None or ci >= len(row.cells):
                continue
            if (row.cells[ci] or "").strip():
                carry[role] = row.cells[ci]
            elif role in carry:
                row = row.with_cell(ci, carry[role])
                if role == "airline":
                    filled += 1
        out.append(row)
    return out, filled


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT
# ══════════════════════════════════════════════════════════════════════════════

STRATEGIES = ("lines_strict", "lines", "text")


def _extract_with_strategy(content: bytes, strategy: str
                           ) -> tuple[list[tuple[int, tuple[str, ...]]], list[int], int]:
    """Return (page, cells) pairs plus the column count seen on each page."""
    import fitz  # PyMuPDF

    raw: list[tuple[int, tuple[str, ...]]] = []
    page_col_counts: list[int] = []
    with fitz.open(stream=io.BytesIO(content), filetype="pdf") as doc:
        page_count = doc.page_count
        for pno, page in enumerate(doc):
            tables = page.find_tables(strategy=strategy)
            best_cols = 0
            for table in tables:
                for cells in table.extract():
                    cells = tuple((c or "").strip() for c in cells)
                    raw.append((pno, cells))
                    best_cols = max(best_cols, len(cells))
            if best_cols:
                page_col_counts.append(best_cols)
    return raw, page_col_counts, page_count


def _build(content: bytes, strategy: str) -> DocLayout:
    try:
        raw, page_col_counts, page_count = _extract_with_strategy(content, strategy)
    except Exception:
        logger.exception("find_tables(strategy=%s) failed", strategy)
        return DocLayout()

    if not raw:
        return DocLayout(page_count=page_count)

    hdr_idx, header = _find_header([cells for _, cells in raw])
    if header is None:
        return DocLayout(page_count=page_count, page_col_counts=page_col_counts)

    return DocLayout(
        header=header,
        col_count=len(header),
        page_count=page_count,
        page_col_counts=page_col_counts,
        used_table_engine=strategy,
        # rows are filled in by build_layout once the strategy is accepted
        rows=[],
    )


def build_layout(content: bytes) -> DocLayout:
    """Parse a deal-sheet PDF into clean, globally-numbered table rows.

    The strategy cascade is gated on HEADER VALIDITY, not on "did we get any
    tables". The Lords sheet returns zero tables under `lines_strict` but a clean
    8-column table under `lines`; the `text` strategy also returns tables for it,
    with per-page column counts of 16/16/13/16 and a shredded header. A
    `len(tables) > 0` accept test walks straight into that.
    """
    import fitz  # noqa: F401 — imported here so a missing PyMuPDF surfaces as a clean failure

    chosen: DocLayout | None = None
    for strategy in STRATEGIES:
        probe = _build(content, strategy)
        if (probe.header
                and len(probe.header) == probe.col_count
                and probe.page_col_counts
                and all(pc == probe.col_count for pc in probe.page_col_counts)):
            chosen = probe
            break

    if chosen is None:
        return DocLayout()

    cm = build_colmap(chosen.header)
    raw, _, _ = _extract_with_strategy(content, chosen.used_table_engine)

    # Merged cabin rows are split before anything is numbered.
    raw, split_count = split_merged_rows(raw, cm)

    rows: list[DocRow] = []
    spans: list[tuple[int, int, str]] = []
    section: str | None = None
    dropped_noise = 0
    dropped_headers = 0
    n = 0

    for page, cells in raw:
        # Order matters and is load-bearing: a banner is consumed as a section
        # BEFORE the noise filter ever sees it.
        found = detect_section(cells)
        if found is not None:
            section = found
            spans.append((n, -1, section))
            continue
        if _is_repeat_header(cells, chosen.header) or cells == chosen.header:
            dropped_headers += 1
            continue
        if is_noise_row(cells, cm):
            dropped_noise += 1
            continue

        rows.append(DocRow(
            n=n,
            page=page,
            cells=cells,
            section=section,
            raw="\t".join(c.replace("\n", " ") for c in cells),
            expects_deals=_row_expects_deals(cells, cm),
        ))
        n += 1

    # Close each span at the last row it governs.
    for i, (start, _, sec) in enumerate(spans):
        end = spans[i + 1][0] - 1 if i + 1 < len(spans) else (n - 1)
        spans[i] = (start, end, sec)

    rows, filled = forward_fill_identity(rows, cm)

    chosen.rows = rows
    chosen.colmap = cm
    chosen.dropped_noise = dropped_noise
    chosen.dropped_headers = dropped_headers
    chosen.forward_filled = filled
    chosen.split_merged = split_count
    chosen.section_spans = spans
    return chosen


# ══════════════════════════════════════════════════════════════════════════════
# CHUNKING
# ══════════════════════════════════════════════════════════════════════════════

def _nudge_out_of_group(rows: list[DocRow], cut: int, start: int, cm: ColumnMap,
                        max_chars: int) -> int:
    """Never open a chunk on a row whose airline name was forward-filled rather
    than printed — the model would have no way to tell an inherited name from a
    real one. Walk the cut back to the head of the inheritance group."""
    if cut >= len(rows) or cm.airline is None:
        return cut
    probe = cut
    budget = int(max_chars * 1.25)
    used = sum(len(r.raw) for r in rows[start:cut])
    while probe > start + 1 and used < budget:
        head = rows[probe]
        prev = rows[probe - 1]
        # Same group == same airline text as the row above it.
        if (head.cells[cm.airline] or "").strip() != (prev.cells[cm.airline] or "").strip():
            break
        probe -= 1
        used -= len(rows[probe].raw)
    return probe


def chunk_rows(rows: list[DocRow], cm: ColumnMap, rows_per_chunk: int = 30,
               max_chars: int = 7000, context_rows: int = 1) -> list[Chunk]:
    out: list[Chunk] = []
    i = 0
    while i < len(rows):
        j, chars = i, 0
        while (j < len(rows)
               and (j - i) < rows_per_chunk
               and chars + len(rows[j].raw) <= max_chars):
            chars += len(rows[j].raw)
            j += 1
        j = max(j, i + 1)                                   # always make progress
        if j < len(rows):
            j = _nudge_out_of_group(rows, j, i, cm, max_chars)
        out.append(Chunk(
            index=len(out),
            body=rows[i:j],
            context=rows[max(0, i - context_rows):i],
            n_lo=rows[i].n,
            n_hi=rows[j - 1].n,
        ))
        i = j
    return out


SECTION_TAG = {"Domestic": "DOM", "International": "INTL", None: "--"}

# Order matters only for readability; the labels are what the model keys on.
_ROLE_LABELS = (
    ("airline", "AL"), ("code", "CD"), ("iata", "IATA"),
    ("eco", "ECO"), ("pey", "PEY"), ("bus", "BUS"),
    ("cabin", "CABIN"), ("commission", "COMM"),
    ("valid_on", "VALIDON"), ("validity", "VALIDITY"), ("remarks", "RMK"),
)


def render_row(row: DocRow, cm: ColumnMap) -> str:
    """Render one row as explicit LABEL=«value» pairs.

    Tab-joined cells against a separate COLUMNS: header made the model align
    fields by counting separators, and it miscounted — consecutive empty cells
    are near-invisible, so an Economy rate could land in the IATA slot and the
    Economy deal would simply never be emitted. Python already knows which
    column holds which role, so labelling removes the guesswork entirely.
    """
    used: set[int] = set()
    parts: list[str] = []
    for role, label in _ROLE_LABELS:
        ci = getattr(cm, role)
        if ci is None or ci >= len(row.cells):
            continue
        used.add(ci)
        parts.append(f"{label}=«{(row.cells[ci] or '').replace(chr(10), ' ').strip()}»")
    # Anything the header didn't map still goes across — never hide a cell.
    for ci, cell in enumerate(row.cells):
        if ci not in used and (cell or "").strip():
            parts.append(f"C{ci}=«{cell.replace(chr(10), ' ').strip()}»")
    return f"[{row.n:4d}][{SECTION_TAG[row.section]}] " + " ".join(parts)


def render_chunk(chunk: Chunk, header: tuple[str, ...], cm: ColumnMap) -> str:
    """The per-chunk user message.

    The section travels as a PER-ROW tag rather than a chunk-level header line.
    That is not a stylistic choice: on the Mirror sheet the Domestic section
    governs only rows 1-5 and the switch happens mid-page, so a chunk-level tag
    would mislabel roughly 26 international airlines.
    """
    lines = [
        "SOURCE COLUMNS: " + " | ".join(h.replace("\n", " ").strip() for h in header),
        "",
    ]

    if chunk.context:
        lines.append("# CONTEXT ONLY - DO NOT EXTRACT")
        lines.extend(render_row(r, cm) for r in chunk.context)
        lines.append("")

    lines.append("# EXTRACT EVERY ROW BELOW")
    lines.extend(render_row(r, cm) for r in chunk.body)
    return "\n".join(lines)
