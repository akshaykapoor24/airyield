"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  RefreshCw, Play, Search, X, AlertCircle, ChevronRight, ChevronLeft,
  GitMerge, CheckCircle2, AlertTriangle, Ticket as TicketIcon, FileX, ScrollText,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";

const BRAND = "#1e3a5f";
const PAGE_SIZE = 50;

const inr = (n: number | null | undefined) =>
  n == null ? "—" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

type AirlineOpt = { id: number; name: string; iata_code?: string };

type Summary = {
  total: number; matched: number; minor_diff: number; mismatch: number;
  missing_bsp: number; extra_bsp: number; possible_match: number;
  total_variance: number; last_run_at: string | null;
};
type Row = {
  id: number; ticket_id: number | null; bsp_row_id: number | null;
  ticket_number: string | null; airline_name: string | null; airline_code: string | null;
  issue_date: string | null; txn_type: string | null;
  match_status: string; severity: string;
  net_variance: number | null; abs_variance: number | null; issue_count: number;
};
type Page = { summary: Summary; total: number; offset: number; limit: number; rows: Row[] };
type FieldDiff = {
  field: string; label: string; expected: number | null; actual: number | null;
  variance: number | null; match: boolean | null; severity: string | null;
};
type Issue = { rule_id: string; field: string; severity: string; message: string; variance: number | null };
type BspTax = { component_type: string | null; component_code: string | null; amount: number | null };
// Full records returned by GET /bsp-reconciliation/{id} (BspStatementRowRead / UploadedTicketRead).
// Rendered generically in the full-info popup, so kept as open records.
type BspRowInfo = Record<string, unknown> & { taxes?: BspTax[] };
type TicketInfo = Record<string, unknown>;
type Detail = Row & {
  pax_name: string | null; match_method: string; commission_source: string | null;
  reconciled_at: string | null; remarks: string | null;
  fields: FieldDiff[]; issues: Issue[]; related_bsp: { bsp_row_id: number; txn_type: string; amount: number | null }[];
  bsp_row: BspRowInfo | null; ticket: TicketInfo | null;
};

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "matched", label: "Matched" },
  { value: "minor_diff", label: "Minor Difference" },
  { value: "mismatch", label: "Mismatch" },
  { value: "missing_bsp", label: "Missing in BSP" },
  { value: "extra_bsp", label: "Extra BSP" },
  { value: "possible_match", label: "Possible Match" },
];
const TXN_OPTIONS = ["TKTT", "ADM", "ACM", "RA", "RFND", "EMD", "EXCH"];

function statusStyle(s: string): { cls: string; label: string } {
  switch (s) {
    case "matched":        return { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Matched" };
    case "minor_diff":     return { cls: "bg-amber-50 text-amber-700 border-amber-200",       label: "Minor Diff" };
    case "mismatch":       return { cls: "bg-red-50 text-red-700 border-red-200",             label: "Mismatch" };
    case "missing_bsp":    return { cls: "bg-gray-100 text-gray-500 border-gray-200",         label: "Missing BSP" };
    case "extra_bsp":      return { cls: "bg-red-50 text-red-700 border-red-200",             label: "Extra BSP" };
    case "possible_match": return { cls: "bg-blue-50 text-blue-700 border-blue-200",          label: "Possible Match" };
    default:               return { cls: "bg-gray-100 text-gray-500 border-gray-200",         label: s };
  }
}

export default function BspReconciliationPage() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [airline, setAirline] = useState("");
  const [status, setStatus] = useState("");
  const [txnType, setTxnType] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);

  const [airlines, setAirlines] = useState<AirlineOpt[]>([]);
  const [page, setPage] = useState<Page | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    api.get<AirlineOpt[]>("/airlines/", { params: { limit: 1000 } })
      .then(r => setAirlines(r.data)).catch(() => setAirlines([]));
  }, []);

  const fetchRows = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<Page>("/bsp-reconciliation/", {
        params: {
          date_from: dateFrom || undefined, date_to: dateTo || undefined,
          airline: airline || undefined, status: status || undefined,
          txn_type: txnType || undefined, search: search.trim() || undefined,
          offset, limit: PAGE_SIZE,
        },
      });
      setPage(data);
    } catch {
      setError("Failed to load reconciliation results.");
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, airline, status, txnType, search, offset]);

  useEffect(() => { fetchRows(); }, [fetchRows]);

  // reset to first page whenever a filter (other than offset) changes
  useEffect(() => { setOffset(0); }, [dateFrom, dateTo, airline, status, txnType, search]);

  const runReconciliation = async () => {
    setRunning(true);
    try {
      const { data } = await api.post<{ matched: number; minor_diff: number; mismatch: number; missing_bsp: number; extra_bsp: number; total: number }>(
        "/bsp-reconciliation/run", {},
      );
      toast.success(`Reconciled ${data.total} rows — ${data.matched} matched, ${data.mismatch + data.minor_diff} with differences, ${data.missing_bsp} missing, ${data.extra_bsp} extra.`);
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
      const { data } = await api.get<Detail>(`/bsp-reconciliation/${id}`);
      setDetail(data);
    } catch {
      toast.error("Failed to load details.");
      setSelected(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const summary = page?.summary;
  const rows = page?.rows ?? [];
  const total = page?.total ?? 0;
  const hasFilter = !!(dateFrom || dateTo || airline || status || txnType || search);
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + rows.length, total);

  const cards = useMemo(() => [
    { label: "Tickets", value: summary?.total ?? 0, cls: "text-slate-600 bg-slate-50", icon: TicketIcon },
    { label: "Matched", value: summary?.matched ?? 0, cls: "text-emerald-600 bg-emerald-50", icon: CheckCircle2 },
    { label: "Missing BSP", value: summary?.missing_bsp ?? 0, cls: "text-gray-500 bg-gray-100", icon: FileX },
    { label: "Extra BSP", value: summary?.extra_bsp ?? 0, cls: "text-red-600 bg-red-50", icon: AlertTriangle },
  ], [summary]);

  return (
    <div className="space-y-5 pb-16">
      {/* header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">BSP Reconciliation</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Expected (internal) vs actual (BSP) — for every ticket, did BSP settle what you expected?
            {summary?.last_run_at && <span className="ml-1 text-gray-400">Last run {new Date(summary.last_run_at).toLocaleString()}.</span>}
          </p>
        </div>
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
          <p className="text-2xl font-bold text-gray-900" title={inr(summary?.total_variance)}>{inr(summary?.total_variance)}</p>
          <p className="text-xs text-gray-500 mt-0.5">Total Variance</p>
        </div>
      </div>

      {/* filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input type="text" placeholder="Search ticket #…" value={search} onChange={e => setSearch(e.target.value)}
            className="pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-48" />
        </div>
        <select value={airline} onChange={e => setAirline(e.target.value)}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white">
          <option value="">All airlines</option>
          {airlines.map(a => <option key={a.id} value={a.name}>{a.name}{a.iata_code ? ` (${a.iata_code})` : ""}</option>)}
        </select>
        <select value={status} onChange={e => setStatus(e.target.value)}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white">
          {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={txnType} onChange={e => setTxnType(e.target.value)}
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white">
          <option value="">All types</option>
          {TXN_OPTIONS.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} title="Issue date from"
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
        <span className="text-xs text-gray-400">–</span>
        <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} title="Issue date to"
          className="py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
        {hasFilter && (
          <button onClick={() => { setDateFrom(""); setDateTo(""); setAirline(""); setStatus(""); setTxnType(""); setSearch(""); }}
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
                {["Ticket #", "Airline", "Issue Date", "Type", "Status", "Difference", ""].map((h, i) => (
                  <th key={h || i} className={`px-4 py-2.5 text-[11px] font-semibold text-white/80 uppercase tracking-wide ${h === "Difference" ? "text-right" : "text-left"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-400"><RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto mb-2" />Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-400">
                  {hasFilter ? "No rows match these filters."
                    : <>No reconciliation yet. Click <button onClick={runReconciliation} className="text-blue-600 hover:underline">Re-run reconciliation</button> after uploading tickets and a BSP statement.</>}
                </td></tr>
              ) : rows.map(r => {
                const st = statusStyle(r.match_status);
                return (
                  <tr key={r.id} onClick={() => openDetail(r.id)} className="border-b border-gray-100 hover:bg-gray-50/70 cursor-pointer">
                    <td className="px-4 py-2.5 text-xs font-medium text-gray-800">{r.ticket_number || "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-600">{r.airline_name || r.airline_code || "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-500">{r.issue_date || "—"}</td>
                    <td className="px-4 py-2.5 text-xs text-gray-600">{r.txn_type || "—"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${st.cls}`}>{st.label}</span>
                      {r.issue_count > 0 && <span className="ml-1.5 text-[10px] text-gray-400">{r.issue_count} issue{r.issue_count === 1 ? "" : "s"}</span>}
                    </td>
                    <td className={`px-4 py-2.5 text-xs text-right font-medium ${r.net_variance != null && Math.abs(r.net_variance) > 0.001 ? "text-red-600" : "text-gray-500"}`}>
                      {r.net_variance == null ? "—" : inr(r.net_variance)}
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
                className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"><ChevronLeft className="w-3.5 h-3.5" /> Prev</button>
              <button disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}
                className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed">Next <ChevronRight className="w-3.5 h-3.5" /></button>
            </div>
          </div>
        )}
      </div>

      {selected != null && (
        <DetailModal detail={detail} loading={detailLoading} onClose={() => { setSelected(null); setDetail(null); }} />
      )}
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 border-b border-black/5 last:border-0">
      <span className="text-[11px] text-gray-400 shrink-0">{label}</span>
      <span className="text-xs text-gray-800 text-right font-medium break-words">{value || "—"}</span>
    </div>
  );
}

// Internal / noise keys not worth showing in the full-info panels.
const HIDE_KEYS = new Set([
  "id", "tenant_id", "created_by_id", "batch_id", "file_name", "file_url", "created_at",
  "updated_at", "raw_data", "taxes", "incentive_breakdown", "matched_ticket_id", "statement_id",
]);

function prettyLabel(k: string): string {
  const acronyms: Record<string, string> = {
    Yq: "YQ", Yr: "YR", K3: "K3", Iata: "IATA", Gds: "GDS", Pnr: "PNR",
    Adm: "ADM", Acm: "ACM", Ra: "RA", Fop: "FOP", Cpui: "CPUI", Nr: "NR", Bsp: "BSP",
  };
  return k
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/\b\w+\b/g, w => acronyms[w] ?? w);
}

function fmtVal(k: string, v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return k.includes("rate") ? `${v}%` : inr(v);
  return String(v);
}

type PanelTone = { border: string; bg: string; head: string; icon: string; text: string };
const BSP_TONE: PanelTone = { border: "border-blue-100", bg: "bg-blue-50/30", head: "bg-blue-50", icon: "text-blue-500", text: "text-blue-700" };
const TKT_TONE: PanelTone = { border: "border-emerald-100", bg: "bg-emerald-50/30", head: "bg-emerald-50", icon: "text-emerald-600", text: "text-emerald-700" };

// Renders every meaningful field of a record generically ("full" info).
function FullRecordPanel({
  title, icon: Icon, tone, obj, taxes, emptyText,
}: {
  title: string; icon: typeof ScrollText; tone: PanelTone;
  obj: Record<string, unknown> | null; taxes?: BspTax[]; emptyText: string;
}) {
  const entries = obj
    ? Object.entries(obj).filter(([k, v]) => !HIDE_KEYS.has(k) && v != null && v !== "" && typeof v !== "object")
    : [];
  return (
    <div className={`rounded-lg border ${tone.border} ${tone.bg} overflow-hidden`}>
      <div className={`flex items-center gap-2 px-3 py-2 border-b ${tone.border} ${tone.head}`}>
        <Icon className={`w-3.5 h-3.5 ${tone.icon}`} />
        <span className={`text-[11px] font-semibold ${tone.text} uppercase tracking-wide`}>{title}</span>
      </div>
      {!obj ? (
        <div className="px-3 py-6 text-center text-xs text-gray-400">{emptyText}</div>
      ) : (
        <div className="px-3 py-2">
          {entries.map(([k, v]) => <KV key={k} label={prettyLabel(k)} value={fmtVal(k, v)} />)}
          {taxes && taxes.length > 0 && (
            <div className="pt-2">
              <p className="text-[10px] text-gray-400 uppercase tracking-wide mb-1">Taxes / Fees</p>
              <div className="flex flex-wrap gap-1">
                {taxes.map((t, i) => (
                  <span key={i} className="px-1.5 py-0.5 rounded border border-blue-100 bg-white text-[10px] text-gray-600">
                    <span className="font-semibold text-gray-700">{t.component_code || t.component_type}</span> {inr(t.amount)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Second popup: full BSP statement + full ticket, side by side.
function FullInfoModal({ detail, onClose }: { detail: Detail; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4"
      onClick={e => { e.stopPropagation(); onClose(); }}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-5xl max-h-[90vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-800 truncate">
            Full details — {detail.ticket_number || "—"}{detail.airline_name ? ` · ${detail.airline_name}` : ""}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
        </div>
        <div className="overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <FullRecordPanel title="BSP Statement (actual)" icon={ScrollText} tone={BSP_TONE}
              obj={detail.bsp_row} taxes={detail.bsp_row?.taxes} emptyText="No BSP settlement matched this ticket." />
            <FullRecordPanel title="Ticket Info (expected)" icon={TicketIcon} tone={TKT_TONE}
              obj={detail.ticket} emptyText="No internal ticket matched this BSP row." />
          </div>
        </div>
      </div>
    </div>
  );
}

function DetailModal({ detail, loading, onClose }: { detail: Detail | null; loading: boolean; onClose: () => void }) {
  const [showFull, setShowFull] = useState(false);
  const st = detail ? statusStyle(detail.match_status) : null;
  const missing = detail?.match_status === "missing_bsp";
  const extra = detail?.match_status === "extra_bsp";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[88vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100">
          <div className="flex items-center gap-2.5 min-w-0">
            <ScrollText className="w-4 h-4 text-gray-400 shrink-0" />
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-gray-800 truncate">
                {detail?.ticket_number || "Reconciliation"} {detail?.airline_name ? `· ${detail.airline_name}` : ""}
              </h2>
              <p className="text-[11px] text-gray-400">
                {detail?.txn_type || "—"}{detail?.issue_date ? ` · ${detail.issue_date}` : ""}
                {detail?.match_method && detail.match_method !== "none" ? ` · matched by ${detail.match_method}` : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {st && <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${st.cls}`}>{st.label}</span>}
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="overflow-y-auto px-5 py-4">
          {loading || !detail ? (
            <div className="py-12 text-center text-sm text-gray-400"><RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto mb-2" />Loading…</div>
          ) : (
            <>
              {/* Opens a second popup with the full BSP statement + ticket info side by side. */}
              <button
                onClick={() => setShowFull(true)}
                className="w-full mb-4 flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-lg border border-gray-200 bg-gray-50 hover:bg-gray-100 transition-colors text-left">
                <span className="flex items-center gap-2 text-xs font-semibold text-gray-700">
                  <ScrollText className="w-3.5 h-3.5 text-blue-500" />
                  View BSP Statement &amp; Ticket Info
                </span>
                <ChevronRight className="w-4 h-4 text-gray-400" />
              </button>

              <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Field comparison</p>
              <div className="rounded-lg border border-gray-200 overflow-hidden">
                <table className="w-full text-left">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200 text-[11px] uppercase tracking-wide text-gray-400">
                      <th className="px-3 py-2 font-semibold">Field</th>
                      <th className="px-3 py-2 font-semibold text-right">Internal (Expected)</th>
                      <th className="px-3 py-2 font-semibold text-right">BSP (Actual)</th>
                      <th className="px-3 py-2 font-semibold text-right">Variance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.fields.map(f => {
                      const compared = f.match !== null || f.variance !== null;
                      return (
                        <tr key={f.field} className="border-b border-gray-100 last:border-0">
                          <td className="px-3 py-1.5 text-xs text-gray-700">{f.label}</td>
                          <td className="px-3 py-1.5 text-xs text-gray-800 text-right">{missing && !compared ? "—" : inr(f.expected)}</td>
                          <td className="px-3 py-1.5 text-xs text-gray-800 text-right">{extra || compared ? inr(f.actual) : <span className="text-gray-300">—</span>}</td>
                          <td className="px-3 py-1.5 text-xs text-right">
                            {f.variance == null ? <span className="text-gray-300">—</span> : (
                              <span className={`inline-flex items-center gap-1 ${f.match ? "text-emerald-600" : "text-red-600"}`}>
                                {f.match ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                                {inr(f.variance)}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {detail.issues.length > 0 && (
                <div className="mt-4">
                  <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Issues</p>
                  <div className="space-y-1.5">
                    {detail.issues.map((iss, i) => (
                      <div key={i} className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-xs ${iss.severity === "critical" ? "bg-red-50 border-red-200 text-red-700" : "bg-amber-50 border-amber-200 text-amber-700"}`}>
                        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                        <span>{iss.message}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {detail.related_bsp.length > 0 && (
                <div className="mt-4">
                  <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Related BSP settlements (same ticket)</p>
                  <div className="flex flex-wrap gap-2">
                    {detail.related_bsp.map((rb, i) => (
                      <span key={i} className="px-2.5 py-1 rounded-lg border border-gray-200 bg-gray-50 text-[11px] text-gray-600">
                        {rb.txn_type} · {inr(rb.amount)}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {detail.remarks && <p className="mt-4 text-[11px] text-gray-400">{detail.remarks}</p>}
            </>
          )}
        </div>
      </div>

      {showFull && detail && <FullInfoModal detail={detail} onClose={() => setShowFull(false)} />}
    </div>
  );
}
