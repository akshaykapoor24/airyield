"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  Upload, RefreshCw, Trash2, Download, Eye, X, AlertTriangle, ArrowLeft,
  FileSpreadsheet, CheckCircle2, Loader2, ChevronLeft, ChevronRight, FolderOpen, Search, Split,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import { notifyRequired } from "@/lib/requiredFields";

const PAGE = 50;
// The API rejects anything below 3 recognised columns (_MIN_MATCHED_COLUMNS in
// api/v1/statements.py). Between that floor and this number the import succeeds
// but most fields land empty, which is worth saying out loud.
const LOW_MATCH_WARNING = 6;
const SELECT_CLS =
  "border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400";

type Batch = {
  batch_id: string;
  source_file: string | null;
  uploaded_at: string;
  row_count: number;
  has_file: boolean;
  created_by_name: string | null;
};
// `kind: "money"` is set by the backend for amount columns so they right-align and format.
type Column = { header: string; field: string; kind?: string };
type Row = Record<string, string | number | null> & { id: number };

// Declared per statement type in the backend spec; absent for types that have no filters,
// in which case the toolbar and the slab below simply never render.
type FilterSpec = { field: string; label: string; type: "select" | "text" };
type Summary = {
  fields: { field: string; label: string }[];
  computed: Record<string, string>;
  declared: Record<string, string | null> | null;
  declared_comparable: boolean;
  declared_note: string | null;
  row_count: number;
  leg_count: number;
};
type RecordsResponse = {
  total: number; columns: Column[]; rows: Row[];
  filters?: FilterSpec[]; summary?: Summary; needs_reprocess?: boolean;
};

function fmtDate(s: string): string {
  try { return new Date(s).toLocaleString(); } catch { return s; }
}
function errMsg(e: unknown, fallback: string): string {
  const m = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return typeof m === "string" ? m : fallback;
}
/** Indian grouping for amounts; anything non-numeric is passed through untouched. */
function fmtMoney(v: string | number | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = Number(String(v).replace(/,/g, ""));
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

/** XLS/CSV upload modal for one adjustment type. */
function UploadModal({ apiBase, title, onClose, onDone }: { apiBase: string; title: string; onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const pick = (f: File | null) => {
    if (f && !/\.(xlsx|xls|csv)$/i.test(f.name)) { toast.error("Choose an .xlsx, .xls or .csv file."); return; }
    setFile(f);
  };
  const submit = async () => {
    if (!file) { notifyRequired("Choose an .xlsx, .xls or .csv file to import."); return; }
    setUploading(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const { data } = await api.post<{ inserted: number; matched_columns: number; source_rows?: number; leg_rows?: number }>(`${apiBase}/upload`, fd);
      // Sector-split types insert more rows than the file has lines — say so, or "imported
      // 518" against a 223-line file reads like a bug.
      const split = data.source_rows != null && data.leg_rows != null && data.leg_rows !== data.source_rows;
      toast.success(split
        ? `Imported ${data.source_rows} ${title} ticket line${data.source_rows === 1 ? "" : "s"} as ${data.leg_rows} sector rows.`
        : `Imported ${data.inserted} ${title} row${data.inserted === 1 ? "" : "s"}.`);
      // The API refuses a file below its minimum recognised-column threshold, but
      // it will happily accept one just above it — and then most columns land
      // empty. The count was already in the response and simply never shown.
      if (data.matched_columns != null && data.matched_columns < LOW_MATCH_WARNING) {
        toast(
          `Only ${data.matched_columns} column${data.matched_columns === 1 ? "" : "s"} were recognised — most fields will be blank. Check the file against the Template.`,
          { icon: "⚠️", duration: 7000 }
        );
      }
      onDone();
    } catch (e) { toast.error(errMsg(e, "Failed to import the file.")); }
    finally { setUploading(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-800">Upload {title} spreadsheet</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0] ?? null); }}
            onClick={() => !file && inputRef.current?.click()}
            className={`cursor-pointer flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center ${
              dragging ? "border-blue-500 bg-blue-50" : file ? "border-emerald-200 bg-emerald-50/40" : "border-slate-200 bg-slate-50/60 hover:border-slate-300"}`}
          >
            {file ? (
              <div className="w-full max-w-sm flex items-center gap-3 rounded-lg border border-emerald-200 bg-white p-3 shadow-sm">
                <div className="w-9 h-9 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0"><FileSpreadsheet className="w-5 h-5 text-emerald-600" /></div>
                <div className="min-w-0 flex-1 text-left"><p className="text-xs font-semibold text-slate-800 truncate" title={file.name}>{file.name}</p><p className="text-[11px] text-slate-500">{(file.size / 1024).toFixed(0)} KB</p></div>
                <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
                <button onClick={(e) => { e.stopPropagation(); setFile(null); }} className="p-1 text-slate-400 hover:text-red-500 shrink-0"><X className="w-4 h-4" /></button>
              </div>
            ) : (
              <>
                <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center mb-3"><Upload className="w-6 h-6 text-blue-600" /></div>
                <p className="text-sm font-medium text-slate-700">Drop your {title} export here</p>
                <p className="text-xs text-slate-400 mt-0.5">or click to browse · .xlsx, .xls, .csv</p>
              </>
            )}
            <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          </div>
          <p className="text-[11px] text-slate-400 mt-3">The original file is stored so you can download it later. Columns are matched by header name.</p>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-slate-100">
          <button onClick={onClose} className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
          <button onClick={submit} disabled={!file || uploading} className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />} Import
          </button>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, sub, accent }: { label: string; value: string; sub?: ReactNode; accent?: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`text-sm font-bold mt-0.5 tabular-nums ${accent ?? "text-slate-800"}`}>{value}</p>
      {sub && <p className="text-[10px] mt-0.5 tabular-nums text-slate-400">{sub}</p>}
    </div>
  );
}

/**
 * Totals for the whole filtered set, lifted out of the table body.
 *
 * Statements carry their own grand-total line, and it does not always agree with the
 * column it claims to total. Rather than pick a winner, both figures are shown: the
 * computed total on top, the vendor's declared figure beneath, and an amber tint when
 * they disagree.
 */
function SummarySlab({ summary }: { summary: Summary }) {
  const { fields, computed, declared, declared_comparable, declared_note, row_count, leg_count } = summary;
  const split = leg_count > row_count;
  return (
    <div className="mb-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-2">
        <Stat
          label={split ? "Tickets · Sectors" : "Rows"}
          value={split ? `${row_count.toLocaleString("en-IN")} · ${leg_count.toLocaleString("en-IN")}` : row_count.toLocaleString("en-IN")}
          sub={split ? "split by sector" : undefined}
        />
        {fields.map((f) => {
          const c = computed[f.field];
          const d = declared?.[f.field];
          const differs = declared_comparable && d != null && d !== "" &&
            Math.abs(Number(String(c).replace(/,/g, "")) - Number(String(d).replace(/,/g, ""))) > 0.005;
          return (
            <Stat key={f.field} label={f.label} value={fmtMoney(c)}
              accent={differs ? "text-amber-700" : undefined}
              sub={
                d == null || d === "" ? undefined
                  : declared_comparable
                    ? <span className={differs ? "text-amber-600" : "text-emerald-600"}>
                        {differs ? "≠" : "✓"} file {fmtMoney(d)}
                      </span>
                    : <span className="text-slate-300">file {fmtMoney(d)}</span>
              } />
          );
        })}
      </div>
      {declared_note && <p className="mt-1.5 text-[11px] text-amber-700">{declared_note}</p>}
      {declared && !declared_comparable && (
        <p className="mt-1.5 text-[11px] text-slate-400">
          Filters are active — these totals cover the filtered rows only, so they are not comparable to the file&apos;s own Total line.
        </p>
      )}
    </div>
  );
}

export default function AdjustmentStatementsView({ apiBase, slug, title }: { apiBase: string; slug: string; title: string; blurb?: string }) {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Batch | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selected, setSelected] = useState<Batch | null>(null);

  // drill-in records
  const [columns, setColumns] = useState<Column[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [rtotal, setRtotal] = useState(0);
  const [roffset, setRoffset] = useState(0);
  const [rloading, setRloading] = useState(false);

  // Opt-in extras — only ever populated for statement types whose spec declares them.
  const [filters, setFilters] = useState<FilterSpec[]>([]);
  const [fvals, setFvals] = useState<Record<string, string>>({});
  const [facets, setFacets] = useState<Record<string, string[]>>({});
  const [summary, setSummary] = useState<Summary | null>(null);
  const [needsReprocess, setNeedsReprocess] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  // Opening a batch should feel instant; only filter edits are worth debouncing.
  const skipDebounce = useRef(true);

  const hasFilters = Object.values(fvals).some(Boolean);
  const hasSelects = filters.some((f) => f.type === "select");

  const fetchBatches = useCallback(async () => {
    setLoading(true);
    try { const { data } = await api.get<Batch[]>(`${apiBase}/batches`); setBatches(data); }
    catch { toast.error(`Failed to load ${title} uploads.`); }
    finally { setLoading(false); }
  }, [apiBase, title]);

  useEffect(() => {
    setSelected(null); setFvals({}); setFilters([]); setFacets({}); setSummary(null);
    fetchBatches();
  }, [fetchBatches, slug]);

  const loadRecords = useCallback(async (batchId: string, offset: number) => {
    setRloading(true);
    try {
      const params: Record<string, string | number> = { batch_id: batchId, offset, limit: PAGE };
      for (const [k, v] of Object.entries(fvals)) if (v) params[`f.${k}`] = v;
      const { data } = await api.get<RecordsResponse>(`${apiBase}/records`, { params });
      setColumns(data.columns); setRows(data.rows); setRtotal(data.total); setRoffset(offset);
      setFilters(data.filters ?? []); setSummary(data.summary ?? null);
      setNeedsReprocess(!!data.needs_reprocess);
    } catch { toast.error("Failed to load rows."); }
    finally { setRloading(false); }
  }, [apiBase, fvals]);

  // One effect covers both typing and dropdowns, and always returns to page 1 — a filtered
  // view paged to offset 300 would otherwise land on an empty page.
  useEffect(() => {
    if (!selected) return;
    const delay = skipDebounce.current ? 0 : 250;
    skipDebounce.current = false;
    const t = setTimeout(() => loadRecords(selected.batch_id, 0), delay);
    return () => clearTimeout(t);
  }, [selected, loadRecords]);

  // Facet values are per batch, not per filter, so the options don't disappear as you narrow.
  useEffect(() => {
    if (!selected || !hasSelects) return;
    api.get<Record<string, string[]>>(`${apiBase}/records/facets`, { params: { batch_id: selected.batch_id } })
      .then((r) => setFacets(r.data ?? {}))
      .catch(() => {});   // types without facets simply 404 — not an error worth surfacing
  }, [apiBase, selected, hasSelects]);

  const openBatch = (b: Batch) => { skipDebounce.current = true; setFvals({}); setSelected(b); };
  const closeBatch = () => { setSelected(null); setFvals({}); setFilters([]); setSummary(null); };
  const clearFilters = () => setFvals({});

  const reprocess = async () => {
    if (!selected) return;
    setReprocessing(true);
    try {
      const { data } = await api.post<{ source_rows: number; leg_rows: number }>(
        `${apiBase}/batches/${selected.batch_id}/resplit`);
      toast.success(`Split ${data.source_rows} ticket line${data.source_rows === 1 ? "" : "s"} into ${data.leg_rows} sector rows.`);
      await fetchBatches();
      await loadRecords(selected.batch_id, 0);
    } catch (e) { toast.error(errMsg(e, "Failed to re-process this upload.")); }
    finally { setReprocessing(false); }
  };

  const downloadFile = async (b: Batch) => {
    try { const { data } = await api.get<{ url: string }>(`${apiBase}/batches/${b.batch_id}/file-url`, { params: { inline: false } }); window.open(data.url, "_blank"); }
    catch { toast.error("No stored file for this upload."); }
  };

  const previewFile = async (b: Batch) => {
    try {
      const { data } = await api.get<{ url: string }>(`${apiBase}/batches/${b.batch_id}/file-url`, { params: { inline: true } });
      const isExcel = /\.(xlsx|xls)$/i.test(b.source_file || "");
      const target = isExcel
        ? `https://view.officeapps.live.com/op/view.aspx?src=${encodeURIComponent(data.url)}`
        : data.url;   // CSV etc. render fine inline
      window.open(target, "_blank");
    } catch { toast.error("No stored file for this upload."); }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`${apiBase}/batches/${deleteTarget.batch_id}`);
      toast.success("Upload deleted.");
      setDeleteTarget(null);
      if (selected?.batch_id === deleteTarget.batch_id) setSelected(null);
      fetchBatches();
    } catch { toast.error("Failed to delete."); }
    finally { setDeleting(false); }
  };

  const downloadTemplate = async () => {
    try {
      const { data } = await api.get(`${apiBase}/template`, { responseType: "blob" });
      const url = URL.createObjectURL(data as Blob);
      const a = document.createElement("a"); a.href = url; a.download = `${slug}_template.xlsx`; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Failed to download template."); }
  };

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
            · {rtotal.toLocaleString("en-IN")} {rtotal === 1 ? "row" : "rows"}
            {hasFilters && <span className="text-amber-600"> (filtered from {selected.row_count.toLocaleString("en-IN")})</span>}
            {" "}· {fmtDate(selected.uploaded_at)}
          </span>
          {selected.has_file && (
            <div className="ml-auto flex items-center gap-2">
              <button onClick={() => previewFile(selected)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-700 border border-blue-200 bg-blue-50 rounded-lg hover:bg-blue-100">
                <Eye className="w-3.5 h-3.5" /> Preview
              </button>
              <button onClick={() => downloadFile(selected)} className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50">
                <Download className="w-3.5 h-3.5" /> Download
              </button>
            </div>
          )}
        </div>
        {needsReprocess && (
          <div className="flex items-center gap-2 mb-3 px-3 py-2.5 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800">
            <Split className="w-4 h-4 shrink-0" />
            <span>This upload predates per-sector splitting. Re-process it to show one row per flown sector, with the fare and taxes divided across the legs, and to lift the file&apos;s Total line out of the table.</span>
            <button onClick={reprocess} disabled={reprocessing}
              className="ml-auto shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-amber-600 rounded-lg hover:bg-amber-700 disabled:opacity-50">
              {reprocessing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Split className="w-3.5 h-3.5" />}
              {reprocessing ? "Re-processing…" : "Re-process"}
            </button>
          </div>
        )}

        {summary && <SummarySlab summary={summary} />}

        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          {filters.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap px-3 py-2.5 border-b border-slate-100 bg-slate-50/40">
              {filters.map((f) => (
                f.type === "select" ? (
                  <select key={f.field} value={fvals[f.field] ?? ""} className={SELECT_CLS}
                    onChange={(e) => setFvals((p) => ({ ...p, [f.field]: e.target.value }))}>
                    <option value="">All {f.label}</option>
                    {(facets[f.field] ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                ) : (
                  <div key={f.field} className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                    <input value={fvals[f.field] ?? ""} placeholder={f.label}
                      onChange={(e) => setFvals((p) => ({ ...p, [f.field]: e.target.value }))}
                      className="pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs w-36 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400" />
                  </div>
                )
              ))}
              {hasFilters && (
                <button onClick={clearFilters} className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800">
                  <X className="w-3.5 h-3.5" /> Clear
                </button>
              )}
              <span className="ml-auto text-[11px] text-slate-400">{rtotal.toLocaleString("en-IN")} rows</span>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="text-left border-collapse text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
                  {columns.map((c) => <th key={c.field} className={`px-3 py-2 font-semibold whitespace-nowrap ${c.kind === "money" ? "text-right" : ""}`}>{c.header}</th>)}
                </tr>
              </thead>
              <tbody>
                {rloading ? (
                  <tr><td colSpan={columns.length || 1} className="px-3 py-8 text-center text-slate-400">Loading…</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={columns.length || 1} className="px-3 py-8 text-center text-slate-400">
                    {hasFilters ? "No rows match these filters." : "No rows."}
                  </td></tr>
                ) : rows.map((r) => {
                  const legs = Number(r.__legs__ ?? 1);
                  return (
                  <tr key={r.id} className={`border-b border-slate-100 hover:bg-slate-50/60 ${legs > 1 ? "border-l-2 border-l-amber-200" : ""}`}>
                    {columns.map((c) => {
                      const v = r[c.field];
                      if (c.field === "__leg__") {
                        return <td key={c.field} className="px-3 py-1.5 text-xs whitespace-nowrap">
                          {legs > 1
                            ? <span className="inline-block px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 font-medium tabular-nums" title={`Sector ${v} of this ticket — fare and taxes divided across ${legs} legs`}>{String(v)}</span>
                            : <span className="text-slate-300">—</span>}
                        </td>;
                      }
                      const money = c.kind === "money";
                      const text = v != null && v !== "" ? (money ? fmtMoney(v) : String(v)) : null;
                      return <td key={c.field} className={`px-3 py-1.5 text-xs text-slate-700 whitespace-nowrap max-w-[240px] truncate ${money ? "text-right tabular-nums" : ""}`} title={v != null ? String(v) : undefined}>{text ?? <span className="text-slate-300">—</span>}</td>;
                    })}
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rtotal > 0 && (
            <div className="flex items-center justify-between px-3 py-2.5 border-t border-slate-100 text-xs text-slate-500">
              <span>Showing {start}–{end} of {rtotal.toLocaleString()}</span>
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

  // ── Uploads (statement-type) list ─────────────────────────────────────────
  return (
    <div>
      <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
        <div className="bg-white border border-slate-200 rounded-lg px-4 py-2">
          <span className="text-[10px] uppercase tracking-wide text-slate-400">Uploads</span>
          <span className="ml-2 text-sm font-bold text-slate-800">{batches.length}</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchBatches} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"><RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh</button>
          <button onClick={downloadTemplate} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50"><Download className="w-3.5 h-3.5" /> Template</button>
          <button onClick={() => setUploadOpen(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700"><Upload className="w-3.5 h-3.5" /> Upload XLS</button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
              <th className="text-left px-3 py-2.5 font-semibold">File</th>
              <th className="text-left px-3 py-2.5 font-semibold">Uploaded</th>
              <th className="text-right px-3 py-2.5 font-semibold">Entries</th>
              <th className="text-left px-3 py-2.5 font-semibold">Uploaded by</th>
              <th className="text-right px-3 py-2.5 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-3 py-10 text-center text-slate-400">Loading…</td></tr>
            ) : batches.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-12 text-center text-slate-400">No {title} uploads yet. <button onClick={() => setUploadOpen(true)} className="text-blue-600 hover:underline">Upload an XLS</button>.</td></tr>
            ) : batches.map((b) => (
              <tr key={b.batch_id} className="border-b border-slate-100 hover:bg-slate-50/60">
                <td className="px-3 py-2">
                  <button onClick={() => openBatch(b)} className="flex items-center gap-2 text-slate-700 hover:text-blue-700">
                    <FolderOpen className="w-4 h-4 text-slate-400" />
                    <span className="font-medium truncate max-w-[280px]" title={b.source_file ?? undefined}>{b.source_file || "upload"}</span>
                  </button>
                </td>
                <td className="px-3 py-2 text-xs text-slate-500 whitespace-nowrap">{fmtDate(b.uploaded_at)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-700">{b.row_count.toLocaleString()}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{b.created_by_name || "—"}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button onClick={() => openBatch(b)} className="text-xs font-medium text-blue-600 hover:underline mr-3">Open</button>
                  {b.has_file && <button onClick={() => previewFile(b)} className="p-1 text-slate-400 hover:text-blue-600 mr-1" title="Preview file"><Eye className="w-3.5 h-3.5" /></button>}
                  {b.has_file && <button onClick={() => downloadFile(b)} className="p-1 text-slate-400 hover:text-slate-700 mr-1" title="Download original"><Download className="w-3.5 h-3.5" /></button>}
                  <button onClick={() => setDeleteTarget(b)} className="p-1 text-slate-400 hover:text-red-600" title="Delete upload"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {uploadOpen && <UploadModal apiBase={apiBase} title={title} onClose={() => setUploadOpen(false)} onDone={() => { setUploadOpen(false); fetchBatches(); }} />}

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
            <div className="flex items-center gap-2.5 mb-2"><AlertTriangle className="w-5 h-5 text-red-500" /><h2 className="text-sm font-semibold text-slate-800">Delete this upload?</h2></div>
            <p className="text-xs text-slate-500 mb-4">This permanently removes all {deleteTarget.row_count} row{deleteTarget.row_count === 1 ? "" : "s"} from “{deleteTarget.source_file || "upload"}”. This cannot be undone.</p>
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
