"use client";

// Vendors → Reconciliation → Third Party → GDS ↔ Internal.
//
// The consolidator's Third Party GDS statement against Internal Statement — sale with
// sale, refund with refund — with the difference per figure and a hint, in words, on
// every row that is not a clean match. All the matching is server-side
// (backend/app/services/vendor_internal_recon.py); this picks the uploads, filters and
// shows the answer.

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle, ArrowLeftRight, CheckCircle2, ChevronDown, ChevronRight, Download, Lightbulb,
  RefreshCw, Search,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

type Side = {
  id: number; ticket_prefix: string | null; pax: string | null; pnr: string | null;
  sector: string; date: string | null; ref: string | null; source: string | null;
  fare: number; commission: number; charges: number; gst: number; tds: number; net: number;
};
type Row = {
  key: string; ticket_number: string | null;
  kind: "sale" | "refund" | "sale+refund";
  status: "matched" | "difference" | "vendor_only" | "internal_only";
  vendor: Side | null; internal: Side | null;
  diff: Record<string, number> | null; hints: string[];
};
type Summary = {
  vendor_lines: number; internal_lines: number;
  matched: number; difference: number; vendor_only: number; internal_only: number;
  vendor_net: number; internal_net: number; net_difference: number; difference_amount: number;
};
type Sources = {
  vendor: { batch_id: string; file_name: string; rows: number; supplier_name: string | null; supplier_code: string | null }[];
  internal: { batch_id: string; statement_name: string | null; agency: string; file_name: string; tickets: number }[];
};

const STATUS: Record<Row["status"], { label: string; cls: string }> = {
  matched:       { label: "Matched",       cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  difference:    { label: "Difference",    cls: "bg-amber-50 text-amber-800 border-amber-200" },
  vendor_only:   { label: "Vendor only",   cls: "bg-red-50 text-red-700 border-red-200" },
  internal_only: { label: "Internal only", cls: "bg-violet-50 text-violet-700 border-violet-200" },
};
const KIND: Record<Row["kind"], string> = { sale: "Sale", refund: "Refund", "sale+refund": "Sold & refunded" };
const FIELDS: [keyof Side & string, string][] = [
  ["fare", "Fare + taxes"], ["commission", "Commission / discount"], ["charges", "Charges"],
  ["gst", "GST"], ["tds", "TDS"], ["net", "Net"],
];

const inr = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function VendorInternalRecon() {
  const [sources, setSources] = useState<Sources | null>(null);
  const [vendorSel, setVendorSel] = useState<Set<string>>(new Set());
  const [internalSel, setInternalSel] = useState<Set<string>>(new Set());
  const [data, setData] = useState<{ summary: Summary; rows: Row[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [status, setStatus] = useState<"" | Row["status"]>("");
  const [kind, setKind] = useState<"" | Row["kind"]>("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.get<Sources>("/reconciliation/vendor-internal/sources")
      .then((r) => setSources(r.data))
      .catch(() => setError("Could not load the uploads to compare."));
  }, []);

  // Empty selection = everything on that side.
  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      vendorSel.forEach((b) => params.append("vendor_batch", b));
      internalSel.forEach((b) => params.append("internal_batch", b));
      const { data } = await api.get<{ summary: Summary; rows: Row[] }>(
        `/reconciliation/vendor-internal?${params.toString()}`);
      setData(data);
      setOpen(new Set());
    } catch {
      setError("Reconciliation failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [vendorSel, internalSel]);

  useEffect(() => { run(); }, [run]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data?.rows ?? []).filter((r) =>
      (!status || r.status === status) && (!kind || r.kind === kind) &&
      (!q || [r.ticket_number, r.vendor?.pax, r.internal?.pax, r.vendor?.pnr, r.internal?.pnr,
              r.internal?.ref, r.vendor?.ref, r.vendor?.sector, r.internal?.sector]
        .some((x) => (x ?? "").toLowerCase().includes(q))));
  }, [data, status, kind, search]);

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    setter(next);
  };

  const exportCsv = () => {
    const head = ["Ticket", "Type", "Status", "Vendor week", "Vendor pax", "Vendor net",
      "Internal Doc No", "Internal pax", "Internal net", "Net difference", "Hints"];
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = rows.map((r) => [
      `${r.vendor?.ticket_prefix ?? r.internal?.ticket_prefix ?? ""} ${r.ticket_number ?? ""}`.trim(),
      KIND[r.kind], STATUS[r.status].label, r.vendor?.ref, r.vendor?.pax, r.vendor?.net,
      r.internal?.ref, r.internal?.pax, r.internal?.net, r.diff?.net, r.hints.join(" | "),
    ].map(esc).join(","));
    const blob = new Blob([[head.join(","), ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "vendor_vs_internal_reconciliation.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const s = data?.summary;

  return (
    <div className="space-y-4">
      {/* what is being compared */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <SourcePicker
          title="Vendor — Third Party GDS statements"
          empty="No Third Party GDS statement uploaded yet (Vendors data → Statements → Third Party → GDS)."
          items={(sources?.vendor ?? []).map((v) => ({
            id: v.batch_id, label: v.file_name,
            sub: `${v.supplier_name ?? "No vendor"}${v.supplier_code ? ` · ${v.supplier_code}` : ""} · ${v.rows} rows`,
          }))}
          selected={vendorSel}
          onToggle={(id) => toggle(vendorSel, setVendorSel, id)}
          onAll={() => setVendorSel(new Set())}
        />
        <SourcePicker
          title="Internal — Internal Statement"
          empty="No Internal Statement tickets yet."
          items={(sources?.internal ?? []).map((i) => ({
            id: i.batch_id,
            label: i.file_name === "Manual Entry" ? `Punched — ${i.agency}` : i.file_name,
            sub: `${i.statement_name ?? i.agency} · ${i.tickets} tickets`,
          }))}
          selected={internalSel}
          onToggle={(id) => toggle(internalSel, setInternalSel, id)}
          onAll={() => setInternalSel(new Set())}
        />
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* summary */}
      {s && (
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2">
          {([
            ["matched", "Matched", s.matched, "text-emerald-700"],
            ["difference", "Differences", s.difference, "text-amber-700"],
            ["vendor_only", "Vendor only", s.vendor_only, "text-red-700"],
            ["internal_only", "Internal only", s.internal_only, "text-violet-700"],
          ] as const).map(([k, label, n, cls]) => (
            <button
              key={k}
              type="button"
              onClick={() => setStatus(status === k ? "" : k)}
              className={cn("text-left bg-white border rounded-xl px-3 py-2 hover:bg-slate-50",
                status === k ? "border-blue-400 ring-1 ring-blue-200" : "border-slate-200")}
            >
              <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
              <p className={cn("text-lg font-bold tabular-nums", cls)}>{n}</p>
            </button>
          ))}
          <Stat label="Vendor net" value={inr(s.vendor_net)} sub={`${s.vendor_lines} lines`} />
          <Stat label="Internal net" value={inr(s.internal_net)} sub={`${s.internal_lines} lines`} />
          <Stat label="Net difference" value={inr(s.net_difference)} sub="internal − vendor"
            tone={Math.abs(s.net_difference) >= 1 ? "amber" : "plain"} />
        </div>
      )}

      {/* filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Ticket, pax, PNR, Doc No, sector…"
            className="pl-8 pr-3 py-2 text-xs border border-slate-200 rounded-lg w-64 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
        </div>
        <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}
          className="py-2 px-2.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-600">
          <option value="">Sales &amp; refunds</option>
          <option value="sale">Sales</option>
          <option value="refund">Refunds</option>
          <option value="sale+refund">Sold &amp; refunded</option>
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}
          className="py-2 px-2.5 text-xs border border-slate-200 rounded-lg bg-white text-slate-600">
          <option value="">All statuses</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <span className="text-xs text-slate-400">{rows.length} row{rows.length !== 1 ? "s" : ""}</span>
        <div className="ml-auto flex items-center gap-2">
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

      {/* rows */}
      <div className={cn("bg-white border border-slate-200 rounded-xl overflow-hidden", loading && "opacity-60")}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-max text-xs">
            <thead>
              <tr className="bg-slate-800 text-white/80">
                <th className="w-6" />
                {["Ticket", "Type", "Status", "Vendor", "Internal"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide">{h}</th>
                ))}
                {["Vendor net", "Internal net", "Difference"].map((h) => (
                  <th key={h} className="px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wide">{h}</th>
                ))}
                <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide">Hint</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-10 text-center text-slate-400">
                  {data ? "Nothing to show for these filters." : "Loading…"}
                </td></tr>
              )}
              {rows.map((r) => {
                const isOpen = open.has(r.key);
                const code = r.vendor?.ticket_prefix ?? r.internal?.ticket_prefix;
                const d = r.diff?.net;
                return (
                  <Fragment key={r.key}>
                    <tr
                      onClick={() => toggle(open, setOpen, r.key)}
                      className={cn("cursor-pointer hover:bg-slate-50", isOpen && "bg-blue-50/40")}
                    >
                      <td className="pl-3">
                        {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" /> : <ChevronRight className="w-3.5 h-3.5 text-slate-300" />}
                      </td>
                      <td className="px-3 py-2 font-mono whitespace-nowrap">
                        {code && <span className="text-slate-400 mr-1">{code}</span>}
                        <b className="text-slate-800">{r.ticket_number ?? "—"}</b>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-bold",
                          r.kind === "sale" ? "bg-emerald-50 text-emerald-700"
                            : r.kind === "refund" ? "bg-amber-100 text-amber-800" : "bg-sky-50 text-sky-700")}>
                          {KIND[r.kind]}
                        </span>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span className={cn("px-1.5 py-0.5 rounded border text-[10px] font-semibold", STATUS[r.status].cls)}>
                          {STATUS[r.status].label}
                        </span>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-slate-600 max-w-[220px] truncate">
                        {r.vendor ? <>{r.vendor.ref ?? "—"} · {r.vendor.pax ?? "—"}</> : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap text-slate-600 max-w-[220px] truncate">
                        {r.internal ? <>{r.internal.ref ?? "—"} · {r.internal.pax ?? "—"}</> : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{inr(r.vendor?.net)}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{inr(r.internal?.net)}</td>
                      <td className={cn("px-3 py-2 text-right tabular-nums font-semibold",
                        d == null ? "text-slate-300" : Math.abs(d) >= 1 ? "text-amber-700" : "text-emerald-600")}>
                        {d == null ? "—" : inr(d)}
                      </td>
                      <td className="px-3 py-2 text-slate-600 max-w-[380px]">
                        {r.hints.length ? (
                          <span className="flex items-start gap-1.5">
                            <Lightbulb className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-px" />
                            <span className="truncate">{r.hints[0]}</span>
                            {r.hints.length > 1 && <span className="text-slate-400 shrink-0">+{r.hints.length - 1}</span>}
                          </span>
                        ) : r.status === "matched" ? (
                          <span className="flex items-center gap-1 text-emerald-600"><CheckCircle2 className="w-3.5 h-3.5" /> Agrees</span>
                        ) : null}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-slate-50/60">
                        <td />
                        <td colSpan={9} className="px-3 py-3">
                          <Detail row={r} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Detail({ row }: { row: Row }) {
  const v = row.vendor, i = row.internal;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-4">
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-100 text-slate-500">
              <th className="px-3 py-1.5 text-left font-semibold" />
              <th className="px-3 py-1.5 text-right font-semibold">Vendor</th>
              <th className="px-3 py-1.5 text-right font-semibold">Internal</th>
              <th className="px-3 py-1.5 text-right font-semibold">Internal − vendor</th>
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
              <td className="px-3 py-1.5">File</td>
              <td className="px-3 py-1.5 text-right truncate max-w-[220px]">{v?.source ?? "—"}</td>
              <td className="px-3 py-1.5 text-right truncate max-w-[220px]">{i?.source ?? "—"}</td>
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <div className="space-y-1.5">
        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1">
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

function SourcePicker({ title, empty, items, selected, onToggle, onAll }: {
  title: string;
  empty: string;
  items: { id: string; label: string; sub: string }[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onAll: () => void;
}) {
  const all = selected.size === 0;
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-3 py-2.5">
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{title}</p>
        <button type="button" onClick={onAll}
          className={cn("text-[10px] font-semibold px-2 py-0.5 rounded",
            all ? "bg-blue-50 text-blue-700" : "text-slate-400 hover:text-slate-700")}>
          All
        </button>
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-slate-400 italic">{empty}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((it) => {
            const on = all || selected.has(it.id);
            return (
              <button
                key={it.id}
                type="button"
                title={it.sub}
                onClick={() => onToggle(it.id)}
                className={cn("text-left px-2 py-1 rounded-lg border text-[11px] max-w-[280px]",
                  on && !all ? "bg-blue-50 border-blue-300 text-blue-800"
                    : all ? "bg-slate-50 border-slate-200 text-slate-700" : "bg-white border-slate-200 text-slate-400")}
              >
                <span className="block truncate font-medium">{it.label}</span>
                <span className="block truncate text-[10px] opacity-70">{it.sub}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, sub, tone = "plain" }: { label: string; value: string; sub?: string; tone?: "plain" | "amber" }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className={cn("text-sm font-bold tabular-nums", tone === "amber" ? "text-amber-700" : "text-slate-800")}>{value}</p>
      {sub && <p className="text-[10px] text-slate-400">{sub}</p>}
    </div>
  );
}
