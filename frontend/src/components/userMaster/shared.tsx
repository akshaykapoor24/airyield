"use client";

import { useState } from "react";
import { Plus, Search, Download, RefreshCw, X } from "lucide-react";
import api from "@/lib/api";

// ── types ────────────────────────────────────────────────────────────────
export type EntityRow = {
  id: number;
  name: string;
  code: string;
  address: string | null;
  state: string | null;
  city: string | null;
  is_active: boolean;
};

export type LoginIdRow = {
  id: number;
  login_id: string;
  airline_name: string | null;
  airline_code: string | null;
  lob: string | null;
  vendor_id: number | null;
  vendor_name: string | null;
  is_active: boolean;
};

export type SupplierOpt = { id: number; name: string };
export type BulkResult = { total: number; success: number; failed: number; errors: string[] };

export const INPUT =
  "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50";
export const LABEL = "block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1";

export function apiError(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return (d[0] as { msg?: string })?.msg ?? "Request failed.";
  return "Request failed.";
}

export async function downloadTemplate(resource: "entities" | "login-ids", filename: string) {
  const res = await api.get(`/${resource}/template`, { responseType: "blob" });
  const url = window.URL.createObjectURL(res.data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

// ── shared UI ──────────────────────────────────────────────────────────────
export function ActiveBadge({ active, onClick }: { active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border cursor-pointer transition-colors ${
        active
          ? "bg-green-50 text-green-700 border-green-200 hover:bg-green-100"
          : "bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100"
      }`}>
      <span className={`w-1.5 h-1.5 rounded-full ${active ? "bg-green-500" : "bg-gray-400"}`} />
      {active ? "Active" : "Inactive"}
    </button>
  );
}

export function UploadBox({
  resource, templateName, columns, onDone,
}: {
  resource: "entities" | "login-ids";
  templateName: string;
  columns: string;
  onDone: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<BulkResult | null>(null);
  const [error, setError] = useState("");

  const upload = async () => {
    if (!file) { setError("Please select a file."); return; }
    setUploading(true); setError(""); setResult(null);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const { data } = await api.post<BulkResult>(`/${resource}/bulk-upload`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(data);
      if (data.success > 0) onDone();
    } catch (e) {
      setError(apiError(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="bg-sky-50 border border-sky-200 rounded-lg px-3 py-2.5 flex items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold text-sky-700">Download XLS Template</p>
          <p className="text-[10px] text-sky-500 mt-0.5">Columns: {columns}</p>
        </div>
        <button type="button" onClick={() => downloadTemplate(resource, templateName)}
          className="flex items-center gap-1 text-sky-600 hover:text-sky-800 text-xs font-medium whitespace-nowrap">
          <Download className="w-3.5 h-3.5" /> Template
        </button>
      </div>

      <div>
        <label className={LABEL}>Select XLS / XLSX File</label>
        <input type="file" accept=".xls,.xlsx"
          onChange={e => { setFile(e.target.files?.[0] ?? null); setResult(null); setError(""); }}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-600 file:mr-3 file:text-xs file:font-semibold file:bg-sky-50 file:text-sky-600 file:border-0 file:rounded file:px-2 file:py-1 bg-gray-50 focus:outline-none" />
      </div>

      {error && <p className="text-[11px] text-red-500">{error}</p>}

      {result && (
        <div className={`rounded-lg border px-3 py-2.5 text-xs space-y-1 ${
          result.failed > 0 ? "bg-yellow-50 border-yellow-200" : "bg-green-50 border-green-200"
        }`}>
          <p className="font-semibold">Upload complete — {result.success} of {result.total} rows added</p>
          {result.errors.slice(0, 6).map((er, i) => <p key={i} className="text-[10px] text-red-500">{er}</p>)}
          {result.errors.length > 6 && (
            <p className="text-[10px] text-gray-400">…and {result.errors.length - 6} more</p>
          )}
        </div>
      )}

      <button type="button" onClick={upload} disabled={uploading || !file}
        className="w-full text-white rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
        style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
        {uploading ? "Uploading…" : "Upload File"}
      </button>
    </div>
  );
}

export function ModalShell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 sticky top-0 bg-white">
          <h2 className="text-sm font-bold text-gray-900">{title}</h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        <div className="px-6 py-4">{children}</div>
      </div>
    </div>
  );
}

export function Toolbar({
  label, count, search, setSearch, onAdd, onRefresh, loading,
}: {
  label: string;
  count: number;
  search: string;
  setSearch: (v: string) => void;
  onAdd: () => void;
  onRefresh: () => void;
  loading: boolean;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="relative flex-1 min-w-48">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder={`Search ${label}…`}
          className="w-full pl-8 pr-3 py-2 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-sky-400" />
      </div>
      <span className="text-[11px] text-gray-400">{count} record{count !== 1 ? "s" : ""}</span>
      <button onClick={onRefresh} disabled={loading}
        className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
        <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
      </button>
      <button onClick={onAdd}
        className="flex items-center gap-1.5 text-white px-3.5 py-2 rounded-lg text-xs font-medium" style={{ background: "#1e3a5f" }}>
        <Plus className="w-3.5 h-3.5" /> Add {label}
      </button>
    </div>
  );
}
