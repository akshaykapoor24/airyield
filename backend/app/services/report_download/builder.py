"""Build one report workbook from an owner-verified selection.

The builder is the only place that knows the ORDER of things; every decision about a single
row lives in a pure module (mappers, linking, summary). The order matters because a row's
Combined values depend on rows of OTHER sources:

  A0  fingerprint every upload (a BSP / LCC statement re-processed since the request is left
      out as "not completed");
  A1  reference data: airline master, statement headers, owner-scoped BSP summaries by group,
      suppliers and declared airlines, TGQ file names;
  A2  key pre-passes BEFORE anything is written — the BSP selection index over every row of
      the included statements (in and out of the period; duplicate uploads de-duplicated
      newest first) and the memo / NDC / TP GDS ticket / TP sale key sets — so a TGQ ticket,
      a memo or an NDC line can be told apart as "in this report", "outside the period" or
      "in another upload" whatever order the sources are written in;
  A3  the TGQ enrichment index (report mode), only when BSP is included;
  B…H the sources in sheet order: BSP (+ BSP Summary), ADM/ACM/RA, TGQ, NDC, LCC Detailed
      (which fills the PNR index the ledgers G link to), LCC ledgers, Third Party;
  close-out: re-fingerprint, Summary (rank 2) and Read Me (rank 1) — written last because
      they describe everything above.

Unresolved links (a memo / TGQ ticket / NDC group whose BSP row is not in the selection) are
buffered and answered in batches by ``queries.bsp_owner_lookup`` against the user's other
BSP uploads, then applied with ``linking.finalize_pending``.

Two operational rules:

* ``state.tick`` is called per streamed chunk and per owner-lookup batch; it raises
  ``ReportCancelled`` (row deleted / retried) or ``ReportTimeout`` (cooperative deadline).
  Nothing here catches broad exceptions, so neither — nor Celery's SoftTimeLimitExceeded —
  can be swallowed.
* ``build_report`` never saves: the worker saves in a thread. On any failure the workbook's
  temp files are released here, because the caller never receives it.

The query layer is injectable (``q=``) so the whole pipeline runs in tests on fake rows.
"""
from __future__ import annotations

import json
import time
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import date
from types import SimpleNamespace
from typing import Any, Optional, Sequence

from app.config import settings
from app.services.report_download import columns as C
from app.services.report_download import linking
from app.services.report_download import normalize as N
from app.services.report_download import queries as default_queries
from app.services.report_download import readme
from app.services.report_download.lcc_codes import sort_codes
from app.services.report_download.mappers import adjustments, base, bsp, lcc, ndc, tgq
from app.services.report_download.mappers import third_party as tp
from app.services.report_download.registry import (
    COMBINED_SHEET, README_SHEET, SOURCES, SUMMARY_SHEET, get_source,
)
from app.services.report_download.selection import OwnedSelection, OwnedUpload
from app.services.report_download.summary import SummaryAccumulator
from app.services.report_download.types import (
    LinkResult, MapCtx, Period, ReportMeta, ReportOptions, UploadMeta,
)
from app.services.report_download.workbook import ColSpec, ReportWorkbook

#: Owner lookups are sent once this many probes are waiting (and at the end of each upload).
PENDING_PROBES_FLUSH = 1_000
#: Above this many rows an NDC upload is not re-grouped in memory; its stored grouping is used.
NDC_GROUPING_MAX_ROWS = 150_000

MEMO_KEYS = ("adm", "acm", "ra")
LEDGER_KEYS = ("lcc-di", "lcc-divided-pnr", "lcc-flown-report", "lcc-cta-bta")
TP_KEYS = ("tp-gds", "tp-lcc", "tp-api")
_CANX = frozenset({"CANX", "CANN"})
_LCC_DETAILED_TABLE = get_source("lcc-detailed").model.__tablename__

LINK_TGQ_SUPPRESSED = "TGQ tickets suppressed (in BSP)"
LINK_TGQ_DUPLICATE = "Duplicate TGQ tickets suppressed (newer upload)"

REASON_UNTICKED = "unticked"
REASON_NOT_COMPLETED = "not_completed"
REASON_NO_ROWS = "no_rows_in_period"
REASON_DELETED = "Deleted before the build"
NOTE_CHANGED = "Changed during the build (re-processed or edited); generate the report again for a consistent copy"

_SHEET_DESCRIPTIONS = {
    "combined": "Every included row in one layout; only Counts In Net = Yes rows are totalled on Summary",
    "bsp": "BSP Detailed rows as stored, with the tax-code pivot",
    "bsp-summary": "BSP Summary PDF lines as stored, with Line Kind / Use For Totals",
    "tgq-hmpr": "TGQ HMPR as stored, one row per flown sector (leg)",
}


class ReportCancelled(Exception):
    """The report row was deleted or taken over by a retry; stop quietly."""


class ReportTimeout(Exception):
    """The cooperative build deadline passed."""


@dataclass
class BuildState:
    """Progress shared with the heartbeat task (``processed`` / ``stage``) and the stop signals
    it sets (``cancelled``). ``deadline`` is a ``time.monotonic()`` value; 0 means none."""
    processed: int = 0
    stage: str = ""
    cancelled: bool = False
    deadline: float = 0.0

    def tick(self, n: int = 0, stage: Optional[str] = None) -> None:
        if stage is not None:
            self.stage = stage
        self.processed += n
        if self.cancelled:
            raise ReportCancelled()
        if self.deadline and time.monotonic() > self.deadline:
            raise ReportTimeout()


@dataclass
class BuildResult:
    workbook: ReportWorkbook
    sheet_row_counts: dict[str, int]
    summary: dict
    combined_rows: int
    files_included: list[dict]
    files_excluded: list[dict]


@dataclass
class _FileStats:
    rows_in_file: int = 0
    rows_included: int = 0
    rows_undated: int = 0
    rows_superseded: int = 0
    fingerprint: Any = None
    notes: list[str] = field(default_factory=list)


def _view(row: Any, **extra: Any) -> SimpleNamespace:
    """A mutable attribute view of a DB row (or a test namespace) plus builder-added fields."""
    mapping = getattr(row, "_mapping", None)
    values = dict(mapping) if mapping is not None else dict(vars(row))
    values.update(extra)
    return SimpleNamespace(**values)


def _undated(row: Any) -> bool:
    return bool(getattr(row, default_queries.UNDATED_ATTR, False))


def _superseded(link: Optional[LinkResult]) -> LinkResult:
    out = replace(link, flags=list(link.flags)) if link is not None else LinkResult()
    out.counts_in_net = C.NET_SUPERSEDED
    if "DUPLICATE_SUPERSEDED" not in out.flags:
        out.flags.append("DUPLICATE_SUPERSEDED")
    return out


def _json(v: Any) -> Any:
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def _docs(items: Any) -> list[str]:
    """Document strings of a JSONB list whose entries are strings or ``{"doc": …}``."""
    items = _json(items)
    if not isinstance(items, list):
        return []
    out = []
    for e in items:
        s = N.clean_text(e.get("doc") if isinstance(e, dict) else e)
        if s:
            out.append(s)
    return out


def _combined_values(row: dict) -> list[Any]:
    return [C.flags_text(row) if k == "data_flags" else row.get(k) for k in C.COMBINED_KEYS]


_COMBINED_SPECS = [ColSpec(c.header, c.kind, c.width) for c in C.COMBINED_COLUMNS]


class _Build:
    def __init__(self, conn: Any, sel: OwnedSelection, params: dict, meta: ReportMeta,
                 workbook_path: str, state: BuildState, q: Any) -> None:
        self.conn, self.sel, self.meta, self.state, self.q = conn, sel, meta, state, q
        self.t, self.u = sel.tenant_id, sel.user_id
        self.options: ReportOptions = meta.options
        self.period: Period = meta.period or Period(
            date.fromisoformat(params["date_from"]), date.fromisoformat(params["date_to"]))
        self.transaction = self.options.basis == "transaction"
        self.partial_bsp = self.transaction and self.options.bsp_scope == "issue_date"
        self.detail = bool(self.options.include_detail_sheets)

        self.wb = ReportWorkbook(workbook_path, styled=settings.REPORT_EXPORT_STYLED_CELLS)
        self.summary = SummaryAccumulator()
        self.dups = linking.DuplicateTracker()
        self.sel_index = linking.SelectionIndex()
        self.memo_keys = linking.KeySet()
        self.ndc_keys = linking.KeySet()
        self.gds_keys = linking.KeySet()
        self.sale_keys = linking.KeySet()
        self.pnr_index = linking.LccPnrIndex()
        self.bsp_superseded: set[int] = set()
        self.bsp_legacy = False

        self.active: dict[str, list[OwnedUpload]] = {}
        self.metas: dict[tuple[str, str], UploadMeta] = {}
        self.stats: dict[tuple[str, str], _FileStats] = {}
        self.excluded: list[dict] = []
        self.ctx_extra: dict[str, dict[str, Any]] = {}      # source → {extra_keys, tax_codes}
        self.detail_cols: dict[str, list] = {}
        self.airlines = None
        self.tgq_index = None
        self.tgq_stats: Optional[dict] = None
        self.tgq_files: dict[str, str] = {}

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _ctx(self, source_key: str, up: OwnedUpload) -> MapCtx:
        extra = self.ctx_extra.get(source_key, {})
        return MapCtx(
            upload=self.metas[(source_key, up.upload_id)], options=self.options, period=self.period,
            airlines=self.airlines, tgq=self.tgq_index, tgq_files=self.tgq_files,
            extra_keys=tuple(extra.get("extra_keys", ())), tax_codes=tuple(extra.get("tax_codes", ())),
        )

    def _emit(self, source_key: str, row: dict) -> None:
        self.wb.append(COMBINED_SHEET.key, _combined_values(row))
        self.summary.add_combined(row, source_key=source_key)

    def _write_detail(self, source_key: str, mapper: Any, ctx: MapCtx, row: Any) -> int:
        if not self.detail:
            return 0
        cols = self.detail_cols.get(source_key)
        if cols is None:
            cols = self.detail_cols[source_key] = mapper.detail_columns(source_key, ctx)
        if not self.wb.has_sheet(source_key):
            src = get_source(source_key)
            self.wb.ensure_sheet(source_key, src.sheet_title, base.column_specs(cols), src.rank)
        self.wb.append(source_key, base.detail_values(cols, row, ctx))
        return 1

    def _stats(self, source_key: str, up: OwnedUpload) -> _FileStats:
        return self.stats[(source_key, up.upload_id)]

    @asynccontextmanager
    async def _stream(self, source_key: str, up: OwnedUpload, **kw: Any):
        """One upload's rows; the read transaction ends as soon as the stream is closed.

        A build can run for tens of minutes. Holding one transaction for all of it would pin
        a snapshot (vacuum falls behind) and make any DDL on a statement table queue behind
        it — and every read queue behind that DDL. Everything the build links on is already
        in memory, so nothing needs one snapshot across uploads."""
        meta = self.metas[(source_key, up.upload_id)]
        async with aclosing(self.q.stream_rows(
                self.conn, self.t, self.u, source_key, up.upload_id, period=self.period,
                options=self.options, header=meta.header, **kw)) as chunks:
            yield chunks
        await self._end_read()

    async def _end_read(self) -> None:
        in_transaction = getattr(self.conn, "in_transaction", None)
        commit = getattr(self.conn, "commit", None)
        if callable(in_transaction) and callable(commit) and in_transaction():
            await commit()

    async def _owner_hits(self, pending: list[tuple[list, Any]]) -> list[Optional[linking.OwnerHit]]:
        """One owner lookup for every probe of ``pending``; the first hit per item."""
        flat = [p for probes, _ in pending for p in probes]
        if not flat:
            return [None] * len(pending)
        forms = linking.owner_probe_forms(p[0] for p in flat)
        hits = await self.q.bsp_owner_lookup(self.conn, self.t, self.u, self.active_ids("bsp"), forms) if forms else []
        resolved = linking.resolve_outside(flat, hits) if hits else [None] * len(flat)
        out, i = [], 0
        for probes, _ in pending:
            chunk = resolved[i:i + len(probes)]
            i += len(probes)
            out.append(next((h for h in chunk if h is not None), None))
        self.state.tick(0)
        return out

    def active_ids(self, source_key: str) -> list[str]:
        return [u.upload_id for u in self.active.get(source_key, ())]

    # ── A0 / A1 ──────────────────────────────────────────────────────────────

    async def check_uploads(self) -> None:
        self.state.tick(stage="Checking uploads")
        for src in SOURCES:
            ups = self.sel.for_source(src.key)
            if not ups:
                continue
            fps = await self.q.upload_fingerprints(self.conn, self.t, self.u, src.key, [x.upload_id for x in ups])
            keep = []
            for up in ups:
                fp = fps.get(up.upload_id)
                if fp is None:
                    self._exclude(src.key, up, REASON_DELETED)
                elif src.completed_only and (fp[0] or "").lower() != "completed":
                    self._exclude(src.key, up, REASON_NOT_COMPLETED)
                else:
                    keep.append(up)
                    self.stats[(src.key, up.upload_id)] = _FileStats(rows_in_file=up.total_rows, fingerprint=fp)
            if keep:
                self.active[src.key] = keep

    @staticmethod
    def _excluded_item(source_key: str, up: OwnedUpload, reason: str) -> dict:
        return {"category": get_source(source_key).category, "source_type": source_key,
                "file_name": up.file_name, "upload_id": up.upload_id, "reason": reason}

    def _exclude(self, source_key: str, up: OwnedUpload, reason: str) -> None:
        self.excluded.append(self._excluded_item(source_key, up, reason))

    async def load_reference(self) -> None:
        self.state.tick(stage="Loading reference data")
        q, conn, t, u = self.q, self.conn, self.t, self.u
        self.airlines = await q.airline_master(conn)

        bsp_headers = await q.bsp_statement_headers(conn, t, u, self.active_ids("bsp")) if self.active.get("bsp") else {}
        groups = {getattr(h, "group_id", None) for h in bsp_headers.values()} - {None}
        summaries = await q.bsp_summaries_by_group(conn, t, u, groups) if groups else {}
        sum_headers = (await q.bsp_summary_statement_headers(conn, t, u, self.active_ids("bsp-summary"))
                       if self.active.get("bsp-summary") else {})
        lcc_headers, lcc_airlines = {}, {}
        if self.active.get("lcc-detailed"):
            ids = self.active_ids("lcc-detailed")
            lcc_headers = await q.lcc_batch_headers(conn, t, u, ids)
            lcc_airlines = await q.lcc_batch_airlines(conn, t, u, ids)
        airlines = {k: await q.batch_airlines(conn, t, u, k, self.active_ids(k)) for k in LEDGER_KEYS if self.active.get(k)}
        suppliers = {k: await q.supplier_snapshots(conn, t, u, k, self.active_ids(k)) for k in TP_KEYS if self.active.get(k)}
        if self.active.get("bsp") or self.active.get("tgq-hmpr"):
            self.tgq_files = await q.tgq_file_names(conn, t, u)

        for key, ups in self.active.items():
            for idx, up in enumerate(ups):
                header = summary_header = supplier = airline = None
                source_format = None
                uploaded_at, reference = up.uploaded_at, up.reference
                if key == "bsp":
                    header = bsp_headers.get(up.upload_id)
                    summary_header = summaries.get(getattr(header, "group_id", None))
                    uploaded_at = getattr(header, "created_at", None) or uploaded_at
                    reference = (getattr(summary_header, "agent_name", None)
                                 or getattr(header, "statement_name", None) or reference)
                elif key == "bsp-summary":
                    header = sum_headers.get(up.upload_id)
                    reference = getattr(header, "agent_name", None) or reference
                elif key == "lcc-detailed":
                    header = lcc_headers.get(up.upload_id)
                    airline = lcc_airlines.get(up.upload_id)
                    source_format = getattr(header, "source_format", None)
                    reference = (getattr(header, "airline_name", None) or getattr(airline, "name", None) or reference)
                elif key in LEDGER_KEYS:
                    airline = airlines[key].get(up.upload_id)
                    reference = getattr(airline, "name", None) or reference
                elif key in TP_KEYS:
                    supplier = suppliers[key].get(up.upload_id)
                    reference = getattr(supplier, "name", None) or reference
                self.metas[(key, up.upload_id)] = UploadMeta(
                    source_key=key, upload_id=up.upload_id, file_name=up.file_name, uploaded_at=uploaded_at,
                    upload_idx=idx, status=up.status, reference=reference, total_rows=up.total_rows,
                    header=header, summary_header=summary_header, supplier=supplier, airline=airline,
                    source_format=source_format,
                )

    # ── A2 / A3 ──────────────────────────────────────────────────────────────

    async def prepass(self) -> None:
        self.state.tick(stage="Indexing BSP documents")
        for idx, up in enumerate(self.active.get("bsp", ())):
            meta = self.metas[("bsp", up.upload_id)]
            st = self._stats("bsp", up)
            outside = 0
            async with aclosing(self.q.stream_bsp_keys(
                    self.conn, self.t, self.u, up.upload_id, header=meta.header, period=self.period,
                    options=self.options)) as chunks:
                async for chunk in chunks:
                    for r in chunk:
                        canon, legacy = bsp.bsp_canon(r)
                        self.bsp_legacy = self.bsp_legacy or legacy
                        if not r.in_period:
                            outside += 1
                        if self.dups.check("bsp", bsp.bsp_natural_key(r), idx) is not None:
                            self.bsp_superseded.add(r.id)
                            continue
                        docs, rtdns = linking.bsp_row_keys(r)
                        spdr = N.clean_text(getattr(r, "spdr_no", None))
                        ttype = (N.clean_text(r.transaction_type) or "").upper()
                        document = r.ticket_number if ttype in _CANX and spdr else r.document_number
                        self.sel_index.add(
                            row_id=r.id, upload_idx=idx, file_name=meta.file_name, canon=canon,
                            in_period=bool(r.in_period), doc_keys=docs, rtdn_keys=rtdns,
                            document=N.clean_text(document) or N.clean_text(r.document_number),
                        )
                    self.state.tick(0)
            if outside and self.partial_bsp:
                st.notes.append(f"{outside:,} rows issued outside the period left out (still used for linking)")

        self.state.tick(stage="Indexing memo, NDC and Third Party keys")
        for kind in MEMO_KEYS:
            cols = ("id", "airline_code", "document_number") + (("rtdn_number",) if kind == "ra" else ())
            for up in self.active.get(kind, ()):
                async with self._stream(kind, up, columns=cols, filter_period=False) as chunks:
                    async for chunk in chunks:
                        for r in chunk:
                            code = adjustments.memo_code(r)
                            self.memo_keys.add(N.doc_key(code, r.document_number))
                            if kind == "ra":
                                self.memo_keys.add(N.doc_key(code, r.rtdn_number))
                        self.state.tick(0)
        for up in self.active.get("ndc", ()):
            async with self._stream("ndc", up, columns=("id", "data"), filter_period=False) as chunks:
                async for chunk in chunks:
                    for r in chunk:
                        d = r.data if isinstance(r.data, dict) else {}
                        self.ndc_keys.add(N.doc_key(d.get("airline_iata_code"), d.get("document_no")))
                    self.state.tick(0)
        for slug in ("tp-gds", "tp-lcc"):
            for up in self.active.get(slug, ()):
                ctx = self._ctx(slug, up)
                async with self._stream(slug, up, columns=("id", "data", "source_format"), filter_period=False) as chunks:
                    async for chunk in chunks:
                        for r in chunk:
                            if slug == "tp-gds":
                                self.gds_keys.add(tp.gds_ticket_key(r))
                            self.sale_keys.add(tp.tp_sale_key(slug, r, ctx))
                        self.state.tick(0)

    async def load_tgq(self) -> None:
        if not self.active.get("bsp"):
            return
        self.state.tick(stage="Loading TGQ enrichment")
        exclude = frozenset(self.sel.unticked_ids("tgq-hmpr"))
        self.tgq_index = await self.q.load_tgq_index(
            self.conn, self.t, self.u, exclude_batch_ids=exclude, report_mode=True,
            max_rows=settings.REPORT_TGQ_MAX_ROWS)
        idx = self.tgq_index
        self.tgq_stats = {"rows_loaded": getattr(idx, "rows_loaded", 0),
                          "batches_used": getattr(idx, "batches_used", 0),
                          "truncated": bool(getattr(idx, "truncated", False))}

    # ── B: BSP ───────────────────────────────────────────────────────────────

    def _tgq_match(self, view: Any, canon: str) -> tuple[Any, Optional[str]]:
        index = self.tgq_index
        if index is None:
            return None, None
        code = bsp.bsp_code(view)
        ttype = (N.clean_text(view.transaction_type) or "").upper()
        if ttype in _CANX and N.clean_text(view.spdr_no):
            document, alts = N.clean_text(view.ticket_number), []
        else:
            assoc = _json(view.associated_docs)
            assoc = assoc if isinstance(assoc, dict) else {}
            document = N.clean_text(view.document_number)
            alts = _docs(view.alt_document_numbers) + _docs(assoc.get("conjunctions"))
        extras: list[str] = []
        if canon in (C.REFUND, C.ADM, C.ACM):
            assoc = _json(view.associated_docs)
            assoc = assoc if isinstance(assoc, dict) else {}
            rtdn_obj = assoc.get("rtdn")
            raw = [view.rtdn, rtdn_obj.get("doc") if isinstance(rtdn_obj, dict) else rtdn_obj]
            extras = [s for s in (N.clean_text(x) for x in raw) if s] + _docs(assoc.get("exchanges"))
        return index.match(code, document, alts, extra_documents=extras, allow_codeless=code is None)

    async def write_bsp(self) -> None:
        ups = self.active.get("bsp", ())
        if ups:
            self.state.tick(stage="Writing BSP")
            codes = await self.q.bsp_tax_codes(self.conn, self.t, self.u, self.active_ids("bsp"))
            self.ctx_extra["bsp"] = {"tax_codes": tuple(codes),
                                     "extra_keys": (bsp.LEGACY_KEY,) if self.bsp_legacy else ()}
        scope = "partial" if self.partial_bsp else "full"
        for up in ups:
            ctx = self._ctx("bsp", up)
            st = self._stats("bsp", up)
            self.summary.set_bsp_statement(up.upload_id, ctx.upload.header, ctx.upload.summary_header, scope)
            async with self._stream("bsp", up) as chunks:
                async for chunk in chunks:
                    taxes = await self.q.bsp_tax_components(self.conn, self.t, self.u, [r.id for r in chunk])
                    written = 0
                    for r in chunk:
                        view = _view(r, taxes=taxes.get(r.id, []))
                        canon, _ = bsp.bsp_canon(view)
                        flags = linking.link_bsp_flags(view, ndc_keys=self.ndc_keys, memo_keys=self.memo_keys)
                        link = LinkResult(flags=flags) if flags else None
                        if view.id in self.bsp_superseded:
                            link = _superseded(link)
                            st.rows_superseded += 1
                        row = bsp.to_common("bsp", view, ctx, link, tgq=self._tgq_match(view, canon))
                        self._emit("bsp", row)
                        written += 1 + self._write_detail("bsp", bsp, ctx, view)
                        self.summary.add_bsp_row(up.upload_id, view, bsp.tie_out_section(view))
                        st.rows_included += 1
                        if "DATE_UNREADABLE" in row["data_flags"]:
                            st.rows_undated += 1
                    self.state.tick(written)

        for up in self.active.get("bsp-summary", ()):
            ctx = self._ctx("bsp-summary", up)
            st = self._stats("bsp-summary", up)
            rows: list[Any] = []
            async with self._stream("bsp-summary", up) as chunks:
                async for chunk in chunks:
                    rows.extend(chunk)
                    self.state.tick(0)
            kinds = bsp.summary_line_kinds(rows)
            written = 0
            for r in rows:
                kind, use = kinds.get(r.id, (None, None))
                written += self._write_detail("bsp-summary", bsp, ctx, _view(r, line_kind=kind, use_for_totals=use))
                st.rows_included += 1
            if not self.detail:
                st.notes.append("Summary PDF lines are written only to the BSP Summary sheet, which is turned off")
            self.state.tick(written)

    # ── C: ADM / ACM / RA ────────────────────────────────────────────────────

    async def write_memos(self) -> None:
        for kind in MEMO_KEYS:
            ups = self.active.get(kind, ())
            if ups:
                self.state.tick(stage=f"Writing {get_source(kind).label}")
            final = "ra" if kind == "ra" else "memo"
            for idx, up in enumerate(ups):
                ctx = self._ctx(kind, up)
                st = self._stats(kind, up)
                pending: list[tuple[list, Any]] = []
                waiting = 0
                async with self._stream(kind, up) as chunks:
                    async for chunk in chunks:
                        written = 0
                        for r in chunk:
                            st.rows_included += 1
                            st.rows_undated += _undated(r)
                            written += self._write_detail(kind, adjustments, ctx, r)
                            if self.dups.check(kind, adjustments.memo_natural_key(kind, r), idx) is not None:
                                st.rows_superseded += 1
                                self._emit(kind, adjustments.to_common(kind, r, ctx, _superseded(None)))
                                written += 1
                                continue
                            link, probes = (linking.link_ra(r, self.sel_index) if kind == "ra"
                                            else linking.link_memo(kind, r, self.sel_index))
                            if probes:
                                pending.append((probes, (r, link)))
                                waiting += len(probes)
                                if waiting >= PENDING_PROBES_FLUSH:
                                    written += await self._flush_memos(kind, final, ctx, pending)
                                    pending, waiting = [], 0
                            else:
                                self._emit(kind, adjustments.to_common(kind, r, ctx, link))
                                written += 1
                        self.state.tick(written)
                self.state.tick(await self._flush_memos(kind, final, ctx, pending))

    async def _flush_memos(self, kind: str, final: str, ctx: MapCtx, pending: list) -> int:
        if not pending:
            return 0
        for (probes, (r, link)), hit in zip(pending, await self._owner_hits(pending)):
            self._emit(kind, adjustments.to_common(kind, r, ctx, linking.finalize_pending(final, link, hit)))
        return len(pending)

    # ── D: TGQ HMPR ──────────────────────────────────────────────────────────

    async def write_tgq(self) -> None:
        ups = self.active.get("tgq-hmpr", ())
        if ups:
            self.state.tick(stage="Writing TGQ HMPR")
            keys = await self.q.distinct_data_keys(self.conn, self.t, self.u, "tgq-hmpr",
                                                   self.active_ids("tgq-hmpr"), self.options.include_pii)
            self.ctx_extra["tgq-hmpr"] = {"extra_keys": keys}
        for idx, up in enumerate(ups):
            ctx = self._ctx("tgq-hmpr", up)
            st = self._stats("tgq-hmpr", up)
            counts = {"tickets": 0, "listed": 0, "in_bsp": 0, "duplicate": 0}
            pending: list[tuple[list, Any]] = []
            grouper = tgq.TgqLegGrouper()
            async with self._stream("tgq-hmpr", up) as chunks:
                async for chunk in chunks:
                    written = 0
                    for legs in grouper.feed(chunk):
                        written += await self._tgq_ticket(legs, idx, ctx, st, counts, pending)
                    self.state.tick(written)
            last = grouper.flush()
            written = await self._tgq_ticket(last, idx, ctx, st, counts, pending) if last else 0
            written += await self._flush_tgq(ctx, pending)
            self.state.tick(written)
            if counts["tickets"]:
                st.notes.append(
                    f"{counts['tickets']:,} tickets: {counts['listed']:,} listed, {counts['in_bsp']:,} in BSP "
                    f"(not repeated), {counts['duplicate']:,} also in a newer TGQ upload")

    async def _tgq_ticket(self, legs: list, idx: int, ctx: MapCtx, st: _FileStats, counts: dict,
                          pending: list) -> int:
        """One ticket's legs: detail rows, then suppress (BSP bills it / newer TGQ copy) or emit."""
        st.rows_included += len(legs)
        st.rows_undated += sum(1 for leg in legs if _undated(leg))
        written = sum(self._write_detail("tgq-hmpr", tgq, ctx, leg) for leg in legs)
        fold = tgq.fold_tgq_ticket(legs)
        if fold is None:                       # the file's own grand-total line
            return written
        counts["tickets"] += 1
        nk = tgq.tgq_natural_key(fold)
        if nk is not None and self.dups.check("tgq-hmpr", nk, idx) is not None:
            counts["duplicate"] += 1
            st.rows_superseded += len(legs)
            self.summary.add_link_stat(LINK_TGQ_DUPLICATE)
            return written
        decision = linking.decide_tgq(fold.code, fold.serial, fold.canon, self.sel_index,
                                      ndc_keys=self.ndc_keys, gds_keys=self.gds_keys)
        if decision.action == "suppress":
            counts["in_bsp"] += 1
            self.summary.add_link_stat(LINK_TGQ_SUPPRESSED)
            return written
        counts["listed"] += 1
        if not decision.pending_probes:
            self._emit("tgq-hmpr", tgq.to_common("tgq-hmpr", fold, ctx, decision.link))
            return written + 1
        pending.append((decision.pending_probes, (fold, decision.link)))
        if sum(len(p) for p, _ in pending) >= PENDING_PROBES_FLUSH:
            written += await self._flush_tgq(ctx, pending)
        return written

    async def _flush_tgq(self, ctx: MapCtx, pending: list) -> int:
        if not pending:
            return 0
        for (probes, (fold, link)), hit in zip(pending, await self._owner_hits(pending)):
            self._emit("tgq-hmpr", tgq.to_common("tgq-hmpr", fold, ctx, linking.finalize_pending("tgq", link, hit)))
        n = len(pending)
        pending.clear()
        return n

    # ── E: NDC ───────────────────────────────────────────────────────────────

    async def write_ndc(self) -> None:
        ups = self.active.get("ndc", ())
        if ups:
            self.state.tick(stage="Writing NDC")
            keys = await self.q.distinct_data_keys(self.conn, self.t, self.u, "ndc", self.active_ids("ndc"),
                                                   self.options.include_pii)
            self.ctx_extra["ndc"] = {"extra_keys": keys}
        for idx, up in enumerate(ups):
            ctx = self._ctx("ndc", up)
            if up.total_rows <= NDC_GROUPING_MAX_ROWS:
                await self._ndc_grouped(idx, up, ctx)
            else:
                await self._ndc_stored(idx, up, ctx)

    async def _ndc_links(self, groups: Sequence[Any]) -> dict[int, LinkResult]:
        """Membership once per group (every row of a group shares it)."""
        links: dict[int, LinkResult] = {}
        pending: list[tuple[list, Any]] = []
        waiting = 0
        for g in groups:
            link, probes = linking.decide_ndc(ndc.group_doc_key(g), ndc.group_canon(g), self.sel_index)
            if probes:
                pending.append((probes, (g, link)))
                waiting += len(probes)
                if waiting >= PENDING_PROBES_FLUSH:
                    await self._resolve_ndc(pending, links)
                    pending, waiting = [], 0
            else:
                links[id(g)] = link
        await self._resolve_ndc(pending, links)
        return links

    async def _resolve_ndc(self, pending: list, links: dict[int, LinkResult]) -> None:
        if not pending:
            return
        for (probes, (g, link)), hit in zip(pending, await self._owner_hits(pending)):
            links[id(g)] = linking.finalize_pending("ndc", link, hit)

    async def _ndc_grouped(self, idx: int, up: OwnedUpload, ctx: MapCtx) -> None:
        st = self._stats("ndc", up)
        rows: list[Any] = []
        async with self._stream("ndc", up, flag_period=True) as chunks:
            async for chunk in chunks:
                rows.extend(chunk)
                self.state.tick(0)
        groups = ndc.ndc_groups(rows)
        by_row = ndc.groups_by_row(groups)
        included = [r for r in rows if getattr(r, default_queries.IN_PERIOD_ATTR, True)]
        wanted = {id(by_row[r.id]): by_row[r.id] for r in included if r.id in by_row}
        links = await self._ndc_links(list(wanted.values()))
        written = 0
        for r in included:
            g = by_row.get(r.id)
            written += self._ndc_row(idx, st, ctx, r, g, links.get(id(g)) if g is not None else None)
            if written >= default_queries.STREAM_CHUNK:
                self.state.tick(written)
                written = 0
        self.state.tick(written)

    async def _ndc_stored(self, idx: int, up: OwnedUpload, ctx: MapCtx) -> None:
        st = self._stats("ndc", up)
        st.notes.append("Very large NDC upload: the stored billing grouping was used")
        async with self._stream("ndc", up) as chunks:
            async for chunk in chunks:
                singles = [ndc.NdcGroup(key=f"O:{r.id}", anchor=r, rows=[r], total=None) for r in chunk]
                links = await self._ndc_links(singles)
                written = 0
                for r, g in zip(chunk, singles):
                    written += self._ndc_row(idx, st, ctx, r, None, links.get(id(g)))
                self.state.tick(written)

    def _ndc_row(self, idx: int, st: _FileStats, ctx: MapCtx, r: Any, group: Any, link: Optional[LinkResult]) -> int:
        st.rows_included += 1
        st.rows_undated += _undated(r)
        if self.dups.check("ndc", ndc.ndc_natural_key(r), idx) is not None:
            st.rows_superseded += 1
            link = _superseded(link)
        self._emit("ndc", ndc.to_common("ndc", r, ctx, link, group=group))
        return 1 + self._write_detail("ndc", ndc, ctx, r)

    # ── F / G: LCC ───────────────────────────────────────────────────────────

    async def write_lcc_detailed(self) -> None:
        ups = self.active.get("lcc-detailed", ())
        if not ups:
            return
        self.state.tick(stage="Writing LCC Detailed")
        ids = self.active_ids("lcc-detailed")
        codes = await self.q.lcc_tax_codes(self.conn, self.t, self.u, ids)
        extra = await self.q.lcc_extra_keys(self.conn, self.t, self.u, ids, self.options.include_pii)
        self.ctx_extra["lcc-detailed"] = {"tax_codes": tuple(sort_codes(codes)), "extra_keys": tuple(extra)}
        for idx, up in enumerate(ups):
            ctx = self._ctx("lcc-detailed", up)
            st = self._stats("lcc-detailed", up)
            header, snap = ctx.upload.header, ctx.upload.airline
            fallback_code = getattr(header, "airline_code", None) or getattr(snap, "code", None)
            async with self._stream("lcc-detailed", up) as chunks:
                async for chunk in chunks:
                    written = 0
                    for r in chunk:
                        st.rows_included += 1
                        st.rows_undated += _undated(r)
                        link = None
                        if self.dups.check("lcc-detailed", lcc.lcc_natural_key(r), idx) is not None:
                            st.rows_superseded += 1
                            link = _superseded(None)
                        else:
                            self.pnr_index.add(r.airline_code or fallback_code, r.record_locator,
                                               base.row_ref(_LCC_DETAILED_TABLE, r.id))
                        self._emit("lcc-detailed", lcc.to_common("lcc-detailed", r, ctx, link))
                        written += 1 + self._write_detail("lcc-detailed", lcc, ctx, r)
                    self.state.tick(written)

    async def write_ledgers(self) -> None:
        for slug in LEDGER_KEYS:
            ups = self.active.get(slug, ())
            if not ups:
                continue
            self.state.tick(stage=f"Writing {get_source(slug).label}")
            keys = await self.q.distinct_data_keys(self.conn, self.t, self.u, slug, self.active_ids(slug),
                                                   self.options.include_pii)
            self.ctx_extra[slug] = {"extra_keys": keys}
            for idx, up in enumerate(ups):
                ctx = self._ctx(slug, up)
                st = self._stats(slug, up)
                snap_code = getattr(ctx.upload.airline, "code", None)
                async with self._stream(slug, up) as chunks:
                    async for chunk in chunks:
                        written = 0
                        for r in chunk:
                            st.rows_included += 1
                            st.rows_undated += _undated(r)
                            d = r.data if isinstance(r.data, dict) else {}
                            code = N.clean_text(d.get("airline_code")) or snap_code
                            link = linking.lcc_ledger_link(code, lcc.ledger_pnrs(slug, r), self.pnr_index)
                            if self.dups.check(slug, lcc.ledger_natural_key(slug, r, ctx), idx) is not None:
                                st.rows_superseded += 1
                                link = _superseded(link)
                            self._emit(slug, lcc.to_common(slug, r, ctx, link))
                            written += 1 + self._write_detail(slug, lcc, ctx, r)
                        self.state.tick(written)

    # ── H: Third Party ───────────────────────────────────────────────────────

    async def write_third_party(self) -> None:
        for slug in TP_KEYS:
            ups = self.active.get(slug, ())
            if not ups:
                continue
            self.state.tick(stage=f"Writing {get_source(slug).label}")
            keys = await self.q.distinct_data_keys(self.conn, self.t, self.u, slug, self.active_ids(slug),
                                                   self.options.include_pii)
            self.ctx_extra[slug] = {"extra_keys": keys}
            for idx, up in enumerate(ups):
                ctx = self._ctx(slug, up)
                st = self._stats(slug, up)
                async with self._stream(slug, up) as chunks:
                    async for chunk in chunks:
                        written = 0
                        for r in chunk:
                            st.rows_included += 1
                            st.rows_undated += _undated(r)
                            d = r.data if isinstance(r.data, dict) else {}
                            flags = linking.tp_flags(
                                slug,
                                gds_key=tp.gds_ticket_key(r) if slug == "tp-gds" else None,
                                sel=self.sel_index, canon=tp.tp_canon(slug, d),
                                sale_key=tp.tp_sale_key(slug, r, ctx), refund_key=tp.tp_refund_key(slug, r, ctx),
                                sale_keys=self.sale_keys if slug != "tp-api" else None,
                            )
                            link = LinkResult(flags=flags) if flags else None
                            if self.dups.check(slug, tp.tp_natural_key(slug, r, ctx), idx) is not None:
                                st.rows_superseded += 1
                                link = _superseded(link)
                            self._emit(slug, tp.to_common(slug, r, ctx, link))
                            written += 1 + self._write_detail(slug, tp, ctx, r)
                        self.state.tick(written)

    # ── close-out ────────────────────────────────────────────────────────────

    async def close_out(self) -> BuildResult:
        self.state.tick(stage="Writing Summary and Read Me")
        for key, ups in self.active.items():
            fps = await self.q.upload_fingerprints(self.conn, self.t, self.u, key, [x.upload_id for x in ups])
            for up in ups:
                st = self._stats(key, up)
                if fps.get(up.upload_id) != st.fingerprint:
                    st.notes.append(NOTE_CHANGED)

        files_included: list[dict] = []
        files_excluded: list[dict] = list(self.excluded)
        for src in SOURCES:
            for up in self.active.get(src.key, ()):
                st = self._stats(src.key, up)
                meta = self.metas[(src.key, up.upload_id)]
                if st.rows_included == 0:
                    files_excluded.append(self._excluded_item(src.key, up, REASON_NO_ROWS))
                    continue
                files_included.append({
                    "category": src.category, "source_type": src.key, "file_name": meta.file_name,
                    "upload_id": up.upload_id, "uploaded_at": meta.uploaded_at, "reference": meta.reference,
                    "rows_in_file": st.rows_in_file, "rows_included": st.rows_included,
                    "rows_undated": st.rows_undated, "rows_superseded": st.rows_superseded,
                    "notes": list(st.notes),
                })
        files_excluded += [self._excluded_item(up.source_key, up, REASON_UNTICKED) for up in self.sel.unticked]

        counts = self.wb.row_counts()
        titles = self.wb.sheet_titles()
        data_sheets = [(COMBINED_SHEET.key, COMBINED_SHEET.title)] + [(s.key, s.sheet_title) for s in SOURCES]
        sheet_row_counts: dict[str, int] = {}
        sheets: list[tuple[str, int, str]] = [
            (SUMMARY_SHEET.title, None, "Totals per category and currency, BSP tie-out, linking and data checks"),
        ]
        for key, title in data_sheets:
            if key not in counts:
                continue
            parts = titles.get(key) or [title]
            desc = _SHEET_DESCRIPTIONS.get(key) or f"{get_source(key).label} rows as stored in the upload"
            if len(parts) > 1:
                desc += f" (split across {', '.join(parts)})"
            sheets.append((parts[0], counts[key], desc))
            sheet_row_counts[parts[0]] = counts[key]

        self.wb.write_blocks(SUMMARY_SHEET.key, SUMMARY_SHEET.title, SUMMARY_SHEET.rank, self.summary.blocks())
        self.wb.write_blocks(README_SHEET.key, README_SHEET.title, README_SHEET.rank, readme.readme_blocks(
            self.meta, files_included=files_included, files_excluded=files_excluded, sheets=sheets,
            tgq_stats=self.tgq_stats))
        return BuildResult(
            workbook=self.wb, sheet_row_counts=sheet_row_counts, summary=self.summary.to_json(),
            combined_rows=counts.get(COMBINED_SHEET.key, 0), files_included=files_included,
            files_excluded=files_excluded,
        )



async def build_report(
    conn: Any, sel: OwnedSelection, params: dict, meta: ReportMeta, workbook_path: str,
    state: BuildState, *, q: Any = None,
) -> BuildResult:
    """Build the workbook for ``sel`` (not saved — the caller saves it in a thread)."""
    b = _Build(conn, sel, params, meta, workbook_path, state, q or default_queries)
    try:
        await b.check_uploads()
        await b.load_reference()
        await b.prepass()
        await b.load_tgq()
        b.wb.ensure_sheet(COMBINED_SHEET.key, COMBINED_SHEET.title, _COMBINED_SPECS, COMBINED_SHEET.rank)
        await b.write_bsp()
        await b.write_memos()
        await b.write_tgq()
        await b.write_ndc()
        await b.write_lcc_detailed()
        await b.write_ledgers()
        await b.write_third_party()
        return await b.close_out()
    except BaseException:
        b.wb.discard()
        raise
