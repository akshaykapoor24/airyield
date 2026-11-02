"use client";

// Vendors data → Payment Module → Vendor Mapping.
//
// ONE WAY — THE VENDOR'S STATEMENT IS THE BASE (the user's call): every ticket a consolidator
// billed (its Third Party GDS and LCC statements) is looked for in the MO — Internal Statement's
// Booking / MO uploads — and its fare compared: Basic, Tax, SSR and their total. ONE ROW PER
// TICKET: every line each side has for it, a side that sold and refunded it knocked off (sale less
// refund) and final compared with final — opened, the row shows this sale, this refund and the
// final on both sides. A ticket is Matched (in the MO under this vendor, at the same fare), a Fare
// difference, Not in MO, or in the MO under another vendor. MO tickets no vendor billed are not
// this screen's question.
//
// A matched line is paid as billed; one the MO does not have, or files under another vendor, is
// held; a higher fare holds its excess. The user closes what is held — the vendor is wrong
// (claimed back), the MO is wrong, or accepted. The server computes all of it on every load
// (backend/app/services/vendor_mapping.py); only the decisions are stored.

import { Fragment, useCallback, useEffect, useState, type ReactNode } from "react";
import {
  AlertCircle, CheckCircle2, ChevronDown, ChevronRight, RefreshCw, Search, Undo2, Wallet, X,
} from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { MO_UPLOAD_HREF, VENDOR_GDS_HREF, VENDOR_MAPPING_API, type PaymentTabSlug } from "@/lib/paymentModule";
import { formatDay, formatPeriod } from "@/lib/statementPeriod";
import { ReasonDialog, errorDetail, inr } from "./shared";
import type {
  MappingDecision, MappingLine, MappingResponse, MappingRow, MappingSide, MappingStatement, MappingStatus,
  MappingView, PayState,
} from "./vendorTypes";

const PAGE = 200;
const SELECT_CLS =
  "py-2 px-2.5 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-slate-700 bg-white";

export const STATUS_STYLE: Record<MappingStatus, { label: string; cls: string }> = {
  matched: { label: "Matched", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  fare_diff: { label: "Fare difference", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  not_in_mo: { label: "Not in MO", cls: "bg-red-50 text-red-700 border-red-200" },
  other_vendor: { label: "Other vendor in MO", cls: "bg-violet-50 text-violet-700 border-violet-200" },
};

const PAY_STYLE: Record<PayState, { label: string; cls: string; title: string }> = {
  clear: { label: "Pay", cls: "text-emerald-700", title: "Paid as billed" },
  hold: { label: "Held", cls: "text-red-700", title: "Nothing is paid until it is decided" },
  part_hold: { label: "Part held", cls: "text-amber-700", title: "Paid less the excess fare — the excess is held" },
  review: { label: "Pay · review", cls: "text-sky-700", title: "Paid as billed — the vendor's fare is lower than the MO's" },
  credit: { label: "Credit", cls: "text-emerald-700", title: "A credit the MO does not have — always taken" },
  claim: { label: "Claimed", cls: "text-violet-700", title: "Decided: the vendor is wrong — not paid" },
};

const DECISION_LABEL: Record<MappingDecision, string> = {
  vendor_wrong: "Vendor is wrong — claimed back",
  mo_wrong: "MO is wrong — paid as billed",
  accepted: "Accepted — paid as billed",
};

/** The decisions, as the bulk bar offers them. */
const ACTIONS: { decision: MappingDecision; label: string; ask: string }[] = [
  {
    decision: "vendor_wrong", label: "Vendor is wrong — claim",
    ask: "What is held on these lines is claimed back from the vendor — never paid. Say what the vendor got wrong; it is what the claim rests on.",
  },
  {
    decision: "mo_wrong", label: "MO is wrong — pay",
    ask: "These lines are paid as billed. Correct the MO so the next statement maps cleanly.",
  },
  {
    decision: "accepted", label: "Accept — pay as billed",
    ask: "These lines are paid as billed, the difference explained or agreed.",
  },
];

function stmtLabel(s: MappingStatement): string {
  const kind = s.slug === "tp-lcc" ? "LCC" : "GDS";
  const period = s.period_from && s.period_to ? formatPeriod(s.period_from, s.period_to) : "no period";
  return `${s.file_name || s.batch_id} · ${kind} · ${period} · ${s.lines} tickets`;
}

function ticket(prefix: string | null | undefined, serial: string | null): string {
  return serial ? (prefix ? `${prefix} ${serial}` : serial) : "—";
}

/** "sale", "refund" or "sale+refund" — what a side has for the ticket. */
function KindBadge({ kind }: { kind: string | null | undefined }) {
  if (!kind || kind === "sale") return null;
  return (
    <span className={`px-1.5 py-px rounded text-[9px] font-sans font-semibold uppercase ${
      kind === "refund" ? "bg-rose-50 text-rose-600" : "bg-amber-50 text-amber-700"}`}>
      {kind}
    </span>
  );
}

/** A fare cell: the total — a side's final, knocked off, when it has more than one line — and
 *  its parts beneath. */
function Fare({ side, kind }: { side: MappingSide | null; kind?: string | null }) {
  if (!side) return <div className="text-right text-slate-300">—</div>;
  return (
    <div className="text-right">
      <div className="font-semibold text-slate-800 tabular-nums">{inr(side.fare)}</div>
      <div className="text-[10px] text-slate-400 tabular-nums whitespace-nowrap">
        {side.lines > 1
          ? <>final of {side.lines} lines{kind === "sale+refund" ? " · knocked off" : ""}</>
          : <>B {inr(side.base)} · T {inr(side.tax)}{side.ssr ? ` · SSR ${inr(side.ssr)}` : ""}</>}
      </div>
    </div>
  );
}

function Tile({ label, count, sub, hint, active, tone, onClick }: {
  label: string; count: number; sub?: ReactNode; hint?: string; active: boolean;
  tone: "slate" | "emerald" | "amber" | "red" | "violet"; onClick: () => void;
}) {
  const tones: Record<string, string> = {
    slate: "text-slate-800", emerald: "text-emerald-700", amber: "text-amber-700",
    red: "text-red-700", violet: "text-violet-700",
  };
  return (
    <button type="button" onClick={onClick} title={hint}
      className={`text-left rounded-xl border px-3.5 py-2.5 transition-colors ${
        active ? "border-blue-400 bg-blue-50/60 ring-1 ring-blue-200" : "border-slate-200 bg-white hover:border-slate-300"}`}>
      <p className="text-[10px] uppercase tracking-wide text-slate-400 font-semibold">{label}</p>
      <p className={`text-lg font-bold tabular-nums ${tones[tone]}`}>{count.toLocaleString("en-IN")}</p>
      {sub != null && <p className="text-[11px] text-slate-500 tabular-nums">{sub}</p>}
    </button>
  );
}

export default function VendorMappingView({
  onOpenTab, focus,
}: {
  onOpenTab?: (slug: PaymentTabSlug, focus?: { vendor?: string | null; statement?: string | null }) => void;
  /** Opened from Vendor Payments: start on that vendor (and statement). */
  focus?: { vendor?: string | null; statement?: string | null } | null;
}) {
  const [vendor, setVendor] = useState(focus?.vendor ?? "");
  const [statement, setStatement] = useState(focus?.statement ?? "");
  const [view, setView] = useState<MappingView>("all");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<MappingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [ask, setAsk] = useState<MappingDecision | null>(null);
  const [busy, setBusy] = useState(false);

  // A new scope or view starts on its first page, nothing ticked, nothing open.
  const fresh = () => { setOffset(0); setSelected(new Set()); setExpanded(null); };
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(q.trim());
      setOffset(0);
      setSelected(new Set());
      setExpanded(null);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const params = useCallback(() => ({
    vendor: vendor || undefined, statement: statement || undefined, view, q: query || undefined,
    offset, limit: PAGE,
  }), [vendor, statement, view, query, offset]);

  // `refresh`: the server builds the mapping afresh. Otherwise it reuses the one it built while
  // nothing it reads has changed — a filter, a search or a page only narrows it.
  const load = useCallback(async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      const { data: d } = await api.get<MappingResponse>(VENDOR_MAPPING_API, {
        params: { ...params(), ...(refresh ? { refresh: true } : {}) },
      });
      setData(d);
    } catch (e) {
      setError(errorDetail(e, "Could not load the vendor mapping."));
    } finally {
      setLoading(false);
    }
  }, [params]);
  useEffect(() => { void load(); }, [load]);

  const pickVendor = (v: string) => {
    setVendor(v);
    // A statement of another vendor no longer belongs to the scope.
    const st = data?.options.statements.find((s) => s.batch_id === statement);
    if (v && st && st.vendor_id !== v) setStatement("");
    fresh();
  };
  const pickStatement = (s: string) => { setStatement(s); fresh(); };
  const pickView = (v: MappingView) => { setView(v); fresh(); };

  const decide = async (decision: MappingDecision, note: string) => {
    setBusy(true);
    try {
      const { data: d } = await api.post<MappingResponse>(`${VENDOR_MAPPING_API}/decisions`, {
        ...params(), keys: [...selected], decision, note: note || null,
      });
      setData(d);
      toast.success(`${selected.size} ticket${selected.size === 1 ? "" : "s"}: ${DECISION_LABEL[decision].toLowerCase()}`);
      setSelected(new Set());
      setAsk(null);
    } catch (e) {
      toast.error(errorDetail(e, "Could not record the decision."));
    } finally {
      setBusy(false);
    }
  };

  const reopen = async () => {
    setBusy(true);
    try {
      const { data: d } = await api.post<MappingResponse>(`${VENDOR_MAPPING_API}/decisions/reopen`, {
        ...params(), keys: [...selected],
      });
      setData(d);
      toast.success("Reopened — the tickets are open again.");
      setSelected(new Set());
    } catch (e) {
      toast.error(errorDetail(e, "Could not reopen these lines."));
    } finally {
      setBusy(false);
    }
  };

  const options = data?.options;
  const statements = (options?.statements ?? []).filter((s) => !vendor || s.vendor_id === vendor);
  const s = data?.summary;
  const rows = data?.rows ?? [];
  const selectable = rows.filter((r) => r.status !== "matched");
  const chosen = selectable.filter((r) => selected.has(r.key));
  const anyResolved = chosen.some((r) => !r.open);
  const allTicked = selectable.length > 0 && selectable.every((r) => selected.has(r.key));
  const toggle = (key: string) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const vendorLabel = options?.vendors.find((v) => v.id === (data?.scope.vendor ?? vendor));
  const noStatements = !!data && data.options.statements.length === 0;
  const noMo = !!data && data.mo.tickets === 0;
  const scopeVendor = data?.scope.vendor ?? (vendor || null);

  return (
    <div className="space-y-4">
      {/* Scope: the vendor, then one of its statements. */}
      <div className="flex items-center gap-2 flex-wrap">
        <select value={vendor} onChange={(e) => pickVendor(e.target.value)} className={SELECT_CLS} aria-label="Vendor">
          <option value="">All vendors</option>
          {(options?.vendors ?? []).map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}{v.branch ? ` — ${v.branch}` : ""} ({v.statements} statement{v.statements === 1 ? "" : "s"})
            </option>
          ))}
        </select>
        <select value={statement} onChange={(e) => pickStatement(e.target.value)} className={`${SELECT_CLS} max-w-[460px]`}
          aria-label="Vendor statement">
          <option value="">{vendor ? "All its statements" : "All statements"}</option>
          {statements.map((st) => (
            <option key={st.batch_id} value={st.batch_id}>
              {vendor ? "" : `${st.vendor_name ?? "No vendor"} · `}{stmtLabel(st)}
            </option>
          ))}
        </select>
        <div className="relative">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ticket, passenger, PNR or Doc No…"
            className="pl-8 pr-7 py-2 text-xs border border-slate-200 rounded-lg w-64 focus:outline-none focus:ring-1 focus:ring-blue-400" />
          {q && (
            <button type="button" onClick={() => setQ("")} aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <button type="button" onClick={() => void load(true)} disabled={loading} title="Map the statements again from scratch"
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-500 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}
      {noStatements && (
        <div className="px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-600">
          No vendor statement is loaded yet. Upload them under{" "}
          <a href={VENDOR_GDS_HREF} className="text-blue-600 hover:underline">Statements → Third Party</a> — every
          ticket on them is then looked for in the MO here.
        </div>
      )}
      {noMo && !noStatements && (
        <div className="flex items-start gap-2 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-800">
          <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
          <span>
            No Booking / MO statement is loaded, so every ticket shows as Not in MO and is held. Upload the MO under{" "}
            <a href={MO_UPLOAD_HREF} className="font-semibold underline">Internal Statement → Upload Statement</a> with
            Statement Type “Booking / MO statement”.
          </span>
        </div>
      )}

      {s && (
        <>
          {/* The vendor's tickets, by what the MO says about them — each a filter on the grid. */}
          <div className="grid gap-2 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
            <Tile label="Total tickets" count={s.lines} sub={`${inr(s.billed)} billed`} tone="slate"
              active={view === "all"} onClick={() => pickView("all")}
              hint="Every ticket on the vendor statements in scope — its lines together — and what they bill" />
            <Tile label="Matched" count={s.status.matched.lines} sub={inr(s.status.matched.amount)} tone="emerald"
              active={view === "matched"} onClick={() => pickView("matched")}
              hint="Found in the MO under this vendor, at the same fare — paid as billed" />
            <Tile label="Fare difference" count={s.status.fare_diff.lines} tone="amber"
              sub={<>{inr(s.fare_excess)} above MO{s.fare_short ? <> · {inr(-s.fare_short)} below</> : null}</>}
              active={view === "fare_diff"} onClick={() => pickView("fare_diff")}
              hint="Found in the MO at another fare. Above: the vendor billed more — that excess is held. Below: it billed less — reviewed, not held" />
            <Tile label="Not in MO" count={s.status.not_in_mo.lines} tone="red"
              sub={<>{inr(s.status.not_in_mo.sales)} sales{s.status.not_in_mo.refunds ? <> · {s.status.not_in_mo.refunds} refunds</> : null}</>}
              active={view === "not_in_mo"} onClick={() => pickView("not_in_mo")}
              hint="Billed by the vendor, not in the MO. A sale is held until decided; a refund's credit is always taken" />
            <Tile label="Other vendor in MO" count={s.status.other_vendor.lines} sub={inr(s.status.other_vendor.amount)}
              tone="violet" active={view === "other_vendor"} onClick={() => pickView("other_vendor")}
              hint="The MO has the ticket, but under another vendor — held, or it could be paid twice" />
          </div>

          {/* What the statements in scope come to for payment. */}
          <div className="flex items-center gap-x-6 gap-y-2 flex-wrap px-4 py-3 bg-white border border-slate-200 rounded-xl text-xs">
            <span className="flex items-center gap-1.5 font-semibold text-slate-700">
              <Wallet className="w-4 h-4 text-slate-400" />
              {data?.statement ? stmtLabel(data.statement) : vendorLabel ? `${vendorLabel.name} — all statements` : "All vendors"}
            </span>
            <span className="text-slate-500" title="Billed less what is held and what is claimed">
              Payable now <b className="text-emerald-700 tabular-nums">{inr(s.payable)}</b>
            </span>
            <button type="button" onClick={() => pickView("on_hold")} className="text-slate-500 hover:underline"
              title="Withheld until decided: sales the MO does not have, tickets under another vendor, and the excess of a higher fare">
              On hold <b className="text-red-700 tabular-nums">{inr(s.hold)}</b> ({data?.counts.on_hold ?? 0})
            </button>
            <button type="button" onClick={() => pickView("claims")} className="text-slate-500 hover:underline"
              title="Decided: the vendor is wrong — claimed back, never paid">
              Claimed <b className="text-violet-700 tabular-nums">{inr(s.claim)}</b> ({data?.counts.claims ?? 0})
            </button>
            {s.credit !== 0 && (
              <span className="text-slate-500" title="Refunds the MO does not have — always taken">
                Credits taken <b className="text-slate-800 tabular-nums">{inr(s.credit)}</b>
              </span>
            )}
            {data && (
              <span className="text-[11px] text-slate-400"
                title="What each vendor ticket is looked for in — Internal Statement uploads filed as Booking / MO">
                Checked against {data.mo.tickets.toLocaleString("en-IN")} MO tickets
                ({data.mo.statements} statement{data.mo.statements === 1 ? "" : "s"})
              </span>
            )}
            <span className="ml-auto flex items-center gap-2">
              <button type="button" onClick={() => pickView("open")}
                className={`px-2.5 py-1 rounded-full border text-[11px] font-semibold ${
                  view === "open" ? "bg-amber-100 border-amber-300 text-amber-800" : "bg-amber-50 border-amber-200 text-amber-700 hover:bg-amber-100"}`}>
                {s.open.toLocaleString("en-IN")} to decide
              </button>
              <button type="button" onClick={() => pickView("resolved")}
                className={`px-2.5 py-1 rounded-full border text-[11px] font-semibold ${
                  view === "resolved" ? "bg-slate-200 border-slate-300 text-slate-800" : "bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100"}`}>
                {s.resolved.toLocaleString("en-IN")} decided
              </button>
              {scopeVendor && (
                <button type="button" onClick={() => onOpenTab?.("payments", { vendor: scopeVendor })}
                  className="px-2.5 py-1 rounded-full border border-blue-200 bg-blue-50 text-[11px] font-semibold text-blue-700 hover:bg-blue-100">
                  Pay this vendor →
                </button>
              )}
            </span>
          </div>
        </>
      )}

      {/* Bulk decisions on the ticked lines. */}
      {selected.size > 0 && (
        <div className="sticky top-2 z-10 flex items-center gap-2 flex-wrap px-4 py-2.5 bg-slate-900 text-white rounded-xl shadow-lg">
          <span className="text-xs font-semibold">{selected.size} ticket{selected.size === 1 ? "" : "s"} selected</span>
          <span className="text-[11px] text-white/60">held {inr(chosen.reduce((a, r) => a + r.pay.hold, 0))}</span>
          <span className="ml-auto flex items-center gap-2">
            {ACTIONS.map((a) => (
              <button key={a.decision} type="button" disabled={busy} onClick={() => setAsk(a.decision)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50 ${
                  a.decision === "vendor_wrong" ? "bg-violet-600 hover:bg-violet-700 text-white" : "bg-white/10 hover:bg-white/20 text-white"}`}>
                {a.label}
              </button>
            ))}
            {anyResolved && (
              <button type="button" disabled={busy} onClick={() => void reopen()}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white/10 hover:bg-white/20 disabled:opacity-50">
                <Undo2 className="w-3.5 h-3.5" /> Reopen
              </button>
            )}
            <button type="button" onClick={() => setSelected(new Set())} className="p-1.5 rounded-lg hover:bg-white/10" aria-label="Clear selection">
              <X className="w-4 h-4" />
            </button>
          </span>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400">
                <th className="px-3 py-2.5 w-8">
                  <input type="checkbox" checked={allTicked} disabled={!selectable.length}
                    onChange={() => setSelected(allTicked ? new Set() : new Set(selectable.map((r) => r.key)))}
                    aria-label="Select every line on this page that can be decided" />
                </th>
                <th className="text-left px-3 py-2.5 font-semibold">Ticket · booked</th>
                <th className="text-left px-3 py-2.5 font-semibold">Passenger · Sector</th>
                <th className="text-right px-3 py-2.5 font-semibold" title="Basic + Tax + SSR, as the vendor billed it">Vendor fare</th>
                <th className="text-right px-3 py-2.5 font-semibold" title="Basic + Tax + SSR, as the MO has it">MO fare</th>
                <th className="text-right px-3 py-2.5 font-semibold" title="The vendor's fare less the MO's — above zero, it billed more">Difference</th>
                <th className="text-left px-3 py-2.5 font-semibold">Status</th>
                <th className="text-right px-3 py-2.5 font-semibold" title="The vendor's net on the line, and what it comes to for payment">Billed · payment</th>
              </tr>
            </thead>
            <tbody>
              {loading && !data ? (
                <tr><td colSpan={8} className="px-3 py-12 text-center text-slate-400">Mapping the statements…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={8} className="px-3 py-12 text-center text-slate-400">
                  {query ? `No ticket matches “${query}”.` : "No tickets in this view."}
                </td></tr>
              ) : rows.map((r) => {
                const st = STATUS_STYLE[r.status];
                const pay = PAY_STYLE[r.pay.state];
                const open = expanded === r.key;
                const can = r.status !== "matched";
                return (
                  <Fragment key={r.key}>
                    <tr onClick={() => setExpanded(open ? null : r.key)}
                      className={`border-b border-slate-100 align-top cursor-pointer hover:bg-slate-50/60 ${
                        selected.has(r.key) ? "bg-blue-50/40" : open ? "bg-slate-50/60" : ""}`}>
                      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                        {can && (
                          <input type="checkbox" checked={selected.has(r.key)} onChange={() => toggle(r.key)}
                            aria-label={`Select ${r.ticket_number ?? "line"}`} />
                        )}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <div className="flex items-center gap-1 font-mono text-slate-700">
                          {open ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
                          {ticket(r.vendor.ticket_prefix, r.ticket_number)}
                          <span className="ml-1"><KindBadge kind={r.kind} /></span>
                        </div>
                        <div className="pl-[18px] text-[10px] text-slate-400">{formatDay(r.booked)}</div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="text-slate-700">{r.vendor.pax || r.mo?.pax || "—"}</div>
                        <div className="text-[10px] text-slate-400">{[r.vendor.sector, r.vendor.pnr].filter(Boolean).join(" · ")}</div>
                      </td>
                      <td className="px-3 py-2"><Fare side={r.vendor} kind={r.kind} /></td>
                      <td className="px-3 py-2">
                        <Fare side={r.mo} kind={r.mo_kind} />
                        {r.mo_kind && r.mo_kind !== "sale" && (
                          <div className="text-right mt-0.5"><KindBadge kind={r.mo_kind} /></div>
                        )}
                      </td>
                      <td className={`px-3 py-2 text-right tabular-nums font-semibold ${
                        r.gap == null || Math.abs(r.gap) < 1 ? "text-slate-300" : r.gap > 0 ? "text-red-600" : "text-sky-600"}`}>
                        {r.gap == null || Math.abs(r.gap) < 1 ? "—" : `${r.gap > 0 ? "+" : ""}${inr(r.gap)}`}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold border whitespace-nowrap ${st.cls}`}>
                          {st.label}
                        </span>
                        {r.status === "other_vendor" && r.mo_vendor_name && (
                          <div className="mt-1 text-[10px] text-violet-700">MO: {r.mo_vendor_name}</div>
                        )}
                        {r.decision && (
                          <div className={`mt-1 text-[10px] ${r.decision.stale ? "text-amber-600" : "text-slate-500"}`}
                            title={r.decision.note ?? undefined}>
                            {r.decision.stale ? "Figures changed — decide again" : DECISION_LABEL[r.decision.decision]}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap" title={pay.title}>
                        <div className="font-semibold tabular-nums text-slate-800">{inr(r.vendor.net)}</div>
                        <div className={`text-[10px] font-semibold ${pay.cls}`}>
                          {pay.label}
                          {r.pay.hold ? <span className="font-normal tabular-nums"> {inr(r.pay.hold)}</span> : null}
                          {r.pay.claim ? <span className="font-normal tabular-nums"> {inr(r.pay.claim)}</span> : null}
                        </div>
                      </td>
                    </tr>
                    {open && <Detail row={r} />}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        {data && data.total > data.limit && (
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-100 text-[11px] text-slate-500">
            <span>
              {(data.offset + 1).toLocaleString("en-IN")}–{Math.min(data.offset + data.limit, data.total).toLocaleString("en-IN")} of{" "}
              {data.total.toLocaleString("en-IN")} tickets
            </span>
            <span className="flex gap-2">
              <button type="button" disabled={data.offset === 0 || loading}
                onClick={() => { setOffset(Math.max(data.offset - PAGE, 0)); setSelected(new Set()); }}
                className="px-2.5 py-1 border border-slate-200 rounded-lg disabled:opacity-40 hover:bg-slate-50">Previous</button>
              <button type="button" disabled={data.offset + data.limit >= data.total || loading}
                onClick={() => { setOffset(data.offset + PAGE); setSelected(new Set()); }}
                className="px-2.5 py-1 border border-slate-200 rounded-lg disabled:opacity-40 hover:bg-slate-50">Next</button>
            </span>
          </div>
        )}
      </div>

      {ask && (
        <ReasonDialog
          title={ACTIONS.find((a) => a.decision === ask)!.label}
          description={ACTIONS.find((a) => a.decision === ask)!.ask}
          confirmLabel={`${ACTIONS.find((a) => a.decision === ask)!.label} (${selected.size})`}
          requireRemarks={ask === "vendor_wrong"}
          busy={busy}
          onCancel={() => setAsk(null)}
          onConfirm={(remarks) => void decide(ask, remarks)}
        />
      )}
    </div>
  );
}

/** One side's lines for the ticket, and their final — this sale, this refund, what is left. */
function Lines({ lines, final, side, showCharge = false }: {
  lines: MappingLine[]; final: MappingSide; side: "vendor" | "mo";
  /** The other side has a cancellation charge: show the column here too, so the two compare. */
  showCharge?: boolean;
}) {
  const cell = "px-1.5 py-1 text-right tabular-nums whitespace-nowrap";
  // The airline's cancellation charge, either side — shown when a line prints one. Taken off a
  // refund's fare (amber), the line adds up: Basic + Tax + SSR + charge = Fare. Printed but not
  // taken off (grey): a sale repeating its refund's, a refund Basic already less it, or a vendor
  // line that IS the charge.
  const charged = showCharge || lines.some((l) => Math.abs(l.charge ?? 0) >= 0.5);
  const chargeNote = (l: MappingLine) => l.charge_applied
    ? "Not given back — taken off this refund"
    : l.kind === "sale"
      ? side === "mo" ? "Printed on the sale as on its refund — counted once" : "Billed on this line — part of its fare"
      : "Already off the refund's Basic — not taken off again";
  // Its own scroll, so a narrow screen scrolls the figures rather than running them into the
  // other side's table.
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
    <table className="w-full text-[11px]">
      <thead>
        <tr className="text-[9px] uppercase tracking-wide text-slate-400">
          <th className="px-1.5 py-1 text-left font-semibold">Line</th>
          <th className={`${cell} font-semibold`}>Basic</th>
          <th className={`${cell} font-semibold`}>Tax</th>
          {charged && (
            <th className={`${cell} font-semibold`} title="The airline's cancellation charge — what it kept of the fare, not given back. Counted once a ticket">
              Canc. charge
            </th>
          )}
          <th className={`${cell} font-semibold`}>Fare</th>
          <th className={`${cell} font-semibold`} title={side === "vendor" ? "What the vendor bills on the line" : "The MO's amount — a refund's what it gave back"}>Net</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((ln) => (
          <tr key={ln.id} className="border-t border-slate-100 align-top">
            <td className="px-1.5 py-1 min-w-[150px]">
              <div className="flex items-center gap-1.5 whitespace-nowrap">
                <span className={`inline-flex px-1.5 py-px rounded text-[9px] font-semibold uppercase ${
                  ln.kind === "refund" ? "bg-rose-50 text-rose-600" : "bg-emerald-50 text-emerald-700"}`}>{ln.kind}</span>
                <span className="text-slate-500">{formatDay(ln.date)}</span>
              </div>
              <div className="text-[10px] text-slate-400 truncate max-w-[200px]" title={ln.source ?? undefined}>
                {side === "mo" && ln.ref ? `Doc ${ln.ref}` : ln.source || ln.ref || "—"}
                {ln.charges_only && ln.kind === "sale" ? " · charges only" : ""}
              </div>
            </td>
            <td className={cell}>{inr(ln.base)}</td>
            <td className={cell}>{inr(ln.tax)}</td>
            {charged && (
              <td className={`${cell} ${ln.charge_applied ? "text-amber-700" : "text-slate-400"}`}
                title={ln.charge ? chargeNote(ln) : undefined}>
                {ln.charge ? inr(ln.charge) : "—"}
              </td>
            )}
            <td className={`${cell} text-slate-800`}
              title={side === "vendor" && ln.kind === "refund"
                ? "What the vendor gave back: its net, with the commission it took back, less TDS — the fare a vendor prints on a refund line is the original ticket's"
                : undefined}>{inr(ln.fare)}</td>
            <td className={`${cell} text-slate-500`}>{inr(ln.net)}</td>
          </tr>
        ))}
        {lines.length > 1 && (
          <tr className="border-t-2 border-slate-300 font-semibold">
            <td className="px-1.5 py-1 text-slate-600">Final{lines.some((l) => l.kind === "refund") && lines.some((l) => l.kind === "sale") ? " — knocked off" : ""}</td>
            <td className={cell}>{inr(final.base)}</td>
            <td className={cell}>{inr(final.tax)}</td>
            {charged && <td className={`${cell} text-amber-700`} title="The ticket's cancellation charge, counted once">{final.charge ? inr(final.charge) : "—"}</td>}
            <td className={`${cell} text-slate-900`}>{inr(final.fare)}</td>
            <td className={cell}>{inr(final.net)}</td>
          </tr>
        )}
      </tbody>
    </table>
    </div>
  );
}

/** A ticket opened: why it is where it is, both sides' lines with their finals, and the decision. */
function Detail({ row }: { row: MappingRow }) {
  const v = row.vendor, m = row.mo;
  // The cancellation charge column on both sides when either has one.
  const charged = [...row.vendor_lines, ...row.mo_lines].some((l) => Math.abs(l.charge ?? 0) >= 0.5);
  return (
    <tr className="bg-slate-50/70 border-b border-slate-200">
      <td />
      <td colSpan={7} className="px-3 py-3">
        {/* Why, across the top; then the two sides' lines side by side, each with the room for
            its five figures — three columns abreast ran the vendor's Net into the MO's table. */}
        <div className="grid gap-3 xl:grid-cols-2 text-[11px]">
          <div className="space-y-1 xl:col-span-2">
            <p className="font-semibold text-slate-600 uppercase tracking-wide text-[10px]">Why</p>
            {row.hints.length ? (
              <ul className="space-y-1 list-disc pl-4 text-slate-600">
                {row.hints.map((h, i) => <li key={i}>{h}</li>)}
              </ul>
            ) : (
              <p className="flex items-center gap-1.5 text-emerald-700"><CheckCircle2 className="w-3.5 h-3.5" /> The MO has this ticket at the same fare.</p>
            )}
            {row.commission_gap != null && Math.abs(row.commission_gap) >= 0.5 && (
              <p className="text-slate-500" title="IATA commission + PLB the MO expects from the vendor — priced against your deals under Commission income">
                Commission: vendor passed {inr(v.commission)} · MO expects {inr(m?.comm_expected ?? 0)}{" "}
                <span className={row.commission_gap > 0 ? "text-emerald-600" : "text-amber-600"}>
                  ({row.commission_gap > 0 ? "+" : ""}{inr(row.commission_gap)})
                </span>
              </p>
            )}
            {row.decision && (
              <div className={`mt-2 px-2.5 py-2 rounded-lg border ${row.decision.stale ? "border-amber-200 bg-amber-50 text-amber-800" : "border-slate-200 bg-white text-slate-600"}`}>
                <b>{DECISION_LABEL[row.decision.decision]}</b>
                {row.decision.decided_at && <> · {formatDay(row.decision.decided_at.slice(0, 10))}</>}
                {row.decision.note && <p className="mt-0.5">{row.decision.note}</p>}
                {row.decision.stale && <p className="mt-0.5">Taken on other figures — the ticket is open again.</p>}
              </div>
            )}
          </div>
          <div className="space-y-1 min-w-0">
            <p className="font-semibold text-slate-600 uppercase tracking-wide text-[10px]">
              Vendor statement{row.vendor_name ? ` — ${row.vendor_name}` : ""}
            </p>
            <Lines lines={row.vendor_lines} final={v} side="vendor" showCharge={charged} />
          </div>
          <div className="space-y-1 min-w-0">
            <p className="font-semibold text-slate-600 uppercase tracking-wide text-[10px]">
              MO{row.status === "other_vendor" && row.mo_vendor_name ? ` — filed under ${row.mo_vendor_name}` : ""}
            </p>
            {m ? <Lines lines={row.mo_lines} final={m} side="mo" showCharge={charged} /> : <p className="text-red-600">Not in the MO.</p>}
          </div>
        </div>
      </td>
    </tr>
  );
}
