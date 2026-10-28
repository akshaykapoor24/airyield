"use client";

// A consolidator statement (Third Party GDS / LCC) line by line, for Commission income:
// what the vendor's statement says it paid you, against what your deals say you earned.
//
// Seven cards — Total tickets · Matched · Unmatched · Commission in statement · IATA
// commission · Expected commission · Difference — each of which filters the table. IATA
// commission is the matched deal's IATA % on the basic fare: part of Expected, and its own
// card, as it is a different entitlement from the deal's incentive. The table is every ticket
// line of the statement, run or not, with the statement's own columns as the vendor printed
// them; then the deal it matched; then the commission check pinned to the right edge, so
// the three figures that matter stay in view however far the statement scrolls.
//
// The money cards add up on screen: expected − statement = difference, over the lines a
// run has calculated (services/commission/statement_lines.py). Selection, running and the
// diagnosis popup stay with the parent, which owns the header's Run selected button.

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Info, Play, Search, X } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CommissionSource } from "@/lib/commissionSources";
import Pagination from "@/components/ui/Pagination";
import AppliedDealModal from "./AppliedDealModal";
import {
  CommissionLine, CommissionLinesPage, CommissionRow, LineBucket, STATUS_STYLE, inr,
} from "./types";

const PAGE = 50;

// The pinned commission check: widths fixed so each sticky cell knows its right offset.
const PIN = { statement: 112, expected: 112, difference: 112, actions: 80 };
const PIN_RIGHT = {
  actions: 0,
  difference: PIN.actions,
  expected: PIN.actions + PIN.difference,
  statement: PIN.actions + PIN.difference + PIN.expected,
};
const pinStyle = (k: keyof typeof PIN) => ({ right: PIN_RIGHT[k], width: PIN[k], minWidth: PIN[k] });

const BUCKET_LABEL: Record<LineBucket, string> = {
  all: "All tickets", matched: "Matched", unmatched: "Unmatched",
  other: "Excluded / skipped", pending: "Not calculated",
  statement: "With commission in statement", iata: "With IATA commission",
  expected: "With expected commission",
  difference: "With a difference",
};

const rupees = (v: number) => `${v < 0 ? "−" : ""}₹${inr(Math.abs(v))}`;

/** expected − statement: amber when the vendor paid less than your deal says. */
function Difference({ v }: { v: number | null }) {
  if (v == null) return <span className="text-slate-300">—</span>;
  if (Math.abs(v) < 1) return <span className="text-emerald-600">₹{inr(v)}</span>;
  if (v > 0) return <span className="text-amber-700 font-semibold">+₹{inr(v)}</span>;
  return <span className="text-slate-500 font-semibold">−₹{inr(Math.abs(v))}</span>;
}

function cellValue(v: string | number | null | undefined, money: boolean) {
  if (v === null || v === undefined || v === "") return <span className="text-slate-300">—</span>;
  if (money) {
    const n = Number(v);
    return Number.isNaN(n) ? String(v) : inr(n);
  }
  return String(v);
}

/** Where the expected figure comes from, for its tooltip. */
function expectedTitle(ln: CommissionLine): string | undefined {
  const c = ln.calc;
  if (!c) return "Not calculated yet — run this line or the whole statement";
  const parts = Object.entries(c.incentive_breakdown ?? {}).map(([k, v]) => `${k}: ₹${inr(v)}`);
  if (c.iata_commission) parts.push(`IATA commission: ₹${inr(c.iata_commission)}`);
  return parts.length ? parts.join("\n") : c.commission_reason || undefined;
}

export default function ThirdPartyStatementLines({
  source, batchId, refreshKey, selected, onToggle, onToggleMany, busyRows, onRun, onDiagnose,
}: {
  source: CommissionSource;
  batchId: string;
  /** Bumped by the parent after a run, a refresh or a finished calculation. */
  refreshKey: number;
  selected: Set<number>;
  onToggle: (lineId: number) => void;
  onToggleMany: (lineIds: number[], on: boolean) => void;
  busyRows: Set<number>;
  onRun: (lineIds: number[]) => void;
  onDiagnose: (row: CommissionRow) => void;
}) {
  const [bucket, setBucket] = useState<LineBucket>("all");
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");      // the search actually sent, on Enter
  const [air, setAir] = useState("");
  const [txn, setTxn] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<CommissionLinesPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // The calculation whose deal popup is open (the Matched deal chip).
  const [appliedCalc, setAppliedCalc] = useState<number | null>(null);

  // Only the latest request may land: clicking through cards quickly must not let a slow
  // earlier answer overwrite the one on screen.
  const latest = useRef(0);
  const load = useCallback(async () => {
    const req = ++latest.current;
    setLoading(true);
    try {
      const { data } = await api.get<CommissionLinesPage>(`${source.apiBase}/statements/${batchId}/lines`, {
        params: { bucket, search: applied || undefined, air: air || undefined, txn: txn || undefined,
                  offset, limit: PAGE },
      });
      if (req === latest.current) { setPage(data); setError(""); }
    } catch {
      if (req === latest.current) setError("Could not load the statement's lines.");
    } finally {
      if (req === latest.current) setLoading(false);
    }
  }, [source.apiBase, batchId, bucket, applied, air, txn, offset]);

  useEffect(() => { load(); }, [load, refreshKey]);

  // A new filter starts from the first page; the selection is the parent's and survives.
  const pick = (b: LineBucket) => { setBucket(b); setOffset(0); };
  const t = page?.totals;
  const cols = page?.columns ?? [];
  const rows = page?.rows ?? [];
  const filtered = bucket !== "all" || !!applied || !!air || !!txn;
  const clear = () => { setBucket("all"); setSearch(""); setApplied(""); setAir(""); setTxn(""); setOffset(0); };

  const pageIds = rows.map((r) => r.line_id);
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const diff = t?.difference ?? 0;

  return (
    <div>
      {/* ── Cards: each one is a filter ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3 mb-4">
        <Card label="Total tickets" active={bucket === "all"} onClick={() => pick("all")}
          value={(t?.tickets ?? 0).toLocaleString("en-IN")}
          sub={t && (t.other || t.pending) ? (
            <>
              {t.other > 0 && (
                <SubLink onClick={() => pick("other")} active={bucket === "other"}>
                  {t.other} excluded / skipped
                </SubLink>
              )}
              {t.other > 0 && t.pending > 0 && " · "}
              {t.pending > 0 && (
                <SubLink onClick={() => pick("pending")} active={bucket === "pending"}>
                  {t.pending} not calculated
                </SubLink>
              )}
            </>
          ) : "in this statement"} />
        <Card label="Matched" tone="text-emerald-700" active={bucket === "matched"} onClick={() => pick("matched")}
          value={(t?.matched ?? 0).toLocaleString("en-IN")} sub="a deal was found" />
        <Card label="Unmatched" tone="text-orange-600" active={bucket === "unmatched"} onClick={() => pick("unmatched")}
          value={(t?.unmatched ?? 0).toLocaleString("en-IN")}
          sub={`no ${source.dealKindLabel} deal found`} />
        <Card label="Commission in statement" active={bucket === "statement"} onClick={() => pick("statement")}
          value={rupees(t?.statement_commission ?? 0)}
          title="The vendor's Agent Commission + Incentive, gross of TDS — counted as earned on a sale and given back on a refund, whichever sign the file prints."
          sub={t && t.statement_pending
            ? `+ ${rupees(t.statement_pending)} on lines not calculated`
            : "what the vendor paid"} />
        <Card label="IATA commission" tone="text-teal-700" active={bucket === "iata"} onClick={() => pick("iata")}
          value={rupees(t?.iata_commission ?? 0)}
          title="The matched deal's IATA commission % applied to each ticket's basic fare. ₹0 on a line whose deal has no IATA %."
          sub={t && t.with_iata
            ? `deal IATA % × basic fare · ${t.with_iata} ticket${t.with_iata === 1 ? "" : "s"}`
            : "no matched deal has an IATA %"} />
        <Card label="Expected commission" tone="text-emerald-700" active={bucket === "expected"} onClick={() => pick("expected")}
          value={rupees(t?.expected_commission ?? 0)}
          title="What your matched deals compute for these tickets: incentive plus IATA commission."
          sub={t && t.iata_commission
            ? `incentive ${rupees(t.incentive)} + IATA ${rupees(t.iata_commission)}`
            : "as per your deals"} />
        <Card label="Difference" active={bucket === "difference"} onClick={() => pick("difference")}
          tone={Math.abs(diff) < 1 ? "text-emerald-700" : diff > 0 ? "text-amber-700" : "text-slate-600"}
          value={`${diff > 0 ? "+" : ""}${rupees(diff)}`}
          title="Expected minus statement. Positive: the vendor paid you less than your deals say — they owe you. Negative: they paid more."
          sub={
            <>
              {Math.abs(diff) < 1 ? "matches your deals" : diff > 0 ? "they owe you" : "paid more than your deals"}
              {t && t.differing > 0 && ` · ${t.differing} ticket${t.differing === 1 ? "" : "s"}`}
            </>
          } />
      </div>

      {/* The vendor's own arithmetic not closing is usually a mapping problem — say so once. */}
      {t && t.unverified > 0 && (
        <div className="flex items-start gap-2 px-3 py-2 mb-3 rounded-lg border border-amber-200 bg-amber-50 text-xs text-amber-800">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-px" />
          <span>
            <strong>{t.unverified} line{t.unverified === 1 ? "'s" : "s'"} own figures do not add up to the statement&apos;s Net Amount</strong>{" "}
            (marked ⚠ below). Usually a column mapped to the wrong field — Total Tax or Total Fare
            mapped to a vendor column that is not the whole tax or fare. Their commission is
            still compared, but check the mapping before you query the vendor.
          </span>
        </div>
      )}

      {/* ── Filters ───────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 flex-wrap mb-3">
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { setApplied(search.trim()); setOffset(0); } }}
            placeholder="Ticket / PNR / passenger / deal — Enter"
            className="pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-lg w-64 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
        <select value={air} onChange={(e) => { setAir(e.target.value); setOffset(0); }}
          className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-400">
          <option value="">All airlines</option>
          {(page?.airlines ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select value={txn} onChange={(e) => { setTxn(e.target.value); setOffset(0); }}
          className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-400">
          <option value="">All invoice types</option>
          {(page?.invoice_types ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        {bucket !== "all" && (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
            {BUCKET_LABEL[bucket]}
            <button onClick={() => pick("all")} title="Show all tickets" className="hover:text-blue-900">
              <X className="w-3 h-3" />
            </button>
          </span>
        )}
        <span className="text-[11px] text-slate-400">
          {page ? `${page.total.toLocaleString("en-IN")} of ${page.totals.tickets.toLocaleString("en-IN")} tickets` : ""}
        </span>
        {filtered && (
          <button onClick={clear} className="flex items-center gap-1 px-2 py-1.5 text-xs text-slate-400 hover:text-slate-700">
            <X className="w-3 h-3" /> Clear
          </button>
        )}
      </div>

      {/* ── Table ─────────────────────────────────────────────────────────────── */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-separate border-spacing-0">
            <thead className="text-[11px] uppercase tracking-wide whitespace-nowrap">
              <tr className="bg-slate-50 text-slate-500">
                <th rowSpan={2} className="sticky left-0 z-20 bg-slate-50 px-3 py-2 w-9 border-b border-slate-200">
                  <input type="checkbox" checked={allOnPage} disabled={!pageIds.length}
                    onChange={() => onToggleMany(pageIds, !allOnPage)}
                    aria-label="Select every line on this page"
                    className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:cursor-not-allowed" />
                </th>
                <th colSpan={Math.max(1, cols.length)} className="text-left px-3 py-1.5 font-bold border-b border-slate-200">
                  Statement <span className="font-normal normal-case tracking-normal text-slate-400">— as the vendor printed it</span>
                </th>
                <th colSpan={4} className="text-left px-3 py-1.5 font-bold border-b border-l border-slate-200 text-sky-700">
                  Your deal
                </th>
                <th colSpan={4} className="sticky right-0 z-20 bg-amber-50 text-left px-3 py-1.5 font-bold border-b border-l border-amber-200 text-amber-800"
                  style={{ width: PIN.statement + PIN.expected + PIN.difference + PIN.actions }}>
                  Commission check
                </th>
              </tr>
              <tr className="bg-slate-50 text-slate-400">
                {cols.length ? cols.map((c) => (
                  <th key={c.field} className={cn("px-3 py-2 font-semibold border-b border-slate-200",
                    c.kind === "money" ? "text-right" : "text-left")}>
                    {c.header}
                  </th>
                )) : <th className="px-3 py-2 border-b border-slate-200" />}
                <th className="text-left px-3 py-2 font-semibold border-b border-l border-slate-200">Result</th>
                <th className="text-left px-3 py-2 font-semibold border-b border-slate-200">Matched deal</th>
                <th className="text-right px-3 py-2 font-semibold border-b border-slate-200 text-teal-600"
                  title="The IATA commission % written on the matched deal.">IATA %</th>
                <th className="text-right px-3 py-2 font-semibold border-b border-slate-200 text-teal-600"
                  title="The deal's IATA % on this ticket's basic fare — part of Expected.">IATA comm.</th>
                <th className="sticky z-20 bg-amber-50 text-right px-3 py-2 font-semibold border-b border-l border-amber-200 text-slate-600 shadow-[-6px_0_8px_-6px_rgba(15,23,42,0.18)]"
                  style={pinStyle("statement")}
                  title="The vendor's commission + incentive, gross of TDS: + on a sale, − on a refund.">
                  Statement
                </th>
                <th className="sticky z-20 bg-amber-50 text-right px-3 py-2 font-semibold border-b border-amber-200 text-emerald-700"
                  style={pinStyle("expected")} title="What your matched deal computes: incentive + IATA commission.">
                  Expected
                </th>
                <th className="sticky z-20 bg-amber-50 text-right px-3 py-2 font-semibold border-b border-amber-200 text-amber-800"
                  style={pinStyle("difference")} title="Expected − statement. + means the vendor paid you less than your deal says.">
                  Difference
                </th>
                <th className="sticky z-20 bg-amber-50 px-2 py-2 border-b border-amber-200" style={pinStyle("actions")} />
              </tr>
            </thead>
            <tbody>
              {error ? (
                <tr><td colSpan={cols.length + 9} className="px-3 py-10 text-center text-sm text-red-500">{error}</td></tr>
              ) : loading && !page ? (
                <tr><td colSpan={cols.length + 9} className="px-3 py-10 text-center text-sm text-slate-400">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={cols.length + 9} className="px-3 py-12 text-center text-sm text-slate-400">
                  {filtered ? "No tickets match these filters." : "This statement has no ticket lines."}
                </td></tr>
              ) : rows.map((ln) => {
                const c = ln.calc;
                const st = c ? (STATUS_STYLE[c.commission_status] ?? STATUS_STYLE.pending) : STATUS_STYLE.pending;
                const busy = busyRows.has(ln.line_id);
                const isSel = selected.has(ln.line_id);
                const bg = isSel ? "bg-blue-50" : "bg-white group-hover:bg-slate-50";
                // Opaque: the statement's columns scroll UNDER the pinned check, and any
                // transparency lets their text show through it.
                const pinBg = isSel ? "bg-blue-50" : "bg-amber-50 group-hover:bg-amber-100";
                return (
                  <tr key={ln.line_id} className={cn("group whitespace-nowrap", !c && "text-slate-400")}>
                    <td className={cn("sticky left-0 z-10 px-3 py-2 border-b border-slate-100", bg)}>
                      <input type="checkbox" checked={isSel} onChange={() => onToggle(ln.line_id)}
                        aria-label={`Select line ${ln.values.ticket_number ?? ln.line_id}`}
                        className="w-3.5 h-3.5 accent-blue-600 cursor-pointer" />
                    </td>
                    {cols.map((col) => {
                      const v = ln.values[col.field];
                      const money = col.kind === "money";
                      // Class: the vendor's code with the cabin the Airline Class Master reads it as.
                      const cabin = col.field === "booking_class" ? ln.cabin : null;
                      return (
                        <td key={col.field}
                          className={cn("px-3 py-2 text-xs border-b border-slate-100 max-w-[220px] truncate", bg,
                            money ? "text-right tabular-nums" : "text-left",
                            c ? "text-slate-700" : "text-slate-400")}
                          title={cabin ? `${v ?? "—"} → ${cabin} (Airline Class Master)`
                            : !money && v != null ? String(v) : undefined}>
                          {cellValue(v, money)}
                          {cabin && <span className="ml-1 text-[10px] text-slate-400">· {cabin}</span>}
                        </td>
                      );
                    })}
                    <td className={cn("px-3 py-2 border-b border-l border-slate-100", bg)}>
                      <span title={c?.commission_reason || (c ? "" : "No run has reached this line yet")}
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border ${st.cls}`}>
                        {c ? st.label : "Not calculated"}
                      </span>
                    </td>
                    <td className={cn("px-3 py-2 text-xs border-b border-slate-100", bg)}>
                      {c?.matched_deal_name ? (
                        <span className="inline-flex items-center gap-1">
                          {/* Opens the deal that applied: why it matched and how it pays. */}
                          <button type="button" onClick={() => setAppliedCalc(c.id)}
                            className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold border bg-sky-50 text-sky-700 border-sky-200 hover:bg-sky-100 hover:border-sky-300 underline-offset-2 hover:underline"
                            title={`${c.matched_deal_no ?? "Deal"} — see why it applied and how it was calculated`}>
                            {source.dealKindLabel} · {c.matched_deal_name}
                          </button>
                          {c.supplier_match_by === "name" && (
                            <span className="text-[10px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded px-1"
                              title="Matched by supplier NAME only — the deal is not linked to an Agency Master branch.">
                              name only
                            </span>
                          )}
                        </span>
                      ) : <span className="text-slate-300">—</span>}
                    </td>
                    <td className={cn("px-3 py-2 text-right tabular-nums text-xs border-b border-slate-100 text-teal-700", bg)}>
                      {ln.iata_pct ? `${String(ln.iata_pct).replace(/%\s*$/, "")}%` : <span className="text-slate-300">—</span>}
                    </td>
                    <td className={cn("px-3 py-2 text-right tabular-nums text-xs border-b border-slate-100 text-teal-700", bg)}>
                      {ln.iata_commission != null ? `₹${inr(ln.iata_commission)}` : <span className="text-slate-300">—</span>}
                    </td>
                    {/* ── Pinned commission check ── */}
                    <td className={cn("sticky z-10 px-3 py-2 text-right tabular-nums text-xs border-b border-l border-amber-100 text-slate-700 shadow-[-6px_0_8px_-6px_rgba(15,23,42,0.18)]", pinBg)}
                      style={pinStyle("statement")}>
                      {ln.statement_commission != null ? `₹${inr(ln.statement_commission)}` : <span className="text-slate-300">—</span>}
                      {ln.net_ok === false && (
                        <span className="text-amber-600 ml-1 cursor-help"
                          title="This line's own figures do not add up to its Net Amount — check the column mapping.">⚠</span>
                      )}
                    </td>
                    <td className={cn("sticky z-10 px-3 py-2 text-right tabular-nums text-xs font-semibold border-b border-amber-100",
                      (ln.expected_commission ?? 0) < 0 ? "text-red-600" : "text-emerald-700", pinBg)}
                      style={pinStyle("expected")} title={expectedTitle(ln)}>
                      {ln.expected_commission != null ? `₹${inr(ln.expected_commission)}` : <span className="text-slate-300 font-normal">—</span>}
                    </td>
                    <td className={cn("sticky z-10 px-3 py-2 text-right tabular-nums text-xs border-b border-amber-100", pinBg)}
                      style={pinStyle("difference")}>
                      <Difference v={ln.difference} />
                    </td>
                    <td className={cn("sticky z-10 px-2 py-2 text-center border-b border-amber-100", pinBg)}
                      style={pinStyle("actions")}>
                      <button onClick={() => onRun([ln.line_id])} disabled={busy}
                        className="p-1 text-slate-400 hover:text-emerald-600 disabled:opacity-40" title="Calculate this line">
                        <Play className={cn("w-3.5 h-3.5", busy && "animate-pulse")} />
                      </button>
                      {c && (
                        <button onClick={() => onDiagnose(c)} className="p-1 text-slate-400 hover:text-blue-600" title="Why this result?">
                          <Info className="w-3.5 h-3.5" />
                        </button>
                      )}
                      {(c?.notes?.length ?? 0) > 0 && (
                        <span className="p-1 text-amber-500 cursor-help" title={(c?.notes ?? []).join("\n\n")}>
                          <AlertTriangle className="w-3.5 h-3.5 inline" />
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {page && page.total > PAGE && (
          <Pagination page={Math.floor(offset / PAGE) + 1} pageSize={PAGE} total={page.total}
            onPageChange={(p) => setOffset((p - 1) * PAGE)} />
        )}
      </div>

      {appliedCalc != null && (
        <AppliedDealModal apiBase={source.apiBase} calcId={appliedCalc} onClose={() => setAppliedCalc(null)} />
      )}
    </div>
  );
}

function Card({
  label, value, sub, tone, active, onClick, title,
}: {
  label: string; value: string; sub?: React.ReactNode; tone?: string;
  active: boolean; onClick: () => void; title?: string;
}) {
  return (
    <div role="button" tabIndex={0} onClick={onClick} title={title}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
      className={cn(
        "text-left bg-white border rounded-xl px-3 py-2.5 cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-blue-300",
        active ? "border-blue-400 ring-1 ring-blue-300 bg-blue-50/40" : "border-slate-200 hover:border-slate-300 hover:bg-slate-50/60",
      )}>
      <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
      <p className={cn("text-sm font-bold mt-0.5 tabular-nums", tone ?? "text-slate-800")}>{value}</p>
      {sub && <p className="text-[10px] text-slate-400 mt-0.5 truncate">{sub}</p>}
    </div>
  );
}

function SubLink({ children, onClick, active }: { children: React.ReactNode; onClick: () => void; active: boolean }) {
  return (
    <button type="button" onClick={(e) => { e.stopPropagation(); onClick(); }}
      className={cn("underline-offset-2 hover:underline", active ? "text-blue-700 font-semibold" : "text-slate-500")}>
      {children}
    </button>
  );
}
