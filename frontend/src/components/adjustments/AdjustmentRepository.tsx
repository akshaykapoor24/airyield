"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Upload, RefreshCw, Trash2, Download, X, AlertTriangle, Search,
  FileSpreadsheet, CheckCircle2, Loader2, ChevronLeft, ChevronRight,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";

const BRAND = "#1e3a5f";
const PAGE_SIZE = 50;

type Column = { header: string; field: string };
type Row = Record<string, string | number | null> & {
  id: number;
  batch_id: string;
  source_file: string | null;
  uploaded_at: string;
};
type RecordsResponse = {
  total: number;
  limit: number;
  offset: number;
  columns: Column[];
  rows: Row[];
};

export default function AdjustmentRepository({
  slug,
  title,
  blurb,
  apiBase,
}: {
  slug: string;             // "adm" | "acm" | "ra" — also the template file name
  title: string;
  blurb: string;
  apiBase?: string;         // full API base; defaults to /airline-adjustments/{slug}
}) {
  const [columns, setColumns] = useState<Column[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");

  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Row | null>(null);
  const [deleting, setDeleting] = useState(false);

  const base = apiBase ?? `/airline-adjustments/${slug}`;

  const fetchRows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<RecordsResponse>(`${base}/records`, {
        params: { limit: PAGE_SIZE, offset, search: search || undefined },
      });
      setColumns(data.columns);
      setRows(data.rows);
      setTotal(data.total);
    } catch {
      setError(`Failed to load ${title} records.`);
    } finally {
      setLoading(false);
    }
  }, [base, offset, search, title]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  // reset to first page whenever the type changes
  useEffect(() => { setOffset(0); setSearch(""); setSearchInput(""); }, [slug]);

  const applySearch = () => { setOffset(0); setSearch(searchInput.trim()); };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`${base}/records/${deleteTarget.id}`);
      toast.success("Record deleted.");
      setDeleteTarget(null);
      // if we just removed the last row on this page, step back a page
      if (rows.length === 1 && offset >= PAGE_SIZE) setOffset(offset - PAGE_SIZE);
      else await fetchRows();
    } catch {
      toast.error("Failed to delete record.");
    } finally {
      setDeleting(false);
    }
  };

  const downloadTemplate = async () => {
    try {
      const { data } = await api.get(`${base}/template`, { responseType: "blob" });
      const url = URL.createObjectURL(data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${slug}_template.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Failed to download template.");
    }
  };

  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + rows.length, total);

  return (
    <div className="w-full pb-16">
      {/* Header */}
      <div className="flex items-start justify-between mb-4 gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{title}</h1>
          {blurb && <p className="text-xs text-gray-400 mt-0.5">{blurb}</p>}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchRows} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
          <button onClick={downloadTemplate} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
            <Download className="w-3.5 h-3.5" /> Template
          </button>
          <button onClick={() => setUploadOpen(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white rounded-lg hover:opacity-90" style={{ backgroundColor: BRAND }}>
            <Upload className="w-3.5 h-3.5" /> Upload XLS
          </button>
        </div>
      </div>

      {/* Toolbar: count + search */}
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-2">
          <span className="text-[10px] uppercase tracking-wide text-gray-400">Total records</span>
          <span className="ml-2 text-sm font-bold text-gray-800">{total.toLocaleString()}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") applySearch(); }}
              placeholder="Search document / airline / agent"
              className="w-64 border border-gray-200 rounded-lg pl-8 pr-2.5 py-1.5 text-xs outline-none focus:border-[#1e3a5f] focus:ring-2 focus:ring-[#1e3a5f]/10"
            />
          </div>
          <button onClick={applySearch} className="px-3 py-1.5 text-xs font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50">Search</button>
          {search && (
            <button onClick={() => { setSearchInput(""); setSearch(""); setOffset(0); }} className="text-xs text-gray-400 hover:text-gray-600">Clear</button>
          )}
        </div>
      </div>

      {/* Records table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="text-left border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-[11px] uppercase tracking-wide text-gray-400">
                <th className="px-3 py-2.5 font-semibold sticky left-0 bg-gray-50 z-10 whitespace-nowrap">Source</th>
                {columns.map(c => (
                  <th key={c.field} className="px-3 py-2.5 font-semibold whitespace-nowrap">{c.header}</th>
                ))}
                <th className="px-3 py-2.5 font-semibold text-right whitespace-nowrap">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={columns.length + 2} className="px-3 py-10 text-center text-sm text-gray-400">Loading…</td></tr>
              ) : error ? (
                <tr><td colSpan={columns.length + 2} className="px-3 py-10 text-center text-sm text-red-500">{error}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={columns.length + 2} className="px-3 py-10 text-center text-sm text-gray-400">
                  {search ? "No records match your search." : (
                    <>No {title} records yet. <button onClick={() => setUploadOpen(true)} className="text-blue-600 hover:underline">Upload an XLS</button>.</>
                  )}
                </td></tr>
              ) : rows.map(r => (
                <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50/60">
                  <td className="px-3 py-2 sticky left-0 bg-white z-10 whitespace-nowrap">
                    <div className="text-[11px] font-medium text-gray-700 truncate max-w-[180px]" title={r.source_file ?? undefined}>{r.source_file || "—"}</div>
                    <div className="text-[10px] text-gray-400">{new Date(r.uploaded_at).toLocaleDateString()}</div>
                  </td>
                  {columns.map(c => {
                    const v = r[c.field];
                    return (
                      <td key={c.field} className="px-3 py-2 text-xs text-gray-700 whitespace-nowrap max-w-[240px] truncate" title={v != null ? String(v) : undefined}>
                        {v != null && v !== "" ? String(v) : <span className="text-gray-300">—</span>}
                      </td>
                    );
                  })}
                  <td className="px-3 py-2 text-right whitespace-nowrap sticky right-0 bg-white">
                    <button onClick={() => setDeleteTarget(r)} className="p-1.5 text-gray-400 hover:text-red-600" title="Delete record"><Trash2 className="w-3.5 h-3.5" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > 0 && (
          <div className="flex items-center justify-between px-3 py-2.5 border-t border-gray-100 text-xs text-gray-500">
            <span>Showing {pageStart}–{pageEnd} of {total.toLocaleString()}</span>
            <div className="flex items-center gap-1">
              <button
                disabled={offset === 0 || loading}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
              ><ChevronLeft className="w-3.5 h-3.5" /> Prev</button>
              <button
                disabled={offset + PAGE_SIZE >= total || loading}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
              >Next <ChevronRight className="w-3.5 h-3.5" /></button>
            </div>
          </div>
        )}
      </div>

      {uploadOpen && (
        <UploadModal
          base={base}
          title={title}
          onClose={() => setUploadOpen(false)}
          onDone={() => { setUploadOpen(false); setOffset(0); fetchRows(); }}
        />
      )}

      {/* Delete confirm */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
            <div className="flex items-center gap-2.5 mb-2">
              <AlertTriangle className="w-5 h-5 text-red-500" />
              <h2 className="text-sm font-semibold text-gray-800">Delete this {title} record?</h2>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              This permanently removes the row{deleteTarget.document_number ? ` (${deleteTarget.document_number})` : ""}. This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeleteTarget(null)} className="px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">Cancel</button>
              <button onClick={confirmDelete} disabled={deleting} className="px-4 py-1.5 text-xs font-semibold text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50">
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function UploadModal({
  base, title, onClose, onDone,
}: {
  base: string; title: string; onClose: () => void; onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const sizeLabel = useMemo(() => {
    if (!file) return "";
    const mb = file.size / (1024 * 1024);
    return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`;
  }, [file]);

  const pickFile = (f: File | null) => {
    if (!f) return;
    const ok = /\.(xlsx|xls|csv)$/i.test(f.name);
    if (!ok) { toast.error("Choose an .xlsx, .xls or .csv file."); return; }
    setFile(f);
  };

  const submit = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post<{ inserted: number; matched_columns: number }>(
        `${base}/upload`, fd
      );
      toast.success(`Imported ${data.inserted} ${title} row${data.inserted === 1 ? "" : "s"} (${data.matched_columns} columns matched).`);
      onDone();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : "Failed to import the file.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-800">Upload {title} XLS</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-5 py-4">
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0] ?? null); }}
            onClick={() => inputRef.current?.click()}
            className={`cursor-pointer flex flex-col items-center justify-center rounded-xl border-2 border-dashed transition-colors p-8 text-center
              ${dragging ? "border-[#1e3a5f] bg-[#1e3a5f]/5" : file ? "border-emerald-200 bg-emerald-50/30" : "border-gray-200 bg-gray-50/50 hover:border-gray-300 hover:bg-gray-50"}`}
          >
            {file ? (
              <div className="w-full max-w-sm flex items-center gap-3 rounded-lg border border-emerald-200 bg-white p-3 shadow-sm">
                <div className="w-9 h-9 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0">
                  <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
                </div>
                <div className="min-w-0 flex-1 text-left">
                  <p className="text-xs font-semibold text-gray-800 truncate" title={file.name}>{file.name}</p>
                  <p className="text-[11px] text-gray-500">{sizeLabel}</p>
                </div>
                <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0" />
                <button onClick={e => { e.stopPropagation(); setFile(null); }} className="p-1 rounded-md text-gray-400 hover:text-red-500 shrink-0"><X className="w-4 h-4" /></button>
              </div>
            ) : (
              <>
                <div className="w-12 h-12 rounded-full flex items-center justify-center mb-3" style={{ backgroundColor: `${BRAND}14` }}>
                  <Upload className="w-6 h-6" style={{ color: BRAND }} />
                </div>
                <p className="text-sm font-medium text-gray-700">Drop your {title} export here</p>
                <p className="text-xs text-gray-400 mt-0.5">or click to browse · .xlsx, .xls, .csv</p>
              </>
            )}
            <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden" onChange={e => pickFile(e.target.files?.[0] ?? null)} />
          </div>
          <p className="text-[11px] text-gray-400 mt-3 leading-relaxed">
            Columns are matched by their header name — the file should use the standard {title} export headers.
            Unrecognised columns are ignored.
          </p>
        </div>

        <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-gray-100">
          <button onClick={onClose} className="px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">Cancel</button>
          <button onClick={submit} disabled={!file || uploading}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white rounded-lg hover:opacity-90 disabled:bg-gray-200 disabled:text-gray-400"
            style={!file || uploading ? undefined : { backgroundColor: BRAND }}>
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            {uploading ? "Importing…" : "Import"}
          </button>
        </div>
      </div>
    </div>
  );
}
