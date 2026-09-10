"""Merging a two-file LCC statement into one row set.

Air India Express (and any carrier on the same Navitaire export) issues one statement
as TWO files that only make sense joined on ``PNR`` <-> ``RecordLocator``:

  * **account file** — one row per money movement: funds used for a booking, funds
    added back from a cancellation, refunds paid out, and a daily balance line. Carries
    the payment method, the GST party, the agent code and the transaction type. No
    fares, no passengers.
  * **passenger file** — one row per passenger PER SEGMENT. Carries the passenger, the
    sectors and the full fare breakdown. No payment, no GST, no transaction type.

This module turns that pair into the flat rows ``lcc_detailed_spec.build_typed_row``
already knows how to type. It is pure — no session, no FastAPI, no I/O — so the whole
decision matrix is unit-testable without a database, the same discipline as
``services/lcc_airline_selection.py``.

Four rules carry the design.

**1. The ACCOUNT file is the spine.**  One imported row per account transaction. The
passenger file is a lookup, not a second set of rows: it supplies the name, the
sectors and the base fare that the account file has no column for.

**2. Only ``PaymentMethodCode = AG`` rows are imported.**  That is the whole filter,
and it is what removes the ``StatementDateAndBalance`` lines — those carry no payment
method, and a running balance is a snapshot of the account rather than a transaction
against it. Everything else in the file is kept.

**3. ``ForeignAmount`` is the total, exactly as printed.**  Positive is a sale,
negative is a refund, which is already what ``_bill_kind`` reads, so no sign is
touched anywhere. NOTE FOR WHOEVER READS THIS NEXT: the ``Note`` column describes the
opposite convention — ``-5516`` is ``"Funds Used: D49GSC"`` (a booking being paid for)
and ``+5073`` is ``"Refund by utility"``. The sign rule here is the one the business
specified, and it was confirmed against that discrepancy rather than in ignorance of
it. If invoices ever come out inverted, this paragraph is where to start.

**4. Tax is DERIVED: ``tax = total - base fare``.**  The account file has no tax
column and the passenger file's own ``Tax`` / ``TransactionFee`` / ``TotalFare``
columns are deliberately unused — the money on the row is the account's, and the only
thing taken from the passenger file is the base fare it is decomposed against. When a
PNR has no passenger row at all (common — the two files routinely cover different
date ranges) the base fare is unknown, so BOTH it and the tax are left blank rather
than a zero fare being asserted.

The passenger file is aggregated PER PNR, not per passenger: the account row's money
is the whole booking's, so the base fare it is compared against has to be the whole
booking's too. A three-passenger PNR contributes one summed base fare, all three
names, and its distinct sectors.

The synthetic columns this module invents (the passenger's name, the base fare, the
derived tax, the leg columns) are named EXACTLY after standard template headers. That
is load-bearing, not cosmetic: it means ``suggest_mapping``'s exact-match path maps
them for free, the user sees and can re-map them like any other column, and the
wizard's preview shows real merged rows before thousands of them are written.
``test_lcc_merge`` asserts the names really are template headers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.services.lcc_statement import norm, _clean


# Bumped whenever the reshape's OUTPUT changes shape — a new synthetic column, a
# different grouping key, a different sum. A batch records the version it was staged
# under, because a stored column_map only means what it meant under that version, in
# exactly the way `spreadsheet.read_table` warns a re-detected header row does.
MERGE_VERSION = 2

# The only payment method that is a real transaction. A StatementDateAndBalance line
# leaves it blank, which is exactly what makes this one test enough to drop them.
AG_PAYMENT_METHOD = "AG"

# ── file roles ───────────────────────────────────────────────────────────────
ROLE_SINGLE = "single"       # an ordinary one-file export (IndiGo and kin)
ROLE_ACCOUNT = "account"
ROLE_PAX = "pax"
FILE_ROLES = (ROLE_SINGLE, ROLE_ACCOUNT, ROLE_PAX)

ROW_KIND_PAX = "pax"
ROW_KIND_ACCOUNT = "account"

# ── account movement kinds ───────────────────────────────────────────────────
# Classified from the NOTE, not from AccountTransactionType. That column has three
# values and conflates two entirely different events: "Funds Added: J7IL8G" (the value
# of a cancelled booking returned to the prepaid account) and "Refund by utility:
# PMTID:..., RL:IBWGPK" (money actually refunded) are BOTH `PPAccountCredit`. In the
# sample the Funds Added / Funds Used pairs net to zero (+8356 J7IL8G then -8356
# IBWGPK) — they are transfers between bookings, not refunds.
MOVEMENT_BALANCE = "balance"
MOVEMENT_BOOKING_PAYMENT = "booking_payment"
MOVEMENT_CANCELLATION_CREDIT = "cancellation_credit"
MOVEMENT_REFUND = "refund"
MOVEMENT_UNKNOWN = "unknown"

MOVEMENT_KINDS = (
    MOVEMENT_BALANCE, MOVEMENT_BOOKING_PAYMENT, MOVEMENT_CANCELLATION_CREDIT,
    MOVEMENT_REFUND, MOVEMENT_UNKNOWN,
)

# Longest-first is irrelevant here (no prefix is a prefix of another), but order is
# fixed so classification is deterministic.
_NOTE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("prepaid account", MOVEMENT_BALANCE),
    ("funds used", MOVEMENT_BOOKING_PAYMENT),
    ("funds added", MOVEMENT_CANCELLATION_CREDIT),
    ("refund by utility", MOVEMENT_REFUND),
)

MAX_LEGS = 5   # the spec folds five; see lcc_detailed_spec._ORDINALS
_ORDINALS = ("First", "Second", "Third", "Fourth", "Fifth")


# ── synthetic column names ───────────────────────────────────────────────────
# Every one of these is a header in lcc_detailed_spec.LCC_STANDARD_HEADERS, so
# suggest_mapping's exact-match path resolves them with no alias work at all.
COL_NAME1 = "Name1"
COL_PAX_COUNT = "PaxCount"
COL_PAX_TYPE = "PaxType"
COL_TRANSACTION_DATE = "Transaction Date"
COL_NAME = "Name"
COL_BOOKING_DATE = "BookingDate"
COL_BASE_FARE = "BaseFare"
COL_TAX_TOTAL = "Tax Total"

# What the passenger file contributes to an account row. Exactly the columns the
# business highlighted, under the template header each lands in. `BaseFare` and the
# leg columns are handled separately because they aggregate rather than copy.
_PAX_COLUMNS_USED = ("organizationname", "bookingdate", "paxfirstname", "paxlastname",
                     "paxtype", "depart_station", "arrive_station", "departuredate",
                     "departurecarriercode", "flightnumber", "basefare")


def leg_headers(n: int) -> tuple[str, str, str]:
    """(route, flight no, dep date) template headers for leg `n` (1-based)."""
    o = _ORDINALS[n - 1]
    return f"{o} Leg", f"{o} Leg Flight No", f"{o} Leg Dep Date"


def synthetic_columns(with_account: bool) -> list[str]:
    """The columns the reshape ADDS to a passenger file, in display order."""
    out = [COL_NAME1, COL_PAX_COUNT, COL_TRANSACTION_DATE]
    for i in range(1, MAX_LEGS + 1):
        out.extend(leg_headers(i))
    return out


def account_columns_after_merge(raw_columns, *, with_pax: bool) -> list[str]:
    """What the mapping UI should offer for the ACCOUNT file — the spine.

    Its own headers unchanged, plus what the passenger file contributes: the
    passenger, the booking, the base fare and the derived tax, each under the
    standard template header it belongs in.
    """
    out = [str(c) for c in raw_columns]
    if not with_pax:
        return out
    extra = [COL_NAME, COL_NAME1, COL_PAX_COUNT, COL_PAX_TYPE, COL_BOOKING_DATE,
             COL_BASE_FARE, COL_TAX_TOTAL]
    for i in range(1, MAX_LEGS + 1):
        extra.extend(leg_headers(i))
    seen = set(out)
    for c in extra:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def pax_columns_after_reshape(raw_columns, *, with_account: bool) -> list[str]:
    """What the mapping UI should offer for a passenger file uploaded ON ITS OWN.

    When an account file is present the passenger file produces no rows of its own —
    it is a lookup — so this is only reached for a standalone passenger upload. The
    raw headers (their VALUES change: money is summed, the booking date gains its
    time) plus the synthetic ones, duplicates dropped.
    """
    idx = _index(raw_columns)
    consumed = {c for c in (_find(idx, n) for n in _CONSUMED_COLUMNS) if c}
    seen: set[str] = set()
    out: list[str] = []
    for c in list(raw_columns) + synthetic_columns(with_account):
        s = str(c)
        # A consumed column is dropped rather than offered: after the reshape its
        # cells are empty, and an always-blank entry in the mapping dropdown reads as
        # a bug. Its content is in the leg columns / BookingDate instead.
        if s in seen or s in consumed:
            continue
        seen.add(s)
        out.append(s)
    return out


# ── classification ───────────────────────────────────────────────────────────
# The filled-in standard template is checked FIRST, and this is not a nicety: the
# template now carries `AccountTransactionType` and `AccountTransactionID` among its
# columns, so an account-marker test run first would classify every IndiGo upload as
# an account file. These markers are structural to the template and appear in neither
# half of a two-file export.
_SINGLE_MARKERS = frozenset({
    "firstleg", "gdsrecordlocator", "gdsrecordcode", "paymentdtm",
    "otherssrtotal", "otherfeetotal", "paxcount", "name1", "productclass",
})
_ACCOUNT_MARKERS = frozenset({"accounttransactionid", "accounttransactiontype"})
_PAX_MARKERS = frozenset({"paxfirstname", "paxlastname"})


def _squash(header) -> str:
    """`norm` with separators removed, so `pax_first_name` and `PaxFirstName` agree.

    `norm` maps every run of non-alphanumerics to `_`, which keeps `Depart_Station`
    and `DepartStation` apart. This vendor already mixes both conventions inside one
    file, so matching squashed is what makes column lookup robust to it.
    """
    return norm(header).replace("_", "")


def classify(columns) -> str:
    """Which half of a two-file export this is — or `single` for an ordinary one."""
    nz = {_squash(c) for c in columns}
    if nz & _SINGLE_MARKERS:
        return ROLE_SINGLE
    if nz & _ACCOUNT_MARKERS:
        return ROLE_ACCOUNT
    if nz & _PAX_MARKERS or {"recordlocator", "totalfare"} <= nz:
        return ROLE_PAX
    return ROLE_SINGLE


# (label shown to the user, accepted normalised names) per role. Checked INSTEAD of the
# generic "at least 3 standard columns matched" gate, which quotes IndiGo headers and
# means nothing to someone uploading a passenger report — and which the passenger file
# only clears by a single column anyway.
REQUIRED_COLUMNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    ROLE_ACCOUNT: (
        ("a PNR (PNR)", ("pnr", "recordlocator")),
        ("an amount (ForeignAmount)", ("foreignamount", "acamount", "amount")),
    ),
    ROLE_PAX: (
        ("a booking reference (RecordLocator)", ("recordlocator", "pnr")),
        ("an amount (TotalFare or BaseFare)", ("totalfare", "basefare", "total")),
        ("a passenger name (PaxFirstName / PaxLastName)",
         ("paxfirstname", "paxlastname", "paxname", "name1")),
    ),
}


def missing_required(role: str, columns) -> list[str]:
    """Human-readable labels for the required columns this file does not have."""
    nz = {_squash(c) for c in columns}
    return [label for label, opts in REQUIRED_COLUMNS.get(role, ())
            if not (nz & {o.replace("_", "") for o in opts})]


# ── small helpers ────────────────────────────────────────────────────────────
def _index(columns) -> dict[str, str]:
    """{normalised name: original name}, first occurrence wins.

    Indexed under both `norm` and its separator-free form, so a lookup finds the
    column whichever convention the file used.
    """
    out: dict[str, str] = {}
    for c in columns:
        n = norm(c)
        out.setdefault(n, str(c))
        out.setdefault(n.replace("_", ""), str(c))
    return out


def _find(idx: dict[str, str], *names) -> str | None:
    """The original name of the first column matching any of `names`."""
    for n in names:
        col = idx.get(n) or idx.get(n.replace("_", ""))
        if col is not None:
            return col
    return None


def _dec(v) -> Decimal | None:
    """Money parse, tolerant of separators and a leading minus.

    Deliberately the same shape as ``lcc_detailed_spec._to_decimal`` so a value sums
    here exactly as it would have coerced there — a figure that survives the sum but
    not the coercion (or vice versa) would make the grid disagree with itself.
    """
    if v is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(v))
    if s in ("", "-", ".", "-.", "."):
        return None
    try:
        return Decimal(s)
    except Exception:  # noqa: BLE001
        return None


def _money_str(d: Decimal | None) -> str | None:
    """Plain decimal text, never exponent form.

    `str(Decimal('1E+3'))` is `'1E+3'`, and the spec's `_to_decimal` strips non-digits
    from that to get `13`. Formatting with 'f' makes that unreachable.
    """
    return None if d is None else format(d, "f")


def _upper(v) -> str:
    return (_clean(v) or "").strip().upper()


# ── stats ────────────────────────────────────────────────────────────────────
@dataclass
class MergeStats:
    """What the merge did, for the done screen and for `lcc_detailed_batch.merge_stats`.

    Every number here answers a question a reconciler will actually ask. The two that
    matter most on a first upload are `unmatched_pax_rows` (is the join key right?) and
    `unknown_notes` (is the movement vocabulary complete?).
    """
    source_rows: int = 0                # non-blank lines read across both files
    pax_source_rows: int = 0
    account_source_rows: int = 0
    account_rows: int = 0               # AG transactions written — the statement itself
    skipped_not_ag: int = 0             # dropped: payment method is not AG (the balance lines)
    pnrs_indexed: int = 0               # distinct bookings found in the passenger file
    enriched_account_rows: int = 0      # transactions whose PNR was in the passenger file
    unmatched_account_rows: int = 0     # ... and those whose PNR was not
    matched_without_fare: int = 0       # PNR matched but carried no base fare
    tax_derived: int = 0                # rows where tax = total - base fare was computed
    pax_rows: int = 0                   # only non-zero for a passenger file uploaded alone
    duplicate_pax_lines: int = 0        # byte-identical repeated source lines, dropped
    repeated_legs: int = 0              # same leg twice with DIFFERENT money — kept, flagged
    legs_truncated: int = 0             # bookings with more than MAX_LEGS legs
    movement_counts: dict = field(default_factory=dict)     # {movement_kind: n}
    unknown_notes: dict = field(default_factory=dict)       # {note prefix: n}
    currencies_seen: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["merge_version"] = MERGE_VERSION
        return d


@dataclass(frozen=True)
class MergedRow:
    """One row ready for ``build_typed_row``.

    `role` says WHICH column_map to apply — the two files share no headers, so each
    keeps its own confirmed mapping (see models/lcc_detailed_batch_file.py). The rest
    are values the mapping cannot produce, which the worker stamps onto the built row.
    """
    role: str
    row_kind: str
    data: dict
    movement_kind: str | None = None
    extra: dict | None = None


# ── passenger reshape ────────────────────────────────────────────────────────
# Columns whose values are SUMMED across a passenger's segments. Everything else is
# taken from the group's first line, which is safe because these are all PNR- or
# passenger-level facts repeated on every segment row.
_SUM_COLUMNS = ("basefare", "tax", "transactionfee", "otherservices", "totalfare")

# Raw columns the reshape CONSUMES: each varies from segment to segment, and each is
# re-emitted through a synthetic template-named column. They are dropped from the
# output rather than carried over from whichever line happened to be first in the
# group — that would be non-deterministic (a re-ingest could pick a different line)
# and misleading (a two-leg row would show one leg's origin as though it were the
# journey's). `BookingTime` is here because it is folded into `BookingDate`.
_CONSUMED_COLUMNS = (
    "depart_station", "arrive_station", "departuredate",
    "departurecarriercode", "flightnumber", "bookingtime",
)


def reshape_pax(rows: list[dict], columns, *, airline_code: str | None = None,
                stats: MergeStats | None = None) -> list[dict]:
    """Passenger-per-segment lines -> one row per (PNR, passenger), legs folded.

    Returns plain dicts keyed by column name — raw headers keep their names (with
    summed money and a booking date that now carries its time), plus the synthetic
    template-named columns.
    """
    st = stats or MergeStats()
    idx = _index(columns)

    c_pnr = _find(idx, "recordlocator", "pnr")
    c_first, c_last = _find(idx, "paxfirstname"), _find(idx, "paxlastname")
    c_ptype = _find(idx, "paxtype")
    c_bdate, c_btime = _find(idx, "bookingdate"), _find(idx, "bookingtime")
    c_dep, c_arr = _find(idx, "depart_station"), _find(idx, "arrive_station")
    c_carrier, c_flight = _find(idx, "departurecarriercode"), _find(idx, "flightnumber")
    c_depdate = _find(idx, "departuredate")
    consumed = {c for c in (_find(idx, n) for n in _CONSUMED_COLUMNS) if c}

    groups: dict[tuple, dict] = {}
    for order, row in enumerate(rows):
        # Upper-cased: the sample carries the same traveller as both "MADHU MAYOORI"
        # and "Madhu MAYOORI". NOT customer_resolver.person_match_key — that sorts
        # tokens (collapsing "ASHISH RAI" with "RAI ASHISH") and strips INF/CHD/ADT,
        # so an infant could merge into the parent they share a surname with.
        key = (
            _upper(row.get(c_pnr) if c_pnr else None),
            _upper(row.get(c_first) if c_first else None),
            _upper(row.get(c_last) if c_last else None),
            _upper(row.get(c_ptype) if c_ptype else None),
        )
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"first": row, "order": order, "legs": [], "seen": set(),
                               "sums": {}, "leg_keys": set()}

        # A byte-identical repeat of a line already in this group is a duplicated
        # export line: drop it, and above all do not add its money again. A repeat of
        # the same LEG carrying DIFFERENT money is not that — it is an amendment, and
        # dropping it would delete real money — so it is kept and counted instead.
        fingerprint = tuple(sorted((str(k), _clean(v)) for k, v in row.items()))
        if fingerprint in g["seen"]:
            st.duplicate_pax_lines += 1
            continue
        g["seen"].add(fingerprint)

        dep = _clean(row.get(c_dep)) if c_dep else None
        arr = _clean(row.get(c_arr)) if c_arr else None
        carrier = (_clean(row.get(c_carrier)) if c_carrier else None) or airline_code or ""
        flight = _clean(row.get(c_flight)) if c_flight else None
        dep_date = _clean(row.get(c_depdate)) if c_depdate else None
        route = f"{dep}-{arr}" if (dep and arr) else (dep or arr)
        # Carrier-prefixed: services/plb_accrual.py derives the operating carrier from
        # the FIRST TWO characters of segments[0].flight_no and drops the row entirely
        # if that doesn't resolve to an airline — a bare "1506" would silently vanish
        # from the accrual board. Hence the fallback to the declared airline code.
        flight_no = f"{carrier}{flight}" if flight else None
        if route or flight_no:
            leg_key = (route, flight_no, dep_date)
            if leg_key in g["leg_keys"]:
                st.repeated_legs += 1
            g["leg_keys"].add(leg_key)
            g["legs"].append({"order": order, "route": route,
                              "flight_no": flight_no, "dep_date": dep_date})

        for n in _SUM_COLUMNS:
            col = _find(idx, n)
            if col is None:
                continue
            d = _dec(row.get(col))
            if d is None:
                continue
            g["sums"][col] = g["sums"].get(col, Decimal("0")) + d

    out: list[dict] = []
    for g in sorted(groups.values(), key=lambda x: x["order"]):
        data = {str(k): _clean(v) for k, v in g["first"].items() if str(k) not in consumed}
        for col, total in g["sums"].items():
            data[col] = _money_str(total)
        # A summed column present in the file but blank on every line of the group
        # stays blank rather than becoming a spurious 0.
        for n in _SUM_COLUMNS:
            col = _find(idx, n)
            if col is not None and col not in g["sums"]:
                data[col] = None

        first = _clean(g["first"].get(c_first)) if c_first else None
        last = _clean(g["first"].get(c_last)) if c_last else None
        data[COL_NAME1] = " ".join(p for p in (first, last) if p) or None
        data[COL_PAX_COUNT] = "1"

        # Booking date + time, joined in place. The spec maps ONE source column per
        # field and never concatenates, so without this the time is simply lost.
        bdate = _clean(g["first"].get(c_bdate)) if c_bdate else None
        btime = _clean(g["first"].get(c_btime)) if c_btime else None
        booking = " ".join(p for p in (bdate, btime) if p) or None
        if c_bdate:
            data[c_bdate] = booking
        # A passenger file has no transaction date. The booking IS the transaction for
        # a sale line, it is always present, and taking it from the account file would
        # be wrong anyway — a PNR's several transactions have several dates.
        data[COL_TRANSACTION_DATE] = booking

        # Order by departure, source order breaking ties (and carrying rows whose date
        # is blank or unparseable), because `departure_date` derives from the first leg
        # that has one.
        legs = sorted(g["legs"], key=lambda l: (_sort_date(l["dep_date"]), l["order"]))
        for i, leg in enumerate(legs[:MAX_LEGS], start=1):
            h_route, h_flight, h_date = leg_headers(i)
            data[h_route] = leg["route"]
            data[h_flight] = leg["flight_no"]
            data[h_date] = leg["dep_date"]
        if len(legs) > MAX_LEGS:
            st.legs_truncated += 1
            # The money already covers every leg; only the visible itinerary is capped.
            # Overflow is kept rather than dropped silently.
            data["__overflow_legs__"] = [
                {"route": l["route"], "flight_no": l["flight_no"], "dep_date": l["dep_date"]}
                for l in legs[MAX_LEGS:]
            ]
        out.append(data)
    return out


def _sort_date(v) -> str:
    """Sortable key for a departure date; blanks sort last, not first."""
    s = _clean(v)
    return s if s else "￿"


# ── the merge ────────────────────────────────────────────────────────────────
def classify_note(note) -> tuple[str, str | None]:
    """(movement_kind, unrecognised prefix). The prefix is None when recognised."""
    s = (_clean(note) or "").strip().lower()
    if not s:
        return MOVEMENT_UNKNOWN, "(no note)"
    for prefix, kind in _NOTE_PREFIXES:
        if s.startswith(prefix):
            return kind, None
    # Name the unrecognised shape rather than the whole free-text line, so the counter
    # groups instead of producing one entry per row.
    return MOVEMENT_UNKNOWN, s.split(":")[0][:60].strip() or s[:60]


@dataclass
class PnrFacts:
    """What the passenger file knows about one booking, aggregated over its rows.

    Per PNR, not per passenger: the account row's money is the whole booking's, so
    the base fare it is decomposed against has to be the whole booking's too.
    """
    names: list[str] = field(default_factory=list)
    pax_type: str | None = None
    booking_date: str | None = None
    organization: str | None = None
    base_fare: Decimal | None = None
    segments: list[dict] = field(default_factory=list)
    overflow: list[dict] = field(default_factory=list)


def build_pnr_index(pax_rows: list[dict], columns, *, airline_code: str | None = None,
                    stats: MergeStats | None = None) -> dict[str, PnrFacts]:
    """{PNR: PnrFacts} — the passenger file as a lookup, keyed by record locator."""
    st = stats or MergeStats()
    idx = _index(columns)
    c_pnr = _find(idx, "recordlocator", "pnr")
    c_first, c_last = _find(idx, "paxfirstname"), _find(idx, "paxlastname")
    c_ptype = _find(idx, "paxtype")
    c_bdate = _find(idx, "bookingdate")
    c_org = _find(idx, "organizationname")
    c_base = _find(idx, "basefare")
    c_dep, c_arr = _find(idx, "depart_station"), _find(idx, "arrive_station")
    c_carrier, c_flight = _find(idx, "departurecarriercode"), _find(idx, "flightnumber")
    c_depdate = _find(idx, "departuredate")

    out: dict[str, PnrFacts] = {}
    seen_names: dict[str, set] = {}
    seen_legs: dict[str, set] = {}
    legs: dict[str, list] = {}

    for order, row in enumerate(pax_rows):
        pnr = _upper(row.get(c_pnr)) if c_pnr else ""
        if not pnr:
            continue
        f = out.get(pnr)
        if f is None:
            f = out[pnr] = PnrFacts()
            seen_names[pnr], seen_legs[pnr], legs[pnr] = set(), set(), []

        # Every line of the booking adds to its base fare — a three-passenger PNR
        # contributes three fares, because the transaction that paid for it paid for
        # all three.
        d = _dec(row.get(c_base)) if c_base else None
        if d is not None:
            f.base_fare = (f.base_fare or Decimal("0")) + d

        first = _clean(row.get(c_first)) if c_first else None
        last = _clean(row.get(c_last)) if c_last else None
        name = " ".join(p for p in (first, last) if p)
        # Upper-cased key, original spelling kept: the sample carries the same
        # traveller as both "MADHU MAYOORI" and "Madhu MAYOORI".
        if name and name.upper() not in seen_names[pnr]:
            seen_names[pnr].add(name.upper())
            f.names.append(name)

        if f.pax_type is None and c_ptype:
            f.pax_type = _clean(row.get(c_ptype))
        if f.booking_date is None and c_bdate:
            f.booking_date = _clean(row.get(c_bdate))
        if f.organization is None and c_org:
            f.organization = _clean(row.get(c_org))

        dep = _clean(row.get(c_dep)) if c_dep else None
        arr = _clean(row.get(c_arr)) if c_arr else None
        carrier = (_clean(row.get(c_carrier)) if c_carrier else None) or airline_code or ""
        flight = _clean(row.get(c_flight)) if c_flight else None
        dep_date = _clean(row.get(c_depdate)) if c_depdate else None
        route = f"{dep}-{arr}" if (dep and arr) else (dep or arr)
        # Carrier-prefixed: services/plb_accrual.py derives the operating carrier from
        # the FIRST TWO characters of segments[0].flight_no and drops the row entirely
        # if that doesn't resolve to an airline — a bare "1506" would silently vanish
        # from the accrual board.
        flight_no = f"{carrier}{flight}" if flight else None
        if route or flight_no:
            key = (route, flight_no, dep_date)
            if key not in seen_legs[pnr]:
                seen_legs[pnr].add(key)
                legs[pnr].append({"order": order, "route": route,
                                  "flight_no": flight_no, "dep_date": dep_date})

    for pnr, f in out.items():
        ordered = sorted(legs[pnr], key=lambda l: (_sort_date(l["dep_date"]), l["order"]))
        f.segments = [{k: l[k] for k in ("route", "flight_no", "dep_date")}
                      for l in ordered[:MAX_LEGS]]
        if len(ordered) > MAX_LEGS:
            st.legs_truncated += 1
            f.overflow = [{k: l[k] for k in ("route", "flight_no", "dep_date")}
                          for l in ordered[MAX_LEGS:]]
    st.pnrs_indexed = len(out)
    return out


def merge(
    pax_rows: list[dict], pax_columns,
    account_rows: list[dict], account_columns,
    *, airline_code: str | None = None,
) -> tuple[list[MergedRow], MergeStats]:
    """The account statement, one row per AG transaction, with the passenger file
    joined in on PNR. Returns the rows and what the merge did.

    A passenger file uploaded ON ITS OWN has no account spine to hang off, so it
    falls back to the per-passenger reshape and imports as an ordinary statement.
    """
    st = MergeStats(
        pax_source_rows=len(pax_rows),
        account_source_rows=len(account_rows),
        source_rows=len(pax_rows) + len(account_rows),
    )
    acct_idx = _index(account_columns or [])
    currencies: set[str] = set()

    if not account_rows:
        return _pax_only(pax_rows, pax_columns, airline_code, st)

    by_pnr = build_pnr_index(pax_rows, pax_columns or [], airline_code=airline_code, stats=st)

    c_apnr = _find(acct_idx, "pnr", "recordlocator")
    c_note = _find(acct_idx, "note")
    c_method = _find(acct_idx, "paymentmethodcode")
    c_amount = _find(acct_idx, "foreignamount")
    c_acur = _find(acct_idx, "currencycode")

    out: list[MergedRow] = []
    for r in account_rows:
        # The one filter. A StatementDateAndBalance line leaves the payment method
        # blank, so this drops the running-balance rows without needing to know what
        # they are — and keeps every real transaction, whichever way its amount runs.
        method = (_clean(r.get(c_method)) if c_method else None) or ""
        if method.strip().upper() != AG_PAYMENT_METHOD:
            st.skipped_not_ag += 1
            continue

        data = {str(k): _clean(v) for k, v in r.items()}
        kind, unknown = classify_note(r.get(c_note) if c_note else None)
        st.movement_counts[kind] = st.movement_counts.get(kind, 0) + 1
        if unknown:
            st.unknown_notes[unknown] = st.unknown_notes.get(unknown, 0) + 1

        if c_acur:
            cur = _clean(r.get(c_acur))
            if cur:
                currencies.add(cur.upper())

        # `total` is ForeignAmount UNTOUCHED: positive sells, negative refunds, which
        # is already what _bill_kind reads. See rule 3 in the module docstring for why
        # this deliberately disagrees with the Note text.
        total = _dec(r.get(c_amount)) if c_amount else None

        pnr = _upper(r.get(c_apnr)) if c_apnr else ""
        facts = by_pnr.get(pnr) if pnr else None
        extra: dict | None = None
        if facts is None:
            st.unmatched_account_rows += 1
        else:
            st.enriched_account_rows += 1
            if facts.names:
                data[COL_NAME1] = " · ".join(facts.names)
                data[COL_PAX_COUNT] = str(len(facts.names))
            if facts.pax_type:
                data[COL_PAX_TYPE] = facts.pax_type
            if facts.booking_date:
                data[COL_BOOKING_DATE] = facts.booking_date
            if facts.organization:
                data[COL_NAME] = facts.organization
            for i, leg in enumerate(facts.segments, start=1):
                h_route, h_flight, h_date = leg_headers(i)
                data[h_route] = leg["route"]
                data[h_flight] = leg["flight_no"]
                data[h_date] = leg["dep_date"]
            if facts.overflow:
                extra = {"overflow_legs": facts.overflow}

            # Base fare, and the tax derived from it. Both are left BLANK together
            # when the passenger file has no fare for this booking: `total - 0` would
            # assert that the whole transaction was tax, which the file never said.
            if facts.base_fare is not None:
                data[COL_BASE_FARE] = _money_str(facts.base_fare)
                if total is not None:
                    data[COL_TAX_TOTAL] = _money_str(total - facts.base_fare)
                    st.tax_derived += 1
            else:
                st.matched_without_fare += 1

        st.account_rows += 1
        out.append(MergedRow(role=ROLE_ACCOUNT, row_kind=ROW_KIND_ACCOUNT,
                             data=data, movement_kind=kind, extra=extra))

    st.currencies_seen = sorted(currencies)
    return out, st


def _pax_only(pax_rows, pax_columns, airline_code, st: MergeStats):
    """A passenger file with no account statement beside it.

    There is no transaction to hang the rows off, so it imports as an ordinary
    one-file statement: one row per (PNR, passenger), its own fare columns intact.
    """
    pax_idx = _index(pax_columns or [])
    c_pcur = _find(pax_idx, "currencycode")
    currencies: set[str] = set()
    out: list[MergedRow] = []
    for data in reshape_pax(pax_rows, pax_columns or [], airline_code=airline_code, stats=st):
        if c_pcur:
            cur = _clean(data.get(c_pcur))
            if cur:
                currencies.add(cur.upper())
        overflow = data.pop("__overflow_legs__", None)
        st.pax_rows += 1
        out.append(MergedRow(role=ROLE_PAX, row_kind=ROW_KIND_PAX, data=data,
                             extra={"overflow_legs": overflow} if overflow else None))
    st.currencies_seen = sorted(currencies)
    return out, st
