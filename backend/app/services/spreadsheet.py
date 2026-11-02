"""One reader for every uploaded spreadsheet, dispatching on CONTENT, not on the file name.

Two things this module exists to get right, both learned from real supplier files:

**The name lies.** ``23APR2026_HMPR_305T.xls`` in the sample folder begins ``PK\\x03\\x04``
and contains ``[Content_Types].xml`` — it is an xlsx wearing a .xls extension, and travel
back-office systems produce these constantly. The reverse happens too: a genuine BIFF
workbook saved as ``.xlsx``, and an HTML ``<table>`` saved as ``.xls``. Every reader in this
codebase used to branch on ``filename.endswith(".xls")``, so each of them was one mis-named
file away from a stack trace. Here the first eight bytes decide, and the extension is only
consulted when the bytes say nothing (a delimited text file).

**The header is not row 1.** A consolidator statement opens with a title, a period line and
the issuing company — ``GLOBE OUR 08 15 AUG 26.xls`` puts its real header on row 4. The
older scanners in this repo re-read the whole file once per candidate row and gave up after
three, so they could not reach it. ``detect_header`` reads the sheet ONCE with ``header=None``
and scores candidate rows in memory, which makes scanning 25 rows cost no more than scanning
one.

Engine choice is deliberate:

* legacy ``.xls`` → ``calamine``. pandas routes BIFF to ``xlrd``, which is unmaintained for
  this purpose and .xls-only; calamine is one Rust dependency covering xls/xlsx/xlsm/xlsb.
* ``.xlsx`` → ``openpyxl``, unchanged. Every working upload in the product already goes
  through it, and swapping the engine under them to gain speed we do not need would be
  trading a real regression risk for nothing.
* ``.xlsx`` with ``fast=True`` → ``calamine``. Only where the speed IS needed: Internal
  Statement's background import of a 1-lakh-line sales report (services/internal_import.py),
  which openpyxl reads in minutes. tests/test_spreadsheet_fast_reader.py holds the two
  engines to the same grid — dates, numbers, leading zeros, blanks.

Pure functions, no DB and no FastAPI — callers raise their own HTTP errors from
``SpreadsheetError``.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd

# ── Formats ──────────────────────────────────────────────────────────────────
XLS = "xls"              # OLE2 compound file holding a BIFF workbook
XLSX = "xlsx"            # zip container (xlsx / xlsm)
ODS = "ods"              # zip container, OpenDocument — recognised so we can say so
XML2003 = "xml2003"      # SpreadsheetML, Excel 2003's XML workbook
HTML = "html"            # an HTML <table> saved with a spreadsheet extension
DELIMITED = "delimited"  # csv / tsv / tab / txt

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP = b"PK\x03\x04"

# Engine per format. Only .xls changes hands; xlsx keeps the engine it has always used.
_ENGINE = {XLS: "calamine", XLSX: "openpyxl"}

_DELIMITED_EXT = (".csv", ".tsv", ".tab", ".txt")

# A cell is empty if it is blank, whitespace-only, or one of the null spellings a
# spreadsheet engine produces. The Globe statement pads unused text cells to a fixed
# width, so " " * 35 is an empty Reference, not a value — without this every such
# column reads as populated.
#
# Placeholders like "-", "--" and "N/A" are deliberately NOT here. They are things a
# person typed, and the statement importers store their cells verbatim on purpose
# ("a stray N/A", api/v1/statements.py) — blanking them in a shared reader would
# silently rewrite data for every importer that has always kept them. The ticket
# path already reads them as absent, in _to_str / _to_float where that decision
# belongs to the field rather than to the file.
_EMPTY = {"", "nan", "none", "nat", "null", "<na>"}

_NUMERIC_RE = re.compile(r"^[+-]?[\d,]*\.?\d+[-]?$|^\(\s*[\d,.]+\s*\)$")


class SpreadsheetError(Exception):
    """The file cannot be read. The message is written to be shown to the user."""


def _install_default_xls_reader() -> None:
    """Teach bare `pd.read_excel` to read legacy .xls, for the callers not yet swept.

    pandas already identifies a BIFF workbook from its magic bytes, then routes it
    to xlrd by default and raises ImportError because xlrd is not installed. This
    points that default at calamine instead.

    Defence in depth, not the mechanism: the readers below always pass `engine=`
    explicitly, so this service never depends on its own side effect. It exists so
    that a `pd.read_excel` somewhere we have not touched — a Celery task, a script,
    a new endpoint written next month — does not fail on a supplier's .xls.
    """
    try:
        import python_calamine  # noqa: F401
    except ImportError:
        return
    try:
        pd.set_option("io.excel.xls.reader", "calamine")
    except Exception:  # noqa: BLE001 — an older pandas without the option
        pass


_install_default_xls_reader()


def cell(value) -> str:
    """One cell as a trimmed string; every flavour of empty becomes ""."""
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in _EMPTY else s


# ── Sniffing ─────────────────────────────────────────────────────────────────

def sniff(content: bytes, filename: str = "") -> str:
    """The file's real format, from its bytes. The extension is the last resort."""
    head = content[:8]
    if head.startswith(_OLE2):
        return XLS
    if head.startswith(_ZIP):
        # Both xlsx and ods are zips. The part names are in the first few KB of the
        # central content, so a cheap substring search separates them without unzipping.
        window = content[:65536]
        if b"[Content_Types].xml" in window or b"xl/workbook.xml" in window:
            return XLSX
        if b"opendocument.spreadsheet" in window:
            return ODS
        return XLSX  # a zip that looks like neither is still most likely an xlsx

    text = content[:4096].decode("utf-8", errors="ignore").lstrip().lower()
    if text.startswith("<?xml"):
        # SpreadsheetML declares itself in its namespace list.
        if "urn:schemas-microsoft-com:office:spreadsheet" in text:
            return XML2003
        return XML2003 if "<workbook" in text else HTML
    if text.startswith(("<html", "<!doctype html", "<table", "<meta")):
        return HTML

    if (filename or "").lower().endswith(_DELIMITED_EXT):
        return DELIMITED
    # Bytes said nothing recognisable and the name does not claim a text format. Treat it
    # as delimited anyway: read_csv fails with a clearer message than a format guess would.
    return DELIMITED


# ── Reading the raw grid ─────────────────────────────────────────────────────

# Excel's own idea of a sheet's size can be the whole grid: one column filled or formatted
# down to row 1,048,576 makes the used range a million rows long, and the reader then walks
# every one — minutes and gigabytes for a 30,000-line statement (Yatra's sales report, with
# a header-only column filled to the bottom). Above this many rows the real extent is found
# first.
_IMPLAUSIBLE_ROWS = 200_000
# Lines with fewer than two filled cells, one after another, that mark the end of the data.
# No ticket line, header or footer is that thin for that long.
_THIN_RUN = 1_000


def _data_rows(book: pd.ExcelFile, name: str) -> int | None:
    """How many rows of sheet `name` to read — None for all of them (the usual case: only a
    sheet claiming more than _IMPLAUSIBLE_ROWS is scanned). The data ends at the last row
    with two or more filled cells before a run of _THIN_RUN thinner ones."""
    try:
        ws = book.book[name]
        claimed, rows = ws.max_row or 0, lambda: ws.iter_rows(values_only=True)
    except Exception:  # noqa: BLE001 — not an openpyxl sheet
        # calamine (`fast`). Loading the sheet to ask its height is the whole read, so the
        # height the file declares is asked instead; only an implausible one is loaded and
        # scanned (an empty cell reads as "").
        if (_declared_rows(book, name) or 0) <= _IMPLAUSIBLE_ROWS:
            return None
        try:
            rows = book.book.get_sheet_by_name(name).iter_rows
        except Exception:  # noqa: BLE001 — read it whole, as before
            return None
        claimed = _IMPLAUSIBLE_ROWS + 1
    if claimed <= _IMPLAUSIBLE_ROWS:
        return None
    last = thin = 0
    for i, row in enumerate(rows(), start=1):
        if sum(1 for v in row if v not in (None, "")) >= 2:
            last, thin = i, 0
        else:
            thin += 1
            if thin >= _THIN_RUN:
                break
    return last or None


_DIMENSION = re.compile(rb'<(?:\w+:)?dimension\s+ref="[A-Z]*\d*:?[A-Z]*(\d+)"')


def _declared_rows(book: pd.ExcelFile, name: str) -> int | None:
    """The last row sheet `name` of an xlsx says it uses — its `<dimension ref="A1:BC33000">`,
    read off the head of the sheet's XML without parsing a row. None when it does not say."""
    import posixpath
    import zipfile
    import xml.etree.ElementTree as ET

    try:
        handle = book._io if hasattr(book, "_io") else None
        data = handle.getvalue() if isinstance(handle, io.BytesIO) else None
        if data is None:
            return None
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            ns_main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            ns_rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
            rid = next((el.get(f"{ns_rel}id")
                        for el in ET.fromstring(z.read("xl/workbook.xml")).iter(f"{ns_main}sheet")
                        if el.get("name") == name), None)
            target = next((el.get("Target")
                           for el in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
                           if el.get("Id") == rid), None)
            if not target:
                return None
            part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"xl/{target}")
            with z.open(part) as f:
                head = f.read(8192)
        m = _DIMENSION.search(head)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001 — an odd workbook: no height known
        return None


def _read_excel_grid(content: bytes, kind: str, sheet: str | None,
                     fast: bool = False) -> tuple[pd.DataFrame, list[str], str]:
    engine = "calamine" if fast else _ENGINE[kind]
    try:
        book = pd.ExcelFile(io.BytesIO(content), engine=engine)
    except ImportError as exc:
        raise SpreadsheetError(
            f"This workbook needs the '{engine}' reader, which is not installed on the "
            f"server. ({exc})"
        ) from exc
    except Exception as exc:  # noqa: BLE001 — corrupt, truncated or password-protected
        raise SpreadsheetError(_unreadable(exc)) from exc

    sheets = [str(s) for s in book.sheet_names]
    if not sheets:
        raise SpreadsheetError("The workbook has no sheets.")

    if sheet is not None and str(sheet) not in sheets:
        raise SpreadsheetError(
            f"The workbook has no sheet named '{sheet}'. It has: {', '.join(sheets)}."
        )

    def _grid(name: str) -> pd.DataFrame:
        nrows = _data_rows(book, name) if kind == XLSX else None
        return book.parse(sheet_name=name, header=None, dtype=str, nrows=nrows)

    if sheet is not None:
        return _grid(str(sheet)), sheets, str(sheet)

    # No sheet asked for: take the one with the most populated cells. A statement workbook
    # routinely ships with Excel's empty Sheet2/Sheet3 still attached, and defaulting to
    # the first sheet is only right by accident.
    best_name, best_grid, best_filled = sheets[0], None, -1
    for name in sheets:
        try:
            g = _grid(name)
        except Exception:  # noqa: BLE001 — one unreadable sheet must not lose the others
            continue
        # The only sheet is the one, however full — counting is a pass over every cell.
        if len(sheets) == 1:
            return g, sheets, name
        filled = int(g.map(lambda v: bool(cell(v))).to_numpy().sum()) if not g.empty else 0
        if filled > best_filled:
            best_name, best_grid, best_filled = name, g, filled
    if best_grid is None:
        raise SpreadsheetError("No sheet in this workbook could be read.")
    return best_grid, sheets, best_name


def _cells(frame: pd.DataFrame) -> pd.DataFrame:
    """`frame.map(cell)`, a column at a time instead of a Python call per cell — the same
    strings (tests/test_spreadsheet_fast_reader.py). The `fast` read's."""
    cleaned = []
    for i in range(frame.shape[1]):
        col = frame.iloc[:, i]
        text = col.astype(object).where(col.notna(), "").astype(str).str.strip()
        cleaned.append(text.mask(text.str.lower().isin(_EMPTY), ""))
    out = pd.concat(cleaned, axis=1) if cleaned else frame.copy()
    out.columns = frame.columns
    return out


def _unreadable(exc: Exception) -> str:
    text = str(exc).lower()
    if "password" in text or "encrypted" in text:
        return "This file is password-protected. Remove the protection and upload it again."
    return f"The file could not be read: {exc}"


def read_grid(
    content: bytes, filename: str = "", sheet: str | None = None, fast: bool = False,
) -> tuple[pd.DataFrame, list[str], str | None, str]:
    """(grid, sheets, sheet, kind) — every cell a string, NO header applied.

    The grid is deliberately header-less: `detect_header` needs to look at the candidate
    header rows as data before deciding which one they are.

    `fast`: an xlsx is read with calamine rather than openpyxl (see the module docstring).
    """
    if not content:
        raise SpreadsheetError("The uploaded file is empty.")

    kind = sniff(content, filename)

    if kind in (XLS, XLSX):
        grid, sheets, chosen = _read_excel_grid(content, kind, sheet, fast)
        return grid, sheets, chosen, kind

    if kind == ODS:
        raise SpreadsheetError(
            "This is an OpenDocument spreadsheet (.ods). Save it as .xlsx or .csv and "
            "upload it again."
        )

    if kind == XML2003:
        raise SpreadsheetError(
            "This is an Excel 2003 XML workbook, which this importer cannot read. Open it "
            "in Excel and save it as .xlsx or .csv, then upload it again."
        )

    if kind == HTML:
        try:
            tables = pd.read_html(io.BytesIO(content), header=None)
        except Exception as exc:  # noqa: BLE001
            raise SpreadsheetError(_unreadable(exc)) from exc
        if not tables:
            raise SpreadsheetError("This file is an HTML page with no table in it.")
        names = [f"Table {i + 1}" for i in range(len(tables))]
        if sheet is not None:
            if sheet not in names:
                raise SpreadsheetError(f"No table named '{sheet}'. It has: {', '.join(names)}.")
            picked = tables[names.index(sheet)]
            return picked.astype(str), names, sheet, kind
        idx = max(range(len(tables)), key=lambda i: tables[i].size)
        return tables[idx].astype(str), names, names[idx], kind

    delim = _sniff_delimiter(content)
    try:
        # index_col=False forces positional alignment: these files routinely end each
        # line with a trailing delimiter, and without it pandas reads the first column
        # as a row index and shifts every value one place left.
        #
        # `names` fixes the column count from the WIDEST line rather than the first.
        # A statement whose first line is a one-cell title would otherwise give a
        # one-column frame and every real column after it would be dropped.
        grid = pd.read_csv(
            io.BytesIO(content), dtype=str, sep=delim, engine="python",
            header=None, index_col=False, skip_blank_lines=False,
            names=range(_max_fields(content, delim)),
        )
    except Exception as exc:  # noqa: BLE001
        raise SpreadsheetError(
            f"The file could not be read as a spreadsheet or as delimited text: {exc}"
        ) from exc
    return grid, [], None, kind


def _max_fields(content: bytes, delim: str) -> int:
    text = content[:1_048_576].decode("utf-8", errors="ignore")
    widest = max(
        (ln.count(delim) + 1 for ln in text.splitlines() if ln.strip()),
        default=1,
    )
    return max(1, widest)


def _sniff_delimiter(content: bytes) -> str:
    """The delimiter, judged across many lines rather than the first one.

    pandas' own ``sep=None`` looks at the start of the file, which is exactly where
    a statement puts its title. Given

        TICKET STATEMENT
        Ticket No,Airline,Fare

    it sees no comma on line 1, guesses whitespace, and splits "Ticket No" in half.
    Counting candidates across a window of lines and taking the one that divides
    the most lines evenly gets it right whatever sits on top.
    """
    text = content[:65536].decode("utf-8", errors="ignore")
    lines = [ln for ln in text.splitlines() if ln.strip()][:50]
    if not lines:
        return ","
    best, best_score = ",", -1.0
    for delim in (",", ";", "\t", "|"):
        counts = [ln.count(delim) for ln in lines]
        present = [c for c in counts if c > 0]
        if len(present) < max(1, len(lines) // 2):
            continue
        # Prefer the delimiter that appears the same number of times on most lines:
        # that is what a column separator does and what stray punctuation does not.
        modal = max(set(present), key=present.count)
        score = present.count(modal) * modal
        if score > best_score:
            best, best_score = delim, score
    return best


# ── Header detection ─────────────────────────────────────────────────────────

def _row_cells(grid: pd.DataFrame, i: int) -> list[str]:
    return [cell(v) for v in grid.iloc[i].tolist()]


def _numeric_count(cells: list[str]) -> int:
    return sum(1 for c in cells if c and _NUMERIC_RE.match(c.replace(" ", "")))


def detect_header(grid: pd.DataFrame, recognise=None, max_scan: int = 25) -> int:
    """Index of the row that is the header. 0 when there is nothing better.

    `recognise(headers) -> int` says how many of those strings the caller can map onto a
    canonical field; it is the strongest signal by far and everything else is a tiebreak
    for files whose vocabulary we do not know.

    The three tiebreaks, in order:

    * how many of its cells are TEXT rather than numbers — a header is words,
    * how much more numeric the row below is — a header sits on top of its data,
    * how many cells it fills at all.

    Textiness outranks fill count deliberately. A header with one blank column fills
    fewer cells than the data row under it, and ranking on fill alone chose the data
    row — which then became the column names, with the real headers imported as a
    ticket.

    A row filling less than half of the widest row is not considered at all. That is what
    rules out the title, the period line and the company name above a statement's header
    without needing to understand any of them.
    """
    if grid.empty:
        return 0

    scan = min(max_scan, len(grid))
    rows = [_row_cells(grid, i) for i in range(scan)]
    filled = [sum(1 for c in r if c) for r in rows]
    widest = max(filled) if filled else 0
    if widest == 0:
        return 0
    floor = max(2, widest // 2)

    best_i, best_score = 0, None
    for i, cells in enumerate(rows):
        if filled[i] < floor:
            continue
        named = [c for c in cells if c]
        matched = recognise(named) if recognise else 0
        texty = len(named) - _numeric_count(named)
        below = _numeric_count(rows[i + 1]) - _numeric_count(named) if i + 1 < scan else 0
        score = (matched, texty, below, filled[i])
        if best_score is None or score > best_score:
            best_i, best_score = i, score
    return best_i


def _header_names(cells: list[str]) -> list[str]:
    """Header strings, with blanks named and repeats suffixed.

    Duplicate column names would collapse into one another as soon as the frame is indexed
    by name, so a file with two "Amount" columns must not silently lose one.
    """
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, c in enumerate(cells):
        name = c or f"Column {i + 1}"
        n = seen.get(name, 0) + 1
        seen[name] = n
        out.append(name if n == 1 else f"{name} ({n})")
    return out


# ── The public result ────────────────────────────────────────────────────────

@dataclass
class ReadResult:
    df: pd.DataFrame                       # the body, columns named by the header row
    columns: list[str]
    header_row: int
    sheet: str | None
    sheets: list[str] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)   # the lines above the header
    kind: str = ""
    grid: pd.DataFrame | None = None       # the raw header-less grid, for a raw preview


def read_table(
    content: bytes,
    filename: str = "",
    *,
    sheet: str | None = None,
    header_row: int | None = None,
    recognise=None,
    max_scan: int = 25,
    fast: bool = False,
) -> ReadResult:
    """Read one sheet into a named-column frame. `fast` as in ``read_grid``.

    `header_row` is DETECTED when None and OBEYED when given. Passing it back on a second
    read of the same file is not optional: a column map is a list of column NAMES, so a
    re-detection that lands one row out renames every column and silently discards the
    whole mapping.
    """
    grid, sheets, chosen, kind = read_grid(content, filename, sheet, fast)

    if grid.empty:
        return ReadResult(
            df=grid, columns=[], header_row=0, sheet=chosen, sheets=sheets,
            preamble=[], kind=kind, grid=grid,
        )

    if header_row is None:
        header_row = detect_header(grid, recognise, max_scan)
    elif not 0 <= header_row < len(grid):
        raise SpreadsheetError(
            f"Header row {header_row + 1} is outside this sheet, which has {len(grid)} rows."
        )

    columns = _header_names(_row_cells(grid, header_row))
    body = grid.iloc[header_row + 1:].reset_index(drop=True)
    body.columns = columns
    body = _cells(body) if fast else body.map(cell)
    # Drop rows that are empty across every column. A statement's trailing blank rows and
    # the spacer row above a totals block would otherwise import as blank tickets. Every
    # cell is a string by now, so a row is empty when none of its strings has anything in
    # it — asked of the whole frame at once: row by row, it was most of a lakh-line read.
    body = body[(body != "").any(axis=1)].reset_index(drop=True)

    preamble = [c for i in range(header_row) for c in _row_cells(grid, i) if c]

    return ReadResult(
        df=body, columns=columns, header_row=header_row, sheet=chosen,
        sheets=sheets, preamble=preamble, kind=kind, grid=grid,
    )


def read_df(
    content: bytes,
    filename: str = "",
    header_row: int = 0,
    *,
    sheet: str | None = None,
    nrows: int | None = None,
) -> pd.DataFrame:
    """A named-column frame with the header taken from `header_row`.

    The drop-in for the `_read_df` helpers that were copied across the routers:
    same signature, same return, but the format comes from the file's bytes rather
    than its extension, so a legacy .xls and an xlsx misnamed .xls both work.
    """
    result = read_table(content, filename, sheet=sheet, header_row=header_row)
    df = result.df
    return df.head(nrows) if nrows else df


# ── Reading a statement's period out of its preamble ─────────────────────────
# "For The Period 8 August 2026 To 15 August 2026" is close to a convention on Indian
# consolidator statements, and it is exactly what the upload form asks the user to retype
# into Valid From / Valid To.

_PERIOD_RE = re.compile(
    r"(?:for\s+the\s+)?(?:period|from|dated?)\b\s*[:\-]?\s*"
    r"(?P<a>.{4,40}?)\s+(?:to|through|till|until|upto|[-–—])\s+(?P<b>.{4,40}?)\s*$",
    re.I,
)


def parse_period(lines: list[str] | str) -> tuple[str, str] | None:
    """(from_iso, to_iso) read out of a preamble line, or None.

    Both ends must parse and be in order; a half-understood period is worse than none,
    because the user would have to notice the wrong date rather than fill in a blank.
    """
    from app.services.flat_statement import to_iso_date

    for line in ([lines] if isinstance(lines, str) else lines):
        m = _PERIOD_RE.search(line or "")
        if not m:
            continue
        a, b = to_iso_date(m.group("a")), to_iso_date(m.group("b"))
        if a and b and a <= b:
            return a, b
    return None
