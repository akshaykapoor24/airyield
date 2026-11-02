"use client";

// One source tab of Commission income. Most tabs are a list of statements, each opened on
// its own. A source with `allTicketsView` (Third Party GDS) adds one toolbar row above it:
//
//   All tickets | Statement wise             every statement's ticket lines in one table, or
//                                            the statements one row each (Open = the detail)
//   Agency → Statement → Booking period      the same filters, in the same order, as
//                                            Vendor Reconciliation's Third Party GDS tab
//   Run all                                  every statement in those filters, to the worker
//
// The filters narrow both sub-tabs and Run all alike, so what Run all calculates is what is
// on screen. A run is still per statement — a refund reverses its issue within its own
// statement — so Run all starts one worker run per statement and the progress shown is
// theirs added up.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  RefreshCw, Calculator, Clock, CheckCircle2, XCircle, MinusCircle, AlertTriangle, X,
} from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatPeriod } from "@/lib/statementPeriod";
import type { CommissionSource } from "@/lib/commissionSources";
import CommissionStatementDetail from "./CommissionStatementDetail";
import ThirdPartyAllTickets from "./ThirdPartyAllTickets";
import { TOOLBAR_ROW } from "./ThirdPartyStatementLines";
import { CommissionStatement, RunAllResponse, inr } from "./types";

const RUNNING = ["queued", "processing"];

const DATE_INPUT =
  "py-1 px-1 text-xs bg-transparent border-0 focus:outline-none text-slate-700 " +
  "[&::-webkit-calendar-picker-indicator]:hidden";

type SubView = "tickets" | "statements";

const errText = (e: unknown, fallback: string) =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;

/** Actually running: queued or processing, with a worker still reporting. */
const isActive = (s: CommissionStatement) => RUNNING.includes(s.status) && !s.is_stale;

/** One consolidator, whichever way the upload recorded it: by its Supplier master row, or
 *  — for an agency typed in by hand — by name and branch. */
function agencyKey(s: CommissionStatement): string {
  if (s.supplier_id != null) return `id:${s.supplier_id}`;
  if (s.supplier_name) return `name:${s.supplier_name}|${s.supplier_branch ?? ""}`;
  return "none";
}

/** Does the statement's period reach into [from, to]? A statement with no period cannot be
 *  shown to, so it drops out once a period is set. */
function overlaps(s: CommissionStatement, from: string, to: string): boolean {
  if (!from && !to) return true;
  if (!s.period_from || !s.period_to) return false;
  return (!to || s.period_from <= to) && (!from || s.period_to >= from);
}

function StatusBadge({ s }: { s: CommissionStatement }) {
  const map: Record<string, { cls: string; icon: React.ReactNode; label: string }> = {
    completed:  { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", icon: <CheckCircle2 className="w-3 h-3" />, label: "Calculated" },
    processing: { cls: "bg-blue-50 text-blue-700 border-blue-200",          icon: <Clock className="w-3 h-3" />,       label: `Running ${s.progress_pct}%` },
    queued:     { cls: "bg-blue-50 text-blue-700 border-blue-200",          icon: <Clock className="w-3 h-3" />,       label: "Queued" },
    failed:     { cls: "bg-red-50 text-red-700 border-red-200",             icon: <XCircle className="w-3 h-3" />,     label: "Failed" },
    idle:       { cls: "bg-slate-100 text-slate-500 border-slate-200",      icon: <MinusCircle className="w-3 h-3" />, label: "Not run" },
  };
  const m = map[s.status] ?? map.idle;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${m.cls}`}>
      {m.icon} {m.label}
    </span>
  );
}

export default function CommissionIncomeView({ source }: { source: CommissionSource }) {
  const [statements, setStatements] = useState<CommissionStatement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<CommissionStatement | null>(null);

  // The state each statement last finished in. When one moves on — a run landed — the tickets
  // reload, once. A statement merely queued or still running has changed nothing on them yet,
  // and the first answer is what they loaded alongside, so neither costs a second request.
  const landed = useRef<Map<string, string> | null>(null);
  const [landedTick, setLandedTick] = useState(0);

  const fetchStatements = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<CommissionStatement[]>(`${source.apiBase}/statements`);
      setStatements(data);
      const seen = landed.current;
      const next = new Map(seen ?? []);
      let moved = false;
      for (const s of data) {
        if (RUNNING.includes(s.status)) continue;
        const v = `${s.status}:${s.calculated_at ?? ""}`;
        if (next.get(s.batch_id) !== v) { next.set(s.batch_id, v); moved = true; }
      }
      landed.current = next;
      if (seen && moved) setLandedTick((k) => k + 1);
    } catch { setError(`Failed to load ${source.statementNoun}s.`); }
    finally { setLoading(false); }
  }, [source]);
  useEffect(() => { fetchStatements(); }, [fetchStatements]);

  // Keep the list live while any statement is calculating — every 2 s on a tab with its own
  // Run all while a worker is really going, so a run of a few seconds reads as that.
  useEffect(() => {
    if (!statements.some((s) => RUNNING.includes(s.status))) return;
    const t = setInterval(fetchStatements, source.allTicketsView && statements.some(isActive) ? 2000 : 4000);
    return () => clearInterval(t);
  }, [statements, fetchStatements, source]);

  // ── All tickets | Statement wise, and the filters over both ────────────────────────────
  const tabbed = !!source.allTicketsView;
  const [view, setView] = useState<SubView>(() => {
    if (typeof window === "undefined") return "tickets";
    return new URLSearchParams(window.location.search).get("view") === "statements" ? "statements" : "tickets";
  });
  const pickView = (v: SubView) => {
    setView(v);
    const url = new URL(window.location.href);
    url.searchParams.set("view", v);
    window.history.replaceState({}, "", url);
  };
  const [agency, setAgency] = useState("");
  const [statement, setStatement] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [refreshTick, setRefreshTick] = useState(0);
  const [startingAll, setStartingAll] = useState(false);
  // The statements the last Run all started, each with the calculated_at it had before —
  // watched until every one has a new one (or failed). Comparing against the old value is
  // what stops a poll sent before the run, and answered after it, reading as "finished".
  const runAllBatches = useRef<Map<string, string | null> | null>(null);

  // An inverted period is said, and ignored until it is fixed.
  const badPeriod = !!(from && to && from > to);
  const pFrom = badPeriod ? "" : from;
  const pTo = badPeriod ? "" : to;

  const agencies = useMemo(() => {
    const m = new Map<string, { label: string; count: number }>();
    for (const s of statements) {
      const k = agencyKey(s);
      const label = s.supplier_name
        ? `${s.supplier_name}${s.supplier_branch ? ` — ${s.supplier_branch}` : ""}`
        : "No agency";
      m.set(k, { label, count: (m.get(k)?.count ?? 0) + 1 });
    }
    return [...m.entries()].sort((a, b) => a[1].label.localeCompare(b[1].label));
  }, [statements]);
  const statementOpts = statements.filter((s) => !agency || agencyKey(s) === agency);

  const pickAgency = (k: string) => {
    setAgency(k);
    const st = statements.find((s) => s.batch_id === statement);
    if (st && k && agencyKey(st) !== k) setStatement("");
  };
  // Choosing a statement with every agency showing chooses its agency too.
  const pickStatement = (b: string) => {
    setStatement(b);
    const st = statements.find((s) => s.batch_id === b);
    if (st && !agency) setAgency(agencyKey(st));
  };
  const filtered = !!(agency || statement || from || to);
  const clearFilters = () => { setAgency(""); setStatement(""); setFrom(""); setTo(""); };

  // What both sub-tabs and Run all act on.
  const scoped = useMemo(() => statements.filter((s) =>
    (!agency || agencyKey(s) === agency) && (!statement || s.batch_id === statement)
    && overlaps(s, pFrom, pTo)), [statements, agency, statement, pFrom, pTo]);
  const narrowed = !!(agency || statement);
  const ticketParams = useMemo(() => ({
    // Only when the Agency / Statement filters narrow it; empty means every statement.
    batches: narrowed ? scoped.map((s) => s.batch_id).join(",") : undefined,
    date_from: pFrom || undefined,
    date_to: pTo || undefined,
  }), [narrowed, scoped, pFrom, pTo]);

  const active = useMemo(() => scoped.filter(isActive), [scoped]);
  const progress = useMemo(() => {
    if (!active.length) return null;
    const done = active.reduce((a, s) => a + s.processed_rows, 0);
    const total = active.reduce((a, s) => a + (s.total_rows || s.row_count), 0);
    return { done, total, pct: total ? Math.min(100, Math.round((100 * done) / total)) : 0 };
  }, [active]);

  // Say when the statements a Run all started have all finished, and whether any failed.
  useEffect(() => {
    const before = runAllBatches.current;
    if (!before?.size) return;
    const mine = statements.filter((s) => before.has(s.batch_id));
    const landed = (s: CommissionStatement) => !isActive(s)
      && (s.status === "failed" || s.is_stale || s.calculated_at !== before.get(s.batch_id));
    if (!mine.every(landed)) return;
    runAllBatches.current = null;
    const failed = mine.filter((s) => s.status === "failed" || s.is_stale);
    if (failed.length) {
      toast.error(`${failed.length} of ${mine.length} statement${mine.length === 1 ? "" : "s"} did not finish — open ${failed.length === 1 ? "it" : "them"} under Statement wise to see why.`);
    } else {
      toast.success(`Commission calculated for ${mine.length} statement${mine.length === 1 ? "" : "s"}.`);
    }
  }, [statements]);

  const runAll = async () => {
    if (!scoped.length) return;
    setStartingAll(true);
    try {
      const everything = scoped.length === statements.length;
      const { data } = await api.post<RunAllResponse>(
        `${source.apiBase}/run-all`, everything ? {} : { batch_ids: scoped.map((s) => s.batch_id) });
      if (data.started.length) {
        runAllBatches.current = new Map(data.started.map((r) => [
          r.batch_id, statements.find((s) => s.batch_id === r.batch_id)?.calculated_at ?? null,
        ]));
        toast.success(`Calculating ${data.started.length} statement${data.started.length === 1 ? "" : "s"} in the background.`);
      }
      if (data.skipped.length) {
        const names = data.skipped.slice(0, 3).map((s) => `${s.statement_name ?? s.batch_id}: ${s.reason}`);
        if (data.skipped.length > 3) names.push(`…and ${data.skipped.length - 3} more`);
        toast.error(`Not started —\n${names.join("\n")}`, { duration: 8000 });
      }
    } catch (e: unknown) {
      toast.error(errText(e, "Could not start the calculation."));
    } finally {
      setStartingAll(false);
      await fetchStatements();
    }
  };

  const refresh = () => { fetchStatements(); setRefreshTick((k) => k + 1); };
  const openStatement = (batchId: string) => {
    const s = statements.find((x) => x.batch_id === batchId);
    if (s) setSelected(s);
  };

  if (selected) {
    return (
      <CommissionStatementDetail
        source={source}
        statement={selected}
        onBack={() => { setSelected(null); fetchStatements(); }}
      />
    );
  }

  const refreshButton = (
    <button onClick={refresh}
      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
      <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
    </button>
  );

  if (!tabbed) {
    return (
      <div>
        <div className="flex items-center justify-end mb-3">{refreshButton}</div>
        <StatementTable source={source} statements={statements} loading={loading} error={error}
          filtered={false} onOpen={setSelected} />
      </div>
    );
  }

  // ── The toolbar: ONE row. All tickets | Statement wise · Agency · Statement · Booked ·
  // [the table's search · airline · invoice type, on All tickets] · Refresh · Run all.
  // Labels live in placeholders and tooltips rather than above each control, and the
  // dropdowns give way (to a readable minimum) before the row is allowed to wrap.
  const start = (
    <>
      <div className="inline-flex shrink-0 p-0.5 rounded-lg bg-slate-100 border border-slate-200">
        {([["tickets", "All tickets"], ["statements", `Statement wise (${scoped.length})`]] as [SubView, string][])
          .map(([k, label]) => (
            <button key={k} onClick={() => pickView(k)}
              className={cn(
                "px-2.5 py-1 rounded-md text-xs font-semibold transition-colors whitespace-nowrap",
                view === k
                  ? "bg-white text-blue-700 shadow-sm"
                  : "text-slate-500 hover:text-slate-800",
              )}>
              {label}
            </button>
          ))}
      </div>
      <span className="w-px h-5 bg-slate-200 mx-0.5 shrink-0" aria-hidden />
      <select value={agency} onChange={(e) => pickAgency(e.target.value)} title="Agency" aria-label="Agency"
        className={cn("py-1.5 px-2 text-xs border rounded-lg bg-white w-40 min-w-[6rem]",
          agency ? "border-blue-300 text-slate-800" : "border-slate-200 text-slate-600")}>
        <option value="">Agency</option>
        {agencies.map(([k, a]) => (
          <option key={k} value={k}>
            {a.label} ({a.count} statement{a.count !== 1 ? "s" : ""})
          </option>
        ))}
      </select>
      <select value={statement} onChange={(e) => pickStatement(e.target.value)} title="Statement" aria-label="Statement"
        className={cn("py-1.5 px-2 text-xs border rounded-lg bg-white w-48 min-w-[6.5rem]",
          statement ? "border-blue-300 text-slate-800" : "border-slate-200 text-slate-600")}>
        <option value="">Statement</option>
        {statementOpts.map((s) => (
          <option key={s.batch_id} value={s.batch_id}>
            {agency ? "" : `${s.supplier_name ?? "No agency"} · `}
            {s.period_from && s.period_to ? formatPeriod(s.period_from, s.period_to) : "No period"}
            {" · "}{s.statement_name || s.batch_id}
          </option>
        ))}
      </select>
      <div title={badPeriod ? "The booking period ends before it starts — it is ignored until fixed." : "Booking period (booked date)"}
        className={cn("flex shrink-0 items-center gap-0.5 pl-2 pr-1 border rounded-lg bg-white",
          badPeriod ? "border-red-300 bg-red-50" : from || to ? "border-blue-300" : "border-slate-200")}>
        <span className="text-[10px] font-semibold uppercase text-slate-400">Booked</span>
        {/* No calendar icon — a click anywhere on the date opens the picker — so the pair
            takes ~40px less of the one-row toolbar. */}
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Booked from"
          onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch { /* not supported */ } }}
          className={DATE_INPUT} />
        <span className="text-slate-300 text-xs">–</span>
        <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} aria-label="Booked to"
          onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch { /* not supported */ } }}
          className={DATE_INPUT} />
      </div>
      {filtered && (
        <button onClick={clearFilters} title="Clear agency, statement and booking period"
          className="shrink-0 p-1 text-blue-600 hover:text-blue-800 rounded hover:bg-blue-50">
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </>
  );
  const end = (
    <>
      <button onClick={refresh} title="Refresh" aria-label="Refresh"
        className="p-1.5 text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
        <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
      </button>
      <button onClick={runAll} disabled={!scoped.length || active.length > 0 || startingAll}
        title={`Calculate every ticket of the ${scoped.length} statement${scoped.length === 1 ? "" : "s"} ${filtered ? "in these filters" : "in this tab"} — each statement runs whole, in the background.`}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap">
        <Calculator className="w-3.5 h-3.5" />
        {progress ? `Calculating ${progress.pct}%` : startingAll ? "Starting…" : `Run all (${scoped.length})`}
      </button>
    </>
  );
  // A thin bar, not a block: it sits between the toolbar and the cards while it runs.
  const below = progress && (
    <div className="flex items-center gap-2 mb-3">
      <div className="flex-1 h-1 bg-slate-100 rounded-full overflow-hidden">
        <div className="h-full bg-blue-500 transition-all" style={{ width: `${progress.pct}%` }} />
      </div>
      <p className="text-[11px] text-slate-400 whitespace-nowrap">
        {active.length} statement{active.length === 1 ? "" : "s"} ·{" "}
        {progress.done.toLocaleString("en-IN")} of {progress.total.toLocaleString("en-IN")} rows
      </p>
    </div>
  );

  // All tickets draws the row itself, with the table's own filters in it; anything else
  // (Statement wise, or nothing to list) gets the row on its own. It is up from the first
  // paint, not after the statements answer: with no filter its tickets do not depend on them,
  // so the two load side by side and the toolbar does not change shape when they land.
  const firstLoad = loading && !statements.length;
  const ticketsShown = view === "tickets" && !(error && !statements.length)
    && (firstLoad || statements.length > 0) && !(narrowed && !scoped.length);

  return (
    <div>
      {!ticketsShown && (
        <>
          <div className={TOOLBAR_ROW}>
            {start}
            <div className="ml-auto flex items-center gap-1.5 shrink-0">{end}</div>
          </div>
          {below}
        </>
      )}

      {view === "statements" ? (
        <StatementTable source={source} statements={scoped} loading={loading} error={error}
          filtered={filtered} onOpen={setSelected} />
      ) : ticketsShown ? (
        <ThirdPartyAllTickets
          source={source}
          params={ticketParams}
          toolbar={{ start, end, below }}
          refreshKey={`${landedTick}:${refreshTick}`}
          onOpenStatement={openStatement}
          onRan={fetchStatements}
        />
      ) : error && !statements.length ? (
        <p className="px-3 py-10 text-center text-sm text-red-500">{error}</p>
      ) : !statements.length ? (
        <p className="px-3 py-12 text-center text-sm text-slate-400">
          No {source.statementNoun}s yet — upload one under{" "}
          <Link href={source.uploadHref} className="text-blue-600 hover:underline">{source.uploadLabel}</Link>{" "}first.
        </p>
      ) : (
        // `batches` empty would read as every statement — so say there are none instead.
        <p className="px-3 py-12 text-center text-sm text-slate-400">
          No statements of this agency fall in this booking period.
        </p>
      )}
    </div>
  );
}

function StatementTable({
  source, statements, loading, error, filtered, onOpen,
}: {
  source: CommissionSource;
  statements: CommissionStatement[];
  loading: boolean;
  error: string | null;
  /** The list is narrowed by the tab's filters — an empty one is not "nothing uploaded". */
  filtered: boolean;
  onOpen: (s: CommissionStatement) => void;
}) {
  // Statement · [Agency|Airline] · Period · Rows · Status · Matched · [Needs TGQ] ·
  // Unmatched · IATA · Estimated · [Variance] · Actions. Computed, because the two
  // literals this replaced had to be re-counted by hand every time a column moved.
  const cols = 10 + (source.showsEnrichment ? 1 : 0) + (source.showsVariance ? 1 : 0);

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400 whitespace-nowrap">
              <th className="text-left px-3 py-2.5 font-semibold">Statement</th>
              <th className="text-left px-3 py-2.5 font-semibold">
                {source.showsAgency ? "Agency" : "Airline"}
              </th>
              <th className="text-left px-3 py-2.5 font-semibold">Period</th>
              <th className="text-right px-3 py-2.5 font-semibold">Rows</th>
              <th className="text-center px-3 py-2.5 font-semibold">Status</th>
              <th className="text-right px-3 py-2.5 font-semibold">Matched</th>
              {/* Without this the biggest population on a BSP statement is invisible
                  from the picker: 9,021 rows that matched a deal but could not be
                  verified read as neither matched nor unmatched. */}
              {source.showsEnrichment && (
                <th className="text-right px-3 py-2.5 font-semibold text-amber-700">Needs TGQ</th>
              )}
              <th className="text-right px-3 py-2.5 font-semibold">Unmatched</th>
              <th className="text-right px-3 py-2.5 font-semibold text-teal-600">IATA comm</th>
              <th className="text-right px-3 py-2.5 font-semibold text-emerald-700">Estimated commission</th>
              {source.showsVariance && (
                <th className="text-right px-3 py-2.5 font-semibold text-amber-700"
                    title="What your deals say you should have earned, minus what the consolidator actually paid. Positive means they owe you.">
                  Variance
                </th>
              )}
              <th className="text-right px-3 py-2.5 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {/* Only the first load blanks the table — a poll while a run is going must not
                flash "Loading…" over the rows it is about to update. */}
            {loading && !statements.length && !filtered ? (
              <tr><td colSpan={cols} className="px-3 py-10 text-center text-sm text-slate-400">Loading…</td></tr>
            ) : error ? (
              <tr><td colSpan={cols} className="px-3 py-10 text-center text-sm text-red-500">{error}</td></tr>
            ) : statements.length === 0 ? (
              <tr><td colSpan={cols} className="px-3 py-12 text-center text-sm text-slate-400">
                {filtered ? "No statements match these filters." : (
                  <>
                    No {source.statementNoun}s yet — upload one under{" "}
                    <Link href={source.uploadHref} className="text-blue-600 hover:underline">
                      {source.uploadLabel}
                    </Link>{" "}first.
                  </>
                )}
              </td></tr>
            ) : statements.map((s) => (
              <tr key={s.batch_id} className="border-b border-slate-100 hover:bg-slate-50/60 whitespace-nowrap">
                <td className="px-3 py-2 text-slate-700 font-medium max-w-[260px] truncate" title={s.statement_name || s.batch_id}>
                  {s.statement_name || s.batch_id}
                  {s.parse_status !== "completed" && (
                    <span className="ml-2 text-[10px] text-orange-500">parsing {s.parse_status}</span>
                  )}
                </td>
                {source.showsAgency ? (
                  <td className="px-3 py-2 text-xs text-slate-600">
                    {s.supplier_name ? (
                      <>
                        {s.supplier_name}
                        {(s.supplier_branch || s.supplier_code) && (
                          <span className="text-slate-400">
                            {" · "}{[s.supplier_branch, s.supplier_code].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </>
                    ) : (
                      // Listed but not runnable: with no consolidator there is no B2B
                      // deal to price it against, and saying so here beats failing later.
                      <span className="inline-flex items-center gap-1 text-amber-600"
                            title={s.blocked_reason ?? undefined}>
                        <AlertTriangle className="w-3 h-3" /> No agency
                      </span>
                    )}
                  </td>
                ) : (
                  <td className="px-3 py-2 text-xs text-slate-600">{s.airline_name || s.airline_code || "—"}</td>
                )}
                <td className="px-3 py-2 text-xs text-slate-500">
                  {s.period_from || "—"}{s.period_to ? ` → ${s.period_to}` : ""}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-600">{s.row_count.toLocaleString("en-IN")}</td>
                <td className="px-3 py-2 text-center"><StatusBadge s={s} /></td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-600">{s.matched_rows.toLocaleString("en-IN")}</td>
                {source.showsEnrichment && (
                  <td
                    className="px-3 py-2 text-right tabular-nums text-amber-700"
                    title="Matched a deal, but it pays only on a cabin class, travel window or route this statement does not print — upload the matching TGQ HMPR and re-run."
                  >
                    {s.needs_data_rows.toLocaleString("en-IN")}
                  </td>
                )}
                <td className="px-3 py-2 text-right tabular-nums text-orange-600">{(s.unmatched_rows + s.needs_data_rows).toLocaleString("en-IN")}</td>
                <td className="px-3 py-2 text-right tabular-nums text-teal-700">
                  {s.iata_total != null ? `₹${inr(s.iata_total)}` : <span className="text-slate-300">—</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums font-semibold text-emerald-700">
                  {s.total_incentive != null ? `₹${inr(s.total_incentive)}` : <span className="text-slate-300">—</span>}
                </td>
                {source.showsVariance && (
                  <td className="px-3 py-2 text-right tabular-nums font-semibold">
                    {s.variance_total == null ? <span className="text-slate-300">—</span>
                      : s.variance_total > 0
                        ? <span className="text-amber-700" title="They paid you less than your deals say">
                            ₹{inr(s.variance_total)}
                          </span>
                        : s.variance_total < 0
                          ? <span className="text-slate-500" title="They paid you more than your deals say">
                              −₹{inr(Math.abs(s.variance_total))}
                            </span>
                          : <span className="text-slate-400">₹0.00</span>}
                  </td>
                )}
                <td className="px-3 py-2 text-right">
                  <button onClick={() => onOpen(s)}
                    className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline">
                    <Calculator className="w-3.5 h-3.5" /> Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
