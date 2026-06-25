"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Upload, RefreshCw, FileSpreadsheet, ChevronRight,
  Building2, Calendar, Hash, AlertCircle, Search, X,
  TrendingUp, Download,
} from "lucide-react";
import api from "@/lib/api";

type StatementType = "B2B" | "AIRLINE";

type TicketStatement = {
  batch_id:        string;
  statement_name:  string | null;
  statement_type:  StatementType;
  agency:          string;
  valid_from:      string;
  valid_to:        string;
  file_name:       string;
  ticket_count:    number;
  created_by_name: string | null;
  created_at:      string;
};

type SummaryTicket = {
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

function formatDateTime(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function TypeBadge({ type }: { type: StatementType }) {
  return type === "AIRLINE"
    ? <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 text-blue-700 uppercase tracking-wide">Airline</span>
    : <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-700 uppercase tracking-wide">B2B</span>;
}

export default function TicketRepositoryPage() {
  const router = useRouter();
  const [statements, setStatements] = useState<TicketStatement[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [filterName,   setFilterName]   = useState("");
  const [filterAgency, setFilterAgency] = useState("");
  const [filterType,   setFilterType]   = useState<"" | StatementType>("");
  const [filterFrom,   setFilterFrom]   = useState("");
  const [filterTo,     setFilterTo]     = useState("");

  // Income summary popup
  const [summaryStmt,    setSummaryStmt]    = useState<TicketStatement | null>(null);
  const [summaryRows,    setSummaryRows]    = useState<SummaryTicket[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError,   setSummaryError]   = useState<string | null>(null);
  const [downloading,    setDownloading]    = useState(false);
  const downloadRef = useRef<HTMLAnchorElement>(null);

  const fetchStatements = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<TicketStatement[]>("/tickets/statements");
      setStatements(data);
    } catch {
      setError("Failed to load ticket statements. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStatements(); }, []);

  // Load per-ticket income when the popup opens
  useEffect(() => {
    if (!summaryStmt) return;
    let cancelled = false;
    (async () => {
      setSummaryLoading(true);
      setSummaryError(null);
      setSummaryRows([]);
      try {
        const { data } = await api.get<SummaryTicket[]>(
          `/tickets/uploads?batch_id=${summaryStmt.batch_id}&limit=2000`
        );
        if (!cancelled) setSummaryRows(data);
      } catch {
        if (!cancelled) setSummaryError("Failed to load income summary.");
      } finally {
        if (!cancelled) setSummaryLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [summaryStmt]);

  const handleDownloadPdf = async () => {
    if (!summaryStmt) return;
    setDownloading(true);
    try {
      const resp = await api.get(
        `/tickets/statements/${summaryStmt.batch_id}/income-summary.pdf`,
        { responseType: "blob" }
      );
      const url = URL.createObjectURL(resp.data as Blob);
      const a   = downloadRef.current!;
      a.href     = url;
      a.download = `income-summary-${summaryStmt.agency}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setSummaryError("Failed to download PDF.");
    } finally {
      setDownloading(false);
    }
  };

  const summaryTotal = summaryRows.reduce((s, t) => s + (t.calculated_incentive ?? 0), 0);
  const summaryPassenger = (t: SummaryTicket) =>
    t.pax_name || [t.first_name, t.last_name].filter(Boolean).join(" ") || "—";

  const allAgencies = Array.from(new Set(statements.map(s => s.agency))).sort();

  const filtered = statements.filter(s => {
    if (filterName && !(s.statement_name ?? "").toLowerCase().includes(filterName.toLowerCase())) return false;
    if (filterAgency && s.agency !== filterAgency) return false;
    if (filterType && s.statement_type !== filterType) return false;
    if (filterFrom && s.valid_to < filterFrom) return false;
    if (filterTo   && s.valid_from > filterTo)   return false;
    return true;
  });

  const hasFilter = filterName || filterAgency || filterType || filterFrom || filterTo;

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Ticket Repository</h1>
          <p className="text-xs text-gray-500 mt-0.5">All uploaded ticket statements for your organisation</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchStatements}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <Link
            href="/tickets/upload"
            className="flex items-center gap-1.5 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f]"
          >
            <Upload className="w-3.5 h-3.5" />
            Upload Statement
          </Link>
        </div>
      </div>

      {/* filter bar */}
      {!loading && !error && statements.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
            <input
              type="text" placeholder="Search statement name…"
              value={filterName} onChange={e => setFilterName(e.target.value)}
              className="pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-52"
            />
          </div>

          {/* Type filter */}
          <select
            value={filterType} onChange={e => setFilterType(e.target.value as "" | StatementType)}
            className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white"
          >
            <option value="">All Types</option>
            <option value="B2B">B2B</option>
            <option value="AIRLINE">Airline</option>
          </select>

          {/* Agency filter — derived from loaded data */}
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
              onClick={() => { setFilterName(""); setFilterAgency(""); setFilterType(""); setFilterFrom(""); setFilterTo(""); }}
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
            <p className="text-sm text-gray-500">Loading statements…</p>
          </div>
        </div>
      )}

      {/* empty state */}
      {!loading && !error && statements.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
            <FileSpreadsheet className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">No ticket statements yet</p>
          <p className="text-xs text-gray-400 mt-1 mb-5">Upload your first supplier statement to get started</p>
          <Link
            href="/tickets/upload"
            className="flex items-center gap-2 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-medium hover:bg-[#16304f]"
          >
            <Upload className="w-4 h-4" /> Upload Statement
          </Link>
        </div>
      )}

      {/* statements table */}
      {!loading && !error && statements.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {/* summary bar */}
          <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
              {filtered.length === statements.length
                ? `${statements.length} Statement${statements.length !== 1 ? "s" : ""}`
                : `${filtered.length} of ${statements.length} Statements`}
            </p>
            <p className="text-xs text-gray-400">Click a row to view tickets</p>
          </div>

          <table className="w-full">
            <thead>
              <tr style={{background:"#1e3a5f"}}>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Type</th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Statement Name</th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">
                  <span className="flex items-center gap-1"><Building2 className="w-3.5 h-3.5" /> Agency</span>
                </th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">
                  <span className="flex items-center gap-1"><Calendar className="w-3.5 h-3.5" /> Valid Period</span>
                </th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">File</th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">
                  <span className="flex items-center gap-1"><Hash className="w-3.5 h-3.5" /> Tickets</span>
                </th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">
                  <span className="flex items-center gap-1"><TrendingUp className="w-3.5 h-3.5" /> Income Summary</span>
                </th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Uploaded By</th>
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Uploaded</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-10 text-center text-xs text-gray-400">
                    No statements match the current filters.
                  </td>
                </tr>
              ) : filtered.map(stmt => (
                <tr
                  key={stmt.batch_id}
                  onClick={() => router.push(`/tickets/${stmt.batch_id}`)}
                  className="hover:bg-blue-50/40 cursor-pointer transition-colors group"
                >
                  {/* Type badge */}
                  <td className="px-4 py-2">
                    <TypeBadge type={stmt.statement_type ?? "B2B"} />
                  </td>

                  {/* Statement Name */}
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                        <FileSpreadsheet className="w-4 h-4 text-blue-500" />
                      </div>
                      <p className="text-sm font-semibold text-gray-800 group-hover:text-[#1e3a5f]">
                        {stmt.statement_name ?? `${stmt.statement_type} · ${stmt.agency}`}
                      </p>
                    </div>
                  </td>

                  {/* Agency */}
                  <td className="px-4 py-2">
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-50 border border-indigo-100 text-xs font-medium text-indigo-700">
                      <Building2 className="w-3 h-3" />
                      {stmt.agency}
                    </span>
                  </td>

                  {/* Valid Period */}
                  <td className="px-4 py-2">
                    <div className="text-xs text-gray-700">
                      <span className="font-medium">{formatDate(stmt.valid_from)}</span>
                      <span className="text-gray-400 mx-1.5">→</span>
                      <span className="font-medium">{formatDate(stmt.valid_to)}</span>
                    </div>
                  </td>

                  {/* File */}
                  <td className="px-4 py-2">
                    <span className="text-xs text-gray-500 truncate max-w-40 block" title={stmt.file_name}>
                      {stmt.file_name}
                    </span>
                  </td>

                  {/* Ticket count */}
                  <td className="px-4 py-2">
                    <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-[#1e3a5f]/10 text-[#1e3a5f] text-xs font-semibold">
                      {stmt.ticket_count.toLocaleString()}
                    </span>
                  </td>

                  {/* Income Summary — clickable, opens popup; stops row navigation */}
                  <td className="px-4 py-2">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setSummaryStmt(stmt); }}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-100 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 transition-colors"
                      title="View per-ticket income summary"
                    >
                      <TrendingUp className="w-3 h-3" /> View summary
                    </button>
                  </td>

                  {/* Uploaded By */}
                  <td className="px-4 py-2 text-xs text-gray-600 font-medium">
                    {stmt.created_by_name || "—"}
                  </td>

                  {/* Created */}
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {formatDateTime(stmt.created_at)}
                  </td>

                  {/* Arrow */}
                  <td className="px-4 py-2 text-right">
                    <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-[#1e3a5f] transition-colors inline" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Income Summary Modal ──────────────────────────────────────────── */}
      {summaryStmt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col">
            {/* Header */}
            <div className="flex items-start justify-between px-6 py-4 border-b border-gray-100">
              <div>
                <h2 className="text-sm font-bold text-gray-900">Income Summary</h2>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  {summaryStmt.statement_name ?? `${summaryStmt.statement_type} · ${summaryStmt.agency}`}
                  <span className="mx-1.5 text-gray-300">·</span>
                  {summaryStmt.agency}
                  <span className="mx-1.5 text-gray-300">·</span>
                  {formatDate(summaryStmt.valid_from)} → {formatDate(summaryStmt.valid_to)}
                </p>
              </div>
              <button onClick={() => setSummaryStmt(null)} className="p-1 hover:bg-gray-100 rounded-lg">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>

            {/* Body */}
            <div className="overflow-y-auto flex-1 px-6 py-4">
              {summaryLoading ? (
                <div className="flex justify-center py-12"><RefreshCw className="w-5 h-5 text-blue-400 animate-spin" /></div>
              ) : summaryError ? (
                <p className="text-xs text-red-600 text-center py-12">{summaryError}</p>
              ) : summaryRows.length === 0 ? (
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
                      <th className="px-2 py-2 font-semibold text-right">Income</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {summaryRows.map(t => (
                      <tr key={t.id} className="text-gray-700">
                        <td className="px-2 py-1.5">{t.ticket_number ?? "—"}</td>
                        <td className="px-2 py-1.5">{summaryPassenger(t)}</td>
                        <td className="px-2 py-1.5">{t.airline_name ?? t.airlines_code ?? "—"}</td>
                        <td className="px-2 py-1.5">{t.sector ?? "—"}</td>
                        <td className="px-2 py-1.5 text-right font-mono">{formatINR(t.sell_fare)}</td>
                        <td className="px-2 py-1.5">
                          <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-gray-100 text-gray-600 capitalize">
                            {t.ticket_status}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono font-semibold text-emerald-700">{formatINR(t.calculated_incentive)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="border-t-2 border-gray-300 font-bold text-gray-900">
                      <td className="px-2 py-2" colSpan={6}>Total ({summaryRows.length} tickets)</td>
                      <td className="px-2 py-2 text-right font-mono text-emerald-700">{formatINR(summaryTotal)}</td>
                    </tr>
                  </tfoot>
                </table>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-2 px-6 py-3 border-t border-gray-100">
              <a ref={downloadRef} className="hidden" />
              <button
                onClick={() => setSummaryStmt(null)}
                className="px-3 py-2 text-xs text-gray-600 hover:bg-gray-100 rounded-lg"
              >
                Close
              </button>
              <button
                onClick={handleDownloadPdf}
                disabled={summaryLoading || downloading || summaryRows.length === 0}
                className="flex items-center gap-1.5 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f] disabled:opacity-50"
              >
                {downloading
                  ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  : <Download className="w-3.5 h-3.5" />}
                {downloading ? "Preparing…" : "Download"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
