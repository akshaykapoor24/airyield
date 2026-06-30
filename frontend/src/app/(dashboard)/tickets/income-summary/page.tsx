"use client";

import { useEffect, useState } from "react";
import {
  RefreshCw, TrendingUp, Building2, Calendar, Hash,
  AlertCircle, X, Trash2, Eye, FileText, FileSpreadsheet,
} from "lucide-react";
import api from "@/lib/api";

// Must stay byte-identical to the backend INCENTIVE_TYPE_KEYS and to
// INCENTIVE_TYPE_COLS on the statement detail page.
const INCENTIVE_TYPE_COLS = [
  { key: "PLB",                    label: "PLB"        },
  { key: "Super PLB",              label: "Super PLB"  },
  { key: "Transaction Fee",        label: "Trans. Fee" },
  { key: "Deposit Incentive (DI)", label: "DI"         },
  { key: "Marketing Fund",         label: "Mktg Fund"  },
  { key: "Ancillary",              label: "Ancillary"  },
  { key: "Frontend",               label: "Frontend"   },
  { key: "Backend",                label: "Backend"    },
  { key: "Cashback",               label: "Cashback"   },
  { key: "Segment Incentive",      label: "Seg. Inc."  },
  { key: "Push Action",            label: "Push Act."  },
] as const;

type IncomeSummary = {
  id:               number;
  batch_id:         string;
  name:             string;
  statement_name:   string | null;
  statement_type:   string;
  agency:           string;
  valid_from:       string;
  valid_to:         string;
  ticket_count:     number;
  incentive_totals: Record<string, number> | null;
  total_income:     number;
  iata_commission_total: number;
  created_at:       string;
  updated_at:       string;
};

type ViewTicket = {
  id:                   number;
  ticket_number:        string | null;
  last_name:            string | null;
  first_name:           string | null;
  pax_name:             string | null;
  airline_name:         string | null;
  airlines_code:        string | null;
  sector:               string | null;
  sell_fare:            number | null;
  ticket_status:        string;
  iata_commission:      number | null;
  calculated_incentive: number | null;
};

function formatINR(n: number | null | undefined) {
  if (n == null) return "—";
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function formatDate(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export default function IncomeSummaryTabPage() {
  const [rows,    setRows]    = useState<IncomeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const [filterAgency, setFilterAgency] = useState("");
  const [filterFrom,   setFilterFrom]   = useState("");
  const [filterTo,     setFilterTo]     = useState("");

  const [deleteTarget, setDeleteTarget] = useState<IncomeSummary | null>(null);
  const [deleting,     setDeleting]     = useState(false);

  // View tickets modal
  const [viewTarget,  setViewTarget]  = useState<IncomeSummary | null>(null);
  const [viewTickets, setViewTickets] = useState<ViewTicket[]>([]);
  const [viewLoading, setViewLoading] = useState(false);
  const [viewError,   setViewError]   = useState<string | null>(null);

  const fetchRows = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<IncomeSummary[]>("/tickets/income-summaries");
      setRows(data);
    } catch {
      setError("Failed to load income summaries. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchRows(); }, []);

  // Load the tickets of a summary's statement when the View modal opens
  useEffect(() => {
    if (!viewTarget) return;
    let cancelled = false;
    (async () => {
      setViewLoading(true);
      setViewError(null);
      setViewTickets([]);
      try {
        const { data } = await api.get<ViewTicket[]>("/tickets/uploads", {
          params: { batch_id: viewTarget.batch_id, limit: 2000 },
        });
        if (!cancelled) setViewTickets(data);
      } catch {
        if (!cancelled) setViewError("Failed to load tickets for this income summary.");
      } finally {
        if (!cancelled) setViewLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [viewTarget]);

  const viewPassenger = (t: ViewTicket) =>
    t.pax_name || [t.first_name, t.last_name].filter(Boolean).join(" ") || "—";
  const viewTotal = viewTickets.reduce((s, t) => s + (t.calculated_incentive ?? 0), 0);
  const viewIataTotal = viewTickets.reduce((s, t) => s + (t.iata_commission ?? 0), 0);

  const downloadIncome = async (summaryId: number, fmt: "pdf" | "xlsx", name: string) => {
    try {
      const res = await api.get(`/tickets/income-summaries/${summaryId}/${fmt}`, { responseType: "blob" });
      const url = window.URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${name || "income-statement"}.${fmt}`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch { alert("Download failed."); }
  };

  const allAgencies = Array.from(new Set(rows.map(r => r.agency))).sort();

  // Client-side filtering (mirrors the Ticket Repository page).
  const filtered = rows.filter(r => {
    if (filterAgency && r.agency !== filterAgency) return false;
    if (filterFrom && r.valid_to   < filterFrom)   return false;   // ends before range start
    if (filterTo   && r.valid_from > filterTo)     return false;   // starts after range end
    return true;
  });

  const hasFilter = filterAgency || filterFrom || filterTo;

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/tickets/income-summaries/${deleteTarget.id}`);
      setRows(prev => prev.filter(r => r.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch {
      setError("Failed to delete income summary.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Income Statement</h1>
          <p className="text-xs text-gray-500 mt-0.5">Saved per-statement income summaries</p>
        </div>
        <button
          onClick={fetchRows}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* filter bar */}
      {!loading && !error && rows.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={filterAgency} onChange={e => setFilterAgency(e.target.value)}
            className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white"
          >
            <option value="">All Agencies</option>
            {allAgencies.map(a => <option key={a} value={a}>{a}</option>)}
          </select>

          <input type="date" value={filterFrom} onChange={e => setFilterFrom(e.target.value)}
            title="Valid from" className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
          <span className="text-xs text-gray-400">–</span>
          <input type="date" value={filterTo} onChange={e => setFilterTo(e.target.value)}
            title="Valid to" className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />

          {hasFilter && (
            <button
              onClick={() => { setFilterAgency(""); setFilterFrom(""); setFilterTo(""); }}
              className="p-2 hover:bg-gray-100 rounded-lg text-gray-400" title="Clear filters"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* error */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* loading */}
      {loading && (
        <div className="flex items-center justify-center py-24">
          <div className="text-center space-y-3">
            <RefreshCw className="w-7 h-7 text-blue-400 animate-spin mx-auto" />
            <p className="text-sm text-gray-500">Loading income summaries…</p>
          </div>
        </div>
      )}

      {/* empty state */}
      {!loading && !error && rows.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
            <TrendingUp className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">No income summaries yet</p>
          <p className="text-xs text-gray-400 mt-1">
            Open a ticket statement, run the calculation, then click “Save Income Statement”.
          </p>
        </div>
      )}

      {/* table */}
      {!loading && !error && rows.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
              {filtered.length === rows.length
                ? `${rows.length} Summar${rows.length !== 1 ? "ies" : "y"}`
                : `${filtered.length} of ${rows.length} Summaries`}
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Income Statement</th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Statement</th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">
                    <span className="flex items-center gap-1"><Building2 className="w-3.5 h-3.5" /> Agency</span>
                  </th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">
                    <span className="flex items-center gap-1"><Calendar className="w-3.5 h-3.5" /> Valid Period</span>
                  </th>
                  <th className="px-4 py-2 text-right text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">
                    <span className="flex items-center gap-1 justify-end"><Hash className="w-3.5 h-3.5" /> Tickets</span>
                  </th>
                  {INCENTIVE_TYPE_COLS.map(c => (
                    <th key={c.key} className="px-3 py-2 text-right text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">{c.label}</th>
                  ))}
                  <th className="px-3 py-2 text-right text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">IATA Comm</th>
                  <th className="px-4 py-2 text-right text-[11px] font-semibold text-white/90 uppercase tracking-wide whitespace-nowrap">Total Income</th>
                  <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Saved</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={INCENTIVE_TYPE_COLS.length + 9} className="px-4 py-10 text-center text-xs text-gray-400">
                      No income summaries match the current filters.
                    </td>
                  </tr>
                ) : filtered.map(r => (
                  <tr key={r.id} className="hover:bg-blue-50/40 transition-colors group">
                    <td className="px-4 py-2">
                      <p className="text-sm font-semibold text-gray-800 whitespace-nowrap">{r.name}</p>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-600 whitespace-nowrap">
                      {r.statement_name ?? `${r.statement_type} · ${r.agency}`}
                    </td>
                    <td className="px-4 py-2">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-50 border border-indigo-100 text-xs font-medium text-indigo-700 whitespace-nowrap">
                        <Building2 className="w-3 h-3" />
                        {r.agency}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <div className="text-xs text-gray-700 whitespace-nowrap">
                        <span className="font-medium">{formatDate(r.valid_from)}</span>
                        <span className="text-gray-400 mx-1.5">→</span>
                        <span className="font-medium">{formatDate(r.valid_to)}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-[#1e3a5f]/10 text-[#1e3a5f] text-xs font-semibold">
                        {r.ticket_count.toLocaleString()}
                      </span>
                    </td>
                    {INCENTIVE_TYPE_COLS.map(c => {
                      const v = r.incentive_totals?.[c.key] ?? 0;
                      return (
                        <td key={c.key} className="px-3 py-2 text-right text-xs font-mono whitespace-nowrap">
                          {v ? <span className="text-amber-600 font-semibold">{formatINR(v)}</span>
                             : <span className="text-gray-300">—</span>}
                        </td>
                      );
                    })}
                    <td className="px-3 py-2 text-right text-xs font-mono whitespace-nowrap">
                      {r.iata_commission_total ? <span className="text-teal-600 font-semibold">{formatINR(r.iata_commission_total)}</span>
                                               : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-2 text-right text-xs font-mono font-bold text-emerald-700 whitespace-nowrap">
                      {formatINR(r.total_income)}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">{formatDate(r.created_at)}</td>
                    <td className="px-4 py-2 text-right whitespace-nowrap">
                      <button
                        onClick={() => setViewTarget(r)}
                        className="p-1.5 rounded-lg text-gray-400 hover:text-[#1e3a5f] hover:bg-blue-50 transition-colors"
                        title="View tickets in this income summary"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setDeleteTarget(r)}
                        className="p-1.5 rounded-lg text-gray-300 hover:text-red-600 hover:bg-red-50 transition-colors"
                        title="Delete income summary"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* view tickets modal */}
      {viewTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col">
            {/* Header */}
            <div className="flex items-start justify-between px-6 py-4 border-b border-gray-100">
              <div>
                <h2 className="text-sm font-bold text-gray-900">{viewTarget.name}</h2>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  {viewTarget.statement_name ?? `${viewTarget.statement_type} · ${viewTarget.agency}`}
                  <span className="mx-1.5 text-gray-300">·</span>
                  {viewTarget.agency}
                  <span className="mx-1.5 text-gray-300">·</span>
                  {formatDate(viewTarget.valid_from)} → {formatDate(viewTarget.valid_to)}
                </p>
              </div>
              <button onClick={() => setViewTarget(null)} className="p-1 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>

            {/* Body */}
            <div className="overflow-auto flex-1 px-6 py-4">
              {viewLoading ? (
                <div className="flex justify-center py-12"><RefreshCw className="w-5 h-5 text-blue-400 animate-spin" /></div>
              ) : viewError ? (
                <p className="text-xs text-red-600 text-center py-12">{viewError}</p>
              ) : viewTickets.length === 0 ? (
                <p className="text-xs text-gray-400 text-center py-12">No tickets in this statement.</p>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-gray-500 border-b border-gray-200">
                      <th className="px-2 py-2 font-semibold">Ticket #</th>
                      <th className="px-2 py-2 font-semibold">Passenger</th>
                      <th className="px-2 py-2 font-semibold">Airline</th>
                      <th className="px-2 py-2 font-semibold">Sector</th>
                      <th className="px-2 py-2 font-semibold text-right">Sell Fare</th>
                      <th className="px-2 py-2 font-semibold">Status</th>
                      <th className="px-2 py-2 font-semibold text-right">IATA Comm</th>
                      <th className="px-2 py-2 font-semibold text-right">Income</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {viewTickets.map(t => (
                      <tr key={t.id} className="text-gray-700">
                        <td className="px-2 py-1.5 whitespace-nowrap">{t.ticket_number ?? "—"}</td>
                        <td className="px-2 py-1.5 whitespace-nowrap">{viewPassenger(t)}</td>
                        <td className="px-2 py-1.5 whitespace-nowrap">{t.airline_name ?? t.airlines_code ?? "—"}</td>
                        <td className="px-2 py-1.5 whitespace-nowrap">{t.sector ?? "—"}</td>
                        <td className="px-2 py-1.5 text-right font-mono whitespace-nowrap">{formatINR(t.sell_fare)}</td>
                        <td className="px-2 py-1.5">
                          <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-600 capitalize">
                            {t.ticket_status}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono whitespace-nowrap">
                          {t.iata_commission != null
                            ? <span className="text-teal-600 font-semibold">{formatINR(t.iata_commission)}</span>
                            : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono font-semibold text-emerald-700 whitespace-nowrap">{formatINR(t.calculated_incentive)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 border-gray-300 font-bold text-gray-900">
                      <td className="px-2 py-2" colSpan={6}>Total ({viewTickets.length} tickets)</td>
                      <td className="px-2 py-2 text-right font-mono text-teal-600 whitespace-nowrap">{formatINR(viewIataTotal)}</td>
                      <td className="px-2 py-2 text-right font-mono text-emerald-700 whitespace-nowrap">{formatINR(viewTotal)}</td>
                    </tr>
                  </tfoot>
                </table>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-3 border-t border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-gray-400">Download:</span>
                <button
                  onClick={() => downloadIncome(viewTarget.id, "pdf", viewTarget.name)}
                  className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-white bg-[#1e3a5f] rounded-lg hover:bg-[#16304f]"
                >
                  <FileText className="w-3.5 h-3.5" /> PDF
                </button>
                <button
                  onClick={() => downloadIncome(viewTarget.id, "xlsx", viewTarget.name)}
                  className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700"
                >
                  <FileSpreadsheet className="w-3.5 h-3.5" /> XLS
                </button>
              </div>
              <button
                onClick={() => setViewTarget(null)}
                className="px-3 py-2 text-xs text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* delete confirmation */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
            <div className="px-6 py-4 border-b border-gray-100">
              <h2 className="text-sm font-bold text-gray-900">Delete Income Statement</h2>
            </div>
            <div className="px-6 py-4">
              <p className="text-xs text-gray-600">
                Delete <span className="font-semibold">{deleteTarget.name}</span>? This cannot be undone.
              </p>
            </div>
            <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-end gap-2">
              <button
                onClick={() => setDeleteTarget(null)}
                className="px-4 py-2 border border-gray-200 text-xs rounded-lg text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deleting}
                className="flex items-center gap-1.5 px-4 py-2 bg-red-600 text-white rounded-lg text-xs font-semibold hover:bg-red-700 disabled:opacity-60"
              >
                {deleting ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Deleting…</> : <><Trash2 className="w-3.5 h-3.5" /> Delete</>}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
