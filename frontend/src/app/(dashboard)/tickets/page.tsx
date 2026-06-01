"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Upload, RefreshCw, FileSpreadsheet, ChevronRight,
  Building2, Calendar, Hash, AlertCircle, Search, X,
} from "lucide-react";
import api from "@/lib/api";

type TicketStatement = {
  batch_id:       string;
  statement_name: string;
  agency:         string;
  valid_from:     string;
  valid_to:       string;
  file_name:      string;
  ticket_count:   number;
  created_at:     string;
};

function formatDate(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function formatDateTime(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

const AGENCY_OPTIONS = [
  "IndiGo Travel Agency", "Air India GDS", "MakeMyTrip B2B",
  "EaseMyTrip Corporate", "Yatra Corporate", "Thomas Cook India",
];

export default function TicketRepositoryPage() {
  const router = useRouter();
  const [statements, setStatements] = useState<TicketStatement[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [filterName,   setFilterName]   = useState("");
  const [filterAgency, setFilterAgency] = useState("");
  const [filterFrom,   setFilterFrom]   = useState("");
  const [filterTo,     setFilterTo]     = useState("");

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

  const filtered = statements.filter(s => {
    if (filterName && !s.statement_name.toLowerCase().includes(filterName.toLowerCase())) return false;
    if (filterAgency && s.agency !== filterAgency) return false;
    if (filterFrom && s.valid_to < filterFrom) return false;
    if (filterTo   && s.valid_from > filterTo)   return false;
    return true;
  });

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
          <select
            value={filterAgency} onChange={e => setFilterAgency(e.target.value)}
            className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white"
          >
            <option value="">All Agencies</option>
            {AGENCY_OPTIONS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
          <input type="date" value={filterFrom} onChange={e => setFilterFrom(e.target.value)}
            title="Valid from" className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
          <span className="text-xs text-gray-400">–</span>
          <input type="date" value={filterTo} onChange={e => setFilterTo(e.target.value)}
            title="Valid to" className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
          {(filterName || filterAgency || filterFrom || filterTo) && (
            <button
              onClick={() => { setFilterName(""); setFilterAgency(""); setFilterFrom(""); setFilterTo(""); }}
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
                <th className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide">Uploaded</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-xs text-gray-400">
                    No statements match the current filters.
                  </td>
                </tr>
              ) : filtered.map(stmt => (
                <tr
                  key={stmt.batch_id}
                  onClick={() => router.push(`/tickets/${stmt.batch_id}`)}
                  className="hover:bg-blue-50/40 cursor-pointer transition-colors group"
                >
                  {/* Statement Name */}
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                        <FileSpreadsheet className="w-4 h-4 text-blue-500" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-gray-800 group-hover:text-[#1e3a5f]">
                          {stmt.statement_name}
                        </p>
                        {/* <p className="text-[11px] text-gray-400 font-mono truncate max-w-50">{stmt.batch_id.slice(0, 8)}…</p> */}
                      </div>
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
    </div>
  );
}
