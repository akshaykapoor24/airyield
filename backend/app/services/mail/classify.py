"""What is this attachment? — statements first (architecture/06 §6.4–6.5).

Deterministic, no AI: a file is recognised by the SAME column recognition the Vendor →
Statements upload screens use, so "the inbox says Third party · GDS" and "the GDS upload
wizard maps it" are one rule, not two that can disagree.

    PDF   BSPlink billing files — by file name (IN_FCAGBILLDETALT_*, IN_FCAGBILLSUMNG_*) or by
          the report code printed inside (FCAGBILLDETALT / FCAGBILLSUM).
    Sheet every statement type is scored with its own parser's `build_col_map` (the upload
          wizard's matcher); LCC Detailed with its own `suggest_mapping`. The best clear winner
          is the type. Divided PNR exports are also recognised by their file name.
          GDS, LCC and MO third-party exports share ONE column layout, so the variant comes
          from the file name ("LCC", "MO") and defaults to GDS — said so in `reason`.
          Not a known spec but a bank export → "Bank statement" (services/bank_statement).
          Ticket / PNR + fare columns but no known spec → "Statement · format not
          recognised": a statement worth importing through column mapping, never a guess.
    Else  "other" — deals, series contracts and payment advices get their own rules next.

Pure apart from the lazy parser imports: takes bytes, returns a DocClass.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)

# Bump when the rules change: attachments classified by an older version are re-checked on the
# next mailbox check (sync.classify_pending), so existing mail picks up new rules by itself.
CLASSIFIER_VERSION = 2          # 1: statements · 2: + deal sheets, subject context

SHEET_EXT = (".xls", ".xlsx", ".xlsm", ".xlsb", ".csv")
_SHEET_TYPES = ("spreadsheet", "excel", "csv", "ms-excel", "officedocument.spreadsheetml")

# type → (family, label). Families group the inbox filter: BSP / LCC / Third party / …
TYPE_LABEL: dict[str, tuple[str, str]] = {
    "bsp":              ("bsp", "BSP · Billing detail"),
    "bsp-summary":      ("bsp", "BSP · Billing summary"),
    "lcc-detailed":     ("lcc", "LCC · Detailed statement"),
    "lcc-di":           ("lcc", "LCC · DI statement"),
    "lcc-divided-pnr":  ("lcc", "LCC · Divided PNR"),
    "lcc-flown-report": ("lcc", "LCC · Flown report"),
    "lcc-cta-bta":      ("lcc", "LCC · CTA/BTA report"),
    "tp-gds":           ("third_party", "Third party · GDS"),
    "tp-lcc":           ("third_party", "Third party · LCC"),
    "tp-api":           ("third_party", "Third party · API"),
    "ndc":              ("ndc", "NDC statement"),
    "tgq-hmpr":         ("tgq", "TGQ HMPR"),
    "mo-gds":           ("mo", "MO statement (mid-office)"),
    "bank":             ("bank", "Bank statement"),
    "unknown":          ("unknown", "Statement · format not recognised"),
}

# Deals (incoming PLB / commission / incentive sheets from airlines and consolidators).
DEAL_LABEL = "Deal sheet"
_DEAL_WORDS = re.compile(
    r"\b(plb|deals?|incentives?|commissions?|comm\.?|schemes?|markups?|cash\s?backs?|segment\s+incentive|"
    r"productivity|override|net\s+fare|special\s+fare)\b", re.IGNORECASE)
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*%")
_DEAL_FILENAME = re.compile(r"deal|plb|incentive|scheme|commission|circular", re.IGNORECASE)
# Spreadsheets are named more loosely ("plb analysis.xlsx" is an internal workbook), so the
# file-name rule for sheets is narrower; real deal sheets are caught by their columns.
_DEAL_SHEET_NAME = re.compile(r"deal|scheme|circular", re.IGNORECASE)

# Spec-scored types; LCC Detailed and bank are handled on their own.
_SPEC_SLUGS = ("tgq-hmpr", "ndc", "lcc-di", "lcc-divided-pnr", "lcc-flown-report", "lcc-cta-bta",
               "tp-gds", "tp-lcc", "tp-api", "mo-gds")
_FLAT_FAMILY = {"tp-gds", "tp-lcc", "mo-gds"}          # same layout — variant from hints
_MIN_MATCHED = 5          # fewer recognised columns than this is never a confident type
_MIN_RATIO = 0.6          # …unless this share of the spec's columns matched
_MIN_ABSOLUTE = 15        # …or this many (wide specs: API has 93 columns, LCC Detailed 141)
_LCC_DETAILED_MIN = 20

_TICKETISH = re.compile(r"ticket|tkt|pnr|e\s*-?ticket")
_MONEYISH = re.compile(r"fare|amount|amt|net|total|tax|commission|comm\b|bill")


@dataclass
class DocClass:
    kind: str                         # statement | deal | other
    doc_type: str | None = None       # a TYPE_LABEL key
    family: str | None = None
    label: str | None = None
    confidence: float = 0.0
    meta: dict = field(default_factory=dict)   # matched, total, header_row, rows, reason

    def as_dict(self) -> dict:
        return asdict(self)


def _statement(doc_type: str, confidence: float, **meta) -> DocClass:
    family, label = TYPE_LABEL[doc_type]
    return DocClass("statement", doc_type, family, label, round(confidence, 3), meta)


def _deal(confidence: float, **meta) -> DocClass:
    return DocClass("deal", "deal-sheet", "deal", DEAL_LABEL, round(confidence, 3), meta)


def looks_like_deal_text(text: str) -> bool:
    """Deal vocabulary AND percentages — a circular, not a passing mention of "deal"."""
    return len(_DEAL_WORDS.findall(text or "")) >= 2 and len(_PERCENT.findall(text or "")) >= 1


def _key(h: str) -> str:
    """'Booking Date' / 'BookingDate' / 'booking_date' → 'bookingdate'."""
    return re.sub(r"[^a-z0-9]+", "", str(h).lower())


def _matched(slug: str, cols: list[str]) -> tuple[int, int]:
    """(recognised columns, columns in the spec) — the upload wizard's own matcher."""
    from app.services import spec_mapping, statement_spec as spec
    total = len(spec.columns(slug)) or len(spec.headers(slug)) or 1
    builder = None
    parser = spec.parser(slug)
    try:
        if parser:
            from app.api.v1.statements import _get_builder   # the router's resolver; moves to services/intake later
            builder = _get_builder(parser)
        elif spec.supports_mapping(slug):
            builder = spec_mapping.mapper_for(slug)
        if builder is not None and hasattr(builder, "build_col_map"):
            return len(builder.build_col_map(cols)), total
    except Exception:  # noqa: BLE001 — a parser that cannot read these headers matched nothing
        logger.debug("[mail.classify] %s matcher failed", slug, exc_info=True)
    wanted = {_key(c.get("header", "")) for c in spec.columns(slug)} | {_key(h) for h in spec.headers(slug)}
    wanted.discard("")
    return len({_key(c) for c in cols} & wanted), total


def _flat_variant(filename: str, sender_hint: str | None) -> tuple[str, str]:
    name = filename.lower()
    if sender_hint == "internal" or re.search(r"\bmo\b|mid[\s-]?office", name):
        return "mo-gds", "file name / sender says mid-office"
    if "lcc" in name:
        return "tp-lcc", "file name says LCC"
    if "gds" in name or "bsp" in name:
        return "tp-gds", "file name says BSP / GDS"
    return "tp-gds", "GDS assumed — the GDS, LCC and MO exports share one layout"


def _classify_pdf(data: bytes, filename: str, context: str = "") -> DocClass:
    name = filename.upper()
    if "FCAGBILLDETALT" in name:
        return _statement("bsp", 0.98, reason="BSPlink file name")
    if "FCAGBILLSUM" in name:
        return _statement("bsp-summary", 0.98, reason="BSPlink file name")
    try:
        import fitz   # PyMuPDF
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                return DocClass("other", meta={"reason": "password-protected PDF"})
            text = " ".join(doc[i].get_text() for i in range(min(2, doc.page_count))).upper()
    except Exception:  # noqa: BLE001 — unreadable PDF: not a statement we can recognise
        return DocClass("other", meta={"reason": "PDF could not be read"})
    if "FCAGBILLDETALT" in text or "AGENT BILLING DETAILS" in text:
        return _statement("bsp", 0.9, reason="BSP report code inside the PDF")
    if "FCAGBILLSUM" in text or ("BILLING SUMMARY" in text and "BSP" in text):
        return _statement("bsp-summary", 0.85, reason="BSP summary heading inside the PDF")
    if looks_like_deal_text(text):
        return _deal(0.85, reason="deal vocabulary and percentages inside the PDF")
    if _DEAL_FILENAME.search(filename) or looks_like_deal_text(context):
        return _deal(0.7, reason="file name / email subject says deal")
    return DocClass("other", meta={"reason": "PDF without statement or deal markers"})


def _deal_columns(lowered_cols: list[str]) -> bool:
    """The deal import's own vocabulary (services/deal_extraction._COL_MAP): an airline column
    next to class or commission columns."""
    from app.services.deal_extraction import _normalise_col
    keys = {_normalise_col(c) for c in lowered_cols}
    return "airline_name" in keys and bool(keys & {"eco", "peco", "bus", "remarks", "validity_raw", "valid_on"}) \
        or ("airline_name" in keys and any(_DEAL_WORDS.search(c) for c in lowered_cols))


def _classify_sheet(data: bytes, filename: str, sender_hint: str | None, context: str = "") -> DocClass:
    from app.services import lcc_detailed_spec, spreadsheet
    try:
        table = spreadsheet.read_table(data, filename)
    except Exception as exc:  # noqa: BLE001
        return DocClass("other", meta={"reason": f"spreadsheet could not be read: {str(exc)[:80]}"})
    cols = [str(c) for c in table.df.columns]
    rows = int(len(table.df))
    base = {"header_row": getattr(table, "header_row", None), "rows": rows, "columns": len(cols)}

    if filename.lower().startswith("dividepnr"):
        n, total = _matched("lcc-divided-pnr", cols)
        return _statement("lcc-divided-pnr", 0.95, matched=n, total=total, reason="Divided PNR export file name", **base)

    _mapping, lcc_n, _template = lcc_detailed_spec.suggest_mapping(cols)
    scores = {slug: _matched(slug, cols) for slug in _SPEC_SLUGS}
    best_slug, (best_n, best_total) = max(scores.items(), key=lambda kv: (kv[1][0] / kv[1][1], kv[1][0]))

    if lcc_n >= _LCC_DETAILED_MIN and lcc_n >= best_n:
        conf = min(0.97, 0.6 + lcc_n / 100)
        return _statement("lcc-detailed", conf, matched=lcc_n, total=len(lcc_detailed_spec.LCC_STANDARD_HEADERS),
                          reason="LCC Detailed columns", **base)

    # Wide specs rarely match a big share, so an absolute count also counts as clear.
    candidates = [(slug, n, t) for slug, (n, t) in scores.items()
                  if n >= _MIN_MATCHED and (n / t >= _MIN_RATIO or n >= _MIN_ABSOLUTE)]
    if candidates:
        slug, n, total = max(candidates, key=lambda c: (c[1] / c[2], c[1]))
        reason = f"{n} of {total} {TYPE_LABEL[slug][1]} columns recognised"
        conf = min(0.97, 0.55 + 0.4 * (n / total) + min(n, 40) / 400)
        if slug in _FLAT_FAMILY:
            slug, why = _flat_variant(filename, sender_hint)
            reason = f"{n} columns of the third-party export layout recognised; {why}"
            conf = min(conf, 0.85)
        return _statement(slug, conf, matched=n, total=total, reason=reason, **base)

    try:
        from app.services import bank_statement
        parsed = bank_statement.parse_statement(data, filename)
        if parsed.rows:
            return _statement("bank", 0.9, reason="bank statement layout",
                              bank=parsed.bank_name, account=(parsed.account_no or "")[-4:] or None, **base)
    except Exception:  # noqa: BLE001 — not a bank export
        pass

    lowered = [c.strip().lower() for c in cols]
    if rows and (_deal_columns(lowered) or _DEAL_SHEET_NAME.search(filename) or
                 (context and _DEAL_WORDS.search(context) and not _TICKETISH.search(" ".join(lowered)))):
        return _deal(0.8 if _deal_columns(lowered) else 0.65,
                     reason="airline and commission columns" if _deal_columns(lowered) else "file name / email subject says deal",
                     **base)

    keys = " ".join(_key(c) for c in cols)
    if rows and _TICKETISH.search(" ".join(c.lower() for c in cols)) and _MONEYISH.search(keys):
        return _statement("unknown", 0.6, reason="ticket and fare columns, but not a known statement format",
                          best_guess=best_slug, best_matched=best_n, **base)
    return DocClass("other", meta={"reason": "spreadsheet that is not a statement", **base})


def is_sheet(filename: str, content_type: str) -> bool:
    return filename.lower().endswith(SHEET_EXT) or any(t in (content_type or "").lower() for t in _SHEET_TYPES)


def classify(data: bytes, filename: str, content_type: str, *, sender_hint: str | None = None,
             context: str = "") -> DocClass:
    """sender_hint: the sender's party type ('agency', 'corporate', 'customer', 'internal').
    context: the email's subject (and opening lines) — "Fwd: Vendor deal sheet" tells a deal
    sheet from a statement when the file itself is ambiguous. It never overrides a statement
    the columns already proved."""
    name = filename or ""
    if name.lower().endswith(".pdf") or (content_type or "").lower() == "application/pdf" or data[:5] == b"%PDF-":
        return _classify_pdf(data, name, context)
    if is_sheet(name, content_type):
        return _classify_sheet(data, name, sender_hint, context)
    if name.lower().endswith((".docx", ".doc")) and (_DEAL_FILENAME.search(name) or looks_like_deal_text(context)):
        return _deal(0.6, reason="Word document named / introduced as a deal")
    return DocClass("other", meta={"reason": "not a statement or deal file type"})
