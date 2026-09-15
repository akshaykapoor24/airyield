"""Cross-source linking and de-duplication for the Combined sheet (design §C).

The Combined sheet puts every upload side by side, so the same money can appear more than
once: a ticket is settled in BSP *and* listed in the GDS's TGQ HMPR file, an ADM is a BSPlink
memo *and* an ADMA line on the BSP billing, a statement is uploaded twice. Linking decides,
per row, whether it is the settlement of record (counts in Net) or a shadow of one (shown,
explained, not counted). Everything here is pure: the builder streams rows in, the SQL owner
lookup (``queries.bsp_owner_lookup``) runs outside, and ``resolve_outside`` /
``finalize_pending`` fold its hits back in.

Decisions a reader should know before editing:

1. **Membership is decided by BSP keys, never by TGQ enrichment.** The enrichment index was
   built for the commission engine and misses by design (no code → no lookup, 13-digit and
   conjunction forms, RFND notices with a NULL ticket number). ``SelectionIndex`` holds every
   non-superseded row of every INCLUDED BSP statement — including rows outside the period, with
   an ``in_period`` bit — so a TGQ ticket is suppressed only when BSP really bills it here, and
   otherwise told apart as "outside the period" or "in another upload".
2. **Type-aware.** A refund in TGQ is not "in BSP" because BSP holds the sale; it is emitted
   with ``BSP_HAS_OTHER_TXN``. ``TYPE_TARGETS`` is the one table saying which BSP types settle
   which source type and whether the RTDN side (refund notices point at the original ticket)
   may be used.
3. **Codeless keys match by serial only when unambiguous.** Legacy Excel BSP rows and many
   TGQ lines carry no airline accounting code. A codeless probe matches when exactly one code
   holds the serial; two airlines sharing a 10-digit serial is ambiguous, never a guess. An
   alphabetic "code" (``AI``) is a designator, not a BSP accounting code, and is treated as
   absent rather than silently never matching.
4. **Memory.** A BSP selection can reach ~750k rows. The index keeps parallel ``array`` /
   ``bytearray`` columns plus int-packed key dicts instead of one object per row; ``RefView``
   objects are only materialised for the refs a lookup returns.
5. **Duplicate uploads are removed before indexing** (``DuplicateTracker``, newest upload
   first), so re-uploading a statement does not make every ticket ``LINK_AMBIGUOUS``.
"""
from __future__ import annotations

import hashlib
import json
from array import array
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from app.services.report_download import columns as C
from app.services.report_download.normalize import (
    canon_bsp_txn, clean_text, doc_key, doc_keys, pack, zfill3,
)
from app.services.report_download.types import DocKey, LinkResult

__all__ = [
    "CANON", "TYPE_TARGETS", "Probe",
    "RefView", "Match", "SelectionIndex", "KeySet", "LccPnrIndex", "DuplicateTracker",
    "bsp_row_keys", "link_bsp_flags", "link_memo", "link_ra",
    "TgqDecision", "decide_tgq", "decide_ndc",
    "OwnerHit", "owner_probe_forms", "resolve_outside", "finalize_pending",
    "lcc_ledger_link", "tp_flags",
    "ALSO_THIS_REPORT", "ALSO_NO", "NOT_IN_BSP_YES", "NOT_IN_BSP_UNKNOWN",
    "VIA_BSP_MEMO_ROW", "VIA_ORIGINAL_TICKET", "VIA_LCC_PNR",
]

#: BSP canonical types the selection index can store (one byte each). Anything else is UNKNOWN.
CANON: tuple[str, ...] = (
    C.UNKNOWN, C.SALE, C.EXCHANGE, C.EMD, C.REFUND, C.ADM, C.ACM, C.CANCELLATION, C.AGENT_FEE, C.VOID,
)
_CANON_CODE: dict[str, int] = {c: i for i, c in enumerate(CANON)}

#: (key, BSP types, via) — one lookup the owner query must answer outside the selection.
Probe = tuple[DocKey, frozenset, str]

_VIAS = ("document", "rtdn", "any")

# ── link texts (exact strings; the Read Me and Summary count on them) ───────────
ALSO_THIS_REPORT = "Yes – this report"
ALSO_NO = "No"
NOT_IN_BSP_YES = "Yes"
NOT_IN_BSP_UNKNOWN = "Unknown – no ticket no."
VIA_BSP_MEMO_ROW = "BSP memo row"
VIA_ORIGINAL_TICKET = "Original ticket (RTDN)"
VIA_LCC_PNR = "LCC Detailed PNR"


def _file(name: Optional[str]) -> str:
    return name or "unnamed upload"


def _also_other_period(name: Optional[str]) -> str:
    return f"Yes – other period ({_file(name)})"


def _also_other_upload(name: Optional[str]) -> str:
    return f"Yes – other upload ({_file(name)})"


def _via_related(name: Optional[str]) -> str:
    return f"Related ticket ({_file(name)})"


def _tgq_outside(name: Optional[str]) -> str:
    return f"BSP row outside period ({_file(name)})"


def _tgq_other_upload(name: Optional[str]) -> str:
    return f"In another BSP upload ({_file(name)})"


# ── type targets (§C.5) ───────────────────────────────────────────────────────

_SALE_KINDS = frozenset({C.SALE, C.EXCHANGE, C.EMD})
_REFUND_ONLY = frozenset({C.REFUND})
_ANY_TYPE = frozenset(CANON)

#: Source canonical type → (BSP types that settle it, lookup sides in order).
TYPE_TARGETS: dict[str, tuple[frozenset, tuple[str, ...]]] = {
    C.SALE: (frozenset({C.SALE, C.EXCHANGE}), ("document",)),
    C.EXCHANGE: (frozenset({C.SALE, C.EXCHANGE}), ("document",)),
    C.EMD: (frozenset({C.EMD}), ("document",)),
    # A refund notice (document 00…/40…, NULL ticket number) is reachable only via its RTDN.
    C.REFUND: (_REFUND_ONLY, ("document", "rtdn")),
    # BSP CANX rows are indexed by ticket_number too, so a voided ticket finds its CANX.
    C.VOID: (frozenset({C.CANCELLATION, C.VOID}), ("document",)),
    C.UNKNOWN: (_ANY_TYPE, ("document",)),
}

# NDC settles through BSP as the ticket (or its EMD); a refund group via document or RTDN.
_NDC_TARGETS: dict[str, tuple[frozenset, tuple[str, ...]]] = {
    C.REFUND: (_REFUND_ONLY, ("document", "rtdn")),
}
_NDC_DEFAULT = (_SALE_KINDS, ("document",))


# ── key helpers ───────────────────────────────────────────────────────────────

def _is_digits(s: Optional[str], n: Optional[int] = None) -> bool:
    return bool(s) and s.isascii() and s.isdigit() and (n is None or len(s) == n)


def _link_code(code: Any) -> Optional[str]:
    """A BSP accounting code usable for linking (3 digits), else None."""
    z = zfill3(code)
    return z if _is_digits(z, 3) else None


def _canon_key(key: DocKey) -> DocKey:
    """Treat a non-numeric code on a numeric ticket serial as absent (see module note 3)."""
    if key.code is not None and not _is_digits(key.code, 3) and _is_digits(key.serial, 10):
        return DocKey(None, key.serial)
    return key


_NO_CODE = -2     # the serial is held by codeless rows only
_MANY = -1        # the serial is held by more than one code (codeless counts as one)


def _code_token(code: Optional[str]) -> Union[int, str]:
    if code is None:
        return _NO_CODE
    return int(code) if _is_digits(code, 3) else code


def _token_code(tok: Union[int, str]) -> Optional[str]:
    if tok == _NO_CODE:
        return None
    return f"{tok:03d}" if isinstance(tok, int) else tok


def _serial_token(serial: str) -> Union[int, str]:
    # 10-digit serials as ints (smaller); every other serial stays text, so they never collide.
    return int(serial) if _is_digits(serial, 10) else serial


def _note_serial(serials: dict, key: DocKey) -> None:
    st, tok = _serial_token(key.serial), _code_token(key.code)
    cur = serials.get(st)
    if cur is None:
        serials[st] = tok
    elif cur != tok and cur != _MANY:
        serials[st] = _MANY


def _get(row: Any, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _json(v: Any) -> Any:
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def _add_flag(flags: list[str], code: str) -> None:
    if code not in C.FLAG_LEGEND:      # same guard as columns.add_flag, fail at the source
        raise KeyError(f"Unknown data flag {code!r}")
    if code not in flags:
        flags.append(code)


# ── selection index ───────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class RefView:
    """One indexed BSP row as a lookup returns it."""
    row_id: int
    upload_idx: int
    file_name: Optional[str]
    canon: str
    in_period: bool
    document: Optional[str]


def _best_order(r: RefView) -> tuple[int, bool]:
    return (r.upload_idx, not r.in_period)


@dataclass(frozen=True)
class Match:
    refs: tuple[RefView, ...] = ()
    ambiguous: bool = False

    @property
    def hit(self) -> bool:
        return bool(self.refs)

    @property
    def best(self) -> Optional[RefView]:
        """Newest upload (lowest ``upload_idx``) first, then an in-period row first."""
        return min(self.refs, key=_best_order) if self.refs else None


_NO_MATCH = Match()


def _pick(m: Match) -> RefView:
    """The ref a decision reports: an in-period ref wins over a newer out-of-period one,
    because that row is written to this report and so already represents the ticket."""
    refs = sorted(m.refs, key=_best_order)
    return next((r for r in refs if r.in_period), refs[0])


_DOC_TEXT = 255   # _doc_len marker: the document is kept verbatim in _doc_text


class SelectionIndex:
    """Every non-superseded BSP row of the included statements, keyed by document and RTDN.

    Storage is columnar: row ``i`` is ``_row_ids[i]``, ``_uploads[i]`` … Key dicts map a
    ``normalize.pack``-ed key to a row index, or to ``~k`` for overflow list ``k`` when several
    rows share the key. ``_serials`` maps a serial to the one code holding it (or ``_MANY``)
    for codeless lookups. A document that is all digits is stored as an int plus its length
    (leading zeros are significant); anything else is kept as text in a sparse dict.
    """

    __slots__ = (
        "_row_ids", "_uploads", "_canon", "_in_period", "_doc_num", "_doc_len", "_doc_text",
        "_files", "_doc", "_rtdn", "_overflow", "_serials", "_type_cache",
    )

    def __init__(self) -> None:
        self._row_ids = array("q")
        self._uploads = array("H")
        self._canon = bytearray()
        self._in_period = bytearray()
        self._doc_num = array("q")
        self._doc_len = bytearray()
        self._doc_text: dict[int, str] = {}
        self._files: list[Optional[str]] = []          # by upload_idx, stored once
        self._doc: dict[Union[int, str], int] = {}
        self._rtdn: dict[Union[int, str], int] = {}
        self._overflow: list[list[int]] = []
        self._serials: dict[Union[int, str], Union[int, str]] = {}
        self._type_cache: dict[frozenset, frozenset] = {}

    def __len__(self) -> int:
        return len(self._row_ids)

    def add(
        self, *, row_id: int, upload_idx: int, file_name: Optional[str], canon: str,
        in_period: bool, doc_keys: Iterable[Optional[DocKey]], rtdn_keys: Iterable[Optional[DocKey]],
        document: Optional[str] = None,
    ) -> None:
        if not 0 <= upload_idx <= 0xFFFF:
            raise ValueError(f"upload_idx {upload_idx} out of range")
        i = len(self._row_ids)
        docs = [_canon_key(k) for k in doc_keys if k is not None]
        rtdns = [_canon_key(k) for k in rtdn_keys if k is not None]

        self._row_ids.append(row_id)
        self._uploads.append(upload_idx)
        self._canon.append(_CANON_CODE.get(canon, 0))
        self._in_period.append(1 if in_period else 0)
        if document is None and docs:
            document = f"{docs[0].code or ''}{docs[0].serial}"
        self._store_document(i, document)
        if upload_idx >= len(self._files):
            self._files.extend([None] * (upload_idx + 1 - len(self._files)))
        if self._files[upload_idx] is None and file_name is not None:
            self._files[upload_idx] = file_name

        for keys, target in ((docs, self._doc), (rtdns, self._rtdn)):
            for key in keys:
                self._put(target, pack(key), i)
                _note_serial(self._serials, key)

    def _store_document(self, i: int, document: Optional[str]) -> None:
        s = clean_text(document)
        if s is None:
            self._doc_num.append(0)
            self._doc_len.append(0)
        elif len(s) <= 18 and _is_digits(s):
            self._doc_num.append(int(s))
            self._doc_len.append(len(s))
        else:
            self._doc_num.append(0)
            self._doc_len.append(_DOC_TEXT)
            self._doc_text[i] = s

    def _put(self, target: dict, pk: Union[int, str], i: int) -> None:
        cur = target.get(pk)
        if cur is None:
            target[pk] = i
        elif cur >= 0:
            if cur != i:
                self._overflow.append([cur, i])
                target[pk] = ~(len(self._overflow) - 1)
        else:
            refs = self._overflow[~cur]
            if refs[-1] != i:            # rows are added in order, so a repeat is always last
                refs.append(i)

    def _ref(self, i: int) -> RefView:
        n = self._doc_len[i]
        if n == 0:
            document = None
        elif n == _DOC_TEXT:
            document = self._doc_text[i]
        else:
            document = str(self._doc_num[i]).zfill(n)
        u = self._uploads[i]
        return RefView(self._row_ids[i], u, self._files[u], CANON[self._canon[i]], bool(self._in_period[i]), document)

    def _maps(self, via: str) -> tuple[dict, ...]:
        if via == "document":
            return (self._doc,)
        if via == "rtdn":
            return (self._rtdn,)
        if via == "any":
            return (self._doc, self._rtdn)
        raise ValueError(f"via must be one of {_VIAS}, got {via!r}")

    def _type_codes(self, types: frozenset) -> frozenset:
        codes = self._type_cache.get(types)
        if codes is None:
            codes = self._type_cache[types] = frozenset(_CANON_CODE[t] for t in types if t in _CANON_CODE)
        return codes

    def _collect(self, maps: tuple[dict, ...], pk: Union[int, str], want: Optional[frozenset]) -> list[int]:
        out: dict[int, None] = {}
        for target in maps:
            cur = target.get(pk)
            if cur is None:
                continue
            for i in ((cur,) if cur >= 0 else self._overflow[~cur]):
                if want is None or self._canon[i] in want:
                    out[i] = None
        return list(out)

    def find(self, key: Optional[DocKey], types: Optional[frozenset], via: str = "document") -> Match:
        """Refs holding ``key`` on the ``via`` side whose type is in ``types`` (None = any).

        A coded probe that finds nothing also tries codeless (legacy) rows with the same
        serial; that is ambiguous when other codes hold the serial too. A codeless probe
        resolves through the one code holding the serial, or is ambiguous with no refs. Refs
        from more than one upload are ambiguous too (best = newest).
        """
        maps = self._maps(via)
        if key is None:
            return _NO_MATCH
        key = _canon_key(key)
        want = None if types is None else self._type_codes(types)
        ambiguous = False
        if key.code is not None:
            idxs = self._collect(maps, pack(key), want)
            if not idxs:
                idxs = self._collect(maps, pack(DocKey(None, key.serial)), want)
                if idxs and self._serials.get(_serial_token(key.serial)) == _MANY:
                    ambiguous = True
        else:
            tok = self._serials.get(_serial_token(key.serial))
            if tok is None:
                return _NO_MATCH
            if tok == _MANY:
                return Match((), True)
            idxs = self._collect(maps, pack(DocKey(_token_code(tok), key.serial)), want)
        if not idxs:
            return _NO_MATCH
        refs = tuple(sorted((self._ref(i) for i in idxs), key=_best_order))
        if len({r.upload_idx for r in refs}) > 1:
            ambiguous = True
        return Match(refs, ambiguous)

    def find_any(self, key: Optional[DocKey]) -> Match:
        """Untyped lookup on both sides — "does BSP hold this ticket at all?"."""
        return self.find(key, None, "any")


# ── small indexes ─────────────────────────────────────────────────────────────

class KeySet:
    """Membership of document keys (packed) or arbitrary hashable keys (tuples / str as-is).

    DocKeys follow the SelectionIndex serial rule: a codeless probe is a member when exactly
    one code holds its serial, and a coded probe also matches a codeless member.
    """

    __slots__ = ("_keys", "_serials")

    def __init__(self, keys: Iterable[Any] = ()) -> None:
        self._keys: set = set()
        self._serials: dict[Union[int, str], Union[int, str]] = {}
        for k in keys:
            self.add(k)

    def add(self, key: Union[DocKey, tuple, str, None]) -> None:
        if key is None:
            return
        if isinstance(key, DocKey):
            key = _canon_key(key)
            self._keys.add(pack(key))
            _note_serial(self._serials, key)
        else:
            self._keys.add(key)

    def __contains__(self, key: Any) -> bool:
        if key is None:
            return False
        if isinstance(key, DocKey):
            key = _canon_key(key)
            if key.code is not None:
                return pack(key) in self._keys or pack(DocKey(None, key.serial)) in self._keys
            tok = self._serials.get(_serial_token(key.serial))
            return tok is not None and tok != _MANY
        return key in self._keys

    def __len__(self) -> int:
        return len(self._keys)


_ABSENT = object()
_SEVERAL = object()


def _upper(v: Any) -> Optional[str]:
    s = clean_text(v)
    return s.upper() if s is not None else None


class LccPnrIndex:
    """(airline code, PNR) → LCC Detailed row ref. The first row added for a key wins
    (LCC Detailed is written newest upload first)."""

    __slots__ = ("_refs", "_airlines")

    def __init__(self) -> None:
        self._refs: dict[tuple[Optional[str], str], str] = {}
        self._airlines: dict[str, Union[Optional[str], object]] = {}

    def add(self, airline_code: Optional[str], pnr: Optional[str], row_ref: str) -> None:
        p = _upper(pnr)
        if p is None:
            return
        code = _upper(airline_code)
        self._refs.setdefault((code, p), row_ref)
        cur = self._airlines.get(p, _ABSENT)
        if cur is _ABSENT:
            self._airlines[p] = code
        elif cur != code:
            self._airlines[p] = _SEVERAL

    def get(self, airline_code: Optional[str], pnr: Optional[str]) -> Optional[str]:
        p = _upper(pnr)
        if p is None:
            return None
        code = _upper(airline_code)
        if code is None:
            holder = self._airlines.get(p, _ABSENT)
            if holder is _ABSENT or holder is _SEVERAL:
                return None          # PNRs are only unique within an airline
            return self._refs.get((holder, p))
        # A detailed row with no airline can still be this airline's booking.
        return self._refs.get((code, p)) or self._refs.get((None, p))

    def __len__(self) -> int:
        return len(self._refs)


class DuplicateTracker:
    """Same record uploaded twice: the first upload that shows it wins.

    Uploads are fed newest first, so the winner is the newest. Keys are stored as 8-byte
    blake2b digests (as ints) — a natural key tuple per row would cost ten times the memory.
    Repeats inside ONE upload are not duplicates (a file may legitimately list a line twice).
    """

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        self._seen: dict[int, int] = {}

    def check(self, source_key: str, natural_key: tuple, upload_idx: int) -> Optional[int]:
        """The winning upload_idx when this row is superseded, else None."""
        digest = hashlib.blake2b(
            repr((source_key, natural_key)).encode("utf-8", "surrogatepass"), digest_size=8,
        ).digest()
        first = self._seen.setdefault(int.from_bytes(digest, "big"), upload_idx)
        return None if first == upload_idx else first

    def __len__(self) -> int:
        return len(self._seen)


# ── BSP rows ──────────────────────────────────────────────────────────────────

def _doc_entries(items: Any) -> list[Any]:
    items = _json(items)
    if not isinstance(items, list):
        return []
    return [(e.get("doc") if isinstance(e, Mapping) else e) for e in items]


def _unique_keys(code: Optional[str], raws: Iterable[Any]) -> list[DocKey]:
    out: dict[DocKey, None] = {}
    for raw in raws:
        if isinstance(raw, (dict, list)):
            continue
        for k in doc_keys(code, raw):
            out[_canon_key(k)] = None
    return list(out)


def bsp_row_keys(row: Any) -> tuple[list[DocKey], list[DocKey]]:
    """``(document keys, RTDN keys)`` of a BSP detailed row, de-duplicated.

    Documents: document_number, ticket_number (a distributed CANX keeps the printed ticket
    there), every alt (conjunction) document and associated conjunction. RTDN: rtdn, the
    associated RTDN and every exchanged (``+RTDN``) document.
    """
    code = _link_code(_get(row, "airline_accounting_code"))
    assoc = _json(_get(row, "associated_docs"))
    assoc = assoc if isinstance(assoc, Mapping) else {}
    rtdn_obj = assoc.get("rtdn")
    docs = [
        _get(row, "document_number"), _get(row, "ticket_number"),
        *_doc_entries(_get(row, "alt_document_numbers")), *_doc_entries(assoc.get("conjunctions")),
    ]
    rtdns = [
        _get(row, "rtdn"),
        rtdn_obj.get("doc") if isinstance(rtdn_obj, Mapping) else rtdn_obj,
        *_doc_entries(assoc.get("exchanges")),
    ]
    return _unique_keys(code, docs), _unique_keys(code, rtdns)


def link_bsp_flags(row: Any, *, ndc_keys: KeySet, memo_keys: KeySet) -> list[str]:
    """``ALSO_IN_NDC`` / ``MEMO_UPLOADED`` for a BSP detailed row."""
    canon, _ = canon_bsp_txn(_get(row, "transaction_type"), _get(row, "associated_docs"))
    docs, rtdns = bsp_row_keys(row)
    flags: list[str] = []
    if any(k in ndc_keys for k in docs):
        _add_flag(flags, "ALSO_IN_NDC")
    if canon in (C.ADM, C.ACM, C.REFUND):
        memo_side = docs + rtdns if canon == C.REFUND else docs
        if any(k in memo_keys for k in memo_side):
            _add_flag(flags, "MEMO_UPLOADED")
    return flags


# ── ADM / ACM / RA (§C.4) ─────────────────────────────────────────────────────

def _find_first(sel: SelectionIndex, steps: Iterable[tuple[Optional[DocKey], frozenset, str]],
                flags: list[str]) -> Optional[RefView]:
    for key, types, via in steps:
        if key is None:
            continue
        m = sel.find(key, types, via)
        if m.ambiguous:
            _add_flag(flags, "LINK_AMBIGUOUS")
        if m.hit:
            return _pick(m)
    return None


def _set_billing(link: LinkResult, ref: RefView) -> None:
    if ref.in_period:
        link.also_in_bsp, link.counts_in_net = ALSO_THIS_REPORT, C.NET_MEMO_IN_BILLING
    else:
        link.also_in_bsp, link.counts_in_net = _also_other_period(ref.file_name), C.NET_MEMO_OTHER_PERIOD


def link_memo(kind: str, row: Any, sel: SelectionIndex) -> tuple[LinkResult, list[Probe]]:
    """An ADM / ACM against the BSP billing, plus the unresolved probes for the owner lookup.

    ``also_in_bsp="No"`` on an unresolved memo is provisional until ``finalize_pending``;
    ``counts_in_net`` stays None then so the mapper's "not yet billed (status…)" stands.
    """
    k = (kind or "").strip().lower()
    if k not in ("adm", "acm"):
        raise ValueError(f"link_memo kind must be 'adm' or 'acm', got {kind!r}")
    types = frozenset({C.ADM}) if k == "adm" else frozenset({C.ACM})
    code = _link_code(_get(row, "airline_code"))
    link = LinkResult(also_in_bsp=ALSO_NO)
    pending: list[Probe] = []

    key = doc_key(code, _get(row, "document_number"))
    memo_ref = _find_first(sel, ((key, types, "document"),), link.flags)
    if memo_ref is not None:
        _set_billing(link, memo_ref)
    elif key is not None:
        pending.append((key, types, "document"))

    related = doc_key(code, _get(row, "related_document"))
    ticket = _find_first(sel, (
        (related, _SALE_KINDS, "document"),
        (related, _REFUND_ONLY, "document"),
        (related, _REFUND_ONLY, "rtdn"),
    ), link.flags)
    if ticket is not None:
        link.linked_document, link.linked_via = ticket.document, _via_related(ticket.file_name)
    elif memo_ref is not None:
        link.linked_document, link.linked_via = memo_ref.document, VIA_BSP_MEMO_ROW
    return link, pending


def link_ra(row: Any, sel: SelectionIndex) -> tuple[LinkResult, list[Probe]]:
    """A BSPlink refund application against the BSP RFND/RFDA rows (by document, then RTDN)
    and its original ticket (the RTDN as a BSP sale / exchange / EMD document)."""
    code = _link_code(_get(row, "airline_code"))
    link = LinkResult(also_in_bsp=ALSO_NO)
    dkey = doc_key(code, _get(row, "document_number"))
    rkey = doc_key(code, _get(row, "rtdn_number"))
    steps = ((dkey, _REFUND_ONLY, "document"), (rkey, _REFUND_ONLY, "rtdn"))

    refund_ref = _find_first(sel, steps, link.flags)
    pending: list[Probe] = []
    if refund_ref is not None:
        _set_billing(link, refund_ref)
    else:
        pending = [(key, types, via) for key, types, via in steps if key is not None]

    ticket = _find_first(sel, ((rkey, _SALE_KINDS, "document"),), link.flags)
    if ticket is not None:
        link.linked_document, link.linked_via = ticket.document, VIA_ORIGINAL_TICKET
    elif refund_ref is not None:
        link.linked_document, link.linked_via = refund_ref.document, VIA_BSP_MEMO_ROW
    return link, pending


# ── TGQ (§C.5) and NDC (§C.6) ─────────────────────────────────────────────────

@dataclass
class TgqDecision:
    action: str                                  # "suppress" | "emit"
    link: LinkResult
    pending_probes: list[Probe] = field(default_factory=list)


def _membership(sel: SelectionIndex, keys: list[DocKey], types: frozenset, vias: tuple[str, ...],
                flags: list[str]) -> Optional[RefView]:
    """The in-period ref if any key hits in period, else the first out-of-period ref, else None."""
    outside: Optional[RefView] = None
    for key in keys:
        for via in vias:
            m = sel.find(key, types, via)
            if m.ambiguous:
                _add_flag(flags, "LINK_AMBIGUOUS")
            if not m.hit:
                continue
            ref = _pick(m)
            if ref.in_period:
                return ref
            if outside is None:
                outside = ref
    return outside


def decide_tgq(
    fold_code: Optional[str], serial: Optional[str], canon: str, sel: SelectionIndex,
    *, ndc_keys: KeySet, gds_keys: KeySet,
) -> TgqDecision:
    """Suppress a TGQ ticket BSP bills in this report; otherwise say why it is listed.

    Only a real 10-digit ticket serial can match BSP (a conjunction expands to every document
    it covers); anything else is unmatchable. An emitted row never counts in Net — HMPR is a
    GDS record, not a settlement.
    """
    keys = [k for k in doc_keys(_link_code(fold_code), serial) if _is_digits(k.serial, 10)]
    if not keys:
        return TgqDecision("emit", LinkResult(
            not_in_bsp=NOT_IN_BSP_UNKNOWN, counts_in_net=C.NET_TGQ_UNMATCHABLE, flags=["TGQ_UNMATCHABLE"],
        ))
    types, vias = TYPE_TARGETS.get(canon, TYPE_TARGETS[C.UNKNOWN])
    flags: list[str] = []
    ref = _membership(sel, keys, types, vias, flags)
    if ref is not None and ref.in_period:
        return TgqDecision("suppress", LinkResult(linked_document=ref.document, flags=flags))

    pending: list[Probe] = []
    if ref is not None:
        link = LinkResult(not_in_bsp=_tgq_outside(ref.file_name), counts_in_net=C.NET_TGQ_OUTSIDE_PERIOD, flags=flags)
    else:
        link = LinkResult(not_in_bsp=NOT_IN_BSP_YES, counts_in_net=C.NET_TGQ_NOT_IN_BSP, flags=flags)
        other = False
        for key in keys:
            m = sel.find_any(key)
            if m.ambiguous:
                _add_flag(flags, "LINK_AMBIGUOUS")
            other = other or m.hit
        if other:
            _add_flag(flags, "BSP_HAS_OTHER_TXN")
        else:
            pending = [(key, types, via) for key in keys for via in vias]
    if any(k in ndc_keys for k in keys):
        _add_flag(flags, "ALSO_IN_NDC")
    if any(k in gds_keys for k in keys):
        _add_flag(flags, "ALSO_IN_TP_GDS")
    return TgqDecision("emit", link, pending)


def decide_ndc(doc_key: Optional[DocKey], canon: str, sel: SelectionIndex) -> tuple[LinkResult, list[Probe]]:
    """An NDC group's ticket against BSP: a hit means BSP settles it (``No – settled in BSP``).

    Unresolved groups return provisional ``also_in_bsp="No"`` with ``counts_in_net`` None (the
    mapper's Yes) and the probes for the owner lookup.
    """
    if doc_key is None:
        return LinkResult(), []
    types, vias = _NDC_TARGETS.get(canon, _NDC_DEFAULT)
    link = LinkResult()
    ref = _membership(sel, [doc_key], types, vias, link.flags)
    if ref is None:
        link.also_in_bsp = ALSO_NO
        return link, [(doc_key, types, via) for via in vias]
    link.also_in_bsp = ALSO_THIS_REPORT if ref.in_period else _also_other_period(ref.file_name)
    link.counts_in_net = C.NET_NDC_IN_BSP
    return link, []


# ── owner lookup outside the selection (§C.7) ─────────────────────────────────

@dataclass(frozen=True)
class OwnerHit:
    """A row of a NON-included BSP statement returned by ``queries.bsp_owner_lookup``.
    ``canon`` may be canonical or the raw ``upper(transaction_type)``."""
    row_id: int
    code: Optional[str]
    document_number: Optional[str]
    ticket_number: Optional[str]
    rtdn: Optional[str]
    canon: str
    file_name: Optional[str]


def owner_probe_forms(keys: Iterable[Optional[DocKey]]) -> list[str]:
    """Text forms a BSP row may have stored a key as: serial, code+serial, and both with the
    leading zeros an Excel import drops (``0580570807`` → ``580570807``, ``098…`` → ``98…``)."""
    out: dict[str, None] = {}
    for key in keys:
        if key is None:
            continue
        forms = [key.serial]
        if key.code:
            forms += [key.code + key.serial, (key.code + key.serial).lstrip("0")]
        forms.append(key.serial.lstrip("0"))
        for f in forms:
            if f:
                out[f] = None
    return list(out)


def _hit_canon(raw: Optional[str]) -> str:
    if raw in _CANON_CODE:
        return raw
    return canon_bsp_txn(raw, None)[0]


def resolve_outside(probes: Sequence[Probe], hits: Sequence[OwnerHit]) -> list[Optional[OwnerHit]]:
    """For each probe, the matching owner hit (newest row id) or None — same index as probes.

    The SQL matched text forms only; here every hit is re-keyed with ``doc_key`` and held to
    the probe's type and side, with the same codeless rule as ``SelectionIndex.find``.
    """
    # (code, serial) → [(hit index, is_rtdn)]; serial → [(hit index, is_rtdn, code)]
    by_key: dict[tuple[Optional[str], str], list[tuple[int, bool]]] = {}
    by_serial: dict[str, list[tuple[int, bool, Optional[str]]]] = {}
    canons: list[str] = []
    for i, h in enumerate(hits):
        canons.append(_hit_canon(h.canon))
        code = _link_code(h.code)
        seen: set[tuple[DocKey, bool]] = set()
        for raw, is_rtdn in ((h.document_number, False), (h.ticket_number, False), (h.rtdn, True)):
            for k in doc_keys(code, raw):
                k = _canon_key(k)
                if (k, is_rtdn) in seen:
                    continue
                seen.add((k, is_rtdn))
                by_key.setdefault((k.code, k.serial), []).append((i, is_rtdn))
                by_serial.setdefault(k.serial, []).append((i, is_rtdn, k.code))

    def side_ok(is_rtdn: bool, via: str) -> bool:
        return via == "any" or (via == "rtdn") == is_rtdn

    out: list[Optional[OwnerHit]] = []
    for key, types, via in probes:
        if key is None:
            out.append(None)
            continue
        key = _canon_key(key)
        cands: list[int] = []
        if key.code is not None:
            for code in (key.code, None):
                cands = [i for i, r in by_key.get((code, key.serial), ())
                         if side_ok(r, via) and (types is None or canons[i] in types)]
                if cands:
                    break
        else:
            entries = by_serial.get(key.serial, ())
            if len({e[2] for e in entries}) == 1:       # exactly one code holds the serial
                cands = [i for i, r, _ in entries
                         if side_ok(r, via) and (types is None or canons[i] in types)]
        out.append(max((hits[i] for i in cands), key=lambda h: h.row_id) if cands else None)
    return out


def finalize_pending(kind: str, link: LinkResult, hit: Optional[OwnerHit]) -> LinkResult:
    """Apply the owner-lookup outcome to a provisional link (``kind``: memo | ra | tgq | ndc)."""
    out = replace(link, flags=list(link.flags))
    if kind in ("memo", "ra"):
        if hit is not None:
            out.also_in_bsp, out.counts_in_net = _also_other_upload(hit.file_name), C.NET_MEMO_OTHER_UPLOAD
        else:
            out.also_in_bsp, out.counts_in_net = ALSO_NO, None
    elif kind == "tgq":
        if hit is not None:
            out.not_in_bsp, out.counts_in_net = _tgq_other_upload(hit.file_name), C.NET_TGQ_OTHER_UPLOAD
        else:
            out.not_in_bsp, out.counts_in_net = NOT_IN_BSP_YES, C.NET_TGQ_NOT_IN_BSP
    elif kind == "ndc":
        if hit is not None:
            out.also_in_bsp, out.counts_in_net = _also_other_upload(hit.file_name), C.NET_MEMO_OTHER_UPLOAD
        else:
            out.also_in_bsp, out.counts_in_net = ALSO_NO, None
    else:
        raise ValueError(f"finalize_pending kind must be memo, ra, tgq or ndc, got {kind!r}")
    return out


# ── LCC (§C.8) and Third Party (§C.9) ─────────────────────────────────────────

def lcc_ledger_link(airline_code: Optional[str], pnrs: Iterable[Optional[str]], idx: LccPnrIndex) -> Optional[LinkResult]:
    """The first of ``pnrs`` (in order, e.g. Divided parent then child) found in LCC Detailed."""
    for pnr in pnrs:
        p = _upper(pnr)
        if p is not None and idx.get(airline_code, p) is not None:
            return LinkResult(linked_document=p, linked_via=VIA_LCC_PNR, flags=["ALSO_IN_LCC_DETAILED"])
    return None


def tp_flags(
    slug: str, *, gds_key: Optional[DocKey] = None, sel: Optional[SelectionIndex] = None,
    canon: Optional[str] = None, sale_key: Any = None, refund_key: Any = None,
    sale_keys: Optional[KeySet] = None,
) -> list[str]:
    """``ALSO_IN_BSP`` (the GDS ticket is in the BSP selection, any type) and
    ``TP_REFUND_WITHOUT_SALE`` (a refund whose supplier+ticket/PNR key has no sale).

    ``refund_key`` is the key to look up for a refund row; when the caller has only the row's
    own ``tp_sale_key`` it may pass that as ``sale_key``. With neither, nothing is flagged —
    an unkeyed refund cannot be proven orphaned.
    """
    flags: list[str] = []
    if gds_key is not None and sel is not None and sel.find_any(gds_key).hit:
        _add_flag(flags, "ALSO_IN_BSP")
    if canon == C.REFUND and sale_keys is not None:
        probe = refund_key if refund_key is not None else sale_key
        if probe is not None and probe not in sale_keys:
            _add_flag(flags, "TP_REFUND_WITHOUT_SALE")
    return flags
