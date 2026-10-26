"""Third Party GDS: which of a new statement's entries are already saved, which are saved again
with something changed, and which repeat inside the file itself — shown on the review step,
and decided by the user before anything is saved.

EVERY UPLOAD IS SCREENED against every statement already saved for the SAME agency, whatever
its period. 01–07 Aug first is all new; 01–07 sent again, or 08–15 that still carries some of
01–07's tickets, finds them. (The period no longer decides whether lines are compared — it
did, and 08–15 after 01–07 then saved 01–07's tickets a second time. It still decides which
tickets are dated before / after the statement, `dates_outside`, and the "this period is
already uploaded" question the wizard asks before reading the file.)

Each entry of the file lands in one bucket:

  * EXACT — "Already uploaded": a saved line that is the same in every respect the key reads
    (below). Left out by default; the user can save it again, the whole bucket or row by row.
  * PARTIAL — the same ticket and event as a saved line, but the passenger, Booked Date, Issue
    Date, Basic Fare or Net Amount differs. Saved by default, flagged, with what changed and
    the line it repeats (`duplicate_of_id`); the user can leave it out.
  * IN_FILE — "Repeated in this file": the same ticket and event as an EARLIER line of this
    very file (identical or not). Saved by default, flagged; the user can leave it out.
  * NEW — none of these. Always saved.

A line left out is not lost: it is kept, as the file had it, beside the statement it was on
with the saved line it repeats (`left_out_rows`, models/statement_row.ThirdPartyGdsLeftOut),
so the statement still holds every line its file had and the reconciliation can show where
each was reconciled.

Another agency's statements are never compared: each agency (each branch) is its own contract,
and the same ticket on two of them is a question for the Payment Module's reconciliation, not
something an upload may quietly drop.

TWO KEYS PER LINE, both stored at upload:
  * `dedup_key` — the exact line: the document (the ticket number's last ten digits — "235
    5809056126" and "2355809056126" agree — or the PNR when there is no ticket), the event
    (Status and Type: a ticket's issue and its cancellation are two lines), the passenger
    (case and spacing ignored), the Issue Date, Basic Fare and Net Amount (to the paisa), and
    the Booked Date. A line with no ticket and no PNR is keyed on all of its fields, so it
    matches only an identical line. Week, Invoice No and Username never count — they change
    from one statement to the next for the very same line.
  * `match_key` — the entry: document and event; with the passenger too when the document is
    a PNR, which is shared by everyone on the booking. None without a document.
Both are built from the line AS THE VENDOR SENT IT — before any correction on the review step,
and never changed by a later cell edit — so a re-send of a corrected line is still recognised.
A line corrected on the review step is also compared as corrected.

BY COUNT, not by presence: a saved line is matched EXACTLY by one line of the new file at
most, so a line saved once and present twice is one EXACT and one IN_FILE. A PARTIAL is told
apart from the saved line of its entry that differs least (the latest upload's on a tie),
which stays free for the file's exact copy, if it has one. The statement's own OLD /
BALANCE / payment lines are never compared — they describe the file they are printed in and
are saved with every upload, so its balance still adds up.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import ThirdPartyGds, ThirdPartyGdsLeftOut
from app.models.third_party_statement import ThirdPartyStatement
from app.services import statement_balance, statement_period

SLUG = "tp-gds"
_CENT = Decimal("0.01")
# Lines listed back to the user with their details. Counts, totals and the per-row marks the
# review grid reads always cover every line.
MAX_LISTED = 200
# Keys per IN (...) list — well under the driver's bind-parameter limit.
_KEYS_PER_QUERY = 2000

EXACT, PARTIAL, IN_FILE, NEW = "exact", "partial", "in_file", "new"
DUPLICATE_KINDS = (EXACT, PARTIAL, IN_FILE)
SAVE, SKIP = "save", "skip"
# What Save does with each bucket unless the user says otherwise.
DEFAULT_CHOICES = {EXACT: SKIP, PARTIAL: SAVE, IN_FILE: SAVE}

# What a partial duplicate is told apart by: the fields the exact key reads beyond the match
# key. `passenger` is the printed name, else First + Last.
DIFF_FIELDS = (
    ("passenger", "Passenger"),
    ("booking_date", "Booked Date"),
    ("issue_date", "Issue Date"),
    ("base_fare", "Basic Fare"),
    ("net_amount", "Net Amount"),
)
_AMOUNT_FIELDS = frozenset({"base_fare", "net_amount"})


# ── the keys ─────────────────────────────────────────────────────────────────
def _text(value) -> str:
    return " ".join(str(value or "").upper().split())


def _document(data: dict) -> str | None:
    digits = re.sub(r"\D", "", str(data.get("ticket_number") or ""))
    if digits:
        return "T" + (digits[-10:] if len(digits) > 10 else digits)
    for key in ("pnr", "airline_pnr", "gds_pnr"):
        pnr = re.sub(r"[^A-Z0-9]", "", str(data.get(key) or "").upper())
        if pnr:
            return "P" + pnr
    return None


def _event(data: dict) -> str:
    return f"{_text(data.get('ticket_status'))}/{_text(data.get('transaction_type'))}"


def _passenger_name(data: dict) -> str | None:
    return data.get("passenger_name") or " ".join(
        p for p in (data.get("first_name"), data.get("last_name")) if p) or None


def _passenger(data: dict) -> str:
    return _text(_passenger_name(data))


def _amount(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(Decimal(str(value).replace(",", "")).quantize(_CENT, ROUND_HALF_UP))
    except InvalidOperation:
        return _text(value)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# What a line WITHOUT a ticket or PNR is not identified by: the statement-level columns,
# the system's own marks on it, and the carrier as resolved against the airline master
# (which can change between two uploads of the very same line).
_NOT_IDENTITY = frozenset({"week", "invoice_number", "username", "__edited__", "unparsed_fields",
                           "airline_id", "airline_master_name", "airline_conflict"})


def base_key(data: dict) -> str | None:
    """The exact key tp_gds_dedup_01 backfilled (its `entry_keys(...)[0]`) — everything but
    the Booked Date. `line_key` extends it; kept apart so the keys stored before the Booked
    Date counted are extended rather than rebuilt (tp_gds_dupes_02)."""
    if data.get(statement_balance.ROW_KIND_KEY):
        return None
    doc = _document(data)
    if doc is None:
        body = "|".join(f"{k}={_text(v)}" for k, v in sorted(data.items())
                        if k not in _NOT_IDENTITY and v not in (None, ""))
        return _hash("X|" + body)
    return _hash("|".join((doc, _event(data), _passenger(data), str(data.get("issue_date") or ""),
                           _amount(data.get("base_fare")), _amount(data.get("net_amount")))))


def extend_key(base: str | None, booking_date) -> str | None:
    """`base_key` with the Booked Date — the stored `dedup_key`."""
    if base is None:
        return None
    return _hash(f"{base}|B{str(booking_date or '')[:10]}")


def line_key(data: dict) -> str | None:
    """Which line this is, exactly — see the module docstring — or None for a balance line."""
    return extend_key(base_key(data), data.get("booking_date"))


def match_key(data: dict) -> str | None:
    """Which entry this is — its document and event, and the passenger when the document is a
    PNR — or None for a balance line and a line with no ticket and no PNR."""
    if data.get(statement_balance.ROW_KIND_KEY):
        return None
    doc = _document(data)
    if doc is None:
        return None
    parts = [doc, _event(data)]
    if doc.startswith("P"):
        parts.append(_passenger(data))
    return _hash("M|" + "|".join(parts))


def _norm(name: str, data: dict) -> str:
    if name == "passenger":
        return _passenger(data)
    if name in _AMOUNT_FIELDS:
        return _amount(data.get(name))
    return str(data.get(name) or "")[:10]


def _raw(name: str, data: dict) -> str | None:
    return _passenger_name(data) if name == "passenger" else data.get(name)


def differences(data: dict, other: dict) -> list[dict]:
    """The DIFF_FIELDS on which two lines of the same entry disagree, each as
    {field, label, file, saved} — `file` is `data`'s value, `saved` is `other`'s. An Issue
    Date both lines took from their Booked Date is not a second difference."""
    out = []
    for name, label in DIFF_FIELDS:
        if name == "issue_date" and data.get("issue_date_source") and other.get("issue_date_source"):
            continue
        if _norm(name, data) != _norm(name, other):
            out.append({"field": name, "label": label,
                        "file": _raw(name, data), "saved": _raw(name, other)})
    return out


# ── what is already saved ────────────────────────────────────────────────────
@dataclass(frozen=True)
class Earlier:
    """An upload of this agency — one whose period overlaps the new one (the wizard's
    question), or one holding a line the new file repeats."""
    batch_id: str
    source_file: str | None
    period_from: date | None
    period_to: date | None
    uploaded_at: datetime | None
    total_entries: int = 0
    new_entries: int = 0

    @property
    def period_label(self) -> str | None:
        return statement_period.label(self.period_from, self.period_to) if self.period_from else None

    def as_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "source_file": self.source_file,
            "period_from": self.period_from.isoformat() if self.period_from else None,
            "period_to": self.period_to.isoformat() if self.period_to else None,
            "period_label": self.period_label or "—",
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "total_entries": self.total_entries,
            "new_entries": self.new_entries,
        }


@dataclass
class Saved:
    """A line already saved for this agency that a line of the new file may repeat."""
    id: int
    batch_id: str
    dedup_key: str | None
    match_key: str | None
    data: dict


def vendor_condition(supplier):
    """This agency, as a condition on its uploads' statement_batch_suppliers row — by its
    supplier-master id or its Agency Master id, whichever the upload carries."""
    conds = []
    if getattr(supplier, "id", None) is not None:
        conds.append(StatementBatchSupplier.supplier_id == supplier.id)
    if getattr(supplier, "agency_id", None) is not None:
        conds.append(StatementBatchSupplier.agency_id == supplier.agency_id)
    return or_(*conds) if conds else None


def earlier_uploads_query(user, supplier, period_from: date, period_to: date):
    """The SELECT behind `earlier_uploads` — this user's Third Party GDS uploads for this
    agency whose period shares a day with [period_from, period_to], oldest first. None when
    the agency cannot be named."""
    vendor = vendor_condition(supplier)
    if vendor is None:
        return None
    H, L = ThirdPartyStatement, StatementBatchSupplier
    return (
        select(H.batch_id, H.source_file, H.period_from, H.period_to, H.uploaded_at,
               H.total_entries, H.new_entries)
        .join(L, (L.batch_id == H.batch_id) & (L.slug == H.slug) & (L.tenant_id == H.tenant_id))
        .where(H.tenant_id == user.tenant_id, H.created_by_id == user.id, H.slug == SLUG, vendor,
               H.period_from <= period_to, H.period_to >= period_from)
        .order_by(H.uploaded_at.asc(), H.batch_id.asc())
    )


async def earlier_uploads(db: AsyncSession, user, supplier,
                          period_from: date, period_to: date) -> list[Earlier]:
    """The uploads whose period overlaps — what the wizard names in "this period is already
    uploaded — Continue / Cancel" before the file is read."""
    q = earlier_uploads_query(user, supplier, period_from, period_to)
    if q is None:
        return []
    return [Earlier(*r) for r in (await db.execute(q)).all()]


_G = ThirdPartyGds
# The saved line's values a match is shown with and told apart by.
_SAVED_COLUMNS = (_G.ticket_number, _G.ticket_status, _G.transaction_type, _G.passenger_name,
                  _G.first_name, _G.last_name, _G.booking_date, _G.issue_date, _G.issue_date_source,
                  _G.base_fare, _G.net_amount)


def saved_lines_query(user, supplier, *, dedup_keys=(), match_keys=()):
    """The SELECT behind `saved_lines` — this user's saved Third Party GDS lines of this agency
    (any period) carrying one of the keys, with the upload each is in, oldest upload first.
    None when the agency cannot be named or there is no key to look for."""
    vendor = vendor_condition(supplier)
    if vendor is None or not (dedup_keys or match_keys):
        return None
    H, L = ThirdPartyStatement, StatementBatchSupplier
    has_key = []
    if dedup_keys:
        has_key.append(_G.dedup_key.in_(list(dedup_keys)))
    if match_keys:
        has_key.append(_G.match_key.in_(list(match_keys)))
    return (
        select(_G.id, _G.batch_id, _G.dedup_key, _G.match_key, *_SAVED_COLUMNS,
               H.source_file, H.period_from, H.period_to, H.uploaded_at, H.total_entries, H.new_entries)
        .join(H, H.batch_id == _G.batch_id)
        .join(L, (L.batch_id == _G.batch_id) & (L.slug == SLUG) & (L.tenant_id == _G.tenant_id))
        .where(_G.tenant_id == user.tenant_id, _G.created_by_id == user.id, H.slug == SLUG, vendor,
               or_(*has_key))
        .order_by(H.uploaded_at.asc(), _G.id.asc())
    )


def _as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _chunks(keys: list[str]):
    for i in range(0, len(keys), _KEYS_PER_QUERY):
        yield keys[i:i + _KEYS_PER_QUERY]


async def saved_lines(db: AsyncSession, user, supplier, dedup_keys: set[str],
                      match_keys: set[str]) -> tuple[list[Saved], list[Earlier]]:
    """The saved lines of this agency carrying any of the keys — oldest upload first — and the
    uploads they are in."""
    found: dict[int, tuple] = {}
    for kind, keys in (("dedup_keys", sorted(dedup_keys)), ("match_keys", sorted(match_keys))):
        for chunk in _chunks(keys):
            q = saved_lines_query(user, supplier, **{kind: chunk})
            if q is None:
                continue
            for r in (await db.execute(q)).all():
                found[r[0]] = tuple(r)
    names = ["id", "batch_id", "dedup_key", "match_key"] + [c.key for c in _SAVED_COLUMNS]
    width = len(names)
    rows = sorted(found.values(), key=lambda r: (r[width + 3] or datetime.min, r[0]))
    saved, earlier = [], {}
    for r in rows:
        values = dict(zip(names, r[:width]))
        data = {k: _as_text(values[k]) for k in names[4:] if values[k] is not None}
        saved.append(Saved(values["id"], values["batch_id"], values["dedup_key"], values["match_key"], data))
        if values["batch_id"] not in earlier:
            earlier[values["batch_id"]] = Earlier(values["batch_id"], *r[width:])
    return saved, list(earlier.values())


# ── the screen ───────────────────────────────────────────────────────────────
def _shown(data: dict) -> dict:
    return {
        "ticket_number": data.get("ticket_number"), "passenger_name": _passenger_name(data),
        "ticket_status": data.get("ticket_status"), "booking_date": data.get("booking_date"),
        "issue_date": data.get("issue_date"), "net_amount": data.get("net_amount"),
    }


@dataclass
class Entry:
    """One entry line of the new file, and the bucket it is in."""
    pos: int                       # position in the screened `lines`
    index: int | None              # the file row (`__index__`)
    kind: str                      # EXACT | PARTIAL | IN_FILE | NEW
    data: dict
    saved: Saved | None = None     # EXACT / PARTIAL: the saved line it repeats
    twin: int | None = None        # IN_FILE: the position of the file's first copy
    twin_index: int | None = None  # …and its file row
    fields: list[dict] = field(default_factory=list)   # PARTIAL / IN_FILE: what differs

    def mark(self) -> dict:
        """What the review grid reads off each duplicate row — uncapped, so kept small."""
        return {"index": self.index, "kind": self.kind,
                "batch_id": self.saved.batch_id if self.saved else None,
                "of_index": self.twin_index, "fields": self.fields}


@dataclass
class Decision:
    """What Save does with a screened file under the user's choices."""
    kept: list                          # lines to write, balance lines included, file order
    kept_entries: int
    left_out: list[Entry]
    saved_kinds: Counter                # duplicate kind → lines of it saved
    left_kinds: Counter                 # duplicate kind → lines of it left out
    left_net: Decimal
    duplicate_of: str | None            # the earlier upload most left-out lines are in


@dataclass
class Screen:
    """A new file's lines, each entry put in its bucket against what is already saved."""
    period: tuple[date, date] | None = None
    earlier: list[Earlier] = field(default_factory=list)   # uploads holding a matched line
    lines: list = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)

    @property
    def counts(self) -> Counter:
        c = Counter({k: 0 for k in (*DUPLICATE_KINDS, NEW)})
        c.update(e.kind for e in self.entries)
        return c

    @property
    def balance_lines(self) -> int:
        return len(self.lines) - len(self.entries)

    @property
    def period_label(self) -> str:
        return statement_period.label(*self.period) if self.period else "this period"

    def _earlier(self, batch_id: str | None) -> Earlier | None:
        return next((e for e in self.earlier if e.batch_id == batch_id), None)

    def _listed(self, e: Entry) -> dict:
        upload = self._earlier(e.saved.batch_id) if e.saved else None
        return {**_shown(e.data), **e.mark(),
                "source_file": upload.source_file if upload else None,
                "period_label": upload.period_label if upload else None}

    def _earlier_dicts(self, entries: list[Entry]) -> list[dict]:
        matched: dict[str, Counter] = defaultdict(Counter)
        for e in entries:
            if e.saved:
                matched[e.saved.batch_id][e.kind] += 1
        return [{**u.as_dict(), "matched": sum(matched[u.batch_id].values()),
                 "exact": matched[u.batch_id][EXACT], "partial": matched[u.batch_id][PARTIAL]}
                for u in self.earlier]

    def preview(self) -> dict:
        """The review step's answer to "what is in this file?" — every entry's bucket, the
        uploads the repeats are saved in, and the defaults Save applies."""
        dupes = [e for e in self.entries if e.kind != NEW]
        return {
            "period_from": self.period[0].isoformat() if self.period else None,
            "period_to": self.period[1].isoformat() if self.period else None,
            "period_label": self.period_label,
            "earlier": self._earlier_dicts(self.entries),
            "total": len(self.entries),
            "balance_lines": self.balance_lines,
            "counts": dict(self.counts),
            "defaults": dict(DEFAULT_CHOICES),
            # Every duplicate row, for the grid to tag and the client to count under its choices.
            "rows": [e.mark() for e in dupes],
            # The first of them with what they hold, for the lists the wizard shows.
            "listed": [self._listed(e) for e in dupes[:MAX_LISTED]],
            # Net of each bucket — what each choice moves in or out of the statement.
            "net": {k: format(sum((statement_balance.to_decimal(e.data.get("net_amount")) or Decimal("0")
                                    for e in self.entries if e.kind == k), Decimal("0")), "f")
                    for k in (*DUPLICATE_KINDS, NEW)},
        }

    def decide(self, choices: dict | None = None) -> Decision:
        """Apply the user's choices — {kind: SAVE | SKIP} for each bucket, `rows` {file row:
        SAVE | SKIP} overriding it row by row — and flag each duplicate line that is saved:
        `duplicate_kind`, the saved line it repeats (`duplicate_of_id`) and what differs
        (`duplicate_fields`). NEW lines and balance lines are always kept."""
        choices = normalize_choices(choices)
        rows = choices["rows"]
        by_pos = {e.pos: e for e in self.entries}
        kept, left_out = [], []
        saved_kinds, left_kinds = Counter(), Counter()
        for pos, line in enumerate(self.lines):
            e = by_pos.get(pos)
            if e is None or e.kind == NEW:
                kept.append(line)
                continue
            choice = rows.get(e.index, choices[e.kind]) if e.index is not None else choices[e.kind]
            if choice == SKIP:
                left_out.append(e)
                left_kinds[e.kind] += 1
                continue
            line.duplicate_kind = e.kind
            line.duplicate_of_id = e.saved.id if e.saved else None
            line.duplicate_fields = ",".join(f["field"] for f in e.fields) or None
            saved_kinds[e.kind] += 1
            kept.append(line)
        net = sum((statement_balance.to_decimal(e.data.get("net_amount")) or Decimal("0")
                   for e in left_out), Decimal("0"))
        where = Counter(e.saved.batch_id for e in left_out if e.saved)
        return Decision(
            kept=kept, kept_entries=len(self.entries) - len(left_out), left_out=left_out,
            saved_kinds=saved_kinds, left_kinds=left_kinds, left_net=net,
            duplicate_of=where.most_common(1)[0][0] if where else None)

    def refusal(self, decision: Decision) -> str | None:
        """Why nothing will be saved — every entry is left out — or None."""
        if not self.entries or decision.kept_entries:
            return None
        n = len(self.entries)
        if decision.left_kinds[EXACT] == n:
            names = list(dict.fromkeys(
                (self._earlier(e.saved.batch_id).source_file if self._earlier(e.saved.batch_id) else None)
                or "an earlier upload" for e in decision.left_out))
            where = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
            return (f"All {n} {'entry' if n == 1 else 'entries'} of this file {'is' if n == 1 else 'are'} "
                    f"already saved (in {where}) — there is nothing new to save.")
        return "Every entry of this file is left out as a duplicate — there is nothing to save."

    def summary(self, decision: Decision) -> dict:
        """What the save did, for its response and the wizard's done screen."""
        return {
            "period_from": self.period[0].isoformat() if self.period else None,
            "period_to": self.period[1].isoformat() if self.period else None,
            "period_label": self.period_label,
            "earlier": self._earlier_dicts(self.entries),
            "total": len(self.entries),
            "counts": dict(self.counts),
            "saved": {k: decision.saved_kinds[k] for k in DUPLICATE_KINDS},
            "left_out": {k: decision.left_kinds[k] for k in DUPLICATE_KINDS},
            "left_out_total": len(decision.left_out),
            "left_out_net": format(decision.left_net, "f"),
            "new": decision.kept_entries,
            "left_out_lines": [self._listed(e) for e in decision.left_out[:MAX_LISTED]],
        }


def repeat_target(screen: Screen, entry: Entry) -> int | None:
    """The saved line a left-out entry repeats: the earlier upload's line it was told apart
    from, else — repeated in this file — its first copy here, or what that copy repeats when
    it was left out too. Call once the kept lines are flushed, so a copy saved here has its
    id; None when nothing saved is left to point at."""
    by_pos = {e.pos: e for e in screen.entries}
    e: Entry | None = entry
    while e is not None:
        if e.saved is not None:
            return e.saved.id
        if e.twin is None:
            return None
        twin_id = getattr(screen.lines[e.twin], "id", None)
        if twin_id is not None:
            return twin_id
        e = by_pos.get(e.twin)
    return None


def left_out_rows(screen: Screen, decision: Decision, *, tenant_id: int, created_by_id: int,
                  batch_id: str) -> list[ThirdPartyGdsLeftOut]:
    """Each line the save left out, as its file had it, with what it repeats — written with
    the statement, so the statement keeps every line its file held
    (models/statement_row.ThirdPartyGdsLeftOut). After the kept lines are flushed."""
    out = []
    for e in decision.left_out:
        line = screen.lines[e.pos]
        row = ThirdPartyGdsLeftOut(
            tenant_id=tenant_id, created_by_id=created_by_id, batch_id=batch_id,
            file_row=e.index, kind=e.kind, repeat_of_id=repeat_target(screen, e),
            differs=",".join(f["field"] for f in e.fields) or None,
            dedup_key=line.dedup_key, match_key=line.match_key)
        # Column for column: the same fields, already typed — and the same `unparsed_fields`.
        for f in ThirdPartyGds.data_fields():
            setattr(row, f.attr, getattr(line, f.attr))
        out.append(row)
    return out


def normalize_choices(raw: dict | None) -> dict:
    """{kind: SAVE | SKIP, "rows": {file row: SAVE | SKIP}} with every bucket filled in from
    DEFAULT_CHOICES. Raises ValueError on anything else."""
    raw = dict(raw or {})
    out: dict = dict(DEFAULT_CHOICES)
    for kind in DUPLICATE_KINDS:
        if kind in raw:
            if raw[kind] not in (SAVE, SKIP):
                raise ValueError(f"'{kind}' must be '{SAVE}' or '{SKIP}'.")
            out[kind] = raw[kind]
    rows = raw.get("rows")
    rows = {} if rows is None else rows
    if not isinstance(rows, dict):
        raise ValueError("'rows' must map file rows to a choice.")
    out["rows"] = {}
    for k, v in rows.items():
        if v not in (SAVE, SKIP):
            raise ValueError(f"Row {k}: the choice must be '{SAVE}' or '{SKIP}'.")
        try:
            out["rows"][int(k)] = v
        except (TypeError, ValueError):
            raise ValueError(f"'{k}' is not a file row.") from None
    unknown = set(raw) - {*DUPLICATE_KINDS, "rows"}
    if unknown:
        raise ValueError(f"Unknown choice: {', '.join(sorted(unknown))}.")
    return out


def _keys(line, sent: dict | None) -> tuple[list[str], list[str]]:
    """A line's exact and match keys — as the vendor sent it, then as it stands now."""
    now = line.data or {}
    sent = sent if sent is not None else now
    exact = list(dict.fromkeys(k for k in (line_key(sent), line_key(now)) if k))
    match = list(dict.fromkeys(k for k in (match_key(sent), match_key(now)) if k))
    return exact, match


def _take(pool: dict[str, deque], keys: list[str], used: set[int]) -> Saved | None:
    """The first saved line, oldest upload first, carrying one of `keys` and not yet matched
    exactly — and now matched."""
    for k in keys:
        q = pool.get(k)
        while q:
            s = q.popleft()
            if s.id not in used:
                used.add(s.id)
                return s
    return None


def _closest(pool: dict[str, list], keys: list[str], data: dict) -> tuple[Saved, list[dict]] | None:
    """The saved line of the same entry that differs from `data` least — the latest upload's
    on a tie, as the version most recently saved — and how it differs. Not consumed: a
    changed line is flagged against the entry, however many times the file changes it."""
    best = None
    seen: set[int] = set()
    for k in keys:
        for order, s in pool.get(k, ()):
            if s.id in seen:
                continue
            seen.add(s.id)
            fields = differences(data, s.data)
            rank = (len(fields), -order)
            if best is None or rank < best[0]:
                best = (rank, s, fields)
    return (best[1], best[2]) if best else None


def partition(lines: list, saved: list[Saved], *, earlier: list[Earlier] = (),
              period: tuple[date, date] | None = None, indexes: list[int] | None = None,
              key_data: list[dict | None] | None = None) -> Screen:
    """Put each entry of a new file (`lines`, in file order) in its bucket against `saved`
    (oldest upload first). `indexes[i]` is the file row of `lines[i]`; `key_data[i]`, when
    given, is `lines[i]` as the file had it before the review step's corrections. Pure, so it
    is tested without a database.

    In this order: a saved line it is exactly (EXACT — by count: each saved line absorbs one
    line of the file); an earlier line of the file it is exactly (IN_FILE); a saved line of
    the same entry (PARTIAL, or EXACT when no compared field differs); an earlier line of the
    file of the same entry (IN_FILE, with what differs); else NEW."""
    by_exact: dict[str, deque] = defaultdict(deque)
    by_match: dict[str, list] = defaultdict(list)
    for order, s in enumerate(saved):
        if s.dedup_key:
            by_exact[s.dedup_key].append(s)
        if s.match_key:
            by_match[s.match_key].append((order, s))
    used: set[int] = set()
    seen_exact: dict[str, int] = {}
    seen_match: dict[str, int] = {}
    out = Screen(period=period, earlier=list(earlier), lines=list(lines))
    for pos, line in enumerate(lines):
        data = line.data or {}
        if data.get(statement_balance.ROW_KIND_KEY):
            continue
        index = indexes[pos] if indexes is not None else None
        exact, match = _keys(line, key_data[pos] if key_data is not None else None)
        e = Entry(pos=pos, index=index, kind=NEW, data=data)
        if (hit := _take(by_exact, exact, used)) is not None:
            e.kind, e.saved = EXACT, hit
        elif (twin := next((seen_exact[k] for k in exact if k in seen_exact), None)) is not None:
            e.kind, e.twin = IN_FILE, twin
        elif (near := _closest(by_match, match, data)) is not None:
            e.saved, e.fields = near
            # The same on every compared field — a line corrected on the review step to what
            # was saved, or a saved line corrected to what the vendor sends now.
            e.kind = PARTIAL if e.fields else EXACT
            if e.kind == EXACT:
                used.add(e.saved.id)
        elif (twin := next((seen_match[k] for k in match if k in seen_match), None)) is not None:
            e.kind, e.twin = IN_FILE, twin
            e.fields = differences(data, lines[twin].data or {})
        if e.twin is not None:
            e.twin_index = indexes[e.twin] if indexes is not None else None
        for k in exact:
            seen_exact.setdefault(k, pos)
        for k in match:
            seen_match.setdefault(k, pos)
        out.entries.append(e)
    # Only the uploads that hold a matched line, in upload order.
    hit_batches = {e.saved.batch_id for e in out.entries if e.saved}
    out.earlier = [u for u in out.earlier if u.batch_id in hit_batches]
    return out


async def compare(db: AsyncSession, user, supplier, period: tuple[date, date] | None, lines: list,
                  *, key_data: list[dict | None] | None = None,
                  indexes: list[int] | None = None) -> Screen:
    """Stamp each line's keys (as the vendor sent it — `key_data[i]` when the review step
    corrected it), then screen the file against every line already saved for this agency
    that carries one of its keys. An agency that cannot be named compares with nothing."""
    dedup_keys: set[str] = set()
    match_keys: set[str] = set()
    for i, line in enumerate(lines):
        sent = key_data[i] if key_data is not None and key_data[i] is not None else None
        line.dedup_key = line_key(sent if sent is not None else (line.data or {}))
        line.match_key = match_key(sent if sent is not None else (line.data or {}))
        exact, match = _keys(line, sent)
        dedup_keys.update(exact)
        match_keys.update(match)
    saved, earlier = await saved_lines(db, user, supplier, dedup_keys, match_keys)
    return partition(lines, saved, earlier=earlier, period=period, indexes=indexes, key_data=key_data)


# The dates that place a ticket in a statement's period. Travel Date is not one: a ticket
# sold in the week flies whenever it flies.
_PERIOD_DATES = ("booking_date", "issue_date")
_UNPARSED_KEY = "unparsed_fields"


def outside_sides(data: dict, period: tuple[date, date]) -> dict[str, str]:
    """{field: "before" | "after" | "unreadable"} for a line's Booked Date and Issue Date
    against `period` — empty when both are inside it, blank, or the line is a balance line.
    An Issue Date the parser copied from the Booked Date is not checked a second time."""
    if data.get(statement_balance.ROW_KIND_KEY):
        return {}
    unparsed = set(str(data.get(_UNPARSED_KEY) or "").split(","))
    outside: dict[str, str] = {}
    for key in _PERIOD_DATES:
        if key == "issue_date" and data.get("issue_date_source"):
            continue
        value = data.get(key)
        side = statement_period.side(value, period) if value else ("unreadable" if key in unparsed else None)
        if side:
            outside[key] = side
    return outside


def dates_outside(lines: list, period: tuple[date, date] | None, *,
                  indexes: list[int] | None = None, skip=frozenset()) -> statement_period.OutsidePeriod:
    """The tickets dated outside the declared period — for the review step to show before
    Save, so a refund of an older ticket, a late posting or a period typed wrong is seen
    rather than saved unnoticed. Nothing is dropped for it: the user reviews and saves.

    A ticket is flagged when its Booked Date or Issue Date is before or after the period, or
    is in the file but could not be read as a date (then nobody can say it is inside). A
    blank date is not flagged — there is nothing to compare. Balance lines and the file rows
    in `skip` are left out. Pure."""
    out = statement_period.OutsidePeriod(period=period)
    if not period:
        return out
    for pos, line in enumerate(lines):
        data = line.data or {}
        index = indexes[pos] if indexes is not None else None
        if index is not None and index in skip:
            continue
        outside = outside_sides(data, period)
        if outside:
            out.lines.append({**_shown(data), "index": index, "outside": outside})
    return out


def weeks_outside(lines: list, period: tuple[date, date] | None, today: date) -> list[dict]:
    """The file's own Week values ("08-15TH AUG 26") that fall outside the declared period —
    a sign the period, or the file, is not the one the user thinks. Week values that read as
    no period are ignored; so is a file with no Week column."""
    if not period:
        return []
    counts: Counter = Counter()
    for line in lines:
        data = line.data or {}
        if data.get(statement_balance.ROW_KIND_KEY):
            continue
        week = " ".join(str(data.get("week") or "").split())
        if week:
            counts[week] += 1
    out = []
    for week, n in counts.most_common():
        p = statement_period.find_period(week, today)
        if p and not (period[0] <= p[0] and p[1] <= period[1]):
            out.append({"week": week, "period_from": p[0].isoformat(), "period_to": p[1].isoformat(),
                        "period_label": statement_period.label(*p), "rows": n})
    return out
