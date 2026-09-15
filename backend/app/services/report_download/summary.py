"""The Summary sheet: the totals and checks an accountant ties a report out with.

WHY AN ACCUMULATOR. The builder streams hundreds of thousands of Combined rows and never
holds them; Summary is written last (``workbook`` re-ranks it to second), so everything it
shows is folded in row by row here and rendered once at the end. Pure: no DB, no openpyxl
beyond the ``Block`` value type, Decimal arithmetic throughout.

Rules that shape every total:

* Only ``Counts In Net == "Yes"`` rows are totalled. A "No – …" row is money that is either
  already inside another row (a memo inside its BSP ADMA row, a TGQ ticket inside BSP) or
  not a settlement at all, so adding it would double count. Those rows are still counted and
  their net shown separately, and the ones that are real exposure get their own block.
* Totals are per currency and are never converted or added across currencies.
* A money column that no row filled stays blank — a printed 0.00 would claim a value.

The BSP tie-out sums BSP rows AS STORED and compares them with the statement's ``gt_*``
grand totals, which the parser wrote from the same rows at upload time
(``workers/bsp_tasks.py::_accumulate_gt``). Section bucketing mirrors that function and the
derived summary in ``api/v1/bsp.py``: settlement_section wins over section, first keyword of
ISSUE/REFUND/DEBIT/CREDIT found in the upper-cased banner. A difference therefore means rows
changed or went missing after parsing, not a parser quirk.

Linking metrics some callers never report explicitly are derived from the Combined rows
(``_derived_link_name``). A name passed to ``add_link_stat`` REPLACES the derived count of
the same name, so a builder that counts a metric itself never doubles it.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from app.services.report_download import columns as C
from app.services.report_download.normalize import parse_money
from app.services.report_download.registry import CATEGORY_ORDER, SOURCES
from app.services.report_download.workbook import Block

ZERO = Decimal("0")
TOLERANCE = Decimal("1.00")          # same ±1 per line as the upload-time reconciliation
BLANK = "(blank)"
NO_CURRENCY = "(no currency)"
NO_ROWS = "No rows"
OK_YES, OK_NO, OK_NA = "Yes", "No", "n/a"

# Block titles, in sheet order.
T_NET = "Net by Category, Source and Currency"
T_BY_TYPE = "By Transaction Type"
T_TIE_OUT = "BSP statement tie-out"
T_SUMMARY_VS_DETAILED = "BSP uploaded summary vs detailed"
T_EXPOSURE = "Not counted (exposure)"
T_LINKING = "Linking"
T_SIGNS = "Sign and identity checks"
T_TP_API = "Third Party API by product"
T_FLAGS = "Data flags"

NET_HEADERS = (
    "Category", "Source", "Currency", "Rows", "Rows counted", "Base Fare", "Total Taxes",
    "Gross", "Commission", "Net Payable", "Rows not counted", "Net Payable not counted",
)
_NET_KINDS = ("text", "text", "text", "int", "int", "money", "money", "money", "money", "money", "int", "money")

# (line key, label, BspStatement / BspSummaryStatement attribute)
TIE_OUT_LINES: tuple[tuple[str, str, str], ...] = (
    ("issues", "Issues", "gt_issues"),
    ("refunds", "Refunds", "gt_refunds"),
    ("debit_memos", "Debit memos", "gt_debit_memos"),
    ("credit_memos", "Credit memos", "gt_credit_memos"),
    ("std_comm", "Std comm", "gt_std_comm"),
    ("sup_comm", "Supp comm", "gt_sup_comm"),
    ("tax_on_comm", "Tax on comm", "gt_tax_on_comm"),
    ("balance_payable", "Balance payable", "gt_balance_payable"),
    ("doc_count", "Doc count", "gt_doc_count"),
)
_MONEY_LINES = tuple(k for k, _, _ in TIE_OUT_LINES if k != "doc_count")
_LINE_LABEL = {k: label for k, label, _ in TIE_OUT_LINES}
# First keyword found wins (workers/bsp_tasks.py::_SECTION_BUCKETS).
_SECTION_BUCKETS = (("ISSUE", "issues"), ("REFUND", "refunds"), ("DEBIT", "debit_memos"), ("CREDIT", "credit_memos"))

IDENTITY_PLUS = "Balance ≈ Txn + Std comm + Supp comm + Tax on comm"
IDENTITY_MINUS = "Balance ≈ Txn − Std comm − Supp comm + Tax on comm"
IDENTITY_BOTH = "Both (no commission on the row)"
IDENTITY_NEITHER = "Neither"
IDENTITY_SKIPPED = "Skipped (blank transaction amount or balance)"
_IDENTITY_ORDER = (IDENTITY_PLUS, IDENTITY_MINUS, IDENTITY_BOTH, IDENTITY_NEITHER, IDENTITY_SKIPPED)

EXP_TGQ = "TGQ GDS-only tickets"
EXP_MEMOS = "Memos not yet billed"
EXP_NDC = "NDC settled in BSP"
EXP_TP_CANCELLED = "Third Party cancelled (verify)"
_EXPOSURE_ORDER = (EXP_TGQ, EXP_MEMOS, EXP_NDC, EXP_TP_CANCELLED)
TGQ_NOT_IN_BSP, TGQ_OTHER_UPLOAD = "Not in BSP", "In another BSP upload"
TGQ_OUTSIDE_PERIOD, TGQ_UNMATCHABLE = "BSP row outside period", "Unmatchable"
_TGQ_BUCKET_ORDER = (TGQ_NOT_IN_BSP, TGQ_OTHER_UPLOAD, TGQ_OUTSIDE_PERIOD, TGQ_UNMATCHABLE)
_TGQ_BY_REASON = {
    C.NET_TGQ_NOT_IN_BSP: TGQ_NOT_IN_BSP,
    C.NET_TGQ_OTHER_UPLOAD: TGQ_OTHER_UPLOAD,
    C.NET_TGQ_OUTSIDE_PERIOD: TGQ_OUTSIDE_PERIOD,
    C.NET_TGQ_UNMATCHABLE: TGQ_UNMATCHABLE,
}
NDC_THIS_REPORT, NDC_OTHER_UPLOAD = "Settled in BSP (this report)", "In another BSP upload"

# Derived linking metric names (see module docstring).
LINK_TGQ_ENRICHED = "BSP rows TGQ-enriched ({})"
LINK_MEMO_IN_BILLING = "Memos in BSP billing (this report)"
LINK_MEMO_OTHER_UPLOAD = "Memos in another BSP upload"
LINK_MEMO_OTHER_PERIOD = "Memos in BSP billing (other period)"
LINK_MEMO_PENDING = "Memos not yet billed in BSP"
LINK_NDC_IN_BSP = "NDC in BSP (this report)"
LINK_NDC_OTHER_UPLOAD = "NDC in another BSP upload"
LINK_LEDGER_LINKED = "LCC ledger rows linked to LCC Detailed"
LINK_SUPERSEDED = "Superseded rows ({})"
LINK_AMBIGUOUS = "LINK_AMBIGUOUS"
_MEMO_LINKS = (
    (C.NET_MEMO_IN_BILLING, LINK_MEMO_IN_BILLING),
    (C.NET_MEMO_OTHER_UPLOAD, LINK_MEMO_OTHER_UPLOAD),
    (C.NET_MEMO_OTHER_PERIOD, LINK_MEMO_OTHER_PERIOD),
    (C.NET_MEMO_NOT_BILLED, LINK_MEMO_PENDING),
)
# Display order of linking metrics by name prefix (design §A.2 block 6); others follow A-Z.
_LINK_PREFIX_ORDER = (
    "BSP rows TGQ-enriched", "TGQ tickets suppressed", "Duplicate TGQ", "Memos", "NDC",
    "LCC ledger", "Superseded rows", LINK_AMBIGUOUS,
)

MEMO_KEYS = frozenset({"adm", "acm", "ra"})
LEDGER_KEYS = frozenset({"lcc-di", "lcc-divided-pnr", "lcc-flown-report", "lcc-cta-bta"})
_LABEL_TO_KEY = {s.label: s.key for s in SOURCES}
_KEY_TO_LABEL = {s.key: s.label for s in SOURCES}
_SOURCE_RANK = {s.label: i for i, s in enumerate(SOURCES)}
_CATEGORY_RANK = {c: i for i, c in enumerate(CATEGORY_ORDER)}
_TYPE_RANK = {t: i for i, t in enumerate(C.TXN_TYPES)}
_FLAG_RANK = {f: i for i, f in enumerate(C.FLAG_LEGEND)}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_JSON_MAP_LIMIT = 200                 # keeps to_json() small whatever names callers invent


# ── small helpers (also used by readme.py) ───────────────────────────────────

def fmt_date(d: Optional[date]) -> Optional[str]:
    """DD-MMM-YYYY without the process locale (``%b`` is locale-dependent)."""
    if d is None:
        return None
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def fmt_datetime(dt: datetime) -> str:
    return f"{fmt_date(dt)} {dt:%H:%M:%S}"


def period_text(date_from: Optional[date], date_to: Optional[date]) -> Optional[str]:
    if date_from is None and date_to is None:
        return None
    if date_to is None or date_to == date_from:
        return fmt_date(date_from)
    if date_from is None:
        return f"until {fmt_date(date_to)}"
    return f"{fmt_date(date_from)} to {fmt_date(date_to)}"


def _get(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _text(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = (v if isinstance(v, str) else str(v)).strip()
    return s or None


def _money(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    if type(v) is Decimal:
        return v if v.is_finite() else None
    return parse_money(v)


def _madd(total: Optional[Decimal], v: Optional[Decimal]) -> Optional[Decimal]:
    if v is None:
        return total
    return v if total is None else total + v


def _is_counted(counts_in_net: str) -> bool:
    return counts_in_net.startswith(C.NET_YES)


def _flag_list(v: Any) -> Iterable[str]:
    if not v:
        return ()
    if isinstance(v, str):
        return [f for f in (p.strip() for p in v.split(";")) if f]
    return [f for f in (_text(p) for p in v) if f]


def _category_sort(cat: str) -> tuple:
    return (_CATEGORY_RANK.get(cat, len(_CATEGORY_RANK)), cat)


def _source_sort(label: str) -> tuple:
    return (_SOURCE_RANK.get(label, len(_SOURCE_RANK)), label)


def _currency_sort(cur: str) -> tuple:
    # INR first (the home currency of every current tenant), blanks last.
    return (0 if cur == "INR" else 2 if cur == NO_CURRENCY else 1, cur)


def _type_sort(t: str) -> tuple:
    return (_TYPE_RANK.get(t, len(_TYPE_RANK)), t)


def _fop_bucket(v: Any) -> str:
    fop = (_text(v) or "").upper()
    return fop if fop in ("CA", "CC") else "Other"


def section_line(section: Any) -> Optional[str]:
    """Tie-out line key for a section banner or keyword ("ISSUES", "DEBIT MEMOS", "REFUND")."""
    sec = (_text(section) or "").upper()
    if not sec:
        return None
    return next((line for kw, line in _SECTION_BUCKETS if kw in sec), None)


def _pct(n: int, base: int) -> Optional[Decimal]:
    if base <= 0:
        return None
    return (Decimal(n) * 100 / Decimal(base)).quantize(Decimal("0.1"))


def _json_map(d: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        if len(out) >= _JSON_MAP_LIMIT:
            break
        out[str(k)[:120]] = v
    return out


# ── accumulators ─────────────────────────────────────────────────────────────

class _NetTotals:
    __slots__ = ("rows", "counted", "base_fare", "total_taxes", "gross", "commission", "net",
                 "not_counted", "net_not_counted")

    def __init__(self) -> None:
        self.rows = 0
        self.counted = 0
        self.not_counted = 0
        self.base_fare: Optional[Decimal] = None
        self.total_taxes: Optional[Decimal] = None
        self.gross: Optional[Decimal] = None
        self.commission: Optional[Decimal] = None
        self.net: Optional[Decimal] = None
        self.net_not_counted: Optional[Decimal] = None

    def merge(self, o: "_NetTotals") -> None:
        self.rows += o.rows
        self.counted += o.counted
        self.not_counted += o.not_counted
        self.base_fare = _madd(self.base_fare, o.base_fare)
        self.total_taxes = _madd(self.total_taxes, o.total_taxes)
        self.gross = _madd(self.gross, o.gross)
        self.commission = _madd(self.commission, o.commission)
        self.net = _madd(self.net, o.net)
        self.net_not_counted = _madd(self.net_not_counted, o.net_not_counted)

    def cells(self) -> list[Any]:
        return [self.rows, self.counted, self.base_fare, self.total_taxes, self.gross,
                self.commission, self.net, self.not_counted, self.net_not_counted]


class _Sums:
    """rows / rows counted / Σ gross / Σ net — the shape of the smaller blocks."""
    __slots__ = ("rows", "counted", "gross", "net")

    def __init__(self) -> None:
        self.rows = 0
        self.counted = 0
        self.gross: Optional[Decimal] = None
        self.net: Optional[Decimal] = None


@dataclass
class _Statement:
    statement_id: str
    header: Any = None
    summary_header: Any = None
    partial: bool = False
    sums: dict[str, Decimal] = field(default_factory=lambda: {k: ZERO for k in _MONEY_LINES})
    doc_count: int = 0


class SummaryAccumulator:
    """Fold Combined rows, BSP rows and linking counts into the Summary sheet blocks."""

    def __init__(self) -> None:
        self._rows = 0
        self._counted = 0
        self._net: dict[tuple[str, str, str], _NetTotals] = {}
        self._by_category: dict[str, list[int]] = {}
        self._by_source: dict[str, list[int]] = {}
        self._source_rows: Counter[str] = Counter()          # by source key (label when unknown)
        self._by_type: dict[tuple[str, str, str], _Sums] = {}
        self._tp_api: dict[tuple[str, str], _Sums] = {}
        self._exposure: dict[tuple[str, str, str], _Sums] = {}
        self._flags: Counter[str] = Counter()
        self._flag_sources: dict[str, Counter[str]] = {}
        self._derived_links: Counter[str] = Counter()
        self._links: dict[str, int] = {}
        self._statements: dict[str, _Statement] = {}
        self._signs: dict[tuple[str, str, str], list[int]] = {}
        self._identity: Counter[str] = Counter()

    # ── Combined rows ────────────────────────────────────────────────────────

    def add_combined(self, row: Mapping[str, Any], source_key: Optional[str] = None) -> None:
        """One Combined row (keys = ``columns.COMBINED_KEYS``). ``source_key`` is the registry
        key; when omitted it is looked up from the row's Source Type label."""
        cat = _text(row.get("category")) or BLANK
        stype = _text(row.get("source_type")) or BLANK
        key = source_key or _LABEL_TO_KEY.get(stype)
        cur = (_text(row.get("currency")) or "").upper() or NO_CURRENCY
        cin_raw = row.get("counts_in_net")
        cin = cin_raw.strip() if isinstance(cin_raw, str) else ""
        counted = _is_counted(cin)
        net = _money(row.get("net_payable"))
        gross = _money(row.get("gross_amount"))

        self._rows += 1
        self._source_rows[key or stype] += 1
        for bucket, name in ((self._by_category, cat), (self._by_source, stype)):
            pair = bucket.get(name)
            if pair is None:
                pair = bucket[name] = [0, 0]
            pair[0] += 1
            pair[1] += counted

        t = self._net.get((cat, stype, cur))
        if t is None:
            t = self._net[(cat, stype, cur)] = _NetTotals()
        t.rows += 1
        if counted:
            self._counted += 1
            t.counted += 1
            t.base_fare = _madd(t.base_fare, _money(row.get("base_fare")))
            t.total_taxes = _madd(t.total_taxes, _money(row.get("total_taxes")))
            t.gross = _madd(t.gross, gross)
            t.commission = _madd(t.commission, _money(row.get("commission")))
            t.net = _madd(t.net, net)
        else:
            t.not_counted += 1
            t.net_not_counted = _madd(t.net_not_counted, net)

        txn = _text(row.get("transaction_type")) or BLANK
        self._add_sums(self._by_type, (cat, cur, txn), counted, gross, net)
        if key == "tp-api":
            product = _text(row.get("product")) or BLANK
            self._add_sums(self._tp_api, (product, cur), counted, gross, net)

        flags = _flag_list(row.get("data_flags"))
        for flag in flags:
            self._flags[flag] += 1
            per = self._flag_sources.get(flag)
            if per is None:
                per = self._flag_sources[flag] = Counter()
            per[stype] += 1

        if not counted and cin != C.NET_SUPERSEDED:
            exposure = self._exposure_bucket(key, stype, cin, row)
            if exposure is not None:
                self._add_sums(self._exposure, (exposure[0], exposure[1], cur), False, gross, net, every_row=True)
        self._derive_links(key, stype, cin, row, flags)

    @staticmethod
    def _add_sums(
        target: dict, k: tuple, counted: bool, gross: Optional[Decimal], net: Optional[Decimal],
        *, every_row: bool = False,
    ) -> None:
        """Σ over counted rows only, or over every row added (exposure rows never count)."""
        s = target.get(k)
        if s is None:
            s = target[k] = _Sums()
        s.rows += 1
        if counted:
            s.counted += 1
        if counted or every_row:
            s.gross = _madd(s.gross, gross)
            s.net = _madd(s.net, net)

    @staticmethod
    def _exposure_bucket(key: Optional[str], stype: str, cin: str, row: Mapping[str, Any]) -> Optional[tuple[str, str]]:
        if key == "tgq-hmpr":
            nib = _text(row.get("not_in_bsp")) or ""
            if nib == "Yes":
                return EXP_TGQ, TGQ_NOT_IN_BSP
            if nib.startswith("In another BSP upload"):
                return EXP_TGQ, TGQ_OTHER_UPLOAD
            if nib.startswith("BSP row outside period"):
                return EXP_TGQ, TGQ_OUTSIDE_PERIOD
            if nib.startswith("Unknown"):
                return EXP_TGQ, TGQ_UNMATCHABLE
            return EXP_TGQ, _TGQ_BY_REASON.get(cin, cin or BLANK)
        if key in MEMO_KEYS and cin.startswith(C.NET_MEMO_NOT_BILLED):
            return EXP_MEMOS, f"{_KEY_TO_LABEL[key]} – {_memo_status(cin, row)}"
        if key == "ndc":
            if cin == C.NET_NDC_IN_BSP:
                return EXP_NDC, NDC_THIS_REPORT
            if cin == C.NET_MEMO_OTHER_UPLOAD:
                return EXP_NDC, NDC_OTHER_UPLOAD
            return None
        if cin == C.NET_CANCELLED_VERIFY:
            return EXP_TP_CANCELLED, stype
        return None

    def _derive_links(self, key: Optional[str], stype: str, cin: str, row: Mapping[str, Any], flags: Iterable[str]) -> None:
        d = self._derived_links
        if key == "bsp":
            te = _text(row.get("tgq_enriched")) or ""
            if te.startswith("Yes"):
                method = te[3:].strip().strip("()").strip() or "unspecified"
                d[LINK_TGQ_ENRICHED.format(method)] += 1
        elif key in MEMO_KEYS:
            for reason, name in _MEMO_LINKS:
                if cin.startswith(reason):
                    d[name] += 1
                    break
        elif key == "ndc":
            if cin == C.NET_NDC_IN_BSP:
                d[LINK_NDC_IN_BSP] += 1
            elif cin == C.NET_MEMO_OTHER_UPLOAD:
                d[LINK_NDC_OTHER_UPLOAD] += 1
        elif key in LEDGER_KEYS and _text(row.get("linked_document")):
            d[LINK_LEDGER_LINKED] += 1
        if cin == C.NET_SUPERSEDED:
            d[LINK_SUPERSEDED.format(stype)] += 1
        if LINK_AMBIGUOUS in flags:
            d[LINK_AMBIGUOUS] += 1

    # ── BSP statements ───────────────────────────────────────────────────────

    def set_bsp_statement(self, statement_id: str, header: Any, summary_header: Any, scope: str) -> None:
        """Register an included BSP statement. ``scope`` "full" (whole statement) or "partial"
        (only rows issued in the period, so a variance is expected and OK shows n/a)."""
        st = self._statements.get(statement_id)
        if st is None:
            st = self._statements[statement_id] = _Statement(statement_id)
        st.header = header
        st.summary_header = summary_header
        st.partial = (scope or "").strip().lower() in ("partial", "issue_date")

    def add_bsp_row(self, statement_id: str, row: Any, section: Optional[str]) -> None:
        """One BSP Detailed row, values as stored. ``section`` is the settlement section (or its
        ISSUE/REFUND/DEBIT/CREDIT keyword); when None the row's raw_data is read instead."""
        st = self._statements.get(statement_id)
        if st is None:
            st = self._statements[statement_id] = _Statement(statement_id)
        if section is None:
            raw = _get(row, "raw_data")
            if isinstance(raw, Mapping):
                section = raw.get("settlement_section") or raw.get("section")
        txn = _money(_get(row, "transaction_amount"))
        std = _money(_get(row, "standard_commission_amount"))
        supp = _money(_get(row, "supplier_discount_amount"))
        toc = _money(_get(row, "tax_on_commission"))
        bal = _money(_get(row, "balance_payable"))

        line = section_line(section)
        sums = st.sums
        if line is not None and txn is not None:
            sums[line] += txn
        if std is not None:
            sums["std_comm"] += std
        if supp is not None:
            sums["sup_comm"] += supp
        if toc is not None:
            sums["tax_on_comm"] += toc
        if bal is not None:
            sums["balance_payable"] += bal
        st.doc_count += 1

        ttype = (_text(_get(row, "transaction_type")) or BLANK).upper()
        bucket = f"{ttype} × {_fop_bucket(_get(row, 'form_of_payment'))}"
        self.add_sign_check("BSP", bucket, "Transaction Amount", txn)
        self.add_sign_check("BSP", bucket, "Balance Payable", bal)

        # Which remittance identity the printed signs follow; never used to rewrite a value.
        if txn is None or bal is None:
            self._identity[IDENTITY_SKIPPED] += 1
            return
        comm = (std or ZERO) + (supp or ZERO)
        base = txn + (toc or ZERO)
        plus = abs(bal - (base + comm)) <= TOLERANCE
        minus = abs(bal - (base - comm)) <= TOLERANCE
        self._identity[
            IDENTITY_BOTH if plus and minus else IDENTITY_PLUS if plus else IDENTITY_MINUS if minus else IDENTITY_NEITHER
        ] += 1

    # ── generic counters ─────────────────────────────────────────────────────

    def add_link_stat(self, name: str, n: int = 1) -> None:
        self._links[name] = self._links.get(name, 0) + n

    def add_sign_check(self, source: str, bucket: str, field: str, value: Any) -> None:
        """Count one stored value as < 0 / > 0 / = 0. Blank or unreadable values are skipped."""
        v = _money(value)
        if v is None:
            return
        k = (source, bucket, field)
        counts = self._signs.get(k)
        if counts is None:
            counts = self._signs[k] = [0, 0, 0]
        counts[0 if v < 0 else 1 if v > 0 else 2] += 1

    # ── output ───────────────────────────────────────────────────────────────

    def blocks(self) -> list[Block]:
        out = [self._net_block()]
        for build in (
            self._by_type_block, self._tie_out_block, self._summary_vs_detailed_block,
            self._exposure_block, self._linking_block, self._signs_block, self._tp_api_block,
            self._flags_block,
        ):
            block = build()
            if block is not None and block.rows:
                out.append(block)
        return out

    def to_json(self) -> dict[str, Any]:
        """A small JSON-safe digest for ``report_exports.summary`` (Decimal → str)."""
        grand = self._grand_totals()
        oks = [ok for _, rows in self._tie_out_rows() for ok in rows if ok != OK_NA]
        return {
            "rows": self._rows,
            "counted_rows": self._counted,
            "by_category": {
                cat: {"rows": v[0], "counted": v[1]}
                for cat, v in sorted(self._by_category.items(), key=lambda kv: _category_sort(kv[0]))
            },
            "by_source": _json_map({
                s: {"rows": v[0], "counted": v[1]}
                for s, v in sorted(self._by_source.items(), key=lambda kv: _source_sort(kv[0]))
            }),
            # Rounded to paise: some supplier exports store Excel float artefacts
            # (52933.994399999996), which would otherwise show in the history API.
            "net_by_currency": {
                cur: str(t.net.quantize(Decimal("0.01"))) for cur, t in grand.items() if t.net is not None
            },
            "link_stats": _json_map(self._link_counts()),
            "flag_counts": _json_map(dict(sorted(self._flags.items(), key=lambda kv: (-kv[1], kv[0])))),
            "tie_out_ok": (all(ok == OK_YES for ok in oks) if oks else None),
        }

    # ── block builders ───────────────────────────────────────────────────────

    def _grand_totals(self) -> dict[str, _NetTotals]:
        grand: dict[str, _NetTotals] = {}
        for (_, _, cur), t in self._net.items():
            grand.setdefault(cur, _NetTotals()).merge(t)
        return dict(sorted(grand.items(), key=lambda kv: _currency_sort(kv[0])))

    def _net_block(self) -> Block:
        rows: list[list[Any]] = []
        groups: dict[tuple[str, str], list[tuple[str, _NetTotals]]] = {}
        for (cat, stype, cur), t in self._net.items():
            groups.setdefault((cat, cur), []).append((stype, t))
        for cat, cur in sorted(groups, key=lambda k: (_category_sort(k[0]), _currency_sort(k[1]))):
            sub = _NetTotals()
            for stype, t in sorted(groups[(cat, cur)], key=lambda it: _source_sort(it[0])):
                rows.append([cat, stype, cur, *t.cells()])
                sub.merge(t)
            rows.append([cat, "Subtotal", cur, *sub.cells()])
        for cur, t in self._grand_totals().items():
            rows.append(["All categories", "Grand total", cur, *t.cells()])
        if not rows:
            rows.append([NO_ROWS] + [None] * (len(NET_HEADERS) - 1))
        return Block(T_NET, NET_HEADERS, rows, _NET_KINDS)

    def _by_type_block(self) -> Block:
        rows = [
            [cat, cur, txn, s.rows, s.counted, s.gross, s.net]
            for (cat, cur, txn), s in sorted(
                self._by_type.items(),
                key=lambda kv: (_category_sort(kv[0][0]), _currency_sort(kv[0][1]), _type_sort(kv[0][2])),
            )
        ]
        return Block(
            T_BY_TYPE,
            ("Category", "Currency", "Transaction Type", "Rows", "Rows counted", "Gross (counted)", "Net Payable (counted)"),
            rows, ("text", "text", "text", "int", "int", "money", "money"),
        )

    def _tie_out_rows(self) -> list[tuple[list[list[Any]], list[str]]]:
        """Per statement: (block rows, OK values)."""
        out = []
        for st in self._statements.values():
            h = st.header
            file_name = _text(_get(h, "file_name")) or _text(_get(h, "statement_name")) or st.statement_id
            period = period_text(_get(h, "period_from"), _get(h, "period_to"))
            scope = "Partial (rows issued in period)" if st.partial else "Whole statement"
            rows, oks = [], []
            for key, label, attr in TIE_OUT_LINES:
                stmt = _money(_get(h, attr))
                if key == "doc_count":
                    report: Any = st.doc_count
                    if stmt is not None and stmt == stmt.to_integral_value():
                        stmt = int(stmt)
                    variance = None if stmt is None else report - stmt
                    good = variance == 0          # a document count has no rounding tolerance
                else:
                    report = st.sums[key]
                    variance = None if stmt is None else report - stmt
                    good = variance is not None and abs(variance) <= TOLERANCE
                ok = OK_NA if st.partial or stmt is None else OK_YES if good else OK_NO
                rows.append([file_name, period, scope, label, report, stmt, variance, ok])
                oks.append(ok)
            out.append((rows, oks))
        return out

    def _tie_out_block(self) -> Optional[Block]:
        if not self._statements:
            return None
        rows = [r for block_rows, _ in self._tie_out_rows() for r in block_rows]
        return Block(
            T_TIE_OUT,
            ("File", "Period", "Scope", "Line", "Report Σ", "Statement", "Variance", "OK"),
            rows, ("text", "text", "text", "text", "money", "money", "money", "text"),
        )

    def _summary_vs_detailed_block(self) -> Optional[Block]:
        rows: list[list[Any]] = []
        for st in self._statements.values():
            sm = st.summary_header
            if sm is None:
                continue
            h = st.header
            summary_file = _text(_get(sm, "file_name"))
            detailed_file = _text(_get(h, "file_name")) or st.statement_id
            period = period_text(_get(sm, "period_from"), _get(sm, "period_to")) or period_text(
                _get(h, "period_from"), _get(h, "period_to"))
            status = _text(_get(sm, "match_status")) or "pending"
            detail = _get(sm, "match_detail")
            if not isinstance(detail, Mapping) or not detail:
                rows.append([summary_file, detailed_file, period, status, None, None, None, None, None])
                continue
            known = [k for k in _MONEY_LINES if k in detail]
            for key in known + sorted(k for k in detail if k not in _MONEY_LINES):
                item = detail.get(key)
                item = item if isinstance(item, Mapping) else {}
                ok = item.get("ok")
                rows.append([
                    summary_file, detailed_file, period, status, _LINE_LABEL.get(key, key),
                    _money(item.get("summary")), _money(item.get("detail")), _money(item.get("variance")),
                    OK_YES if ok is True else OK_NO if ok is False else None,
                ])
        if not rows:
            return None
        return Block(
            T_SUMMARY_VS_DETAILED,
            ("Summary File", "Detailed File", "Period", "Match Status", "Line", "Summary PDF", "Detailed", "Variance", "OK"),
            rows, ("text", "text", "text", "text", "text", "money", "money", "money", "text"),
        )

    def _exposure_block(self) -> Block:
        def order(k: tuple[str, str, str]) -> tuple:
            section, bucket, cur = k
            s_rank = _EXPOSURE_ORDER.index(section) if section in _EXPOSURE_ORDER else len(_EXPOSURE_ORDER)
            b_rank = _TGQ_BUCKET_ORDER.index(bucket) if bucket in _TGQ_BUCKET_ORDER else len(_TGQ_BUCKET_ORDER)
            # memo buckets "ADM – <status>" follow registry order (ADM, ACM, RA)
            return (s_rank, b_rank, _source_sort(bucket.split(" – ", 1)[0]), bucket, _currency_sort(cur))

        rows = [
            [section, bucket, cur, s.rows, s.gross, s.net]
            for (section, bucket, cur), s in sorted(self._exposure.items(), key=lambda kv: order(kv[0]))
        ]
        return Block(
            T_EXPOSURE, ("Exposure", "Bucket", "Currency", "Rows", "Gross", "Net Payable"),
            rows, ("text", "text", "text", "int", "money", "money"),
        )

    def _link_counts(self) -> dict[str, int]:
        merged: dict[str, int] = dict(self._derived_links)
        merged.update(self._links)            # an explicit count replaces the derived one
        return dict(sorted(merged.items(), key=lambda kv: _link_sort(kv[0])))

    def _link_base(self, name: str, counts: Mapping[str, int]) -> tuple[Optional[int], Optional[str]]:
        rows = self._source_rows
        if name.startswith("BSP rows"):
            return rows["bsp"], "BSP rows"
        if "TGQ" in name and "suppressed" in name.lower():
            suppressed = sum(n for k, n in counts.items() if "TGQ" in k and "suppressed" in k.lower())
            return rows["tgq-hmpr"] + suppressed, "TGQ tickets"
        if name.startswith("Memos"):
            return sum(rows[k] for k in MEMO_KEYS), "ADM / ACM / RA rows"
        if name.startswith("NDC"):
            return rows["ndc"], "NDC rows"
        if name.startswith("LCC ledger"):
            return sum(rows[k] for k in LEDGER_KEYS), "LCC ledger rows"
        if name.startswith("Superseded rows (") and name.endswith(")"):
            label = name[len("Superseded rows ("):-1]
            key = _LABEL_TO_KEY.get(label, label)
            return rows[key], f"{_KEY_TO_LABEL.get(key, label)} rows"
        if name == LINK_AMBIGUOUS:
            return self._rows, "All Combined rows"
        return None, None

    def _linking_block(self) -> Block:
        counts = self._link_counts()
        rows = []
        for name, n in counts.items():
            base, of = self._link_base(name, counts)
            pct = _pct(n, base) if base is not None else None
            rows.append([name, n, pct, of if pct is not None else None])
        return Block(T_LINKING, ("Metric", "Count", "%", "Of"), rows, ("text", "int", "text", "text"))

    def _signs_block(self) -> Block:
        rows: list[list[Any]] = [
            [source, bucket, fld, c[0], c[1], c[2], c[0] + c[1] + c[2]]
            for (source, bucket, fld), c in sorted(self._signs.items())
        ]
        for label in _IDENTITY_ORDER:
            if self._identity[label]:
                rows.append(["BSP", "Remittance identity", label, None, None, None, self._identity[label]])
        return Block(
            T_SIGNS, ("Source", "Bucket", "Field / Test", "< 0", "> 0", "= 0", "Rows"),
            rows, ("text", "text", "text", "int", "int", "int", "int"),
        )

    def _tp_api_block(self) -> Block:
        rows = [
            [product, cur, s.rows, s.counted, s.net]
            for (product, cur), s in sorted(self._tp_api.items(), key=lambda kv: (kv[0][0], _currency_sort(kv[0][1])))
        ]
        return Block(
            T_TP_API, ("Product", "Currency", "Rows", "Rows counted", "Net Payable (counted)"),
            rows, ("text", "text", "int", "int", "money"),
        )

    def _flags_block(self) -> Block:
        rows = []
        for flag, n in sorted(self._flags.items(), key=lambda kv: (-kv[1], _FLAG_RANK.get(kv[0], len(_FLAG_RANK)), kv[0])):
            top = sorted(self._flag_sources[flag].items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            rows.append([flag, C.FLAG_LEGEND.get(flag), n, ", ".join(f"{s} ({c})" for s, c in top)])
        return Block(T_FLAGS, ("Flag", "Meaning", "Rows", "Top sources"), rows, ("text", "text", "int", "text"))


def _memo_status(cin: str, row: Mapping[str, Any]) -> str:
    """"No – not yet billed in BSP (status: PENDING, sent to DPC)" → "PENDING, sent to DPC"."""
    idx = cin.find("(status:")
    if idx >= 0:
        inner = cin[idx + len("(status:"):].strip()
        if inner.endswith(")"):
            inner = inner[:-1].strip()
        if inner:
            return inner
    return _text(row.get("status")) or BLANK


def _link_sort(name: str) -> tuple:
    for i, prefix in enumerate(_LINK_PREFIX_ORDER):
        if name.startswith(prefix):
            return (i, name)
    return (len(_LINK_PREFIX_ORDER), name)
