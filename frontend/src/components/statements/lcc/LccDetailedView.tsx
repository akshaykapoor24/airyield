"use client";

import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
  Upload, RefreshCw, Trash2, Download, Eye, ArrowLeft, AlertTriangle,
  ChevronLeft, ChevronRight, FolderOpen, CheckCircle2, Loader2, Clock, XCircle,
  X, Search, SlidersHorizontal, ChevronDown, ChevronUp,
} from "lucide-react";
import api from "@/lib/api";
import { inr } from "@/lib/money";
import toast from "react-hot-toast";
import LccUploadWizard from "./LccUploadWizard";
import LccBillingWorklist from "./LccBillingWorklist";

const PAGE = 50;
const SELECT_CLS = "border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";
const TEXT_CLS = "pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs w-36 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";
const DATE_CLS = "border border-slate-200 rounded-md px-1.5 py-1 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";

type BatchStatus = "staged" | "pending" | "processing" | "completed" | "failed";
type Batch = {
  batch_id: string;
  source_file: string | null;
  uploaded_at: string;
  completed_at: string | null;
  status: BatchStatus;
  total_rows: number;
  processed_rows: number;
  expected_rows: number | null;
  progress_pct: number;
  row_count: number;
  has_file: boolean;
  created_by_name: string | null;
  // Declared at upload from User Master → Airline Master. Null on batches imported
  // before the airline was captured — those are fixed with "Set airline", not re-uploaded.
  airline_name: string | null;
  airline_code: string | null;
  airline_ref_id: string | null;
  tenant_airline_id: number | null;
  // Billing: how many of this upload's rows have a party, and whether they have been
  // projected into uploaded_tickets yet. See LccBillingWorklist.
  billable_rows: number;
  resolved_rows: number;
  unresolved_rows: number;
  projected_rows: number;
  resolution_status: "none" | "resolved" | "projected";
};
type Column = { header: string; field: string };
type Row = Record<string, string | number | null> & { id: number };
type TenantAirlineOpt = {
  id: number; ref_id: string; airline_name: string | null; airline_code: string | null;
};

// Declared by the backend spec (services/lcc_detailed_spec.py FILTERS), so adding a
// filter is a server-side edit and this view needs no change. `primary` filters sit in
// the always-visible row, the rest behind "More filters". `options` is set only where the
// values are fixed rather than discovered from the data (the International boolean).
type FilterSpec = {
  field: string; label: string;
  type: "text" | "select" | "daterange";
  primary?: boolean; options?: string[];
};
type Summary = {
  fields: { field: string; label: string }[];
  // Strings, not numbers — a float round-trip through JSON would lose paise.
  computed: Record<string, string>;
  row_count: number;
  pax_count: number;
};
type RecordsResponse = {
  total: number; columns: Column[]; rows: Row[];
  filters?: FilterSpec[]; summary?: Summary;
};

/** The fvals keys a filter owns — a date range holds two, everything else one. */
function fkeys(f: FilterSpec): string[] {
  return f.type === "daterange" ? [`${f.field}.from`, `${f.field}.to`] : [f.field];
}

function fmtDate(s: string | null): string {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(); } catch { return s; }
}

function StatusCell({ b }: { b: Batch }) {
  if (b.status === "completed") {
    return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700"><CheckCircle2 className="w-3.5 h-3.5" /> Completed</span>;
  }
  if (b.status === "failed") {
    return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-red-600"><XCircle className="w-3.5 h-3.5" /> Failed</span>;
  }
  if (b.status === "staged") {
    return <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-400"><Clock className="w-3.5 h-3.5" /> Staged</span>;
  }
  // pending | processing → progress bar
  const pct = b.status === "pending" ? 0 : b.progress_pct;
  return (
    <div className="min-w-[120px]">
      <div className="flex items-center gap-1 text-[11px] font-medium text-blue-600 mb-1">
        <Loader2 className="w-3 h-3 animate-spin" />
        {b.status === "pending" ? "Queued…" : `Processing ${b.processed_rows.toLocaleString()} / ${b.total_rows.toLocaleString()}`}
      </div>
      <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
        <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${Math.max(3, pct)}%` }} />
      </div>
    </div>
  );
}

function Stat({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`text-sm font-bold mt-0.5 tabular-nums ${accent ?? "text-slate-800"}`}>{value}</p>
      {sub && <p className="text-[10px] mt-0.5 text-slate-400">{sub}</p>}
    </div>
  );
}

/**
 * Totals over the WHOLE filtered set, not the visible page.
 *
 * The field order mirrors the identity a reconciler eyeballs — Total ≈ Base Fare + Taxes
 * + Other Fees + SSR — so a file that doesn't add up shows it without exporting anything.
 * Unlike the BSP/TGQ slab there is no declared figure to compare against: an LCC export
 * carries no grand-total line, so these are computed figures only.
 */
function TotalsStrip({ summary, filtered }: { summary: Summary; filtered: boolean }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-2 mb-3">
      <Stat label="Rows" value={summary.row_count.toLocaleString("en-IN")} sub={filtered ? "filtered" : undefined} />
      <Stat label="Pax" value={summary.pax_count.toLocaleString("en-IN")} />
      {summary.fields.map((f) => {
        const n = Number(summary.computed[f.field] ?? "0");
        // Refunds and payment reversals are genuinely negative — that should read as a
        // refund, not as a typo.
        return <Stat key={f.field} label={f.label} value={inr(n, 2)}
          accent={n < 0 ? "text-red-600" : undefined} />;
      })}
    </div>
  );
}

function FilterControl({ f, fvals, setFvals, facets }: {
  f: FilterSpec;
  fvals: Record<string, string>;
  setFvals: Dispatch<SetStateAction<Record<string, string>>>;
  facets: Record<string, string[]>;
}) {
  // Delete rather than store "", so `hasFilters` and the active-count badge stay honest.
  const set = (k: string, v: string) =>
    setFvals((p) => { const n = { ...p }; if (v) n[k] = v; else delete n[k]; return n; });

  if (f.type === "select") {
    return (
      <select value={fvals[f.field] ?? ""} className={SELECT_CLS} title={f.label}
        onChange={(e) => set(f.field, e.target.value)}>
        <option value="">All {f.label}</option>
        {(f.options ?? facets[f.field] ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
      </select>
    );
  }
  if (f.type === "daterange") {
    return (
      <div className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1">
        <span className="text-[10px] uppercase tracking-wide text-slate-400 whitespace-nowrap">{f.label}</span>
        <input type="date" className={DATE_CLS} aria-label={`${f.label} from`}
          value={fvals[`${f.field}.from`] ?? ""} onChange={(e) => set(`${f.field}.from`, e.target.value)} />
        <span className="text-slate-300 text-xs">→</span>
        <input type="date" className={DATE_CLS} aria-label={`${f.label} to`}
          value={fvals[`${f.field}.to`] ?? ""} onChange={(e) => set(`${f.field}.to`, e.target.value)} />
      </div>
    );
  }
  return (
    <div className="relative">
      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
      <input value={fvals[f.field] ?? ""} placeholder={f.label} className={TEXT_CLS}
        onChange={(e) => set(f.field, e.target.value)} />
    </div>
  );
}

export default function LccDetailedView({ apiBase, title }: { apiBase: string; title: string }) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Batch | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selected, setSelected] = useState<Batch | null>(null);
  // The billing worklist is a third view, alongside the uploads list and the records
  // drill-in. Kept as local state rather than a route, matching `selected`.
  const [billingTarget, setBillingTarget] = useState<Batch | null>(null);

  // Backfilling the airline onto an already-imported batch.
  const [airlineTarget, setAirlineTarget] = useState<Batch | null>(null);
  const [airlineOpts, setAirlineOpts] = useState<TenantAirlineOpt[]>([]);
  const [airlinePick, setAirlinePick] = useState<number | "">("");
  const [savingAirline, setSavingAirline] = useState(false);

  // drill-in records
  const [columns, setColumns] = useState<Column[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [rtotal, setRtotal] = useState(0);
  const [roffset, setRoffset] = useState(0);
  const [rloading, setRloading] = useState(false);

  // drill-in filters — all declared by the backend, so this view has no field list of its own
  const [filters, setFilters] = useState<FilterSpec[]>([]);
  const [fvals, setFvals] = useState<Record<string, string>>({});
  const [facets, setFacets] = useState<Record<string, string[]>>({});
  const [summary, setSummary] = useState<Summary | null>(null);
  const [showMore, setShowMore] = useState(false);
  // Opening a batch should feel instant; only filter edits are worth debouncing.
  const skipDebounce = useRef(true);
  // Monotonic request id. Debouncing cancels pending TIMERS, not in-flight REQUESTS, so
  // without this a slow "DEL" response can land after a fast "DELHI" one and paint the
  // wrong rows and totals under the newer text.
  const reqSeq = useRef(0);

  const hasFilters = Object.values(fvals).some(Boolean);
  const primaryFilters = filters.filter((f) => f.primary);
  const moreFilters = filters.filter((f) => !f.primary);
  const moreActive = moreFilters.filter((f) => fkeys(f).some((k) => fvals[k])).length;

  const fetchBatches = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try { const { data } = await api.get<Batch[]>(`${apiBase}/batches`); setBatches(data); }
    catch { if (!silent) toast.error("Failed to load uploads."); }
    finally { if (!silent) setLoading(false); }
  }, [apiBase]);

  useEffect(() => {
    setSelected(null); setFvals({}); setFilters([]); setFacets({}); setSummary(null);
    fetchBatches();
  }, [fetchBatches]);

  // Poll while any upload is still queued/processing.
  const hasActive = batches.some((b) => b.status === "pending" || b.status === "processing");
  useEffect(() => {
    if (!hasActive) return;
    const t = setInterval(() => fetchBatches(true), 2000);
    return () => clearInterval(t);
  }, [hasActive, fetchBatches]);

  const loadRecords = useCallback(async (batchId: string, offset: number) => {
    const seq = ++reqSeq.current;
    setRloading(true);
    try {
      const params: Record<string, string | number> = { batch_id: batchId, offset, limit: PAGE };
      for (const [k, v] of Object.entries(fvals)) if (v) params[`f.${k}`] = v;
      const { data } = await api.get<RecordsResponse>(`${apiBase}/records`, { params });
      if (seq !== reqSeq.current) return;   // a newer request already landed
      setColumns(data.columns); setRows(data.rows); setRtotal(data.total); setRoffset(offset);
      setFilters(data.filters ?? []); setSummary(data.summary ?? null);
    } catch { if (seq === reqSeq.current) toast.error("Failed to load rows."); }
    finally { if (seq === reqSeq.current) setRloading(false); }
  }, [apiBase, fvals]);

  // One effect covers typing, dropdowns and date pickers, and always returns to page 1 —
  // a filtered view still paged to offset 300 would otherwise land on an empty page with
  // a working Prev button and no rows.
  useEffect(() => {
    if (!selected) return;
    const delay = skipDebounce.current ? 0 : 250;
    skipDebounce.current = false;
    const t = setTimeout(() => loadRecords(selected.batch_id, 0), delay);
    return () => clearTimeout(t);
  }, [selected, loadRecords]);

  // Facet values are per batch, not per active filter, so the options don't disappear as
  // you narrow. A failure just leaves the dropdowns empty — not worth a toast.
  useEffect(() => {
    if (!selected) return;
    api.get<Record<string, string[]>>(`${apiBase}/records/facets`, { params: { batch_id: selected.batch_id } })
      .then((r) => setFacets(r.data ?? {}))
      .catch(() => {});
  }, [apiBase, selected]);

  const openBatch = (b: Batch) => {
    if (b.status !== "completed") { toast(b.status === "failed" ? "This upload failed." : "This upload is still processing."); return; }
    // No loadRecords call here — the effect above does it. Doing both fires two requests.
    skipDebounce.current = true;
    setFvals({}); setFacets({}); setSummary(null); setShowMore(false);
    setSelected(b);
  };

  const closeBatch = () => {
    setSelected(null);
    setFvals({}); setFilters([]); setFacets({}); setSummary(null); setShowMore(false);
  };

  const clearFilters = () => { setFvals({}); setShowMore(false); };

  const downloadFile = async (b: Batch) => {
    try { const { data } = await api.get<{ url: string }>(`${apiBase}/batches/${b.batch_id}/file-url`, { params: { inline: false } }); window.open(data.url, "_blank"); }
    catch { toast.error("No stored file for this upload."); }
  };

  const previewFile = async (b: Batch) => {
    // Open the tab synchronously so it isn't blocked as a popup, then navigate it to the
    // Microsoft Office web viewer once we have the (possibly just-converted) xlsx URL.
    const w = window.open("", "_blank");
    if (w) w.document.write("<p style='font:14px system-ui,sans-serif;padding:24px;color:#555'>Preparing preview…</p>");
    try {
      const { data } = await api.get<{ url: string }>(`${apiBase}/batches/${b.batch_id}/viewer-url`);
      const office = `https://view.officeapps.live.com/op/view.aspx?src=${encodeURIComponent(data.url)}`;
      if (w) w.location.href = office; else window.open(office, "_blank");
    } catch { if (w) w.close(); toast.error("Could not open preview."); }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`${apiBase}/batches/${deleteTarget.batch_id}`);
      toast.success("Upload deleted.");
      setDeleteTarget(null);
      // closeBatch, not setSelected(null): deleting the upload you are drilled into must
      // drop its filters too, or they leak onto the next upload you open.
      if (selected?.batch_id === deleteTarget.batch_id) closeBatch();
      fetchBatches();
    } catch { toast.error("Failed to delete."); }
    finally { setDeleting(false); }
  };

  const openAirlineModal = async (b: Batch) => {
    setAirlineTarget(b);
    setAirlinePick(b.tenant_airline_id ?? "");
    try {
      const { data } = await api.get<TenantAirlineOpt[]>("/tenant-airlines/", { params: { active: true } });
      setAirlineOpts(data);
    } catch { toast.error("Failed to load your Airline Master."); }
  };

  const saveAirline = async () => {
    if (!airlineTarget || !airlinePick) return;
    setSavingAirline(true);
    try {
      // One indexed bulk UPDATE server-side — the rows parsed fine, only the carrier
      // was missing, so there is nothing to re-ingest.
      const { data } = await api.patch<{ rows_updated: number; airline_name: string | null }>(
        `${apiBase}/batches/${airlineTarget.batch_id}/airline`, { tenant_airline_id: airlinePick });
      toast.success(`${data.airline_name ?? "Airline"} set on ${data.rows_updated.toLocaleString()} rows.`);
      setAirlineTarget(null);
      fetchBatches();
    } catch { toast.error("Could not set the airline."); }
    finally { setSavingAirline(false); }
  };

  const downloadTemplate = async () => {
    try {
      const { data } = await api.get(`${apiBase}/template`, { responseType: "blob" });
      const url = URL.createObjectURL(data as Blob);
      const a = document.createElement("a"); a.href = url; a.download = "lcc_detailed_template.xlsx"; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Failed to download template."); }
  };

  // ── Billing worklist ──────────────────────────────────────────────────────
  if (billingTarget) {
    return (
      <LccBillingWorklist
        apiBase={apiBase}
        batchId={billingTarget.batch_id}
        fileName={billingTarget.source_file}
        onBack={() => { setBillingTarget(null); fetchBatches(); }}
        onChanged={() => fetchBatches(true)}
      />
    );
  }

  // ── Drill-in: one upload's rows ───────────────────────────────────────────
  if (selected) {
    const start = rtotal === 0 ? 0 : roffset + 1;
    const end = Math.min(roffset + rows.length, rtotal);
    return (
      <div>
        <div className="flex items-center gap-2 mb-3">
          <button onClick={closeBatch} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-700"><ArrowLeft className="w-3.5 h-3.5" /> Back to uploads</button>
          <span className="text-slate-300">|</span>
          <h3 className="text-sm font-semibold text-slate-800 truncate max-w-[320px]" title={selected.source_file ?? undefined}>{title} · {selected.source_file || "upload"}</h3>
          <span className="text-[11px] text-slate-400">
            {/* the filtered count, not the batch's — those differ the moment you filter */}
            · {rtotal.toLocaleString()} {rtotal === 1 ? "entry" : "entries"}
            {hasFilters && <span className="text-amber-600"> (filtered from {selected.row_count.toLocaleString()})</span>}
            {" "}· {fmtDate(selected.uploaded_at)}
          </span>
          {selected.has_file && (
            <div className="ml-auto flex items-center gap-2">
              <button onClick={() => previewFile(selected)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-700 border border-blue-200 bg-blue-50 rounded-lg hover:bg-blue-100"><Eye className="w-3.5 h-3.5" /> Preview</button>
              <button onClick={() => downloadFile(selected)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50"><Download className="w-3.5 h-3.5" /> Download</button>
            </div>
          )}
        </div>
        {summary && <TotalsStrip summary={summary} filtered={hasFilters} />}

        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          {filters.length > 0 && (
            <div className="border-b border-slate-100 bg-slate-50/40">
              <div className="flex items-center gap-2 flex-wrap px-3 py-2.5">
                {primaryFilters.map((f) => (
                  <FilterControl key={f.field} f={f} fvals={fvals} setFvals={setFvals} facets={facets} />
                ))}
                {moreFilters.length > 0 && (
                  <button onClick={() => setShowMore((s) => !s)}
                    className="inline-flex items-center gap-1 px-2 py-1.5 text-xs text-slate-500 border border-slate-200 rounded-lg bg-white hover:bg-slate-50">
                    <SlidersHorizontal className="w-3.5 h-3.5" /> More filters
                    {/* the count, so a filter hidden inside the disclosure is never invisible */}
                    {moreActive > 0 && (
                      <span className="px-1.5 rounded-full bg-amber-100 text-amber-700 text-[10px] font-semibold tabular-nums">{moreActive}</span>
                    )}
                    {showMore ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                  </button>
                )}
                {hasFilters && (
                  <button onClick={clearFilters} className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800">
                    <X className="w-3.5 h-3.5" /> Clear
                  </button>
                )}
                <span className="ml-auto text-[11px] text-slate-400 tabular-nums">{rtotal.toLocaleString()} rows</span>
              </div>
              {showMore && (
                <div className="flex items-center gap-2 flex-wrap px-3 pb-2.5 pt-1 border-t border-slate-100">
                  {moreFilters.map((f) => (
                    <FilterControl key={f.field} f={f} fvals={fvals} setFvals={setFvals} facets={facets} />
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="text-left border-collapse text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
                  {columns.map((c) => <th key={c.field} className="px-3 py-2 font-semibold whitespace-nowrap">{c.header}</th>)}
                </tr>
              </thead>
              {/* Dim the current page rather than blanking it: with a 250 ms debounce,
                  swapping to "Loading…" on every keystroke reads as a strobe. */}
              <tbody className={rloading && rows.length > 0 ? "opacity-50 transition-opacity" : ""}>
                {rloading && rows.length === 0 ? (
                  <tr><td colSpan={columns.length || 1} className="px-3 py-8 text-center text-slate-400">Loading…</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={columns.length || 1} className="px-3 py-8 text-center text-slate-400">
                    {hasFilters ? "No rows match these filters." : "No rows."}
                  </td></tr>
                ) : rows.map((r) => (
                  <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50/60">
                    {columns.map((c) => {
                      const v = r[c.field];
                      return <td key={c.field} className="px-3 py-1.5 text-xs text-slate-700 whitespace-nowrap max-w-[240px] truncate" title={v != null ? String(v) : undefined}>{v != null && v !== "" ? String(v) : <span className="text-slate-300">—</span>}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rtotal > 0 && (
            <div className="flex items-center justify-between px-3 py-2.5 border-t border-slate-100 text-xs text-slate-500">
              <span>Showing {start.toLocaleString()}–{end.toLocaleString()} of {rtotal.toLocaleString()}</span>
              <div className="flex items-center gap-1">
                <button disabled={roffset === 0 || rloading} onClick={() => loadRecords(selected.batch_id, Math.max(0, roffset - PAGE))} className="flex items-center gap-1 px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40"><ChevronLeft className="w-3.5 h-3.5" /> Prev</button>
                <button disabled={roffset + PAGE >= rtotal || rloading} onClick={() => loadRecords(selected.batch_id, roffset + PAGE)} className="flex items-center gap-1 px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40">Next <ChevronRight className="w-3.5 h-3.5" /></button>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Uploads list ──────────────────────────────────────────────────────────
  return (
    <div>
      <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
        <div className="bg-white border border-slate-200 rounded-lg px-4 py-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">Uploads</span>
          <span className="ml-2 text-sm font-bold text-slate-800">{batches.length}</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => fetchBatches()} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"><RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh</button>
          <button onClick={downloadTemplate} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"><Download className="w-3.5 h-3.5" /> Template</button>
          <button onClick={() => setWizardOpen(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700"><Upload className="w-3.5 h-3.5" /> Upload XLS</button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
              <th className="text-left px-3 py-2.5 font-semibold">File</th>
              <th className="text-left px-3 py-2.5 font-semibold">Airline</th>
              <th className="text-left px-3 py-2.5 font-semibold">Uploaded</th>
              <th className="text-left px-3 py-2.5 font-semibold">Status</th>
              <th className="text-right px-3 py-2.5 font-semibold">Entries</th>
              <th className="text-left px-3 py-2.5 font-semibold">Billing</th>
              <th className="text-left px-3 py-2.5 font-semibold">Uploaded by</th>
              <th className="text-right px-3 py-2.5 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="px-3 py-10 text-center text-slate-400">Loading…</td></tr>
            ) : batches.length === 0 ? (
              <tr><td colSpan={8} className="px-3 py-12 text-center text-slate-400">No uploads yet. <button onClick={() => setWizardOpen(true)} className="text-blue-600 hover:underline">Upload an XLS</button>.</td></tr>
            ) : batches.map((b) => (
              <tr key={b.batch_id} className="border-b border-slate-100 hover:bg-slate-50/60">
                <td className="px-3 py-2">
                  <button onClick={() => openBatch(b)} className="flex items-center gap-2 text-slate-700 hover:text-blue-700" disabled={b.status !== "completed"}>
                    <FolderOpen className="w-4 h-4 text-slate-400" />
                    <span className="font-medium truncate max-w-[240px]" title={b.source_file ?? undefined}>{b.source_file || "upload"}</span>
                  </button>
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {b.airline_name ? (
                    <span className="text-xs text-slate-700">
                      {b.airline_code && <span className="font-semibold">{b.airline_code}</span>} {b.airline_name}
                      {b.airline_ref_id && <span className="text-slate-400"> · {b.airline_ref_id}</span>}
                    </span>
                  ) : (
                    <button onClick={() => openAirlineModal(b)}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700 border border-amber-200 bg-amber-50 rounded-md px-2 py-1 hover:bg-amber-100"
                      title="This upload has no airline — the file doesn't name one">
                      <AlertTriangle className="w-3 h-3" /> Set airline
                    </button>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-slate-500 whitespace-nowrap">{fmtDate(b.uploaded_at)}</td>
                <td className="px-3 py-2"><StatusCell b={b} /></td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <span className="tabular-nums text-slate-700">{b.row_count.toLocaleString()}</span>
                  {b.expected_rows != null && b.status === "completed" && (
                    b.row_count === b.expected_rows ? (
                      <span title={`Matches the ${b.expected_rows.toLocaleString()} expected records`}
                        className="ml-1.5 inline-flex items-center align-middle text-emerald-500"><CheckCircle2 className="w-3.5 h-3.5" /></span>
                    ) : (
                      <span title={`Expected ${b.expected_rows.toLocaleString()} — ${Math.abs(b.row_count - b.expected_rows).toLocaleString()} ${b.row_count < b.expected_rows ? "missing" : "extra"}`}
                        className="ml-1.5 inline-flex items-center gap-0.5 align-middle text-[10px] font-semibold text-amber-600"><AlertTriangle className="w-3 h-3" /> /{b.expected_rows.toLocaleString()}</span>
                    )
                  )}
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {b.status !== "completed" ? (
                    <span className="text-[11px] text-slate-300">—</span>
                  ) : b.resolution_status === "none" ? (
                    <button onClick={() => setBillingTarget(b)}
                      className="text-[11px] font-medium text-blue-600 hover:underline">
                      Set up billing
                    </button>
                  ) : (
                    <button onClick={() => setBillingTarget(b)} className="text-left group">
                      <span className="text-[11px] tabular-nums text-slate-700 group-hover:underline">
                        {b.resolved_rows.toLocaleString()} / {b.billable_rows.toLocaleString()} billable
                      </span>
                      <span className="block text-[10px]">
                        {b.projected_rows > 0
                          ? <span className="text-emerald-600">{b.projected_rows.toLocaleString()} in billing</span>
                          : <span className="text-amber-600">not sent to billing yet</span>}
                      </span>
                    </button>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-slate-500">{b.created_by_name || "—"}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button onClick={() => openBatch(b)} disabled={b.status !== "completed"} className="text-xs font-medium text-blue-600 hover:underline mr-3 disabled:text-slate-300 disabled:no-underline">Open</button>
                  {b.airline_name && <button onClick={() => openAirlineModal(b)} className="text-xs font-medium text-slate-500 hover:underline mr-3" title="Change the airline on this upload">Airline</button>}
                  {b.has_file && <button onClick={() => previewFile(b)} className="p-1 text-slate-400 hover:text-blue-600 mr-1" title="Preview file"><Eye className="w-3.5 h-3.5" /></button>}
                  {b.has_file && <button onClick={() => downloadFile(b)} className="p-1 text-slate-400 hover:text-slate-700 mr-1" title="Download original"><Download className="w-3.5 h-3.5" /></button>}
                  <button onClick={() => setDeleteTarget(b)} className="p-1 text-slate-400 hover:text-red-600" title="Delete upload"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {wizardOpen && (
        <LccUploadWizard
          apiBase={apiBase}
          title={title}
          onClose={() => setWizardOpen(false)}
          onDone={() => { setWizardOpen(false); fetchBatches(); }}
        />
      )}

      {airlineTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5">
            <h2 className="text-sm font-semibold text-slate-800 mb-1">Set the airline for this upload</h2>
            <p className="text-xs text-slate-500 mb-3">
              An LCC statement doesn&apos;t name its carrier, so it has to be declared. This stamps it
              onto the upload and all {airlineTarget.row_count.toLocaleString()} of its rows — nothing is re-imported.
            </p>
            <select
              value={airlinePick}
              onChange={(e) => setAirlinePick(e.target.value ? Number(e.target.value) : "")}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
              <option value="">Select your airline ID…</option>
              {airlineOpts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.ref_id} — {a.airline_name ?? "?"}{a.airline_code ? ` (${a.airline_code})` : ""}
                </option>
              ))}
            </select>
            {airlineOpts.length === 0 && (
              <p className="text-[11px] text-amber-600 mt-2">
                Your Airline Master is empty — add the airline under User Master → Airline Master first.
              </p>
            )}
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setAirlineTarget(null)} className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
              <button onClick={saveAirline} disabled={savingAirline || !airlinePick} className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">{savingAirline ? "Saving…" : "Set airline"}</button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
            <div className="flex items-center gap-2.5 mb-2"><AlertTriangle className="w-5 h-5 text-red-500" /><h2 className="text-sm font-semibold text-slate-800">Delete this upload?</h2></div>
            <p className="text-xs text-slate-500 mb-4">This permanently removes “{deleteTarget.source_file || "upload"}” and all its rows. This cannot be undone.</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeleteTarget(null)} className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
              <button onClick={confirmDelete} disabled={deleting} className="px-4 py-1.5 text-xs font-semibold text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50">{deleting ? "Deleting…" : "Delete"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
