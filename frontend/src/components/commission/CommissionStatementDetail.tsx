"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft, Calculator, Download, RefreshCw, Search, Info, X, Play, AlertTriangle,
} from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { INCENTIVE_TYPE_COLS } from "@/lib/incentives";
import Pagination from "@/components/ui/Pagination";
import CommissionDiagnosisModal from "./CommissionDiagnosisModal";
import {
  CommissionGap, CommissionRow, CommissionRowsPage, CommissionStatement,
  CommissionSummary, Facets, RunResponse, inr, SKIPPED_LABEL, STAT_LABEL, STATUS_STYLE,
} from "./types";

const PAGE = 50;
const RUNNING = ["queued", "processing"];
const MAX_SELECTION = 500;   // matches MAX_INLINE_ROWS on the API
// Non-incentive <th> in the results grid: checkbox, Document #, Ticket #, TRNC, Airline,
// Issue date, STAT, Sector, Class, Travel date, Fare, YQ, YR, Matched deal, IATA comm,
// Estimated, Status, Actions. Keep in step with the header row below — the placeholder
// colSpans read it, and they had already drifted once.
const STATIC_COLS = 18;

type Tab = "results" | "summary" | "gaps";

/** Tooltip explaining where a row's sector/class/travel date came from. */
function enrichTitle(r: CommissionRow): string {
  if (!r.enrichment_source) return "No TGQ HMPR counterpart — this criterion was not evaluated";
  const legs = r.enriched_leg_count ?? 1;
  return `From TGQ HMPR · ${legs} ${legs === 1 ? "sector" : "sectors"}`;
}

export default function CommissionStatementDetail({
  statement, onBack,
}: { statement: CommissionStatement; onBack: () => void }) {
  const [stmt, setStmt] = useState(statement);
  const [tab, setTab] = useState<Tab>("results");
  const [starting, setStarting] = useState(false);

  // results
  const [rows, setRows] = useState<CommissionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loadingRows, setLoadingRows] = useState(false);
  const [search, setSearch] = useState("");
  const [txn, setTxn] = useState("");
  const [air, setAir] = useState("");
  const [status, setStatus] = useState("");
  const [enrichment, setEnrichment] = useState("");   // "" | enriched | not_enriched
  const [facets, setFacets] = useState<Facets>({ txn_types: [], airlines: [], statuses: [], enrichment: [] });
  const [diagnoseRow, setDiagnoseRow] = useState<CommissionRow | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busyRows, setBusyRows] = useState<Set<number>>(new Set());

  // other tabs
  const [summary, setSummary] = useState<CommissionSummary | null>(null);
  const [gaps, setGaps] = useState<CommissionGap[] | null>(null);

  // A run whose worker went quiet is not "running" as far as the UI is concerned —
  // otherwise the button would sit on "Calculating…" forever with nothing behind it.
  const stale = stmt.is_stale;
  const running = RUNNING.includes(stmt.status) && !stale;
  const hasResults =
    stmt.matched_rows + stmt.unmatched_rows + stmt.excluded_rows + stmt.skipped_rows > 0;

  const refreshStatement = useCallback(async () => {
    try {
      const { data } = await api.get<CommissionStatement>(`/bsp-commission/statements/${stmt.batch_id}`);
      setStmt(data);
      return data;
    } catch { return null; }
  }, [stmt.batch_id]);

  // Poll while the worker is calculating; reload the open tab when it lands.
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      const next = await refreshStatement();
      if (next && !RUNNING.includes(next.status)) {
        if (next.status === "failed") toast.error(next.error || "Calculation failed.");
        else toast.success("Commission calculated.");
        setRows([]); setSummary(null); setGaps(null); setOffset(0);
      }
    }, 3000);
    return () => clearInterval(t);
  }, [running, refreshStatement]);

  const loadRows = useCallback(async (off: number) => {
    setLoadingRows(true);
    try {
      const { data } = await api.get<CommissionRowsPage>(
        `/bsp-commission/statements/${stmt.batch_id}/rows`,
        { params: {
          offset: off, limit: PAGE,
          search: search || undefined, txn_type: txn || undefined,
          air: air || undefined, comm_status: status || undefined,
          enrichment: enrichment || undefined,
        } },
      );
      setRows(data.rows); setTotal(data.total); setOffset(off);
    } catch { setRows([]); }
    finally { setLoadingRows(false); }
  }, [stmt.batch_id, search, txn, air, status, enrichment]);

  // Selection is scoped to what is on screen: changing page or filters drops it so
  // a later "Run selected" can never act on rows the user can no longer see.
  // Re-loading after a run deliberately keeps it, so the ticks survive.
  const goToPage = (off: number) => { setSelected(new Set()); loadRows(off); };
  const applyFilters = () => { setSelected(new Set()); loadRows(0); };

  useEffect(() => { if (tab === "results") loadRows(0); }, [tab, loadRows]);

  useEffect(() => {
    api.get<Facets>(`/bsp-commission/statements/${stmt.batch_id}/rows/facets`)
      .then(({ data }) => setFacets(data)).catch(() => {});
  }, [stmt.batch_id]);

  useEffect(() => {
    if (tab !== "summary" || summary) return;
    api.get<CommissionSummary>(`/bsp-commission/statements/${stmt.batch_id}/summary`)
      .then(({ data }) => setSummary(data)).catch(() => setSummary(null));
  }, [tab, summary, stmt.batch_id]);

  useEffect(() => {
    if (tab !== "gaps" || gaps) return;
    api.get<CommissionGap[]>(`/bsp-commission/statements/${stmt.batch_id}/gaps`)
      .then(({ data }) => setGaps(data)).catch(() => setGaps([]));
  }, [tab, gaps, stmt.batch_id]);

  const errText = (e: unknown, fallback: string) =>
    (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

  /** Whole statement → the worker. Progress arrives via polling. */
  const runAll = async () => {
    setStarting(true);
    try {
      await api.post(`/bsp-commission/statements/${stmt.batch_id}/run`, {});
      toast.success("Calculating — large statements take a few minutes.");
      await refreshStatement();
    } catch (e: unknown) {
      toast.error(errText(e, "Could not start the calculation."));
      await refreshStatement();   // the API releases the run on a failed queue
    } finally { setStarting(false); }
  };

  /** A hand-picked set of rows → calculated inline, results are immediate. */
  const runRows = async (ids: number[]) => {
    if (!ids.length) return;
    setBusyRows((prev) => new Set([...prev, ...ids]));
    try {
      const { data } = await api.post<RunResponse>(
        `/bsp-commission/statements/${stmt.batch_id}/run`, { row_ids: ids },
      );
      const bits = [
        data.calculated && `${data.calculated} calculated`,
        data.reversed && `${data.reversed} reversed`,
        data.excluded && `${data.excluded} excluded`,
        data.skipped && `${data.skipped} skipped`,
        data.unmatched && `${data.unmatched} unmatched`,
      ].filter(Boolean).join(", ");
      toast.success(
        `${ids.length} row${ids.length === 1 ? "" : "s"} — ${bits || "no change"}` +
        (data.total_incentive ? ` · ₹${inr(data.total_incentive)}` : ""),
      );
      await Promise.all([loadRows(offset), refreshStatement()]);
      setSummary(null); setGaps(null);
    } catch (e: unknown) {
      toast.error(errText(e, "Calculation failed."));
    } finally {
      setBusyRows((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.delete(id));
        return next;
      });
    }
  };

  /** Release a run that lost its worker, so it can be started again. */
  const resetRun = async () => {
    try {
      const { data } = await api.post<CommissionStatement>(`/bsp-commission/statements/${stmt.batch_id}/reset`);
      setStmt(data);
      toast.success("Run released — you can start it again.");
    } catch (e: unknown) { toast.error(errText(e, "Could not reset the run.")); }
  };

  const toggleRow = (id: number) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const allOnPageSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const toggleAllOnPage = () => setSelected((prev) => {
    if (allOnPageSelected) {
      const next = new Set(prev);
      rows.forEach((r) => next.delete(r.id));
      return next;
    }
    return new Set([...prev, ...rows.map((r) => r.id)]);
  });

  const downloadXlsx = async () => {
    try {
      const res = await api.get(`/bsp-commission/statements/${stmt.batch_id}/xlsx`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data as Blob);
      const a = window.document.createElement("a");
      a.href = url;
      a.download = `commission-income-${stmt.batch_id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Export failed."); }
  };

  const hasFilters = !!(search || txn || air || status || enrichment);
  const clearFilters = () => { setSearch(""); setTxn(""); setAir(""); setStatus(""); setEnrichment(""); };

  const title = stmt.statement_name || stmt.batch_id;

  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap mb-4">
        <div className="flex items-start gap-3">
          <button onClick={onBack} className="mt-0.5 p-1.5 text-slate-400 hover:text-slate-700 border border-slate-200 rounded-lg">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h2 className="text-base font-bold text-slate-900">{title}</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {stmt.airline_name || stmt.airline_code || "All airlines"} ·{" "}
              {stmt.period_from || "—"}{stmt.period_to ? ` → ${stmt.period_to}` : ""} ·{" "}
              {stmt.row_count.toLocaleString("en-IN")} settlement rows
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => { refreshStatement(); if (tab === "results") loadRows(offset); }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
          {hasResults && (
            <button onClick={downloadXlsx}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
              <Download className="w-3.5 h-3.5" /> Export
            </button>
          )}
          {selected.size > 0 ? (
            <button onClick={() => runRows([...selected])}
              disabled={busyRows.size > 0 || selected.size > MAX_SELECTION}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50">
              <Play className="w-3.5 h-3.5" />
              {busyRows.size > 0 ? "Calculating…" : `Run selected (${selected.size})`}
            </button>
          ) : (
            <button onClick={runAll} disabled={running || starting || stmt.parse_status !== "completed"}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">
              <Calculator className="w-3.5 h-3.5" />
              {running ? `Calculating ${stmt.progress_pct}%` : starting ? "Starting…" : hasResults ? "Re-run all" : "Run all"}
            </button>
          )}
        </div>
      </div>

      {selected.size > MAX_SELECTION && (
        <p className="mb-4 text-xs text-orange-600 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2">
          {selected.size} rows selected — run at most {MAX_SELECTION} at a time, or use Run all.
        </p>
      )}

      {stale && (
        <div className="mb-4 flex items-start gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">This run stopped reporting progress.</p>
            <p className="mt-0.5">
              Its background worker is no longer alive — check that Redis and a Celery worker on the{" "}
              <code className="font-mono">bsp</code> queue are running. You can start it again, or
              tick a few rows and use <span className="font-semibold">Run selected</span>, which
              calculates immediately without a worker.
            </p>
            <button onClick={resetRun} className="mt-1.5 text-xs font-semibold text-amber-900 underline">
              Release this run
            </button>
          </div>
        </div>
      )}

      {stmt.parse_status !== "completed" && (
        <p className="mb-4 text-xs text-orange-600 bg-orange-50 border border-orange-200 rounded-lg px-3 py-2">
          This statement is still parsing ({stmt.parse_status}) — there are no settlement rows to calculate yet.
        </p>
      )}
      {stmt.status === "failed" && stmt.error && (
        <p className="mb-4 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{stmt.error}</p>
      )}

      {/* Progress */}
      {running && (
        <div className="mb-4">
          <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 transition-all" style={{ width: `${stmt.progress_pct}%` }} />
          </div>
          <p className="text-[11px] text-slate-400 mt-1">
            {stmt.processed_rows.toLocaleString("en-IN")} of {stmt.total_rows.toLocaleString("en-IN")} rows
          </p>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
        <Stat label="Estimated commission" value={`₹${inr(stmt.total_incentive)}`} accent="text-emerald-700" />
        <Stat label="IATA commission" value={`₹${inr(stmt.iata_total)}`} accent="text-teal-700" />
        <Stat label="Matched" value={stmt.matched_rows.toLocaleString("en-IN")} />
        <Stat label="Unmatched" value={stmt.unmatched_rows.toLocaleString("en-IN")} accent="text-orange-600" />
        <Stat label="Excluded / skipped" value={`${stmt.excluded_rows + stmt.skipped_rows}`} accent="text-slate-500" />
        <Stat
          label="Enriched from TGQ"
          value={`${stmt.enriched_rows.toLocaleString("en-IN")} of ${stmt.total_rows.toLocaleString("en-IN")}`}
          accent={stmt.enriched_rows === 0 ? "text-amber-600" : "text-sky-700"}
        />
      </div>

      {/* The difference between "no deal applies" and "the other half of the data is missing". */}
      {hasResults && stmt.enriched_rows === 0 && (
        <div className="flex items-start gap-2 px-3 py-2.5 mb-4 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />
          <span>
            No settlement row matched a TGQ HMPR statement, so cabin class, sector and travel date
            could not be evaluated for any row — deals that depend on them cannot match. Upload the
            TGQ HMPR covering {stmt.period_from ?? "this period"} – {stmt.period_to ?? ""} under
            Vendors data → Statements, then re-run.
          </span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1.5 mb-4">
        {([["results", "Results"], ["summary", "Summary"], ["gaps", "Unmatched & skipped"]] as [Tab, string][])
          .map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors",
                tab === k
                  ? "bg-blue-50 border-blue-300 text-blue-700"
                  : "bg-white border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-800",
              )}>
              {label}
            </button>
          ))}
      </div>

      {tab === "results" && (
        <>
          {/* Filters */}
          <div className="flex items-center gap-2 flex-wrap mb-3">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") applyFilters(); }}
                placeholder="Document / ticket / deal"
                className="pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-lg w-56 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>
            <Select value={txn} onChange={setTxn} options={facets.txn_types} placeholder="All TRNC" />
            <Select value={air} onChange={setAir} options={facets.airlines} placeholder="All airlines" />
            <Select value={status} onChange={setStatus} options={facets.statuses} placeholder="All statuses" />
            <Select value={enrichment} onChange={setEnrichment}
                    options={["enriched", "not_enriched"]} placeholder="All rows" />
            <button onClick={applyFilters} className="px-3 py-1.5 text-xs font-medium text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50">
              Apply
            </button>
            {hasFilters && (
              <button onClick={() => { clearFilters(); }} className="flex items-center gap-1 px-2 py-1.5 text-xs text-slate-400 hover:text-slate-700">
                <X className="w-3 h-3" /> Clear
              </button>
            )}
          </div>

          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400 whitespace-nowrap">
                    <th className="px-3 py-2.5 w-8">
                      <input
                        type="checkbox"
                        checked={allOnPageSelected}
                        onChange={toggleAllOnPage}
                        disabled={rows.length === 0}
                        aria-label="Select all rows on this page"
                        className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:cursor-not-allowed"
                      />
                    </th>
                    <th className="text-left px-3 py-2.5 font-semibold">Document #</th>
                    <th className="text-left px-3 py-2.5 font-semibold">Ticket #</th>
                    <th className="text-left px-3 py-2.5 font-semibold">TRNC</th>
                    <th className="text-left px-3 py-2.5 font-semibold">Airline</th>
                    <th className="text-left px-3 py-2.5 font-semibold">Issue date</th>
                    <th className="text-left px-3 py-2.5 font-semibold">STAT</th>
                    <th className="text-left px-3 py-2.5 font-semibold text-sky-600">Sector</th>
                    <th className="text-left px-3 py-2.5 font-semibold text-sky-600">Class</th>
                    <th className="text-left px-3 py-2.5 font-semibold text-sky-600">Travel date</th>
                    <th className="text-right px-3 py-2.5 font-semibold">Fare</th>
                    <th className="text-right px-3 py-2.5 font-semibold">YQ</th>
                    <th className="text-right px-3 py-2.5 font-semibold">YR</th>
                    <th className="text-left px-3 py-2.5 font-semibold">Matched deal</th>
                    {INCENTIVE_TYPE_COLS.map((c) => (
                      <th key={c.key} className="text-right px-3 py-2.5 font-semibold text-amber-600">{c.label}</th>
                    ))}
                    <th className="text-right px-3 py-2.5 font-semibold text-teal-600">IATA comm</th>
                    <th className="text-right px-3 py-2.5 font-semibold text-emerald-700">Estimated</th>
                    <th className="text-center px-3 py-2.5 font-semibold">Status</th>
                    <th className="text-center px-3 py-2.5 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {loadingRows ? (
                    <tr><td colSpan={STATIC_COLS + INCENTIVE_TYPE_COLS.length} className="px-3 py-10 text-center text-sm text-slate-400">Loading…</td></tr>
                  ) : rows.length === 0 ? (
                    <tr><td colSpan={STATIC_COLS + INCENTIVE_TYPE_COLS.length} className="px-3 py-12 text-center text-sm text-slate-400">
                      {hasResults ? "No rows match these filters." : "Tick a few rows and press Run selected, or run the whole statement."}
                    </td></tr>
                  ) : rows.map((r) => {
                    const st = STATUS_STYLE[r.commission_status] ?? STATUS_STYLE.pending;
                    const bd = r.incentive_breakdown || {};
                    const busy = busyRows.has(r.id);
                    return (
                      <tr key={r.id} className={cn(
                        "border-b border-slate-100 hover:bg-slate-50/60 whitespace-nowrap",
                        selected.has(r.id) && "bg-blue-50/50",
                      )}>
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            checked={selected.has(r.id)}
                            onChange={() => toggleRow(r.id)}
                            aria-label={`Select document ${r.document_number ?? r.id}`}
                            className="w-3.5 h-3.5 accent-blue-600 cursor-pointer"
                          />
                        </td>
                        <td className="px-3 py-2 font-medium text-slate-700">{r.document_number || "—"}</td>
                        <td className="px-3 py-2 text-xs text-slate-600 font-mono">{r.ticket_number || "—"}</td>
                        <td className="px-3 py-2 text-xs text-slate-500">{r.transaction_type || "—"}</td>
                        <td className="px-3 py-2 text-xs text-slate-600" title={r.airline_name || ""}>
                          {r.airline_name || r.airline_accounting_code || r.airline_code || "—"}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-500">{r.issue_date || "—"}</td>
                        <td className="px-3 py-2 text-xs text-slate-500" title={r.stat ? STAT_LABEL[r.stat] : ""}>{r.stat || "—"}</td>
                        <td className="px-3 py-2 text-xs font-mono text-slate-600" title={enrichTitle(r)}>
                          {r.enriched_sector || <span className="text-slate-300">—</span>}
                        </td>
                        <td className="px-3 py-2 text-xs font-mono text-slate-600" title={enrichTitle(r)}>
                          {r.enriched_booking_class || <span className="text-slate-300">—</span>}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-600" title={
                          r.enriched_travel_date_source === "inferred"
                            ? "Year inferred from the issue date — TGQ HMPR prints the day and month only"
                            : enrichTitle(r)
                        }>
                          {r.enriched_travel_date
                            ? <>{r.enriched_travel_date}{r.enriched_travel_date_source === "inferred" && <span className="text-amber-500 ml-0.5">~</span>}</>
                            : <span className="text-slate-300">—</span>}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-slate-700">{inr(r.fare_amount)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-slate-500">{inr(r.yq)}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-slate-500">{inr(r.yr)}</td>
                        <td className="px-3 py-2 text-xs">
                          {r.matched_deal_name ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-sky-50 text-sky-700 border-sky-200">
                              AIR · {r.matched_deal_name}
                            </span>
                          ) : <span className="text-slate-300">—</span>}
                        </td>
                        {INCENTIVE_TYPE_COLS.map((c) => (
                          <td key={c.key} className="px-3 py-2 text-right tabular-nums text-amber-700">
                            {bd[c.key] != null ? `₹${inr(bd[c.key])}` : <span className="text-slate-300">—</span>}
                          </td>
                        ))}
                        <td className="px-3 py-2 text-right tabular-nums text-teal-700">{inr(r.iata_commission)}</td>
                        <td className={cn(
                          "px-3 py-2 text-right tabular-nums font-semibold",
                          (r.calculated_incentive ?? 0) < 0 ? "text-red-600" : "text-emerald-700",
                        )}>
                          {r.calculated_incentive != null ? `₹${inr(r.calculated_incentive)}` : <span className="text-slate-300">—</span>}
                        </td>
                        <td className="px-3 py-2 text-center">
                          <span title={r.commission_reason || ""}
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${st.cls}`}>
                            {st.label}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-center whitespace-nowrap">
                          <button
                            onClick={() => runRows([r.id])}
                            disabled={busy}
                            className="p-1 text-slate-400 hover:text-emerald-600 disabled:opacity-40"
                            title="Run calculation for this row"
                          >
                            <Play className={cn("w-3.5 h-3.5", busy && "animate-pulse")} />
                          </button>
                          <button onClick={() => setDiagnoseRow(r)} className="p-1 text-slate-400 hover:text-blue-600" title="Why this result?">
                            <Info className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {total > PAGE && (
              <Pagination
                page={Math.floor(offset / PAGE) + 1}
                pageSize={PAGE}
                total={total}
                onPageChange={(p) => goToPage((p - 1) * PAGE)}
              />
            )}
          </div>

          {rows.length > 0 && (() => {
            // Per row, not "the first row speaks for all": a statement holds a mix.
            const enriched = rows.filter((r) => r.enrichment_source).length;
            const missing = [...new Set(rows.flatMap((r) => r.skipped_criteria ?? []))];
            if (!missing.length) {
              return (
                <p className="text-[11px] text-slate-400 mt-2">
                  All {rows.length} rows on this page were enriched from a TGQ HMPR statement —
                  cabin class, sector and travel date were all evaluated.
                </p>
              );
            }
            return (
              <p className="text-[11px] text-slate-400 mt-2">
                {enriched} of {rows.length} rows on this page were enriched from a TGQ HMPR
                statement. For the other {rows.length - enriched}, the BSP statement prints no{" "}
                {missing.map((c) => SKIPPED_LABEL[c] ?? c).join(", ")}, so deal criteria that
                depend on them were skipped rather than guessed.
              </p>
            );
          })()}
        </>
      )}

      {tab === "summary" && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400 whitespace-nowrap">
                  <th className="text-left px-3 py-2.5 font-semibold">Airline</th>
                  <th className="text-right px-3 py-2.5 font-semibold">Rows</th>
                  {INCENTIVE_TYPE_COLS.map((c) => (
                    <th key={c.key} className="text-right px-3 py-2.5 font-semibold text-amber-600">{c.label}</th>
                  ))}
                  <th className="text-right px-3 py-2.5 font-semibold text-teal-600">IATA comm</th>
                  <th className="text-right px-3 py-2.5 font-semibold text-emerald-700">Total</th>
                </tr>
              </thead>
              <tbody>
                {!summary ? (
                  <tr><td colSpan={4 + INCENTIVE_TYPE_COLS.length} className="px-3 py-10 text-center text-sm text-slate-400">Loading…</td></tr>
                ) : summary.airlines.length === 0 ? (
                  <tr><td colSpan={4 + INCENTIVE_TYPE_COLS.length} className="px-3 py-12 text-center text-sm text-slate-400">Nothing calculated yet.</td></tr>
                ) : (
                  <>
                    {summary.airlines.map((a) => (
                      <tr key={a.airline} className="border-b border-slate-100 whitespace-nowrap">
                        <td className="px-3 py-2 font-medium text-slate-700">{a.airline}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-slate-500">{a.rows.toLocaleString("en-IN")}</td>
                        {INCENTIVE_TYPE_COLS.map((c) => (
                          <td key={c.key} className="px-3 py-2 text-right tabular-nums text-amber-700">
                            {a.incentives[c.key] ? `₹${inr(a.incentives[c.key])}` : <span className="text-slate-300">—</span>}
                          </td>
                        ))}
                        <td className="px-3 py-2 text-right tabular-nums text-teal-700">₹{inr(a.iata_commission)}</td>
                        <td className="px-3 py-2 text-right tabular-nums font-semibold text-emerald-700">₹{inr(a.total_incentive)}</td>
                      </tr>
                    ))}
                    <tr className="bg-slate-50 font-semibold whitespace-nowrap">
                      <td className="px-3 py-2 text-slate-700">Total</td>
                      <td />
                      {INCENTIVE_TYPE_COLS.map((c) => (
                        <td key={c.key} className="px-3 py-2 text-right tabular-nums text-amber-700">
                          {summary.totals.incentives[c.key] ? `₹${inr(summary.totals.incentives[c.key])}` : <span className="text-slate-300">—</span>}
                        </td>
                      ))}
                      <td className="px-3 py-2 text-right tabular-nums text-teal-700">₹{inr(summary.totals.iata_commission)}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-emerald-700">₹{inr(summary.totals.total_incentive)}</td>
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "gaps" && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
                <th className="text-left px-3 py-2.5 font-semibold">Status</th>
                <th className="text-left px-3 py-2.5 font-semibold">Reason</th>
                <th className="text-right px-3 py-2.5 font-semibold">Rows</th>
                <th className="text-left px-3 py-2.5 font-semibold">Example documents</th>
              </tr>
            </thead>
            <tbody>
              {!gaps ? (
                <tr><td colSpan={4} className="px-3 py-10 text-center text-sm text-slate-400">Loading…</td></tr>
              ) : gaps.length === 0 ? (
                <tr><td colSpan={4} className="px-3 py-12 text-center text-sm text-slate-400">
                  Nothing unmatched — every settlement row either earned commission or was a reversal.
                </td></tr>
              ) : gaps.map((g, i) => {
                const st = STATUS_STYLE[g.status] ?? STATUS_STYLE.pending;
                return (
                  <tr key={i} className="border-b border-slate-100">
                    <td className="px-3 py-2">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border ${st.cls}`}>{st.label}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600">{g.reason}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-700 font-medium">{g.count.toLocaleString("en-IN")}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-400 font-mono">{g.sample_documents.join(", ") || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {diagnoseRow && (
        <CommissionDiagnosisModal
          rowId={diagnoseRow.id}
          document={diagnoseRow.document_number}
          onClose={() => setDiagnoseRow(null)}
        />
      )}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className={cn("text-sm font-bold mt-0.5 tabular-nums", accent ?? "text-slate-800")}>{value}</p>
    </div>
  );
}

function Select({
  value, onChange, options, placeholder,
}: { value: string; onChange: (v: string) => void; options: string[]; placeholder: string }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-400"
    >
      <option value="">{placeholder}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}
