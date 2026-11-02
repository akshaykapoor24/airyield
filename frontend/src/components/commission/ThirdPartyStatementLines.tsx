"use client";

// A consolidator statement (Third Party GDS / LCC) line by line, for Commission income:
// what the vendor's statement says it paid you, against what your deals say you earned.
//
// Seven cards — Total tickets · Matched · Unmatched · Commission in statement · IATA
// commission · Expected commission · Difference — each of which filters the table. IATA
// commission is the matched deal's IATA % on the basic fare: part of Expected, and its own
// card, as it is a different entitlement from the deal's incentive. The table is every ticket
// line of the statement, run or not, with the statement's own columns as the vendor printed
// them; then one column per incentive type, PLB first; then the commission check pinned to the
// right edge — IATA % · IATA comm. · Statement · Expected (every type plus IATA) · Difference ·
// Result · ▶ — so a line's whole check stays in view however far the statement scrolls. The
// Result badge opens every deal for the ticket (LineDealsModal).
//
// The money cards add up on screen: expected − statement = difference, over the lines a
// run has calculated (services/commission/statement_lines.py). Selection, running and the
// diagnosis popup stay with the parent, which owns the header's Run selected button.
//
// Two scopes, one table: a single statement (its detail page, `…/statements/{batch}/lines`)
// or every statement in the tab's filters (All tickets, `…/lines` plus `params`), where
// `showStatement` adds each line's agency and statement file ahead of the vendor's columns.

import { memo, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Play, Search, X } from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CommissionSource } from "@/lib/commissionSources";
import { INCENTIVE_TYPE_COLS, NOT_PRICED_PER_TICKET } from "@/lib/incentives";
import Pagination from "@/components/ui/Pagination";
import LineDealsModal from "./LineDealsModal";
import {
  CommissionLine, CommissionLineColumn, CommissionLinesPage, CommissionRow, LineBucket, STATUS_STYLE, inr,
} from "./types";

const PAGE = 50;

// The pinned commission check, left to right: IATA % · IATA comm. · Statement · Expected ·
// Difference · Result · ▶ — the deal's side beside the money it explains, so nothing about
// a line's check is off-screen. Widths are fixed so each sticky cell knows its right offset:
// the sum of the widths to its right.
const PIN_ORDER = ["iataPct", "iata", "statement", "expected", "difference", "result", "actions"] as const;
type PinKey = (typeof PIN_ORDER)[number];
// Each is its widest content plus the cell's padding — the header, or a five-digit amount
// ("₹11,097.16 ⚠" on 1–7 Oct 2026's Brightsun statement), or the "Calculated" badge — so no
// column carries dead space, and none is narrower than its content, which would widen it
// and throw the sticky offsets out.
const PIN: Record<PinKey, number> = {
  iataPct: 56, iata: 86, statement: 94, expected: 84, difference: 86, result: 84, actions: 30,
};
const PIN_RIGHT = Object.fromEntries(PIN_ORDER.map((k, i) =>
  [k, PIN_ORDER.slice(i + 1).reduce((a, x) => a + PIN[x], 0)])) as Record<PinKey, number>;
const pinStyle = (k: PinKey) => ({ right: PIN_RIGHT[k], width: PIN[k], minWidth: PIN[k] });

const BUCKET_LABEL: Record<LineBucket, string> = {
  all: "All tickets", matched: "Matched", unmatched: "Unmatched",
  other: "Excluded / skipped", pending: "Not calculated",
  statement: "With commission in statement", iata: "With IATA commission",
  expected: "With expected commission",
  difference: "With a difference",
};

const rupees = (v: number) => `${v < 0 ? "−" : ""}₹${inr(Math.abs(v))}`;

/** One incentive type's column. `total`: over every ticket in scope, null when none carries it. */
type IncentiveCol = { key: string; label: string; total: number | null };

/** A column for every incentive type, in the deal form's order, each with its scope's total. */
function incentiveColumns(totals: Record<string, number>): IncentiveCol[] {
  const known = new Set<string>(INCENTIVE_TYPE_COLS.map((c) => c.key));
  return [
    // Plain "PLB" on this grid; the other ticket tables keep the shared "PLB Inc.".
    ...INCENTIVE_TYPE_COLS.map((c): { key: string; label: string } => ({ key: c.key, label: c.key === "PLB" ? c.key : c.label })),
    // `incentive_type` is a free String on the deal, so a type no list names can reach a
    // breakdown. It is still part of Expected, and these columns must add up to it.
    ...Object.keys(totals).filter((k) => !known.has(k)).sort().map((k) => ({ key: k, label: k })),
  ].map((c) => ({ ...c, total: totals[c.key] ?? null }));
}

/** A type's heading: why it is empty when it always will be, else what its total covers. */
function incentiveTitle(c: IncentiveCol): string {
  const notPriced = NOT_PRICED_PER_TICKET[c.key];
  if (notPriced) return `${c.key} — ${notPriced}`;
  return c.total != null
    ? `${c.key} — part of Expected. ${rupees(c.total)} across every ticket in these filters.`
    : `${c.key} — part of Expected, but no ticket here earned it.`;
}

/** A line's amount of one type. ₹0 means its deal has this type and it paid nothing; a dash,
 *  that the type played no part on this line. */
function incentiveAmount(v: number | undefined) {
  return v == null ? <span className="text-slate-300">—</span> : rupees(Number(v));
}

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

/** The parent's own controls, drawn in ONE row with this table's filters, above the cards:
 *  `start` · search · airline · invoice type · `end` (right-aligned), then `below`. */
export type LinesToolbar = { start: ReactNode; end: ReactNode; below?: ReactNode };

/** That row — also used by CommissionIncomeView when it draws the row alone. From xl it never
 *  wraps: the dropdowns and search give way to their minimum widths instead, and a window too
 *  narrow even for those scrolls the row sideways rather than breaking it in two. */
export const TOOLBAR_ROW =
  "flex flex-wrap xl:flex-nowrap xl:overflow-x-auto items-center gap-1.5 py-0.5 mb-2.5";

export default function ThirdPartyStatementLines({
  source, url, params, showStatement, onOpenStatement, toolbar, refreshKey, selected, onToggle,
  onToggleMany, busyRows, onRun,
}: {
  source: CommissionSource;
  /** Given: one toolbar row above the cards (All tickets). Not given: the filters sit under
   *  the cards, as on one statement's page, whose header holds its own buttons. */
  toolbar?: LinesToolbar;
  /** The lines endpoint: one statement's, or the tab's across-statement one. */
  url: string;
  /** Scope sent with every request (the tab's Agency / Statement / Booking period). A new
   *  scope goes back to the first page; the card and the table filters are kept. */
  params?: Record<string, string | undefined>;
  /** Each line's agency and statement file as the first columns — across statements. */
  showStatement?: boolean;
  /** Clicking a line's statement file opens that statement. */
  onOpenStatement?: (batchId: string) => void;
  /** Changed by the parent after a run, a refresh or a finished calculation. */
  refreshKey: number | string;
  selected: Set<number>;
  onToggle: (lineId: number) => void;
  onToggleMany: (lineIds: number[], on: boolean) => void;
  busyRows: Set<number>;
  onRun: (lineIds: number[]) => void;
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
  // The line whose deals popup is open (its Result badge).
  const [dealsFor, setDealsFor] = useState<CommissionRow | null>(null);

  // Compared by value, so a parent re-render with an equal object is not a new scope.
  const scope = JSON.stringify(params ?? {});
  const [seenScope, setSeenScope] = useState(scope);
  if (scope !== seenScope) { setSeenScope(scope); setOffset(0); }

  // Only the latest request may land: clicking through cards quickly must not let a slow
  // earlier answer overwrite the one on screen.
  const latest = useRef(0);
  const load = useCallback(async () => {
    const req = ++latest.current;
    setLoading(true);
    try {
      const { data } = await api.get<CommissionLinesPage>(url, {
        params: { ...JSON.parse(scope), bucket, search: applied || undefined, air: air || undefined,
                  txn: txn || undefined, offset, limit: PAGE },
      });
      if (req === latest.current) { setPage(data); setError(""); }
    } catch {
      if (req === latest.current) setError(`Could not load the ${showStatement ? "tickets" : "statement's lines"}.`);
    } finally {
      if (req === latest.current) setLoading(false);
    }
  }, [url, scope, showStatement, bucket, applied, air, txn, offset]);

  useEffect(() => { load(); }, [load, refreshKey]);

  // LineRow is memoised, so it must get the same handlers on every render, whatever the parent
  // passes: these stay one function and forward to the parent's latest.
  const handlers = useRef({ onToggle, onRun, onOpenStatement });
  useEffect(() => { handlers.current = { onToggle, onRun, onOpenStatement }; });
  const toggleRow = useCallback((id: number) => handlers.current.onToggle(id), []);
  const runRow = useCallback((id: number) => handlers.current.onRun([id]), []);
  const openRow = useCallback((batch: string) => handlers.current.onOpenStatement?.(batch), []);

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
  // Compared by value: every reload brings a new object, and LineRow is memoised on this one.
  const incTotals = JSON.stringify(t?.incentives ?? {});
  const incCols = useMemo(() => incentiveColumns(JSON.parse(incTotals)), [incTotals]);
  // Checkbox · [Agency · Statement] · the vendor's columns · the incentive types · the check.
  const span = 1 + (showStatement ? 2 : 0) + Math.max(1, cols.length) + incCols.length + PIN_ORDER.length;
  // What Expected is made of, for its card.
  const expectedParts = [
    ...incCols.filter((c) => c.total != null).map((c) => `${c.key} ${rupees(c.total ?? 0)}`),
    ...(t?.iata_commission ? [`IATA ${rupees(t.iata_commission)}`] : []),
  ];

  // In the one-row toolbar these give way first — down to a readable minimum — so the row
  // fits on one line; on their own row they keep their natural width.
  const searchBox = (
    <div className={cn("relative", toolbar && "w-44 min-w-[6.5rem]")}>
      <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { setApplied(search.trim()); setOffset(0); } }}
        placeholder={toolbar ? "Ticket / PNR / pax / deal" : "Ticket / PNR / passenger / deal — Enter"}
        title="Search by ticket, PNR, passenger or deal — press Enter"
        className={cn("pl-8 pr-3 py-1.5 text-xs border rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400",
          toolbar ? "w-full" : "w-64", applied ? "border-blue-300" : "border-slate-200")}
      />
    </div>
  );
  const airSelect = (
    <select value={air} onChange={(e) => { setAir(e.target.value); setOffset(0); }} title="Airline" aria-label="Airline"
      className={cn("px-2 py-1.5 text-xs border rounded-lg bg-white text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-400",
        toolbar && "w-32 min-w-[5.5rem]", air ? "border-blue-300" : "border-slate-200")}>
      <option value="">{toolbar ? "Airline" : "All airlines"}</option>
      {(page?.airlines ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
    </select>
  );
  const txnSelect = (
    <select value={txn} onChange={(e) => { setTxn(e.target.value); setOffset(0); }} title="Invoice type" aria-label="Invoice type"
      className={cn("px-2 py-1.5 text-xs border rounded-lg bg-white text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-400",
        toolbar && "w-36 min-w-[7rem]", txn ? "border-blue-300" : "border-slate-200")}>
      <option value="">{toolbar ? "Invoice type" : "All invoice types"}</option>
      {(page?.invoice_types ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
    </select>
  );

  return (
    <div>
      {/* ── One row: the parent's controls · this table's filters · the parent's buttons ──
          The ticket count shows only while something narrows the table: unfiltered, it is
          the Total tickets card. The card picked is shown by the card itself. */}
      {toolbar && (
        <>
          <div className={TOOLBAR_ROW}>
            {toolbar.start}
            <span className="w-px h-5 bg-slate-200 mx-0.5 shrink-0" aria-hidden />
            {searchBox}
            {airSelect}
            {txnSelect}
            {filtered && page && (
              <button onClick={clear} title={`Showing ${BUCKET_LABEL[bucket].toLowerCase()} — clear the card, search, airline and invoice type`}
                className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 whitespace-nowrap">
                {page.total.toLocaleString("en-IN")} of {page.totals.tickets.toLocaleString("en-IN")}
                <X className="w-3 h-3" />
              </button>
            )}
            <div className="ml-auto flex items-center gap-1.5 shrink-0">{toolbar.end}</div>
          </div>
          {toolbar.below}
        </>
      )}

      {/* ── Cards: each one is a filter ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2 mb-3">
        <Card waiting={!t} label="Total tickets" active={bucket === "all"} onClick={() => pick("all")}
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
          ) : showStatement ? "in these statements" : "in this statement"} />
        <Card waiting={!t} label="Matched" tone="text-emerald-700" active={bucket === "matched"} onClick={() => pick("matched")}
          value={(t?.matched ?? 0).toLocaleString("en-IN")} sub="a deal was found" />
        <Card waiting={!t} label="Unmatched" tone="text-orange-600" active={bucket === "unmatched"} onClick={() => pick("unmatched")}
          value={(t?.unmatched ?? 0).toLocaleString("en-IN")}
          sub={`no ${source.dealKindLabel} deal found`} />
        <Card waiting={!t} label="Commission in statement" active={bucket === "statement"} onClick={() => pick("statement")}
          value={rupees(t?.statement_commission ?? 0)}
          title="The vendor's Agent Commission + Incentive, gross of TDS — counted as earned on a sale and given back on a refund, whichever sign the file prints."
          sub={t && t.statement_pending
            ? `+ ${rupees(t.statement_pending)} on lines not calculated`
            : "what the vendor paid"} />
        <Card waiting={!t} label="IATA commission" tone="text-teal-700" active={bucket === "iata"} onClick={() => pick("iata")}
          value={rupees(t?.iata_commission ?? 0)}
          title="The matched deal's IATA commission % applied to each ticket's basic fare. ₹0 on a line whose deal has no IATA %."
          sub={t && t.with_iata
            ? `deal IATA % × basic fare · ${t.with_iata} ticket${t.with_iata === 1 ? "" : "s"}`
            : "no matched deal has an IATA %"} />
        <Card waiting={!t} label="Expected commission" tone="text-emerald-700" active={bucket === "expected"} onClick={() => pick("expected")}
          value={rupees(t?.expected_commission ?? 0)}
          title={["What your matched deals compute for these tickets: every incentive type on the deal, plus IATA commission.",
            ...expectedParts].join("\n")}
          sub={expectedParts.length > 1 ? expectedParts.join(" + ") : "as per your deals"} />
        <Card waiting={!t} label="Difference" active={bucket === "difference"} onClick={() => pick("difference")}
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

      {/* No banner for lines whose own figures do not add up to their Net Amount (taken off on
          request): each such line still carries its ⚠ beside the statement figure, with the
          explanation in its tooltip. */}

      {/* ── Filters (one statement's page — no toolbar) ──────────────────────────── */}
      {!toolbar && (
      <div className="flex items-center gap-2 flex-wrap mb-3">
        {searchBox}
        {airSelect}
        {txnSelect}
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
      )}

      {/* ── Table ─────────────────────────────────────────────────────────────── */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-separate border-spacing-0">
            <thead className="text-[11px] uppercase tracking-wide whitespace-nowrap">
              <tr className="bg-slate-50 text-slate-400">
                <th className="sticky left-0 z-20 bg-slate-50 px-2 py-2 w-8 border-b border-slate-200">
                  <input type="checkbox" checked={allOnPage} disabled={!pageIds.length}
                    onChange={() => onToggleMany(pageIds, !allOnPage)}
                    aria-label="Select every line on this page"
                    className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:cursor-not-allowed" />
                </th>
                {showStatement && (
                  <>
                    <th className="text-left px-2 py-2 font-semibold border-b border-slate-200">Agency</th>
                    <th className="text-left px-2 py-2 font-semibold border-b border-r border-slate-200">Statement</th>
                  </>
                )}
                {cols.length ? cols.map((c) => (
                  <th key={c.field} className={cn("px-2 py-2 font-semibold border-b border-slate-200",
                    c.kind === "money" ? "text-right" : "text-left")}>
                    {c.header}
                  </th>
                )) : <th className="px-2 py-2 border-b border-slate-200" />}
                {incCols.map((c, i) => (
                  <th key={c.key} title={incentiveTitle(c)}
                    className={cn("text-right px-2 py-2 font-semibold border-b border-slate-200",
                      i === 0 && "border-l", c.total == null ? "text-slate-300" : "text-teal-700")}>
                    {c.label}
                  </th>
                ))}
                <th className="sticky z-20 bg-amber-50 text-right px-1.5 py-2 font-semibold border-b border-l border-amber-200 text-teal-700 shadow-[-6px_0_8px_-6px_rgba(15,23,42,0.18)]"
                  style={pinStyle("iataPct")} title="The IATA commission % written on the matched deal.">
                  IATA %
                </th>
                <th className="sticky z-20 bg-amber-50 text-right px-1.5 py-2 font-semibold border-b border-amber-200 text-teal-700"
                  style={pinStyle("iata")} title="The deal's IATA % on this ticket's basic fare — part of Expected.">
                  IATA comm.
                </th>
                <th className="sticky z-20 bg-amber-50 text-right px-1.5 py-2 font-semibold border-b border-amber-200 text-slate-600"
                  style={pinStyle("statement")}
                  title="The vendor's commission + incentive, gross of TDS: + on a sale, − on a refund.">
                  Statement
                </th>
                <th className="sticky z-20 bg-amber-50 text-right px-1.5 py-2 font-semibold border-b border-amber-200 text-emerald-700"
                  style={pinStyle("expected")} title="What your matched deal computes: every incentive type on it + IATA commission.">
                  Expected
                </th>
                <th className="sticky z-20 bg-amber-50 text-right px-1.5 py-2 font-semibold border-b border-amber-200 text-amber-800"
                  style={pinStyle("difference")} title="Expected − statement. + means the vendor paid you less than your deal says.">
                  Difference
                </th>
                <th className="sticky z-20 bg-amber-50 text-left px-1.5 py-2 font-semibold border-b border-amber-200 text-slate-600"
                  style={pinStyle("result")} title="What the run found for this line. Hover a badge for the reason.">
                  Result
                </th>
                <th className="sticky z-20 bg-amber-50 px-1 py-2 border-b border-amber-200" style={pinStyle("actions")} />
              </tr>
            </thead>
            <tbody>
              {error ? (
                <tr><td colSpan={span} className="px-3 py-10 text-center text-sm text-red-500">{error}</td></tr>
              ) : loading && !page ? (
                <tr><td colSpan={span} className="px-3 py-10 text-center text-sm text-slate-400">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={span} className="px-3 py-12 text-center text-sm text-slate-400">
                  {filtered ? "No tickets match these filters."
                    : showStatement ? "No ticket lines in these statements for this booking period."
                    : "This statement has no ticket lines."}
                </td></tr>
              ) : rows.map((ln) => (
                <LineRow key={ln.line_id} ln={ln} cols={cols} incCols={incCols} showStatement={!!showStatement}
                  isSel={selected.has(ln.line_id)} busy={busyRows.has(ln.line_id)}
                  onToggle={toggleRow} onRun={runRow} onOpen={onOpenStatement ? openRow : undefined}
                  onDeals={setDealsFor} />
              ))}
            </tbody>
          </table>
        </div>
        {page && page.total > PAGE && (
          <Pagination page={Math.floor(offset / PAGE) + 1} pageSize={PAGE} total={page.total}
            onPageChange={(p) => setOffset((p - 1) * PAGE)} />
        )}
      </div>

      {dealsFor && (
        <LineDealsModal apiBase={source.apiBase} calc={dealsFor} dealKind={source.dealKindLabel}
          onClose={() => setDealsFor(null)} />
      )}
    </div>
  );
}

/** One ticket line. Memoised: with 50 rows of about 50 columns, redrawing all of them took a
 *  third of a second in the browser — on every keystroke in the search box, every ticked box
 *  and every progress poll. Now a row redraws only when its own line, tick or run changes. */
const LineRow = memo(function LineRow({
  ln, cols, incCols, showStatement, isSel, busy, onToggle, onRun, onOpen, onDeals,
}: {
  ln: CommissionLine;
  cols: CommissionLineColumn[];
  incCols: IncentiveCol[];
  showStatement: boolean;
  isSel: boolean;
  busy: boolean;
  onToggle: (lineId: number) => void;
  onRun: (lineId: number) => void;
  onOpen?: (batchId: string) => void;
  onDeals: (calc: CommissionRow) => void;
}) {
  const c = ln.calc;
  const st = c ? (STATUS_STYLE[c.commission_status] ?? STATUS_STYLE.pending) : STATUS_STYLE.pending;
  const breakdown = c?.incentive_breakdown ?? {};
  const bg = isSel ? "bg-blue-50" : "bg-white group-hover:bg-slate-50";
  // Opaque: the statement's columns scroll UNDER the pinned check, and any
  // transparency lets their text show through it.
  const pinBg = isSel ? "bg-blue-50" : "bg-amber-50 group-hover:bg-amber-100";
  return (
    <tr className={cn("group whitespace-nowrap", !c && "text-slate-400")}>
      <td className={cn("sticky left-0 z-10 px-2 py-2 border-b border-slate-100", bg)}>
        <input type="checkbox" checked={isSel} onChange={() => onToggle(ln.line_id)}
          aria-label={`Select line ${ln.values.ticket_number ?? ln.line_id}`}
          className="w-3.5 h-3.5 accent-blue-600 cursor-pointer" />
      </td>
      {showStatement && (
        <>
          <td className={cn("px-2 py-2 text-xs border-b border-slate-100 max-w-[130px] truncate text-slate-600", bg)}
            title={ln.agency ?? undefined}>
            {ln.agency || <span className="text-slate-300">—</span>}
          </td>
          <td className={cn("px-2 py-2 text-xs border-b border-r border-slate-100 max-w-[170px] truncate", bg)}
            title={ln.statement_name ? `${ln.statement_name} — open this statement` : undefined}>
            {ln.batch_id && onOpen ? (
              <button type="button" onClick={() => onOpen(ln.batch_id!)}
                className="max-w-full truncate text-blue-600 hover:underline underline-offset-2">
                {ln.statement_name || ln.batch_id}
              </button>
            ) : (ln.statement_name || <span className="text-slate-300">—</span>)}
          </td>
        </>
      )}
      {cols.map((col) => {
        const v = ln.values[col.field];
        const money = col.kind === "money";
        // Class: the vendor's code with the cabin the Airline Class Master reads it as.
        const cabin = col.field === "booking_class" ? ln.cabin : null;
        return (
          <td key={col.field}
            className={`px-2 py-2 text-xs border-b border-slate-100 max-w-[220px] truncate ${bg} ${money ? "text-right tabular-nums" : "text-left"} ${c ? "text-slate-700" : "text-slate-400"}`}
            title={cabin ? `${v ?? "—"} → ${cabin} (Airline Class Master)`
              : !money && v != null ? String(v) : undefined}>
            {cellValue(v, money)}
            {cabin && <span className="ml-1 text-[10px] text-slate-400">· {cabin}</span>}
          </td>
        );
      })}
      {incCols.map((col, i) => (
        <td key={col.key}
          className={cn("px-2 py-2 text-right tabular-nums text-xs border-b border-slate-100", i === 0 && "border-l", bg)}>
          {incentiveAmount(breakdown[col.key])}
        </td>
      ))}
      {/* ── Pinned commission check ── */}
      <td className={cn("sticky z-10 px-1.5 py-2 text-right tabular-nums text-xs border-b border-l border-amber-100 text-teal-700 shadow-[-6px_0_8px_-6px_rgba(15,23,42,0.18)]", pinBg)}
        style={pinStyle("iataPct")}>
        {ln.iata_pct ? `${String(ln.iata_pct).replace(/%\s*$/, "")}%` : <span className="text-slate-300">—</span>}
      </td>
      <td className={cn("sticky z-10 px-1.5 py-2 text-right tabular-nums text-xs border-b border-amber-100 text-teal-700", pinBg)}
        style={pinStyle("iata")}>
        {ln.iata_commission != null ? rupees(ln.iata_commission) : <span className="text-slate-300">—</span>}
      </td>
      <td className={cn("sticky z-10 px-1.5 py-2 text-right tabular-nums text-xs border-b border-amber-100 text-slate-700", pinBg)}
        style={pinStyle("statement")}>
        {ln.statement_commission != null ? rupees(ln.statement_commission) : <span className="text-slate-300">—</span>}
        {ln.net_ok === false && (
          <span className="text-amber-600 ml-1 cursor-help"
            title="This line's own figures do not add up to its Net Amount — check the column mapping.">⚠</span>
        )}
      </td>
      <td className={cn("sticky z-10 px-1.5 py-2 text-right tabular-nums text-xs font-semibold border-b border-amber-100",
        (ln.expected_commission ?? 0) < 0 ? "text-red-600" : "text-emerald-700", pinBg)}
        style={pinStyle("expected")} title={expectedTitle(ln)}>
        {ln.expected_commission != null ? rupees(ln.expected_commission) : <span className="text-slate-300 font-normal">—</span>}
      </td>
      <td className={cn("sticky z-10 px-1.5 py-2 text-right tabular-nums text-xs border-b border-amber-100", pinBg)}
        style={pinStyle("difference")}>
        <Difference v={ln.difference} />
      </td>
      {/* The badge opens every deal for this ticket: the one applied, then the
          rest and why each does not apply (LineDealsModal). */}
      <td className={cn("sticky z-10 px-1.5 py-2 border-b border-amber-100", pinBg)}
        style={pinStyle("result")}>
        {c ? (
          <button type="button" onClick={() => onDeals(c)}
            title={`${c.commission_reason || st.label}\n\nClick: every deal for this ticket — the one applied, and why the others do not.`}
            className={cn("relative inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold border cursor-pointer hover:ring-2 hover:ring-offset-1 hover:ring-blue-200 underline-offset-2 hover:underline", st.cls)}>
            {st.label}
            {c.supplier_match_by === "name" && (
              <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-amber-500"
                aria-label="Matched by supplier name only" />
            )}
          </button>
        ) : (
          <span title="Not calculated — no run has reached this line yet. Run it (▶)."
            className={cn("inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-semibold border", st.cls)}>
            {st.label}
          </span>
        )}
      </td>
      <td className={cn("sticky z-10 px-1 py-2 text-center border-b border-amber-100", pinBg)}
        style={pinStyle("actions")}>
        <button onClick={() => onRun(ln.line_id)} disabled={busy}
          className="p-1 text-slate-400 hover:text-emerald-600 disabled:opacity-40" title="Calculate this line">
          <Play className={cn("w-3.5 h-3.5", busy && "animate-pulse")} />
        </button>
      </td>
    </tr>
  );
});

function Card({
  label, value, sub, tone, active, onClick, title, waiting,
}: {
  label: string; value: string; sub?: React.ReactNode; tone?: string;
  active: boolean; onClick: () => void; title?: string;
  /** No answer yet: a dash, not the ₹0.00 "matches your deals" an empty total would read as. */
  waiting?: boolean;
}) {
  return (
    <div role="button" tabIndex={0} onClick={onClick} title={title}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
      className={cn(
        "min-w-0 text-left bg-white border rounded-xl px-3 py-1.5 cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-blue-300",
        active ? "border-blue-400 ring-1 ring-blue-300 bg-blue-50/40" : "border-slate-200 hover:border-slate-300 hover:bg-slate-50/60",
      )}>
      {/* One line each: a label that wraps makes its card — and with it the whole row of
          cards — a line taller, pushing the tickets further down. */}
      <p className="text-[10px] uppercase text-slate-400 truncate">{label}</p>
      <p className={cn("text-sm font-bold tabular-nums leading-5", waiting ? "text-slate-300" : tone ?? "text-slate-800")}>
        {waiting ? "—" : value}
      </p>
      {sub && <p className="text-[10px] text-slate-400 truncate">{waiting ? " " : sub}</p>}
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
