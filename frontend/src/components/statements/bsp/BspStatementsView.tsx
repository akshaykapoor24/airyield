"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Upload, RefreshCw, Trash2, AlertTriangle, CheckCircle2, XCircle, Clock,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import BspUploadWizard from "./BspUploadWizard";
import BspGroupDetail from "./BspGroupDetail";

type Group = {
  group_id: string;
  agent_code: string | null;
  agent_name: string | null;
  reference: string | null;
  period_from: string | null;
  period_to: string | null;
  summary_batch_id: string | null;
  summary_status: string | null;
  summary_balance: number | string | null;
  detail_batch_id: string | null;
  detail_status: string | null;
  detail_balance: number | string | null;
  detail_progress_pct: number | null;
  match_status: string;
  created_by_name: string | null;
  created_at: string;
};

function inr(v: number | string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function MatchBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; icon: React.ReactNode; label: string }> = {
    matched: { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", icon: <CheckCircle2 className="w-3 h-3" />, label: "Matched" },
    mismatch: { cls: "bg-red-50 text-red-700 border-red-200", icon: <XCircle className="w-3 h-3" />, label: "Mismatch" },
    pending: { cls: "bg-slate-100 text-slate-500 border-slate-200", icon: <Clock className="w-3 h-3" />, label: "Pending" },
  };
  const m = map[status] ?? map.pending;
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${m.cls}`}>{m.icon} {m.label}</span>;
}

function legStatus(status: string | null, pct: number | null): string {
  if (!status) return "—";
  if (status === "processing") return `processing ${pct ?? 0}%`;
  return status;
}

export default function BspStatementsView() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Group | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selected, setSelected] = useState<Group | null>(null);

  const fetchGroups = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<Group[]>("/bsp/groups");
      setGroups(data);
    } catch { setError("Failed to load BSP statements."); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { fetchGroups(); }, [fetchGroups]);

  // Refresh periodically while any leg is still parsing.
  useEffect(() => {
    const anyActive = groups.some(g =>
      ["pending", "processing"].includes(g.summary_status ?? "") ||
      ["pending", "processing"].includes(g.detail_status ?? ""));
    if (!anyActive) return;
    const t = setInterval(fetchGroups, 4000);
    return () => clearInterval(t);
  }, [groups, fetchGroups]);

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/bsp/groups/${deleteTarget.group_id}`);
      toast.success("BSP statement deleted.");
      setDeleteTarget(null);
      fetchGroups();
    } catch { toast.error("Failed to delete."); }
    finally { setDeleting(false); }
  };

  if (selected) {
    return <BspGroupDetail group={selected} onBack={() => { setSelected(null); fetchGroups(); }} />;
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between mb-4 gap-3 flex-wrap">
        <div>
          <h2 className="text-base font-bold text-slate-900">BSP settlement statements</h2>
          <p className="text-xs text-slate-400 mt-0.5">Upload a Summary then its Detailed PDF — we reconcile the two grand totals.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchGroups} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
          <button onClick={() => setWizardOpen(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
            <Upload className="w-3.5 h-3.5" /> Upload BSP
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
                <th className="text-left px-3 py-2.5 font-semibold">Agent</th>
                <th className="text-left px-3 py-2.5 font-semibold">Period</th>
                <th className="text-left px-3 py-2.5 font-semibold">Reference</th>
                <th className="text-right px-3 py-2.5 font-semibold">Summary ₹</th>
                <th className="text-right px-3 py-2.5 font-semibold">Detailed ₹</th>
                <th className="text-left px-3 py-2.5 font-semibold">Detailed</th>
                <th className="text-center px-3 py-2.5 font-semibold">Match</th>
                <th className="text-right px-3 py-2.5 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-sm text-slate-400">Loading…</td></tr>
              ) : error ? (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-sm text-red-500">{error}</td></tr>
              ) : groups.length === 0 ? (
                <tr><td colSpan={8} className="px-3 py-12 text-center text-sm text-slate-400">
                  No BSP statements yet. <button onClick={() => setWizardOpen(true)} className="text-blue-600 hover:underline">Upload your first one</button>.
                </td></tr>
              ) : groups.map((g) => (
                <tr key={g.group_id} className="border-b border-slate-100 hover:bg-slate-50/60">
                  <td className="px-3 py-2 text-slate-700">
                    <div className="font-medium">{g.agent_code || "—"}</div>
                    {g.agent_name && <div className="text-[11px] text-slate-400 truncate max-w-[160px]" title={g.agent_name}>{g.agent_name}</div>}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600 whitespace-nowrap">{g.period_from || "—"}{g.period_to ? ` → ${g.period_to}` : ""}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{g.reference || "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-700">{inr(g.summary_balance)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-700">{inr(g.detail_balance)}</td>
                  <td className="px-3 py-2 text-xs text-slate-500 capitalize">{legStatus(g.detail_status, g.detail_progress_pct)}</td>
                  <td className="px-3 py-2 text-center"><MatchBadge status={g.match_status} /></td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <button onClick={() => setSelected(g)} className="text-xs font-medium text-blue-600 hover:underline mr-3">Open</button>
                    <button onClick={() => setDeleteTarget(g)} className="p-1 text-slate-400 hover:text-red-600" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {wizardOpen && <BspUploadWizard onClose={() => setWizardOpen(false)} onDone={fetchGroups} />}

      {/* Delete confirm */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5">
            <div className="flex items-center gap-2.5 mb-2">
              <AlertTriangle className="w-5 h-5 text-red-500" />
              <h2 className="text-sm font-semibold text-slate-800">Delete this BSP statement?</h2>
            </div>
            <p className="text-xs text-slate-500 mb-4">This permanently removes the summary and detailed statements and all their rows. This cannot be undone.</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setDeleteTarget(null)} className="px-3 py-1.5 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
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
