"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Upload, RefreshCw, Trash2, Download, Eye, X, AlertTriangle, ArrowLeft,
  FileSpreadsheet, CheckCircle2, Loader2, ChevronLeft, ChevronRight, FolderOpen,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";

const PAGE = 50;

type Batch = {
  batch_id: string;
  source_file: string | null;
  uploaded_at: string;
  row_count: number;
  has_file: boolean;
  created_by_name: string | null;
};
type Column = { header: string; field: string };
type Row = Record<string, string | number | null> & { id: number };

function fmtDate(s: string): string {
  try { return new Date(s).toLocaleString(); } catch { return s; }
}
function errMsg(e: unknown, fallback: string): string {
  const m = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return typeof m === "string" ? m : fallback;
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
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const { data } = await api.post<{ inserted: number; matched_columns: number }>(`${apiBase}/upload`, fd);
      toast.success(`Imported ${data.inserted} ${title} row${data.inserted === 1 ? "" : "s"}.`);
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

  const fetchBatches = useCallback(async () => {
    setLoading(true);
    try { const { data } = await api.get<Batch[]>(`${apiBase}/batches`); setBatches(data); }
    catch { toast.error(`Failed to load ${title} uploads.`); }
    finally { setLoading(false); }
  }, [apiBase, title]);

  useEffect(() => { setSelected(null); fetchBatches(); }, [fetchBatches, slug]);

  const loadRecords = useCallback(async (batchId: string, offset: number) => {
    setRloading(true);
    try {
      const { data } = await api.get<{ total: number; columns: Column[]; rows: Row[] }>(
        `${apiBase}/records`, { params: { batch_id: batchId, offset, limit: PAGE } });
      setColumns(data.columns); setRows(data.rows); setRtotal(data.total); setRoffset(offset);
    } catch { toast.error("Failed to load rows."); }
    finally { setRloading(false); }
  }, [apiBase]);

  const openBatch = (b: Batch) => { setSelected(b); loadRecords(b.batch_id, 0); };

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
          <button onClick={() => setSelected(null)} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-700"><ArrowLeft className="w-3.5 h-3.5" /> Back to uploads</button>
          <span className="text-slate-300">|</span>
          <h3 className="text-sm font-semibold text-slate-800 truncate max-w-[320px]" title={selected.source_file ?? undefined}>{title} · {selected.source_file || "upload"}</h3>
          <span className="text-[11px] text-slate-400">· {selected.row_count} entries · {fmtDate(selected.uploaded_at)}</span>
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
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="text-left border-collapse text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
                  {columns.map((c) => <th key={c.field} className="px-3 py-2 font-semibold whitespace-nowrap">{c.header}</th>)}
                </tr>
              </thead>
              <tbody>
                {rloading ? (
                  <tr><td colSpan={columns.length || 1} className="px-3 py-8 text-center text-slate-400">Loading…</td></tr>
                ) : rows.length === 0 ? (
                  <tr><td colSpan={columns.length || 1} className="px-3 py-8 text-center text-slate-400">No rows.</td></tr>
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
