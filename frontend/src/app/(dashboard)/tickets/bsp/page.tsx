"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Upload, RefreshCw, Trash2, ChevronRight, FileText, AlertTriangle } from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";

type BspStatement = {
  batch_id: string;
  statement_name: string | null;
  airline_code: string | null;
  airline_name: string | null;
  period_from: string | null;
  period_to: string | null;
  file_name: string | null;
  row_count: number;
  status: string;
  progress_pct: number;
  created_by_name: string | null;
  created_at: string;
};

function statusBadge(s: string): string {
  switch (s) {
    case "completed":  return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "processing": return "bg-blue-50 text-blue-700 border-blue-200";
    case "failed":     return "bg-red-50 text-red-700 border-red-200";
    default:           return "bg-gray-100 text-gray-500 border-gray-200"; // pending
  }
}

export default function BspRepositoryPage() {
  const [rows, setRows] = useState<BspStatement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BspStatement | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchRows = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<BspStatement[]>("/bsp/statements");
      setRows(data);
    } catch {
      setError("Failed to load BSP statements.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/bsp/statements/${deleteTarget.batch_id}`);
      toast.success("BSP statement deleted.");
      setDeleteTarget(null);
      await fetchRows();
    } catch {
      toast.error("Failed to delete statement.");
    } finally {
      setDeleting(false);
    }
  };

  const fmtDate = (d: string | null) => (d ? d : "—");

  return (
    <div className="w-full pb-16">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">BSP Repository</h1>
          <p className="text-xs text-gray-400 mt-0.5">Uploaded BSP settlement statements. Open one to review its rows.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchRows} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
          <Link href="/tickets/bsp/upload" className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
            <Upload className="w-3.5 h-3.5" /> Upload BSP
          </Link>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-[11px] uppercase tracking-wide text-gray-400">
                <th className="px-3 py-2.5 font-semibold">Statement</th>
                <th className="px-3 py-2.5 font-semibold">Airline</th>
                <th className="px-3 py-2.5 font-semibold">File Name</th>
                <th className="px-3 py-2.5 font-semibold">Status</th>
                <th className="px-3 py-2.5 font-semibold">Period</th>
                <th className="px-3 py-2.5 font-semibold text-right">Rows</th>
                <th className="px-3 py-2.5 font-semibold">Created by</th>
                <th className="px-3 py-2.5 font-semibold">Uploaded</th>
                <th className="px-3 py-2.5 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={9} className="px-3 py-10 text-center text-sm text-gray-400">Loading…</td></tr>
              ) : error ? (
                <tr><td colSpan={9} className="px-3 py-10 text-center text-sm text-red-500">{error}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={9} className="px-3 py-10 text-center text-sm text-gray-400">
                  No BSP statements yet. <Link href="/tickets/bsp/upload" className="text-blue-600 hover:underline">Upload one</Link>.
                </td></tr>
              ) : rows.map(r => (
                <tr key={r.batch_id} className="border-b border-gray-100 hover:bg-gray-50/60">
                  <td className="px-3 py-2.5">
                    <Link href={`/tickets/bsp/${r.batch_id}`} className="flex items-center gap-2 group">
                      <FileText className="w-4 h-4 text-gray-300 group-hover:text-blue-500" />
                      <span className="text-xs font-medium text-gray-800 group-hover:text-blue-600 truncate max-w-[240px]" title={r.statement_name ?? undefined}>
                        {r.statement_name || r.file_name || r.batch_id.slice(0, 8)}
                      </span>
                    </Link>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-600">{r.airline_name || r.airline_code || "—"}</td>
                  <td className="px-3 py-2.5">
                    <span className="text-xs text-gray-700 font-mono truncate inline-block max-w-[260px] align-middle" title={r.file_name ?? undefined}>
                      {r.file_name || "—"}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border capitalize ${statusBadge(r.status)}`}>
                      {r.status === "processing" ? `processing ${r.progress_pct}%` : r.status}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-600">{fmtDate(r.period_from)} → {fmtDate(r.period_to)}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-800 text-right">{r.row_count}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-600">{r.created_by_name || "—"}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-500">{new Date(r.created_at).toLocaleDateString()}</td>
                  <td className="px-3 py-2.5 text-right whitespace-nowrap">
                    <Link href={`/tickets/bsp/${r.batch_id}`} className="inline-flex p-1.5 text-gray-400 hover:text-blue-600" title="Open"><ChevronRight className="w-3.5 h-3.5" /></Link>
                    <button onClick={() => setDeleteTarget(r)} className="p-1.5 text-gray-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
            <div className="flex items-center gap-2.5 mb-2">
              <AlertTriangle className="w-5 h-5 text-red-500" />
              <h2 className="text-sm font-semibold text-gray-800">Delete BSP statement?</h2>
            </div>
            <p className="text-xs text-gray-500 mb-4">
              This permanently removes the statement and its {deleteTarget.row_count} row{deleteTarget.row_count === 1 ? "" : "s"}. This cannot be undone.
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
