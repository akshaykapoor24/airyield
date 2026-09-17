"use client";

// One grid for every reconciliation source.
//
// TWO RESPONSE SHAPES, ONE COMPONENT. BSP answers "did the airline settle what we
// expected" and returns expected/actual/net_variance with missing_bsp/extra_bsp counts;
// every other source answers "what did this cost and what did it sell for" and returns
// buy/sell/margin with buy_only/sell_only. Rather than branch on the slug throughout, both
// are normalised once — `readRow`, `readSummary`, `readFields` — and the rest of the file
// renders one shape. The same trick `commission/types.facetValues` uses for the one place
// its two routers disagree on key names.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle, AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, FileX,
  GitMerge, Play, RefreshCw, Search, Ticket as TicketIcon, X,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import type { ReconSource } from "@/lib/reconciliationSources";

const BRAND = "#1e3a5f";
const PAGE_SIZE = 50;

const inr = (n: number | null | undefined) =>
  n == null ? "—" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

type AirlineOpt = { id: number; name: string; iata_code?: string };
type BatchOpt = { batch_id: string; source_file: string | null; row_count: number };

/** Whatever the two routers return, reduced to what the grid draws. */
type ViewRow = {
  id: number;
  /** Shown the way the statement prints it: "607 5808583279". The airline accounting
   *  code and the document serial are stored in separate columns — joining them here is
   *  presentation, never a key. */
  ticketNumber: string | null;
  airline: string | null;
  issueDate: string | null;
  status: string;
  buy: number | null;
  sell: number | null;
  diff: number | null;
  issueCount: number;
  /** "2 statement rows · 4 sector legs" — a figure built from several rows must say so. */
  provenance: string | null;
};

type ViewSummary = {
  total: number; matched: number; minorDiff: number; mismatch: number;
  buyOnly: number; sellOnly: number; possible: number;
  totalBuy: number | null; totalSell: number | null; totalDiff: number | null;
  lastRunAt: string | null;
};

type ViewField = {
  key: string; label: string;
  buy: number | null; sell: number | null;
  variance: number | null; match: boolean | null;
};

type ViewDetail = {
  row: ViewRow;
  matchMethod: string;
  reconciledAt: string | null;
  fields: ViewField[];
  issues: { severity: string; message: string; label?: string | null }[];
  notes: string[];
};

type ApiRow = Record<string, unknown>;

const num = (v: unknown): number | null =>
  v == null ? null : typeof v === "number" ? v : Number(v);
const str = (v: unknown): string | null => (v == null ? null : String(v));

/** Status vocabulary. The two engines share four values and differ on the other two. */
function statusStyle(s: string, src: ReconSource): { cls: string; label: string } {
  const buySide = src.comparison === "buy-vs-sell";
  switch (s) {
    case "matched": return { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Matched" };
    case "minor_diff": return { cls: "bg-amber-50 text-amber-700 border-amber-200", label: "Minor Diff" };
    case "mismatch": return { cls: "bg-red-50 text-red-700 border-red-200", label: "Mismatch" };
    case "possible_match": return { cls: "bg-blue-50 text-blue-700 border-blue-200", label: "Possible Match" };
    case "missing_bsp": return { cls: "bg-gray-100 text-gray-500 border-gray-200", label: "Missing BSP" };
    case "extra_bsp": return { cls: "bg-red-50 text-red-700 border-red-200", label: "Extra BSP" };
    case "buy_only": return { cls: "bg-gray-100 text-gray-500 border-gray-200", label: buySide ? "Not sold" : "Missing" };
    // "No purchase here", not "not bought": the sell side is the whole ticket file and is
    // shared by every source, so all this row knows is that THIS source's statements do
    // not account for the sale — it may well have been bought through another.
    case "sell_only": return { cls: "bg-purple-50 text-purple-700 border-purple-200", label: buySide ? "No purchase here" : "Extra" };
    default: return { cls: "bg-gray-100 text-gray-500 border-gray-200", label: s };
  }
}

function statusOptions(src: ReconSource) {
  const shared = [
    { value: "", label: "All statuses" },
    { value: "matched", label: "Matched" },
    { value: "minor_diff", label: "Minor Difference" },
    { value: "mismatch", label: "Mismatch" },
    { value: "possible_match", label: "Possible Match" },
  ];
  return src.comparison === "buy-vs-sell"
    ? [...shared,
       { value: "buy_only", label: "Bought, not sold" },
       { value: "sell_only", label: "Sold, no purchase here" }]
    : [...shared,
       { value: "missing_bsp", label: "Missing in BSP" },
       { value: "extra_bsp", label: "Extra BSP" }];
}

function readRow(r: ApiRow, src: ReconSource): ViewRow {
  const buySide = src.comparison === "buy-vs-sell";
  const bits: string[] = [];
  const buyRows = num(r.buy_rows) ?? 0;
  const legs = num(r.sell_legs) ?? 0;
  if (buyRows > 1) bits.push(`${buyRows} statement rows`);
  if (legs > 1) bits.push(`${legs} sector legs`);
  const serial = str(r.ticket_number);
  const prefix = str(r.ticket_prefix);
  return {
    id: num(r.id) as number,
    ticketNumber: serial && prefix ? `${prefix} ${serial}` : serial,
    airline: str(r.airline_name) ?? str(r.airline_code),
    issueDate: str(r.issue_date),
    status: String(r.match_status ?? ""),
    buy: buySide ? num(r.buy_net) : null,
    sell: buySide ? num(r.sell_net) : null,
    diff: buySide ? num(r.margin) : num(r.net_variance),
    issueCount: num(r.issue_count) ?? 0,
    provenance: bits.length ? bits.join(" · ") : null,
  };
}

function readSummary(s: ApiRow, src: ReconSource): ViewSummary {
  const buySide = src.comparison === "buy-vs-sell";
  return {
    total: num(s.total) ?? 0,
    matched: num(s.matched) ?? 0,
    minorDiff: num(s.minor_diff) ?? 0,
    mismatch: num(s.mismatch) ?? 0,
    buyOnly: num(buySide ? s.buy_only : s.missing_bsp) ?? 0,
    sellOnly: num(buySide ? s.sell_only : s.extra_bsp) ?? 0,
    possible: num(s.possible_match) ?? 0,
    totalBuy: buySide ? num(s.total_buy) : null,
    totalSell: buySide ? num(s.total_sell) : null,
    totalDiff: buySide ? num(s.total_margin) : num(s.total_variance),
    lastRunAt: str(s.last_run_at),
  };
}

function readFields(d: ApiRow, src: ReconSource): ViewField[] {
  const raw = (d.fields as ApiRow[]) ?? [];
  const buySide = src.comparison === "buy-vs-sell";
  return raw.map((f) => ({
    key: String(f.key ?? f.field ?? ""),
    label: String(f.label ?? ""),
    buy: num(buySide ? f.buy : f.expected),
    sell: num(buySide ? f.sell : f.actual),
    variance: num(f.variance),
    match: f.match == null ? null : Boolean(f.match),
  }));
}

export default function ReconciliationView({ source }: { source: ReconSource }) {
  const buySide = source.comparison === "buy-vs-sell";

  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [airline, setAirline] = useState("");
  const [status, setStatus] = useState("");
  const [batch, setBatch] = useState("");
  const [search, setSearch] = useState("");
  // Debounced copy. The BSP page fired a request per keystroke; a ticket number is 13
  // characters, so that was thirteen round trips to find one ticket.
  const [searchQ, setSearchQ] = useState("");
  const [offset, setOffset] = useState(0);

  const [airlines, setAirlines] = useState<AirlineOpt[]>([]);
  const [batches, setBatches] = useState<BatchOpt[]>([]);
  const [summary, setSummary] = useState<ViewSummary | null>(null);
  const [rows, setRows] = useState<ViewRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ViewDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setSearchQ(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    api.get<AirlineOpt[]>("/airlines/", { params: { limit: 1000 } })
      .then((r) => setAirlines(r.data)).catch(() => setAirlines([]));
  }, []);

  useEffect(() => {
    if (!source.showsBatchFilter) return;
    api.get<{ batches: BatchOpt[] }>(`${source.apiBase}/facets`)
      .then((r) => setBatches(r.data.batches ?? [])).catch(() => setBatches([]));
  }, [source]);

  const listUrl = buySide ? `${source.apiBase}/` : `${source.apiBase}/`;

  const fetchRows = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<ApiRow>(listUrl, {
        params: {
          date_from: dateFrom || undefined, date_to: dateTo || undefined,
          airline: airline || undefined, status: status || undefined,
          batch_id: batch || undefined, search: searchQ || undefined,
          offset, limit: PAGE_SIZE,
        },
      });
      setSummary(readSummary((data.summary as ApiRow) ?? {}, source));
      setRows(((data.rows as ApiRow[]) ?? []).map((r) => readRow(r, source)));
      setTotal(num(data.total) ?? 0);
    } catch {
      setError("Failed to load reconciliation results.");
      setRows([]); setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [listUrl, dateFrom, dateTo, airline, status, batch, searchQ, offset, source]);

  useEffect(() => { fetchRows(); }, [fetchRows]);
  useEffect(() => { setOffset(0); }, [dateFrom, dateTo, airline, status, batch, searchQ]);

  const runReconciliation = async () => {
    setRunning(true);
    try {
      const body = buySide ? { batch_id: batch || undefined } : {};
      const { data } = await api.post<ApiRow>(`${source.apiBase}/run`, body);
      if (buySide) {
        const margin = num(data.total_margin) ?? 0;
        toast.success(
          `Reconciled ${num(data.total) ?? 0} tickets — ${num(data.matched) ?? 0} matched, ` +
          `net ${margin >= 0 ? "margin" : "loss"} of ${inr(Math.abs(margin))}.`);
      } else {
        toast.success(
          `Reconciled ${num(data.total) ?? 0} rows — ${num(data.matched) ?? 0} matched, ` +
          `${(num(data.mismatch) ?? 0) + (num(data.minor_diff) ?? 0)} with differences.`);
      }
      await fetchRows();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof msg === "string" ? msg : "Failed to run reconciliation.");
    } finally {
      setRunning(false);
    }
  };

  const openDetail = async (id: number) => {
    setSelected(id); setDetail(null); setDetailLoading(true);
    try {
      const url = buySide ? `${source.apiBase}/rows/${id}` : `${source.apiBase}/${id}`;
      const { data } = await api.get<ApiRow>(url);
      setDetail({
        row: readRow(data, source),
        matchMethod: String(data.match_method ?? "none"),
        reconciledAt: str(data.reconciled_at),
        fields: readFields(data, source),
        issues: ((data.issues as ApiRow[]) ?? []).map((i) => ({
          severity: String(i.severity ?? "warning"),
          message: String(i.message ?? ""),
          label: str(i.label),
        })),
        notes: ((data.notes as string[]) ?? []).map(String),
      });
    } catch {
      toast.error("Failed to load details.");
      setSelected(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const hasFilter = !!(dateFrom || dateTo || airline || status || batch || search);
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + rows.length, total);

  const cards = useMemo(() => [
    { label: "Tickets", value: summary?.total ?? 0, cls: "text-slate-600 bg-slate-50", icon: TicketIcon },
    { label: "Matched", value: summary?.matched ?? 0, cls: "text-emerald-600 bg-emerald-50", icon: CheckCircle2 },
    { label: buySide ? "Bought, not sold" : "Missing BSP", value: summary?.buyOnly ?? 0, cls: "text-gray-500 bg-gray-100", icon: FileX },
    { label: buySide ? "Sold, no purchase" : "Extra BSP", value: summary?.sellOnly ?? 0, cls: "text-red-600 bg-red-50", icon: AlertTriangle },
  ], [summary, buySide]);

  const diffTile = summary?.totalDiff ?? null;
  const columns = buySide
    ? ["Ticket #", "Airline", "Issue Date", "Status", source.buyLabel, source.sellLabel, source.diffLabel, ""]
    : ["Ticket #", "Airline", "Issue Date", "Status", source.diffLabel, ""];

  return (
    <div className="space-y-5 pb-16">
      {/* header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-xs text-gray-500">
          {summary?.lastRunAt
            ? <>Last run {new Date(summary.lastRunAt).toLocaleString()}.</>
            : <>Not reconciled yet.</>}
        </p>
        <div className="flex items-center gap-2">
          <button onClick={fetchRows} disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
          <button onClick={runReconciliation} disabled={running}
            className="flex items-center gap-1.5 px-4 py-2 text-white rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-60"
            style={{ backgroundColor: BRAND }}>
            {running ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {running ? "Reconciling…" : "Re-run reconciliation"}
          </button>
        </div>
      </div>

      {/* summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        {cards.map(({ label, value, cls, icon: Icon }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className={`p-2.5 rounded-lg ${cls} w-fit mb-3`}><Icon className="w-4 h-4" /></div>
            <p className="text-2xl font-bold text-gray-900">{value.toLocaleString()}</p>
            <p className="text-xs text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="p-2.5 rounded-lg text-[#1e3a5f] bg-[#1e3a5f]/10 w-fit mb-3"><GitMerge className="w-4 h-4" /></div>
          <p className={`text-2xl font-bold ${buySide && diffTile != null && diffTile < 0 ? "text-red-600" : "text-gray-900"}`}
             title={inr(diffTile)}>{inr(diffTile)}</p>
          <p className="text-xs text-gray-500 mt-0.5">
            {buySide ? "Total margin" : "Total Variance"}
          </p>
          {buySide && summary && (
            <p className="text-[10px] text-gray-400 mt-1">
              {inr(summary.totalSell)} sold − {inr(summary.totalBuy)} bought
            </p>
          )}
        </div>
      </div>

      {/* filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input type="text" placeholder="Search ticket #…" value={search} onChange={(e) => setSearch(e.target.value)}
            className="pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-48" />
        </div>
        {source.showsBatchFilter && (
          <select value={batch} onChange={(e) => setBatch(e.target.value)}
            className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white max-w-[260px]">
            <option value="">All statements</option>
            {batches.map((b) => (
              <option key={b.batch_id} value={b.batch_id}>
                {b.source_file || b.batch_id} ({b.row_count})
              </option>
            ))}
          </select>
        )}
        <select value={airline} onChange={(e) => setAirline(e.target.value)}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white">
          <option value="">All airlines</option>
          {airlines.map((a) => <option key={a.id} value={a.name}>{a.name}{a.iata_code ? ` (${a.iata_code})` : ""}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white">
          {statusOptions(source).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} title="Issue date from"
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
        <span className="text-xs text-gray-400">–</span>
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} title="Issue date to"
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
        {hasFilter && (
          <button onClick={() => { setDateFrom(""); setDateTo(""); setAirline(""); setStatus(""); setBatch(""); setSearch(""); }}
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-400" title="Clear filters"><X className="w-3.5 h-3.5" /></button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* grid */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: BRAND }}>
                {columns.map((h, i) => (
                  <th key={h || i}
                      className={`px-4 py-2.5 text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap ${
                        [source.buyLabel, source.sellLabel, source.diffLabel].includes(h) ? "text-right" : "text-left"}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={columns.length} className="px-4 py-12 text-center text-sm text-gray-400">
                  <RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto mb-2" />Loading…
                </td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={columns.length} className="px-4 py-12 text-center text-sm text-gray-400">
                  {hasFilter ? "No rows match these filters." : (
                    <div className="space-y-1">
                      <p>
                        Nothing reconciled yet. Click{" "}
                        <button onClick={runReconciliation} className="text-blue-600 hover:underline">
                          Re-run reconciliation
                        </button>{" "}
                        once you have uploaded a {source.statementNoun} and the tickets you sold.
                      </p>
                      <p className="text-[11px] text-gray-400">
                        Statements live under {source.uploadLabel}.
                      </p>
                      {!source.joinsByTicket && (
                        <p className="text-[11px] text-amber-600">
                          This statement prints no ticket number, so its rows can only be
                          paired with a sale through the billing projection.
                        </p>
                      )}
                    </div>
                  )}
                </td></tr>
              ) : rows.map((r) => {
                const st = statusStyle(r.status, source);
                return (
                  <tr key={r.id} onClick={() => openDetail(r.id)}
                      className="border-b border-gray-100 hover:bg-gray-50/70 cursor-pointer">
                    <td className="px-4 py-2.5 text-xs font-medium text-gray-800">
                      {r.ticketNumber || "—"}
                      {r.provenance && (
                        <span className="block text-[10px] text-gray-400 font-normal">{r.provenance}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600">{r.airline || "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-500">{r.issueDate || "—"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${st.cls}`}>{st.label}</span>
                      {r.issueCount > 0 && (
                        <span className="ml-1.5 text-[10px] text-gray-400">
                          {r.issueCount} issue{r.issueCount === 1 ? "" : "s"}
                        </span>
                      )}
                    </td>
                    {buySide && (
                      <>
                        <td className="px-4 py-2.5 text-xs text-right text-gray-600">{inr(r.buy)}</td>
                        <td className="px-4 py-2.5 text-xs text-right text-gray-600">{inr(r.sell)}</td>
                      </>
                    )}
                    <td className={`px-4 py-2.5 text-xs text-right font-medium ${
                      r.diff == null ? "text-gray-300"
                        : r.diff < 0 ? "text-red-600"
                        : r.diff > 0 ? (buySide ? "text-emerald-600" : "text-red-600")
                        : "text-gray-500"}`}>
                      {r.diff == null ? "—" : inr(r.diff)}
                    </td>
                    <td className="px-4 py-2.5 text-right"><ChevronRight className="w-4 h-4 text-gray-300 inline" /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {total > 0 && (
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 text-xs text-gray-500">
            <span>Showing {pageStart}–{pageEnd} of {total.toLocaleString()}</span>
            <div className="flex items-center gap-1">
              <button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed">
                <ChevronLeft className="w-3.5 h-3.5" /> Prev
              </button>
              <button disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}
                className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed">
                Next <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>

      {selected != null && (
        <DetailModal source={source} detail={detail} loading={detailLoading}
                     onClose={() => { setSelected(null); setDetail(null); }} />
      )}
    </div>
  );
}

const MATCH_METHOD_LABEL: Record<string, string> = {
  ticket_number: "matched on the full ticket number",
  projection: "linked through the billing projection",
  alt10: "matched only on the last 10 digits",
  none: "not matched",
};

function DetailModal({
  source, detail, loading, onClose,
}: {
  source: ReconSource;
  detail: ViewDetail | null;
  loading: boolean;
  onClose: () => void;
}) {
  const buySide = source.comparison === "buy-vs-sell";
  const r = detail?.row;
  const st = r ? statusStyle(r.status, source) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
          <div>
            <h2 className="text-sm font-bold text-gray-900">{r?.ticketNumber || "Reconciliation"}</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {[r?.airline, r?.issueDate].filter(Boolean).join(" · ") || "—"}
              {detail && <span className="text-gray-400"> · {MATCH_METHOD_LABEL[detail.matchMethod] ?? detail.matchMethod}</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {st && <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${st.cls}`}>{st.label}</span>}
            <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {loading || !detail ? (
          <div className="px-5 py-12 text-center text-sm text-gray-400">
            <RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto mb-2" />Loading…
          </div>
        ) : (
          <div className="px-5 py-4 space-y-5">
            {buySide && (
              <div className="grid grid-cols-3 gap-3">
                <Tile label={source.buyLabel} value={inr(r?.buy)} />
                <Tile label={source.sellLabel} value={inr(r?.sell)} />
                <Tile label={source.diffLabel} value={inr(r?.diff)}
                      tone={r?.diff == null ? "" : r.diff < 0 ? "text-red-600" : "text-emerald-600"} />
              </div>
            )}

            <div>
              <h3 className="text-xs font-semibold text-gray-700 mb-2">Field comparison</h3>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-100">
                    {["Field", source.buyLabel, source.sellLabel, "Difference"].map((h, i) => (
                      <th key={h} className={`py-1.5 text-[10px] font-semibold text-gray-400 uppercase ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {detail.fields.map((f) => {
                    // Both sides empty means the two documents simply do not print this
                    // field — showing 0.00 would claim nothing was charged.
                    const comparable = f.buy != null || f.sell != null;
                    return (
                      <tr key={f.key} className="border-b border-gray-50 last:border-0">
                        <td className="py-1.5 text-xs text-gray-600">{f.label}</td>
                        <td className="py-1.5 text-xs text-right text-gray-800">{comparable ? inr(f.buy) : "—"}</td>
                        <td className="py-1.5 text-xs text-right text-gray-800">{comparable ? inr(f.sell) : "—"}</td>
                        <td className={`py-1.5 text-xs text-right font-medium ${
                          f.variance == null ? "text-gray-300" : f.match ? "text-gray-500" : "text-red-600"}`}>
                          {f.variance == null ? "—" : inr(f.variance)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {detail.issues.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-gray-700 mb-2">Issues</h3>
                <div className="space-y-1.5">
                  {detail.issues.map((i, n) => (
                    <div key={n} className={`px-3 py-2 rounded-lg border text-xs ${
                      i.severity === "critical"
                        ? "bg-red-50 border-red-200 text-red-700"
                        : "bg-amber-50 border-amber-200 text-amber-700"}`}>
                      {i.message}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {detail.notes.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-gray-700 mb-2">How these figures were built</h3>
                <ul className="space-y-1">
                  {detail.notes.map((n, i) => (
                    <li key={i} className="text-xs text-gray-500 flex gap-2">
                      <span className="text-gray-300">•</span><span>{n}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.reconciledAt && (
              <p className="text-[11px] text-gray-400">
                Reconciled {new Date(detail.reconciledAt).toLocaleString()}.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Tile({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="bg-gray-50 rounded-xl px-3 py-2.5">
      <p className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className={`text-sm font-bold mt-0.5 ${tone || "text-gray-900"}`}>{value}</p>
    </div>
  );
}
