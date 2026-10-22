"use client";

// Internal Statement's ticket list — every ticket, uploaded or hand-punched, in the
// shape of the statement it mirrors: Doc No / Doc Date, sale or refund, and the
// Invoice Amount (total_amt, the statement's BillAmount).
//
// Used twice: as the "All tickets" tab (every ticket) and inside one uploaded
// statement (batchId). Paginated server-side through /internal-tickets/uploads/page,
// the same endpoint the Customer data list uses, so tens of thousands of rows stay
// cheap.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, ChevronRight, RefreshCw, Search, SquarePen, Ticket, Trash2, X } from "lucide-react";
import api from "@/lib/api";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Pagination from "@/components/ui/Pagination";
import { MANUAL_ENTRY_FILE_NAME, inr, type TicketRow } from "@/lib/ticketFields";

const PAGE_SIZE = 50;
const REFUND_TYPES = new Set(["Credit Note", "Refund"]);

type Row = TicketRow & {
  id:               number;
  batch_id:         string;
  file_name:        string;
  created_at:       string;
  ticket_prefix?:   string | null;
  doc_no?:          string | null;
  doc_date?:        string | null;
  statement_agency: string | null;
  statement_name:   string | null;
};

type Page = { total: number; offset: number; limit: number; rows: Row[] };
type Facets = { airlines: string[] };

const SELECT =
  "py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white";

const fmtDate = (d?: string | null) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" }) : "—";

const num = (v: unknown) => (typeof v === "number" ? v : Number(v) || 0);

/** "IST/AUH AUH/DEL" → "IST/AUH/DEL": the route as the statement prints it. */
function route(sector?: string | null): string {
  if (!sector) return "—";
  const codes = sector.toUpperCase().split(/[\s/]+/).filter((c, i, a) => c && c !== a[i - 1]);
  return codes.join("/");
}

export default function InternalTicketsView({
  apiBase = "/internal-tickets",
  batchId,
  statementBase = "/internal-statement/statements",
  onDeleted,
}: {
  apiBase?: string;
  /** Only this statement's tickets — the statement detail screen. */
  batchId?: string;
  /** Where an uploaded ticket's row opens its statement. */
  statementBase?: string;
  /** After a ticket is deleted — so a header showing the count can refresh. */
  onDeleted?: () => void;
}) {
  const router = useRouter();
  const [page, setPage] = useState<Page | null>(null);
  const [airlines, setAirlines] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [pageNo, setPageNo] = useState(1);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [airline, setAirline] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Row | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Any filter change invalidates the current page number.
  useEffect(() => { setPageNo(1); }, [debounced, airline]);

  useEffect(() => {
    api.get<Facets>(`${apiBase}/uploads/facets`).then((r) => setAirlines(r.data.airlines ?? [])).catch(() => {});
  }, [apiBase]);

  const fetchPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Page>(`${apiBase}/uploads/page`, {
        params: {
          offset: (pageNo - 1) * PAGE_SIZE,
          limit: PAGE_SIZE,
          search: debounced || undefined,
          airline: airline || undefined,
          batch_id: batchId || undefined,
        },
      });
      setPage(data);
    } catch {
      setError("Failed to load tickets. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [apiBase, pageNo, debounced, airline, batchId]);

  useEffect(() => { fetchPage(); }, [fetchPage]);

  const hasFilter = !!(search || airline);
  const clearFilters = () => { setSearch(""); setAirline(""); };

  const totals = useMemo(() => {
    const rows = page?.rows ?? [];
    return {
      fare:    rows.reduce((t, r) => t + num(r.sell_fare), 0),
      invoice: rows.reduce((t, r) => t + num(r.total_amt), 0),
    };
  }, [page]);

  const taxes = (r: Row) =>
    num(r.sell_tax_yq) + num(r.sale_yr) + num(r.sale_k3) + num(r.oc_tax) + num(r.other_tax);

  return (
    <div className="space-y-4">
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
        <select value={airline} onChange={(e) => setAirline(e.target.value)} className={SELECT}>
          <option value="">All Airlines</option>
          {airlines.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        {hasFilter && (
          <button onClick={clearFilters} title="Clear filters" className="p-2 hover:bg-gray-100 rounded-lg text-gray-400">
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        <button
          onClick={fetchPage}
          disabled={loading}
          className="ml-auto flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {loading && !page && (
        <div className="flex items-center justify-center py-20">
          <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        </div>
      )}

      {!error && page && page.total === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
            <Ticket className="w-7 h-7 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">
            {hasFilter ? "No tickets match the current filters" : "No tickets yet"}
          </p>
          {hasFilter && (
            <button onClick={clearFilters} className="text-xs text-blue-600 hover:underline mt-2">Clear filters</button>
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
            {!batchId && <p className="text-xs text-gray-400">Click an uploaded ticket to open its statement</p>}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-max text-xs">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  {["Doc Date", "Doc No", "Ticket No", "Pax Name", "Sector", "AL", "Customer", "Payable To", "Type",
                    ...(batchId ? [] : ["Source"])].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">{h}</th>
                  ))}
                  {["Basic", "Taxes", "Discount", "Serv. Chrgs", "RAF", "GST", "TDS", "Invoice Amt"].map((h) => (
                    <th key={h} className="px-3 py-2 text-right text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">{h}</th>
                  ))}
                  <th className="px-2 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {page.rows.map((t) => {
                  const manual = t.file_name === MANUAL_ENTRY_FILE_NAME;
                  const refund = REFUND_TYPES.has(String(t.invoice_type ?? ""));
                  // A punched ticket has no statement of its own to open.
                  const opens = !batchId && !manual;
                  const money = (v: unknown) => {
                    const n = num(v);
                    return n === 0 ? <span className="text-gray-300">—</span> : inr(n);
                  };
                  return (
                    <tr
                      key={t.id}
                      onClick={opens ? () => router.push(`${statementBase}/${t.batch_id}`) : undefined}
                      className={`${opens ? "cursor-pointer hover:bg-blue-50/40" : ""} ${refund ? "bg-amber-50/30" : ""} group`}
                    >
                      <td className="px-3 py-2 whitespace-nowrap text-gray-600">{fmtDate(t.doc_date ?? t.ticket_date)}</td>
                      <td className="px-3 py-2 whitespace-nowrap font-mono text-gray-700">
                        {t.doc_no ? t.doc_no.replace(/\s+/g, " ") : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap font-mono font-semibold text-gray-800">
                        {t.ticket_prefix && <span className="text-gray-400 font-normal mr-1">{t.ticket_prefix}</span>}
                        {t.ticket_number ?? "—"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-gray-700 max-w-[200px] truncate" title={t.pax_name ?? undefined}>
                        {t.pax_name ?? "—"}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap font-mono text-gray-700">{route(t.sector)}</td>
                      <td className="px-3 py-2 whitespace-nowrap text-gray-700" title={t.airline_name ?? undefined}>{t.airlines_code ?? "—"}</td>
                      <td className="px-3 py-2 whitespace-nowrap text-gray-600 max-w-[180px] truncate"
                        title={t.customer_name ?? t.statement_agency ?? undefined}>
                        {t.customer_name ?? t.statement_agency ?? "—"}
                      </td>
                      {/* Who it was bought from (Create Ticket). Uploaded lines do not say. */}
                      <td className="px-3 py-2 whitespace-nowrap text-gray-600 max-w-[180px] truncate" title={t.payable_to ?? undefined}>
                        {t.payable_to ? (
                          <>
                            <span className={`mr-1 inline-flex px-1 py-px rounded text-[9px] font-bold ${
                              t.payable_type === "airline" ? "bg-sky-50 text-sky-700" : "bg-violet-50 text-violet-700"}`}>
                              {t.payable_type === "airline" ? "AL" : "B2B"}
                            </span>
                            {t.payable_to}
                          </>
                        ) : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          refund ? "bg-amber-100 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>
                          {refund ? "Refund" : "Sale"}
                        </span>
                      </td>
                      {!batchId && (
                        <td className="px-3 py-2 whitespace-nowrap">
                          {manual ? (
                            <span className="inline-flex items-center gap-1 text-[10px] text-violet-700">
                              <SquarePen className="w-3 h-3" /> Punched
                            </span>
                          ) : (
                            <span className="text-[10px] text-gray-500 truncate max-w-[160px] inline-block align-bottom" title={t.file_name}>
                              {t.file_name}
                            </span>
                          )}
                        </td>
                      )}
                      <td className="px-3 py-2 text-right tabular-nums">{money(t.sell_fare)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(taxes(t))}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(t.dis_sell)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(t.serv_charge)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(t.raf)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(t.gst_sell)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{money(t.tds_sell)}</td>
                      <td className={`px-3 py-2 text-right tabular-nums font-semibold ${num(t.total_amt) < 0 ? "text-amber-800" : "text-gray-900"}`}>
                        {inr(num(t.total_amt))}
                      </td>
                      <td className="px-2 py-2 whitespace-nowrap text-right">
                        <button
                          type="button"
                          title="Delete this ticket"
                          onClick={(e) => { e.stopPropagation(); setDeleteTarget(t); }}
                          className="p-1 rounded-md text-gray-300 hover:text-red-600 hover:bg-red-50 transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                        {opens && <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-[#1e3a5f] inline ml-0.5" />}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="bg-gray-50 border-t border-gray-200 font-semibold text-gray-700">
                  <td className="px-3 py-2 text-[11px] uppercase tracking-wide text-gray-500" colSpan={batchId ? 9 : 10}>
                    This page
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{inr(totals.fare)}</td>
                  <td colSpan={6} />
                  <td className="px-3 py-2 text-right tabular-nums">{inr(totals.invoice)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>

          <div className="px-5 py-3 border-t border-gray-100">
            <Pagination page={pageNo} pageSize={PAGE_SIZE} total={page.total} onPageChange={setPageNo} />
          </div>
        </div>
      )}

      {deleteTarget && (
        <ConfirmDialog
          title="Delete ticket?"
          confirmLabel="Delete ticket"
          onClose={() => setDeleteTarget(null)}
          onConfirm={async () => {
            await api.delete(`${apiBase}/uploads/${deleteTarget.id}`);
            setDeleteTarget(null);
            onDeleted?.();
            // Re-read, so the count, the page totals and the pager stay right — and an
            // emptied last page steps back rather than showing nothing.
            if (page && page.rows.length === 1 && pageNo > 1) setPageNo(pageNo - 1);
            else await fetchPage();
          }}
        >
          <p>
            Ticket{" "}
            <b className="font-mono">
              {deleteTarget.ticket_prefix ? `${deleteTarget.ticket_prefix} ` : ""}{deleteTarget.ticket_number ?? "—"}
            </b>
            {deleteTarget.pax_name && <> — {deleteTarget.pax_name}</>}
            {deleteTarget.doc_no && <> ({deleteTarget.doc_no.replace(/\s+/g, " ")})</>}
            , invoice amount <b>{inr(num(deleteTarget.total_amt))}</b>, will be permanently deleted.
          </p>
          {deleteTarget.file_name !== MANUAL_ENTRY_FILE_NAME && (
            <p className="mt-2 text-gray-500">
              It is removed from its statement <b>{deleteTarget.statement_name || deleteTarget.statement_agency}</b>;
              the statement and its other tickets stay.
            </p>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
