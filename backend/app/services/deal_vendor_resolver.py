"""Which onboarded agency does each row of a multi-supplier deal sheet belong to?

A vendor-comparison sheet — the weekly one an OTA compiles from every consolidator it
buys from — lists all of their deals in one table, one row per airline per supplier,
with the supplier in a Source column: AKBAR, BRIGHTSUN, RIYA, TSC, YATRA(TSI) … Uploaded
with "All suppliers", every row must become a deal of the right Agency Master row,
because that row's supplier_id is what a third-party statement is priced against
(deal_matching._supplier_guard). A row filed under the wrong vendor prices somebody
else's tickets, so this module only PROPOSES, and says how sure it is:

  remembered     the agency the user confirmed for this Source on an earlier upload. The
                 sheet arrives every week; a decision made once is not asked again.
  matched        the Source names exactly one onboarded agency, on the row's channel
  suggested      one agency fits, but only partly — a name with words the cell lacks, an
                 acronym, the wrong channel, a qualifier like "(TSI)" it does not explain.
                 Offered, NOT picked: the reviewer confirms it with one click.
  ambiguous      several agencies fit (one vendor onboarded per branch). Nothing is
                 picked — choosing a branch on the user's behalf is a guess about money.
  not_onboarded  no agency fits — the reviewer maps it, onboards it, or drops the rows
  blank          the row has no Source at all

Only `remembered` and `matched` carry an agency_id. Everything else needs a person.

THE SOURCE CELL IS AN ABBREVIATION, NOT A NAME. "AKBAR" is Akbar Travels of India Pvt
Ltd, "YATRA(YFB)" is Yatra for Business, "AKBAR DEL" is Akbar's Delhi branch. A cell is
compared with an agency on its IDENTITY words — the ones that are not trade vocabulary
or legal form — after removing what the agency itself explains (its branch, its
initials). Equal identities are strong evidence; anything less is a suggestion.

Pure: no DB, no network. The API layer loads the agencies and the remembered mappings.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from app.services.deal_supplier_check import GENERIC, _words, supplier_cell_matches

REMEMBERED = "remembered"
MATCHED = "matched"
SUGGESTED = "suggested"
AMBIGUOUS = "ambiguous"
NOT_ONBOARDED = "not_onboarded"
BLANK = "blank"

# Where an upload records which agency each Source value became: on its deal statement,
# beside the column map, because it IS that upload's mapping. Read back newest-first to
# pre-fill the next upload of the same sheet — see remembered_from().
SOURCE_MAP_KEY = "__source_suppliers__"

# Legal form. Never identity, and never part of an acronym ("Sky Connect Pvt Ltd" is SC).
_LEGAL = {"pvt", "private", "ltd", "limited", "llp", "inc", "co", "plc", "llc"}
# Joining words an acronym may or may not keep ("The Sky Connect" is TSC or SC).
_JOINERS = {"the", "of", "and", "for", "n"}
# Acronyms shorter than this match far too much ("BT", "SC").
_MIN_ACRONYM = 3


@dataclass(frozen=True)
class AgencyRef:
    """The parts of an Agency Master row the resolver reads."""
    id: int
    name: str
    channels: str                       # GDS | LCC | (legacy) BOTH
    branch_code: str = ""
    branch_name: str | None = None
    agency_code: str | None = None      # AG-0001 — shared by one branch's GDS and LCC rows


@dataclass
class VendorMatch:
    status: str
    agency_id: int | None = None                         # set only for remembered / matched
    candidates: list[int] = field(default_factory=list)  # what the reviewer is offered
    note: str | None = None


def source_key(cell: str | None) -> str:
    """'YATRA(TSI)' -> 'yatratsi'. How a Source value is compared and remembered."""
    return re.sub(r"[^a-z0-9]", "", (cell or "").lower())


def _identity(s: str | None) -> set[str]:
    """The words that identify a company — 'Akbar Travels of India Pvt Ltd' -> {akbar},
    'YATRA(TSI)' -> {yatra, tsi}. Three letters is enough here (TSI, YFB, TSC are whole
    identities); trade words, legal form and numbers never are."""
    return {w for w in _words(s or "") if len(w) >= 3 and w not in GENERIC
            and w not in _LEGAL and not w.isdigit()}


def _acronyms(name: str) -> set[str]:
    """Initials a sheet might abbreviate the name to: 'Yatra For Business Pvt Ltd' ->
    {yfb, yb}, 'The Sky Connect' -> {tsc, sc}."""
    words = [w for w in _words(name) if w not in _LEGAL]
    out = {"".join(w[0] for w in words),
           "".join(w[0] for w in words if w not in _JOINERS)}
    return {a for a in out if len(a) >= _MIN_ACRONYM}


def _branch_words(a: AgencyRef) -> set[str]:
    return set(_words(a.branch_name or "")) | set(_words(a.branch_code or ""))


def _core(name: str) -> str:
    """The name with legal form removed, squeezed: 'Trip Jack Pvt Ltd' -> 'tripjack'."""
    return "".join(w for w in _words(name) if w not in _LEGAL)


def _on_channel(a: AgencyRef, channel: str | None) -> bool:
    return not channel or a.channels in (channel, "BOTH")


def _is_strong(cell: str, a: AgencyRef) -> bool:
    """Does the cell name THIS agency and nothing else?

    The cell's identity, less whatever the agency explains (its branch, its initials),
    must equal the agency's identity less its branch. So "AKBAR DEL" is Akbar's Delhi
    branch and not its Mumbai one, "YATRA(YFB)" is Yatra For Business and not Yatra
    Online, and "YATRA" is not "Money Yatra" — that name says something the cell does not.
    An acronym alone never makes it strong: it can explain a qualifier, not BE the name.
    """
    key = source_key(cell)
    if a.agency_code and source_key(a.agency_code) == key:
        return True
    if key and key == _core(a.name):
        return True                     # "TRIPJACK" for "Trip Jack Pvt Ltd"
    branch = _branch_words(a)
    rest = _identity(cell) - _acronyms(a.name) - branch
    return bool(rest) and rest == (_identity(a.name) - branch)


def _is_candidate(cell: str, a: AgencyRef) -> bool:
    if _is_strong(cell, a) or supplier_cell_matches(cell, a.name):
        return True
    key = source_key(cell)
    return key.isalpha() and key in _acronyms(a.name)


def resolve_source(
    cell: str | None,
    channel: str | None,
    agencies: list[AgencyRef],
    remembered: dict[str, int] | None = None,
) -> VendorMatch:
    """Which agency a Source cell names, for a row on `channel` (GDS / LCC).

    `agencies` are the user's ACTIVE Agency Master rows; `remembered` maps source_key →
    the agency id confirmed for it on an earlier upload."""
    key = source_key(cell)
    if not key:
        return VendorMatch(BLANK, note="This row has no Source in the sheet.")
    by_id = {a.id: a for a in agencies}

    rid = (remembered or {}).get(key)
    if rid in by_id:
        a = by_id[rid]
        if _on_channel(a, channel):
            return VendorMatch(REMEMBERED, a.id, note="Mapped this way on an earlier upload.")
        # The same vendor branch on this row's channel: GDS and LCC rows of one branch
        # share its agency code (models/agency.py, uq_agencies_user_code_channel).
        sib = [b for b in agencies
               if a.agency_code and b.agency_code == a.agency_code and _on_channel(b, channel)]
        if len(sib) == 1:
            return VendorMatch(REMEMBERED, sib[0].id, note="Mapped this way on an earlier upload.")
        # Not onboarded on this channel — fall through and let the names decide.

    hits = [a for a in agencies if _is_candidate(cell, a)]
    if not hits:
        return VendorMatch(NOT_ONBOARDED, note=f"No agency in your Agency Master matches '{cell.strip()}'.")
    strong = [a for a in hits if _is_strong(cell, a)]
    pool = strong or hits
    on = [a for a in pool if _on_channel(a, channel)]

    if strong and len(on) == 1:
        return VendorMatch(MATCHED, on[0].id)

    group = on or pool
    if len(group) > 1:
        return VendorMatch(AMBIGUOUS, candidates=[a.id for a in group],
                           note=f"{len(group)} agencies fit '{cell.strip()}' — pick the branch.")
    a = group[0]
    if not on:
        note = f"{a.name} is onboarded on {a.channels} only — this row is {channel}."
    elif source_key(cell) in _acronyms(a.name) and not supplier_cell_matches(cell, a.name):
        note = f"'{cell.strip()}' looks like the initials of {a.name}."
    else:
        note = f"'{cell.strip()}' only partly matches {a.name}."
    return VendorMatch(SUGGESTED, candidates=[a.id], note=note)


# ── memory ───────────────────────────────────────────────────────────────────

def learn_mappings(pairs: Iterable[tuple[str | None, int | None]]) -> dict[str, dict]:
    """What an upload decided, per Source: {source_key: {"source": "AKBAR", "agency_id": 12}}.

    `pairs` is (Source cell, agency id) for every saved row. A Source whose rows went to
    different agencies is remembered by its majority — the odd row out is a deliberate
    exception, not the rule. A tie is no decision, and is not remembered."""
    votes: dict[str, Counter] = {}
    label: dict[str, str] = {}
    for cell, agency_id in pairs:
        key = source_key(cell)
        if not key or agency_id is None:
            continue
        votes.setdefault(key, Counter())[agency_id] += 1
        label.setdefault(key, (cell or "").strip())
    out: dict[str, dict] = {}
    for key, counts in votes.items():
        ranked = counts.most_common(2)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue
        out[key] = {"source": label[key], "agency_id": ranked[0][0]}
    return out


def remembered_from(column_maps: Iterable[dict | None]) -> dict[str, int]:
    """source_key → agency id, from upload statements' column maps given NEWEST FIRST.
    The latest decision about a Source wins."""
    out: dict[str, int] = {}
    for cm in column_maps:
        entries = (cm or {}).get(SOURCE_MAP_KEY)
        if not isinstance(entries, dict):
            continue
        for key, entry in entries.items():
            agency_id = entry.get("agency_id") if isinstance(entry, dict) else None
            if isinstance(agency_id, int) and key not in out:
                out[key] = agency_id
    return out


def multi_vendor_label(names: Iterable[str | None], limit: int = 300) -> str:
    """The batch / statement label for an upload spanning several suppliers —
    "3 suppliers: Akbar Travels, Riya Travel & Tours, TSC". Fits `limit` characters
    (deal_batches.supplier_name), naming as many as fit and counting the rest."""
    uniq = sorted({n.strip() for n in names if n and n.strip()}, key=str.lower)
    if not uniq:
        return "Multiple suppliers"
    if len(uniq) == 1:
        return uniq[0][:limit]
    head = f"{len(uniq)} suppliers: "
    shown: list[str] = []
    for i, n in enumerate(uniq):
        left = len(uniq) - i - 1
        tail = f" +{left} more" if left else ""
        candidate = head + ", ".join([*shown, n]) + tail
        if len(candidate) > limit:
            break
        shown.append(n)
    if not shown:
        return f"{len(uniq)} suppliers"[:limit]
    left = len(uniq) - len(shown)
    return head + ", ".join(shown) + (f" +{left} more" if left else "")
