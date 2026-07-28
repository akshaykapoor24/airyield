"use client";

import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowLeft, FileText, FileSpreadsheet, ExternalLink, ChevronLeft, ChevronRight, Loader2, RefreshCw, Search, X,
} from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";
import BspComparisonPanel from "./BspComparisonPanel";

export type BspGroup = {
  group_id: string;
  agent_code: string | null;
  agent_name: string | null;
  reference: string | null;
  period_from: string | null;
  period_to: string | null;
  summary_batch_id: string | null;
  summary_status: string | null;
  detail_batch_id: string | null;
  detail_status: string | null;
  match_status: string;
};

type CompLine = { line: string; summary: number | string | null; detail: number | string | null; variance: number | string | null; ok: boolean };
type SummaryRow = {
  id: number; category: string | null; airline_code: string | null; airline_iata: string | null;
  airline_name: string | null; fop: string | null; issues: number | string | null; refunds: number | string | null;
  debit_memos: number | string | null; credit_memos: number | string | null; std_comm: number | string | null;
  sup_comm: number | string | null; tax_on_comm: number | string | null; balance_payable: number | string | null; doc_count: number | null;
};
// One fare component of a BSP row. component_type buckets the code by the PDF
// column it sat in: TAX (govt/airport taxes), FEE (Taxes-Fees-&-Charges / F&C —
// carrier surcharges like YQ/YR), or PENALTY (the PEN column).
type BspTax = { component_type: string | null; component_code: string | null; amount: number | null };
type DetailRow = {
  id: number; document_number: string | null; ticket_number: string | null; spdr_no: string | null; transaction_type: string | null;
  airline_accounting_code: string | null; airline_name: string | null; issue_date: string | null;
  cpui: string | null; nr_code: string | null; stat: string | null; form_of_payment: string | null;
  transaction_amount: number | null; fare_amount: number | null; penalty_amount: number | null; net_sales: number | null;
  standard_commission_rate: number | null; standard_commission_amount: number | null;
  supplier_discount_rate: number | null; supplier_discount_amount: number | null;
  tax_on_commission: number | null; balance_payable: number | null;
  taxes: BspTax[] | null;
  tour: string[] | null; alt_document_numbers: string[] | null; rtdn: string | null; esac: string | null; wavr: string | null;
  associated_docs: AssociatedDocs | null;
  match_status: string;
};
// Full continuation-line detail parsed from the BSP detailed PDF: the +RTDN exchange
// document(s) (with reference + EX marker) and any +TKTT conjunction tickets. A row can
// carry several exchanges; `rtdn` is kept as the FIRST exchange for back-compat.
type ExchangeDoc = { doc: string; ref?: string; indicator?: string };
type AssociatedDocs = {
  rtdn?: ExchangeDoc;
  exchanges?: ExchangeDoc[];
  conjunctions?: { doc: string; issue_date?: string; cpui?: string }[];
};

// Exchange tickets for a row, tolerant of statements not yet re-parsed (which only
// carry the single `rtdn`).
function exchangeDocs(a: AssociatedDocs | null | undefined): ExchangeDoc[] {
  if (!a) return [];
  if (a.exchanges?.length) return a.exchanges;
  return a.rtdn ? [a.rtdn] : [];
}

const PAGE = 50;
function inr(v: number | string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}
// Commission / discount rates print as "0.00" on the statement even when zero.
function rate(v: number | string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : n.toFixed(2);
}

function sumAmts(items: BspTax[]): number {
  return items.reduce((s, t) => s + (Number(t.amount) || 0), 0);
}

// Collapsed view: a single BSP row can carry many taxes, so the cell shows only
// the group TOTAL (+ a subtle component count). The full per-code breakdown is in
// the expandable detail panel below the row. `fallback` covers the PEN column,
// where a summed penalty_amount may exist without itemised components.
function TaxTotal({ items, fallback }: { items: BspTax[]; fallback?: number | null }) {
  if (!items.length) {
    return fallback != null
      ? <span className="tabular-nums text-slate-600">{inr(fallback)}</span>
      : <span className="text-slate-300">—</span>;
  }
  return (
    <span className="inline-flex items-baseline justify-end gap-1 whitespace-nowrap">
      <span className="tabular-nums text-slate-600">{inr(sumAmts(items))}</span>
      {items.length > 1 && <span className="text-[9px] text-slate-400 font-medium">{items.length}</span>}
    </span>
  );
}

// Expanded view: one titled group (Tax / F&C / Pen) with a subtotal and a 2-col
// grid of code → amount. Renders nothing when the group is empty.
function TaxGroup({ title, items }: { title: string; items: BspTax[] }) {
  if (!items.length) return null;
  return (
    <div className="min-w-[190px]">
      <div className="flex items-center justify-between gap-6 mb-1.5 pb-1 border-b border-slate-200">
        <span className="text-[10px] uppercase tracking-wide font-semibold text-slate-400">{title}</span>
        <span className="text-[11px] tabular-nums font-medium text-slate-600">{inr(sumAmts(items))}</span>
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1">
        {items.map((t, i) => (
          <div key={i} className="flex items-center justify-between gap-4 text-[11px]">
            <span className="text-slate-400 font-medium">{t.component_code || "—"}</span>
            <span className="tabular-nums text-slate-600">{inr(t.amount)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function hasAssociated(a: AssociatedDocs | null): boolean {
  return !!(a && (a.rtdn || a.exchanges?.length || a.conjunctions?.length));
}

// Expand-panel section listing every +TKTT conjunction ticket and every +RTDN exchange
// ticket, with the fields the flat columns can't hold (ref, EX marker, conjunction date/CPUI).
function RelatedDocs({ data }: { data: AssociatedDocs }) {
  const conjunctions = data.conjunctions ?? [];
  const exchanges = exchangeDocs(data);
  return (
    <>
      {conjunctions.length > 0 && (
        <div className="min-w-55">
          <div className="text-[10px] uppercase tracking-wide font-semibold text-slate-400 mb-1.5 pb-1 border-b border-slate-200">
            Conjunction tickets
          </div>
          <div className="flex flex-col gap-1.5 text-[11px]">
            {conjunctions.map((c, i) => (
              <div key={i} className="flex items-center gap-2 whitespace-nowrap">
                <span className="text-slate-400 font-medium w-14">+TKTT</span>
                <span className="text-slate-600 tabular-nums">{c.doc}</span>
                {c.issue_date && <span className="text-slate-400">· {c.issue_date}</span>}
                {c.cpui && <span className="text-slate-400">· {c.cpui}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
      {exchanges.length > 0 && (
        <div className="min-w-55">
          <div className="text-[10px] uppercase tracking-wide font-semibold text-slate-400 mb-1.5 pb-1 border-b border-slate-200">
            Exchange tickets
          </div>
          <div className="flex flex-col gap-1.5 text-[11px]">
            {exchanges.map((e, i) => (
              <div key={i} className="flex items-center gap-2 whitespace-nowrap">
                <span className="text-slate-400 font-medium w-14">+RTDN</span>
                <span className="text-slate-600 tabular-nums">{e.doc}</span>
                {e.ref && <span className="text-slate-400">· ref {e.ref}</span>}
                {e.indicator && <span className="px-1 py-px rounded bg-amber-100 text-amber-700 text-[9px] font-semibold">{e.indicator}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

type SummaryGroup = {
  key: string; category: string | null; airline_code: string | null;
  airline_iata: string | null; airline_name: string | null; rows: SummaryRow[]; total: SummaryRow;
};

// Group per-airline summary rows (one airline can print CASH / CARD / … sub-lines plus a
// TOTAL). The TOTAL is the airline's headline row; the sub-lines expand beneath it.
// Single-FOP airlines have no TOTAL line — their sole line already IS the total.
function groupSummaryRows(rows: SummaryRow[]): SummaryGroup[] {
  const order: string[] = [];
  const map = new Map<string, SummaryGroup>();
  for (const r of rows) {
    const key = `${r.category ?? ""}::${r.airline_code ?? r.airline_name ?? ""}`;
    let g = map.get(key);
    if (!g) {
      g = { key, category: r.category, airline_code: r.airline_code, airline_iata: r.airline_iata,
        airline_name: r.airline_name, rows: [], total: r };
      map.set(key, g); order.push(key);
    }
    g.rows.push(r);
  }
  for (const g of map.values()) {
    g.total = g.rows.find((r) => (r.fop ?? "").toUpperCase() === "TOTAL")
      ?? g.rows.find((r) => r.balance_payable != null)
      ?? g.rows[g.rows.length - 1];
  }
  return order.map((k) => map.get(k)!);
}

// The per-airline financial lines cross-checked between the two summaries. Money only,
// ±1 tolerance; doc_count is excluded because the uploaded PDF and the detailed statement
// count documents differently.
const COMPARE_FIELDS: (keyof SummaryRow)[] = [
  "issues", "refunds", "debit_memos", "credit_memos", "std_comm", "sup_comm", "tax_on_comm", "balance_payable",
];

// Cross-compare the uploaded vs calculated per-airline summaries by their TOTAL line.
// Returns, per airline group key, the set of columns whose totals differ (used to flag
// mismatches in red in BOTH summary tabs). An airline present in only one summary flags
// every field. Returns null until both datasets are loaded.
function diffSummaries(uploaded: SummaryRow[] | null, calculated: SummaryRow[] | null): Map<string, Set<string>> | null {
  if (!uploaded || !calculated) return null;
  const indexTotals = (rows: SummaryRow[]) => {
    const m = new Map<string, SummaryRow>();
    for (const g of groupSummaryRows(rows)) m.set(g.key, g.total);
    return m;
  };
  const up = indexTotals(uploaded), calc = indexTotals(calculated);
  const numOf = (v: number | string | null) => { const n = v == null || v === "" ? 0 : Number(v); return Number.isFinite(n) ? n : 0; };
  const out = new Map<string, Set<string>>();
  for (const key of new Set([...up.keys(), ...calc.keys()])) {
    const u = up.get(key), c = calc.get(key);
    const bad = new Set<string>();
    for (const f of COMPARE_FIELDS) {
      if (!u || !c || Math.abs(numOf(u[f] as number | string | null) - numOf(c[f] as number | string | null)) > 1) bad.add(f);
    }
    if (bad.size) out.set(key, bad);
  }
  return out;
}

// The grouped per-airline summary table + its filter toolbar. Reused by both the
// "Summary (per-airline)" tab (rows from the uploaded PDF) and the "Summary (from
// detailed)" tab (rows aggregated from the detailed statement). Owns its own filter +
// expand state so the two instances are independent. `toolbarExtra` is an optional slot
// (e.g. the Re-parse button, which only makes sense for the uploaded-PDF summary).
function SummaryTable({ rows, emptyText = "No summary rows.", toolbarExtra, mismatches }:
  { rows: SummaryRow[] | null; emptyText?: string; toolbarExtra?: ReactNode; mismatches?: Map<string, Set<string>> | null }) {
  const [search, setSearch] = useState("");
  const [cat, setCat] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (key: string) => setExpanded((prev) => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  const cats = useMemo(() => Array.from(new Set((rows ?? []).map((r) => r.category).filter(Boolean))) as string[], [rows]);
  const filtered = useMemo(() => {
    if (!rows) return null;
    const q = search.trim().toLowerCase();
    return rows.filter((r) =>
      (!q || [r.airline_code, r.airline_iata, r.airline_name, r.category].some((v) => (v ?? "").toLowerCase().includes(q))) &&
      (!cat || r.category === cat));
  }, [rows, search, cat]);
  const hasFilters = !!(search || cat);
  const groups = useMemo(() => (filtered ? groupSummaryRows(filtered) : null), [filtered]);

  return (
    <div className="rounded-xl border border-slate-200 overflow-hidden">
      <div className="flex items-center gap-2 flex-wrap px-3 py-2.5 border-b border-slate-100 bg-slate-50/40">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search airline / category…"
            className="pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs w-56 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white" />
        </div>
        <select value={cat} onChange={(e) => setCat(e.target.value)}
          className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
          <option value="">All categories</option>
          {cats.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        {hasFilters && (
          <button onClick={() => { setSearch(""); setCat(""); }}
            className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"><X className="w-3.5 h-3.5" /> Clear</button>
        )}
        <div className="ml-auto flex items-center gap-3">
          {toolbarExtra}
          <span className="text-[11px] text-slate-400">{groups?.length ?? 0} airlines</span>
        </div>
      </div>
      <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400">
            <th className="text-left px-3 py-2 font-semibold">Category</th>
            <th className="text-left px-3 py-2 font-semibold">Airline</th>
            <th className="text-left px-3 py-2 font-semibold">FOP</th>
            <th className="text-right px-3 py-2 font-semibold">Issues</th>
            <th className="text-right px-3 py-2 font-semibold">Refunds</th>
            <th className="text-right px-3 py-2 font-semibold">Debits</th>
            <th className="text-right px-3 py-2 font-semibold">Credits</th>
            <th className="text-right px-3 py-2 font-semibold">STD</th>
            <th className="text-right px-3 py-2 font-semibold">SUP</th>
            <th className="text-right px-3 py-2 font-semibold">Tax on Comm</th>
            <th className="text-right px-3 py-2 font-semibold">Balance</th>
            <th className="text-right px-3 py-2 font-semibold">Docs</th>
          </tr>
        </thead>
        <tbody>
          {groups === null ? (
            <tr><td colSpan={12} className="px-3 py-8 text-center text-slate-400">Loading…</td></tr>
          ) : groups.length === 0 ? (
            <tr><td colSpan={12} className="px-3 py-8 text-center text-slate-400">{hasFilters ? "No airlines match the filters." : emptyText}</td></tr>
          ) : groups.map((g) => {
            const t = g.total;
            const canExpand = g.rows.length > 1;
            const isOpen = canExpand && expanded.has(g.key);
            // Columns whose totals disagree with the OTHER summary → shown in red.
            const bad = mismatches?.get(g.key);
            const cell = (f: string, base = "text-slate-600") =>
              `px-3 py-2 text-right tabular-nums ${bad?.has(f) ? "text-red-600 font-semibold" : base}`;
            return (
            <Fragment key={g.key}>
              <tr onClick={canExpand ? () => toggle(g.key) : undefined}
                className={`border-b border-slate-100 ${canExpand ? "cursor-pointer" : ""} ${isOpen ? "bg-blue-50/40" : "hover:bg-slate-50/60"}`}>
                <td className="px-3 py-2 text-[11px] text-slate-500">{g.category}</td>
                <td className="px-3 py-2 text-slate-700 whitespace-nowrap">
                  <span className="inline-flex items-center gap-1.5">
                    {canExpand
                      ? <ChevronRight className={`w-3.5 h-3.5 shrink-0 transition-transform ${isOpen ? "rotate-90 text-blue-500" : "text-slate-300"}`} />
                      : <span className="inline-block w-3.5 shrink-0" />}
                    <span className="font-medium">{g.airline_code} {g.airline_iata}</span>
                    <span className="text-[11px] text-slate-400">{g.airline_name}</span>
                  </span>
                </td>
                <td className="px-3 py-2 text-[11px] font-medium text-slate-400">{(t.fop ?? "").toUpperCase() === "TOTAL" ? "Total" : (t.fop || "—")}</td>
                <td className={cell("issues")}>{inr(t.issues)}</td>
                <td className={cell("refunds")}>{inr(t.refunds)}</td>
                <td className={cell("debit_memos")}>{inr(t.debit_memos)}</td>
                <td className={cell("credit_memos")}>{inr(t.credit_memos)}</td>
                <td className={cell("std_comm")}>{inr(t.std_comm)}</td>
                <td className={cell("sup_comm")}>{inr(t.sup_comm)}</td>
                <td className={cell("tax_on_comm")}>{inr(t.tax_on_comm)}</td>
                <td className={cell("balance_payable", "font-medium text-slate-800")}>{inr(t.balance_payable)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-500">{t.doc_count ?? "—"}</td>
              </tr>
              {isOpen && g.rows.map((r) => (
                <tr key={r.id} className="border-b border-slate-100 bg-blue-50/10">
                  <td className="px-3 py-1.5"></td>
                  <td className="px-3 py-1.5"></td>
                  <td className="px-3 py-1.5 text-[11px] font-medium text-slate-500">{r.fop || "—"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{inr(r.issues)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{inr(r.refunds)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{inr(r.debit_memos)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{inr(r.credit_memos)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{inr(r.std_comm)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{inr(r.sup_comm)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{inr(r.tax_on_comm)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{inr(r.balance_payable)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[11px] text-slate-500">{r.doc_count ?? "—"}</td>
                </tr>
              ))}
            </Fragment>
            );
          })}
        </tbody>
      </table>
      </div>
    </div>
  );
}

type Tab = "reconciliation" | "summary" | "bsp_summary" | "detailed";

export default function BspGroupDetail({ group, onBack }: { group: BspGroup; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>("reconciliation");

  // reconciliation
  const [comp, setComp] = useState<{ match_status: string; lines: CompLine[] } | null>(null);
  // summary rows
  const [srows, setSrows] = useState<SummaryRow[] | null>(null);
  // detailed rows
  const [drows, setDrows] = useState<DetailRow[]>([]);
  const [dtotal, setDtotal] = useState(0);
  const [doffset, setDoffset] = useState(0);
  const [dloading, setDloading] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());  // detail-row ids whose tax breakdown is open
  const toggleRow = (id: number) => setExpanded((prev) => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });
  // detailed-rows filters (server-side) + dropdown facets
  const [dSearch, setDSearch] = useState("");
  const [dTxn, setDTxn] = useState("");
  const [dFop, setDFop] = useState("");
  const [dAir, setDAir] = useState("");
  const [facets, setFacets] = useState<{ txn_types: string[]; fops: string[]; airlines: string[] }>({ txn_types: [], fops: [], airlines: [] });
  const [dReparsing, setDReparsing] = useState(false);
  const dHasFilters = !!(dSearch || dTxn || dFop || dAir);
  const clearDetailFilters = () => { setDSearch(""); setDTxn(""); setDFop(""); setDAir(""); };

  // Per-airline summary aggregated FROM the detailed statement (the "Summary (from
  // detailed)" tab) — computed server-side, same shape as the uploaded summary rows.
  const [bsrows, setBsrows] = useState<SummaryRow[] | null>(null);

  useEffect(() => {
    api.get(`/bsp/groups/${group.group_id}`).then(({ data }) => setComp(data)).catch(() => {});
  }, [group.group_id]);

  const [sReparsing, setSReparsing] = useState(false);

  const loadSummary = useCallback(async () => {
    if (!group.summary_batch_id) return;
    try {
      const { data } = await api.get<SummaryRow[]>(`/bsp/summary/${group.summary_batch_id}/rows`);
      setSrows(data);
    } catch { setSrows([]); }
  }, [group.summary_batch_id]);

  // Per-airline summary computed live from the detailed statement rows (server-side aggregation).
  const loadBspSummary = useCallback(async () => {
    if (!group.detail_batch_id) return;
    try {
      const { data } = await api.get<SummaryRow[]>(`/bsp/statements/${group.detail_batch_id}/summary`);
      setBsrows(data);
    } catch { setBsrows([]); }
  }, [group.detail_batch_id]);

  // Re-run the parser on the stored summary PDF, then poll until it finishes and
  // reload the rows — used to backfill the CASH/CARD breakdown on older summaries.
  const reparseSummary = useCallback(async () => {
    if (!group.summary_batch_id || sReparsing) return;
    setSReparsing(true);
    try {
      await api.post(`/bsp/summary/${group.summary_batch_id}/reparse`);
      toast.success("Re-parsing the summary…");
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const { data } = await api.get<{ status: string }>(`/bsp/summary/${group.summary_batch_id}`);
        if (data.status === "completed") { toast.success("Summary updated."); break; }
        if (data.status === "failed") { toast.error("Re-parse failed — check the worker logs."); break; }
      }
      await loadSummary();
    } catch {
      toast.error("Could not start the re-parse.");
    } finally {
      setSReparsing(false);
    }
  }, [group.summary_batch_id, sReparsing, loadSummary]);

  const loadDetail = useCallback(async (offset: number) => {
    if (!group.detail_batch_id) return;
    setDloading(true);
    try {
      const { data } = await api.get<{ total: number; rows: DetailRow[] }>(
        `/bsp/statements/${group.detail_batch_id}/rows`,
        { params: { offset, limit: PAGE, search: dSearch || undefined, txn_type: dTxn || undefined, fop: dFop || undefined, air: dAir || undefined } });
      setDrows(data.rows); setDtotal(data.total); setDoffset(offset); setExpanded(new Set());
    } catch { setDrows([]); }
    finally { setDloading(false); }
  }, [group.detail_batch_id, dSearch, dTxn, dFop, dAir]);

  // Re-run the parser on the stored detailed PDF, then poll until it finishes and
  // reload — used to backfill parser fixes (e.g. the TOUR/ESAC split) on statements
  // parsed before them. Large statements take minutes, so the poll window is wide.
  const reparseDetail = useCallback(async () => {
    if (!group.detail_batch_id || dReparsing) return;
    setDReparsing(true);
    try {
      await api.post(`/bsp/statements/${group.detail_batch_id}/reparse`);
      toast.success("Re-parsing the statement — large files take a few minutes…");
      let done = false;
      for (let i = 0; i < 80; i++) {           // up to ~4 min
        await new Promise((r) => setTimeout(r, 3000));
        const { data } = await api.get<{ status: string }>(`/bsp/statements/${group.detail_batch_id}`);
        if (data.status === "completed") { done = true; break; }
        if (data.status === "failed") { toast.error("Re-parse failed — check the worker logs."); break; }
      }
      if (done) { toast.success("Statement updated."); await loadDetail(0); }
      else { toast("Still processing — reload in a moment to see the update.", { icon: "⏳" }); }
    } catch {
      toast.error("Could not start the re-parse.");
    } finally {
      setDReparsing(false);
    }
  }, [group.detail_batch_id, dReparsing, loadDetail]);

  // Either summary tab loads BOTH datasets, so the uploaded-vs-calculated mismatch
  // comparison (red highlighting + tab counts) works regardless of which one is open.
  const onSummaryTab = tab === "summary" || tab === "bsp_summary";
  useEffect(() => { if (onSummaryTab && srows === null) loadSummary(); }, [onSummaryTab, srows, loadSummary]);
  useEffect(() => { if (onSummaryTab && bsrows === null) loadBspSummary(); }, [onSummaryTab, bsrows, loadBspSummary]);

  // Airlines whose uploaded vs calculated totals disagree (null until both are loaded).
  const summaryMismatch = useMemo(() => diffSummaries(srows, bsrows), [srows, bsrows]);
  const mismatchCount = summaryMismatch?.size ?? 0;

  // Load filter dropdown values once when the detailed tab first opens.
  useEffect(() => {
    if (tab === "detailed" && group.detail_batch_id && facets.txn_types.length === 0 && facets.fops.length === 0 && facets.airlines.length === 0) {
      api.get(`/bsp/statements/${group.detail_batch_id}/rows/facets`).then(({ data }) => setFacets(data)).catch(() => {});
    }
  }, [tab, group.detail_batch_id, facets]);

  // (Re)load rows from page 0 when on the detailed tab or when a filter changes (debounced for typing).
  useEffect(() => {
    if (tab !== "detailed") return;
    const t = setTimeout(() => loadDetail(0), 250);
    return () => clearTimeout(t);
  }, [tab, loadDetail]);


  const openPdf = async (kind: "summary" | "detail") => {
    const url = kind === "summary"
      ? `/bsp/summary/${group.summary_batch_id}/file-url`
      : `/bsp/statements/${group.detail_batch_id}/file-url`;
    try {
      const { data } = await api.get<{ url: string }>(url);
      window.open(data.url, "_blank");
    } catch { toast.error("Could not open the PDF."); }
  };

  // Download the data (not the PDF) as an Excel workbook, filled with the same rows
  // shown in the "Summary Uploaded" / "Detailed rows" tabs.
  const [xlsBusy, setXlsBusy] = useState<"summary" | "detail" | null>(null);
  const downloadXlsx = async (kind: "summary" | "detail") => {
    const id = kind === "summary" ? group.summary_batch_id : group.detail_batch_id;
    if (!id) return;
    const url = kind === "summary" ? `/bsp/summary/${id}/xlsx` : `/bsp/statements/${id}/xlsx`;
    setXlsBusy(kind);
    try {
      const res = await api.get(url, { responseType: "blob" });
      const href = window.URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = href;
      a.download = `bsp-${kind === "summary" ? "summary" : "detailed"}-${group.reference || group.agent_code || id}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(href);
    } catch {
      toast.error("Could not download the XLS.");
    } finally {
      setXlsBusy(null);
    }
  };

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <button onClick={onBack} className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-700">
          <ArrowLeft className="w-3.5 h-3.5" /> Back
        </button>
        <span className="text-slate-300">|</span>
        <h2 className="text-sm font-semibold text-slate-800">
          BSP · {group.agent_code || "—"}
          {group.agent_name ? <span className="text-slate-400 font-normal"> · {group.agent_name}</span> : null}
        </h2>
      </div>

      <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
        <div className="text-xs text-slate-500">
          <span className="text-slate-400">Period:</span> {group.period_from} → {group.period_to}
          {group.reference ? <> · <span className="text-slate-400">Ref:</span> {group.reference}</> : null}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => openPdf("summary")} disabled={!group.summary_batch_id}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40">
            <FileText className="w-3.5 h-3.5 text-red-500" /> Summary PDF <ExternalLink className="w-3 h-3" />
          </button>
          <button onClick={() => downloadXlsx("summary")} disabled={!group.summary_batch_id || xlsBusy === "summary"}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-700 border border-emerald-200 rounded-lg hover:bg-emerald-50 disabled:opacity-40">
            {xlsBusy === "summary" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-600" />} Summary XLS
          </button>
          <span className="w-px h-5 bg-slate-200" />
          <button onClick={() => openPdf("detail")} disabled={!group.detail_batch_id}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40">
            <FileText className="w-3.5 h-3.5 text-red-500" /> Detailed PDF <ExternalLink className="w-3 h-3" />
          </button>
          <button onClick={() => downloadXlsx("detail")} disabled={!group.detail_batch_id || xlsBusy === "detail"}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-700 border border-emerald-200 rounded-lg hover:bg-emerald-50 disabled:opacity-40">
            {xlsBusy === "detail" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-600" />} Detailed XLS
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-slate-200 mb-4">
        {([["reconciliation", "Reconciliation"], ["summary", "Summary Uploaded"], ["bsp_summary", "Summary (Calculated from detailed)"], ["detailed", "Detailed rows"]] as [Tab, string][]).map(([t, label]) => (
          <button key={t} onClick={() => setTab(t)}
            className={`inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold border-b-2 -mb-px transition-colors ${
              tab === t ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {label}
            {mismatchCount > 0 && (t === "summary" || t === "bsp_summary") && (
              <span title={`${mismatchCount} airline${mismatchCount === 1 ? "" : "s"} differ between the uploaded and calculated summaries`}
                className="inline-flex items-center justify-center min-w-4 h-4 px-1 rounded-full bg-red-100 text-red-600 text-[10px] font-bold">{mismatchCount}</span>
            )}
          </button>
        ))}
      </div>

      {/* Reconciliation */}
      {tab === "reconciliation" && (
        comp ? <BspComparisonPanel matchStatus={comp.match_status} lines={comp.lines} />
             : <div className="py-8 text-center text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin inline" /> Loading…</div>
      )}

      {/* Summary (per-airline) — parsed from the uploaded summary PDF */}
      {tab === "summary" && (
        <SummaryTable
          rows={srows}
          mismatches={summaryMismatch}
          toolbarExtra={
            <button onClick={reparseSummary} disabled={sReparsing || !group.summary_batch_id}
              title="Re-read the stored PDF to refresh the CASH / CARD breakdown"
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40">
              {sReparsing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              {sReparsing ? "Re-parsing…" : "Re-parse"}
            </button>
          }
        />
      )}

      {/* Summary (from detailed) — same format, aggregated from the detailed statement */}
      {tab === "bsp_summary" && (
        <SummaryTable rows={bsrows} mismatches={summaryMismatch} emptyText="No detailed rows to summarize yet." />
      )}

      {/* Detailed transaction rows */}
      {tab === "detailed" && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="flex items-center gap-2 flex-wrap px-3 py-2.5 border-b border-slate-100 bg-slate-50/40">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
              <input value={dSearch} onChange={(e) => setDSearch(e.target.value)} placeholder="Search document / ticket #…"
                className="pl-8 pr-3 py-1.5 border border-slate-200 rounded-lg text-xs w-60 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white" />
            </div>
            <select value={dTxn} onChange={(e) => setDTxn(e.target.value)}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
              <option value="">All Txn</option>
              {facets.txn_types.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <select value={dFop} onChange={(e) => setDFop(e.target.value)}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
              <option value="">All FOP</option>
              {facets.fops.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <select value={dAir} onChange={(e) => setDAir(e.target.value)}
              className="border border-slate-200 rounded-lg px-2 py-1.5 text-xs bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
              <option value="">All Airlines</option>
              {facets.airlines.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            {dHasFilters && (
              <button onClick={clearDetailFilters}
                className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"><X className="w-3.5 h-3.5" /> Clear</button>
            )}
            <div className="ml-auto flex items-center gap-3">
              <button onClick={reparseDetail} disabled={dReparsing || !group.detail_batch_id}
                title="Re-read the stored PDF to backfill parser fixes (e.g. the TOUR / ESAC split)"
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-40">
                {dReparsing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                {dReparsing ? "Re-parsing…" : "Re-parse"}
              </button>
              <span className="text-[11px] text-slate-400">{dtotal.toLocaleString("en-IN")} rows</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                {/* Single-row header. TAX / F&C / PEN are the three Taxes-Fees-&-Charges
                    columns; STD %/COMM and SUPP %/DISC are the commission rate + amount pairs. */}
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-400 [&>th]:px-3 [&>th]:py-2 [&>th]:font-semibold [&>th]:whitespace-nowrap">
                  <th className="text-left">Document #</th>
                  <th className="text-left">Ticket No</th>
                  <th className="text-left">Txn</th>
                  <th className="text-left">Air</th>
                  <th className="text-left">Airline</th>
                  <th className="text-left">Date</th>
                  <th className="text-left">CPUI</th>
                  <th className="text-left">NR</th>
                  <th className="text-left">STAT</th>
                  <th className="text-left">FOP</th>
                  <th className="text-right">Txn Amt</th>
                  <th className="text-right">Fare</th>
                  <th className="text-right">Tax</th>
                  <th className="text-right">F&amp;C</th>
                  <th className="text-right">Pen</th>
                  <th className="text-right">Net Sales</th>
                  <th className="text-right">Std %</th>
                  <th className="text-right">Std Comm</th>
                  <th className="text-right">Supp %</th>
                  <th className="text-right">Supp Disc</th>
                  <th className="text-right">Tax/Comm</th>
                  <th className="text-right">Balance</th>
                  <th className="text-left">Conjunction Ticket</th>
                  <th className="text-left">Exchange Ticket</th>
                  <th className="text-left">Tour</th>
                  <th className="text-left">Alt Docs</th>
                  <th className="text-left">SPDR No</th>
                  <th className="text-left">RTDN</th>
                  <th className="text-left">ESAC</th>
                  <th className="text-left">WAVR</th>
                </tr>
              </thead>
              <tbody>
                {dloading ? (
                  <tr><td colSpan={30} className="px-3 py-8 text-center text-slate-400">Loading…</td></tr>
                ) : drows.length === 0 ? (
                  <tr><td colSpan={30} className="px-3 py-8 text-center text-slate-400">{dHasFilters ? "No rows match the filters." : "No rows."}</td></tr>
                ) : drows.map((r) => {
                  const comps = r.taxes ?? [];
                  const tax = comps.filter((t) => t.component_type === "TAX");
                  const fc = comps.filter((t) => t.component_type === "FEE");
                  const pen = comps.filter((t) => t.component_type === "PENALTY");
                  const isOpen = expanded.has(r.id);
                  const hasBreakdown = comps.length > 0;
                  const related = r.associated_docs;
                  const hasRelated = hasAssociated(related);
                  const conj = r.alt_document_numbers ?? [];          // +TKTT conjunction tickets
                  const exch = exchangeDocs(related);                 // +RTDN exchange tickets
                  return (
                  <Fragment key={r.id}>
                  <tr onClick={() => toggleRow(r.id)}
                    className={`border-b border-slate-100 cursor-pointer ${isOpen ? "bg-blue-50/40" : "hover:bg-slate-50/60"}`}>
                    <td className="px-3 py-2 text-slate-700 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5">
                        <ChevronRight className={`w-3.5 h-3.5 shrink-0 transition-transform ${isOpen ? "rotate-90 text-blue-500" : "text-slate-300"}`} />
                        {r.document_number || r.ticket_number || "—"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-600 whitespace-nowrap">
                      {r.ticket_number || <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-500">{r.transaction_type}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500">{r.airline_accounting_code}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-600 whitespace-nowrap max-w-40 truncate" title={r.airline_name ?? undefined}>{r.airline_name || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{r.issue_date || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{r.cpui || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{r.nr_code || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500">{r.stat || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500">{r.form_of_payment || "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{inr(r.transaction_amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{inr(r.fare_amount)}</td>
                    <td className="px-3 py-2 text-right"><TaxTotal items={tax} /></td>
                    <td className="px-3 py-2 text-right"><TaxTotal items={fc} /></td>
                    <td className="px-3 py-2 text-right"><TaxTotal items={pen} fallback={r.penalty_amount} /></td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{inr(r.net_sales)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-[11px] text-slate-500">{rate(r.standard_commission_rate)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{inr(r.standard_commission_amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-[11px] text-slate-500">{rate(r.supplier_discount_rate)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{inr(r.supplier_discount_amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{inr(r.tax_on_commission)}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium text-slate-800">{inr(r.balance_payable)}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-600 whitespace-nowrap">
                      {conj.length ? (
                        <span className="inline-flex items-center gap-1">
                          <span className="tabular-nums">{conj[0]}</span>
                          {conj.length > 1 && <span className="text-[9px] text-slate-400 font-medium">+{conj.length - 1}</span>}
                        </span>
                      ) : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-600 whitespace-nowrap">
                      {exch.length ? (
                        <span className="inline-flex items-center gap-1">
                          <span className="tabular-nums">{exch[0].doc}</span>
                          {exch.length > 1 && <span className="text-[9px] text-slate-400 font-medium">+{exch.length - 1}</span>}
                          {exch.some((e) => e.indicator === "EX") && (
                            <span className="px-1 py-px rounded bg-amber-100 text-amber-700 text-[9px] font-semibold">EX</span>
                          )}
                        </span>
                      ) : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{r.tour?.length ? r.tour.join(" · ") : "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{r.alt_document_numbers?.length ? r.alt_document_numbers.join(" · ") : "—"}</td>
                    <td className="px-3 py-2 text-[11px] whitespace-nowrap">{r.spdr_no ? <span className="text-blue-600 tabular-nums">{r.spdr_no}</span> : <span className="text-slate-300">—</span>}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">
                      {related?.rtdn ? (
                        <span className="inline-flex items-center gap-1">
                          {related.rtdn.doc}
                          {related.rtdn.ref && <span className="text-slate-400">· {related.rtdn.ref}</span>}
                          {related.rtdn.indicator && <span className="px-1 py-px rounded bg-amber-100 text-amber-700 text-[9px] font-semibold">{related.rtdn.indicator}</span>}
                        </span>
                      ) : (r.rtdn || "—")}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{r.esac || "—"}</td>
                    <td className="px-3 py-2 text-[11px] text-slate-500 whitespace-nowrap">{r.wavr || "—"}</td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-slate-100 bg-blue-50/20">
                      <td colSpan={30} className="px-10 py-3.5">
                        <div className="text-[10px] uppercase tracking-wide font-semibold text-slate-400 mb-2.5">
                          Fare components · {r.document_number || r.ticket_number || ""}
                        </div>
                        {hasBreakdown || hasRelated ? (
                          <div className="flex flex-wrap gap-x-12 gap-y-4">
                            <TaxGroup title="Tax" items={tax} />
                            <TaxGroup title="Taxes, Fees & Charges (F&C)" items={fc} />
                            <TaxGroup title="Penalty (PEN)" items={pen} />
                            {hasRelated && related && <RelatedDocs data={related} />}
                          </div>
                        ) : (
                          <div className="text-xs text-slate-400">No tax, fee or penalty components recorded for this ticket.</div>
                        )}
                      </td>
                    </tr>
                  )}
                  </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          {dtotal > 0 && (
            <div className="flex items-center justify-between px-3 py-2.5 border-t border-slate-100 text-xs text-slate-500">
              <span>Showing {dtotal === 0 ? 0 : doffset + 1}–{Math.min(doffset + drows.length, dtotal)} of {dtotal.toLocaleString("en-IN")}</span>
              <div className="flex items-center gap-1">
                <button disabled={doffset === 0 || dloading} onClick={() => loadDetail(Math.max(0, doffset - PAGE))}
                  className="flex items-center gap-1 px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40"><ChevronLeft className="w-3.5 h-3.5" /> Prev</button>
                <button disabled={doffset + PAGE >= dtotal || dloading} onClick={() => loadDetail(doffset + PAGE)}
                  className="flex items-center gap-1 px-2 py-1 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40">Next <ChevronRight className="w-3.5 h-3.5" /></button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
