"use client";

// Reconciliation → Vendor Reconciliation → Third Party GDS.
//
// Every vendor's Third Party GDS statements against Internal Statement, sale with sale and
// refund with refund, narrowed by three filters — a vendor (Agency Master), one of its
// statements, a booking period — and read as an accountant's reconciliation statement:
//
//   Billed as per vendor statement
//     Less 1  Extra fare charged by vendor          Add 2  Less fare charged by vendor
//     Less 3  Extra refund charges by vendor        Add 4  Less refund charges by vendor
//     Less 5  Extra commission charged by vendor    Add 6  Less commission charged by vendor
//          7  In vendor statement, not in books          8  In your books, not in vendor statement
//   = As per your books
//
// plus, for one vendor, its balance payable as per its statement and as per your books. Each
// case is a tab listing its lines; a line is resolved — closed — there, and reopens by itself
// if either statement's figures change. All matching, every case and every figure are
// server-side (backend/app/services/vendor_internal_recon.py); this asks for one tab at a time.

import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import toast from "react-hot-toast";
import {
  AlertCircle, ArrowLeft, ArrowLeftRight, ArrowRight, Building2, CheckCircle2, ChevronDown, ChevronRight, Clock, Copy,
  Download, FileText, Hourglass, Landmark, Lightbulb, ListChecks, RefreshCw, RotateCcw, Scale, Search, X,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { errorDetail } from "@/components/payment/shared";
import { formatPeriod } from "@/lib/statementPeriod";

type Status = "matched" | "difference" | "vendor_only" | "internal_only";
type OpenStatus = Exclude<Status, "matched">;
type CaseId =
  | "extra_fare" | "less_fare" | "extra_refund" | "less_refund"
  | "extra_commission" | "less_commission" | "vendor_only" | "internal_only";
type ViewId = "summary" | "all" | CaseId | "matched" | "unmatched" | "resolved" | "already_uploaded";
type ListView = Exclude<ViewId, "summary" | "already_uploaded">;
/** All tickets, narrowed by where each line stands. */
type StatusFilter = "" | "open" | "resolved" | "matched";
type Decision = "vendor_wrong" | "internal_wrong" | "accepted";
type Kind = "sale" | "refund" | "sale+refund";

type Side = {
  id: number; ticket_prefix: string | null; pax: string | null; pnr: string | null;
  sector: string; date: string | null; booked: string | null; ref: string | null; source: string | null;
  loaded_at: string | null; vendor_key: string | null; statements: string[]; lines: number;
  fare: number; commission: number; charges: number; gst: number; tds: number; net: number;
};
type Resolution = {
  id: number; decision: Decision; note: string | null; status: Status;
  vendor_net: number | null; internal_net: number | null; difference: number | null;
  resolved_at: string | null; stale: boolean;
};
type Sibling = {
  key: string; kind: Kind; status: Status; open: boolean; cases: CaseId[];
  vendor_net: number | null; internal_net: number | null; vendor_ref: string | null; internal_ref: string | null;
};
type Row = {
  key: string; ticket_number: string | null; kind: Kind; status: Status;
  vendor: Side | null; internal: Side | null;
  diff: Record<string, number> | null; hints: string[];
  pending: "next_statement" | "in_period" | null;
  resolution: Resolution | null; open: boolean;
  vendor_id: string | null; vendor_name: string | null;
  books_vendor_id: string | null; books_vendor_name: string | null;
  booked: string | null; statements: string[];
  cases: { case: CaseId; amount: number }[]; adjustment: number;
  siblings: Sibling[];
};
type CaseAgg = {
  lines: number; tickets: number; amount: number;
  open: number; open_amount: number; resolved: number; resolved_amount: number;
};
type StatementOpt = {
  batch_id: string; vendor_id: string | null; vendor_name: string | null; file_name: string | null;
  uploaded_at: string | null; period_from: string | null; period_to: string | null;
  lines: number; billed: number; opening: number | null; closing: number | null;
  /** Lines of its file its upload left out as repeats of saved lines — not in `lines` /
   *  `billed` — and how many more were left out before those lines were kept. */
  repeats: number; repeats_net: number; repeats_unlisted: number;
};
/** A line of a statement's file its upload left out because it repeats a saved line — shown
 *  with that statement, reconciled once, as the line it repeats (`original`). */
type LeftOutKind = "exact" | "partial" | "in_file";
type LeftOutState = "matched" | "resolved" | "open" | "unsaved";
type LeftOut = {
  key: string; ticket_number: string | null; kind: Kind; left_out: LeftOutKind;
  differs: string[]; file_row: number | null;
  vendor: Side; vendor_id: string | null; vendor_name: string | null; booked: string | null;
  statement: StatementOpt | null; first_statement: StatementOpt | null;
  state: LeftOutState; original: Row | null;
};
type LeftOutAgg = Record<LeftOutState, number> & { lines: number; amount: number; unlisted: number };
/** One of a vendor's statements, with where the lines it holds stand. */
type StatementRow = StatementOpt & {
  reconciled: { matched: number; open: number; open_amount: number; resolved: number; difference: number };
};
type VendorOpt = {
  id: string; name: string; branch: string | null; channels: string[];
  statements: number; books_tickets: number;
};
type Balance = {
  available: boolean; reason?: string; statement: StatementOpt;
  as_at?: string; since?: string | null; opening?: number | null; billed?: number; payments?: number | null;
  closing?: number; vendor_upto?: number; books_upto?: number; items?: number; open_items?: number;
  books?: number; later?: number;
  /** Of `billed`, on lines its upload left out as repeats — reconciled with the line they repeat. */
  repeated?: { lines: number; amount: number };
};
type ByVendor = {
  vendor_id: string | null; vendor_name: string | null; statements: number;
  vendor_billed: number; books: number; difference: number; open: { lines: number; amount: number };
  lines: number; closing: number | null; books_balance: number | null; as_at: string | null;
};
type Summary = {
  vendor_billed: number; vendor_lines: number; books: number; books_lines: number; tickets: number;
  difference: number; cases: Record<CaseId, CaseAgg>; round_off: number;
  matched: { lines: number; amount: number }; open: { lines: number; amount: number };
  resolved: number; lines: number;
  balance: Balance | null;
  statement: (StatementOpt & { other_billed: number; other_lines: number }) | null;
  by_vendor: ByVendor[];
  coverage: { statements: string[]; internal_statements: number };
  already_uploaded: LeftOutAgg;
  /** The chosen vendor's statements (or the chosen statement's vendor's), newest first. */
  statements: StatementRow[];
};
type Result = {
  view: ViewId;
  options: { vendors: VendorOpt[]; statements: StatementOpt[]; unassigned_books: number };
  summary: Summary;
  counts: Record<string, number>;
  rows: Row[];
  /** The "already_uploaded" view's lines; empty on every other view. */
  repeats: LeftOut[];
};

// ── the eight cases ──────────────────────────────────────────────────────────
// Labels and order as the backend's CASES. An amount is books − vendor: negative is LESS (the
// vendor's figure is higher), positive is ADD.
const CASES: { id: CaseId; n: number; label: string; short: string; what: string; cls: string }[] = [
  { id: "extra_fare", n: 1, label: "Extra fare charged by vendor", short: "Extra fare",
    what: "On a sale the vendor billed more than your books — fare, taxes, service charges or GST.",
    cls: "text-red-700" },
  { id: "less_fare", n: 2, label: "Less fare charged by vendor", short: "Less fare",
    what: "On a sale the vendor billed less than your books.", cls: "text-sky-700" },
  { id: "extra_refund", n: 3, label: "Extra refund charges by vendor", short: "Extra refund charges",
    what: "On a refund the vendor credited less than your books — higher cancellation or refund charges.",
    cls: "text-red-700" },
  { id: "less_refund", n: 4, label: "Less refund charges by vendor", short: "Less refund charges",
    what: "On a refund the vendor credited more than your books.", cls: "text-sky-700" },
  { id: "extra_commission", n: 5, label: "Extra commission charged by vendor", short: "Extra commission",
    what: "The vendor passed on less commission than your books (or took more back on a refund), so it bills more.",
    cls: "text-red-700" },
  { id: "less_commission", n: 6, label: "Less commission charged by vendor", short: "Less commission",
    what: "The vendor passed on more commission than your books, so it bills less.", cls: "text-sky-700" },
  { id: "vendor_only", n: 7, label: "In vendor statement, not in your books", short: "In vendor only",
    what: "Billed by the vendor and not in Internal Statement — booked late, missed, or not yours.",
    cls: "text-red-700" },
  { id: "internal_only", n: 8, label: "In your books, not in vendor statement", short: "In books only",
    what: "In Internal Statement and not billed by the vendor — billed late, missed, or booked in error.",
    cls: "text-violet-700" },
];
const CASE_BY = Object.fromEntries(CASES.map((c) => [c.id, c])) as Record<CaseId, (typeof CASES)[number]>;

const KIND: Record<Kind, string> = { sale: "Sale", refund: "Refund", "sale+refund": "Sold & refunded" };
const KIND_CLS: Record<Kind, string> = {
  sale: "bg-emerald-50 text-emerald-700", refund: "bg-amber-100 text-amber-800", "sale+refund": "bg-sky-50 text-sky-700",
};
const STATUS_LABEL: Record<Status, string> = {
  matched: "Matched", difference: "Difference", vendor_only: "In vendor only", internal_only: "In books only",
};
// Why a line was left out at upload — the upload's own labels and colours.
const LEFT_OUT: Record<LeftOutKind, { label: string; cls: string; what: string }> = {
  exact:   { label: "Already uploaded", cls: "bg-amber-100 text-amber-800",
             what: "the same line is saved on an earlier statement" },
  partial: { label: "Partial dup.",     cls: "bg-fuchsia-100 text-fuchsia-800",
             what: "the same ticket & status is saved, with something changed" },
  in_file: { label: "Repeated in file", cls: "bg-indigo-100 text-indigo-800",
             what: "it repeats an earlier row of the same file" },
};
const FIELDS: [keyof Side & string, string][] = [
  ["fare", "Fare + taxes"], ["commission", "Commission / discount"], ["charges", "Charges"],
  ["gst", "GST"], ["tds", "TDS"], ["net", "Net"],
];

const DECISION: Record<Decision, { label: string; short: string; cls: string }> = {
  vendor_wrong:   { label: "Vendor statement is wrong",   short: "Vendor wrong",   cls: "bg-red-50 text-red-700 border-red-200" },
  internal_wrong: { label: "Internal statement is wrong", short: "Internal wrong", cls: "bg-violet-50 text-violet-700 border-violet-200" },
  accepted:       { label: "Accept as it is",             short: "Accepted",       cls: "bg-slate-100 text-slate-600 border-slate-200" },
};
// What each decision means depends on what is wrong with the line.
const DECISION_HELP: Record<OpenStatus, Record<Decision, string>> = {
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

const inr = (v: number | null | undefined) =>
  v == null ? "—" : (Object.is(v, -0) ? 0 : v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = (v: number) => `${v > 0 ? "+" : ""}${inr(v)}`;
const fmtDate = (s: string | null | undefined) => {
  if (!s) return "—";
  const d = new Date(s.length === 10 ? `${s}T00:00:00` : s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
};
/** LESS when the vendor's figure is higher (books − vendor < 0), ADD when lower. */
const lessAdd = (amount: number) => (amount < 0 ? "Less" : amount > 0 ? "Add" : "");
const stmtLabel = (s: StatementOpt) =>
  `${s.period_from && s.period_to ? formatPeriod(s.period_from, s.period_to) : "No period"} · ${s.file_name ?? "statement"}`;
const caseAmount = (r: Row, c: CaseId) => r.cases.find((x) => x.case === c)?.amount ?? 0;

export default function VendorInternalRecon() {
  // ── the filters ──────────────────────────────────────────────────────────
  const [vendor, setVendor] = useState("");
  const [statement, setStatement] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [view, setView] = useState<ViewId>("summary");

  const [data, setData] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  // ── the list on a case tab ───────────────────────────────────────────────
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<"" | Kind>("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [resolving, setResolving] = useState<Row[] | null>(null);
  const [busy, setBusy] = useState(false);

  const badPeriod = !!(from && to && from > to);
  const query = useMemo(() => ({
    vendor: vendor || undefined, statement: statement || undefined,
    date_from: from || undefined, date_to: to || undefined,
  }), [vendor, statement, from, to]);

  // Everything loaded is matched on every request — a line waiting for its partner meets it
  // whichever upload it arrives in — and the filters only narrow what comes back.
  const load = useCallback(async () => {
    if (badPeriod) return;
    const n = ++seq.current;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Result>("/reconciliation/vendor-internal", { params: { ...query, view } });
      if (n !== seq.current) return;
      setData(data);
      setOpen(new Set());
      setSelected(new Set());
    } catch (err) {
      if (n === seq.current) setError(errorDetail(err, "Reconciliation failed. Please try again."));
    } finally {
      if (n === seq.current) setLoading(false);
    }
  }, [query, view, badPeriod]);

  useEffect(() => { void load(); }, [load]);

  const options = data?.options;
  const s = data?.summary;
  const vendorOpt = options?.vendors.find((v) => v.id === vendor) ?? null;
  // A vendor's statements, or every vendor's while none is chosen.
  const statementOpts = (options?.statements ?? []).filter((x) => !vendor || x.vendor_id === vendor);
  const stmtOpt = options?.statements.find((x) => x.batch_id === statement) ?? null;

  const pickVendor = (v: string) => {
    setVendor(v);
    if (statement && options?.statements.find((x) => x.batch_id === statement)?.vendor_id !== v) setStatement("");
  };
  // Choosing a statement with every vendor showing chooses its vendor too.
  const pickStatement = (b: string) => {
    setStatement(b);
    const st = options?.statements.find((x) => x.batch_id === b);
    if (b && st?.vendor_id && !vendor) setVendor(st.vendor_id);
  };
  const clearFilters = () => { setVendor(""); setStatement(""); setFrom(""); setTo(""); };
  const pick = (v: ViewId, status: StatusFilter = "") => { setView(v); setSearch(""); setKind(""); setStatusFilter(status); };

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const standing = (r: Row) => !statusFilter || (view !== "all" && view !== "unmatched") || (
      statusFilter === "matched" ? r.status === "matched"
        : statusFilter === "open" ? r.open : r.status !== "matched" && !r.open);
    return (data?.rows ?? []).filter((r) => (!kind || r.kind === kind) && standing(r) &&
      (!q || [r.ticket_number, r.vendor?.pax, r.internal?.pax, r.vendor?.pnr, r.internal?.pnr, r.internal?.ref,
              r.vendor?.ref, r.vendor?.source, r.vendor_name, r.resolution?.note]
        .some((x) => (x ?? "").toLowerCase().includes(q))));
  }, [data, kind, search, statusFilter, view]);
  const repeats = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data?.repeats ?? []).filter((p) => (!kind || p.kind === kind) &&
      (!q || [p.ticket_number, p.vendor.pax, p.vendor.pnr, p.vendor.ref, p.statement?.file_name,
              p.first_statement?.file_name, p.original?.internal?.ref, p.original?.internal?.pax, p.vendor_name]
        .some((x) => (x ?? "").toLowerCase().includes(q))));
  }, [data, kind, search]);

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    setter(next);
  };
  const isCase = view in CASE_BY;
  const selectable = isCase || view === "resolved";
  const picked = rows.filter((r) => selected.has(r.key));
  const allPicked = rows.length > 0 && picked.length === rows.length;

  const submitResolve = async (lines: Row[], decision: Decision, note: string) => {
    setBusy(true);
    try {
      const { data } = await api.post<Result>("/reconciliation/vendor-internal/resolutions", {
        keys: lines.map((r) => r.key), decision, note: note.trim() || null, ...query, view,
      });
      setData(data);
      setSelected(new Set());
      setResolving(null);
      toast.success(`${lines.length} line${lines.length !== 1 ? "s" : ""} resolved — ${DECISION[decision].short}`);
    } catch (err) {
      toast.error(errorDetail(err, "Could not save the decision. Please try again."));
      setResolving(null);
      void load();
    } finally {
      setBusy(false);
    }
  };

  const reopen = async (lines: Row[]) => {
    setBusy(true);
    try {
      const { data } = await api.post<Result>("/reconciliation/vendor-internal/resolutions/reopen", {
        keys: lines.map((r) => r.key), ...query, view,
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

  // The whole reconciliation as a workpaper — every line in the filters, with its cases.
  const exportCsv = async (which: ViewId) => {
    let list = rows;
    if (which === "summary") {
      try {
        list = (await api.get<Result>("/reconciliation/vendor-internal", { params: { ...query, view: "all" } })).data.rows;
      } catch (err) {
        toast.error(errorDetail(err, "Could not download. Please try again."));
        return;
      }
    }
    const head = ["Vendor", "Ticket", "Type", "Status", "Passenger", "Booked", "Vendor statement", "Vendor net",
      "Doc No", "Books net", "Books − vendor", "Cases", "Open", "Decision", "Note", "Hints"];
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = list.map((r) => [
      r.vendor_name ?? "", `${r.vendor?.ticket_prefix ?? r.internal?.ticket_prefix ?? ""} ${r.ticket_number ?? ""}`.trim(),
      KIND[r.kind], STATUS_LABEL[r.status], r.internal?.pax ?? r.vendor?.pax, r.booked,
      r.vendor?.source ?? r.vendor?.ref, r.vendor?.net, r.internal?.ref, r.internal?.net, r.adjustment,
      r.cases.map((c) => `${CASE_BY[c.case].n} ${CASE_BY[c.case].short} ${c.amount}`).join("; "),
      r.status === "matched" ? "" : r.open ? "Open" : "Resolved",
      r.resolution ? DECISION[r.resolution.decision].label : "", r.resolution?.note, r.hints.join(" | "),
    ].map(esc).join(","));
    const blob = new Blob([[head.join(","), ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `vendor_reconciliation_${vendorOpt?.name.replace(/\W+/g, "_") ?? "all_vendors"}_${which}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  // Read left to right: the overview — every line, then the matched and the unmatched ones —
  // the eight reconciling items, and what is closed or set aside. The figures are on the
  // Summary and in the header, not on the tabs.
  const tabGroups: { id: ViewId; label: string; title?: string }[][] = [
    [{ id: "summary", label: "Summary" }, { id: "all", label: "All tickets" },
     { id: "matched", label: "Matched", title: "Lines both statements agree on, within ₹1" },
     { id: "unmatched", label: "Unmatched", title: "Lines the vendor statement and your books disagree on — open or resolved" }],
    CASES.map((c) => ({ id: c.id, label: c.short, title: `${c.label} — ${c.what}` })),
    [{ id: "resolved", label: "Resolved" }, { id: "already_uploaded", label: "Already uploaded" }],
  ];
  const cols = columns(view, !vendor);
  // The chosen statement's own row of its vendor's statements.
  const stmtRow = s?.statements.find((x) => x.batch_id === statement) ?? null;

  return (
    <div className="space-y-4">
      {/* ── the filters ─────────────────────────────────────────────────── */}
      <div className="bg-white border border-slate-200 rounded-xl px-4 py-3 flex flex-wrap items-end gap-3">
        <Field label="Vendor">
          <select value={vendor} onChange={(e) => pickVendor(e.target.value)}
            className="py-2 px-2.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 w-64">
            <option value="">All vendors</option>
            {(options?.vendors ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}{v.branch ? ` — ${v.branch}` : ""} ({v.statements} statement{v.statements !== 1 ? "s" : ""})
              </option>
            ))}
          </select>
        </Field>
        <Field label="Statement">
          <select value={statement} onChange={(e) => pickStatement(e.target.value)}
            className="py-2 px-2.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 w-80">
            <option value="">{vendor ? "All statements of this vendor" : "All statements"}</option>
            {statementOpts.map((x) => (
              <option key={x.batch_id} value={x.batch_id}>
                {vendor ? "" : `${x.vendor_name ?? "No vendor"} · `}{stmtLabel(x)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Booking period">
          <div className="flex items-center gap-1.5">
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
              onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch { /* not supported */ } }}
              className={cn("py-1.5 px-2 text-xs border rounded-lg", badPeriod ? "border-red-300 bg-red-50" : "border-slate-200")} />
            <span className="text-slate-300 text-xs">–</span>
            <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)}
              onClick={(e) => { try { (e.target as HTMLInputElement).showPicker(); } catch { /* not supported */ } }}
              className={cn("py-1.5 px-2 text-xs border rounded-lg", badPeriod ? "border-red-300 bg-red-50" : "border-slate-200")} />
          </div>
        </Field>
        {(vendor || statement || from || to) && (
          <button onClick={clearFilters} className="pb-2 text-[11px] font-semibold text-blue-600 hover:underline">
            Clear filters
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => void exportCsv(view)} disabled={!data || (view !== "summary" && !rows.length)}
            className="flex items-center gap-1.5 px-3 py-2 border border-slate-200 rounded-lg text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            title={view === "summary" ? "Every line in these filters, with its cases" : "The lines on this tab"}>
            <Download className="w-3.5 h-3.5" /> CSV
          </button>
          <button onClick={() => void load()} disabled={loading || badPeriod}
            className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 text-white rounded-lg text-xs font-semibold hover:bg-blue-700 disabled:opacity-50">
            <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} /> Reconcile
          </button>
        </div>
        {badPeriod && <p className="basis-full text-[11px] text-red-600">The booking period ends before it starts.</p>}
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* ── what is being reconciled, and where it stands ───────────────── */}
      {s && (
        <ScopeHeader s={s} vendor={vendorOpt} stmt={stmtOpt} from={from} to={to}
          unassigned={vendor ? 0 : options?.unassigned_books ?? 0}
          onAllVendors={() => { setVendor(""); setStatement(""); }} onVendor={() => setStatement("")} onView={pick} />
      )}

      {/* ── the tabs ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-slate-200 overflow-x-auto">
        {tabGroups.map((group, g) => (
          <Fragment key={g}>
            {g > 0 && <span aria-hidden className="mx-1.5 h-4 w-px shrink-0 bg-slate-200" />}
            {group.map((t) => {
              const active = t.id === view;
              return (
                <button key={t.id} type="button" onClick={() => pick(t.id)} title={t.title}
                  className={cn("px-3 py-2 text-xs font-semibold border-b-2 -mb-px whitespace-nowrap transition-colors",
                    active ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
                  {t.label}
                </button>
              );
            })}
          </Fragment>
        ))}
      </div>

      {!s ? (
        <div className="bg-white border border-slate-200 rounded-xl px-4 py-10 text-center text-xs text-slate-400">
          {loading ? "Reconciling…" : "Nothing to show yet."}
        </div>
      ) : view === "summary" ? (
        <SummaryTab s={s} vendor={vendorOpt} stmtOpt={stmtOpt} stmtRow={stmtRow} allVendors={!vendor}
          onCase={pick} onVendor={pickVendor} onStatement={pickStatement} onAllStatements={() => setStatement("")}
          loading={loading} />
      ) : view === "already_uploaded" ? (
        <>
          <LeftOutBanner a={s.already_uploaded} oneStatement={!!stmtOpt} />
          <ListFilters search={search} onSearch={setSearch} kind={kind} onKind={setKind} count={repeats.length} />
          <LeftOutTable list={repeats} withVendor={!vendor} withStatement={!statement} loading={loading}
            empty={data?.repeats.length ? "Nothing to show for these filters." : "No line of these statements was left out at upload."}
            open={open} onToggle={(k) => toggle(open, setOpen, k)} />
        </>
      ) : (
        <>
          <ViewBanner view={view} s={s} />

          <ListFilters search={search} onSearch={setSearch} kind={kind} onKind={setKind} count={rows.length}
            status={view === "all" || view === "unmatched" ? statusFilter : undefined} onStatus={setStatusFilter}
            withMatched={view === "all"}>
            <div className="ml-auto flex items-center gap-2">
              {picked.length > 0 && isCase && (
                <button onClick={() => setResolving(picked)} disabled={busy}
                  className="flex items-center gap-1.5 px-3 py-2 bg-amber-500 text-white rounded-lg text-xs font-semibold hover:bg-amber-600 disabled:opacity-50">
                  <Scale className="w-3.5 h-3.5" /> Resolve {picked.length} selected
                </button>
              )}
              {picked.length > 0 && view === "resolved" && (
                <button onClick={() => void reopen(picked)} disabled={busy}
                  className="flex items-center gap-1.5 px-3 py-2 border border-slate-300 rounded-lg text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                  <RotateCcw className="w-3.5 h-3.5" /> Reopen {picked.length} selected
                </button>
              )}
            </div>
          </ListFilters>

          <div className={cn("bg-white border border-slate-200 rounded-xl overflow-hidden", loading && "opacity-60")}>
            <div key={view} className="overflow-x-auto">
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
                      {loading ? "Loading…" : data?.rows.length ? "Nothing to show for these filters." : EMPTY[view]}
                    </td></tr>
                  )}
                  {rows.map((r) => {
                    const isOpen = open.has(r.key);
                    return (
                      <Fragment key={r.key}>
                        <tr onClick={() => toggle(open, setOpen, r.key)}
                          className={cn("cursor-pointer bg-white hover:bg-slate-50", (isOpen || selected.has(r.key)) && "bg-blue-50")}>
                          {selectable && (
                            <td className="pl-3" onClick={(e) => e.stopPropagation()}>
                              <input type="checkbox" checked={selected.has(r.key)} onChange={() => toggle(selected, setSelected, r.key)}
                                className="accent-blue-500" aria-label={`Select ${r.ticket_number ?? "line"}`} />
                            </td>
                          )}
                          <td className="pl-2">
                            {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-300" />}
                          </td>
                          <Cells row={r} view={view} cols={cols} busy={busy}
                            onResolve={() => setResolving([r])} onReopen={() => void reopen([r])} />
                        </tr>
                        {isOpen && (
                          <tr className="bg-slate-50/60">
                            <td colSpan={selectable ? 2 : 1} />
                            <td colSpan={cols.length} className="py-3 pr-3 pl-3"><Detail row={r} /></td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {resolving && resolving.length > 0 && (
        <ResolveDialog rows={resolving} busy={busy} onClose={() => setResolving(null)}
          onSubmit={(d, note) => void submitResolve(resolving, d, note)} />
      )}
    </div>
  );
}

/** A list tab's search, sale / refund filter, status filter (All tickets and Unmatched:
 *  `status` given; Matched among its choices on All tickets only) and line count —
 *  `children` on the right. */
function ListFilters({ search, onSearch, kind, onKind, status, onStatus, withMatched = true, count, children }: {
  search: string; onSearch: (v: string) => void; kind: "" | Kind; onKind: (k: "" | Kind) => void;
  status?: StatusFilter; onStatus?: (s: StatusFilter) => void; withMatched?: boolean;
  count: number; children?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
        <input value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Ticket, pax, PNR, Doc No…"
          className="pl-8 pr-3 py-2 text-xs border border-slate-200 rounded-lg w-56 focus:outline-none focus:ring-1 focus:ring-blue-400" />
      </div>
      <select value={kind} onChange={(e) => onKind(e.target.value as "" | Kind)}
        className="py-2 px-2.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-600">
        <option value="">Sales &amp; refunds</option>
        <option value="sale">Sales</option>
        <option value="refund">Refunds</option>
        <option value="sale+refund">Sold &amp; refunded</option>
      </select>
      {status !== undefined && onStatus && (
        <select value={status} onChange={(e) => onStatus(e.target.value as StatusFilter)}
          className="py-2 px-2.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-600">
          <option value="">Every status</option>
          <option value="open">Open — to resolve</option>
          <option value="resolved">Resolved</option>
          {withMatched && <option value="matched">Matched</option>}
        </select>
      )}
      <span className="text-xs text-slate-400">{count} line{count !== 1 ? "s" : ""}</span>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[10px] font-bold uppercase tracking-wide text-slate-400 mb-1">{label}</span>
      {children}
    </label>
  );
}

// ── the Summary tab ──────────────────────────────────────────────────────────
// ── above the tabs: what is being reconciled, and where it stands ─────────────
function ScopeHeader({ s, vendor, stmt, from, to, unassigned, onAllVendors, onVendor, onView }: {
  s: Summary; vendor: VendorOpt | null; stmt: StatementOpt | null; from: string; to: string; unassigned: number;
  onAllVendors: () => void; onVendor: () => void; onView: (v: ViewId, status?: StatusFilter) => void;
}) {
  const crumb = "text-blue-600 hover:underline";
  const here = "font-semibold text-slate-800";
  const diff = s.difference;
  return (
    <div className="space-y-2">
      <nav className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-slate-500" aria-label="Reconciling">
        {vendor ? <button type="button" onClick={onAllVendors} className={crumb}>All vendors</button>
          : <span className={here}>All vendors</span>}
        {vendor && (
          <>
            <ChevronRight className="w-3 h-3 text-slate-300" />
            {stmt ? <button type="button" onClick={onVendor} className={crumb}>{vendor.name}</button>
              : <span className={here}>{vendor.name}{vendor.branch ? ` — ${vendor.branch}` : ""}</span>}
          </>
        )}
        {stmt && (
          <>
            <ChevronRight className="w-3 h-3 text-slate-300" />
            <span className={here}>{stmtLabel(stmt)}</span>
          </>
        )}
        <span className="text-slate-400">
          · {s.tickets.toLocaleString("en-IN")} ticket{s.tickets !== 1 ? "s" : ""}
          {!stmt && <> on {s.coverage.statements.length} vendor statement{s.coverage.statements.length !== 1 ? "s" : ""}</>}
          {(from || to) && <> · booked {from ? fmtDate(from) : "…"} – {to ? fmtDate(to) : "…"}</>}
        </span>
        {unassigned > 0 && (
          <span className="text-amber-700">
            · {unassigned} ticket{unassigned !== 1 ? "s" : ""} in your books {unassigned !== 1 ? "have" : "has"} no vendor — shown under All vendors only
          </span>
        )}
      </nav>
      <div className="grid gap-2 grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Billed as per vendor" value={inr(s.vendor_billed)} sub={`${s.vendor_lines} line${s.vendor_lines !== 1 ? "s" : ""}`}
          onClick={() => onView("all")} />
        <Kpi label="As per your books" value={inr(s.books)} sub={`${s.books_lines} line${s.books_lines !== 1 ? "s" : ""}`}
          onClick={() => onView("all")} />
        <Kpi label="Books − vendor" value={signed(diff)} tone={Math.abs(diff) >= 1 ? "amber" : "emerald"}
          sub={diff <= -1 ? "the vendor billed more" : diff >= 1 ? "the vendor billed less" : "both agree"} />
        <Kpi label="Open items" value={s.open.lines.toLocaleString("en-IN")} tone={s.open.lines ? "amber" : "emerald"}
          sub={s.open.lines ? `${lessAdd(s.open.amount)} ${inr(Math.abs(s.open.amount))} · ${s.resolved} resolved` : `${s.resolved} resolved`}
          onClick={s.open.lines ? () => onView("unmatched", "open") : undefined} />
        <Kpi label="Matched" value={s.matched.lines.toLocaleString("en-IN")} tone="emerald" sub="agree within ₹1"
          onClick={s.matched.lines ? () => onView("matched") : undefined} />
        <Kpi label="Already uploaded" value={s.already_uploaded.lines.toLocaleString("en-IN")} sub="reconciled once, not counted again"
          onClick={s.already_uploaded.lines ? () => onView("already_uploaded") : undefined} />
      </div>
    </div>
  );
}

function Kpi({ label, value, sub, tone = "slate", onClick }: {
  label: string; value: string; sub: string; tone?: "slate" | "amber" | "emerald"; onClick?: () => void;
}) {
  const body = (
    <>
      <span className="block text-[10px] font-semibold uppercase tracking-wide text-slate-400 truncate">{label}</span>
      <span className={cn("block text-base font-bold tabular-nums leading-snug truncate",
        tone === "amber" ? "text-amber-700" : tone === "emerald" ? "text-emerald-700" : "text-slate-900")}>{value}</span>
      <span className="block text-[11px] text-slate-500 truncate">{sub}</span>
    </>
  );
  const cls = "min-w-0 text-left bg-white border border-slate-200 rounded-xl px-3 py-2";
  return onClick
    ? <button type="button" onClick={onClick} className={cn(cls, "hover:border-blue-300 hover:bg-blue-50/40 transition-colors")}>{body}</button>
    : <div className={cls}>{body}</div>;
}

// ── the Summary tab ──────────────────────────────────────────────────────────
function SummaryTab({ s, vendor, stmtOpt, stmtRow, allVendors, onCase, onVendor, onStatement, onAllStatements, loading }: {
  s: Summary; vendor: VendorOpt | null; stmtOpt: StatementOpt | null; stmtRow: StatementRow | null;
  allVendors: boolean; onCase: (v: ViewId) => void; onVendor: (id: string) => void;
  onStatement: (batch: string) => void; onAllStatements: () => void; loading: boolean;
}) {
  return (
    <div className={cn("space-y-4", loading && "opacity-60")}>
      {stmtRow ? (
        <StatementCard st={stmtRow} vendorName={vendor?.name ?? stmtRow.vendor_name} statements={s.statements.length}
          onAllStatements={onAllStatements} />
      ) : vendor && (
        <VendorStatements vendor={vendor} rows={s.statements} onPick={onStatement} />
      )}
      {s.balance && <BalanceCard b={s.balance} vendorName={vendor?.name ?? null} />}
      <ReconStatement s={s} stmtOpt={stmtOpt} onCase={onCase} />
      {allVendors && s.by_vendor.length > 0 && <VendorTable rows={s.by_vendor} onVendor={onVendor} />}
    </div>
  );
}

const fileLines = (x: StatementOpt) => x.lines + x.repeats + x.repeats_unlisted;

/** One vendor: who it is, what it has sent, and each of its statements — click one to open it. */
function VendorStatements({ vendor, rows, onPick }: {
  vendor: VendorOpt; rows: StatementRow[]; onPick: (batch: string) => void;
}) {
  const [all, setAll] = useState(false);
  const SHOWN = 6;
  const shown = all ? rows : rows.slice(0, SHOWN);
  const starts = rows.map((x) => x.period_from).filter(Boolean).sort() as string[];
  const ends = rows.map((x) => x.period_to).filter(Boolean).sort() as string[];
  const total = (f: (x: StatementRow) => number) => rows.reduce((t, x) => t + f(x), 0);
  const num = "px-3 py-2 text-right tabular-nums whitespace-nowrap";
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-100 flex flex-wrap items-start gap-x-6 gap-y-2">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Building2 className="w-4 h-4 text-slate-400" /> {vendor.name}
            {vendor.channels.map((c) => (
              <span key={c} className="px-1.5 py-px rounded bg-slate-100 text-[10px] font-semibold text-slate-500">{c}</span>
            ))}
          </p>
          {vendor.branch && <p className="text-[11px] text-slate-500 pl-6">{vendor.branch}</p>}
        </div>
        <Fact label="Statements loaded" value={rows.length.toLocaleString("en-IN")}
          sub={starts.length ? `${fmtDate(starts[0])} – ${fmtDate(ends[ends.length - 1])}` : "none yet"} />
        <Fact label="Lines on their files" value={total(fileLines).toLocaleString("en-IN")}
          sub={`${total((x) => x.repeats + x.repeats_unlisted)} already uploaded`} />
        <Fact label="Billed" value={inr(total((x) => x.billed))} sub="on the lines saved" />
        <Fact label="In your books" value={vendor.books_tickets.toLocaleString("en-IN")} sub="tickets of this vendor" />
        <Fact label="Open items" value={total((x) => x.reconciled.open).toLocaleString("en-IN")}
          sub={`${total((x) => x.reconciled.matched)} matched`} tone={total((x) => x.reconciled.open) ? "amber" : "emerald"} />
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-center text-xs text-slate-400">
          No Third Party GDS statement of this vendor is loaded yet.{" "}
          <Link href="/vendors/statements/third-party/gds" className="text-blue-600 hover:underline">Load one</Link>
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-max text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-slate-400 bg-slate-50">
                <th className="px-4 py-1.5 text-left font-semibold">Statement</th>
                <th className="px-3 py-1.5 text-left font-semibold">Uploaded</th>
                <th className="px-3 py-1.5 text-right font-semibold">Lines in file</th>
                <th className="px-3 py-1.5 text-right font-semibold">Already uploaded</th>
                <th className="px-3 py-1.5 text-right font-semibold">Billed</th>
                <th className="px-3 py-1.5 text-right font-semibold">Closing</th>
                <th className="px-3 py-1.5 text-right font-semibold">Matched</th>
                <th className="px-3 py-1.5 text-right font-semibold">Open</th>
                <th className="px-3 py-1.5 text-right font-semibold">Books − vendor</th>
                <th className="w-6" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shown.map((x) => (
                <tr key={x.batch_id} onClick={() => onPick(x.batch_id)} className="cursor-pointer hover:bg-blue-50/50">
                  <td className="px-4 py-2">
                    <span className="block font-semibold text-slate-800">
                      {x.period_from && x.period_to ? formatPeriod(x.period_from, x.period_to) : "No period"}
                    </span>
                    <span className="block text-[11px] text-slate-400 truncate max-w-[260px]" title={x.file_name ?? undefined}>{x.file_name}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-500 whitespace-nowrap">{fmtDate(x.uploaded_at)}</td>
                  <td className={num}>{fileLines(x)}</td>
                  <td className={cn(num, x.repeats + x.repeats_unlisted ? "text-amber-700" : "text-slate-300")}>
                    {x.repeats + x.repeats_unlisted}
                  </td>
                  <td className={num}>{inr(x.billed)}</td>
                  <td className={num}>{x.closing != null ? inr(x.closing) : <span className="text-slate-300">—</span>}</td>
                  <td className={cn(num, "text-emerald-700")}>{x.reconciled.matched}</td>
                  <td className={cn(num, x.reconciled.open ? "font-semibold text-amber-700" : "text-slate-300")}>{x.reconciled.open}</td>
                  <td className={cn(num, Math.abs(x.reconciled.difference) >= 1 ? "font-semibold text-amber-700" : "text-emerald-700")}>
                    {signed(x.reconciled.difference)}
                  </td>
                  <td className="pr-3"><ChevronRight className="w-3.5 h-3.5 text-slate-300" /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > SHOWN && (
            <button type="button" onClick={() => setAll(!all)}
              className="w-full px-4 py-2 border-t border-slate-100 text-[11px] font-semibold text-blue-600 hover:bg-slate-50">
              {all ? "Show the latest only" : `Show all ${rows.length} statements`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** One statement: what its file held and where its lines stand. */
function StatementCard({ st, vendorName, statements, onAllStatements }: {
  st: StatementRow; vendorName: string | null; statements: number; onAllStatements: () => void;
}) {
  const r = st.reconciled;
  const leftOut = st.repeats + st.repeats_unlisted;
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-100 flex flex-wrap items-center gap-x-3 gap-y-1">
        <FileText className="w-4 h-4 text-slate-400" />
        <span className="text-sm font-semibold text-slate-800">
          {st.period_from && st.period_to ? formatPeriod(st.period_from, st.period_to) : "No period"}
        </span>
        <span className="text-xs text-slate-500 truncate max-w-[360px]" title={st.file_name ?? undefined}>{st.file_name}</span>
        <span className="text-xs text-slate-400">· uploaded {fmtDate(st.uploaded_at)}</span>
        {statements > 1 && (
          <button type="button" onClick={onAllStatements}
            className="ml-auto inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:underline">
            <ArrowLeft className="w-3 h-3" /> All {statements} statements of {vendorName ?? "this vendor"}
          </button>
        )}
      </div>
      <div className="px-4 py-3 flex flex-wrap gap-x-8 gap-y-3">
        <Fact label="Lines in its file" value={fileLines(st).toLocaleString("en-IN")}
          sub={leftOut ? `${st.lines} billed here · ${leftOut} already uploaded` : "every one billed here"} />
        <Fact label="Billed on it" value={inr(st.billed)}
          sub={st.repeats ? `+ ${inr(st.repeats_net)} already uploaded` : "on the lines saved"} />
        <Fact label="Opening · closing" value={`${inr(st.opening)} · ${inr(st.closing)}`}
          sub={st.closing == null ? "no BALANCE line printed" : "as printed on the file"} />
        <Fact label="Matched" value={r.matched.toLocaleString("en-IN")} sub="agree within ₹1" tone="emerald" />
        <Fact label="Open" value={r.open.toLocaleString("en-IN")} tone={r.open ? "amber" : "emerald"}
          sub={r.open ? `${lessAdd(r.open_amount)} ${inr(Math.abs(r.open_amount))} · ${r.resolved} resolved` : `${r.resolved} resolved`} />
        <Fact label="Books − vendor" value={signed(r.difference)} tone={Math.abs(r.difference) >= 1 ? "amber" : "emerald"}
          sub="this statement's tickets" />
      </div>
      {st.repeats_unlisted > 0 && (
        <p className="px-4 py-2 border-t border-slate-100 text-[11px] text-slate-500">
          {st.repeats_unlisted} of its lines were left out before such lines were kept — delete it and upload it again to list them.
        </p>
      )}
    </div>
  );
}

function Fact({ label, value, sub, tone = "slate" }: {
  label: string; value: string; sub?: string; tone?: "slate" | "amber" | "emerald";
}) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className={cn("text-sm font-bold tabular-nums",
        tone === "amber" ? "text-amber-700" : tone === "emerald" ? "text-emerald-700" : "text-slate-800")}>{value}</p>
      {sub && <p className="text-[11px] text-slate-500">{sub}</p>}
    </div>
  );
}

function BalanceCard({ b, vendorName }: { b: Balance; vendorName: string | null }) {
  if (!b.available) {
    return (
      <div className="flex items-start gap-2.5 px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-600">
        <Landmark className="w-4 h-4 shrink-0 text-slate-400 mt-px" />
        <span><b className="text-slate-700">Balance payable</b> — {b.reason} ({stmtLabel(b.statement)}). Load a statement that
          prints its BALANCE line to see the balance as per the vendor and as per your books.</span>
      </div>
    );
  }
  const diff = b.items ?? 0;
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-100 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Landmark className="w-4 h-4 text-slate-400 self-center" />
        <span className="text-xs font-bold uppercase tracking-wide text-slate-600">Balance payable</span>
        <span className="text-xs text-slate-500">
          {vendorName ?? b.statement.vendor_name} · as at <b className="text-slate-700">{fmtDate(b.as_at)}</b>, the end of {b.statement.file_name}
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr_auto_1fr] items-stretch">
        <div className="px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">As per vendor statement</p>
          <p className="text-xl font-bold tabular-nums text-slate-900">{inr(b.closing)}</p>
          {b.opening != null ? (
            <p className="text-[11px] text-slate-500 tabular-nums mt-0.5">
              Opening {inr(b.opening)} + billed {inr(b.billed)} − payments &amp; other {inr(b.payments)}
            </p>
          ) : <p className="text-[11px] text-slate-400 mt-0.5">Billed on it {inr(b.billed)} · no opening balance printed</p>}
          {!!b.repeated?.lines && (
            <p className="text-[11px] text-slate-400 tabular-nums mt-0.5">
              Billed includes {inr(b.repeated.amount)} on {b.repeated.lines} line{b.repeated.lines !== 1 ? "s" : ""} already uploaded
            </p>
          )}
        </div>
        <Op>{diff < 0 ? "−" : "+"}</Op>
        <div className="px-4 py-3 bg-amber-50/40">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            Your books − vendor, tickets {b.since ? fmtDate(b.since) : ""} – {fmtDate(b.as_at)}
          </p>
          <p className={cn("text-xl font-bold tabular-nums", Math.abs(diff) >= 1 ? "text-amber-700" : "text-emerald-700")}>{signed(diff)}</p>
          <p className="text-[11px] text-slate-500 tabular-nums mt-0.5">
            In your books {inr(b.books_upto)} · billed by vendor {inr(b.vendor_upto)}
          </p>
        </div>
        <Op>=</Op>
        <div className="px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">As per your books</p>
          <p className="text-xl font-bold tabular-nums text-slate-900">{inr(b.books)}</p>
          <p className="text-[11px] text-slate-500 mt-0.5">
            {b.open_items ? <><b className="text-amber-700">{b.open_items}</b> open item{b.open_items !== 1 ? "s" : ""} to resolve up to then</> : "No open items up to then"}
          </p>
        </div>
      </div>
      <p className="px-4 py-2 border-t border-slate-100 text-[11px] text-slate-400">
        The opening balance and the payments are taken as agreed.
        {!!b.later && <> {b.later} line{b.later !== 1 ? "s" : ""} dated after {fmtDate(b.as_at)} {b.later !== 1 ? "are" : "is"} not in this balance.</>}
        {!!b.repeated?.lines && (
          <> Its closing counts {inr(b.repeated.amount)} on {b.repeated.lines} line{b.repeated.lines !== 1 ? "s" : ""} that
            repeat{b.repeated.lines === 1 ? "s" : ""} a line already saved; each is reconciled once, with the line it repeats, and
            is not an item here — if the vendor&apos;s balance carries {b.repeated.lines === 1 ? "it" : "them"} twice, raise it with the vendor.</>
        )}
      </p>
    </div>
  );
}

function Op({ children }: { children: ReactNode }) {
  return <div className="hidden md:flex items-center justify-center px-1 text-lg font-bold text-slate-300">{children}</div>;
}

function ReconStatement({ s, stmtOpt, onCase }: { s: Summary; stmtOpt: StatementOpt | null; onCase: (v: ViewId) => void }) {
  const num = "px-4 py-2 text-right tabular-nums whitespace-nowrap";
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2">
        <Scale className="w-4 h-4 text-slate-400" />
        <span className="text-xs font-bold uppercase tracking-wide text-slate-600">Reconciliation statement</span>
        <span className="text-xs text-slate-400">— vendor statement to your books, for the tickets in these filters</span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-slate-400 bg-slate-50">
            <th className="px-4 py-1.5 text-left font-semibold w-14" />
            <th className="px-2 py-1.5 text-left font-semibold">Item</th>
            <th className="px-4 py-1.5 text-right font-semibold">Lines</th>
            <th className="px-4 py-1.5 text-right font-semibold">Open</th>
            <th className="px-4 py-1.5 text-right font-semibold">Resolved</th>
            <th className="px-4 py-1.5 text-right font-semibold">Amount</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          <tr className="bg-slate-50/60 font-semibold text-slate-800">
            <td className="px-4 py-2" />
            <td className="px-2 py-2">Billed as per vendor statement</td>
            <td className={num}>{s.vendor_lines}</td>
            <td className={num} /><td className={num} />
            <td className={num}>{inr(s.vendor_billed)}</td>
          </tr>
          {s.statement && Math.abs(s.statement.other_billed) >= 0.01 && (
            <tr className="text-[11px] text-slate-500">
              <td />
              <td className="px-2 py-1.5" colSpan={5}>
                Billed on {stmtOpt?.file_name ?? "this statement"} {inr(s.statement.billed)} ({s.statement.lines} lines), and{" "}
                {inr(s.statement.other_billed)} on {s.statement.other_lines} line{s.statement.other_lines !== 1 ? "s" : ""} of its
                tickets on other statements — sold here and refunded later (or the other way round), compared whole.
              </td>
            </tr>
          )}
          {(s.already_uploaded.lines > 0 || s.already_uploaded.unlisted > 0) && (
            <tr className="text-[11px] text-slate-500">
              <td />
              <td className="px-2 py-1.5" colSpan={5}>
                <LeftOutNote a={s.already_uploaded} stmt={s.statement} onOpen={() => onCase("already_uploaded")} />
              </td>
            </tr>
          )}
          {CASES.map((c) => {
            const a = s.cases[c.id];
            const empty = !a.lines;
            return (
              <tr key={c.id} onClick={() => !empty && onCase(c.id)}
                className={cn(empty ? "text-slate-300" : "cursor-pointer hover:bg-blue-50/50 text-slate-700")}>
                <td className="px-4 py-2 font-semibold">
                  {!empty && <span className={a.amount < 0 ? "text-red-600" : "text-sky-700"}>{lessAdd(a.amount)}</span>}
                </td>
                <td className="px-2 py-2">
                  <span className="inline-flex items-center gap-2">
                    <span className={cn("w-4 h-4 rounded-full text-[10px] font-bold flex items-center justify-center",
                      empty ? "bg-slate-50 text-slate-300" : "bg-slate-100 text-slate-500")}>{c.n}</span>
                    <span className={empty ? "" : "font-medium"}>{c.label}</span>
                    {!empty && <ArrowRight className="w-3 h-3 text-slate-300" />}
                  </span>
                  {!empty && <span className="block pl-6 text-[11px] text-slate-400">{c.what}</span>}
                </td>
                <td className={num}>{a.lines || "—"}</td>
                <td className={cn(num, a.open ? "text-amber-700 font-semibold" : "")}>{empty ? "" : a.open}</td>
                <td className={num}>{empty ? "" : a.resolved}</td>
                <td className={cn(num, !empty && "font-semibold", !empty && (a.amount < 0 ? "text-red-700" : "text-sky-700"))}>
                  {empty ? "—" : signed(a.amount)}
                </td>
              </tr>
            );
          })}
          <tr className="text-slate-500">
            <td className="px-4 py-2" />
            <td className="px-2 py-2">
              Round-off{" "}
              <span className="text-[11px] text-slate-400">
                — {s.matched.lines} line{s.matched.lines !== 1 ? "s" : ""} agree within ₹1 (your books round to the rupee)
              </span>
            </td>
            <td className={num}>{s.matched.lines}</td>
            <td className={num} /><td className={num} />
            <td className={num}>{signed(s.round_off)}</td>
          </tr>
          <tr className="bg-slate-50/60 font-semibold text-slate-800 border-t-2 border-slate-200">
            <td className="px-4 py-2" />
            <td className="px-2 py-2">As per your books</td>
            <td className={num}>{s.books_lines}</td>
            <td className={cn(num, "text-amber-700")}>{s.open.lines || ""}</td>
            <td className={num}>{s.resolved || ""}</td>
            <td className={num}>{inr(s.books)}</td>
          </tr>
        </tbody>
      </table>
      <p className="px-4 py-2 border-t border-slate-100 text-[11px] text-slate-400">
        Less: the vendor&apos;s figure is higher than your books. Add: it is lower. A line can be in two items — its
        commission and the rest of its difference — and they add up to its net difference. Click an item to see its lines.
      </p>
    </div>
  );
}

/** Under "Billed as per vendor statement": the lines of the file(s) not saved as repeats. */
function LeftOutNote({ a, stmt, onOpen }: {
  a: LeftOutAgg; stmt: Summary["statement"]; onOpen: () => void;
}) {
  return (
    <span>
      {a.lines > 0 && (
        <>
          {stmt
            ? <>Its file has {stmt.lines + a.lines} lines: {stmt.lines} billed here and {a.lines} not saved</>
            : <>{a.lines} more line{a.lines !== 1 ? "s" : ""} of these statements&apos; files {a.lines !== 1 ? "were" : "was"} not saved</>}
          {" "}— already uploaded or repeated ({inr(a.amount)}), each reconciled once with the line it repeats:
          {" "}{a.matched} matched, {a.resolved} resolved, {a.open} open{a.unsaved ? `, ${a.unsaved} whose saved line was deleted` : ""}.
          Not counted again.{" "}
          <button type="button" onClick={onOpen} className="inline-flex items-center gap-0.5 font-semibold text-blue-600 hover:underline">
            See them <ArrowRight className="w-3 h-3" />
          </button>
        </>
      )}
      {a.unlisted > 0 && (
        <> {a.unlisted} more {a.unlisted !== 1 ? "were" : "was"} left out by uploads made before those lines were kept —
          delete the statement and upload it again to list them.</>
      )}
    </span>
  );
}

function VendorTable({ rows, onVendor }: { rows: ByVendor[]; onVendor: (id: string) => void }) {
  const num = "px-3 py-2 text-right tabular-nums whitespace-nowrap";
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-100 text-xs font-bold uppercase tracking-wide text-slate-600">By vendor</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-max text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-slate-400 bg-slate-50">
              <th className="px-3 py-1.5 text-left font-semibold">Vendor</th>
              <th className="px-3 py-1.5 text-right font-semibold">Statements</th>
              <th className="px-3 py-1.5 text-right font-semibold">Billed as per vendor</th>
              <th className="px-3 py-1.5 text-right font-semibold">As per your books</th>
              <th className="px-3 py-1.5 text-right font-semibold">Books − vendor</th>
              <th className="px-3 py-1.5 text-right font-semibold">Open items</th>
              <th className="px-3 py-1.5 text-right font-semibold">Balance as per vendor</th>
              <th className="px-3 py-1.5 text-right font-semibold">Balance as per books</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((v) => (
              <tr key={v.vendor_id ?? "none"} onClick={() => v.vendor_id && onVendor(v.vendor_id)}
                className={cn(v.vendor_id ? "cursor-pointer hover:bg-blue-50/50" : "text-slate-500")}>
                <td className="px-3 py-2 font-medium text-slate-800">
                  {v.vendor_name ?? <span className="italic text-slate-500">No vendor in your books</span>}
                </td>
                <td className={num}>{v.vendor_id ? v.statements : "—"}</td>
                <td className={num}>{inr(v.vendor_billed)}</td>
                <td className={num}>{inr(v.books)}</td>
                <td className={cn(num, Math.abs(v.difference) >= 1 ? "font-semibold text-amber-700" : "text-emerald-700")}>{signed(v.difference)}</td>
                <td className={cn(num, v.open.lines ? "text-amber-700 font-semibold" : "")}>{v.open.lines}</td>
                <td className={num}>
                  {v.closing != null ? <>{inr(v.closing)}<span className="block text-[10px] text-slate-400">as at {fmtDate(v.as_at)}</span></> : "—"}
                </td>
                <td className={num}>{v.books_balance != null ? inr(v.books_balance) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── a case tab ───────────────────────────────────────────────────────────────
function ViewBanner({ view, s }: { view: ListView; s: Summary }) {
  if (view === "all") {
    return (
      <Banner tone="bg-slate-50 border-slate-200 text-slate-700" icon={<ListChecks className="w-4 h-4 text-slate-500" />}>
        <span>
          <b>Every ticket line in these filters</b>, on either side — <b className="text-emerald-700">{s.matched.lines}</b> matched,{" "}
          <b className={s.open.lines ? "text-amber-700" : ""}>{s.open.lines}</b> open, <b>{s.resolved}</b> resolved.
          Open a line to see both sides; resolve an open one here or on its case tab.
        </span>
      </Banner>
    );
  }
  if (view === "unmatched") {
    return (
      <Banner tone="bg-amber-50/40 border-amber-100 text-amber-950" icon={<Scale className="w-4 h-4 text-amber-600" />}>
        <span>
          <b>Lines the vendor statement and your books disagree on</b> — a figure differs, or the line is on one side
          only: <b className={s.open.lines ? "text-amber-700" : ""}>{s.open.lines}</b> open, <b>{s.resolved}</b> resolved.
          Each is in one of the eight items; open a line to see which figure moved.
        </span>
      </Banner>
    );
  }
  if (view === "matched") {
    return (
      <Banner tone="bg-emerald-50/60 border-emerald-100 text-emerald-900" icon={<CheckCircle2 className="w-4 h-4 text-emerald-600" />}>
        <b>Agreed.</b> Both statements show these lines within ₹1 — your books round to the rupee. Nothing to check
        again when the next statement loads.
      </Banner>
    );
  }
  if (view === "resolved") {
    return (
      <Banner tone="bg-slate-50 border-slate-200 text-slate-700" icon={<CheckCircle2 className="w-4 h-4 text-slate-500" />}>
        The lines you resolved and closed. If either statement&apos;s figures for a line change later, it moves back to its
        case marked <b>Reopened</b>. Reopen a line here to undo a decision.
      </Banner>
    );
  }
  const c = CASE_BY[view];
  const a = s.cases[view];
  return (
    <Banner tone={a.open_amount < 0 ? "bg-red-50/40 border-red-100 text-red-950" : "bg-sky-50/50 border-sky-100 text-sky-950"}
      icon={view === "vendor_only" || view === "internal_only"
        ? <Hourglass className="w-4 h-4 text-slate-500" /> : <Scale className="w-4 h-4 text-slate-500" />}>
      <span className="flex-1">
        <b>{c.n}. {c.label}</b> — {c.what}{" "}
        <span className="whitespace-nowrap">
          {a.open} open: <b className={a.open_amount < 0 ? "text-red-700" : "text-sky-700"}>{lessAdd(a.open_amount)} {inr(Math.abs(a.open_amount))}</b>
        </span>
        {a.resolved > 0 && <span className="text-slate-500"> · {a.resolved} resolved</span>}.
        {" "}Open a line to see which figure moved; resolve it once you&apos;ve raised it with the vendor or corrected your books.
      </span>
      {view === "vendor_only" && (
        <Link href="/internal-statement/upload" className="shrink-0 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline">
          Load internal statement <ArrowRight className="w-3 h-3" /></Link>
      )}
      {view === "internal_only" && (
        <Link href="/vendors/statements/third-party/gds" className="shrink-0 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline">
          Load GDS statement <ArrowRight className="w-3 h-3" /></Link>
      )}
    </Banner>
  );
}

function Banner({ tone, icon, children }: { tone: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div className={cn("flex items-center gap-2.5 px-4 py-2.5 border rounded-xl text-xs", tone)}>
      <span className="shrink-0">{icon}</span>
      {children}
    </div>
  );
}

// Column headings per view — each asks a different question of the same line. "a" is the
// action column, pinned to the right edge so it stays in reach however wide the hints run.
type Col = [string, "l" | "r" | "a"];
function columns(view: ViewId, withVendor: boolean): Col[] {
  const lead: Col[] = [["Ticket", "l"], ["Type", "l"], ...(withVendor ? [["Vendor", "l"] as Col] : []), ["Passenger", "l"], ["Booked", "l"]];
  switch (view) {
    case "all":
    case "unmatched":
      return [...lead, ["Status", "l"], ["Vendor statement", "l"], ["Vendor net", "r"], ["Doc No", "l"], ["Books net", "r"],
        ["Books − vendor", "r"], ["", "a"]];
    case "vendor_only":
      return [...lead, ["Vendor statement", "l"], ["Vendor net", "r"], ["Item", "r"], ["Outlook", "l"], ["Why", "l"], ["", "a"]];
    case "internal_only":
      return [...lead, ["Doc No", "l"], ["Books net", "r"], ["Item", "r"], ["Outlook", "l"], ["Why", "l"], ["", "a"]];
    case "matched":
      return [...lead, ["Vendor statement", "l"], ["Vendor net", "r"], ["Books net", "r"], ["Round-off", "r"]];
    case "resolved":
      return [...lead, ["Was", "l"], ["Vendor net", "r"], ["Books net", "r"], ["Books − vendor", "r"], ["Decision", "l"],
        ["Resolved", "l"], ["Note", "l"], ["", "a"]];
    default:
      // Money before references: on a laptop screen the difference must not be the part that scrolls away.
      return [...lead, ["Vendor net", "r"], ["Books net", "r"], ["Item", "r"], ["Also", "l"], ["What differs", "l"],
        ["Vendor statement", "l"], ["", "a"]];
  }
}
const STICKY_ACTION = "sticky right-0 shadow-[-8px_0_8px_-8px_rgba(15,23,42,0.25)]";

const EMPTY: Record<ListView, string> = {
  all: "No ticket in these filters.",
  unmatched: "Every line agrees — nothing unmatched in these filters.",
  extra_fare: "No sale billed higher than your books.",
  less_fare: "No sale billed lower than your books.",
  extra_refund: "No refund credited lower than your books.",
  less_refund: "No refund credited higher than your books.",
  extra_commission: "No commission short-passed or taken back.",
  less_commission: "No commission passed on beyond your books.",
  vendor_only: "Everything on the vendor statements is in your books.",
  internal_only: "Everything in your books is billed on a vendor statement.",
  matched: "No line agrees yet.",
  resolved: "Nothing resolved yet. Resolve a line in its case and it appears here.",
};

function Cells({ row: r, view, cols, busy, onResolve, onReopen }: {
  row: Row; view: ViewId; cols: Col[]; busy: boolean; onResolve: () => void; onReopen: () => void;
}) {
  const code = r.vendor?.ticket_prefix ?? r.internal?.ticket_prefix;
  const td = "px-3 py-2 whitespace-nowrap";
  const num = "px-3 py-2 text-right tabular-nums whitespace-nowrap";
  const capped = (text: string | null | undefined, w: string, cls = "") => (
    <div className={cn("truncate", w, cls)} title={text ?? undefined}>{text ?? "—"}</div>
  );
  const item = (amount: number) => (
    <div className={cn("font-semibold", amount < 0 ? "text-red-700" : "text-sky-700")}>
      <span className="text-[10px] font-bold uppercase mr-1">{lessAdd(amount)}</span>{inr(Math.abs(amount))}
    </div>
  );
  const cell = (h: string): ReactNode => {
    switch (h) {
      case "Ticket":
        return (
          <td key={h} className={cn(td, "font-mono")}>
            {code && <span className="text-slate-400 mr-1">{code}</span>}
            <b className="text-slate-800">{r.ticket_number ?? "—"}</b>
            {r.open && r.resolution?.stale && (
              <span title={`Resolved ${fmtDate(r.resolution.resolved_at)} as “${DECISION[r.resolution.decision].label}” — the figures have changed since`}
                className="ml-1.5 font-sans px-1.5 py-0.5 rounded border text-[10px] font-semibold bg-orange-50 text-orange-700 border-orange-200">
                Reopened
              </span>
            )}
          </td>
        );
      case "Type":
        return <td key={h} className={td}><span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold", KIND_CLS[r.kind])}>{KIND[r.kind]}</span></td>;
      case "Vendor":
        return <td key={h} className={td}>{capped(r.vendor_name ?? "No vendor", "max-w-[150px]", "text-slate-600")}</td>;
      case "Passenger":
        return <td key={h} className={td}>{capped(r.internal?.pax ?? r.vendor?.pax, "max-w-[170px]", "text-slate-700")}</td>;
      case "Booked":
        return <td key={h} className={cn(td, "text-slate-500")}>{fmtDate(r.booked)}</td>;
      case "Vendor statement":
        return <td key={h} className={td}>{capped(r.vendor?.ref ?? r.vendor?.source, "max-w-[170px]", "text-slate-600")}</td>;
      case "Doc No":
        return <td key={h} className={td}>{capped(r.internal?.ref, "max-w-[150px]", "text-slate-600 font-mono")}</td>;
      case "Vendor net":
        return <td key={h} className={num}>{inr(r.vendor?.net)}</td>;
      case "Books net":
        return <td key={h} className={num}>{inr(r.internal?.net)}</td>;
      case "Item":
        // A case tab shows that case's part of the line; any other, the line's whole difference.
        return <td key={h} className={num}>{item(view in CASE_BY ? caseAmount(r, view as CaseId) : r.adjustment)}</td>;
      case "Books − vendor":
        return <td key={h} className={cn(num, "font-semibold text-slate-600")}>{signed(r.adjustment)}</td>;
      case "Status":
        return <td key={h} className={td}><Standing row={r} /></td>;
      case "Round-off":
        return (
          <td key={h} className={cn(num, "text-emerald-600")}>
            {Math.abs(r.adjustment) >= 0.005 ? signed(r.adjustment) : <CheckCircle2 className="w-3.5 h-3.5 inline" />}
          </td>
        );
      case "Also": {
        // The row's other item — its commission, or the rest of its difference.
        const others = r.cases.filter((c) => c.case !== view);
        return (
          <td key={h} className={td}>
            {others.length ? others.map((c) => (
              <span key={c.case} title={CASE_BY[c.case].label}
                className="mr-1 px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50 text-[10px] text-slate-600 tabular-nums">
                {CASE_BY[c.case].n} {CASE_BY[c.case].short} {inr(Math.abs(c.amount))}
              </span>
            )) : <span className="text-slate-300">—</span>}
          </td>
        );
      }
      case "What differs": {
        const moved = FIELDS.filter(([k]) => k !== "net" && Math.abs(r.diff?.[k] ?? 0) >= 0.5);
        return (
          <td key={h} className={td}>
            {moved.length ? moved.map(([k, label]) => (
              <span key={k} title={`Vendor ${inr(r.vendor?.[k] as number)} · books ${inr(r.internal?.[k] as number)}`}
                className="mr-1 px-1.5 py-0.5 rounded bg-amber-50 text-[10px] font-semibold text-amber-800">{label}</span>
            )) : <span className="text-[11px] text-slate-400">Net only</span>}
          </td>
        );
      }
      case "Outlook":
        return (
          <td key={h} className={td}>
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
      case "Why":
        return (
          <td key={h} className="px-3 py-2 text-slate-600">
            {r.hints.length ? (
              <span className="flex items-start gap-1.5 max-w-[320px]" title={r.hints.join("\n")}>
                <Lightbulb className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-px" />
                <span className="truncate">{r.hints[0]}</span>
                {r.hints.length > 1 && <span className="text-slate-400 shrink-0">+{r.hints.length - 1}</span>}
              </span>
            ) : null}
          </td>
        );
      case "Was":
        return (
          <td key={h} className={td}>
            {r.cases.length ? r.cases.map((c) => (
              <span key={c.case} className="mr-1 px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50 text-[10px] text-slate-600">
                {CASE_BY[c.case].n} {CASE_BY[c.case].short}
              </span>
            )) : STATUS_LABEL[r.status]}
          </td>
        );
      case "Decision":
        return (
          <td key={h} className={td}>
            {r.resolution && (
              <span className={cn("px-1.5 py-0.5 rounded border text-[10px] font-semibold", DECISION[r.resolution.decision].cls)}>
                {DECISION[r.resolution.decision].short}
              </span>
            )}
          </td>
        );
      case "Resolved":
        return <td key={h} className={cn(td, "text-slate-500")}>{fmtDate(r.resolution?.resolved_at)}</td>;
      case "Note":
        return <td key={h} className={td}>{capped(r.resolution?.note, "max-w-[280px]", "text-slate-600")}</td>;
      case "":
        return (
          <td key="action" className={cn("px-2 py-2 bg-inherit", STICKY_ACTION)} onClick={(e) => e.stopPropagation()}>
            {r.status === "matched" ? null : view === "resolved" || !r.open ? (
              <button onClick={onReopen} disabled={busy}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md border border-slate-300 bg-white text-slate-600 text-[11px] font-semibold hover:bg-slate-50 disabled:opacity-50">
                <RotateCcw className="w-3 h-3" /> Reopen
              </button>
            ) : (
              <button onClick={onResolve} disabled={busy}
                className="px-2.5 py-1 rounded-md border border-amber-300 bg-amber-50 text-amber-800 text-[11px] font-semibold hover:bg-amber-100 disabled:opacity-50">
                Resolve
              </button>
            )}
          </td>
        );
      default:
        return <td key={h} />;
    }
  };
  return <>{cols.map(([h]) => cell(h))}</>;
}

/** Where a line stands: matched, or its reconciling items and whether they are still open. */
function Standing({ row: r }: { row: Row }) {
  const pill = "inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold";
  if (r.status === "matched") {
    return <span className={cn(pill, "bg-emerald-50 text-emerald-700 border-emerald-200")}><CheckCircle2 className="w-3 h-3" /> Matched</span>;
  }
  return (
    <span className="inline-flex items-center gap-1">
      {(r.cases.length ? r.cases.map((c) => `${CASE_BY[c.case].n} ${CASE_BY[c.case].short}`) : [STATUS_LABEL[r.status]]).map((t) => (
        <span key={t} className="px-1.5 py-0.5 rounded border border-slate-200 bg-slate-50 text-[10px] text-slate-600">{t}</span>
      ))}
      {r.open ? (
        <span className={cn(pill, "bg-amber-50 text-amber-800 border-amber-200")}>
          {r.resolution?.stale ? "Reopened" : "Open"}
        </span>
      ) : (
        <span className={cn(pill, "bg-slate-100 text-slate-600 border-slate-200")}>
          Resolved{r.resolution ? ` · ${DECISION[r.resolution.decision].short}` : ""}
        </span>
      )}
    </span>
  );
}

function Detail({ row }: { row: Row }) {
  const v = row.vendor, i = row.internal;
  const res = row.resolution;
  const waiting = row.open && (row.status === "vendor_only" || row.status === "internal_only") ? (v ?? i) : null;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-4">
      <div className="space-y-3">
        <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-100 text-slate-500">
                <th className="px-3 py-1.5 text-left font-semibold" />
                <th className="px-3 py-1.5 text-right font-semibold">Vendor statement</th>
                <th className="px-3 py-1.5 text-right font-semibold">Your books</th>
                <th className="px-3 py-1.5 text-right font-semibold">Books − vendor</th>
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
                <td className="px-3 py-1.5">Sector · booked</td>
                <td className="px-3 py-1.5 text-right font-mono">{v ? `${v.sector || "—"} · ${v.booked ?? "—"}` : "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono">{i ? `${i.sector || "—"} · ${i.booked ?? "—"}` : "—"}</td>
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
        {row.cases.length > 0 && (
          <div className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-xs">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">In the reconciliation as</p>
            {row.cases.map((c) => (
              <p key={c.case} className="flex justify-between gap-3 tabular-nums">
                <span className="text-slate-600">{CASE_BY[c.case].n}. {CASE_BY[c.case].label}</span>
                <b className={c.amount < 0 ? "text-red-700" : "text-sky-700"}>{lessAdd(c.amount)} {inr(Math.abs(c.amount))}</b>
              </p>
            ))}
            {row.cases.length > 1 && (
              <p className="flex justify-between gap-3 tabular-nums border-t border-slate-100 mt-1 pt-1 text-slate-500">
                <span>Net difference of the line</span><b>{signed(row.adjustment)}</b>
              </p>
            )}
          </div>
        )}
        {row.siblings.length > 0 && (
          <div className="bg-white border border-slate-200 rounded-lg px-3 py-2 text-xs">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1">Other lines of this ticket</p>
            {row.siblings.map((o) => (
              <p key={o.key} className="flex flex-wrap items-center gap-2 py-0.5 text-slate-600">
                <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold", KIND_CLS[o.kind])}>{KIND[o.kind]}</span>
                <span className="font-semibold">
                  {o.status === "matched" ? "Matched" : o.cases.length
                    ? o.cases.map((c) => `${CASE_BY[c].n} ${CASE_BY[c].short}`).join(" + ") : STATUS_LABEL[o.status]}
                  {o.status !== "matched" && !o.open ? " · resolved" : ""}
                </span>
                <span className="tabular-nums">vendor {inr(o.vendor_net)} · books {inr(o.internal_net)}</span>
                <span className="text-slate-400 truncate max-w-[260px]">{[o.vendor_ref, o.internal_ref].filter(Boolean).join(" · ")}</span>
              </p>
            ))}
          </div>
        )}
      </div>
      <div className="space-y-1.5">
        {res && (
          <div className={cn("text-xs rounded-lg px-2.5 py-2 border",
            res.stale ? "bg-orange-50 border-orange-200 text-orange-900" : "bg-white border-slate-200 text-slate-700")}>
            <p className="font-semibold">
              {res.stale ? "Was resolved — figures changed since" : "Resolved"}: {DECISION[res.decision].label}
            </p>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {fmtDate(res.resolved_at)} · at vendor {inr(res.vendor_net)} / books {inr(res.internal_net)}
              {res.difference != null && ` · difference ${inr(res.difference)}`}
            </p>
            {res.note && <p className="mt-1 text-slate-700">“{res.note}”</p>}
          </div>
        )}
        {waiting && (
          <p className="flex items-start gap-1.5 text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5">
            <Hourglass className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-px" />
            Waiting since {fmtDate(waiting.loaded_at)}, when {waiting.source ?? "its statement"} was loaded.
            {row.pending === "next_statement" ? " It is dated after everything the other side has loaded for this vendor — expected in its next statement."
              : row.pending === "in_period" ? " The other side's statements for this vendor already cover its date." : ""}
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

// ── the Already uploaded tab ─────────────────────────────────────────────────
function LeftOutBanner({ a, oneStatement }: { a: LeftOutAgg; oneStatement: boolean }) {
  return (
    <Banner tone="bg-amber-50/40 border-amber-100 text-slate-700" icon={<Copy className="w-4 h-4 text-amber-600" />}>
      <span>
        <b>Already uploaded.</b> Lines of {oneStatement ? "this statement's file" : "these statements' files"} that were not
        saved because they repeat a line already saved — on an earlier statement, or earlier in the same file. Each is
        reconciled once, as the line it repeats, and is not counted again in the reconciliation.
        {a.lines > 0 && (
          <> <b>{a.matched}</b> matched · <b>{a.resolved}</b> resolved · <b className={a.open ? "text-amber-700" : ""}>{a.open}</b> still open
            {a.unsaved ? <> · <b className="text-orange-700">{a.unsaved}</b> whose saved line was deleted</> : null}.</>
        )}
        {a.unlisted > 0 && (
          <> {a.unlisted} more {a.unlisted !== 1 ? "were" : "was"} left out before these lines were kept — delete{" "}
            {oneStatement ? "this statement" : "that statement"} and upload it again to list them.</>
        )}
      </span>
    </Banner>
  );
}

/** Where the line a left-out line repeats — and so the left-out line — stands. */
function ReconciledThere({ p }: { p: LeftOut }) {
  const o = p.original;
  const pill = "inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold";
  if (!o || p.state === "unsaved") {
    return <span className={cn(pill, "bg-orange-50 text-orange-700 border-orange-200")}><AlertCircle className="w-3 h-3" /> Saved line deleted</span>;
  }
  if (p.state === "matched") {
    return <span className={cn(pill, "bg-emerald-50 text-emerald-700 border-emerald-200")}><CheckCircle2 className="w-3 h-3" /> Matched · closed</span>;
  }
  if (p.state === "resolved") {
    return (
      <span className={cn(pill, "bg-slate-100 text-slate-600 border-slate-200")}>
        <CheckCircle2 className="w-3 h-3" /> Resolved{o.resolution ? ` · ${DECISION[o.resolution.decision].short}` : ""}
      </span>
    );
  }
  return (
    <span className={cn(pill, "bg-amber-50 text-amber-800 border-amber-200")}
      title="Still open on the statement the line is saved in — resolve it there">
      <Hourglass className="w-3 h-3" /> Open · {o.cases.length
        ? o.cases.map((c) => `${CASE_BY[c.case].n} ${CASE_BY[c.case].short}`).join(" + ") : STATUS_LABEL[o.status]}
    </span>
  );
}

function LeftOutTable({ list, withVendor, withStatement, loading, empty, open, onToggle }: {
  list: LeftOut[]; withVendor: boolean; withStatement: boolean; loading: boolean; empty: string;
  open: Set<string>; onToggle: (key: string) => void;
}) {
  const heads: [string, "l" | "r"][] = [
    ["Ticket", "l"], ["Type", "l"], ...(withVendor ? [["Vendor", "l"] as [string, "l"]] : []),
    ["Passenger", "l"], ["Booked", "l"], ["Vendor net", "r"], ["Not saved as", "l"],
    ...(withStatement ? [["On statement", "l"] as [string, "l"]] : []),
    ["Saved in", "l"], ["Reconciled there", "l"], ["Doc No", "l"], ["Books net", "r"],
  ];
  const td = "px-3 py-2 whitespace-nowrap";
  const num = "px-3 py-2 text-right tabular-nums whitespace-nowrap";
  const capped = (text: string | null | undefined, w: string, cls = "") => (
    <div className={cn("truncate", w, cls)} title={text ?? undefined}>{text ?? "—"}</div>
  );
  return (
    <div className={cn("bg-white border border-slate-200 rounded-xl overflow-hidden", loading && "opacity-60")}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-max text-xs">
          <thead>
            <tr className="bg-slate-800 text-white/80">
              <th className="w-6" />
              {heads.map(([h, align]) => (
                <th key={h} className={cn("px-3 py-2 text-[11px] font-semibold uppercase tracking-wide",
                  align === "r" ? "text-right" : "text-left")}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {list.length === 0 && (
              <tr><td colSpan={heads.length + 1} className="px-4 py-10 text-center text-slate-400">{loading ? "Loading…" : empty}</td></tr>
            )}
            {list.map((p) => {
              const isOpen = open.has(p.key);
              const o = p.original;
              return (
                <Fragment key={p.key}>
                  <tr onClick={() => onToggle(p.key)}
                    className={cn("cursor-pointer bg-white hover:bg-slate-50", isOpen && "bg-blue-50")}>
                    <td className="pl-2">
                      {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-300" />}
                    </td>
                    <td className={cn(td, "font-mono")}>
                      {p.vendor.ticket_prefix && <span className="text-slate-400 mr-1">{p.vendor.ticket_prefix}</span>}
                      <b className="text-slate-800">{p.ticket_number ?? "—"}</b>
                    </td>
                    <td className={td}>
                      <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold", KIND_CLS[p.kind])}>{KIND[p.kind]}</span>
                    </td>
                    {withVendor && <td className={td}>{capped(p.vendor_name ?? "No vendor", "max-w-[150px]", "text-slate-600")}</td>}
                    <td className={td}>{capped(p.vendor.pax, "max-w-[170px]", "text-slate-700")}</td>
                    <td className={cn(td, "text-slate-500")}>{fmtDate(p.booked)}</td>
                    <td className={num}>{inr(p.vendor.net)}</td>
                    <td className={td}>
                      <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-semibold", LEFT_OUT[p.left_out].cls)}>
                        {LEFT_OUT[p.left_out].label}
                      </span>
                      {p.differs.length > 0 && <span className="ml-1 text-[10px] text-slate-500">{p.differs.join(", ")} changed</span>}
                      {p.file_row != null && <span className="ml-1 text-[10px] text-slate-400">row {p.file_row + 1}</span>}
                    </td>
                    {withStatement && <td className={td}>{capped(p.statement ? stmtLabel(p.statement) : null, "max-w-[200px]", "text-slate-600")}</td>}
                    <td className={td}>{capped(p.first_statement ? stmtLabel(p.first_statement) : null, "max-w-[200px]", "text-slate-600")}</td>
                    <td className={td}><ReconciledThere p={p} /></td>
                    <td className={cn(td, "font-mono text-slate-600")}>{o?.internal?.ref ?? "—"}</td>
                    <td className={num}>{inr(o?.internal?.net)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="bg-slate-50/60">
                      <td />
                      <td colSpan={heads.length} className="py-3 pr-3 pl-3"><LeftOutDetail p={p} /></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LeftOutDetail({ p }: { p: LeftOut }) {
  const o = p.original;
  return (
    <div className="space-y-2">
      <p className="flex items-start gap-1.5 text-xs text-slate-600 bg-white border border-slate-200 rounded-lg px-2.5 py-1.5">
        <Copy className="w-3.5 h-3.5 text-slate-400 shrink-0 mt-px" />
        <span>
          {p.file_row != null ? `Row ${p.file_row + 1} of ` : "A line of "}{p.statement?.file_name ?? "this statement"} — not
          saved: {LEFT_OUT[p.left_out].what}
          {p.differs.length > 0 && <> ({p.differs.join(", ")} changed — net {inr(p.vendor.net)} on this file, {inr(o?.vendor?.net)} as saved)</>}.{" "}
          {o
            ? <>It is reconciled once, as the line saved in <b>{p.first_statement?.file_name ?? "an earlier statement"}</b>:</>
            : <>The line it repeats has been deleted since. Delete this statement and upload it again to save it and reconcile it.</>}
        </span>
      </p>
      {o && <Detail row={o} />}
    </div>
  );
}

function ResolveDialog({ rows, busy, onClose, onSubmit }: {
  rows: Row[]; busy: boolean; onClose: () => void; onSubmit: (d: Decision, note: string) => void;
}) {
  const [decision, setDecision] = useState<Decision | null>(null);
  const [note, setNote] = useState("");
  const st = rows[0].status as OpenStatus;
  const one = rows.length === 1 ? rows[0] : null;
  const total = rows.reduce((t, r) => t + r.adjustment, 0);

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
            <MiniStat label="Vendor net" value={inr(rows.reduce((t, r) => t + (r.vendor?.net ?? 0), 0))} />
            <MiniStat label="Books net" value={inr(rows.reduce((t, r) => t + (r.internal?.net ?? 0), 0))} />
            <MiniStat label={total < 0 ? "Less" : "Add"} value={inr(Math.abs(total))} tone />
          </div>
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
            {busy ? "Saving…" : rows.length > 1 ? `Resolve ${rows.length} lines` : "Resolve & close"}
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
