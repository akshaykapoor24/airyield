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
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """
    sector:          str | None       # 'BOM/DEL/MNL/DEL/BOM'
    booking_class:   str | None       # 'L/U'
    travel_raw:      str | None       # first leg's TravelDt token, verbatim ('14MAY')
    ticket_date_raw: str | None       # TGQ Ticket_Date, the fallback anchor
    leg_count:       int
    batch_id:        str | None

    def resolve_travel(self, issue_date: date | None) -> tuple[date | None, str | None]:
        """Travel date for this ticket, anchored on the BSP issue date when there is one."""
        if self.travel_raw is None:
            return None, None
        anchor_raw = issue_date.isoformat() if issue_date else self.ticket_date_raw
        return resolve_travel_date(self.travel_raw, anchor_raw, issue_date)


class TgqIndex:
    """(airline accounting code, document serial) → TgqTicket, resolved once per run."""

    def __init__(self, exact: dict, norm: dict):
        self._exact = exact
        self._norm = norm

    def __len__(self) -> int:
        return len(self._exact)

    def lookup(
        self,
        accounting_code: str | None,
        document_number: str | None,
        alt_documents: list | None = None,
    ) -> TgqTicket | None:
        code = (accounting_code or "").strip().upper()
        if code.isdigit():
            code = code.zfill(3)
        if not code:
            return None

        for doc in [document_number, *(alt_documents or [])]:
            key = (doc or "").strip()
            if key and (hit := self._exact.get((code, key))) is not None:
                return hit

        # Last resort: compare on the normalised serial, and only when exactly one ticket
        # claims it — an ambiguous normalisation must never produce a confident wrong join.
        key = norm_tn(document_number or "")
        return self._norm.get((code, key)) if key else None


async def load_tgq_index(db: AsyncSession, tenant_id: int, created_by_id: int) -> TgqIndex:
    """Build the whole index in one query — the same discipline as
    ``bsp_commission._airline_name_map`` / ``_tax_totals``, so a run never goes N+1."""
    rows = (await db.execute(
        select(
            TgqHmpr.batch_id, TgqHmpr.uploaded_at, TgqHmpr.id,
            TgqHmpr.row_seq, TgqHmpr.sector_index, TgqHmpr.sector_count, TgqHmpr.split_status,
            TgqHmpr.data["airline_code"].astext,
            TgqHmpr.data["ticket_no"].astext,
            TgqHmpr.data["sectors"].astext,
            TgqHmpr.data["class"].astext,
            TgqHmpr.data["traveldt"].astext,
            TgqHmpr.data["ticket_date"].astext,
        )
        .where(
            TgqHmpr.tenant_id == tenant_id,
            TgqHmpr.created_by_id == created_by_id,
            TgqHmpr.is_total.is_(False),
        )
        .limit(MAX_TGQ_ROWS + 1)
    )).all()

    if len(rows) > MAX_TGQ_ROWS:
        logger.warning("[tgq] index truncated at %d rows — enrichment coverage will be partial.", MAX_TGQ_ROWS)
        rows = rows[:MAX_TGQ_ROWS]

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
        ticket = _fold_legs(legs, slot["batch_id"])
        if ticket is None:
            continue

        for doc in (expand_conjunction(serial) or [serial]):
            exact[(code, doc)] = ticket
            nkey = (code, norm_tn(doc))
            # None marks a normalised key two different tickets claim — never guess between them.
            norm[nkey] = ticket if nkey not in norm else (
                ticket if norm.get(nkey) is ticket else None
            )

    logger.info("[tgq] index built: %d document keys from %d rows", len(exact), len(rows))
    return TgqIndex(exact, norm)


def _fold_legs(legs: list, batch_id: str | None) -> TgqTicket | None:
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
            return TgqTicket(
                sector=journey_chain(pairs),
                booking_class=distinct_classes(classes or [raw_class]),
                travel_raw=travels[0] if travels else raw_travel,
                ticket_date_raw=ticket_date,
                leg_count=n, batch_id=batch_id,
            )
        # Unparseable sectors: still usable for class/travel date when both are single-valued.
        return _single_valued(raw_class, raw_travel, ticket_date, batch_id)

    if first.split_status == sector_split.UNPARSED:
        return _single_valued(first[10], first[11], ticket_date, batch_id)

    return TgqTicket(
        sector=journey_chain([r[9] for r in legs]),
        booking_class=distinct_classes([r[10] for r in legs]),
        travel_raw=first[11],
        ticket_date_raw=ticket_date,
        leg_count=len(legs),
        batch_id=batch_id,
    )


def _single_valued(raw_class, raw_travel, ticket_date, batch_id) -> TgqTicket | None:
    """No usable sector. Keep class / travel date only when each is a single token — a
    multi-token value on an unparsed row cannot be aligned to any leg."""
    cls = (raw_class or "").strip()
    trv = (raw_travel or "").strip()
    cls = cls if cls and len(cls.split()) == 1 else None
    trv = trv if trv and len(trv.split()) == 1 else None
    if not cls and not trv:
        return None
    return TgqTicket(
        sector=None, booking_class=distinct_classes([cls]) if cls else None,
        travel_raw=trv, ticket_date_raw=ticket_date,
        leg_count=1, batch_id=batch_id,
    )
