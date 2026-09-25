"""Read a group / series / SIT / MICE contract PDF into a draft the review form can load.

THE SHAPE OF THE PROBLEM. Both reference contracts are phone photographs of paper — no
text layer at all — and they could hardly be more different: Air France's is a priced
Group Sales Agreement with deposits, a name-list date, a ticketing date and two
date-banded cancellation tables; Air India's is a group request with no price anywhere and
three pages of quota rules (80% materialisation, 20% free release, 20% name replacement,
4000/6000/9000 per-cabin grids, D-24h no-show). A reader that expects one layout reads
neither. So the model is given the whole document — text where there is text, the page
image where there is not — and a strict schema that mirrors this module's own vocabulary.

WHAT THE MODEL DOES AND WHAT PYTHON DOES. The model reads and classifies: it is good at
"this paragraph is a partial-cancellation band" and bad at arithmetic. Everything that is
arithmetic or a rule is done here, deterministically, and tested:

  * vocabularies are forced (`_choice`), so a creative enum from the model is dropped, not
    stored;
  * a series pattern ("every Tue/Sat, 01 Nov – 31 Mar") is expanded into dated departures
    here, not by the model;
  * cross-checks — components vs the printed per-pax total, per-pax × seats vs the printed
    group total, a stated deadline vs its "N days before departure", deposits vs a round
    percentage of a basis (Air France's 38,760 is exactly 5% of the 775,200 net-fare total)
    — become warnings the reviewer has to acknowledge.

NOTHING HERE WRITES A CONTRACT. The output is a draft for a person to review; the save goes
through the ordinary create endpoint like a hand-typed contract.

The document text is data, not instructions. It reaches the model only as user content,
the output is held to a JSON schema, and a person approves every field before it is saved.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.models.series import (
    COMPONENT_CODES, CONTRACT_TYPES, DEADLINE_TYPES, DIRECTIONS, DOCUMENT_KINDS,
    PAX_TYPES, PAYMENT_KINDS, SOURCE_TYPES, TERM_CHARGE_TYPES, TERM_PHASES,
    TERM_RULE_TYPES, TERM_SCOPES,
)
from app.services.series import bases

logger = logging.getLogger(__name__)

CABINS = ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST")
# A page with less text than this is treated as scanned and sent as an image. A photo of
# paper still yields a few stray characters (a page number, a watermark) from some
# producers, so zero is the wrong threshold.
MIN_TEXT_CHARS = 60
# Longest edge of a rendered page. Past ~2000px the model downsamples anyway; below
# ~1400px the small print of a penalty table stops being legible.
RENDER_LONG_EDGE = 2000
MAX_EXPANDED_DEPARTURES = 60

# Payments belong on the schedule, not the deadline list. The schedule raises its own
# deadlines (services/series/deadlines.py::specs_from_payment_schedule), so a payment date
# extracted as a deadline as well would appear twice on the timeline.
_PAYMENT_DEADLINES = {"ADVANCE_DEPOSIT", "DEPOSIT", "FINAL_PAYMENT", "DEPARTURE", "PENALTY_STEP"}
EXTRACTABLE_DEADLINES = tuple(t for t in DEADLINE_TYPES if t not in _PAYMENT_DEADLINES)


class ExtractionError(Exception):
    """The document could not be read at all. Carries a message fit for the user."""


# ══════════════════════════════════════════════════════════════════════════════
# READING THE PDF
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PageContent:
    number: int
    text: str | None
    image_jpeg: bytes | None


@dataclass
class PdfContent:
    pages: list[PageContent]
    page_count: int
    scanned_pages: int


def read_pdf(content: bytes, *, max_pages: int) -> PdfContent:
    """Split a PDF into per-page text, or a JPEG of the page when it has no text layer."""
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — any parse failure is the same answer
        raise ExtractionError("This file could not be opened as a PDF.") from exc
    if doc.needs_pass:
        raise ExtractionError("This PDF is password-protected. Remove the password and upload it again.")

    page_count = doc.page_count
    if page_count == 0:
        raise ExtractionError("This PDF has no pages.")
    if page_count > max_pages:
        raise ExtractionError(
            f"This PDF has {page_count} pages; contract reading is limited to {max_pages}. "
            f"Upload the agreement itself rather than the airline's full terms booklet."
        )

    pages: list[PageContent] = []
    scanned = 0
    for index, page in enumerate(doc, start=1):
        text = (page.get_text("text", sort=True) or "").strip()
        if len(text) >= MIN_TEXT_CHARS:
            pages.append(PageContent(index, text, None))
            continue
        scanned += 1
        long_edge = max(page.rect.width, page.rect.height) or 1
        zoom = min(2.5, RENDER_LONG_EDGE / long_edge)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        pages.append(PageContent(index, text or None, pix.tobytes("jpeg", jpg_quality=82)))
    doc.close()
    return PdfContent(pages=pages, page_count=page_count, scanned_pages=scanned)


def build_user_content(pdf: PdfContent, *, file_name: str, today: date) -> list[dict]:
    """The document as chat content parts, each page announced by its number so the model
    can cite it as evidence."""
    parts: list[dict] = [{
        "type": "text",
        "text": (
            f"Document: {file_name}\nPages: {pdf.page_count}\nToday's date: {today.isoformat()}\n"
            "Read every page below and return the JSON described in the instructions."
        ),
    }]
    for page in pdf.pages:
        if page.image_jpeg is not None:
            parts.append({"type": "text", "text": f"=== PAGE {page.number} (scanned image) ==="})
            encoded = base64.b64encode(page.image_jpeg).decode("ascii")
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}", "detail": "high"},
            })
        else:
            parts.append({"type": "text", "text": f"=== PAGE {page.number} ===\n{page.text}"})
    return parts


# ══════════════════════════════════════════════════════════════════════════════
# THE PROMPT
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a senior airline group-sales and travel-agency operations expert. \
You read airline group contracts, group quotations, series agreements, SIT / MICE group \
confirmations and B2B consolidator group offers, and you capture them for an Indian travel \
agency's back office. You return ONLY a JSON object matching the schema.

GOLDEN RULES
1. Extract only what the document says. A value that is not in the document is null — never \
guess, never use 0 for "unknown", never invent a fare, a date or a percentage.
2. For every important value you fill, add an `evidence` entry: the field path, the page number, \
and a SHORT verbatim quote (max ~20 words) from that page. Paths look like "header.contract_number", \
"departures[0].sectors[1].flight_number", "fare_components[2].amount_per_pax", \
"payment_schedule[0].due_date", "deadlines[1].stated_date".
3. Dates are YYYY-MM-DD. Date-times are YYYY-MM-DDTHH:MM in the local time printed. Read \
two-digit years and airline formats (30 Apr 25, 27/12/23, 15OCT) using today's date for context. \
Indian and European documents write DD/MM/YY.
4. Amounts are plain numbers without separators or currency ("38 760.00 INR" -> 38760). \
Percentages are numbers (5% -> 5).
5. Add a `notes_for_reviewer` item for anything ambiguous, contradictory, handwritten, cut off \
or illegible — the reviewer relies on these.

CLASSIFICATION
- contract_type: SERIES = the same space repeated on many dates across a season; GROUP = a \
one-off block for one departure (possibly with a return); SIT = special-interest group (pilgrimage, \
sports, school, tour-operator itinerary) — also when the document or a handwritten note says SIT; \
MICE = meetings / incentives / conferences / events. When unsure between GROUP and SIT choose GROUP.
- source_type: AIRLINE when the document is issued by the airline or its group desk; B2B when \
issued by a consolidator / wholesaler / B2B portal selling group or fixed-departure seats.
- doc_kind: QUOTATION (offer / request not yet confirmed), CONTRACT (agreement / confirmation), \
AMENDMENT, NAME_LIST, OTHER.

HEADER
- contract_number: the agreement / request / quotation number (e.g. "A 5854811-1/1", "GRP123003").
- group_reference: the group PNR or group reference / record locator if printed (e.g. "L64E9A").
- group_name: the group's name as printed (e.g. "DELATQDEL", "Direct Canada DEC").
- airline_code: 2-character IATA code of the operating airline (AF, AI, 6E, EK ...).
- supplier_name / supplier_ref: only for B2B documents — the consolidator and its reference.
- contracted_pax: the group size. minimum_pax: the minimum group size the fare needs. When the minimum is given per cabin \
("Economy - minimum 10 pax and maximum 99 pax per departure"), use the figures for the cabin \
this group is in (economy when not stated) for minimum_pax / maximum_pax.
- materialization_floor_pct: the minimum utilisation the group must reach (e.g. "minimum group \
materialisation should be 80%" -> 80).
- contract_date: the document / request / agreement date. option_expires_on: the date the offer \
lapses if not accepted (e.g. "signed copy ... together with the deposit ... no later than 06 January 2023").
- foc_per_paid: tour-conductor free seats, "1 free per 15 paid" -> 15. baggage_allowance as printed.
- If a cabin rule depends on cabin (economy / premium economy / business), set cabin to the cabin \
this group is actually booked in, if stated.

DEPARTURES AND SECTORS
- One departure per travel date block. A round trip booked as one group is ONE departure with \
two sectors: the outbound sector(s) direction OUTBOUND, the return sector(s) INBOUND.
- A CONNECTION is not a return. DEL-CDG then CDG-YYZ is two OUTBOUND legs of a one-way journey. \
Only legs that travel back towards the origin are INBOUND.
- flight_number includes the airline code, no spaces ("AF 225" -> "AF225", "AI-495" -> "AI495").
- rbd is the booking class letter ("Class U" -> "U").
- If the document describes a repeating series ("every Tue & Sat from 01 Nov to 31 Mar"), fill \
`series_pattern` and give ONE example departure — the system expands the dates itself.

FARE (per passenger)
Split the fare into components with these codes:
- BASE = net / base fare. YQ = carrier-imposed surcharge YQ, or "YR-I,YQ" when printed together.
- YR_I = carrier surcharge YR-I printed on its own. YR_F = Sustainable Fuel Contribution / YR-F.
- label: the line's own name exactly as printed ("Net fare per passenger", "Carrier-imposed \
international surcharge (YR-I,YQ)").
- TAX_STATUTORY = government / airport taxes (K3 GST, PSF, UDF, ASF...). OT = other charges. FEE = service fees.
- is_guaranteed_until_ticketing = the document says this element is guaranteed / frozen until \
ticketing ("only AI retention (Base + YQ) will freeze" -> BASE and YQ true; "taxes subject to change at \
date of ticketing" -> false).
- is_refundable_on_noshow = the document says this element is refunded on a no-show ("only statutory \
taxes are refundable" -> TAX_STATUTORY true). Both flags are false unless the document says so.
- fare_totals: copy any printed per-passenger total and group total so they can be cross-checked.
- Many group requests contain NO price. Then fare_components is an empty list.

PAYMENT SCHEDULE
- Every deposit / instalment / final payment with its amount and/or percentage and due date.
- kind: ADVANCE_DEPOSIT (the first deposit that confirms / firms the group), DEPOSIT (later \
deposits), BALANCE, FINAL_PAYMENT (full payment / final payment before ticketing).
- pct_basis — what a percentage is OF: NET_FARE (base fare only), AI_RETENTION (base + YQ, "airline \
retention"), FARE_PLUS_SURCHARGES (base + YQ + YR), TOTAL (everything incl. taxes), TAX_ONLY.
- due_offset_days: when the due date is written as "N days before departure".
- is_refundable: false when the deposit is forfeited on cancellation / "non-refundable", true when \
refundable, null when not stated.
- A final payment with no printed amount still gets a row (amount null) with its due date.

DEADLINES (not payments — payments live on the schedule)
deadline_type is one of: NAME_LIST (passenger name list due), TICKETING (tickets issued by), \
SEAT_RELEASE (last date to release seats free), NO_SHOW_CUTOFF (cancel at least N hours before \
departure to avoid no-show), DEVIATION_CUTOFF (last date for deviations), OPTION_EXPIRY.
Give offset_days (days BEFORE departure) and/or offset_hours, and stated_date when the document \
prints the actual date. Example: "no later than 30 days before departure date, which is 27 November \
2023" -> offset_days 30, stated_date 2023-11-27. A cut-off in hours stays in hours: "at least D-24 \
hours before departure" -> offset_hours 24, offset_days null.

TERMS — THE MOST IMPORTANT PART. Go through the conditions clause by clause, line by line, and \
capture EVERY clause that prices, permits, forbids or limits a change as its own row. Airline group \
conditions routinely produce 15-30 rows; a short list usually means clauses were skipped. Before \
answering, re-read every page and check each of these was captured if present: total cancellation \
bands, partial cancellation bands (free quota AND over-quota charge), seat release / attrition \
allowances, name correction before ticketing, name replacement after ticketing (quota and fee grid), \
ticket cancellation fee grid, deviation / re-routing quota and fee grid, reissue fees, no-show, \
refunds of unused or partly used tickets, below-materialisation consequence, deposit forfeiture.
- rule_type: CANCELLATION (cancelling seats / the group — "total cancellation" is scope GROUP, \
"partial cancellation" is scope PARTIAL), SEAT_RELEASE (only for clauses worded as seat release / \
reduction / attrition allowance), NAME_CHANGE (name correction / replacement), DEVIATION (date / routing change \
of part of the group), REISSUE (reissue charges), NO_SHOW, REFUND (what is refunded on unused / \
partly used tickets), MATERIALIZATION (consequence of falling below the materialisation floor).
- scope: GROUP (whole group / "total cancellation"), PARTIAL (some seats / "partial cancellation" / \
per-departure quota), PER_PAX (a per-passenger fee).
- phase: ANY, BEFORE_DEPOSIT, AFTER_DEPOSIT_BEFORE_FINAL, AFTER_FINAL_PAYMENT, BEFORE_TICKETING, \
AFTER_TICKETING.
- Window in days before departure, both ends inclusive: days_before_max = far edge, days_before_min = \
near edge, null = open. "Up to 121 days prior" -> max null, min 121. "From 120 to 101 days prior" -> \
max 120, min 101. "From 30 days prior to departure" -> max 30, min 0.
- Quotas: share_min_pct / share_max_pct of the seats the rule covers. "20% of seats can be cancelled \
without penalty. Over and above: penalty of 5%" -> TWO rows: FREE with share 0-20, and PCT_OF_BASIS 5 \
with share_min_pct 20.
- Date-banded tables: read each band's line on its own and keep its numbers with ITS date range. \
Never shift a percentage to a neighbouring band. When a band has both a free quota and an over-quota \
charge, it becomes two rows with the same days_before_max / days_before_min.
- "before ticketing" -> phase BEFORE_TICKETING; "after ticketing" / "after ticket issue" -> \
AFTER_TICKETING; "after advance deposit and before final payment" -> AFTER_DEPOSIT_BEFORE_FINAL. \
Leave the day window null when the clause gives none.
- charge_type: FREE, PCT_OF_BASIS (charge_value % of charge_basis per affected seat), FIXED_PER_PAX, \
FIXED_TOTAL, DEPOSIT_FORFEIT, NON_REFUNDABLE, TAXES_ONLY_REFUNDABLE, FARE_DIFFERENCE, NOT_PERMITTED.
- charge_basis uses the same values as pct_basis. "% of the fare" on a document whose deposits are \
computed on the net fare means NET_FARE. "AI retention" means AI_RETENTION.
- A grid priced per cabin (Economy 4000 / Premium Economy 6000 / Business 9000) becomes one row per \
cabin with `cabin` set — and every separate grid (name replacement, ticket cancellation, deviation) \
gets its own rows even when the numbers repeat. Domestic / international variants: put the variant \
in the description.
- "penalty will be 100% of AI retention" -> PCT_OF_BASIS, charge_value 100, charge_basis AI_RETENTION.
- plus_gst: true when GST / taxes are charged on top of the penalty.
- description: one short plain-English line. source_text: the clause verbatim (trimmed). source_page.

PASSENGERS: only if the document contains a passenger / name list. Otherwise an empty list.

SUMMARY: 2-4 sentences for the reviewer: what this document is, the group, the key money and the \
key risks (e.g. "No fare is quoted; penalties are per-cabin fixed amounts")."""


def _nullable(schema: dict) -> dict:
    kind = schema.get("type")
    out = dict(schema)
    out["type"] = [kind, "null"] if isinstance(kind, str) else kind
    if "enum" in out:
        out["enum"] = list(out["enum"]) + [None]
    return out


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


_S = {"type": "string"}
_I = {"type": "integer"}
_N = {"type": "number"}
_B = {"type": "boolean"}
S, I, N, B = (_nullable(x) for x in (_S, _I, _N, _B))


def _enum(values) -> dict:
    return _nullable({"type": "string", "enum": list(values)})


_BASES = tuple(bases.BASES)

_SECTOR = _obj({
    "direction": _enum(DIRECTIONS), "origin": S, "destination": S, "airline_code": S,
    "flight_number": S, "departure_at": S, "arrival_at": S, "cabin": _enum(CABINS), "rbd": S,
})

SCHEMA = {
    "name": "series_contract",
    "strict": True,
    "schema": _obj({
        "doc_kind": _enum(DOCUMENT_KINDS),
        "summary": S,
        "header": _obj({
            "contract_type": _enum(CONTRACT_TYPES),
            "source_type": _enum(SOURCE_TYPES),
            "contract_number": S, "group_reference": S, "group_name": S,
            "airline_code": S, "airline_name": S,
            "supplier_name": S, "supplier_ref": S,
            "currency": S,
            "contracted_pax": I, "minimum_pax": I, "maximum_pax": I,
            "materialization_floor_pct": N,
            "cabin": _enum(CABINS),
            "contract_date": S, "option_expires_on": S,
            "foc_per_paid": I, "baggage_allowance": S, "event_name": S,
        }),
        "departures": _arr(_obj({
            "departure_date": S, "requested_pax": I, "sectors": _arr(_SECTOR),
        })),
        # A nullable object is `anyOf` in strict mode; a type array is for scalars only.
        "series_pattern": {"anyOf": [_obj({
            "weekdays": _arr({"type": "string", "enum": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]}),
            "date_from": S, "date_to": S, "seats_per_departure": I,
        }), {"type": "null"}]},
        "fare_components": _arr(_obj({
            "component_code": _enum(COMPONENT_CODES), "label": S, "amount_per_pax": N,
            "is_guaranteed_until_ticketing": B, "is_refundable_on_noshow": B,
        })),
        "fare_totals": _obj({"per_pax_total": N, "group_total": N, "group_total_excluding_taxes": N}),
        "payment_schedule": _arr(_obj({
            "kind": _enum(PAYMENT_KINDS), "due_date": S, "due_offset_days": I,
            "amount": N, "pct": N, "pct_basis": _enum(_BASES), "is_refundable": B, "notes": S,
        })),
        "deadlines": _arr(_obj({
            "deadline_type": _enum(EXTRACTABLE_DEADLINES), "offset_days": I, "offset_hours": I,
            "stated_date": S, "action_required": S,
        })),
        "terms": _arr(_obj({
            "rule_type": _enum(TERM_RULE_TYPES), "scope": _enum(TERM_SCOPES), "phase": _enum(TERM_PHASES),
            "days_before_max": I, "days_before_min": I, "share_min_pct": N, "share_max_pct": N,
            "charge_type": _enum(TERM_CHARGE_TYPES), "charge_value": N, "charge_basis": _enum(_BASES),
            "cabin": _enum(CABINS), "plus_gst": B,
            "description": S, "source_text": S, "source_page": I,
        })),
        "passengers": _arr(_obj({
            "title": S, "first_name": S, "last_name": S, "pax_type": _enum(PAX_TYPES),
            "gender": S, "date_of_birth": S, "nationality": S,
            "passport_number": S, "passport_expiry": S,
        })),
        "evidence": _arr(_obj({"field": _S, "page": I, "quote": S})),
        "notes_for_reviewer": _arr(_S),
    }),
}


# ══════════════════════════════════════════════════════════════════════════════
# NORMALISATION — pure, and what the tests pin
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Draft:
    header: dict = field(default_factory=dict)
    allocations: list[dict] = field(default_factory=list)
    fare_components: list[dict] = field(default_factory=list)
    payment_schedule: list[dict] = field(default_factory=list)
    deadlines: list[dict] = field(default_factory=list)
    terms: list[dict] = field(default_factory=list)
    passengers: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    warnings: list[dict] = field(default_factory=list)
    summary: str | None = None
    doc_kind: str | None = None

    def warn(self, level: str, field_path: str | None, message: str) -> None:
        self.warnings.append({"level": level, "field": field_path, "message": message})

    def as_dict(self) -> dict:
        return {
            "header": self.header,
            "allocations": self.allocations,
            "fare_components": self.fare_components,
            "payment_schedule": self.payment_schedule,
            "deadlines": self.deadlines,
            "terms": self.terms,
            "passengers": self.passengers,
            "evidence": self.evidence,
            "warnings": self.warnings,
            "summary": self.summary,
            "doc_kind": self.doc_kind,
        }


def _clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _choice(value, allowed) -> str | None:
    text = (_clean(value) or "").upper().replace(" ", "_").replace("-", "_")
    return text if text in allowed else None


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(Decimal(text)) if text not in ("", "-", ".") else None
    except InvalidOperation:
        return None


def _int(value) -> int | None:
    number = _num(value)
    return int(round(number)) if number is not None else None


def _date(value) -> date | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d %b %Y", "%d %b %y", "%d %B %Y", "%d%b%y", "%d%b%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _datetime(value) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace(" ", "T")[:16])
    except ValueError:
        only_date = _date(text)
        return datetime.combine(only_date, datetime.min.time()) if only_date else None


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M")
    return value.isoformat()


def _code(value, length: int) -> str | None:
    text = re.sub(r"[^A-Z0-9]", "", (_clean(value) or "").upper())
    return text[:length] or None


def _flight(value) -> str | None:
    text = re.sub(r"[\s\-]", "", (_clean(value) or "").upper())
    return text[:10] or None


def _close(a: float | None, b: float | None, tolerance: float = 1.0) -> bool:
    return a is None or b is None or abs(a - b) <= tolerance


_WEEKDAY_INDEX = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


def expand_series(pattern: dict | None, template: dict | None) -> list[dict]:
    """Dated departures from a weekly pattern, each a copy of `template` moved to its date.

    Sector times are kept and their dates shifted by the same number of days as the
    departure, so a return leg two days after the outbound stays two days after it.
    """
    if not pattern:
        return []
    start, end = _date(pattern.get("date_from")), _date(pattern.get("date_to"))
    days = {_WEEKDAY_INDEX[d] for d in (pattern.get("weekdays") or []) if d in _WEEKDAY_INDEX}
    if not start or not end or not days or end < start:
        return []
    anchor = _date((template or {}).get("departure_date"))
    seats = _int(pattern.get("seats_per_departure")) or _int((template or {}).get("requested_pax"))

    out: list[dict] = []
    cursor = start
    while cursor <= end and len(out) < MAX_EXPANDED_DEPARTURES:
        if cursor.weekday() in days:
            shift = (cursor - anchor) if anchor else timedelta(0)
            sectors = []
            for sector in (template or {}).get("sectors") or []:
                moved = dict(sector)
                for key in ("departure_at", "arrival_at"):
                    at = _datetime(sector.get(key))
                    if at is not None:
                        moved[key] = _iso(at + shift) if anchor else _iso(
                            datetime.combine(cursor, at.time()))
                sectors.append(moved)
            out.append({"departure_date": cursor.isoformat(), "requested_pax": seats, "sectors": sectors})
        cursor += timedelta(days=1)
    return out


def normalize(raw: dict, *, today: date) -> Draft:
    """Turn the model's JSON into the review form's draft, with every check applied."""
    draft = Draft()
    raw = raw or {}
    draft.summary = _clean(raw.get("summary"))
    draft.doc_kind = _choice(raw.get("doc_kind"), DOCUMENT_KINDS) or "CONTRACT"

    for item in raw.get("evidence") or []:
        path = _clean(item.get("field"))
        # The model is told "departures"; the form calls them allocations.
        if path and path.startswith("departures"):
            path = "allocations" + path[len("departures"):]
        if path and path not in draft.evidence:
            draft.evidence[path] = {"page": _int(item.get("page")), "quote": _clean(item.get("quote"))}

    # ── header ────────────────────────────────────────────────────────────────
    h = raw.get("header") or {}
    source = _choice(h.get("source_type"), SOURCE_TYPES) or "AIRLINE"
    header = {
        "contract_type": _choice(h.get("contract_type"), CONTRACT_TYPES) or "GROUP",
        "source_type": source,
        "contract_number": _clean(h.get("contract_number")),
        "group_reference": _clean(h.get("group_reference")),
        "group_name": _clean(h.get("group_name")),
        "agent_name": _clean(h.get("supplier_name")) if source == "B2B" else None,
        "supplier_ref": _clean(h.get("supplier_ref")),
        "airline_code": _code(h.get("airline_code"), 3),
        "airline_name": _clean(h.get("airline_name")),
        "currency": (_code(h.get("currency"), 3) or "INR"),
        "contracted_pax": _int(h.get("contracted_pax")),
        "minimum_pax": _int(h.get("minimum_pax")),
        "materialization_floor_pct": _num(h.get("materialization_floor_pct")),
        "cabin": _choice(h.get("cabin"), CABINS) or "ECONOMY",
        "contract_date": _iso(_date(h.get("contract_date"))),
        "option_expires_on": _iso(_date(h.get("option_expires_on"))),
        "foc_per_paid": _int(h.get("foc_per_paid")),
        "baggage_allowance": _clean(h.get("baggage_allowance")),
        "event_name": _clean(h.get("event_name")),
        "notes": None,
    }
    if header["contract_number"] is None:
        draft.warn("warning", "header.contract_number",
                   "No contract or request number found — enter the one the airline will quote back.")
    if source == "B2B" and not header["agent_name"]:
        draft.warn("warning", "header.agent_name", "B2B document but the supplier's name was not found.")
    draft.header = header

    # ── departures ────────────────────────────────────────────────────────────
    departures = []
    for raw_dep in raw.get("departures") or []:
        sectors = []
        for seg_no, s in enumerate(raw_dep.get("sectors") or [], start=1):
            sectors.append({
                "segment_no": seg_no,
                "direction": _choice(s.get("direction"), DIRECTIONS) or ("OUTBOUND" if seg_no == 1 else None),
                "origin": _code(s.get("origin"), 3),
                "destination": _code(s.get("destination"), 3),
                "airline_code": _code(s.get("airline_code"), 3) or header["airline_code"],
                "flight_number": _flight(s.get("flight_number")),
                "departure_at": _iso(_datetime(s.get("departure_at"))),
                "arrival_at": _iso(_datetime(s.get("arrival_at"))),
                "cabin": _choice(s.get("cabin"), CABINS) or header["cabin"],
                "rbd": _code(s.get("rbd"), 4),
            })
        # A journey that never comes back to where it started has no inbound leg: CDG-YYZ
        # after DEL-CDG is a connection, whatever the model called it.
        if sectors and sectors[0]["origin"] and not any(
                s["destination"] == sectors[0]["origin"] for s in sectors):
            for s in sectors:
                s["direction"] = "OUTBOUND"
        dep_date = _date(raw_dep.get("departure_date"))
        if dep_date is None and sectors and sectors[0]["departure_at"]:
            dep_date = _date(sectors[0]["departure_at"])
        departures.append({
            "departure_date": _iso(dep_date),
            "requested_pax": _int(raw_dep.get("requested_pax")) or header["contracted_pax"],
            "sectors": sectors,
        })

    pattern = raw.get("series_pattern")
    if pattern and len(departures) <= 1:
        expanded = expand_series(pattern, departures[0] if departures else None)
        if expanded:
            departures = expanded
            header["contract_type"] = "SERIES"
            draft.warn("info", "allocations",
                       f"Expanded the series pattern into {len(expanded)} departures — check the "
                       f"dates against the airline's schedule, including blackout dates.")
            if len(expanded) >= MAX_EXPANDED_DEPARTURES:
                draft.warn("warning", "allocations",
                           f"Stopped at {MAX_EXPANDED_DEPARTURES} departures; the season is longer.")

    for index, dep in enumerate(departures):
        for s_index, sector in enumerate(dep["sectors"]):
            dep_at, arr_at = _datetime(sector["departure_at"]), _datetime(sector["arrival_at"])
            if dep_at and arr_at and arr_at < dep_at:
                draft.warn("info", f"allocations[{index}].sectors[{s_index}]",
                           f"{sector['origin']}→{sector['destination']} arrives before it departs "
                           f"in local times — normal across time zones, but check for a +1 day.")
        dep_date = _date(dep["departure_date"])
        if dep_date and dep_date < today:
            draft.warn("warning", f"allocations[{index}].departure_date",
                       f"Departure {dep_date:%d %b %Y} is in the past — is this an old contract?")

    if not departures:
        draft.warn("warning", "allocations", "No departure or flight details were found.")
    draft.allocations = departures

    seats = sum((d["requested_pax"] or 0) for d in departures) or (header["contracted_pax"] or 0)
    if header["contracted_pax"] and len(departures) == 1 and departures[0]["requested_pax"] \
            and departures[0]["requested_pax"] != header["contracted_pax"]:
        draft.warn("warning", "header.contracted_pax",
                   f"The group size ({header['contracted_pax']}) and the seats on the departure "
                   f"({departures[0]['requested_pax']}) disagree.")
    if header["minimum_pax"] and header["contracted_pax"] and header["minimum_pax"] > header["contracted_pax"]:
        draft.warn("warning", "header.minimum_pax", "The minimum group size is larger than the group.")

    # ── fare ──────────────────────────────────────────────────────────────────
    merged: dict[str, dict] = {}
    for c in raw.get("fare_components") or []:
        code = _choice(c.get("component_code"), COMPONENT_CODES)
        amount = _num(c.get("amount_per_pax"))
        if not code or amount is None:
            continue
        if code in merged:
            # Two tax lines are one TAX_STATUTORY component here; keep both labels.
            merged[code]["amount_per_pax"] = round(merged[code]["amount_per_pax"] + amount, 2)
            merged[code]["label"] = " + ".join(filter(None, [merged[code]["label"], _clean(c.get("label"))]))[:80] or None
            continue
        merged[code] = {
            "component_code": code,
            "label": (_clean(c.get("label")) or "")[:80] or None,
            "amount_per_pax": round(amount, 2),
            "is_guaranteed_until_ticketing": bool(c.get("is_guaranteed_until_ticketing")),
            "is_refundable_on_noshow": bool(c.get("is_refundable_on_noshow")),
        }
    draft.fare_components = [merged[c] for c in COMPONENT_CODES if c in merged]
    per_pax = round(sum(c["amount_per_pax"] for c in draft.fare_components), 2)

    totals = raw.get("fare_totals") or {}
    if not draft.fare_components:
        draft.warn("warning", "fare_components",
                   "No fare is quoted in this document — enter it from the airline's price "
                   "confirmation, or penalties and deposits cannot be priced.")
    else:
        stated_pp = _num(totals.get("per_pax_total"))
        if stated_pp is not None and not _close(per_pax, stated_pp):
            draft.warn("warning", "fare_components",
                       f"Fare components add up to {per_pax:,.2f} per passenger but the document "
                       f"prints {stated_pp:,.2f}.")
        stated_total = _num(totals.get("group_total"))
        if stated_total is not None and seats and not _close(per_pax * seats, stated_total, max(1.0, seats * 0.5)):
            draft.warn("warning", "fare_components",
                       f"{per_pax:,.2f} × {seats} seats = {per_pax * seats:,.2f}, but the document's "
                       f"group total is {stated_total:,.2f}. Check the seat count and each component.")

    # ── payment schedule ──────────────────────────────────────────────────────
    basis_totals = _basis_totals(draft.fare_components, seats)
    first_departure = min((_date(d["departure_date"]) for d in departures if d["departure_date"]), default=None)
    schedule = []
    for index, row in enumerate(raw.get("payment_schedule") or []):
        entry = {
            "kind": _choice(row.get("kind"), PAYMENT_KINDS) or ("ADVANCE_DEPOSIT" if index == 0 else "DEPOSIT"),
            "due_date": _iso(_date(row.get("due_date"))),
            "due_offset_days": _int(row.get("due_offset_days")),
            "amount": _num(row.get("amount")),
            "pct": _num(row.get("pct")),
            "pct_basis": _choice(row.get("pct_basis"), _BASES),
            "is_refundable": row.get("is_refundable") if isinstance(row.get("is_refundable"), bool) else None,
            "notes": (_clean(row.get("notes")) or "")[:300] or None,
        }
        if entry["due_date"] is None and entry["due_offset_days"] is not None and first_departure:
            entry["due_date"] = _iso(first_departure - timedelta(days=entry["due_offset_days"]))
        _reconcile_percentage(entry, basis_totals, draft, f"payment_schedule[{index}]")
        schedule.append(entry)
    draft.payment_schedule = schedule
    if not schedule:
        draft.warn("info", "payment_schedule", "No deposit or payment schedule was found in the document.")

    # ── deadlines ─────────────────────────────────────────────────────────────
    deadlines = []
    for index, row in enumerate(raw.get("deadlines") or []):
        kind = _choice(row.get("deadline_type"), EXTRACTABLE_DEADLINES)
        if not kind:
            continue
        entry = {
            "deadline_type": kind,
            "anchor": "DEPARTURE",
            "offset_days": _int(row.get("offset_days")),
            "offset_hours": _int(row.get("offset_hours")),
            "stated_date": _iso(_date(row.get("stated_date"))),
            "action_required": (_clean(row.get("action_required")) or "")[:200] or None,
        }
        if entry["offset_days"] is None and entry["offset_hours"] is None and entry["stated_date"] is None:
            continue
        if entry["stated_date"] and entry["offset_days"] is not None and first_departure and len(departures) == 1:
            computed = first_departure - timedelta(days=entry["offset_days"])
            if computed != _date(entry["stated_date"]):
                draft.warn("warning", f"deadlines[{len(deadlines)}]",
                           f"{kind.replace('_', ' ').title()}: the document says {entry['offset_days']} "
                           f"days before departure ({computed:%d %b %Y}) but prints "
                           f"{_date(entry['stated_date']):%d %b %Y}. The printed date is used.")
        deadlines.append(entry)
    if header["option_expires_on"] and not any(d["deadline_type"] == "OPTION_EXPIRY" for d in deadlines):
        deadlines.append({
            "deadline_type": "OPTION_EXPIRY", "anchor": "CONTRACT_DATE", "offset_days": None,
            "offset_hours": None, "stated_date": header["option_expires_on"], "action_required": None,
        })
    draft.deadlines = deadlines

    # ── terms ─────────────────────────────────────────────────────────────────
    terms = []
    for index, t in enumerate(raw.get("terms") or []):
        rule = _choice(t.get("rule_type"), TERM_RULE_TYPES)
        charge = _choice(t.get("charge_type"), TERM_CHARGE_TYPES)
        if not rule or not charge:
            continue
        entry = {
            "rule_type": rule,
            "scope": _choice(t.get("scope"), TERM_SCOPES),
            "phase": _choice(t.get("phase"), TERM_PHASES) or "ANY",
            "days_before_max": _int(t.get("days_before_max")),
            "days_before_min": _int(t.get("days_before_min")),
            "share_min_pct": _num(t.get("share_min_pct")),
            "share_max_pct": _num(t.get("share_max_pct")),
            "charge_type": charge,
            "charge_value": _num(t.get("charge_value")),
            "charge_basis": _choice(t.get("charge_basis"), _BASES),
            "cabin": _choice(t.get("cabin"), CABINS),
            "plus_gst": bool(t.get("plus_gst")),
            "description": (_clean(t.get("description")) or "")[:300] or None,
            "source_text": (_clean(t.get("source_text")) or "")[:1000] or None,
            "source_page": _int(t.get("source_page")),
        }
        lo, hi = entry["days_before_min"], entry["days_before_max"]
        if lo is not None and hi is not None and lo > hi:
            entry["days_before_min"], entry["days_before_max"] = hi, lo
        if charge == "PCT_OF_BASIS":
            if entry["charge_value"] is None:
                draft.warn("warning", f"terms[{len(terms)}]", "A percentage penalty was found without its percentage.")
            if entry["charge_basis"] is None:
                entry["charge_basis"] = "NET_FARE"
                draft.warn("warning", f"terms[{len(terms)}]",
                           f"\"{entry['description'] or rule.title()}\": the base of the percentage "
                           f"was not stated; assumed net fare. Check it.")
        terms.append(entry)
    _check_bands(terms, draft)
    if not any(t["rule_type"] == "CANCELLATION" for t in terms):
        draft.warn("warning", "terms", "No cancellation terms were found — check the airline's group conditions.")
    draft.terms = terms

    # ── passengers ────────────────────────────────────────────────────────────
    passengers = []
    horizon = (first_departure or today) + timedelta(days=182)
    for index, p in enumerate(raw.get("passengers") or []):
        first, last = _clean(p.get("first_name")), _clean(p.get("last_name"))
        if not first and not last:
            continue
        pax_type = _choice(p.get("pax_type"), PAX_TYPES) or "ADT"
        entry = {
            "title": _clean(p.get("title")),
            "first_name": first,
            "last_name": last,
            "pax_type": pax_type,
            "gender": _clean(p.get("gender")),
            "date_of_birth": _iso(_date(p.get("date_of_birth"))),
            "nationality": _clean(p.get("nationality")),
            "passport_number": _code(p.get("passport_number"), 50),
            "passport_expiry": _iso(_date(p.get("passport_expiry"))),
        }
        expiry = _date(entry["passport_expiry"])
        if expiry and expiry < horizon:
            draft.warn("warning", f"passengers[{len(passengers)}]",
                       f"{first or ''} {last or ''}: passport expires {expiry:%d %b %Y}, less than six "
                       f"months after travel.")
        passengers.append(entry)
    if passengers and seats and len(passengers) > seats:
        draft.warn("warning", "passengers",
                   f"{len(passengers)} names for {seats} seats — more names than the group holds.")
    draft.passengers = passengers

    for note in raw.get("notes_for_reviewer") or []:
        text = _clean(note)
        if text:
            draft.warn("info", None, text[:300])
    return draft


def _basis_totals(components: list[dict], seats: int) -> dict[str, float]:
    """Contract-level total per basis — the same arithmetic the form shows."""
    if not seats:
        return {}
    out = {}
    for basis, codes in bases.BASIS_COMPONENTS.items():
        per = sum(c["amount_per_pax"] for c in components if c["component_code"] in codes)
        if per:
            out[basis] = round(per * seats, 2)
    return out


def _reconcile_percentage(entry: dict, basis_totals: dict[str, float], draft: Draft, path: str) -> None:
    """Explain an instalment's amount as a round percentage of a basis, or flag a mismatch.

    Air France prints 38,760 and 193,800 and no percentage at all. Both are exact round
    shares of the net-fare total (5% and 25% of 775,200) — recovering that is what keeps
    the schedule right after the fare is renegotiated. Only a whole or half percentage is
    accepted as an explanation; anything else is a coincidence.
    """
    amount, pct, basis = entry["amount"], entry["pct"], entry["pct_basis"]
    if amount is not None and pct is not None and basis and basis_totals.get(basis):
        expected = basis_totals[basis] * pct / 100
        if not _close(amount, expected, max(1.0, expected * 0.005)):
            draft.warn("warning", path,
                       f"{pct:g}% of the {basis.replace('_', ' ').lower()} total is {expected:,.2f}, "
                       f"but the document asks for {amount:,.2f}.")
        return
    if amount is not None and pct is None and basis_totals:
        for candidate in ("NET_FARE", "AI_RETENTION", "FARE_PLUS_SURCHARGES", "TOTAL"):
            total = basis_totals.get(candidate)
            if not total:
                continue
            share = amount / total * 100
            if share > 0 and abs(share * 2 - round(share * 2)) < 0.002:
                entry["pct"] = round(share * 2) / 2
                entry["pct_basis"] = candidate
                draft.warn("info", path,
                           f"{amount:,.2f} is exactly {entry['pct']:g}% of the "
                           f"{candidate.replace('_', ' ').lower()} total — recorded as a percentage "
                           f"so it follows the fare if it changes.")
                return


def _check_bands(terms: list[dict], draft: Draft) -> None:
    """Group-cancellation bands must not overlap: an overlap means two prices for one day."""
    bands = [
        (i, t) for i, t in enumerate(terms)
        if t["rule_type"] == "CANCELLATION" and (t["scope"] or "GROUP") == "GROUP"
        and t["phase"] != "AFTER_TICKETING"
        and (t["days_before_min"] is not None or t["days_before_max"] is not None)
    ]
    for a in range(len(bands)):
        for b in range(a + 1, len(bands)):
            (ia, ta), (ib, tb) = bands[a], bands[b]
            if ta["cabin"] != tb["cabin"]:
                continue
            a_lo, a_hi = ta["days_before_min"] or 0, ta["days_before_max"] if ta["days_before_max"] is not None else 10_000
            b_lo, b_hi = tb["days_before_min"] or 0, tb["days_before_max"] if tb["days_before_max"] is not None else 10_000
            if a_lo <= b_hi and b_lo <= a_hi:
                draft.warn("warning", f"terms[{ib}]",
                           f"Cancellation bands overlap ({a_lo}–{a_hi} and {b_lo}–{b_hi} days before "
                           f"departure). Check the day ranges.")


# ══════════════════════════════════════════════════════════════════════════════
# THE CALL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExtractionResult:
    draft: Draft
    page_count: int
    scanned_pages: int
    model: str
    duration_ms: int


async def extract(content: bytes, *, file_name: str, today: date) -> ExtractionResult:
    """Read the PDF, ask the model, normalise. Raises ExtractionError with a user-facing
    message when the document cannot be read, and lets provider errors propagate."""
    import asyncio

    from app.config import settings
    from app.services import ai_client

    started = time.monotonic()
    pdf = await asyncio.to_thread(read_pdf, content, max_pages=settings.SERIES_AI_MAX_PAGES)
    model = settings.SERIES_AI_MODEL or settings.OPENAI_MODEL
    client = ai_client.build_client()
    raw_text = await ai_client.call_json(
        client,
        system_prompt=SYSTEM_PROMPT,
        user_content=build_user_content(pdf, file_name=file_name, today=today),
        schema=SCHEMA,
        max_tokens=(settings.SERIES_AI_MAX_OUTPUT_TOKENS if ai_client.is_reasoning_model(model)
                    else min(settings.SERIES_AI_MAX_OUTPUT_TOKENS, 16000)),
        label="series-extract",
        model=model,
        reasoning_effort=settings.SERIES_AI_REASONING_EFFORT or None,
    )
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.warning("series-extract unreadable output file=%s head=%r", file_name, raw_text[:300])
        raise ExtractionError(
            "The AI's answer could not be read (it may have been cut off). Try again, or fill "
            "the form by hand — the PDF is saved either way."
        ) from exc

    draft = normalize(raw, today=today)
    if pdf.scanned_pages:
        draft.warn("info", None,
                   f"{pdf.scanned_pages} of {pdf.page_count} page(s) were photographs or scans and were "
                   f"read as images. Check small print, handwriting and numbers carefully.")
    duration = int((time.monotonic() - started) * 1000)
    logger.info(
        "series-extract done file=%s pages=%s scanned=%s deps=%s fare=%s terms=%s warnings=%s ms=%s",
        file_name, pdf.page_count, pdf.scanned_pages, len(draft.allocations),
        len(draft.fare_components), len(draft.terms), len(draft.warnings), duration,
    )
    return ExtractionResult(draft, pdf.page_count, pdf.scanned_pages, model, duration)
