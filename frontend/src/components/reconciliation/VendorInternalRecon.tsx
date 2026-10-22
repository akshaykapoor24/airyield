"use client";

// Vendors → Reconciliation → Third Party → GDS ↔ Internal.
//
// Every Third Party GDS statement against every Internal Statement, sorted into the four
// cases a reconciler works through, one at a time:
//   1 Matched           settled — nothing to check again when the next statement loads
//   2 Differences       on both, amounts disagree — resolved by saying which side is wrong
//   3 In GDS only       carried forward — re-checked when the next internal statement loads
//   4 In Internal only  carried forward — re-checked when the next GDS statement loads
// plus Resolved, the decisions taken, and Total, every line of both sides at once. A ticket
// with more than one line (sold and refunded, typically — the sale matched, the refund a
// difference) is shown as one group with all its lines, whichever case each is in. All
// matching is server-side (backend/app/services/vendor_internal_recon.py); this shows one
// case at a time and records the user's decisions.

import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import toast from "react-hot-toast";
import {
  AlertCircle, ArrowLeftRight, ArrowRight, CheckCircle2, ChevronDown, ChevronRight, Clock, Download,
  Hourglass, Layers, Lightbulb, RefreshCw, RotateCcw, Scale, Search, X,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { errorDetail } from "@/components/payment/shared";

type Status = "matched" | "difference" | "vendor_only" | "internal_only";
type OpenCase = Exclude<Status, "matched">;
type Case = Status | "resolved";
/** What the table shows: one case, or every line ("total"). */
type View = Case | "total";
type Decision = "vendor_wrong" | "internal_wrong" | "accepted";

type Side = {
  id: number; ticket_prefix: string | null; pax: string | null; pnr: string | null;
  sector: string; date: string | null; ref: string | null; source: string | null; loaded_at: string | null;
  fare: number; commission: number; charges: number; gst: number; tds: number; net: number;
};
type Resolution = {
  id: number; decision: Decision; note: string | null; status: Status;
  vendor_net: number | null; internal_net: number | null; difference: number | null;
  resolved_at: string | null; stale: boolean;
};
type Row = {
  key: string; ticket_number: string | null;
  kind: "sale" | "refund" | "sale+refund";
  status: Status;
  vendor: Side | null; internal: Side | null;
  diff: Record<string, number> | null; hints: string[];
  pending: "next_statement" | "in_period" | null;
  resolution: Resolution | null; open: boolean;
};
type Coverage = { statements: number; last_date: string | null; last_loaded: string | null };
type Summary = {
  vendor_lines: number; internal_lines: number;
  vendor_tickets: number; internal_tickets: number; tickets: number;
  matched: number; difference: number; vendor_only: number; internal_only: number;
  matched_net: number;
  open: Record<OpenCase, number>; open_amount: Record<OpenCase, number>; resolved: Record<OpenCase, number>;
  bridge: { round_off: number } & Record<OpenCase, number>;
  coverage: { vendor: Coverage; internal: Coverage };
  vendor_net: number; internal_net: number; net_difference: number; difference_amount: number;
};
type Result = { summary: Summary; rows: Row[] };

const KIND: Record<Row["kind"], string> = { sale: "Sale", refund: "Refund", "sale+refund": "Sold & refunded" };
const KIND_CLS: Record<Row["kind"], string> = {
  sale: "bg-emerald-50 text-emerald-700", refund: "bg-amber-100 text-amber-800", "sale+refund": "bg-sky-50 text-sky-700",
};
const CASE_LABEL: Record<Case, string> = {
  matched: "Matched", difference: "Difference", vendor_only: "In GDS only",
  internal_only: "In Internal only", resolved: "Resolved",
};
const CASE_CHIP: Record<Case, string> = {
  matched: "bg-emerald-50 text-emerald-700 border-emerald-200",
  difference: "bg-amber-50 text-amber-800 border-amber-200",
  vendor_only: "bg-red-50 text-red-700 border-red-200",
  internal_only: "bg-violet-50 text-violet-700 border-violet-200",
  resolved: "bg-slate-100 text-slate-600 border-slate-200",
};
// A ticket's lines in reading order: the sale, then what happened to it.
const KIND_ORDER: Record<Row["kind"], number> = { sale: 0, "sale+refund": 1, refund: 2 };
const FIELDS: [keyof Side & string, string][] = [
  ["fare", "Fare + taxes"], ["commission", "Commission / discount"], ["charges", "Charges"],
  ["gst", "GST"], ["tds", "TDS"], ["net", "Net"],
];

const DECISION: Record<Decision, { label: string; short: string; cls: string }> = {
  vendor_wrong:   { label: "GDS statement is wrong",      short: "GDS wrong",      cls: "bg-red-50 text-red-700 border-red-200" },
  internal_wrong: { label: "Internal statement is wrong", short: "Internal wrong", cls: "bg-violet-50 text-violet-700 border-violet-200" },
  accepted:       { label: "Accept as it is",             short: "Accepted",       cls: "bg-slate-100 text-slate-600 border-slate-200" },
};
// What each decision means depends on what is wrong with the line.
const DECISION_HELP: Record<OpenCase, Record<Decision, string>> = {
  difference: {
    vendor_wrong: "The vendor billed it wrong — raise it with them for a correction.",
    internal_wrong: "Your books are wrong — correct the entry in Internal Statement.",
    accepted: "The difference is explained or agreed — nothing to correct.",
  },
  vendor_only: {
    vendor_wrong: "Not your ticket, or billed in error — dispute it with the vendor.",
    internal_wrong: "You missed booking it — add it to Internal Statement.",
    accepted: "Explained — e.g. booked under another ticket number.",
  },
  internal_only: {
    vendor_wrong: "The vendor should have billed it — follow up with them.",
    internal_wrong: "Booked in error — remove it from Internal Statement.",
    accepted: "Explained — e.g. its charges are billed on another ticket.",
  },
};

// The narrower split inside each case, shown as chips above the table.
const SUBS: Record<View, { id: string; label: string; title: string }[]> = {
  total: [
    { id: "matched", label: "Matched", title: "Both statements agree" },
    { id: "difference", label: "Differences", title: "On both, amounts differ — to resolve" },
    { id: "vendor_only", label: "In GDS only", title: "Billed, not in your internal statement yet" },
    { id: "internal_only", label: "In Internal only", title: "In your books, not billed on a GDS statement yet" },
    { id: "resolved", label: "Resolved", title: "Lines you resolved" },
  ],
  difference: [
    { id: "gds_higher", label: "GDS higher", title: "The GDS statement asks for more than your books: a sale charged higher, or a refund credited lower" },
    { id: "internal_higher", label: "Internal higher", title: "Your books show more than the GDS statement asks for" },
  ],
  vendor_only: [
    { id: "next_statement", label: "Expected in next internal statement", title: "Dated after everything your internal statements cover" },
    { id: "in_period", label: "Missing from period loaded", title: "Your internal statements cover this date, and it is not there" },
  ],
  internal_only: [
    { id: "next_statement", label: "Expected in next GDS statement", title: "Dated after everything the GDS statements cover" },
    { id: "in_period", label: "Missing from period loaded", title: "The GDS statements cover this date, and it is not billed" },
  ],
  resolved: [
    { id: "vendor_wrong", label: "GDS wrong", title: DECISION.vendor_wrong.label },
    { id: "internal_wrong", label: "Internal wrong", title: DECISION.internal_wrong.label },
    { id: "accepted", label: "Accepted", title: DECISION.accepted.label },
  ],
  matched: [],
};

const inr = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = (v: number) => `${v > 0 ? "+" : ""}${inr(v)}`;
const fmtDate = (s: string | null | undefined) => {
  if (!s) return "—";
  const d = new Date(s.length === 10 ? `${s}T00:00:00` : s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
};

const caseOf = (r: Row): Case => (r.status === "matched" ? "matched" : r.open ? r.status : "resolved");
const subOf = (r: Row, c: View): string | null => {
  if (c === "total") return caseOf(r);
  if (c === "difference") return (r.diff?.net ?? 0) < 0 ? "gds_higher" : "internal_higher";
  if (c === "vendor_only" || c === "internal_only") return r.pending;
  if (c === "resolved") return r.resolution?.decision ?? null;
  return null;
};

/** Which side is higher, in words — internal − vendor < 0 means the GDS statement asks for more. */
function direction(r: Row): string | null {
  const d = r.diff?.net;
  if (d == null || Math.abs(d) < 1) return null;
  const amt = inr(Math.abs(d));
  if (r.kind === "refund") return d > 0 ? `Vendor refunded ${amt} more` : `Vendor refunded ${amt} less`;
  return d < 0 ? `Vendor charged ${amt} more` : `Vendor charged ${amt} less`;
}

export default function VendorInternalRecon() {
  const [data, setData] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [view, setView] = useState<View | null>(null);
  const [sub, setSub] = useState("");
  const [kind, setKind] = useState<"" | Row["kind"]>("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  // Ticket groups the user folded away — groups start open, so every line is in sight.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [resolving, setResolving] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState(false);

  // Every GDS statement against every internal statement: a line waiting for its partner
  // meets it whichever upload either arrives in.
  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Result>("/reconciliation/vendor-internal");
      setData(data);
      setOpen(new Set());
      setSelected(new Set());
    } catch {
      setError("Reconciliation failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { run(); }, [run]);

  const s = data?.summary;
  // Until the user picks, land on the first case that needs them.
  const active: View = view
    ?? (s ? ((["difference", "vendor_only", "internal_only"] as const).find((c) => s.open[c] > 0) ?? "matched") : "difference");

  const pick = (c: View) => {
    setView(c);
    setSub("");
    setSelected(new Set());
    setOpen(new Set());
  };

  const inCase = useMemo(
    () => (data?.rows ?? []).filter((r) => active === "total" || caseOf(r) === active), [data, active]);
  const subCounts = useMemo(() => {
    const n: Record<string, number> = {};
    inCase.forEach((r) => { const k = subOf(r, active); if (k) n[k] = (n[k] ?? 0) + 1; });
    return n;
  }, [inCase, active]);
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return inCase.filter((r) =>
      (!sub || subOf(r, active) === sub) && (!kind || r.kind === kind) &&
      (!q || [r.ticket_number, r.vendor?.pax, r.internal?.pax, r.vendor?.pnr, r.internal?.pnr,
              r.internal?.ref, r.vendor?.ref, r.vendor?.sector, r.internal?.sector, r.resolution?.note]
        .some((x) => (x ?? "").toLowerCase().includes(q))));
  }, [inCase, active, sub, kind, search]);

  // Every line of a ticket, whichever case it is in — what a ticket group shows.
  const byTicket = useMemo(() => {
    const m = new Map<string, Row[]>();
    (data?.rows ?? []).forEach((r) => {
      if (r.ticket_number) m.set(r.ticket_number, [...(m.get(r.ticket_number) ?? []), r]);
    });
    m.forEach((list) => list.sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind]));
    return m;
  }, [data]);

  // The table, one entry per ticket in the order its first line sorts: the lines this view
  // shows (`here`) and every line the ticket has (`all`).
  const groups = useMemo(() => {
    const out: { id: string; here: Row[]; all: Row[] }[] = [];
    const at = new Map<string, number>();
    rows.forEach((r) => {
      const t = r.ticket_number;
      const i = t ? at.get(t) : undefined;
      if (i != null) { out[i].here.push(r); return; }
      if (t) at.set(t, out.length);
      out.push({ id: t ?? r.key, here: [r], all: t ? byTicket.get(t) ?? [r] : [r] });
    });
    return out;
  }, [rows, byTicket]);
  const multi = groups.filter((g) => g.all.length > 1);

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    setter(next);
  };

  const picked = rows.filter((r) => selected.has(r.key));
  const allPicked = rows.length > 0 && picked.length === rows.length;
  // One decision for many lines needs them in one case — not in Total, which mixes them.
  const selectable = active !== "matched" && active !== "total";

  // Acting on a case pins it: resolving its last line should leave the user looking at an
  // emptied case, not jump them to the next one.
  const submitResolve = async (lines: Row[], decision: Decision, note: string) => {
    setView(active);
    setBusy(true);
    try {
      const { data } = await api.post<Result>("/reconciliation/vendor-internal/resolutions", {
        keys: lines.map((r) => r.key), decision, note: note.trim() || null,
      });
      setData(data);
      setSelected(new Set());
      setResolving(null);
      toast.success(`${lines.length} line${lines.length !== 1 ? "s" : ""} resolved — ${DECISION[decision].short}`);
    } catch (err) {
      toast.error(errorDetail(err, "Could not save the decision. Please try again."));
      setResolving(null);
      run();
    } finally {
      setBusy(false);
    }
  };

  const reopen = async (lines: Row[]) => {
    setView(active);
    setBusy(true);
    try {
      const { data } = await api.post<Result>("/reconciliation/vendor-internal/resolutions/reopen", {
        keys: lines.map((r) => r.key),
      });
      setData(data);
      setSelected(new Set());
      toast.success(`${lines.length} line${lines.length !== 1 ? "s" : ""} reopened`);
    } catch (err) {
      toast.error(errorDetail(err, "Could not reopen. Please try again."));
    } finally {
      setBusy(false);
    }
  };

  const exportCsv = () => {
    const head = ["Case", "Ticket", "Type", "Passenger", "GDS week", "GDS net", "Internal Doc No", "Internal net",
      "Difference (internal − GDS)", "Which side", "Outlook", "Decision", "Note", "Resolved on", "Lines for ticket", "Hints"];
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = rows.map((r) => [
      CASE_LABEL[caseOf(r)],
      `${r.vendor?.ticket_prefix ?? r.internal?.ticket_prefix ?? ""} ${r.ticket_number ?? ""}`.trim(),
      KIND[r.kind], r.internal?.pax ?? r.vendor?.pax, r.vendor?.ref, r.vendor?.net,
      r.internal?.ref, r.internal?.net, r.diff?.net, direction(r),
      r.pending === "next_statement" ? "Expected in next statement" : r.pending === "in_period" ? "Missing from period loaded" : "",
      r.resolution ? DECISION[r.resolution.decision].label : "", r.resolution?.note,
      r.resolution ? fmtDate(r.resolution.resolved_at) : "",
      r.ticket_number ? byTicket.get(r.ticket_number)?.length ?? 1 : 1, r.hints.join(" | "),
    ].map(esc).join(","));
    const blob = new Blob([[head.join(","), ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `gds_vs_internal_${active}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const resolvedTotal = s ? s.resolved.difference + s.resolved.vendor_only + s.resolved.internal_only : 0;
  const cols = COLUMNS[active];

  // One line of this view, with its detail underneath when opened. `record` places it
  // inside a ticket group: indented, tinted, and numbered among the ticket's records.
  const lineRow = (r: Row, record?: RecordPos) => {
    const isOpen = open.has(r.key);
    return (
      <Fragment key={r.key}>
        <tr
          onClick={() => toggle(open, setOpen, r.key)}
          // Opaque backgrounds: the sticky action cell inherits the row's, and
          // a translucent one would let the scrolled columns show through it.
          className={cn("cursor-pointer", record ? cn(RECORD_BG, GROUP_RULE) : "bg-white hover:bg-slate-50",
            (isOpen || selected.has(r.key)) && "bg-blue-50")}
        >
          {selectable && (
            <td className="pl-3" onClick={(e) => e.stopPropagation()}>
              <input type="checkbox" checked={selected.has(r.key)}
                onChange={() => toggle(selected, setSelected, r.key)}
                className="accent-blue-500" aria-label={`Select ${r.ticket_number ?? "line"}`} />
            </td>
          )}
          <td className="pl-2">
            {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-300" />}
          </td>
          <Cells row={r} active={active} busy={busy} record={record}
            onResolve={() => setResolving([r])} onReopen={() => reopen([r])} />
        </tr>
        {isOpen && <DetailRow row={r} span={cols.length} selectable={selectable} grouped={!!record} />}
      </Fragment>
    );
  };

  // A record of the ticket that sits in another case: shown for the whole picture, acted on there.
  const contextRow = (r: Row, record: RecordPos) => {
    const isOpen = open.has(r.key);
    const c = caseOf(r);
    return (
      <Fragment key={r.key}>
        <tr onClick={() => toggle(open, setOpen, r.key)}
          className={cn("cursor-pointer text-slate-500", RECORD_BG, GROUP_RULE, isOpen && "bg-blue-50")}>
          {selectable && <td />}
          <td className="pl-2">
            {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-300" />}
          </td>
          <td colSpan={cols.length} className="px-3 py-2">
            <div className="flex items-center gap-3 whitespace-nowrap">
              <RecordLabel record={record} />
              <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold", KIND_CLS[r.kind])}>{KIND[r.kind]}</span>
              <span className={cn("px-1.5 py-0.5 rounded border text-[10px] font-semibold", CASE_CHIP[c])}>{CASE_LABEL[c]}</span>
              <span className="tabular-nums">GDS <b className="text-slate-600">{inr(r.vendor?.net)}</b></span>
              <span className="tabular-nums">Internal <b className="text-slate-600">{inr(r.internal?.net)}</b></span>
              {r.diff && <span className="tabular-nums">Internal − GDS <b className="text-slate-600">{inr(r.diff.net)}</b></span>}
              <span className="truncate max-w-[260px]">{[r.vendor?.ref, r.internal?.ref].filter(Boolean).join(" · ")}</span>
              <span className="text-[10px] italic text-slate-400">under {CASE_LABEL[c]}</span>
            </div>
          </td>
        </tr>
        {isOpen && <DetailRow row={r} span={cols.length} selectable={selectable} grouped />}
      </Fragment>
    );
  };

  // The ticket itself, above its lines: what each line is, and the ticket's own totals.
  const ticketRow = (g: { id: string; here: Row[]; all: Row[] }) => {
    const folded = collapsed.has(g.id);
    const first = g.all[0];
    const code = first.vendor?.ticket_prefix ?? first.internal?.ticket_prefix;
    const pax = g.all.map((r) => r.internal?.pax ?? r.vendor?.pax).find(Boolean);
    const gds = g.all.reduce((t, r) => t + (r.vendor?.net ?? 0), 0);
    const books = g.all.reduce((t, r) => t + (r.internal?.net ?? 0), 0);
    // Only worth a button of its own when it acts on more than the one line below it.
    const actionable = active === "resolved" ? g.here : selectable ? g.here.filter((r) => r.open) : [];
    const pickedHere = actionable.filter((r) => selected.has(r.key));
    const setPicked = (on: boolean) => {
      const next = new Set(selected);
      actionable.forEach((r) => (on ? next.add(r.key) : next.delete(r.key)));
      setSelected(next);
    };

    // The ticket's totals sit under the money columns this view has, so they read down the
    // same columns as its records; a total with no column here is said in words instead.
    const gap = books - gds;
    const gapCls = Math.abs(gap) >= 1 ? "text-amber-700" : "text-emerald-700";
    const money: Record<string, ReactNode> = {
      "GDS net": inr(gds),
      "Internal net": inr(books),
      Difference: <span className={gapCls}>{signed(gap)}</span>,
      "Round-off": <span className={gapCls}>{signed(gap)}</span>,
    };
    const shown = new Set(cols.map(([h]) => h));
    const unshown = [
      !shown.has("GDS net") && `GDS ${inr(gds)}`,
      !shown.has("Internal net") && `Internal ${inr(books)}`,
      !shown.has("Difference") && !shown.has("Round-off") && `Internal − GDS ${signed(gap)}`,
    ].filter(Boolean);
    const info = (
      <div className="flex flex-wrap items-center gap-1.5">
        {g.all.map((r) => (
          <span key={r.key} className={cn("px-1.5 py-0.5 rounded border text-[10px] font-semibold whitespace-nowrap", CASE_CHIP[caseOf(r)])}>
            {KIND[r.kind]} · {CASE_LABEL[caseOf(r)]}
          </span>
        ))}
        {pax && <span className="ml-1 text-slate-700 whitespace-nowrap">{pax}</span>}
        {unshown.length > 0 && (
          <span className="text-[11px] text-slate-500 tabular-nums whitespace-nowrap">Ticket total: {unshown.join(" · ")}</span>
        )}
      </div>
    );
    const cells: ReactNode[] = [];
    let span = 0;
    let placed = false;
    const flush = (k: string) => {
      if (!span) return;
      cells.push(<td key={k} colSpan={span} className="px-3 py-2">{placed ? null : info}</td>);
      placed = true;
      span = 0;
    };
    cols.forEach(([h, align], i) => {
      if (h === "Ticket") {
        flush(`s${i}`);
        cells.push(
          <td key="ticket" className="px-3 py-2 whitespace-nowrap">
            <span className="font-mono">
              {code && <span className="text-slate-400 mr-1">{code}</span>}
              <b className="text-slate-900">{g.id}</b>
            </span>
            <span className="ml-2 px-1.5 py-0.5 rounded-full bg-blue-600 text-white text-[10px] font-bold">
              {g.all.length} records
            </span>
          </td>,
        );
      } else if (h in money) {
        flush(`s${i}`);
        cells.push(
          <td key={h} className="px-3 py-2 text-right tabular-nums whitespace-nowrap">
            <div className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">Ticket total</div>
            <div className="font-bold text-slate-800">{money[h]}</div>
          </td>,
        );
      } else if (align === "a") {
        flush(`s${i}`);
        cells.push(
          <td key="action" className={cn("px-2 py-2 bg-inherit", STICKY_ACTION)} onClick={(e) => e.stopPropagation()}>
            {actionable.length > 1 && (active === "resolved" ? (
              <button onClick={() => reopen(actionable)} disabled={busy}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-slate-300 bg-white text-slate-600 text-[11px] font-semibold hover:bg-slate-50 disabled:opacity-50">
                <RotateCcw className="w-3 h-3" /> Reopen {actionable.length}
              </button>
            ) : (
              <button onClick={() => setResolving(actionable)} disabled={busy}
                className="px-2.5 py-1 rounded-md border border-amber-300 bg-amber-50 text-amber-800 text-[11px] font-semibold hover:bg-amber-100 disabled:opacity-50">
                Resolve {actionable.length}
              </button>
            ))}
          </td>,
        );
      } else {
        span += 1;
      }
    });
    flush("end");

    return (
      <tr key={`t:${g.id}`} onClick={() => toggle(collapsed, setCollapsed, g.id)}
        className={cn("cursor-pointer bg-slate-100 hover:bg-slate-200", GROUP_RULE)}>
        {selectable && (
          <td className="pl-3" onClick={(e) => e.stopPropagation()}>
            {actionable.length > 1 && (
              <input type="checkbox" checked={pickedHere.length === actionable.length}
                onChange={() => setPicked(pickedHere.length !== actionable.length)}
                className="accent-blue-500" aria-label={`Select ticket ${g.id}`} />
            )}
          </td>
        )}
        <td className="pl-2">
          {folded ? <ChevronRight className="w-4 h-4 text-blue-600" /> : <ChevronDown className="w-4 h-4 text-blue-600" />}
        </td>
        {cells}
      </tr>
    );
  };

  return (
    <div className="space-y-4">
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* everything loaded, the four cases, and what has been decided */}
      {s && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2.5">
          <TotalCard s={s} active={active} onPick={pick} />
          <CaseCard n={1} id="matched" title="Matched" active={active} onPick={pick} accent="border-l-emerald-500" numCls="text-emerald-700"
            count={s.matched} unit="settled" amount={`net ${inr(s.matched_net)}`}
            what="Both statements agree. No need to check these again when the next statement loads." />
          <CaseCard n={2} id="difference" title="Differences" active={active} onPick={pick} accent="border-l-amber-500" numCls="text-amber-700"
            count={s.open.difference} unit="to resolve" amount={`${signed(s.open_amount.difference)} internal − GDS`}
            what="On both, amounts differ. Decide which statement is wrong."
            extra={s.resolved.difference ? `${s.resolved.difference} resolved` : undefined} />
          <CaseCard n={3} id="vendor_only" title="In GDS only" active={active} onPick={pick} accent="border-l-red-500" numCls="text-red-700"
            count={s.open.vendor_only} unit="waiting" amount={`${inr(s.open_amount.vendor_only)} on GDS`}
            what="Billed, not in your internal statement yet. Re-checked when the next internal statement loads." />
          <CaseCard n={4} id="internal_only" title="In Internal only" active={active} onPick={pick} accent="border-l-violet-500" numCls="text-violet-700"
            count={s.open.internal_only} unit="waiting" amount={`${inr(s.open_amount.internal_only)} in books`}
            what="In your books, not billed on a GDS statement yet. Re-checked when the next GDS statement loads." />
          <CaseCard id="resolved" title="Resolved" active={active} onPick={pick} accent="border-l-slate-400" numCls="text-slate-700"
            count={resolvedTotal} unit="decided"
            what="Lines you resolved. A line reopens by itself if either statement's figures change." />
        </div>
      )}

      {/* the net difference, explained by case */}
      {s && (
        <div className="bg-white border border-slate-200 rounded-xl px-4 py-2.5 flex flex-wrap items-center gap-x-8 gap-y-2">
          <Total label="GDS net" value={inr(s.vendor_net)}
            sub={`${s.vendor_lines} lines · ${s.coverage.vendor.statements} statement${s.coverage.vendor.statements !== 1 ? "s" : ""} to ${fmtDate(s.coverage.vendor.last_date)}`} />
          <Total label="Internal net" value={inr(s.internal_net)}
            sub={`${s.internal_lines} lines · ${s.coverage.internal.statements} statement${s.coverage.internal.statements !== 1 ? "s" : ""} to ${fmtDate(s.coverage.internal.last_date)}`} />
          <Total label="Net difference" value={inr(s.net_difference)} sub="internal − GDS"
            tone={Math.abs(s.net_difference) >= 1 ? "amber" : "plain"} />
          <div className="flex-1 min-w-[260px]">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Made up of</p>
            <p className="text-xs text-slate-500 tabular-nums flex flex-wrap gap-x-3">
              <span className="whitespace-nowrap">Differences <b className="text-amber-700">{signed(s.bridge.difference)}</b></span>
              <span className="whitespace-nowrap">In GDS only <b className="text-red-700">{signed(s.bridge.vendor_only)}</b></span>
              <span className="whitespace-nowrap">In Internal only <b className="text-violet-700">{signed(s.bridge.internal_only)}</b></span>
              {Math.abs(s.bridge.round_off) >= 0.01 && (
                <span className="whitespace-nowrap">Round-off <b className="text-slate-600">{signed(s.bridge.round_off)}</b></span>
              )}
            </p>
          </div>
        </div>
      )}

      {s && <CaseBanner active={active} s={s} />}

      {/* filters and actions for the case on screen */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Ticket, pax, PNR, Doc No, sector…"
            className="pl-8 pr-3 py-2 text-xs border border-slate-200 rounded-lg w-56 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
        <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}
          className="py-2 px-2.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-600">
          <option value="">Sales &amp; refunds</option>
          <option value="sale">Sales</option>
          <option value="refund">Refunds</option>
          <option value="sale+refund">Sold &amp; refunded</option>
        </select>
        {SUBS[active].length > 0 && (
          <div className="flex items-center gap-1">
            <SubChip label="All" n={inCase.length} on={!sub} onClick={() => setSub("")} />
            {SUBS[active].map((x) => (
              <SubChip key={x.id} label={x.label} title={x.title} n={subCounts[x.id] ?? 0}
                on={sub === x.id} onClick={() => setSub(sub === x.id ? "" : x.id)} />
            ))}
          </div>
        )}
        <span className="text-xs text-slate-400">
          {rows.length} line{rows.length !== 1 ? "s" : ""} · {groups.length} ticket{groups.length !== 1 ? "s" : ""}
        </span>
        {multi.length > 0 && (
          <button type="button"
            onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(multi.map((g) => g.id)))}
            className="text-[11px] font-semibold text-blue-600 hover:underline">
            {collapsed.size ? "Expand all tickets" : "Collapse all tickets"}
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          {picked.length > 0 && active !== "resolved" && active !== "matched" && active !== "total" && (
            <button onClick={() => setResolving(picked)} disabled={busy}
              className="flex items-center gap-1.5 px-3 py-2 bg-amber-500 text-white rounded-lg text-xs font-semibold hover:bg-amber-600 disabled:opacity-50">
              <Scale className="w-3.5 h-3.5" /> Resolve {picked.length} selected
            </button>
          )}
          {picked.length > 0 && active === "resolved" && (
            <button onClick={() => reopen(picked)} disabled={busy}
              className="flex items-center gap-1.5 px-3 py-2 border border-slate-300 rounded-lg text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
              <RotateCcw className="w-3.5 h-3.5" /> Reopen {picked.length} selected
            </button>
          )}
          <button onClick={exportCsv} disabled={!rows.length}
            className="flex items-center gap-1.5 px-3 py-2 border border-slate-200 rounded-lg text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40">
            <Download className="w-3.5 h-3.5" /> CSV
          </button>
          <button onClick={run} disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 text-white rounded-lg text-xs font-semibold hover:bg-blue-700 disabled:opacity-50">
            <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} /> Reconcile
          </button>
        </div>
      </div>

      {/* the lines of this case, a ticket with several lines grouped under the ticket */}
      <div className={cn("bg-white border border-slate-200 rounded-xl overflow-hidden", loading && "opacity-60")}>
        {/* keyed by case: a new case starts scrolled to its first column */}
        <div key={active} className="overflow-x-auto">
          <table className="w-full min-w-max text-xs">
            <thead>
              <tr className="bg-slate-800 text-white/80">
                {selectable && (
                  <th className="w-8 pl-3">
                    <input type="checkbox" checked={allPicked} disabled={!rows.length}
                      onChange={() => setSelected(allPicked ? new Set() : new Set(rows.map((r) => r.key)))}
                      className="accent-blue-500" aria-label="Select all" />
                  </th>
                )}
                <th className="w-6" />
                {cols.map(([h, align]) => (
                  <th key={h} className={cn("px-3 py-2 text-[11px] font-semibold uppercase tracking-wide",
                    align === "r" ? "text-right" : "text-left", align === "a" && STICKY_ACTION + " bg-slate-800")}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.length === 0 && (
                <tr><td colSpan={cols.length + 2} className="px-4 py-10 text-center text-slate-400">
                  {!data ? "Loading…" : inCase.length ? "Nothing to show for these filters." : EMPTY[active]}
                </td></tr>
              )}
              {groups.map((g) => (g.all.length < 2 ? g.here.map((r) => lineRow(r)) : (
                <Fragment key={`g:${g.id}`}>
                  {ticketRow(g)}
                  {!collapsed.has(g.id) && g.all.map((r, i) => {
                    const pos = { n: i + 1, of: g.all.length, last: i === g.all.length - 1 };
                    return g.here.includes(r) ? lineRow(r, pos) : contextRow(r, pos);
                  })}
                </Fragment>
              )))}
            </tbody>
          </table>
        </div>
      </div>

      {resolving && resolving.length > 0 && (
        <ResolveDialog rows={resolving} busy={busy} onClose={() => setResolving(null)}
          onSubmit={(d, note) => submitResolve(resolving, d, note)} />
      )}
    </div>
  );
}

/** Where a record sits among its ticket's records: "Record 2 of 2", drawn as the last branch. */
type RecordPos = { n: number; of: number; last: boolean };

// A ticket group: one solid rule down its left edge, from the ticket row through every record
// and opened detail, so where a ticket starts and ends reads at a glance.
const GROUP_RULE = "border-l-[3px] border-l-blue-500";
// A record under its ticket. Opaque: the sticky action cell inherits the row's background.
const RECORD_BG = "bg-[#f5f8ff] hover:bg-[#e9f1ff]";

/** A record's place under its ticket — indented, and joined to it by a tree branch. */
function RecordLabel({ record }: { record: RecordPos }) {
  return (
    <span className="inline-flex items-center gap-1.5 pl-5 font-sans whitespace-nowrap">
      <span className="text-blue-400 select-none" aria-hidden>{record.last ? "└─" : "├─"}</span>
      <span className="px-1.5 py-0.5 rounded bg-white border border-blue-200 text-[10px] font-bold text-blue-700">
        Record {record.n} of {record.of}
      </span>
    </span>
  );
}

function DetailRow({ row, span, selectable, grouped }: { row: Row; span: number; selectable: boolean; grouped: boolean }) {
  return (
    <tr className={grouped ? cn("bg-[#f5f8ff]", GROUP_RULE) : "bg-slate-50/60"}>
      <td colSpan={selectable ? 2 : 1} />
      <td colSpan={span} className={cn("py-3 pr-3", grouped ? "pl-12" : "pl-3")}>
        <Detail row={row} />
      </td>
    </tr>
  );
}

// Column headings per case — each case asks a different question of the same line. "a" is
// the action column, pinned to the right edge so it stays in reach however wide the hints run.
const COLUMNS: Record<View, [string, "l" | "r" | "a"][]> = {
  // Every line, each with the case it is in — and acted on in place.
  total: [["Ticket", "l"], ["Type", "l"], ["Case", "l"], ["Passenger", "l"], ["GDS net", "r"], ["Internal net", "r"],
    ["Difference", "r"], ["GDS statement", "l"], ["Internal", "l"], ["Why", "l"], ["", "a"]],
  // Money before references: on a laptop screen the difference must not be the part that scrolls away.
  difference: [["Ticket", "l"], ["Type", "l"], ["Passenger", "l"], ["GDS net", "r"], ["Internal net", "r"],
    ["Difference", "r"], ["GDS statement", "l"], ["Internal", "l"], ["Why", "l"], ["", "a"]],
  vendor_only: [["Ticket", "l"], ["Type", "l"], ["Passenger", "l"], ["Date", "l"], ["GDS statement", "l"],
    ["GDS net", "r"], ["Outlook", "l"], ["Why", "l"], ["", "a"]],
  internal_only: [["Ticket", "l"], ["Type", "l"], ["Passenger", "l"], ["Date", "l"], ["Internal", "l"],
    ["Internal net", "r"], ["Outlook", "l"], ["Why", "l"], ["", "a"]],
  matched: [["Ticket", "l"], ["Type", "l"], ["Passenger", "l"], ["GDS net", "r"], ["Internal net", "r"],
    ["Round-off", "r"], ["GDS statement", "l"], ["Internal", "l"]],
  resolved: [["Ticket", "l"], ["Type", "l"], ["Was", "l"], ["Passenger", "l"], ["GDS net", "r"], ["Internal net", "r"],
    ["Difference", "r"], ["Decision", "l"], ["Resolved", "l"], ["Note", "l"], ["", "a"]],
};
const STICKY_ACTION = "sticky right-0 shadow-[-8px_0_8px_-8px_rgba(15,23,42,0.25)]";

const EMPTY: Record<View, string> = {
  total: "Nothing loaded yet — upload a Third Party GDS statement and an internal statement.",
  matched: "No line matches yet.",
  difference: "No differences left to resolve.",
  vendor_only: "Everything on the GDS statements is in your internal statement.",
  internal_only: "Everything in your internal statement is billed on a GDS statement.",
  resolved: "Nothing resolved yet. Resolve a difference and it appears here.",
};

function Cells({ row: r, active, busy, record, onResolve, onReopen }: {
  row: Row; active: View; busy: boolean; record?: RecordPos; onResolve: () => void; onReopen: () => void;
}) {
  const code = r.vendor?.ticket_prefix ?? r.internal?.ticket_prefix;
  const d = r.diff?.net;
  const pax = r.internal?.pax ?? r.vendor?.pax;
  const td = "px-3 py-2 whitespace-nowrap";
  const num = "px-3 py-2 text-right tabular-nums whitespace-nowrap";

  // Under its ticket a record is numbered rather than repeating the ticket number the row
  // above already shows — which is still there on hover.
  const ticket = (
    <td className={cn(td, "font-mono")} title={record ? `${code ? `${code} ` : ""}${r.ticket_number ?? ""}` : undefined}>
      {record ? <RecordLabel record={record} /> : (
        <>
          {code && <span className="text-slate-400 mr-1">{code}</span>}
          <b className="text-slate-800">{r.ticket_number ?? "—"}</b>
        </>
      )}
      {r.open && r.resolution?.stale && (
        <span title={`Resolved ${fmtDate(r.resolution.resolved_at)} as “${DECISION[r.resolution.decision].label}” at ${inr(r.resolution.difference)} — the figures have changed since`}
          className="ml-1.5 font-sans px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-orange-50 text-orange-700 border-orange-200">
          Reopened
        </span>
      )}
    </td>
  );
  const type = (
    <td className={td}>
      <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold", KIND_CLS[r.kind])}>{KIND[r.kind]}</span>
    </td>
  );
  // A table cell ignores max-width, so each long text sits in a capped, truncating block.
  const capped = (text: string | null | undefined, w: string, cls = "") => (
    <td className={cn(td, cls)}><div className={cn("truncate", w)} title={text ?? undefined}>{text ?? "—"}</div></td>
  );
  const passenger = capped(pax, "max-w-[170px]", "text-slate-700");
  const gdsRef = capped(r.vendor?.ref ?? r.vendor?.source, "max-w-[170px]", "text-slate-600");
  const intRef = capped(r.internal?.ref, "max-w-[150px]", "text-slate-600 font-mono");
  const why = (
    <td className="px-3 py-2 text-slate-600">
      {r.hints.length ? (
        <span className="flex items-start gap-1.5 max-w-[320px]" title={r.hints.join("\n")}>
          <Lightbulb className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-px" />
          <span className="truncate">{r.hints[0]}</span>
          {r.hints.length > 1 && <span className="text-slate-400 shrink-0">+{r.hints.length - 1}</span>}
        </span>
      ) : null}
    </td>
  );
  const resolveBtn = (
    <td className={cn("px-2 py-2 bg-inherit", STICKY_ACTION)} onClick={(e) => e.stopPropagation()}>
      <button onClick={onResolve} disabled={busy}
        className="px-2.5 py-1 rounded-md border border-amber-300 bg-amber-50 text-amber-800 text-[11px] font-semibold hover:bg-amber-100 disabled:opacity-50">
        Resolve
      </button>
    </td>
  );
  const reopenBtn = (
    <td className={cn("px-2 py-2 bg-inherit", STICKY_ACTION)} onClick={(e) => e.stopPropagation()}>
      <button onClick={onReopen} disabled={busy}
        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-slate-300 bg-white text-slate-600 text-[11px] font-semibold hover:bg-slate-50 disabled:opacity-50">
        <RotateCcw className="w-3 h-3" /> Reopen
      </button>
    </td>
  );
  const outlook = (
    <td className={td}>
      {r.pending === "next_statement" ? (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-sky-50 text-sky-700 border-sky-200">
          <Clock className="w-3 h-3" /> Expected in next statement
        </span>
      ) : r.pending === "in_period" ? (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-amber-50 text-amber-800 border-amber-200">
          <AlertCircle className="w-3 h-3" /> Missing from period loaded
        </span>
      ) : <span className="text-slate-300">—</span>}
    </td>
  );

  switch (active) {
    case "total": {
      const c = caseOf(r);
      return (
        <>
          {ticket}{type}
          <td className={td}>
            <span className={cn("px-1.5 py-0.5 rounded border text-[10px] font-semibold", CASE_CHIP[c])}>{CASE_LABEL[c]}</span>
          </td>
          {passenger}
          <td className={num}>{inr(r.vendor?.net)}</td>
          <td className={num}>{inr(r.internal?.net)}</td>
          <td className={cn(num, d != null && Math.abs(d) >= 1 ? "font-semibold text-amber-700" : "text-slate-400")}>
            {d == null ? "—" : inr(d)}
          </td>
          {gdsRef}{intRef}{why}
          {c === "resolved" ? reopenBtn : c === "matched"
            ? <td className={cn("px-2 py-2 bg-inherit", STICKY_ACTION)} /> : resolveBtn}
        </>
      );
    }
    case "difference": {
      const dir = direction(r);
      return (
        <>
          {ticket}{type}{passenger}
          <td className={num}>{inr(r.vendor?.net)}</td>
          <td className={num}>{inr(r.internal?.net)}</td>
          <td className={num}>
            <div className="font-semibold text-amber-700">{d == null ? "—" : inr(d)}</div>
            {dir && <div className={cn("text-[10px] font-medium", (d ?? 0) < 0 ? "text-red-600" : "text-sky-700")}>{dir}</div>}
          </td>
          {gdsRef}{intRef}{why}{resolveBtn}
        </>
      );
    }
    case "vendor_only":
      return (
        <>
          {ticket}{type}{passenger}
          <td className={cn(td, "text-slate-500 font-mono")}>{fmtDate(r.vendor?.date)}</td>
          {gdsRef}
          <td className={num}>{inr(r.vendor?.net)}</td>
          {outlook}{why}{resolveBtn}
        </>
      );
    case "internal_only":
      return (
        <>
          {ticket}{type}{passenger}
          <td className={cn(td, "text-slate-500 font-mono")}>{fmtDate(r.internal?.date)}</td>
          {intRef}
          <td className={num}>{inr(r.internal?.net)}</td>
          {outlook}{why}{resolveBtn}
        </>
      );
    case "matched":
      return (
        <>
          {ticket}{type}{passenger}
          <td className={num}>{inr(r.vendor?.net)}</td>
          <td className={num}>{inr(r.internal?.net)}</td>
          <td className={cn(num, "text-emerald-600")}>
            {d != null && Math.abs(d) >= 0.005 ? inr(d) : <CheckCircle2 className="w-3.5 h-3.5 inline" />}
          </td>
          {gdsRef}{intRef}
        </>
      );
    case "resolved": {
      const res = r.resolution!;
      return (
        <>
          {ticket}{type}
          <td className={td}>
            <span className={cn("px-1.5 py-0.5 rounded border text-[10px] font-semibold", CASE_CHIP[r.status])}>
              {CASE_LABEL[r.status]}
            </span>
          </td>
          {passenger}
          <td className={num}>{inr(r.vendor?.net)}</td>
          <td className={num}>{inr(r.internal?.net)}</td>
          <td className={cn(num, "font-semibold text-slate-600")}>{d == null ? "—" : inr(d)}</td>
          <td className={td}>
            <span className={cn("px-1.5 py-0.5 rounded border text-[10px] font-semibold", DECISION[res.decision].cls)}>
              {DECISION[res.decision].short}
            </span>
          </td>
          <td className={cn(td, "text-slate-500")}>{fmtDate(res.resolved_at)}</td>
          {capped(res.note, "max-w-[320px]", "text-slate-600")}
          {reopenBtn}
        </>
      );
    }
  }
}

/** Everything loaded on each side — the totals the four cases divide up. */
function TotalCard({ s, active, onPick }: { s: Summary; active: View; onPick: (c: View) => void }) {
  const on = active === "total";
  const side = (label: string, net: number, lines: number, tickets: number) => (
    <div>
      <p className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold text-slate-500">{label}</span>
        <span className="text-sm font-bold tabular-nums text-slate-800">{inr(net)}</span>
      </p>
      <p className="text-[10px] text-slate-400">
        {lines} line{lines !== 1 ? "s" : ""} · {tickets} ticket{tickets !== 1 ? "s" : ""}
      </p>
    </div>
  );
  return (
    <button
      type="button"
      onClick={() => onPick("total")}
      className={cn("text-left bg-white border border-l-4 border-l-blue-500 rounded-xl px-3.5 py-3 transition-colors",
        on ? "ring-2 ring-blue-200 border-t-blue-300 border-r-blue-300 border-b-blue-300" : "border-t-slate-200 border-r-slate-200 border-b-slate-200 hover:bg-slate-50")}
    >
      <div className="flex items-baseline gap-1.5">
        <span className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Total</span>
        <span className="ml-auto text-[11px] text-slate-400">
          <b className="text-blue-700 tabular-nums">{s.tickets}</b> tickets
        </span>
      </div>
      <div className="mt-1.5 space-y-1">
        {side("GDS", s.vendor_net, s.vendor_lines, s.vendor_tickets)}
        {side("Internal", s.internal_net, s.internal_lines, s.internal_tickets)}
      </div>
    </button>
  );
}

function CaseCard({ n, id, title, active, onPick, accent, numCls, count, unit, amount, what, extra }: {
  n?: number; id: Case; title: string; active: View; onPick: (c: View) => void; accent: string; numCls: string;
  count: number; unit: string; amount?: string; what: string; extra?: string;
}) {
  const on = active === id;
  return (
    <button
      type="button"
      onClick={() => onPick(id)}
      className={cn("text-left bg-white border border-l-4 rounded-xl px-3.5 py-3 transition-colors", accent,
        on ? "ring-2 ring-blue-200 border-t-blue-300 border-r-blue-300 border-b-blue-300" : "border-t-slate-200 border-r-slate-200 border-b-slate-200 hover:bg-slate-50")}
    >
      <div className="flex items-center gap-1.5">
        {n != null && (
          <span className="w-4 h-4 shrink-0 rounded-full bg-slate-100 text-[10px] font-bold text-slate-500 flex items-center justify-center">{n}</span>
        )}
        <span className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{title}</span>
      </div>
      <p className="mt-1 flex items-baseline gap-1.5">
        <span className={cn("text-2xl font-bold tabular-nums", numCls)}>{count}</span>
        <span className="text-[11px] text-slate-400">{unit}</span>
        {extra && <span className="ml-auto text-[10px] font-semibold text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">{extra}</span>}
      </p>
      {amount && <p className="text-[11px] tabular-nums text-slate-500">{amount}</p>}
      <p className="mt-1.5 text-[11px] text-slate-400 leading-snug">{what}</p>
    </button>
  );
}

function CaseBanner({ active, s }: { active: View; s: Summary }) {
  const cov = s.coverage;
  const tone: Record<View, string> = {
    total: "bg-blue-50/50 border-blue-100 text-blue-900",
    matched: "bg-emerald-50/60 border-emerald-100 text-emerald-900",
    difference: "bg-amber-50/60 border-amber-100 text-amber-900",
    vendor_only: "bg-red-50/50 border-red-100 text-red-900",
    internal_only: "bg-violet-50/50 border-violet-100 text-violet-900",
    resolved: "bg-slate-50 border-slate-200 text-slate-700",
  };
  const checked = (c: Coverage, what: string) =>
    `Checked against ${c.statements} ${what} statement${c.statements !== 1 ? "s" : ""}${c.last_date ? ` dated up to ${fmtDate(c.last_date)}` : ""}`;
  const content: Record<View, ReactNode> = {
    total: (
      <><Layers className="w-4 h-4 shrink-0 text-blue-600" />
        <span><b>Every line on both sides</b> — {s.vendor_lines} GDS and {s.internal_lines} internal, across {s.tickets} tickets — each with the case it is in.
          A ticket with more than one line (sold and refunded, say) is grouped under the ticket with its total. Lines are resolved here or in their own case.</span></>
    ),
    matched: (
      <><CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
        <span><b>Settled.</b> Both statements agree on these, within ₹1 of round-off. They don&apos;t need checking again when the next statement is loaded.</span></>
    ),
    difference: (
      <><Scale className="w-4 h-4 shrink-0 text-amber-600" />
        <span><b>On both statements, but the amounts differ.</b> The difference can sit on either side. Open a line to see which figure moved, then resolve it: <i>GDS statement is wrong</i>, <i>Internal statement is wrong</i>, or <i>Accept as it is</i>. Tick several to resolve them together.</span></>
    ),
    vendor_only: (
      <><Hourglass className="w-4 h-4 shrink-0 text-red-600" />
        <span className="flex-1"><b>Billed by the vendor, not in your internal statement.</b> Carried forward. {checked(cov.internal, "internal")}. They are re-checked automatically when the next internal statement is loaded.</span>
        <Link href="/internal-statement/upload" className="shrink-0 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline">
          Load internal statement <ArrowRight className="w-3 h-3" /></Link></>
    ),
    internal_only: (
      <><Hourglass className="w-4 h-4 shrink-0 text-violet-600" />
        <span className="flex-1"><b>In your internal statement, not billed by the vendor.</b> Carried forward. {checked(cov.vendor, "GDS")}. They are re-checked automatically when the next GDS statement is loaded.</span>
        <Link href="/vendors/statements/third-party/gds" className="shrink-0 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline">
          Load GDS statement <ArrowRight className="w-3 h-3" /></Link></>
    ),
    resolved: (
      <><CheckCircle2 className="w-4 h-4 shrink-0 text-slate-500" />
        <span>The decisions you took. If either statement&apos;s figures for a line change later, it moves back to its case marked <b>Reopened</b>. Reopen a line here to undo a decision.</span></>
    ),
  };
  return (
    <div className={cn("flex items-center gap-2.5 px-4 py-2.5 border rounded-xl text-xs", tone[active])}>
      {content[active]}
    </div>
  );
}

function ResolveDialog({ rows, busy, onClose, onSubmit }: {
  rows: Row[]; busy: boolean; onClose: () => void; onSubmit: (d: Decision, note: string) => void;
}) {
  const [decision, setDecision] = useState<Decision | null>(null);
  const [note, setNote] = useState("");
  const st = rows[0].status as OpenCase;
  const one = rows.length === 1 ? rows[0] : null;
  const total = rows.reduce((t, r) => t + (r.diff?.net ?? (r.vendor ? -r.vendor.net : r.internal?.net ?? 0)), 0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-800">
            Resolve {one ? `ticket ${one.ticket_number ?? ""}` : `${rows.length} lines`}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Close"><X className="w-4 h-4" /></button>
        </div>
        <div className="px-5 py-4 space-y-4">
          <div className="grid grid-cols-3 gap-2 text-xs">
            <MiniStat label="GDS net" value={one ? inr(one.vendor?.net) : inr(rows.reduce((t, r) => t + (r.vendor?.net ?? 0), 0))} />
            <MiniStat label="Internal net" value={one ? inr(one.internal?.net) : inr(rows.reduce((t, r) => t + (r.internal?.net ?? 0), 0))} />
            <MiniStat label="Internal − GDS" value={inr(total)} tone />
          </div>
          {one && direction(one) && <p className="text-xs text-slate-500 -mt-2">{direction(one)}.</p>}
          {st !== "difference" && (
            <p className="text-[11px] text-slate-500 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
              Lines on one side only are re-checked automatically when the next statement loads. Resolve one now only if you already know the answer.
            </p>
          )}
          <div className="space-y-2">
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">Which statement is wrong?</p>
            {(Object.keys(DECISION) as Decision[]).map((d) => (
              <label key={d}
                className={cn("flex items-start gap-2.5 px-3 py-2.5 border rounded-lg cursor-pointer",
                  decision === d ? "border-blue-400 bg-blue-50/60 ring-1 ring-blue-200" : "border-slate-200 hover:bg-slate-50")}>
                <input type="radio" name="decision" checked={decision === d} onChange={() => setDecision(d)} className="mt-0.5 accent-blue-600" />
                <span>
                  <span className="block text-xs font-semibold text-slate-800">{DECISION[d].label}</span>
                  <span className="block text-[11px] text-slate-500">{DECISION_HELP[st][d]}</span>
                </span>
              </label>
            ))}
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500 mb-1">Note <span className="font-normal normal-case text-slate-400">(optional)</span></p>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000}
              placeholder="e.g. Raised with Globe on 14 Oct — debit note awaited"
              className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400" />
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-100">
          <button onClick={onClose} className="px-3 py-2 text-xs text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50">Cancel</button>
          <button onClick={() => decision && onSubmit(decision, note)} disabled={!decision || busy}
            className="px-3 py-2 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {busy ? "Saving…" : rows.length > 1 ? `Resolve ${rows.length} lines` : "Resolve"}
          </button>
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value, tone }: { label: string; value: string; tone?: boolean }) {
  return (
    <div className="bg-slate-50 border border-slate-200 rounded-lg px-2.5 py-1.5">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className={cn("font-bold tabular-nums", tone ? "text-amber-700" : "text-slate-800")}>{value}</p>
    </div>
  );
}

function SubChip({ label, n, on, onClick, title }: { label: string; n: number; on: boolean; onClick: () => void; title?: string }) {
  return (
    <button type="button" onClick={onClick} title={title}
      className={cn("px-2 py-1.5 rounded-lg border text-[11px] font-semibold whitespace-nowrap",
        on ? "bg-blue-50 border-blue-300 text-blue-700" : "bg-white border-slate-200 text-slate-500 hover:bg-slate-50")}>
      {label} <span className={cn("ml-0.5 tabular-nums", on ? "text-blue-500" : "text-slate-400")}>{n}</span>
    </button>
  );
}

function Detail({ row }: { row: Row }) {
  const v = row.vendor, i = row.internal;
  const res = row.resolution;
  const waiting = row.open && (row.status === "vendor_only" || row.status === "internal_only") ? (v ?? i) : null;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-4">
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-100 text-slate-500">
              <th className="px-3 py-1.5 text-left font-semibold" />
              <th className="px-3 py-1.5 text-right font-semibold">GDS statement</th>
              <th className="px-3 py-1.5 text-right font-semibold">Internal statement</th>
              <th className="px-3 py-1.5 text-right font-semibold">Internal − GDS</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {FIELDS.map(([k, label]) => {
              const dv = row.diff?.[k];
              return (
                <tr key={k} className={k === "net" ? "font-semibold" : ""}>
                  <td className="px-3 py-1.5 text-slate-600">{label}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{v ? inr(v[k] as number) : "—"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{i ? inr(i[k] as number) : "—"}</td>
                  <td className={cn("px-3 py-1.5 text-right tabular-nums",
                    dv == null ? "text-slate-300" : Math.abs(dv) >= 0.5 ? "text-amber-700 font-semibold" : "text-slate-400")}>
                    {dv == null ? "—" : inr(dv)}
                  </td>
                </tr>
              );
            })}
            <tr className="text-slate-500">
              <td className="px-3 py-1.5">Reference</td>
              <td className="px-3 py-1.5 text-right">{v?.ref ?? "—"}</td>
              <td className="px-3 py-1.5 text-right font-mono">{i?.ref ?? "—"}</td>
              <td />
            </tr>
            <tr className="text-slate-500">
              <td className="px-3 py-1.5">Passenger · PNR</td>
              <td className="px-3 py-1.5 text-right">{v ? `${v.pax ?? "—"} · ${v.pnr ?? "—"}` : "—"}</td>
              <td className="px-3 py-1.5 text-right">{i ? `${i.pax ?? "—"} · ${i.pnr ?? "—"}` : "—"}</td>
              <td />
            </tr>
            <tr className="text-slate-500">
              <td className="px-3 py-1.5">Sector · date</td>
              <td className="px-3 py-1.5 text-right font-mono">{v ? `${v.sector || "—"} · ${v.date ?? "—"}` : "—"}</td>
              <td className="px-3 py-1.5 text-right font-mono">{i ? `${i.sector || "—"} · ${i.date ?? "—"}` : "—"}</td>
              <td />
            </tr>
            <tr className="text-slate-400">
              <td className="px-3 py-1.5">File · loaded</td>
              <td className="px-3 py-1.5 text-right truncate max-w-[220px]">{v ? `${v.source ?? "—"} · ${fmtDate(v.loaded_at)}` : "—"}</td>
              <td className="px-3 py-1.5 text-right truncate max-w-[220px]">{i ? `${i.source ?? "—"} · ${fmtDate(i.loaded_at)}` : "—"}</td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <div className="space-y-1.5">
        {res && (
          <div className={cn("text-xs rounded-lg px-2.5 py-2 border",
            res.stale ? "bg-orange-50 border-orange-200 text-orange-900" : "bg-white border-slate-200 text-slate-700")}>
            <p className="font-semibold">
              {res.stale ? "Was resolved — figures changed since" : "Resolved"}: {DECISION[res.decision].label}
            </p>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {fmtDate(res.resolved_at)} · at GDS {inr(res.vendor_net)} / internal {inr(res.internal_net)}
              {res.difference != null && ` · difference ${inr(res.difference)}`}
            </p>
            {res.note && <p className="mt-1 text-slate-700">“{res.note}”</p>}
          </div>
        )}
        {waiting && (
          <p className="flex items-start gap-1.5 text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5">
            <Hourglass className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-px" />
            Waiting since {fmtDate(waiting.loaded_at)}, when {waiting.source ?? "its statement"} was loaded.
            {row.pending === "next_statement" ? " It is dated after everything the other side has loaded — expected in its next statement."
              : row.pending === "in_period" ? " The other side's statements already cover its date." : ""}
          </p>
        )}
        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1 pt-1">
          <ArrowLeftRight className="w-3 h-3" /> Why
        </p>
        {row.hints.length ? row.hints.map((h, n) => (
          <p key={n} className="flex items-start gap-1.5 text-xs text-slate-700 bg-amber-50/60 border border-amber-100 rounded-lg px-2.5 py-1.5">
            <Lightbulb className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-px" /> {h}
          </p>
        )) : (
          <p className="flex items-center gap-1.5 text-xs text-emerald-700">
            <CheckCircle2 className="w-3.5 h-3.5" /> Every compared figure agrees.
          </p>
        )}
      </div>
    </div>
  );
}

function Total({ label, value, sub, tone = "plain" }: { label: string; value: string; sub?: string; tone?: "plain" | "amber" }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className={cn("text-sm font-bold tabular-nums", tone === "amber" ? "text-amber-700" : "text-slate-800")}>{value}</p>
      {sub && <p className="text-[10px] text-slate-400">{sub}</p>}
    </div>
  );
}
