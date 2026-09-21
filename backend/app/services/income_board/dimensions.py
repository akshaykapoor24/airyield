"""Turning four sources' vocabularies into the board's one.

Every function here exists because two places in this codebase would otherwise disagree
about the same row. The rule throughout: DERIVE the mapping from the constant the money
engine already uses, never retype it. A copied set drifts on the first edit, and the
symptom is a dashboard that quietly contradicts the incentive it is displaying.

The SQL builders return CASE expressions generated FROM those same Python constants, so
adding a transaction type to `bsp_commission._SKIP_TXN` changes the projection too,
without anybody remembering to come here.
"""
from __future__ import annotations

from app.models.income_board import (
    TXN_ADJUSTMENT, TXN_CREDIT_MEMO, TXN_DEBIT_MEMO, TXN_OTHER, TXN_REFUND, TXN_SALE,
)
from app.services.bsp_commission import _ISSUE_TXN, _REFUND_TXN, _SKIP_TXN, stat_to_segment
from app.services.deal_matching import segment_letter

# The memo families, split out of _SKIP_TXN. bsp_commission treats all of these the
# same way — none is a sale — but the board has to tell a debit memo from a credit memo,
# because ADM exposure is a number an operator acts on and ACM is money coming back.
_DEBIT_MEMO = {"ADM", "ADMA", "ADMD"}
_CREDIT_MEMO = {"ACM", "ACMA", "ACMD"}


def classify_txn(txn_type: str | None) -> str:
    """A transaction type -> the board's txn_class.

    Only `sale` and `refund` carry revenue. Everything in _SKIP_TXN is a settlement
    adjustment and must stay out of every revenue denominator: a memo has no fare, so
    counting its value as gross corrupts every ratio on the board — and does it
    invisibly, because memos are legitimately status='excluded' and therefore appear in
    neither the matched nor the needs-data count.

    EXCH is deliberately NOT a sale: bsp_commission settles an exchange under the
    reissued document, so counting it here would book the same journey twice.
    """
    t = (txn_type or "").strip().upper()
    if not t:
        return TXN_OTHER
    if t in _ISSUE_TXN:
        return TXN_SALE
    if t in _REFUND_TXN:
        return TXN_REFUND
    if t in _DEBIT_MEMO:
        return TXN_DEBIT_MEMO
    if t in _CREDIT_MEMO:
        return TXN_CREDIT_MEMO
    if t in _SKIP_TXN:
        return TXN_ADJUSTMENT
    return TXN_OTHER


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


def txn_class_sql(col: str) -> str:
    """CASE mapping a raw transaction-type column onto txn_class."""
    t = f"upper(btrim(coalesce({col}, '')))"
    return f"""
        CASE
            WHEN {t} = '' THEN '{TXN_OTHER}'
            WHEN {t} IN ({_quoted(_ISSUE_TXN)})   THEN '{TXN_SALE}'
            WHEN {t} IN ({_quoted(_REFUND_TXN)})  THEN '{TXN_REFUND}'
            WHEN {t} IN ({_quoted(_DEBIT_MEMO)})  THEN '{TXN_DEBIT_MEMO}'
            WHEN {t} IN ({_quoted(_CREDIT_MEMO)}) THEN '{TXN_CREDIT_MEMO}'
            WHEN {t} IN ({_quoted(_SKIP_TXN - _DEBIT_MEMO - _CREDIT_MEMO)})
                THEN '{TXN_ADJUSTMENT}'
            ELSE '{TXN_OTHER}'
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
