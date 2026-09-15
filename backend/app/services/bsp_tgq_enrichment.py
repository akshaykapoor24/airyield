"""BSP settlement row → TGQ HMPR ticket detail, joined on (airline code, ticket no).

A BSP settlement statement prints no cabin class, no sector and no travel date, so the
commission engine has to skip every criterion that depends on them. The TGQ HMPR statement
prints all three — and since ``sector_split.split_ticket_no`` lifted the 3-digit IATA
accounting code out of the TGQ ``Ticket_No`` cell, the two join with no transformation::

    tgq_hmpr.data->>'airline_code'  ==  bsp_statement_rows.airline_accounting_code   # "098"
    tgq_hmpr.data->>'ticket_no'     ==  bsp_statement_rows.document_number           # "5805708071"

Join on ``document_number``, never ``ticket_number``: ``bsp_pdf_parser.derive_ticket_number``
deliberately NULLs the latter for EMD/ACM/ADM and ``00…``/``40…`` refunds.

TGQ holds one row per flown SECTOR, so BSP-document → TGQ is 1:N. The legs are folded back
into ONE journey (``journey_chain``) because that is what the deal engine and
``exclusion_evaluator`` are written to consume — the evaluator reads ``parts[0]`` as the
origin and ``parts[-1]`` as the destination, so a return ticket must not arrive as a one-way.

Everything here fails closed. A sector that does not parse, a travel date whose year cannot
be established, a conjunction range that looks implausible — each yields ``None`` and the
row keeps that criterion in its skipped list. A guessed route or a fabricated year would
silently move money.

REPORT MODE (``load_tgq_index(..., report_mode=True)``) is the Workspace report download's
opt-in variant. It additionally carries passenger / PNR / flight / fare-basis detail, reads
the uploads newest-first in a deterministic order, streams instead of buffering, caps at a
whole-batch boundary and records how much it loaded — so a report can say on its Read Me
exactly which TGQ coverage its enrichment had. The commission engine never sets it, and every
default argument reproduces the original query and index byte for byte.
"""
from __future__ import annotations

import logging
import re
from collections import namedtuple
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.models.statement_row import TgqHmpr
from app.services import sector_split
from app.services.bsp_reconciliation import norm_tn

logger = logging.getLogger(__name__)

SOURCE_TGQ = "tgq_hmpr"

# A real document serial. Also the guard that keeps a statement's grand-total line out of
# the index: `tgq_split_01` gave `is_total` a false server_default and did NOT backfill, so
# a batch imported before the split still reads false — but its total line has no ticket no.
_SERIAL_RE = re.compile(r"^\d{9,11}$")
# "5800920932-933" — one TGQ line, several BSP documents.
_CONJ_RE = re.compile(r"^(\d{9,11})\s*-\s*(\d{1,11})$")
# "28APR" / "28 APR"
_DDMMM_RE = re.compile(r"^(\d{1,2})\s*([A-Z]{3})$")
# "23APR26" / "23APR2026"
_DDMMMYY_RE = re.compile(r"^(\d{1,2})\s*([A-Z]{3})\s*(\d{2}|\d{4})$")

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

# A conjunction covers a handful of coupons, never a wide span. Anything wider is a parse
# artefact, and inventing serials would join this ticket to somebody else's.
MAX_CONJUNCTION_SPAN = 15
# Travel is normally on or after issue, but a day or two either way is ordinary data entry —
# only a clear backwards jump means the trip rolls into the next year.
TRAVEL_ROLL_GRACE = timedelta(days=3)
# Backstop so a pathological tenant can't build an unbounded in-memory index.
MAX_TGQ_ROWS = 200_000
# Report mode fetches this many rows per server-side-cursor round trip. Large enough that a
# 600k-row index is ~30 round trips; small enough that one buffered chunk stays a few MB.
REPORT_FETCH_SIZE = 20_000

# How `TgqIndex.match` found a ticket — surfaced on the report as "TGQ Enriched = Yes (<method>)".
MATCH_DOCUMENT = "document"        # (code, document_number) exactly
MATCH_CONJUNCTION = "conjunction"  # via an alternate / conjunction document of the row
MATCH_RTDN = "rtdn"                # via a related document (RTDN, exchanged-for) of the row
MATCH_NORMALISED = "normalised"    # (code, norm_tn(document_number)), claimed by one ticket only
MATCH_CODELESS = "codeless"        # row has no airline code; serial claimed by one code only


# ── Pure helpers ────────────────────────────────────────────────────────────

def journey_chain(legs: list[str | None]) -> str | None:
    """``['BOM/DEL','DEL/MNL','MNL/DEL','DEL/BOM']`` → ``'BOM/DEL/MNL/DEL/BOM'``.

    Consecutive legs are welded at the shared airport; a gap (a surface sector the passenger
    covered by other means) keeps both endpoints, so the chain still starts at the true
    origin and ends at the true destination. Any leg that is not ``AAA/BBB`` aborts the whole
    chain — a partially-understood route is worse than none.
    """
    points: list[str] = []
    for leg in legs:
        origin, _, dest = (leg or "").strip().upper().partition("/")
        if len(origin) != 3 or len(dest) != 3 or not origin.isalpha() or not dest.isalpha():
            return None
        if not points:
            points.append(origin)
        elif points[-1] != origin:
            points.append(origin)
        points.append(dest)
    return "/".join(points) if len(points) >= 2 else None


def distinct_classes(codes: list[str | None]) -> str | None:
    """``['L','L','U','U']`` → ``'L/U'`` — ordered-unique, the shape
    ``deal_matching._resolve_cabin_groups`` already splits on."""
    out: list[str] = []
    for c in codes:
        code = (c or "").strip().upper()
        if code and code not in out:
            out.append(code)
    return "/".join(out) if out else None


def _parse_anchor(raw: str | None) -> date | None:
    """A TGQ ``Ticket_Date`` (``'23APR26'``) or an ISO date → date."""
    s = (raw or "").strip().upper()
    if not s:
        return None
    m = _DDMMMYY_RE.match(s)
    if m:
        day, mon, yr = int(m.group(1)), _MONTHS.get(m.group(2)), int(m.group(3))
        if mon:
            year = yr + 2000 if yr < 100 else yr
            try:
                return date(year, mon, day)
            except ValueError:
                return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def resolve_travel_date(
    traveldt: str | None,
    ticket_date: str | None,
    issue_date: date | None,
) -> tuple[date | None, str | None]:
    """TGQ prints ``TravelDt`` with no year. Returns ``(date, 'explicit'|'inferred')``.

    The anchor is the ticket's own issue date — TGQ's ``Ticket_Date`` when readable, else the
    BSP ``issue_date``. Travel is on or after issue, so a candidate landing clearly before the
    anchor rolls into the next year: issued 23DEC26 travelling 05JAN → 2027-01-05. The grace
    stops a one-day slip from fabricating a whole year.

    Returns ``(None, None)`` when the token or the anchor can't be read. A bare ``'28APR'`` is
    never handed to dateutil — with no year it silently assumes *today's*, which is exactly
    the kind of quiet guess this pipeline refuses.
    """
    s = (traveldt or "").strip().upper()
    if not s:
        return None, None

    explicit = _parse_anchor(s)
    if explicit is not None:
        return explicit, "explicit"

    m = _DDMMM_RE.match(s)
    if not m:
        return None, None
    day, mon = int(m.group(1)), _MONTHS.get(m.group(2))
    if not mon:
        return None, None

    anchor = _parse_anchor(ticket_date) or issue_date
    if anchor is None:
        return None, None

    for year in (anchor.year, anchor.year + 1):
        try:
            candidate = date(year, mon, day)
        except ValueError:
            continue          # 29FEB in a non-leap year — try the next
        if candidate >= anchor - TRAVEL_ROLL_GRACE:
            return candidate, "inferred"
    return None, None


def expand_conjunction(serial: str | None) -> list[str]:
    """``'5800920932-933'`` → ``['5800920932','5800920933']``.

    A conjunction ticket is one TGQ line but several BSP documents. The tail is the trailing
    digits of the end serial. Fails closed — a span wider than ``MAX_CONJUNCTION_SPAN`` or a
    tail below the head returns ``[]`` and the raw string is indexed verbatim instead, because
    a fabricated serial would join this ticket to a different one.
    """
    m = _CONJ_RE.match((serial or "").strip())
    if not m:
        return []
    head, tail = m.group(1), m.group(2)
    try:
        start = int(head)
        end = int(head[: len(head) - len(tail)] + tail) if len(tail) < len(head) else int(tail)
    except ValueError:
        return []
    if end < start or end - start > MAX_CONJUNCTION_SPAN:
        return []
    width = len(head)
    return [str(n).zfill(width) for n in range(start, end + 1)]


# ── The aggregate ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TgqTicket:
    """One BSP document's worth of TGQ detail, folded from its N flown sectors.

    The travel date stays UNRESOLVED here. TGQ prints the first leg as ``'14MAY'`` with no
    year, and the year has to be inferred from the issue date — but the authoritative issue
    date is the BSP settlement's own ``issue_date``, not TGQ's ``Ticket_Date``. The latter is
    only a fallback: pandas turns date-formatted Excel cells into Timestamps, so a real file
    can carry a mix of ``'23APR26'`` and ``'2026-07-01 00:00:00'``, and anchoring on a wrong
    one silently shifts a trip by a year. Hence ``resolve_travel(bsp_issue_date)``.

    The trailing fields are filled in report mode only and stay None for the commission
    engine, which neither loads nor reads them.
    """
    sector:          str | None       # 'BOM/DEL/MNL/DEL/BOM'
    booking_class:   str | None       # 'L/U'
    travel_raw:      str | None       # first leg's TravelDt token, verbatim ('14MAY')
    ticket_date_raw: str | None       # TGQ Ticket_Date, the fallback anchor
    leg_count:       int
    batch_id:        str | None
    pax_name:        str | None = None   # first leg's Pax_Name
    air_pnr:         str | None = None   # first leg's Air_PNR (airline record locator)
    gal_pnr:         str | None = None   # first leg's Gal_PNR (GDS record locator)
    flight_numbers:  str | None = None   # 'AI-2928/AI-2362' — legs in flown order
    fare_basis:      str | None = None   # ordered-unique over the legs, '/'-joined

    def resolve_travel(self, issue_date: date | None) -> tuple[date | None, str | None]:
        """Travel date for this ticket, anchored on the BSP issue date when there is one."""
        if self.travel_raw is None:
            return None, None
        anchor_raw = issue_date.isoformat() if issue_date else self.ticket_date_raw
        return resolve_travel_date(self.travel_raw, anchor_raw, issue_date)


def _doc_text(doc: Any) -> str:
    """A document cell as a stripped string ('' for blank). JSONB lists can hold numbers."""
    if doc is None:
        return ""
    return doc.strip() if isinstance(doc, str) else str(doc).strip()


class TgqIndex:
    """(airline accounting code, document serial) → TgqTicket, resolved once per run.

    ``by_serial`` (report mode) maps a bare serial to its ticket for rows that carry no
    airline code — legacy BSP Excel rows. A serial two airlines both issued maps to None,
    which ``match`` treats as a miss: a codeless join is only made when it cannot be wrong.

    ``truncated`` / ``rows_loaded`` / ``batches_used`` describe what ``load_tgq_index`` read,
    so a report can disclose partial enrichment instead of implying full coverage.
    """

    def __init__(self, exact: dict, norm: dict, *, by_serial: dict | None = None):
        self._exact = exact
        self._norm = norm
        self._by_serial = by_serial
        self.truncated: bool = False
        self.rows_loaded: int = 0
        self.batches_used: int = 0

    def __len__(self) -> int:
        return len(self._exact)

    def lookup(
        self,
        accounting_code: str | None,
        document_number: str | None,
        alt_documents: list | None = None,
    ) -> TgqTicket | None:
        """The commission engine's join: exact document, then alternates, then normalised."""
        return self.match(accounting_code, document_number, alt_documents)[0]

    def match(
        self,
        code: str | None,
        document: str | None,
        alt_documents: Iterable | None = None,
        *,
        extra_documents: Iterable = (),
        allow_codeless: bool = False,
    ) -> tuple[TgqTicket | None, str | None]:
        """``(ticket, method)`` or ``(None, None)``; method is one of the ``MATCH_*`` values.

        With a code, the probes run from strongest to weakest evidence: the row's own document,
        its alternate/conjunction documents, its related documents (``extra_documents`` — a
        refund's RTDN, an exchange's original), and last the normalised document, only when a
        single ticket claims that normalisation. Called with just the first three arguments
        this is exactly ``lookup``.

        Without a code nothing is joined unless ``allow_codeless``; then each document is
        tried as a bare serial against ``by_serial``. The first serial two airlines share
        ends the search with a miss rather than moving on to a weaker probe — the ambiguity
        says this row cannot be placed, not that another of its documents should decide.
        """
        alts = list(alt_documents or [])
        extras = list(extra_documents or [])
        c = (code or "").strip().upper()
        if c.isdigit():
            c = c.zfill(3)

        if not c:
            if not allow_codeless or not self._by_serial:
                return None, None
            for doc in (document, *alts, *extras):
                key = _doc_text(doc)
                if not key or key not in self._by_serial:
                    continue
                hit = self._by_serial[key]
                return (hit, MATCH_CODELESS) if hit is not None else (None, None)
            return None, None

        for docs, method in (([document], MATCH_DOCUMENT), (alts, MATCH_CONJUNCTION),
                             (extras, MATCH_RTDN)):
            for doc in docs:
                key = _doc_text(doc)
                if key and (hit := self._exact.get((c, key))) is not None:
                    return hit, method

        # Last resort: compare on the normalised serial, and only when exactly one ticket
        # claims it — an ambiguous normalisation must never produce a confident wrong join.
        key = norm_tn(document or "")
        hit = self._norm.get((c, key)) if key else None
        return (hit, MATCH_NORMALISED) if hit is not None else (None, None)


# `data` keys report mode adds, in column order; each is also the row attribute name.
_REPORT_FIELDS = ("pax_name", "air_pnr", "gal_pnr", "flightno", "fare_basis")
# Newest upload first; batch_id keeps one upload's legs contiguous when two share a timestamp,
# and id makes the order total — so the cap cuts the same rows on every run.
_REPORT_ORDER = (TgqHmpr.uploaded_at.desc(), TgqHmpr.batch_id.asc(), TgqHmpr.id.asc())


def _index_query(
    tenant_id: int,
    created_by_id: int,
    exclude_batch_ids: frozenset[str],
    report_mode: bool,
) -> Select:
    """The owner-scoped leg query. Columns 0-12 are the commission index's, in its order;
    report mode appends the five labelled detail columns (13-17)."""
    cols = [
        TgqHmpr.batch_id, TgqHmpr.uploaded_at, TgqHmpr.id,
        TgqHmpr.row_seq, TgqHmpr.sector_index, TgqHmpr.sector_count, TgqHmpr.split_status,
        TgqHmpr.data["airline_code"].astext,
        TgqHmpr.data["ticket_no"].astext,
        TgqHmpr.data["sectors"].astext,
        TgqHmpr.data["class"].astext,
        TgqHmpr.data["traveldt"].astext,
        TgqHmpr.data["ticket_date"].astext,
    ]
    if report_mode:
        cols += [TgqHmpr.data[f].astext.label(f) for f in _REPORT_FIELDS]
    stmt = select(*cols).where(
        TgqHmpr.tenant_id == tenant_id,
        TgqHmpr.created_by_id == created_by_id,
        TgqHmpr.is_total.is_(False),
    )
    if exclude_batch_ids:
        stmt = stmt.where(TgqHmpr.batch_id.notin_(sorted(exclude_batch_ids)))
    return stmt


# A report-mode leg held until the index is folded: the query row as a plain named tuple with
# the same positions, so the grouping and `_fold_legs` read it exactly like a driver Row.
_ReportLeg = namedtuple("_ReportLeg", (
    "batch_id", "uploaded_at", "id", "row_seq", "sector_index", "sector_count", "split_status",
    "airline_code", "ticket_no", "sectors", "cls", "traveldt", "ticket_date", *_REPORT_FIELDS,
))
# Positions whose values repeat across legs and tickets — upload id, upload time, split status,
# carrier, sector, class, the two date tokens, flight, fare basis.
_POOLED_POSITIONS = (0, 1, 6, 7, 9, 10, 11, 12, 16, 17)


def _compact(row: Sequence, pool: dict) -> _ReportLeg:
    """One driver row → a ``_ReportLeg`` whose repeating values are shared objects.

    The report index holds every leg up to the cap (600k by default) until it is folded, and a
    driver decodes each cell to a fresh object — the same 36-character upload id half a million
    times. Measured on a synthetic 120k-leg load this halves what the held legs cost (about
    970 → 470 bytes a leg). Only low-cardinality positions are pooled, so the pool stays small.
    """
    vals = list(row)
    for i in _POOLED_POSITIONS:
        v = vals[i]
        if v is not None:
            vals[i] = pool.setdefault(v, v)
    return _ReportLeg._make(vals)


def _take_until_cap(rows: list, chunk: Iterable, max_rows: int) -> bool:
    """Append ``chunk`` to ``rows``, stopping at the first batch boundary once ``max_rows``
    rows are held. Returns True when it stopped early (the index is truncated).

    The cap never splits an upload: half a batch would resolve some of its tickets from an
    older upload of the same ticket, the exact interleaving the batch ranking exists to stop.
    """
    for r in chunk:
        if rows and len(rows) >= max_rows and r.batch_id != rows[-1].batch_id:
            return True
        rows.append(r)
    return False


async def _fetch_report_rows(
    db: AsyncSession | AsyncConnection, stmt: Select, max_rows: int,
) -> tuple[list, bool]:
    """Report-mode rows in ``_REPORT_ORDER`` up to the batch-bounded cap → ``(rows, truncated)``.

    A server-side cursor when ``db`` can stream (AsyncSession and AsyncConnection both can),
    so the driver never buffers the whole result next to the rows kept. Anything else gets a
    keyset-paged fetch over the same total order, which reads the same rows.
    """
    ordered = stmt.order_by(*_REPORT_ORDER)
    rows: list[_ReportLeg] = []
    pool: dict = {}

    stream = getattr(db, "stream", None)
    if stream is not None:
        result = await stream(ordered.execution_options(yield_per=REPORT_FETCH_SIZE))
        try:
            # fetchmany, not `async for … in partitions()`: stopping at the cap then leaves no
            # half-consumed async generator behind, and the cursor is closed right here.
            while chunk := await result.fetchmany(REPORT_FETCH_SIZE):
                if _take_until_cap(rows, (_compact(r, pool) for r in chunk), max_rows):
                    return rows, True
        finally:
            await result.close()
        return rows, False

    last = None
    while True:
        page = ordered
        if last is not None:
            page = page.where(or_(
                TgqHmpr.uploaded_at < last.uploaded_at,
                and_(TgqHmpr.uploaded_at == last.uploaded_at, or_(
                    TgqHmpr.batch_id > last.batch_id,
                    and_(TgqHmpr.batch_id == last.batch_id, TgqHmpr.id > last.id),
                )),
            ))
        chunk = (await db.execute(page.limit(REPORT_FETCH_SIZE))).all()
        if _take_until_cap(rows, (_compact(r, pool) for r in chunk), max_rows):
            return rows, True
        if len(chunk) < REPORT_FETCH_SIZE:
            return rows, False
        last = chunk[-1]


async def load_tgq_index(
    db: AsyncSession | AsyncConnection,
    tenant_id: int,
    created_by_id: int,
    *,
    exclude_batch_ids: frozenset[str] = frozenset(),
    report_mode: bool = False,
    max_rows: int = MAX_TGQ_ROWS,
) -> TgqIndex:
    """Build the whole index from one query — the same discipline as
    ``bsp_commission._airline_name_map`` / ``_tax_totals``, so a run never goes N+1.

    Default arguments are the commission engine's index: one buffered fetch, ``LIMIT`` at the
    cap, class / sector / travel date only. ``report_mode`` adds the passenger / PNR / flight
    / fare-basis columns, a deterministic newest-first order, streaming, a cap that stops at a
    whole-batch boundary, identity-only tickets for rows with no usable sector, and the
    codeless serial map. ``exclude_batch_ids`` drops uploads the user unticked.
    """
    stmt = _index_query(tenant_id, created_by_id, exclude_batch_ids, report_mode)
    if report_mode:
        rows, truncated = await _fetch_report_rows(db, stmt, max_rows)
        if truncated:
            logger.warning("[tgq] report index stopped at a batch boundary after %d rows (cap %d) — "
                           "enrichment coverage will be partial.", len(rows), max_rows)
    else:
        rows = (await db.execute(stmt.limit(max_rows + 1))).all()
        truncated = len(rows) > max_rows
        if truncated:
            logger.warning("[tgq] index truncated at %d rows — enrichment coverage will be partial.", max_rows)
            rows = rows[:max_rows]

    # Rank batches so a ticket re-uploaded in a later statement resolves from that one, and
    # the loser's legs are discarded whole rather than interleaved with the winner's.
    batch_rank: dict[str, tuple] = {}
    for r in rows:
        prev = batch_rank.get(r.batch_id)
        cur = (r.uploaded_at, r.id)
        if prev is None or cur > prev:
            batch_rank[r.batch_id] = cur

    # (code, serial) → {row_seq: [legs]}, keeping only the best batch seen for that key.
    grouped: dict[tuple[str, str], dict] = {}
    for r in rows:
        code = (r[7] or "").strip().upper()
        serial = (r[8] or "").strip()
        if not code or not _SERIAL_RE.match(serial.split("-")[0].strip()):
            continue
        if code.isdigit():
            code = code.zfill(3)

        key = (code, serial)
        rank = batch_rank.get(r.batch_id, (None, 0))
        slot = grouped.get(key)
        if slot is None or rank > slot["rank"]:
            slot = grouped[key] = {"rank": rank, "batch_id": r.batch_id, "seqs": {}}
        elif rank < slot["rank"]:
            continue
        slot["seqs"].setdefault(r.row_seq or 0, []).append(r)

    exact: dict[tuple[str, str], TgqTicket] = {}
    norm: dict[tuple[str, str], TgqTicket | None] = {}

    for (code, serial), slot in grouped.items():
        # Same ticket listed twice in the winning batch (a reissue): the later line wins.
        legs = slot["seqs"][max(slot["seqs"])]
        legs.sort(key=lambda r: (r.sector_index or 1, r.id))
        ticket = _fold_legs(legs, slot["batch_id"], report_mode=report_mode)
        if ticket is None:
            continue

        for doc in (expand_conjunction(serial) or [serial]):
            exact[(code, doc)] = ticket
            nkey = (code, norm_tn(doc))
            # None marks a normalised key two different tickets claim — never guess between them.
            norm[nkey] = ticket if nkey not in norm else (
                ticket if norm.get(nkey) is ticket else None
            )

    index = TgqIndex(exact, norm, by_serial=_serial_map(exact) if report_mode else None)
    index.truncated = truncated
    index.rows_loaded = len(rows)
    index.batches_used = len(batch_rank)
    logger.info("[tgq] index built: %d document keys from %d rows", len(exact), len(rows))
    return index


def _serial_map(exact: dict[tuple[str, str], TgqTicket]) -> dict[str, TgqTicket | None]:
    """serial → ticket, or None when more than one airline code holds that serial.

    ``exact`` keys are unique (code, serial) pairs, so a serial reaches the first branch once
    — for the first code seen — and every further code marks it ambiguous for good.
    """
    out: dict[str, TgqTicket | None] = {}
    owner: dict[str, str] = {}
    for (code, doc), ticket in exact.items():
        out[doc] = ticket if owner.setdefault(doc, code) == code else None
    return out


def _clean(v: Any) -> str | None:
    s = _doc_text(v)
    return s or None


def _ordered_unique(values: Iterable) -> str | None:
    out: list[str] = []
    for v in values:
        s = _clean(v)
        if s and s not in out:
            out.append(s)
    return "/".join(out) if out else None


def _report_detail(legs: Sequence, flights: Sequence) -> dict:
    """Report-mode TgqTicket fields. Pax and PNRs are ticket-level, so the first leg's copy is
    the ticket's. ``flights`` is one flight cell per leg in flown order — a blank leg is
    skipped, never invented — or, for a row whose sectors could not be split, its one cell
    verbatim, since tokens that cannot be aligned to legs must not be presented as if they were.
    """
    first = legs[0]
    return {
        "pax_name": _clean(first.pax_name),
        "air_pnr": _clean(first.air_pnr),
        "gal_pnr": _clean(first.gal_pnr),
        "flight_numbers": "/".join(f for f in map(_clean, flights) if f) or None,
        "fare_basis": _ordered_unique(r.fare_basis for r in legs),
    }


def _fold_legs(legs: list, batch_id: str | None, *, report_mode: bool = False) -> TgqTicket | None:
    """The N rows of one ticket → one journey, one class set, one first-leg travel token."""
    first = legs[0]
    ticket_date = first[12]

    if first.sector_count is None:
        # Batch predates the per-sector split, so the row is still ticket-level: `sectors`
        # holds "BOM/DEL DEL/MNL …" and `class` holds "L L U U". Expand it here rather than
        # re-implementing the grammar, so enrichment works without forcing a re-process.
        raw_sectors, raw_class, raw_travel = first[9], first[10], first[11]
        pairs, status = sector_split.leg_sectors(raw_sectors)
        n = len(pairs)
        if n and status != sector_split.UNPARSED:
            classes = sector_split.tokens(raw_class, n)
            travels = sector_split.tokens(raw_travel, n)
            detail: dict = {}
            if report_mode:
                # The same per-leg tokens `split_row` would have written; one leg is left
                # whole, as there, so "AI 101" is not read as two flights.
                flights = sector_split.tokens(first.flightno, n) if n > 1 else [first.flightno]
                detail = _report_detail(legs, flights)
            return TgqTicket(
                sector=journey_chain(pairs),
                booking_class=distinct_classes(classes or [raw_class]),
                travel_raw=travels[0] if travels else raw_travel,
                ticket_date_raw=ticket_date,
                leg_count=n, batch_id=batch_id,
                **detail,
            )
        # Unparseable sectors: still usable for class/travel date when both are single-valued.
        return _single_valued(raw_class, raw_travel, ticket_date, batch_id,
                              _report_detail(legs, [first.flightno]) if report_mode else None)

    if first.split_status == sector_split.UNPARSED:
        return _single_valued(first[10], first[11], ticket_date, batch_id,
                              _report_detail(legs, [first.flightno]) if report_mode else None)

    return TgqTicket(
        sector=journey_chain([r[9] for r in legs]),
        booking_class=distinct_classes([r[10] for r in legs]),
        travel_raw=first[11],
        ticket_date_raw=ticket_date,
        leg_count=len(legs),
        batch_id=batch_id,
        **(_report_detail(legs, [r.flightno for r in legs]) if report_mode else {}),
    )


def _single_valued(raw_class, raw_travel, ticket_date, batch_id,
                   detail: dict | None = None) -> TgqTicket | None:
    """No usable sector. Keep class / travel date only when each is a single token — a
    multi-token value on an unparsed row cannot be aligned to any leg.

    ``detail`` is report mode's pax / PNR / flight block (None for the commission engine).
    A report still wants the ticket when it names a passenger or a PNR even with neither
    class nor travel date, because that identity is what the BSP row is missing; the
    commission engine has no use for such a ticket, so for it nothing changes.
    """
    cls = (raw_class or "").strip()
    trv = (raw_travel or "").strip()
    cls = cls if cls and len(cls.split()) == 1 else None
    trv = trv if trv and len(trv.split()) == 1 else None
    has_identity = bool(detail and (detail["pax_name"] or detail["air_pnr"] or detail["gal_pnr"]))
    if not cls and not trv and not has_identity:
        return None
    return TgqTicket(
        sector=None, booking_class=distinct_classes([cls]) if cls else None,
        travel_raw=trv, ticket_date_raw=ticket_date,
        leg_count=1, batch_id=batch_id,
        **(detail or {}),
    )
