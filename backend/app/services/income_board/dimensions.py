"""Turning every source's vocabulary into the board's one.

Every function here exists because two places in this codebase would otherwise disagree
about the same row. The rule throughout: DERIVE the mapping from the constant the money
engine already uses, never retype it. A copied set drifts on the first edit, and the
symptom is a dashboard that quietly contradicts the incentive it is displaying.

The SQL builders return CASE expressions generated FROM those same Python constants, so
adding a transaction type to `bsp_commission._SKIP_TXN` changes the projection too,
without anybody remembering to come here.

THE VOCABULARY IS PER SOURCE, AND THAT WAS LEARNED THE HARD WAY. `txn_class_sql` used to
take a column and generate one CASE out of BSP's transaction types. But BSP is the only
source that writes BSP's vocabulary:

    bsp            transaction_type   TKTT | RFND | ADM | ACM | EXCH | CANX …
    tp-gds/tp-lcc  ticket_status      CONFIRMED | REFUNDED | CANCELLED | PENDING …
    lcc-detailed   bill_kind          sale | refund | payment
    ndc            txn_type           PAID_BOOKING | TICKETING | REFUND | REFUND_SEAT …
    tp-api         booking_status     Confirmed | Cancelled | Refunded | Pending …

Not one of the non-BSP strings is in `_ISSUE_TXN` or `_REFUND_TXN`, so every one of those
rows classified as `other`, and `measures.gross_revenue()` — which filters on
sale|refund — returned BSP-only figures from the day the table shipped. Nothing errored;
three-quarters of the gross was simply absent. `TestTransactionClass` now feeds the
Python classifier and the compiled SQL the same literals FOR EACH SOURCE, which is the
test that would have caught it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import literal_column
from sqlalchemy.dialects import postgresql

from app.models.income_board import (
    SOURCE_BSP, SOURCE_LCC_DETAILED, SOURCE_NDC, SOURCE_TP_API, SOURCE_TP_GDS,
    SOURCE_TP_LCC,
    TXN_ADJUSTMENT, TXN_CREDIT_MEMO, TXN_DEBIT_MEMO, TXN_OTHER, TXN_REFUND, TXN_SALE,
)
from app.services import markup_categories as _mc
from app.services import tp_api_spec as _tp_spec
from app.services import ndc_billing_projection as _ndc_proj
from app.services.ndc_billing_projection import REFUND_TXN as _NDC_REFUND_TXN
from app.services.tp_api_billing_projection import (
    CANCELLED as _TPA_CANCELLED_KIND, NEEDS_REVIEW as _TPA_NEEDS_REVIEW,
    NO_AMOUNT as _TPA_NO_AMOUNT, NO_CATEGORY as _TPA_NO_CATEGORY,
    PENDING as _TPA_PENDING_KIND, REFUND as _TPA_REFUND, SALE as _TPA_SALE,
    TBO_CREDIT_SERIES as _TPA_CREDIT_SERIES,
    _CANCELLED_STATUSES as _TPA_CANCELLED, _NIL as _TPA_NIL,
    _PENDING_STATUS as _TPA_PENDING,
)

def qq(field: str) -> str:
    """`.data->>'field'`, so the quoting lives in one place."""
    return f".data->>'{field}'"


# The two regexes ndc_billing_projection classifies a line's product with. Their `.pattern`
# is taken rather than retyped, and both are plain POSIX-compatible alternations, so
# Postgres's `~` reads them the same way Python's `re` does.
_NDC_FLIGHT_PRODUCT = _ndc_proj._FLIGHT_PRODUCT.pattern
_NDC_ANCILLARY_TXN = _ndc_proj._ANCILLARY_TXN.pattern

_TPA_TBO_LABEL = _tp_spec.VENDOR_LABELS[_tp_spec.TBO]
_TPA_CATEGORY_ALIASES = frozenset(_mc.CATEGORY_ALIASES)
# Everything `classify` refuses to bill. Derived rather than listed so a sixth verdict
# cannot appear there and quietly start counting as a sale here.
_TPA_NOT_BILLABLE = frozenset({
    _TPA_NO_CATEGORY, _TPA_PENDING_KIND, _TPA_CANCELLED_KIND,
    _TPA_NEEDS_REVIEW, _TPA_NO_AMOUNT,
})
from app.services.bsp_commission import _ISSUE_TXN, _REFUND_TXN, _SKIP_TXN, stat_to_segment
from app.services.deal_matching import segment_letter
from app.services.lcc_merge import MOVEMENT_BALANCE
from app.services.report_download import columns as C
from app.services.report_download.normalize import date_key_sql
# Private names on purpose, and with precedent: report_download/mappers/third_party.py
# already reaches into tpb's classification constants for the same reason. Importing the
# authority is the point — a public copy would be a second definition.
from app.services.commission.third_party import _REFUND_STATUS, _SKIP_STATUS
from app.services.report_download.mappers.third_party import (
    _DATE_FIELDS, _IDENTITY_FIELDS, _VOID_PENALTY_SLACK, _VOID_STATUSES,
)

# The memo families, split out of _SKIP_TXN. bsp_commission treats all of these the
# same way — none is a sale — but the board has to tell a debit memo from a credit memo,
# because ADM exposure is a number an operator acts on and ACM is money coming back.
_DEBIT_MEMO = {"ADM", "ADMA", "ADMD"}
_CREDIT_MEMO = {"ACM", "ACMA", "ACMD"}

# lcc-detailed writes `bill_kind or payment_status`, and commission/lcc_detailed._KIND
# maps the three bill kinds onto issue/refund/skip. Derived from that dict rather than
# retyped so a fourth bill kind cannot appear there and be silently classified `other`
# here. Upper-cased because every comparison below is.
from app.services.commission.lcc_detailed import _KIND as _LCC_BILL_KIND  # noqa: E402
from app.services.commission.calc_row import (  # noqa: E402
    KIND_ISSUE, KIND_REFUND, KIND_SKIP,
)

_KIND_TO_CLASS = {KIND_ISSUE: TXN_SALE, KIND_REFUND: TXN_REFUND, KIND_SKIP: TXN_ADJUSTMENT}


@dataclass(frozen=True)
class _Vocab:
    """One source's transaction vocabulary, mapped onto the board's `txn_class`.

    `buckets` is ordered — the first set containing the value wins — and `fallback` is
    what an unrecognised value means, which is NOT the same answer for every source and
    must not be flattened into one. BSP falls through to `other`: a settlement type
    nobody recognises is not something to book as revenue. The consolidator sources fall
    through to `sale`, deliberately, because `commission/third_party.classify` does —
    "a whitelist-only issue rule would silently zero a whole file the first time one of
    them wrote 'TICKETED' instead of 'CONFIRMED'".

    `punctuation_folds` matches ndc_spec.norm_txn, which reads "Paid Booking",
    "paid-booking" and " PAID_BOOKING " as one value because another airline's portal
    exporting the same fact with a space is the same transaction. Only NDC needs it;
    turning it on everywhere would make BSP's "ON HOLD" and "ON_HOLD" the same string in
    a vocabulary that has only ever seen one of them.
    """
    buckets: tuple[tuple[str, frozenset[str]], ...]
    fallback: str
    punctuation_folds: bool = False

    def normalise(self, value: str | None) -> str:
        v = str(value or "").strip().upper()
        if self.punctuation_folds:
            v = re.sub(r"[^A-Z0-9]+", "_", v).strip("_")
        return v

    def sql_value(self, col: str) -> str:
        base = f"upper(btrim(coalesce({col}, '')))"
        if not self.punctuation_folds:
            return base
        return f"btrim(regexp_replace({base}, '[^A-Z0-9]+', '_', 'g'), '_')"


def _up(values) -> frozenset[str]:
    return frozenset(str(v).strip().upper() for v in values)


_TP_VOCAB = _Vocab(
    buckets=(
        (TXN_REFUND, _up(_REFUND_STATUS)),
        # Cancelled / void / failed / pending / hold / expired / rejected. Not a sale and
        # not a refund: a settlement event carrying no fare, which is what `adjustment`
        # means here and what keeps it out of every revenue denominator.
        (TXN_ADJUSTMENT, _up(_SKIP_STATUS)),
    ),
    fallback=TXN_SALE,
)

_VOCABS: dict[str, _Vocab] = {
    SOURCE_BSP: _Vocab(
        buckets=(
            (TXN_SALE, _up(_ISSUE_TXN)),
            (TXN_REFUND, _up(_REFUND_TXN)),
            (TXN_DEBIT_MEMO, _up(_DEBIT_MEMO)),
            (TXN_CREDIT_MEMO, _up(_CREDIT_MEMO)),
            (TXN_ADJUSTMENT, _up(_SKIP_TXN - _DEBIT_MEMO - _CREDIT_MEMO)),
        ),
        fallback=TXN_OTHER,
    ),
    SOURCE_TP_GDS: _TP_VOCAB,
    SOURCE_TP_LCC: _TP_VOCAB,
    # NDC — the airline's own `TXN Type`, normalised the way ndc_spec.norm_txn does.
    # `ndc_billing_projection.bill_kind` classifies on this column and explicitly not on
    # the sign: "reading the sign instead would let a REFUND whose portal wrote a
    # positive Payment Amount project as a charge — a credit note issued as an invoice".
    # Everything that is not a refund is a sale; the types that are neither
    # (FREE_SEAT, UNPAID_BOOKING, …) never reach the table, since ndc_spec.is_excluded
    # drops them at ingest.
    SOURCE_NDC: _Vocab(
        buckets=((TXN_REFUND, _up(_NDC_REFUND_TXN)),),
        fallback=TXN_SALE,
        punctuation_folds=True,
    ),
    # Third Party API — the aggregator's `Booking Status`. "Refunded" is a refund even
    # though tp_api_billing_projection groups it with "Cancelled": those two share a
    # BILLING rule (read the retained amount), not a transaction class, and a refund
    # that classified as an adjustment would drop out of gross entirely instead of
    # subtracting from it.
    SOURCE_TP_API: _Vocab(
        buckets=(
            (TXN_REFUND, _up(v for v in _TPA_CANCELLED if v.upper() == "REFUNDED")),
            (TXN_ADJUSTMENT,
             _up({*(v for v in _TPA_CANCELLED if v.upper() != "REFUNDED"),
                  _TPA_PENDING})),
        ),
        fallback=TXN_SALE,
    ),
    SOURCE_LCC_DETAILED: _Vocab(
        buckets=tuple(
            (cls, _up(k for k, v in _LCC_BILL_KIND.items() if _KIND_TO_CLASS[v] == cls))
            for cls in (TXN_SALE, TXN_REFUND, TXN_ADJUSTMENT)
        ),
        # commission/lcc_detailed does `_KIND.get(kind, KIND_ISSUE)` — an unresolved row
        # (bill_kind NULL, so the value is `payment_status`) is a booking until something
        # says otherwise. Whether it enters a SALE total is a separate question, answered
        # by counts_in_net_sql, which is where the balance-movement rule lives.
        fallback=TXN_SALE,
    ),
}


def classify_txn(source: str, txn_type: str | None) -> str:
    """A source's raw transaction value -> the board's txn_class.

    Only `sale` and `refund` carry revenue. A memo or a cancelled booking is a
    settlement adjustment and must stay out of every revenue denominator: it has no
    fare, so counting its value as gross corrupts every ratio on the board — and does it
    invisibly, because memos are legitimately `status='excluded'` and therefore appear in
    neither the matched nor the needs-data count.

    BSP's EXCH is deliberately NOT a sale: bsp_commission settles an exchange under the
    reissued document, so counting it here would book the same journey twice.
    """
    vocab = _VOCABS.get(source)
    if vocab is None:
        raise ValueError(f"income_board: no transaction vocabulary for source {source!r}")
    value = vocab.normalise(txn_type)
    if not value:
        # A blank is not an unrecognised value. BSP prints a type on every settlement
        # row, so a blank there is a parse gap; a consolidator legitimately leaves the
        # status column empty on an issued ticket, and `classify` reads that as an issue.
        return TXN_OTHER if vocab.fallback == TXN_OTHER else vocab.fallback
    for txn_class, values in vocab.buckets:
        if value in values:
            return txn_class
    return vocab.fallback


def normalise_segment(segment_type: str | None) -> str | None:
    """A segment in any source's spelling -> 'I' | 'D' | None.

    Straight through deal_matching.segment_letter, which is the vocabulary the money
    engine matches on. Note what it does NOT accept: a bare 'I' or 'D'. See
    `normalise_bsp_segment` for why that matters.
    """
    return segment_letter(segment_type)


def normalise_bsp_segment(stat: str | None) -> str | None:
    """BSP's STAT column -> 'I' | 'D' | None, via the word form.

    THE ROUND TRIP IS NOT OPTIONAL. BSP prints a letter ('I', and 'I71' on amended
    rows); `segment_letter`'s vocabularies are {INTERNATIONAL, INTL, INTER, INT} and
    {DOMESTIC, DOM}, neither of which contains a bare letter. Feeding STAT straight in
    returns None for every BSP row on the board — silently, since None is a legitimate
    "could not determine". `stat_to_segment` maps the letter to the word first.
    """
    return segment_letter(stat_to_segment(stat))


# ── SQL builders ──────────────────────────────────────────────────────────────
# Generated from the sets above so the projection cannot drift from classify_txn.

def _quoted(values) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in sorted(values))


def txn_class_sql(source: str, col: str) -> str:
    """CASE mapping one source's raw transaction column onto txn_class.

    The source argument is not optional and there is no default: a new arm that forgets
    it raises here rather than silently inheriting BSP's vocabulary, which is the exact
    failure this signature exists to make impossible.
    """
    vocab = _VOCABS.get(source)
    if vocab is None:
        raise ValueError(f"income_board: no transaction vocabulary for source {source!r}")
    t = vocab.sql_value(col)
    arms = [f"WHEN {t} = '' THEN '{TXN_OTHER if vocab.fallback == TXN_OTHER else vocab.fallback}'"]
    for txn_class, values in vocab.buckets:
        if values:
            arms.append(f"WHEN {t} IN ({_quoted(values)}) THEN '{txn_class}'")
    arms.append(f"ELSE '{vocab.fallback}'")
    body = "\n            ".join(arms)
    return f"""
        CASE
            {body}
        END"""


def _segment_sql_from(sets: tuple[set[str], set[str]], expr: str) -> str:
    intl, dom = sets
    return f"""
        CASE
            WHEN {expr} IN ({_quoted(intl)}) THEN 'I'
            WHEN {expr} IN ({_quoted(dom)})  THEN 'D'
            ELSE NULL
        END"""


def _engine_vocabularies() -> tuple[set[str], set[str]]:
    """The exact strings segment_letter answers 'I' and 'D' to.

    Read back OUT of the function rather than imported from its private module-level
    sets, so this stays correct if it ever stops being a plain membership test.
    """
    candidates = [
        "INTERNATIONAL", "INTL", "INTER", "INT", "DOMESTIC", "DOM",
        "International", "Domestic", "I", "D",
    ]
    intl = {c.upper() for c in candidates if segment_letter(c) == "I"}
    dom = {c.upper() for c in candidates if segment_letter(c) == "D"}
    return intl, dom


def segment_sql(col: str) -> str:
    """CASE mapping a word-form segment column onto 'I' | 'D' | NULL."""
    return _segment_sql_from(_engine_vocabularies(), f"upper(btrim(coalesce({col}, '')))")


# The STAT letter -> word pairs stat_to_segment knows, recovered by asking it rather
# than retyping _STAT_SEGMENT. Keeps this file honest if it ever gains a third letter.
_STAT_PAIRS = [(ch, stat_to_segment(ch)) for ch in "IDO" if stat_to_segment(ch)]


def bsp_segment_sql(col: str) -> str:
    """CASE mapping BSP's STAT column onto 'I' | 'D' | NULL.

    Takes the leading letter first, because amended rows carry a suffix (I71, D41), then
    maps it the way stat_to_segment does before segment_letter sees it.
    """
    lead = f"upper(left(coalesce({col}, ''), 1))"
    intl = {k for k, v in _STAT_PAIRS if segment_letter(v) == "I"}
    dom = {k for k, v in _STAT_PAIRS if segment_letter(v) == "D"}
    return f"""
        CASE
            WHEN {lead} IN ({_quoted(intl)}) THEN 'I'
            WHEN {lead} IN ({_quoted(dom)})  THEN 'D'
            ELSE NULL
        END"""


# norm_tn, in SQL: strip non-alphanumerics, strip leading zeros, uppercase. NULLIF
# collapses an empty result to NULL, because an all-zeros or punctuation-only ticket
# number is not a link to anything and leaving it as '' would group every such row
# together. The Python original is services/bsp_reconciliation.norm_tn; the sell
# reconciliation query already carries this same expression.
def ticket_key_sql(col: str) -> str:
    return (
        f"NULLIF(upper(ltrim(regexp_replace(coalesce({col}, ''), "
        f"'[^0-9A-Za-z]', '', 'g'), '0')), '')"
    )


# A JSONB text field cast to numeric ONLY when it really is one. services/
# flat_statement.py deliberately keeps the original text when a number fails to parse
# ("so nobody reads a blank accrual bucket as 'no sales'"), so an unguarded ::numeric
# raises and takes the whole projection down with it.
def jsonb_numeric_sql(expr: str) -> str:
    return (
        f"CASE WHEN ({expr}) ~ '^-?[0-9]+(\\.[0-9]+)?$' "
        f"THEN ({expr})::numeric ELSE NULL END"
    )


def jsonb_decimal_sql(expr: str) -> str:
    """Like `jsonb_numeric_sql`, but tolerating the thousands separators NDC keeps.

    `statement_spec.STATEMENT_SPECS["ndc"]` declares no `normalize_row`, so an NDC cell
    reaches the table exactly as the airline's portal printed it — including
    "1,23,456.78". `ndc_spec.to_decimal` strips commas before parsing, so the same cell
    is a number in Python and NULL under `jsonb_numeric_sql`'s regex, which would show up
    as a carrier that sold nothing rather than as an error.

    Only the separators are stripped, and only when they sit where a real grouping puts
    them is NOT checked here — unlike normalize._GROUPED_INT_RE — because the guard that
    follows is the whole-string numeric test: "1.234,56" survives comma-stripping as
    "1.23456", which the regex rejects, so a European decimal comma still lands as NULL
    rather than as a number 100x too large.
    """
    stripped = f"btrim(replace(coalesce({expr}, ''), ',', ''))"
    return (
        f"CASE WHEN ({stripped}) ~ '^-?[0-9]+(\\.[0-9]+)?$' "
        f"THEN ({stripped})::numeric ELSE NULL END"
    )


def iso_date_sql(expr: str) -> str:
    """An ALREADY-ISO date string -> date, guarded. For `data` the ingest normalised.

    flat_statement and tp_api_spec write ISO dates into `data` and stamp
    `date_parse_failed` on the rows they could not read, keeping the original text rather
    than blanking it "so nobody reads a blank accrual bucket as 'no sales'". So those
    columns need a prefix guard, not the nine-pattern parser — this is the same
    `^\\d{4}-\\d{2}-\\d{2}` test services/plb_accrual.flown_from_third_party already
    applies to the same columns. Use `date_sql` for a source that keeps vendor spellings.
    """
    e = f"coalesce({expr}, '')"
    return (f"CASE WHEN ({e}) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' "
            f"THEN (left({e}, 10))::date ELSE NULL END")


#: SQLAlchemy's OWN bind-parameter pattern, copied from `sqlalchemy.sql.elements.TextClause`
#: so that what `date_sql` escapes is exactly what `text()` would otherwise capture. Kept
#: verbatim rather than approximated: a looser pattern here would escape a colon text()
#: does not touch, and PostgreSQL would then see a stray backslash inside a regex.
#: The two characters `text()` reads as "this colon is literal". Built from chr(92)
#: rather than written as a string escape so no future reformat can silently halve it.
BACKSLASH_COLON = chr(92) + ":"

_SA_BIND_PARAM = re.compile(r"(?<![:\w\$]):([\w\$]+)(?![:\w\$])")


def date_sql(expr: str) -> str:
    """One of any vendor's printed date spellings -> a 'YYYY-MM-DD' text expression.

    `report_download.normalize.date_key_sql` is the authority and is already proven, on a
    real database, to agree with its Python twin `parse_report_date` — the two are
    generated from one `DATE_PATTERNS` table precisely so a row can never be counted by
    the upload listing and then dropped by the build. Reusing it here means the revenue
    board's months cannot disagree with the report's months either.

    It is a SQLAlchemy expression and `project.py` builds raw `text()`, so it is compiled
    with `literal_binds`. That is safe ONLY because normalize.py asserts every pattern is
    free of quotes and backslashes (see its `_PATTERN_SAFE` check) — the binds being
    inlined are its own regexes, never anything a vendor typed.

    THE DIALECT IS NOT OPTIONAL AND THE DEFAULT ONE IS WRONG. `postgresql.dialect()` is
    psycopg2's, whose `pyformat` paramstyle escapes every `%` by doubling it. This
    expression is built on `format('%1$s-%2$s-%3$s', VARIADIC regexp_match(...))`, and
    `%%` inside `format()` means a LITERAL percent — so the doubled version returns the
    string "%1$s-%2$s-%3$s" for every row instead of a date. It raises nothing: every
    date simply fails to parse and every month bucket comes back empty, which reads as
    "no sales". Compiling against the dialect the engine actually uses (asyncpg, which
    binds positionally and leaves `%` alone) is what keeps that impossible, and the
    assertion below is what keeps it impossible if the driver ever changes.
    """
    sql = str(
        date_key_sql(literal_column(expr)).compile(
            dialect=postgresql.asyncpg.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "%%" not in sql, (
        "date_sql compiled a doubled '%%', which format() reads as a literal percent. "
        "The compiling dialect's paramstyle no longer matches the engine's."
    )

    # THE SAME TRAP AS THE '%%' ABOVE, ONE PUNCTUATION MARK OVER, and it cost the NDC arm
    # of the revenue board every row it ever had.
    #
    # `literal_binds` inlines DATE_PATTERNS' regexes into the SQL, and those regexes are
    # full of non-capturing groups: `(?:0?[13578]|1[02])`, `(?:JAN|MAR|MAY|...)`. When
    # project.py hands the finished string to `text()`, SQLAlchemy re-parses it looking for
    # `:name` bind parameters -- and `(?:0?...` reads as a bind called "0", `(?:JAN|...` as
    # one called "JAN". The statement then raises "A value is required for bind parameter
    # '0'" on EVERY execution.
    #
    # It fails INVISIBLY, which is why it lasted: income_board/hooks.refresh and
    # runner._project_income_board both catch and log, so an NDC upload simply never lands
    # on the board and the freshness banner reports it as "never projected" forever.
    #
    # `\:` is how text() is told a colon is literal -- it strips the backslash before the
    # statement reaches the driver. Every colon in here is inside one of our own regexes
    # (the compile above inlined them; nothing a vendor typed reaches this string), so
    # escaping all of them is right rather than merely expedient.
    sql = _SA_BIND_PARAM.sub(r"\\:\1", sql)
    # Strip what we just escaped, then ask the ORIGINAL pattern whether any BARE
    # colon survived. Re-checking with `_SA_BIND_PARAM` directly cannot work: its
    # lookbehind excludes `:`, a word char and `$` but not a backslash, so it matches
    # `\:JAN` exactly as happily as `:JAN`.
    assert not _SA_BIND_PARAM.search(sql.replace(BACKSLASH_COLON, "")), (
        "date_sql left a bare ':name' in its SQL, which text() will read as a bind "
        "parameter and refuse to execute. See the note above."
    )
    return sql


# ── Document identity, for cross-source linking ───────────────────────────────

def doc_key_sql(doc_expr: str, code_expr: str) -> tuple[str, str]:
    """(doc_code, doc_serial) — the two halves of report_download.normalize.doc_key.

    LEADING ZEROS ARE KEPT, which is the entire reason this exists beside
    `ticket_key_sql`. `norm_tn` strips them, harmlessly, for the BSP-to-internal-ticket
    join it was written for; normalize.py's header states the opposite requirement for
    linking two VENDOR documents — "098 0123456789" and "098 123456789" are different
    documents, and matching them would suppress NDC sale that BSP never settled.

    Two shapes are recognised, and anything else yields (NULL, NULL):

      * a 13-character document — the printed ticket, accounting code included;
      * a bare serial of at most 10 digits, taking its code from `code_expr` (the row's
        accounting or ticket-prefix column).

    The Python original also handles conjunctions and alphanumeric documents. Those are
    deliberately left unmatched here rather than approximated: a document that cannot be
    linked is a visible gap, a document linked to the wrong one is a wrong number.
    """
    d = f"upper(regexp_replace(coalesce({doc_expr}, ''), '[^0-9A-Za-z]', '', 'g'))"
    code = f"lpad(nullif(regexp_replace(coalesce({code_expr}, ''), '[^0-9]', '', 'g'), ''), 3, '0')"
    code_sql = f"""
        CASE
            WHEN {d} ~ '^[0-9]{{13}}$' THEN left({d}, 3)
            WHEN {d} ~ '^[0-9]{{1,10}}$' THEN {code}
            ELSE NULL
        END"""
    serial_sql = f"""
        CASE
            WHEN {d} ~ '^[0-9]{{13}}$' THEN right({d}, 10)
            WHEN {d} ~ '^[0-9]{{1,10}}$' AND {code} IS NOT NULL THEN lpad({d}, 10, '0')
            ELSE NULL
        END"""
    return code_sql, serial_sql


# ── Counts In Net ─────────────────────────────────────────────────────────────
# services/report_download/columns.COUNTS_IN_NET_RULES is the rule set and the
# user-visible vocabulary; this renders it into SQL. Two independently-written
# definitions of "does this line count" would hand finance two authoritative sale
# figures and no way to tell which is right — see invariant 7.

def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _blank(expr: str) -> str:
    return f"nullif(btrim(coalesce({expr}, '')), '') IS NULL"


def counts_in_net_sql(source: str, alias: str) -> tuple[str, str]:
    """(counts_in_net, counts_in_net_reason) for one source, as SQL expressions.

    `alias` is the STATEMENT table's alias in the arm — the row's own columns are what
    these rules read, never the calculation's, because an unpriced row has no calculation
    and must still be classified.
    """
    if source == SOURCE_BSP:
        # The settlement file itself. COUNTS_IN_NET_RULES: "BSP Detailed — Yes".
        return "true", "NULL"

    if source in (SOURCE_TP_GDS, SOURCE_TP_LCC):
        return _tp_counts_in_net_sql(alias)

    if source == SOURCE_LCC_DETAILED:
        return _lcc_counts_in_net_sql(alias)

    if source == SOURCE_NDC:
        return _ndc_counts_in_net_sql(alias)

    if source == SOURCE_TP_API:
        return _tp_api_counts_in_net_sql(alias)

    raise ValueError(f"income_board: no counts-in-net rule for source {source!r}")


def _tp_counts_in_net_sql(a: str) -> tuple[str, str]:
    """Third Party GDS / LCC — mappers/third_party.py's §B.3 rule 8, in order.

    The order matters and is not the obvious one. A footer line is tested FIRST, before
    the status, because a footer has no status either and would otherwise fall through to
    "issue" and add the statement's own total to the statement's own rows. A voided line
    carrying its own negative net is a REFUND and counts — the consolidator is crediting
    the agency, and dropping the credit would overstate what the agency owes.
    """
    status = f"upper(btrim(coalesce({a}.data->>'ticket_status', '')))"
    net = jsonb_numeric_sql(f"{a}.data->>'net_amount'")
    # N.dsum of the two, coalesced: the mapper compares against `abs(penalty_pair or 0)`,
    # so a row printing neither field gets a zero allowance rather than a NULL comparison
    # that would quietly make every void count.
    penalty_terms = []
    for field in ("agent_penalty", "cancellation_markup"):
        penalty_terms.append(
            "coalesce(" + jsonb_numeric_sql(a + ".data->>'" + field + "'") + ", 0)")
    penalty = "(" + " + ".join(penalty_terms) + ")"

    summary = " AND ".join(
        _blank(f"{a}.data->>'{f}'")
        for f in (*_IDENTITY_FIELDS, "ticket_status", *_DATE_FIELDS)
    )
    skip = _quoted(_up(_SKIP_STATUS))
    void = _quoted(_up(_VOID_STATUSES))
    slack = str(Decimal(_VOID_PENALTY_SLACK))

    # A void whose net is within its own penalty (plus a rupee) is the penalty being
    # billed, not a sale nobody reversed — it counts. Anything larger is the other export
    # style, where the cancelled line still carries the full positive sale, and that one
    # is held back for a human rather than netted off.
    void_ok = f"abs(coalesce({net}, 0)) <= abs({penalty}) + {slack}"

    counts = f"""
        CASE
            WHEN {summary} THEN false
            WHEN {status} IN ({skip}) THEN
                CASE
                    WHEN {status} IN ({void}) AND coalesce({net}, 0) < 0 THEN true
                    WHEN {status} IN ({void}) THEN ({void_ok})
                    ELSE false
                END
            ELSE true
        END"""
    reason = f"""
        CASE
            WHEN {summary} THEN {_sql_str(C.NET_SUMMARY_ONLY)}
            WHEN {status} IN ({skip}) THEN
                CASE
                    WHEN {status} IN ({void}) AND coalesce({net}, 0) < 0 THEN NULL
                    WHEN {status} IN ({void}) THEN
                        CASE WHEN {void_ok} THEN NULL
                             ELSE {_sql_str(C.NET_CANCELLED_VERIFY)} END
                    ELSE {_sql_str(C.NET_NOT_A_SALE)}
                END
            ELSE NULL
        END"""
    return counts, reason


def _norm_txn_sql(expr: str) -> str:
    """ndc_spec.norm_txn in SQL: "Paid Booking" / "paid-booking" -> PAID_BOOKING."""
    return (f"btrim(regexp_replace(upper(btrim(coalesce({expr}, ''))), "
            f"'[^A-Z0-9]+', '_', 'g'), '_')")


def ndc_is_refund_sql(a: str) -> str:
    """ndc_billing_projection.is_refund — on TXN Type alone, never on the sign.

    Reading the sign instead "would let a REFUND whose portal wrote a positive Payment
    Amount project as a charge — a credit note issued as an invoice".
    """
    return f"({_norm_txn_sql(a + qq('txn_type'))} IN ({_quoted(_up(_NDC_REFUND_TXN))}))"


def ndc_is_ancillary_sql(a: str) -> str:
    """ndc_billing_projection._looks_ancillary — anything the airline does not call
    transport.

    Defined this way round on purpose. Enumerating the add-ons (SEAT|BAG|MEAL|…) means
    being right about every product name an airline might invent, and the first unlisted
    one — "Lounge Access" — quietly becomes a ticket of its own. There is exactly one
    word for the thing being flown. When `Product` is blank the TXN Type decides and the
    default is FLIGHT: a line we cannot classify is better counted on its own than
    latched onto someone's ticket.
    """
    product = _norm_txn_sql(a + qq("product"))
    txn = _norm_txn_sql(a + qq("txn_type"))
    return f"""(
            CASE
                WHEN {product} <> '' THEN NOT ({product} ~ '{_NDC_FLIGHT_PRODUCT}')
                ELSE ({txn} ~ '{_NDC_ANCILLARY_TXN}')
            END)"""


def tp_api_product_sql(a: str) -> str:
    """markup_categories.category_slug over `product_type` — 'air' | 'hotel' | … | NULL.

    Generated from CATEGORY_ALIASES so a new spelling ("Domestic Flight") is recognised
    here the moment billing recognises it. NULL is the same answer `row_category` gives
    and means the same thing: the product names no billing category, so there is nothing
    to bill it at and nothing to count it as.
    """
    key = (f"lower(btrim(regexp_replace(coalesce({a}.data->>'product_type', ''),"
           f" '\\s+', ' ', 'g')))")
    arms = []
    for slug in sorted(set(_mc.CATEGORY_ALIASES.values())):
        spellings = sorted(k for k, v in _mc.CATEGORY_ALIASES.items() if v == slug)
        arms.append(f"WHEN {key} IN ({_quoted(spellings)}) THEN {_sql_str(slug)}")
    body = "\n            ".join(arms)
    return f"""
        CASE
            {body}
            ELSE NULL
        END"""


#: The alias the tp-api lateral publishes. `tpk.kind` and `tpk.amount` are the verdict.
TP_API_ALIAS = "tpk"


def tp_api_bill_lateral(a: str) -> str:
    """A CROSS JOIN LATERAL computing one Third Party API row's billing verdict ONCE.

    A LATERAL and not three inline expressions, because `classify` reads `net_amount`,
    `total_paid_amount` and `refund_amount` a dozen times between them and each read is a
    regex-guarded JSONB cast. Inlined, the verdict alone compiled to 18 KB of SQL and the
    arm referenced it three times — for `gross_amount`, for `counts_in_net` and for its
    reason. Postgres has no common-subexpression elimination, so that is not only
    unreadable, it is the same cast evaluated a hundred times a row.

    Three chained laterals, each allowed to see the one before it: the parsed money, then
    the derived facts, then the verdict.
    """
    kind, amount = _tp_api_bill_exprs(a)
    net = jsonb_decimal_sql(f"{a}.data->>'net_amount'")
    paid = jsonb_decimal_sql(f"{a}.data->>'total_paid_amount'")
    refund = jsonb_decimal_sql(f"{a}.data->>'refund_amount'")
    return f"""
        CROSS JOIN LATERAL (
            SELECT ({net}) AS net, ({paid}) AS paid, ({refund}) AS refund
        ) tpm
        CROSS JOIN LATERAL (
            SELECT {_TPA_BASE} AS base
        ) tpb
        CROSS JOIN LATERAL (
            SELECT ({kind}) AS kind, ({amount}) AS amount
        ) {TP_API_ALIAS}"""


# bill_base, over the parsed lateral: FIRST NON-ZERO, then first parsed. A plain coalesce
# would stop at an explicit "0.00" and never look at the other column, which on a
# mixed-vendor file zeroes out a real figure. None and 0 stay different answers.
_TPA_BASE = """
            CASE
                WHEN tpm.net IS NOT NULL AND tpm.net <> 0 THEN tpm.net
                WHEN tpm.paid IS NOT NULL AND tpm.paid <> 0 THEN tpm.paid
                WHEN tpm.net IS NOT NULL THEN tpm.net
                ELSE tpm.paid
            END"""


def _tp_api_bill_exprs(a: str) -> tuple[str, str]:
    """(bill_kind, bill_amount) for one Third Party API row — `tpb.classify`, in SQL.

    THIS IS THE HIGHEST-RISK EXPRESSION IN THE PROJECTION, and it is rendered here rather
    than read off `third_party_api.bill_amount` for one reason: that column is written
    only when somebody opens the billing worklist and resolves the batch
    (api/v1/tp_api_billing.py), so on every unresolved upload it is NULL — a revenue tab
    built on it would show a real statement as nothing sold. It is also not the same
    figure: `bill_amount` is what the row BILLS, and gross is what it sold.

    Stamping it at ingest instead is not available either: `statement_spec` declares no
    parser for `tp-api`, so `reprocess_batch` refuses the type outright, and anything
    stamped at ingest could never be re-derived without a re-upload.

    Every literal below is generated from `tp_api_billing_projection`'s own constants, so
    a new cancelled status or credit series changes both renderings at once. What that
    cannot catch is a difference in the ORDER of the rules or in the arithmetic, which is
    why `test_income_board` compiles this and `tests/test_tp_api_billing` runs the Python
    over the same fixture rows: the two must return the same pair.

    The order is `classify`'s and none of it is arbitrary — category first (a "Visa" line
    with a perfectly good amount is still out), pending before any amount test, a TBO
    credit negated by its invoice series rather than by a status, and an MMT cancellation
    billing what the vendor KEPT.
    """
    net, paid, refund, base = "tpm.net", "tpm.paid", "tpm.refund", "tpb.base"

    # markup_categories.category_slug: whitespace-collapsed, lower-cased, looked up.
    # Generated from CATEGORY_ALIASES so a new spelling is recognised in both places.
    prod = (f"lower(btrim(regexp_replace(coalesce({a}.data->>'product_type', ''),"
            f" '\\s+', ' ', 'g')))")
    has_category = f"{prod} IN ({_quoted(_TPA_CATEGORY_ALIASES)})"

    status = f"nullif(btrim(coalesce({a}.data->>'booking_status', '')), '')"
    inv = f"nullif(btrim(coalesce({a}.data->>'invoice_number', '')), '')"
    tbo_credit = (
        f"({a}.data->>'vendor' = {_sql_str(_TPA_TBO_LABEL)}"
        f" AND {inv} LIKE '%/%'"
        f" AND upper(btrim(split_part({inv}, '/', 1))) IN ({_quoted(_TPA_CREDIT_SERIES)}))"
    )
    # _paid_is_a_tender_total: MMT's Total Paid is the tender at booking with the refund
    # beside it; TBO's NET is already net of everything, so subtracting there would count
    # the refund twice.
    tender = f"(({net}) IS NULL OR ({net}) = 0)"
    retained = f"(({paid}) - ({refund}))"
    cancelled = _quoted(_up(_TPA_CANCELLED))

    # _is_zero: ABSENT counts as nil, PRESENT-BUT-UNREADABLE does not. MakeMyTrip ships no
    # cancellation_fee column at all, so treating absent as unknown would stop the
    # `cancelled` verdict ever firing on an MMT file; a cell that says "N/A" is a fact we
    # do not have and must fall through to `no_amount` instead.
    def _nil(field: str) -> str:
        cell = a + ".data->>'" + field + "'"
        raw = f"nullif(btrim(coalesce({cell}, '')), '')"
        return f"(({raw}) IS NULL OR ({jsonb_decimal_sql(cell)}) = 0)"

    dead_cancel = " AND ".join(
        _nil(f) for f in ("refund_amount", "cancellation_fee", "base_fare"))

    kind = f"""
        CASE
            WHEN NOT ({has_category}) THEN {_sql_str(_TPA_NO_CATEGORY)}
            WHEN {status} = {_sql_str(_TPA_PENDING)} THEN {_sql_str(_TPA_PENDING_KIND)}
            WHEN {tbo_credit} THEN
                CASE WHEN ({base}) IS NULL OR ({base}) = 0
                     THEN {_sql_str(_TPA_NO_AMOUNT)} ELSE {_sql_str(_TPA_REFUND)} END
            WHEN upper({status}) IN ({cancelled}) AND ({refund}) IS NOT NULL
                 AND ({refund}) > 0 AND {tender} THEN
                CASE
                    WHEN ({paid}) IS NULL OR ({paid}) <= 0
                        THEN {_sql_str(_TPA_NEEDS_REVIEW)}
                    WHEN abs({retained}) < {_TPA_NIL} THEN {_sql_str(_TPA_CANCELLED_KIND)}
                    WHEN {retained} < 0 THEN {_sql_str(_TPA_REFUND)}
                    ELSE {_sql_str(_TPA_SALE)}
                END
            WHEN upper({status}) IN ({cancelled}) AND {dead_cancel}
                 AND (({base}) IS NULL OR ({base}) = 0)
                THEN {_sql_str(_TPA_CANCELLED_KIND)}
            WHEN ({base}) IS NULL OR ({base}) = 0 THEN {_sql_str(_TPA_NO_AMOUNT)}
            WHEN ({base}) < 0 THEN {_sql_str(_TPA_REFUND)}
            ELSE {_sql_str(_TPA_SALE)}
        END"""

    amount = f"""
        CASE
            WHEN {tbo_credit} AND ({base}) IS NOT NULL AND ({base}) <> 0
                THEN -abs({base})
            WHEN upper({status}) IN ({cancelled}) AND ({refund}) IS NOT NULL
                 AND ({refund}) > 0 AND {tender} THEN
                CASE
                    WHEN ({paid}) IS NULL OR ({paid}) <= 0 THEN -({refund})
                    WHEN abs({retained}) < {_TPA_NIL} THEN 0
                    ELSE {retained}
                END
            ELSE ({base})
        END"""
    return kind, amount


def _tp_api_counts_in_net_sql(a: str) -> tuple[str, str]:
    """Third Party API — only a row that actually sold something counts.

    `tpb.classify`'s five not-billable verdicts, each with the Report Download's own
    wording. COUNTS_IN_NET_RULES: "Third Party API — Yes, except pending / no amount /
    cancelled / needs review".
    """
    kind = f"{TP_API_ALIAS}.kind"
    counts = (f"CASE WHEN {kind} IN ({_quoted(_TPA_NOT_BILLABLE)}) "
              f"THEN false ELSE true END")
    reason = f"""
        CASE {kind}
            WHEN {_sql_str(_TPA_PENDING_KIND)}     THEN {_sql_str(C.NET_NOT_A_SALE)}
            WHEN {_sql_str(_TPA_NO_CATEGORY)}      THEN {_sql_str(C.NET_NOT_A_SALE)}
            WHEN {_sql_str(_TPA_NO_AMOUNT)}        THEN {_sql_str(C.NET_NOT_A_SALE)}
            WHEN {_sql_str(_TPA_CANCELLED_KIND)}   THEN {_sql_str(C.NET_CANCELLED)}
            WHEN {_sql_str(_TPA_NEEDS_REVIEW)}     THEN {_sql_str(C.NET_NEEDS_REVIEW)}
            ELSE NULL
        END"""
    return counts, reason


def _ndc_counts_in_net_sql(a: str) -> tuple[str, str]:
    """NDC — everything counts here, and the exclusion is applied afterwards.

    COUNTS_IN_NET_RULES: "NDC — Yes, unless the ticket is settled through BSP in this or
    another upload." That test is a join against the BSP rows, not a predicate on this
    one, so it cannot live in a row expression. `overlap.stamp_bsp_ndc_overlap` runs it
    as its own statement after either side is projected — see that module for why it has
    to be bidirectional.
    """
    return "true", "NULL"


def _lcc_counts_in_net_sql(a: str) -> tuple[str, str]:
    """LCC Detailed — mappers/lcc.lcc_canon, which is `bill_kind` with two overrides.

    Money that moved without a fare is not a sale. `movement_kind='balance'` is the
    account-file version of that and wins over `bill_kind`; an unresolved row (no
    `bill_kind` yet) falls back on the sign of `total`, exactly as
    api/v1/lcc_detailed._bill_kind does, where a zero or absent total means a payment.

    A `cancellation_credit` on an account row is NOT excluded: it is funds coming back
    from a cancelled booking, which the report labels CREDIT_TRANSFER and counts.
    """
    movement = f"lower(btrim(coalesce({a}.movement_kind, '')))"
    kind = f"lower(btrim(coalesce({a}.bill_kind, '')))"
    is_payment = f"""(
            {movement} = {_sql_str(MOVEMENT_BALANCE)}
            OR {kind} = 'payment'
            OR ({kind} NOT IN ('sale', 'refund', 'payment')
                AND ({a}.total IS NULL OR {a}.total = 0))
        )"""
    counts = f"CASE WHEN {is_payment} THEN false ELSE true END"
    reason = (f"CASE WHEN {is_payment} THEN {_sql_str(C.NET_LCC_PAYMENT)} "
              f"ELSE NULL END")
    return counts, reason
