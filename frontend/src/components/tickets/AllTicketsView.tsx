"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertCircle, Building2, ChevronRight, RefreshCw, Search, Ticket, X,
} from "lucide-react";
import api from "@/lib/api";
import { useStatementSectionBase } from "@/lib/statementSection";
import Pagination from "@/components/ui/Pagination";
import { inr, type TicketRow } from "@/lib/ticketFields";

const PAGE_SIZE = 50;

type TicketWithStatement = TicketRow & {
  id:               number;
  batch_id:         string;
  file_name:        string;
  ticket_status:    string;
  created_at:       string;
  statement_agency: string | null;
  statement_name:   string | null;
};

type Page = { total: number; offset: number; limit: number; rows: TicketWithStatement[] };
type Facets = { airlines: string[]; statuses: string[]; statement_types: string[] };

const STATUS_STYLE: Record<string, string> = {
  draft:      "bg-gray-100 text-gray-600",
  calculated: "bg-emerald-50 text-emerald-700 border border-emerald-200",
  included:   "bg-emerald-50 text-emerald-700 border border-emerald-200",
  reviewed:   "bg-blue-50 text-blue-700 border border-blue-200",
  excluded:   "bg-red-50 text-red-600 border border-red-200",
  cancelled:  "bg-orange-50 text-orange-600 border border-orange-200",
  reversed:   "bg-amber-50 text-amber-700 border border-amber-200",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap ${
      STATUS_STYLE[status] ?? "bg-gray-100 text-gray-600"}`}>
      {status}
    </span>
  );
}

const SELECT =
  "py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white";

/**
 * All-tickets view — every ticket the user owns, flat across statements.
 *
 * Paginated and filtered server-side: a tenant can hold tens of thousands of
 * rows, so the statement-wise view's load-everything-and-filter-in-the-browser
 * approach does not carry over here.
 */
export default function AllTicketsView() {
  // Row click must stay in whichever section this list is rendered in.
  const sectionBase = useStatementSectionBase();
  const router = useRouter();

  const [page, setPage] = useState<Page | null>(null);
  const [facets, setFacets] = useState<Facets>({ airlines: [], statuses: [], statement_types: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [pageNo, setPageNo] = useState(1);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [airline, setAirline] = useState("");
  const [statementType, setStatementType] = useState("");
  const [status, setStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Any filter change invalidates the current page number.
  useEffect(() => { setPageNo(1); }, [debounced, airline, statementType, status, dateFrom, dateTo]);

  useEffect(() => {
    api.get<Facets>("/tickets/uploads/facets").then((r) => setFacets(r.data)).catch(() => {});
  }, []);

  const fetchPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Page>("/tickets/uploads/page", {
        params: {
          offset: (pageNo - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
          search: debounced || undefined,
          airline: airline || undefined,
          statement_type: statementType || undefined,
          ticket_status: status || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        },
      });
      setPage(data);
    } catch {
      setError("Failed to load tickets. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [pageNo, debounced, airline, statementType, status, dateFrom, dateTo]);

  useEffect(() => { fetchPage(); }, [fetchPage]);

  const hasFilter = !!(search || airline || statementType || status || dateFrom || dateTo);
  const clearFilters = () => {
    setSearch(""); setAirline(""); setStatementType(""); setStatus(""); setDateFrom(""); setDateTo("");
  };

  const totals = useMemo(() => {
    const rows = page?.rows ?? [];
    return {
      fare: rows.reduce((t, r) => t + (Number(r.sell_fare) || 0), 0),
      amt: rows.reduce((t, r) => t + (Number(r.total_amt) || 0), 0),
      incentive: rows.reduce((t, r) => t + (Number(r.calculated_incentive) || 0), 0),
    };
  }, [page]);

  return (
    <div className="space-y-5">
      {/* filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Ticket no, PNR, pax, sector, customer…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-64"
          />
        </div>

        <select value={statementType} onChange={(e) => setStatementType(e.target.value)} className={SELECT}>
          <option value="">All Types</option>
          {facets.statement_types.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>

        <select value={airline} onChange={(e) => setAirline(e.target.value)} className={SELECT}>
          <option value="">All Airlines</option>
          {facets.airlines.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>

        <select value={status} onChange={(e) => setStatus(e.target.value)} className={SELECT}>
          <option value="">All Statuses</option>
          {facets.statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
          title="Ticket date from" className={SELECT} />
        <span className="text-xs text-gray-400">–</span>
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
          title="Ticket date to" className={SELECT} />

        {hasFilter && (
          <button onClick={clearFilters} title="Clear filters"
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-400">
            <X className="w-3.5 h-3.5" />
          </button>
        )}

        <button
          onClick={fetchPage}
          disabled={loading}
          className="ml-auto flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {loading && !page && (
        <div className="flex items-center justify-center py-24">
          <div className="text-center space-y-3">
            <RefreshCw className="w-7 h-7 text-blue-400 animate-spin mx-auto" />
            <p className="text-sm text-gray-500">Loading tickets…</p>
          </div>
        </div>
      )}

      {!error && page && page.total === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
            <Ticket className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">
            {hasFilter ? "No tickets match the current filters" : "No tickets yet"}
          </p>
          {hasFilter && (
            <button onClick={clearFilters} className="text-xs text-blue-600 hover:underline mt-2">
              Clear filters
            </button>
          )}
        </div>
      )}

      {!error && page && page.total > 0 && (
        <div className={`bg-white rounded-xl border border-gray-200 overflow-hidden transition-opacity ${loading ? "opacity-60" : ""}`}>
          <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
              {page.total.toLocaleString()} Ticket{page.total !== 1 ? "s" : ""}
              {hasFilter && <span className="text-gray-400 font-normal normal-case ml-1.5">(filtered)</span>}
            </p>
            <p className="text-xs text-gray-400">Click a row to open its statement</p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-max">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  {["Ticket #", "Airline", "Sector", "Class", "Ticket Date", "Passenger",
                    "Statement", "Status"].map((h) => (
                    <th key={h} className="px-4 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                  {["Sell Fare", "Total Amt", "Incentive"].map((h) => (
                    <th key={h} className="px-4 py-2 text-right text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {page.rows.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => router.push(`${sectionBase}/${t.batch_id}`)}
                    className="hover:bg-blue-50/40 cursor-pointer transition-colors group"
                  >
                    <td className="px-4 py-2 whitespace-nowrap">
                      <span className="text-xs font-semibold text-gray-800 font-mono group-hover:text-[#1e3a5f]">
                        {t.ticket_number ?? <span className="text-gray-300">—</span>}
                      </span>
                      {t.split_type === "split" && (
                        <span className="ml-1.5 inline-flex px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-50 text-amber-600 border border-amber-200">
                          leg
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <span className="text-xs text-gray-700" title={t.airline_name ?? undefined}>
                        {t.airlines_code ?? <span className="text-gray-300">—</span>}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-700 font-mono whitespace-nowrap">
                      {t.sector ?? <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-700">
                      {t.booking_class ?? <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-600 whitespace-nowrap">
                      {t.ticket_date ?? <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-600 max-w-40 truncate">
                      {t.pax_name
                        ?? [t.last_name, t.first_name].filter(Boolean).join("/")
                        ?? <span className="text-gray-300">—</span>}
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-indigo-50 border border-indigo-100 text-[11px] font-medium text-indigo-700 max-w-48 truncate"
                        title={t.statement_name ?? undefined}>
                        <Building2 className="w-3 h-3 shrink-0" />
                        {t.statement_agency ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <StatusBadge status={t.ticket_status} />
                    </td>
                    <td className="px-4 py-2 text-xs text-right text-gray-800 tabular-nums whitespace-nowrap">
                      {inr(t.sell_fare)}
                    </td>
                    <td className="px-4 py-2 text-xs text-right text-gray-800 tabular-nums whitespace-nowrap">
                      {inr(t.total_amt)}
                    </td>
                    <td className="px-4 py-2 text-xs text-right font-semibold text-emerald-700 tabular-nums whitespace-nowrap">
                      {inr(t.calculated_incentive)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-[#1e3a5f] transition-colors inline" />
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-gray-50 border-t border-gray-200">
                  <td colSpan={8} className="px-4 py-2 text-[11px] font-semibold text-gray-500 text-right">
                    This page
                  </td>
                  <td className="px-4 py-2 text-xs text-right font-semibold text-gray-700 tabular-nums whitespace-nowrap">
                    {inr(totals.fare)}
                  </td>
                  <td className="px-4 py-2 text-xs text-right font-semibold text-gray-700 tabular-nums whitespace-nowrap">
                    {inr(totals.amt)}
                  </td>
                  <td className="px-4 py-2 text-xs text-right font-semibold text-emerald-700 tabular-nums whitespace-nowrap">
                    {inr(totals.incentive)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>

          <Pagination
            page={pageNo}
            pageSize={PAGE_SIZE}
            total={page.total}
            onPageChange={setPageNo}
          />
        </div>
      )}
    </div>
  );
}
